"""设定一致性扫描 = 章脉派生(轻 LLM)。ADR-010 出路 B 的一个视图。

**为什么改章脉派生**:矛盾天生**跨章**——第 5 章说左撇子、第 80 章用右手,要同时看见两章
才发现。老实现 ``generate_consistency_scan`` 把整本一次进 context,三国 73 万字已可能截断、
几百万字网文必截,"扫全书"打折——截掉的那半本里的矛盾根本看不见。

做法:从章脉收**全书逐章人物处境(char_states)+ 主张(claims,理论书)+ 事件流(events)**当
紧凑清单(每章一句句话,不发原文),**一次 LLM 调用**让模型在这份全书摘要里找前后打架的两章。
章脉是"整本压缩成能进 context 的结构",一次看全书既不像老版大书截断、又跨得了章。

**证据怎么来**:每条矛盾锚到章脉里**真有那条状态/主张的章**,两处原文取那两章章脉已核验过的
evidence(章级锚,贴 ADR-010 出路 B——证据点开现取精确句,这里先给章级证据)。章号、章存在
都校过(防 LLM 编章号);两章必须不同(同章不叫前后矛盾)。

**命根子(沿 exp-011 双向守卫)**:既要找得到真矛盾,又**绝不编**书里没有的矛盾。prompt 明列
"不算矛盾"的三种(号称/实有、不同史料、视角/时间变化);锚不到真实章 / 两章相同 → 丢。解析不
出 / 调用抛 → 返 None,端点照走。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from bookscope.agent._internal.llm_cache import invoke_client_cached
from bookscope.agent.chapter_spine_evidence import find_supporting_sentences
from bookscope.agent.utils.json_parsing import (
    extract_first_json_object,
    salvage_closed_objects,
    strip_code_fence,
)

logger = logging.getLogger(__name__)

DEFAULT_SCAN_MAX_TOKENS = 24000
"""矛盾条数 ∝ 全书可疑点,加 reasoning 头,给足防截断。

deepseek-v4-flash 是 reasoning 模型,reasoning_content 算进 max_tokens(见
[[reference_reasoning_model_token_budget]])。同伏笔派生:一次全书清单输入大、reasoning 长,
给 24000 覆盖三国 + 余量;更大的书超了靠 ``_parse_scan`` 截断抢救兜底。"""

_MAX_STATES_PER_CH = 6   # 每章人物处境取前几条,够定位又不撑爆 input
_MAX_CLAIMS_PER_CH = 4   # 理论书每章主张取前几条
_MAX_EVENTS_PER_CH = 3   # 每章事件取前几条当线索

_SCAN_INSTR = (
    "下面 chapters 是一本书逐章的紧凑摘要:states 是这章主要人物的处境、claims 是这章提出的"
    "主张、events 是这章主要事件。\n"
    "请在这份全书摘要里找出**真正的前后矛盾**——同一个设定 / 人物 / 事实,在不同章节前后说法"
    "打架(如第 5 章说某人是左撇子、第 80 章用右手)。\n"
    "**只列真矛盾,宁缺毋滥。** 以下都【不算】矛盾,绝不要列:\n"
    "① 同一事物的不同口径(如『实有十五万、对外号称二十万』——这是自洽的);\n"
    "② 不同史料 / 来源给的不同数字(作者并列引用多方记载,不是自相矛盾);\n"
    "③ 不同视角 / 不同时间点的合理变化(人物成长、立场随事件演变)。\n"
    "- 两处必须在**不同章**(同章不叫前后矛盾)。\n"
    "- 只依据给出的摘要,别编摘要里没有的矛盾。错报一条比漏报一条更糟。\n"
    "topic 写矛盾涉及的设定 / 人物;conflict 用一句话说矛盾在哪。\n"
    "严格输出 JSON(别的话别说、别加 markdown 围栏):\n"
    '{"contradictions":[{"topic":"涉及的设定","conflict":"一句话说矛盾在哪",'
    '"a_chapter":前一处章号整数,"b_chapter":后一处章号整数}]}'
)


def _collect_inventory(
    spine: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], set[int], dict[int, str]]:
    """从章脉收 逐章摘要清单 + 章集 + 章号→已核验证据。

    每章摘出 states(人物处境)/claims(主张)/events(事件),拼成一句话级别的紧凑清单当输入;
    原文证据不进输入(只在出结果时按章号取章脉那章已核验的 evidence)。

    返回 (chapters_digest, 全部章集, 章号→evidence)。
    """
    digest: list[dict[str, Any]] = []
    all_chs: set[int] = set()
    evidence: dict[int, str] = {}
    for rec in spine:
        if not isinstance(rec, dict):
            continue
        ch = rec.get("chapter")
        if not isinstance(ch, int):
            continue
        all_chs.add(ch)
        evidence[ch] = str(rec.get("evidence", "")).strip()

        states: list[str] = []
        cs = rec.get("char_states")
        if isinstance(cs, list):
            for s in cs[:_MAX_STATES_PER_CH]:
                if isinstance(s, dict):
                    name = str(s.get("name", "")).strip()
                    state = str(s.get("state", "")).strip()
                    if name and state:
                        states.append(f"{name}:{state}")
                    elif state:
                        states.append(state)

        claims: list[str] = []
        cl = rec.get("claims")
        if isinstance(cl, list):
            claims = [str(c).strip() for c in cl[:_MAX_CLAIMS_PER_CH] if str(c).strip()]

        events: list[str] = []
        ev = rec.get("events")
        if isinstance(ev, list):
            events = [
                str(e.get("event", e) if isinstance(e, dict) else e).strip()
                for e in ev[:_MAX_EVENTS_PER_CH]
            ]
            events = [e for e in events if e]

        entry: dict[str, Any] = {"章": ch}
        if states:
            entry["states"] = states
        if claims:
            entry["claims"] = claims
        if events:
            entry["events"] = events
        digest.append(entry)
    return digest, all_chs, evidence


def _chapter_text_map(chunks: list[dict[str, Any]]) -> dict[int, str]:
    """章号 → 该章全部 chunk 原文拼接。给每条矛盾按"这条矛盾的关键词"在各自章原文里捞证据用。

    同 ``chapter_spine_relationship._chapter_text_map``,各 viz 现捞证据共用的章原文表。
    """
    by_ch: dict[int, list[str]] = {}
    for c in chunks:
        ch = c.get("chapter")
        txt = str(c.get("text", ""))
        if isinstance(ch, int) and txt:
            by_ch.setdefault(ch, []).append(txt)
    return {ch: "\n".join(parts) for ch, parts in by_ch.items()}


def _conflict_terms(topic: str, conflict: str) -> list[str]:
    """把"这条矛盾"拆成检索词:topic(涉及的设定/人物,整词)+ conflict 拆 2-gram。

    topic 多是实体名/设定名(如"安禄山惯用手"),字面常原样出现在原文,当主检索词;conflict 是模型
    概括过的一句话(如"前说左撇子后用右手"),整句当不了子串,拆 2-gram 衡量"哪句最像在讲这件事"
    (中文没空格切词,同 ``evidence_for_event`` 思路)。两者合一组词,命中越多的句越像这条矛盾。
    """
    terms: list[str] = []
    t = (topic or "").strip()
    if t:
        terms.append(t)
    c = re.sub(r"\s+", "", conflict or "")
    terms.extend({c[i : i + 2] for i in range(len(c) - 1)})
    return terms


def _scan_snippet(chapter_text: str, topic: str, conflict: str) -> str:
    """一条矛盾的某一处 snippet:在那章原文里按 topic/conflict 关键词现捞最相关那句。

    捞到 → 那句;捞不到(这条矛盾在那章原文里找不到支撑句)→ 空串,交给下游"任一空就丢"守卫
    拦掉这条(不 cry wolf:在原文里坐实不了的矛盾不出)。绝不退回章代表句——那只代表这章最显眼
    的事、未必关乎这条矛盾,正是病二的张冠李戴。
    """
    hits = find_supporting_sentences(chapter_text, _conflict_terms(topic, conflict), 1)
    return hits[0] if hits else ""


def _parse_scan(text: str) -> list[dict[str, Any]] | None:
    """解析 ``{"contradictions":[...]}``;三层兜底(直解析 / 切首个对象 / 截断抢救)。

    空数组(自洽书)是合法结果返 ``[]``;彻底解析不出返 ``None``。
    """
    raw = (text or "").strip()
    if not raw:
        return None
    candidate = strip_code_fence(raw)
    obj: Any = None
    try:
        obj = json.loads(candidate)
    except json.JSONDecodeError:
        sliced = extract_first_json_object(candidate)
        if sliced is not None:
            try:
                obj = json.loads(sliced)
            except json.JSONDecodeError:
                obj = None
    if isinstance(obj, dict) and isinstance(obj.get("contradictions"), list):
        return obj["contradictions"]
    salvaged = salvage_closed_objects(candidate, '"contradictions"')
    if salvaged:
        logger.warning(
            "chapter_spine_consistency: 主解析失败,从截断抢救到 %d 条矛盾", len(salvaged)
        )
        return salvaged
    return None


def consistency_scan_from_spine(
    *,
    spine: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    chunks: list[dict[str, Any]] | None = None,
    max_tokens: int = DEFAULT_SCAN_MAX_TOKENS,
    cache_enabled: bool = True,
) -> list[dict[str, Any]] | None:
    """章脉全书摘要一次 LLM 找前后矛盾 → 矛盾 list。失败返 ``None``,自洽书返 ``[]``。

    矛盾形态同 ``generate_consistency_scan``:
    ``{topic, conflict, a:{snippet, chapter, verified}, b:{snippet, chapter, verified}}``。
    两处章号必须都是章脉真实章且互不相同(防 LLM 编),按 topic 去重。

    **证据怎么来(治病二·证据张冠李戴)**:传了 ``chunks``(全书原文)时,a/b 两处 snippet 各自按
    "这条矛盾的 topic/conflict 关键词"在**各自章原文**里现捞最相关那句(``_scan_snippet``),
    不再统一挂"那章最显眼的代表句"。``chunks=None`` 时保持旧行为——两处 snippet 取那两章章脉已
    核验的代表句(向后兼容,端点接线由主 Claude 统一加 ``chunks=``)。

    两种模式都走"a_snip / b_snip 任一空就丢这条矛盾"守卫:旧行为下防的是"章脉那章没留证据",
    现捞模式下防的是"这条矛盾在那章原文捞不到支撑句"(不 cry wolf)。
    """
    digest, all_chs, evidence = _collect_inventory(spine)
    if not all_chs:
        return None

    chapter_text = _chapter_text_map(chunks) if chunks else {}

    user_content = json.dumps({"chapters": digest}, ensure_ascii=False)
    try:
        resp = invoke_client_cached(
            llm_client,
            model=model,
            system=_SCAN_INSTR,
            tools=[],
            messages=[{"role": "user", "content": user_content}],
            max_tokens=max_tokens,
            cache_enabled=cache_enabled,
        )
        text = llm_client.extract_final_text(resp)
    except Exception as exc:  # noqa: BLE001 — 调用失败降级返 None,不 break 端点
        logger.warning(
            "chapter_spine_consistency: 扫描调用抛 %s: %s;返 None", type(exc).__name__, exc
        )
        return None

    parsed = _parse_scan(text)
    if parsed is None:
        return None

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for c in parsed:
        if not isinstance(c, dict):
            continue
        a_ch = c.get("a_chapter")
        b_ch = c.get("b_chapter")
        # 锚到真实章 + 两章不同(防 LLM 编章号 / 把同章当前后矛盾)
        if not (isinstance(a_ch, int) and isinstance(b_ch, int)):
            continue
        if a_ch == b_ch or a_ch not in all_chs or b_ch not in all_chs:
            continue
        topic = str(c.get("topic", "")).strip()
        conflict = str(c.get("conflict", "")).strip()
        key = topic or conflict
        if not key or key in seen:
            continue
        if chunks:
            # 现捞:按这条矛盾的关键词在各自章原文里找支撑句(治病二,见 docstring)
            a_snip = _scan_snippet(chapter_text.get(a_ch, ""), topic, conflict)
            b_snip = _scan_snippet(chapter_text.get(b_ch, ""), topic, conflict)
        else:
            # 旧行为:章脉那章已核验的代表句(向后兼容)
            a_snip = evidence.get(a_ch, "")
            b_snip = evidence.get(b_ch, "")
        if not a_snip or not b_snip:
            continue  # 没证据不输出:旧行为=章脉那章没证据,现捞=这条矛盾捞不到支撑句
        seen.add(key)
        out.append({
            "topic": topic,
            "conflict": conflict,
            "a": {"snippet": a_snip, "chapter": a_ch, "verified": True},
            "b": {"snippet": b_snip, "chapter": b_ch, "verified": True},
        })
    out.sort(key=lambda x: (x["a"]["chapter"], x["b"]["chapter"]))
    return out  # 可空(自洽书 / 候选全被守卫滤掉)


__all__ = ["DEFAULT_SCAN_MAX_TOKENS", "consistency_scan_from_spine"]
