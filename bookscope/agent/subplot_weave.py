"""支线编织图：整本进 context、抽"情节支线 + 逐章活跃 + 支线交汇"结构化 JSON。

设计：WP-subplot-weave。

probe GO（伪支线/伪交汇假阳性 0%，两轮复现）：agent 能从长文本切出"读者直觉认得出"
的情节支线、可靠判定逐章活跃与交汇，且不把零散提及硬编成支线、不瞎报交汇。本模块把它从
单段 probe 做成整本抽取的生产实现——给前端画 braided narrative（每条支线一条横向泳道、
活跃段亮、休眠段灰、两线同章交汇画连接节点）。

结构同 :func:`bookscope.agent.character_flow.generate_character_flow`，差别两处：

1. **出"支线 + 交汇"两组**——``{"subplots": [{name, active_chapters:[int], evidence}],
   "intersections": [{subplots:[name,name], chapter, a_evidence, b_evidence}]}``，分析单位
   从"角色同场"上抬到"情节支线"。
2. **双命根子证据**——支线活跃挂一条该支线推进的原文过 :func:`verify_citations`（挂不上
   的活跃章丢掉，宁可少画一段活跃也不编）；交汇挂**两条**原文，**两端都核验命中才画交汇
   节点**（同 :func:`bookscope.agent.consistency_scan` 的双端守卫——交汇是这张图最容易编的
   部分，一条腿站不住的交汇绝不画）。

整本书结构化功能模式三可靠性守卫照搬：够 max_tokens 防 reasoning 吃 token 截断、
``cache_enabled=False`` 防坏响应被 poison、解析失败重试一次 + 截断抢救。契约同
``generate_character_flow``：成功返 ``{"subplots": [...], "intersections": [...]}``，
**任意环节失败返 None**。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from bookscope.agent._internal.llm_cache import invoke_client_cached as _invoke_client
from bookscope.agent.citation_check import verify_citations
from bookscope.agent.utils.json_parsing import (
    extract_first_json_object as _extract_first_json_object,
)
from bookscope.agent.utils.json_parsing import (
    strip_code_fence as _strip_code_fence,
)

logger = logging.getLogger(__name__)

DEFAULT_WEAVE_MAX_TOKENS = 8000
"""支线 + 逐章活跃 + 交汇双端证据一大就长——给 8000 留 reasoning 头，防截断/空（同关系图）。"""

_MAX_ATTEMPTS = 2

_SYSTEM_INSTRUCTION = (
    "你是严谨的长文本分析助手。下面 === 全书原文 === 之后是一整本书的完整原文。"
    "请梳理这本书的**情节支线编织结构**——有哪几条情节支线、每条在哪些章活跃、"
    "哪些章两条支线交汇。\n"
    "一条**支线** = 一组围绕共同目标/冲突/人物群、有起有止地推进的事件序列"
    "（主线是贯穿全书最粗的那条，支线时起时落）。\n"
    "**命根子（务必守住）：**\n"
    "① 只把真正成一条线的事件序列算作支线。书里零散、互不相干的次要提及，"
    "**不要硬凑成一条贯穿的支线**——宁可少切几条，不可把碎事编成支线。\n"
    "② 只在两条支线**真的交汇**时才报交汇——同一场景里碰头、互相因果影响、人物跨线流动。"
    "两条各自独立推进、人物不重叠的支线，**不要为了凑数编一个不存在的交汇点**。\n"
    "只依据原文，不臆测、不编造。\n"
    "严格输出 JSON（不要别的话、不要 markdown 代码围栏）：\n"
    '{"subplots": [{"name": "支线名（一句话概括这条线）", '
    '"active_chapters": [这条支线有推进的章号整数，从小到大], '
    '"evidence": "证明这条支线存在的原文逐字片段，原样摘录不改写"}], '
    '"intersections": [{"subplots": ["支线A名", "支线B名"], "chapter": 交汇章号整数, '
    '"a_evidence": "证明这章支线A在场推进的原文逐字片段", '
    '"b_evidence": "证明这章支线B在场推进的原文逐字片段"}]}\n'
    "subplots 列全书主要支线（含主线，最多约 10 条），每条 active_chapters 列它活跃的章号；"
    "intersections 只列真交汇，两条 a_evidence / b_evidence 都必须是原文里逐字出现的句子，"
    "分别证明这一章两条支线都在场且发生勾连。"
    "subplots 里的 name 要和 intersections 里引用的支线名一致。"
    "宁可少而准，不必穷尽。"
)

_BOOK_DELIMITER = "\n\n=== 全书原文 ===\n"


def _coerce_subplot(item: Any) -> dict[str, Any] | None:
    """把一条支线 dict 归一成 ``{name, active_chapters:list[int], evidence}``。

    name 缺/空 → 丢（没名字的泳道没法画）；active_chapters 归一成去重升序整数 list；
    evidence 可缺（缺则后续 verified 自然 False）。
    """
    if not isinstance(item, dict):
        return None
    name = str(item.get("name", "")).strip()
    if not name:
        return None

    active: list[int] = []
    seen: set[int] = set()
    raw = item.get("active_chapters")
    if isinstance(raw, list):
        for ch in raw:
            if isinstance(ch, bool):  # bool 是 int 子类，单独挡掉
                continue
            if isinstance(ch, int) and ch not in seen:
                seen.add(ch)
                active.append(ch)
    active.sort()

    return {
        "name": name,
        "active_chapters": active,
        "evidence": str(item.get("evidence", "")).strip(),
    }


def _coerce_subplots(raw: Any) -> list[dict[str, Any]]:
    """保留 name 齐全的支线；按 name 去重（先到先得）。"""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        sp = _coerce_subplot(item)
        if sp is None or sp["name"] in seen:
            continue
        seen.add(sp["name"])
        out.append(sp)
    return out


def _coerce_intersection(item: Any) -> dict[str, Any] | None:
    """把一条交汇 dict 归一成 ``{subplots:[a,b], chapter:int, a_evidence, b_evidence}``。

    subplots 必须是两个不同的非空支线名；chapter 必须是整数；两条 evidence 都要有
    （缺任一则这条交汇不成立——双端守卫的前提）。
    """
    if not isinstance(item, dict):
        return None
    raw_sp = item.get("subplots")
    if not isinstance(raw_sp, list) or len(raw_sp) < 2:
        return None
    a_name = str(raw_sp[0]).strip()
    b_name = str(raw_sp[1]).strip()
    if not a_name or not b_name or a_name == b_name:
        return None
    ch = item.get("chapter")
    if isinstance(ch, bool) or not isinstance(ch, int):
        return None
    a_ev = str(item.get("a_evidence", "")).strip()
    b_ev = str(item.get("b_evidence", "")).strip()
    if not a_ev or not b_ev:
        return None
    return {
        "subplots": [a_name, b_name],
        "chapter": ch,
        "a_evidence": a_ev,
        "b_evidence": b_ev,
    }


def _coerce_intersections(raw: Any) -> list[dict[str, Any]]:
    """保留两端证据齐全的交汇；按 (支线对, 章号) 去重。"""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    for item in raw:
        it = _coerce_intersection(item)
        if it is None:
            continue
        key = (tuple(sorted(it["subplots"])), it["chapter"])
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def _build_weave(obj: Any) -> dict[str, Any] | None:
    """从解析出的对象组装 ``{subplots, intersections}``；没有任何支线则返 None。"""
    if not isinstance(obj, dict):
        return None
    subplots = _coerce_subplots(obj.get("subplots"))
    if not subplots:
        return None  # 没支线的编织图没意义
    intersections = _coerce_intersections(obj.get("intersections"))
    return {"subplots": subplots, "intersections": intersections}


def _salvage_truncated(text: str) -> dict[str, Any] | None:
    """从截断的 JSON 里抢救已吐完的支线数组。

    flash 把 reasoning_content 算进 max_tokens，支线 + 双端证据一大就可能被截断成半截
    JSON，整段 ``json.loads`` 必败。``subplots`` 通常排在 ``intersections`` 前，截断多半
    丢的是后半段交汇——优先抠出已闭合的 ``subplots`` 对象，至少把泳道画出来（同关系图/
    叙事流截断抢救思路）。交汇若也截断就当空，不强抢半截交汇。
    """
    subplots = _salvage_array(text, '"subplots"')
    if not subplots:
        return None
    intersections = _salvage_array(text, '"intersections"') or []
    return _build_weave({"subplots": subplots, "intersections": intersections})


def _salvage_array(text: str, key: str) -> list[Any] | None:
    """从 ``text`` 里抠出 ``key`` 对应数组里已经闭合的 ``{...}`` 对象（截断抢救通用件）。"""
    idx = text.find(key)
    if idx == -1:
        return None
    start = text.find("[", idx)
    if start == -1:
        return None
    raw_items: list[Any] = []
    i = start + 1
    n = len(text)
    while i < n:
        while i < n and text[i] not in "{]":  # 跳到下一个对象起点；遇 ] 收工
            i += 1
        if i >= n or text[i] == "]":
            break
        depth = 0
        in_str = False
        esc = False
        closed = False
        j = i
        while j < n:  # 括号匹配抠一个完整 {...}，跳过字符串内的括号
            ch = text[j]
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = not in_str
            elif not in_str:
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        j += 1
                        closed = True
                        break
            j += 1
        if not closed:
            break  # 最后一个对象被截断 → 停
        try:
            raw_items.append(json.loads(text[i:j]))
        except json.JSONDecodeError:
            pass
        i = j
    return raw_items or None


def _parse_weave(text: str) -> dict[str, Any] | None:
    """解析模型输出的编织图 JSON。正常失败 → 抢救截断的支线 → 仍不行返 None。"""
    raw = (text or "").strip()
    if not raw:
        return None
    candidate = _strip_code_fence(raw)
    obj: Any = None
    try:
        obj = json.loads(candidate)
    except json.JSONDecodeError:
        sliced = _extract_first_json_object(candidate)
        if sliced is not None:
            try:
                obj = json.loads(sliced)
            except json.JSONDecodeError:
                obj = None
    weave = _build_weave(obj)
    if weave is not None:
        return weave
    salvaged = _salvage_truncated(candidate)
    if salvaged is not None:
        logger.warning(
            "subplot_weave: 主解析失败，从截断输出抢救到 %d 条支线",
            len(salvaged["subplots"]),
        )
        return salvaged
    logger.warning("subplot_weave parse failed; raw head=%r", candidate[:200])
    return None


def _verify_one(
    snippet: str, evidence: dict[str, dict], self_chapter: object = None
) -> dict[str, Any]:
    """核验一条原文片段：命中 → verified + 命中 chunk 的真章号；返附加字段 dict。

    ``self_chapter`` 是这条引用的 LLM 自报章号，当多命中消歧弱先验（真章号在 verify
    后仍用 chunk_id 覆盖）；缺/非正整数时不传，退回确定性首个。
    """
    cit: dict[str, Any] = {"snippet": snippet}
    if isinstance(self_chapter, int) and self_chapter > 0:
        cit["chapter"] = self_chapter
    cits = [cit]
    verify_citations(cits, evidence)
    vc = cits[0]
    cid = vc.get("chunk_id")
    true_ch = evidence.get(cid, {}).get("chapter") if cid else None
    return {
        "verified": bool(vc.get("verified", False)),
        "match_score": vc.get("match_score", 0.0),
        "true_chapter": true_ch if isinstance(true_ch, int) and true_ch > 0 else None,
    }


def _verify_subplots(
    subplots: list[dict[str, Any]], evidence: dict[str, dict]
) -> None:
    """每条支线的 evidence 过 verify_citations（原地附加 verified / match_score）。

    支线整体的 evidence 核不过 → ``verified=False``（FE 整条泳道淡化），但泳道仍画——
    支线判定是主观构念，描述性的存在判定留给读者自己核（同 character_voice features）。
    活跃段细到逐章的证据本模块不逐章挂（一条支线一条代表 evidence 即可，避免输出爆炸），
    活跃/休眠靠 active_chapters 画。
    """
    for sp in subplots:
        v = _verify_one(sp["evidence"], evidence)
        sp["verified"] = v["verified"]
        sp["match_score"] = v["match_score"]


def _verify_intersections(
    intersections: list[dict[str, Any]], evidence: dict[str, dict]
) -> list[dict[str, Any]]:
    """双端守卫：交汇的两条 evidence 都核验命中才保留（编的交汇过不了）。

    同 consistency_scan：一条腿站不住的交汇绝不画。命中后用真章号纠偏（不信模型自报）。
    返回过滤后的交汇列表，每条附加 a_verified / b_verified / 两侧 match_score。
    """
    kept: list[dict[str, Any]] = []
    for it in intersections:
        # 交汇两端 evidence 同属这条交汇的自报章号，两腿都带上当消歧弱先验。
        va = _verify_one(it["a_evidence"], evidence, it.get("chapter"))
        vb = _verify_one(it["b_evidence"], evidence, it.get("chapter"))
        if not (va["verified"] and vb["verified"]):
            continue  # 双端守卫：任一端没命中 → 不画这个交汇
        it["a_verified"] = True
        it["b_verified"] = True
        it["a_match_score"] = va["match_score"]
        it["b_match_score"] = vb["match_score"]
        # 两端命中章号一般同章；取 a 端真章号纠偏模型自报的 chapter
        if va["true_chapter"] is not None:
            it["chapter"] = va["true_chapter"]
        kept.append(it)
    kept.sort(key=lambda x: x["chapter"])
    return kept


def generate_subplot_weave(
    *,
    full_text: str,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    max_tokens: int = DEFAULT_WEAVE_MAX_TOKENS,
    session_id: str | None = None,
) -> dict[str, Any] | None:
    """整本进 context 抽支线编织结构 + 双命根子证据核验；失败返 ``None``。

    Args:
        full_text: 整本书 cleaned 原文。
        chunks: 全书 chunk dict（含 ``chunk_id`` / ``chapter`` / ``text``），给支线 /
            交汇 evidence 做证据登记表 + 提供章号 ground truth。
        llm_client: duck-typed LLM client（同 AgentLoop / character_flow）。
        model: 模型名。
        max_tokens: 单次 LLM 调用 max_tokens（默认 8000，支线 + 双端证据长）。
        session_id: 仅签名兼容——本任务关缓存（防坏响应被 poison）。

    Returns:
        ``{"subplots": [{name, active_chapters:[int], evidence, verified, match_score}],
        "intersections": [{subplots:[name,name], chapter, a_evidence, b_evidence,
        a_verified, b_verified, a_match_score, b_match_score}]}``；交汇已双端 verify-filter
        （挂不上原文的不画）；任意失败返 ``None``。
    """
    _ = session_id  # 关缓存：本任务出结构化 JSON，坏响应不该被缓存 poison
    evidence = {
        str(c["chunk_id"]): {"chapter": c.get("chapter", 0), "text": c.get("text", "")}
        for c in chunks
        if c.get("chunk_id")
    }
    system = _SYSTEM_INSTRUCTION + _BOOK_DELIMITER + full_text
    messages = [{"role": "user", "content": "请抽这本书的情节支线编织结构。"}]
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            response = _invoke_client(
                llm_client,
                model=model,
                system=system,
                tools=[],
                messages=messages,
                max_tokens=max_tokens,
                cache_enabled=False,
            )
        except Exception as exc:  # noqa: BLE001 — 包死，重试 / 返 None
            logger.warning(
                "subplot_weave LLM call raised %s: %s (attempt %d)",
                type(exc).__name__, exc, attempt,
            )
            continue
        weave = _parse_weave(llm_client.extract_final_text(response))
        if weave is not None:
            _verify_subplots(weave["subplots"], evidence)
            weave["intersections"] = _verify_intersections(
                weave["intersections"], evidence
            )
            return weave
        logger.warning(
            "subplot_weave parse failed (attempt %d/%d)", attempt, _MAX_ATTEMPTS
        )
    return None


__all__ = ["DEFAULT_WEAVE_MAX_TOKENS", "generate_subplot_weave"]
