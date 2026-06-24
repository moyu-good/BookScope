"""声口一致：给一个角色，整本进 context 归拢他的对白、刻画语言特征、标出"这句不像他说的"。

设计：WP-character-voice（probe GO：判别成立、三类对抗假阳性 0%）。

作家写长篇最容易翻车的地方之一——第 5 章那个粗豪武夫，到第 80 章嘴里冒出文绉绉的排比。
读者说不清哪不对，只觉得"出戏"。这件事把这种违和落成可定位、挂着原文的一条条提示。

和「人物弧线」不是一回事：弧线管动机/性格转变合不合理，声口管说话腔调一不一致。一个人物
可以性格没变而口吻飘了（作者手滑），也可以性格大变而口吻该跟着变（合理，不该报）。所以
这件事的命根子全在"别把合理的口吻变化判成 drift"。

复用 [[project_wholebook_feature_pattern]]：长上下文整本进 context + 结构化 JSON +
三守卫（够 token / 关缓存 / 重试 + 截断抢救）。每个特征、每条 drift 判定挂原文过
verify_citations。两种证据处理不同（设计 §4）：

1. **语言特征（features）**——保留全部，verified=false 的留着标低置信（前端淡化），
   evidence-first 但不剔（特征是描述性的，读者点开自己核）。
2. **drift 提示（drift_items）**——verify-filter：核不过的整条丢（同 study_cards），
   挂不上原文的 drift 是 agent 一面之词，不报。

命根子（probe 守住的，写进 prompt）：合理的剧情驱动口吻变化别报 drift、样本不足明说
不硬判、不把别人的话算到他头上。

契约：成功返 ``{features, drift_items}`` dict，**任意环节失败返 None**；角色对白太少
返 ``{features: [], drift_items: [], sample_too_small: True}``（合法，不是失败）。

**喂什么文本（ADR-010 跨章采样修，1.x）**：声口要的是这个角色逐字对白，章脉只有处境描述
没对白，派生不了——所以不改章脉派生，改**跨章采样**。给了 ``spine`` 就用章脉的 ``present``
（每章在场人物）定位这个角色出场的章，只把这些章的原文（从 chunks 取）拼进 context。
好处：① 只喂相关章 → 几百万字的书也不截断（老的整本进 context 三国 73 万字已可能截断）；
② 喂的是该角色真出场的章的真原文（含对白），不掺没他的章。没给 spine 退回整本（向后兼容、
小书照旧）。分析逻辑和输出形态一字不改，换的只是「喂什么」。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from bookscope.agent._internal.llm_cache import invoke_client_cached as _invoke_client
from bookscope.agent._internal.longctx_system import build_longctx_system
from bookscope.agent.citation_check import build_evidence_map, verify_citations
from bookscope.agent.utils.json_parsing import (
    extract_first_json_object as _extract_first_json_object,
)
from bookscope.agent.utils.json_parsing import (
    salvage_closed_objects,
)
from bookscope.agent.utils.json_parsing import (
    strip_code_fence as _strip_code_fence,
)

logger = logging.getLogger(__name__)

DEFAULT_VOICE_MAX_TOKENS = 8000
"""特征（每条挂代表对白）+ 多条 drift（每条挂原文 + 一句为什么）比单点判断长——给 8000
留 reasoning 头，防截断/空（同关系图/弧线/叙事流）。"""

_MAX_ATTEMPTS = 2
_MAX_FEATURES = 12
_MAX_DRIFT = 20

DEFAULT_VOICE_SAMPLE_CHAR_BUDGET = 200_000
"""跨章采样后喂进 context 的字符上限（约 136k token，远低于长上下文 600k 上限）。

声口只看一个角色出场的章——大书里他出场可能也几百章（三国刘备出场上百回）。出场章太多
就按「戏份重」（角色名在该章原文出现次数）排序，取够 budget 的前若干章。给 20 万字是因为
单角色出场章拼起来通常远小于整本，留足头给 system prompt + 8000 输出，几百万字的书也不会
把这段撑爆。"""

_SYSTEM_INSTRUCTION = (
    "你是 BookScope 的声口分析助手。"
    "用户会给一个角色。请只根据这本书的原文，做两件事：\n"
    "一、把这个角色全书的对白归拢起来，刻画他说话的腔调，列出几条语言特征"
    "（口头禅、句式长短、文白程度、用词偏好、语气）。每条特征挂 1 句最能代表"
    "这条腔调的原文对白当依据。\n"
    "二、标出哪几句对白「不像他说的」（声口飘了）。每条挂上那句对白的原文 + "
    "所在章 + 一句话说明为什么觉得不像。\n"
    "三条铁律（违反就是冤枉好句子，宁可少报也别犯）：\n"
    "1. 角色在剧情里确实有理由换腔调（受了刺激变冷峻、地位变了说话端着、装扮成"
    "别人），这是合理的剧情驱动变化，**不算 drift，不要报**。只报那种没来由、"
    "像作者手滑写串了的违和。\n"
    "2. 这个角色全书对白很少、样本不够刻画稳定腔调时，**明说样本不足，不硬下 "
    "drift 判定**——把 sample_too_small 标 true，features 和 drift 给空或极少。\n"
    "3. 只算这个角色自己说的话。**别的角色说的话不要算到他头上**，更不要因为某句"
    "有特色就硬说成是他说的。\n"
    "只依据原文，不臆测、不编造。snippet 必须是原文里这个角色逐字说过的对白。\n"
    "严格输出 JSON（不要别的话、不要 markdown 代码围栏）：\n"
    '{"sample_too_small": false, '
    '"features": [{"trait": "这条语言特征", "evidence": "代表这条腔调的原文对白逐字片段"}], '
    '"drift_items": [{"chapter": 章号整数, "quote": "那句不像他说的对白原文逐字片段", '
    '"reason": "为什么觉得不像他说的"}]}\n'
    "features 最多约 6 条、宁可少而准；drift 默认从严，没把握的不报、空数组也没关系。"
)


def _coerce_features(raw: Any) -> list[dict[str, Any]]:
    """收编语言特征。trait 缺/空 → 丢（没特征名画不出卡）；evidence 可缺（缺则核不过、
    标低置信）。"""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        trait = str(item.get("trait", "")).strip()
        if not trait:
            continue
        out.append(
            {"trait": trait, "evidence": str(item.get("evidence", "")).strip()}
        )
        if len(out) >= _MAX_FEATURES:
            break
    return out


def _coerce_drift(raw: Any) -> list[dict[str, Any]]:
    """收编 drift 提示。quote 缺/空 → 丢（drift 没原文对白没法核也没法摆）；chapter
    非整数退 0、reason 可缺。"""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        quote = str(item.get("quote", "")).strip()
        if not quote:
            continue
        ch = item.get("chapter")
        out.append(
            {
                "chapter": ch if isinstance(ch, int) else 0,
                "quote": quote,
                "reason": str(item.get("reason", "")).strip(),
            }
        )
        if len(out) >= _MAX_DRIFT:
            break
    return out


def _coerce(raw: Any) -> dict[str, Any] | None:
    """结构合法（dict 含 features / drift_items 任一为列表）→ 收编后的
    ``{sample_too_small, features, drift_items}``；结构非法 → ``None``（触发抢救/重试）。

    features 与 drift_items 都空、且 sample_too_small 不为 true 时也算合法结果（书里这个
    角色声口很稳、没扫出 drift），不返 None。"""
    if not isinstance(raw, dict):
        return None
    has_features = isinstance(raw.get("features"), list)
    has_drift = isinstance(raw.get("drift_items"), list)
    if not has_features and not has_drift:
        return None
    return {
        "sample_too_small": bool(raw.get("sample_too_small", False)),
        "features": _coerce_features(raw.get("features")),
        "drift_items": _coerce_drift(raw.get("drift_items")),
    }


def _salvage_truncated(text: str) -> dict[str, Any] | None:
    """从截断的 JSON 里把 ``features`` / ``drift_items`` 两个数组里已闭合的完整对象抠出来。

    特征 + 多条 drift 一大就可能被截断成半截 JSON（flash 把 reasoning_content 算进
    max_tokens），整段 json.loads 必败。括号匹配逐个抠完整 {...}，拼部分结果比整张丢掉好
    （同 entity_recall / study_cards 抢救）。两个数组任一抢到东西就算有效。
    """
    features = salvage_closed_objects(text, '"features"')
    drift = salvage_closed_objects(text, '"drift_items"')
    if features is None and drift is None:
        return None
    return _coerce(
        {
            "sample_too_small": False,
            "features": features or [],
            "drift_items": drift or [],
        }
    )


def _parse_voice(text: str) -> dict[str, Any] | None:
    """解析模型输出的声口 JSON。正常失败 → 抢救截断的数组 → 仍不行返 None。"""
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
    result = _coerce(obj)
    if result is not None:
        return result
    salvaged = _salvage_truncated(candidate)
    if salvaged is not None:
        logger.warning(
            "character_voice: 主解析失败，从截断输出抢救到 %d 特征 / %d drift",
            len(salvaged["features"]),
            len(salvaged["drift_items"]),
        )
        return salvaged
    logger.warning("character_voice parse failed; raw head=%r", candidate[:200])
    return None


def _verify(result: dict[str, Any], chunks: list[dict[str, Any]]) -> dict[str, Any]:
    """核验两部分证据，处理方式不同（设计 §4）。

    - **features**：保留全部，每条 evidence 过 verify_citations 标 verified + 真章号纠偏
      （核不过的留着、前端标低置信）。无 evidence 的天然 verified=False。
    - **drift_items**：verify-filter——quote 核不过的整条丢（同 study_cards），章号纠偏。
    """
    evidence_map = build_evidence_map(chunks)

    for feat in result["features"]:
        cits = [{"snippet": feat["evidence"]}]
        verify_citations(cits, evidence_map)
        vc = cits[0]
        feat["verified"] = bool(vc.get("verified", False))
        feat["match_score"] = vc.get("match_score", 0.0)
        cid = vc.get("chunk_id")
        true_ch = evidence_map.get(cid, {}).get("chapter") if cid else None
        feat["chapter"] = true_ch if isinstance(true_ch, int) and true_ch > 0 else 0

    kept_drift: list[dict[str, Any]] = []
    for d in result["drift_items"]:
        # 带上 LLM 自报章号当多命中消歧弱先验（真章号在 verify 后用 chunk_id 覆盖）；
        # chapter 为 0 = 模型没报，不传，退回确定性首个。
        self_ch = d.get("chapter")
        cit: dict[str, Any] = {"snippet": d["quote"]}
        if isinstance(self_ch, int) and self_ch > 0:
            cit["chapter"] = self_ch
        cits = [cit]
        verify_citations(cits, evidence_map)
        vc = cits[0]
        if not vc.get("verified"):
            continue  # 挂不上原文的 drift 不报（agent 一面之词）
        cid = vc.get("chunk_id")
        true_ch = evidence_map.get(cid, {}).get("chapter") if cid else None
        if isinstance(true_ch, int) and true_ch > 0:
            d["chapter"] = true_ch  # 命中 chunk 的真章号纠偏，别让作家拿错章号翻稿
        d["verified"] = True
        d["match_score"] = vc.get("match_score", 0.0)
        kept_drift.append(d)
    kept_drift.sort(key=lambda x: x["chapter"])
    result["drift_items"] = kept_drift
    return result


def _character_aliases(character: str, name_map: dict[str, str] | None) -> set[str]:
    """收齐这个角色的所有叫法：自身 + name_map 里归到它名下的别名 + 它的 canonical。

    name_map 是 别名→canonical（``build_spine_name_map`` 出的）。用户查「刘备」，章脉 present
    里可能写「玄德」「先主」——把这些都算成同一个人才定位得全。用户查的名字自己可能也是别名
    （查「玄德」→ canonical 是「刘备」），所以先把它 canon 化，再把同 canonical 的全收进来。
    没 name_map 就只有名字自身（退回精确 + 子串匹配兜底）。
    """
    target = character.strip()
    if not target:
        return set()
    canonical = (name_map or {}).get(target, target)
    aliases = {target, canonical}
    if name_map:
        aliases |= {alias for alias, canon in name_map.items() if canon == canonical}
    return {a for a in aliases if a}


def _is_present(present: Any, aliases: set[str]) -> bool:
    """这一章 present 列表里有没有这个角色（任一叫法）。

    先精确比对（present 里的名字 ∈ 别名集）；再宽松子串兜底（present 写「刘玄德」、查「玄德」，
    或反过来）——章脉 present 是逐章原文称呼，未必跟别名集 byte 对齐。
    """
    if not isinstance(present, list):
        return False
    for name in present:
        if not isinstance(name, str):
            continue
        n = name.strip()
        if not n:
            continue
        if n in aliases:
            return True
        if any(a in n or n in a for a in aliases):
            return True
    return False


def _sample_text_by_spine(
    *,
    aliases: set[str],
    spine: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    char_budget: int,
) -> tuple[str, list[int], int]:
    """用章脉 present 定位角色出场章，只取这些章的原文拼成采样文本。

    返回 ``(sampled_text, kept_chapters, present_chapter_count)``：
    - ``sampled_text``——拼好的采样原文（按章号升序，让模型读到时序）；空串=没定位到。
    - ``kept_chapters``——实际拼进文本的章号（升序）；出场章超预算时是「戏份重」的子集。
    - ``present_chapter_count``——定位到的出场章总数（含没拼进去的），给报告看覆盖。

    戏份重 = 角色名（及别名）在该章原文里出现的次数。出场章太多（大书单角色上百章）就按
    这个排序贪心取到 budget，再按章号升序还原时序。
    """
    if not aliases or not spine:
        return "", [], 0

    # 1. 章脉 present 定位出场章号
    present_chapters: set[int] = set()
    for rec in spine:
        ch = rec.get("chapter")
        if isinstance(ch, int) and _is_present(rec.get("present"), aliases):
            present_chapters.add(ch)
    if not present_chapters:
        return "", [], 0

    # 2. 把这些章的 chunk 原文按章号归拢
    by_chapter: dict[int, list[str]] = {}
    for c in chunks:
        ch = c.get("chapter")
        if isinstance(ch, int) and ch in present_chapters:
            txt = str(c.get("text", ""))
            if txt:
                by_chapter.setdefault(ch, []).append(txt)
    if not by_chapter:
        return "", [], len(present_chapters)

    chapter_text = {ch: "\n".join(parts) for ch, parts in by_chapter.items()}

    # 3. 戏份重排序：角色名 + 别名在该章原文出现次数降序（同分按章号升序，确定性 → 缓存稳）
    def _screen_time(ch: int) -> int:
        body = chapter_text[ch]
        return sum(body.count(a) for a in aliases)

    ranked = sorted(chapter_text, key=lambda ch: (-_screen_time(ch), ch))

    # 4. 贪心取到 budget；再按章号升序还原时序拼接
    kept: list[int] = []
    used = 0
    for ch in ranked:
        body = chapter_text[ch]
        if kept and used + len(body) > char_budget:
            continue  # 超预算的略过（但首章再大也保一章，免得空手）
        kept.append(ch)
        used += len(body)
        if used >= char_budget:
            break
    kept.sort()
    sampled = "\n\n".join(f"【第{ch}章】\n{chapter_text[ch]}" for ch in kept)
    return sampled, kept, len(present_chapters)


def generate_character_voice(
    *,
    character: str,
    full_text: str,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    spine: list[dict[str, Any]] | None = None,
    name_map: dict[str, str] | None = None,
    sample_char_budget: int = DEFAULT_VOICE_SAMPLE_CHAR_BUDGET,
    max_tokens: int = DEFAULT_VOICE_MAX_TOKENS,
    session_id: str | None = None,
) -> dict[str, Any] | None:
    """归拢一个角色的对白、刻画语言特征、标 voice drift；失败返 ``None``。

    Args:
        character: 要分析的角色名（角色列表可复用人物图抽出的节点）。
        full_text: 整本书 cleaned 原文。**没给 spine 时**直接整本进 context（小书照旧、
            向后兼容）；给了 spine 且采到样本就忽略它，改喂跨章采样文本。
        chunks: 全书 chunk dict（含 ``chunk_id`` / ``chapter`` / ``text``），给 evidence
            做证据登记表 + 提供章号 ground truth；也是跨章采样取原文的来源。
        llm_client: duck-typed LLM client（同 AgentLoop / character_arc）。
        model: 模型名。
        spine: 可选章脉（``get_or_build_spine`` 出的逐章 dict）。给了就用它的 ``present``
            字段定位角色出场章、只喂这些章原文（防大书截断）；没给退回整本 full_text。
        name_map: 可选别名→canonical 表（``build_spine_name_map`` 出的），定位角色时合并
            玄德/刘备/先主这类碎裂称呼。没给走精确 + 子串匹配兜底。
        sample_char_budget: 跨章采样文本字符上限（默认 20 万）。出场章超预算按戏份重取前若干。
        max_tokens: 单次 LLM 调用 max_tokens（默认 8000）。
        session_id: 仅签名兼容——本任务关缓存（防坏响应被 poison）。

    Returns:
        ``{"sample_too_small": bool, "features": [{trait, evidence, verified, match_score,
        chapter}], "drift_items": [{chapter, quote, reason, verified, match_score}]}``——
        features 保留全部（含核不过的，标低置信）；drift_items verify-filter（核不过的丢）。
        任意失败 ``None``；角色名为空 ``None``。
    """
    _ = session_id  # 关缓存：本任务出结构化 JSON，坏响应不该被缓存 poison
    character = (character or "").strip()
    if not character:
        return None

    # 喂什么文本：有 spine → 用 present 定位出场章、只喂这些章原文（防大书截断）；
    # 采不到（没 spine / 没定位到出场章 / chunks 取不到原文）退回整本（小书照旧）。
    context_text = full_text
    if spine:
        aliases = _character_aliases(character, name_map)
        sampled, kept_chapters, present_count = _sample_text_by_spine(
            aliases=aliases, spine=spine, chunks=chunks, char_budget=sample_char_budget
        )
        if sampled:
            context_text = sampled
            logger.info(
                "character_voice: 跨章采样「%s」——出场 %d 章，喂 %d 章 / %d 字（整本 %d 字）",
                character, present_count, len(kept_chapters), len(sampled), len(full_text),
            )
        else:
            logger.info(
                "character_voice: 「%s」章脉没定位到出场章，退回整本（%d 字）",
                character, len(full_text),
            )

    system = build_longctx_system(context_text, _SYSTEM_INSTRUCTION)
    messages = [
        {"role": "user", "content": f"请分析角色「{character}」的声口一致性。"}
    ]
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
                "character_voice LLM call raised %s: %s (attempt %d)",
                type(exc).__name__, exc, attempt,
            )
            continue
        result = _parse_voice(llm_client.extract_final_text(response))
        if result is not None:
            return _verify(result, chunks)
        logger.warning(
            "character_voice parse failed (attempt %d/%d)", attempt, _MAX_ATTEMPTS
        )
    return None


__all__ = [
    "DEFAULT_VOICE_MAX_TOKENS",
    "DEFAULT_VOICE_SAMPLE_CHAR_BUDGET",
    "generate_character_voice",
]
