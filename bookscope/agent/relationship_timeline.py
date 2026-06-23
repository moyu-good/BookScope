"""关系随时间演变：整本进 context、逐对主要关系抽"逐章强度 + 关键转折章"结构化 JSON。

设计：WP-relationship-over-time。

probe GO（方向 100% / 转折 100% / 假阳性 0/3）：agent 能逐章可靠判定"这一对角色截至
此章关系有多紧 / 是什么性质"，连成的强度曲线既稳又对，且不顺着诱导编出不存在的转折。
本模块把它从单段 probe 做成整本抽取的生产实现——把人物关系图那张冻住的网加一根时间轴：
每对主要关系一条贯穿全书的强度曲线，关键转折挂得上原文。

结构同 :func:`bookscope.agent.character_flow.generate_character_flow`，差别两处：

1. **出逐对关系的逐章序列**——``{"relations": [{"a", "b", "relation",
   "points": [{"chapter": N, "strength": 0-10}], "turning_points": [{"chapter": N,
   "change": 描述, "evidence": 原文片段}]}]}``，而不是逐章同场结构。
2. **每个转折挂原文证据**——每个 turning_point 的 ``evidence`` 当一条 citation 过
   :func:`verify_citations`：命中某 chunk → ``verified=True`` + 用命中 chunk 的真章号
   纠偏；``verified=False`` 的转折留着但标灰（FE 把核不过的转折标低置信/不画），
   evidence-first（设计 §4：挂不上原文的强度变化不画，宁可平段也不编波动）。

整本书结构化功能模式三可靠性守卫照搬：够 max_tokens 防 reasoning 吃 token 截断、
``cache_enabled=False`` 防坏响应被 poison、解析失败重试一次 + 截断抢救。契约同
``generate_character_flow``：成功返 list[关系 dict]，**任意环节失败返 None**。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from bookscope.agent._internal.exhaustive import merge_keyed_points, run_segments
from bookscope.agent._internal.llm_cache import invoke_client_cached as _invoke_client
from bookscope.agent._internal.longctx_system import build_longctx_system
from bookscope.agent.citation_check import verify_citations
from bookscope.agent.utils.json_parsing import (
    extract_first_json_object as _extract_first_json_object,
)
from bookscope.agent.utils.json_parsing import (
    strip_code_fence as _strip_code_fence,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMELINE_MAX_TOKENS = 8000
"""逐对关系 × 逐章强度序列 + 转折比单张图长——给 8000 留 reasoning 头，防截断/空
（同关系图/叙事流/character-flow）。"""

_MAX_ATTEMPTS = 2

_SYSTEM_INSTRUCTION = (
    "请梳理书里**主要人物关系**随章节怎么变——不是只给一张最终的关系网，"
    "而是每一对重要关系一条贯穿全书的强度曲线，外加关键转折。每对关系给：\n"
    "1. relation（关系性质）：这两人是什么关系（君臣/政敌/父子/同盟/师徒等）。"
    "若全书内性质有变，填最有代表性的那种。\n"
    "2. points（逐章强度）：列若干 {chapter, strength} 点，strength 是这一对截至此章"
    "关系有多紧（0-10 整数，越大越紧密）。只在关系**确实有变化**的章给点——"
    "他们同场越多、互动越关键，强度越高；长期不互动则缓慢回落。"
    "没事件发生的平段不必逐章给点（曲线在那段就是平的）。\n"
    "3. turning_points（关键转折）：列这对关系**真正发生明显变化**的章——初识、"
    "升温、决裂、和解、顶峰等。每个转折给 {chapter, change（一句话说这章他们之间发生了"
    "什么导致关系变化）, evidence（证明这次变化的原文逐字片段，原样摘录不改写）}。\n"
    "只依据原文，不臆测、不编造。**关系全程平稳、没什么大变化的，turning_points 就留空，"
    "绝不为了凑数编一个不存在的拐点；关系明确越来越近的，不要判成越走越远——"
    "方向以原文为准。**\n"
    "严格输出 JSON（不要别的话、不要 markdown 代码围栏）：\n"
    '{"relations": [{"a": "人物A", "b": "人物B", "relation": "关系性质", '
    '"points": [{"chapter": 章号整数, "strength": 0-10整数}], '
    '"turning_points": [{"chapter": 章号整数, "change": "这章发生了什么", '
    '"evidence": "证明这次变化的原文逐字片段"}]}]}\n'
    "只列书里真正重要的几对关系（最多约 12 对），每对的 points 按章号从小到大、"
    "turning_points 按章号从小到大；evidence 是原文里逐字出现的句子。宁可少而准，不必穷尽。"
)


def _clamp_int(value: Any, lo: int, hi: int, default: int) -> int:
    """把模型给的数值钳到 [lo, hi] 整数；非数 / 缺失退 default。"""
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _coerce_points(raw: Any) -> list[dict[str, Any]]:
    """逐章强度点归一成 ``[{chapter:int, strength:0-10}]``；去重同章号、按章号升序。

    chapter 缺/非整数的点丢（没章号摆不到横轴）；strength 钳到 0-10。
    """
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for p in raw:
        if not isinstance(p, dict):
            continue
        ch = p.get("chapter")
        if not isinstance(ch, int) or ch in seen:
            continue
        seen.add(ch)
        out.append({"chapter": ch, "strength": _clamp_int(p.get("strength"), 0, 10, 0)})
    out.sort(key=lambda x: x["chapter"])
    return out


def _coerce_turning_points(raw: Any, fallback_chapter: int) -> list[dict[str, Any]]:
    """转折点归一成 ``[{chapter:int, change:str, evidence:str}]``；按章号升序。

    chapter 缺/非整数的退 fallback_chapter（仍知道大概在哪、不丢这个转折）；
    change / evidence 归一成字符串（evidence 可空，空则后续 verified 自然 False）。
    """
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for tp in raw:
        if not isinstance(tp, dict):
            continue
        ch = tp.get("chapter")
        chapter = ch if isinstance(ch, int) else fallback_chapter
        out.append(
            {
                "chapter": chapter,
                "change": str(tp.get("change", "")).strip(),
                "evidence": str(tp.get("evidence", "")).strip(),
            }
        )
    out.sort(key=lambda x: x["chapter"])
    return out


def _coerce_relation(item: Any) -> dict[str, Any] | None:
    """把一条关系 dict 归一成 ``{a, b, relation, points, turning_points}``。

    a/b 缺或相同 → 丢（一对关系必须两端）；relation 归一成字符串；points 与
    turning_points 各自归一。points 与 turning_points 全空的关系也丢——没强度点
    又没转折的"关系"画不出东西、也没核验锚点。
    """
    if not isinstance(item, dict):
        return None
    a = str(item.get("a", "")).strip()
    b = str(item.get("b", "")).strip()
    if not a or not b or a == b:
        return None
    points = _coerce_points(item.get("points"))
    first_ch = points[0]["chapter"] if points else 0
    turning_points = _coerce_turning_points(item.get("turning_points"), first_ch)
    if not points and not turning_points:
        return None
    return {
        "a": a,
        "b": b,
        "relation": str(item.get("relation", "")).strip(),
        "points": points,
        "turning_points": turning_points,
    }


def _coerce_relations(raw: Any) -> list[dict[str, Any]]:
    """保留 a/b 齐全且有内容的关系；去重同一对（无向，{a,b} 相同算一对）。"""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[frozenset[str]] = set()
    for item in raw:
        rel = _coerce_relation(item)
        if rel is None:
            continue
        key = frozenset((rel["a"], rel["b"]))
        if key in seen:
            continue
        seen.add(key)
        out.append(rel)
    return out


def _salvage_truncated_relations(text: str) -> list[dict[str, Any]] | None:
    """从截断的 JSON 里抢救已吐完的完整关系对象。

    flash 把 reasoning_content 算进 max_tokens，逐对关系结构一大就可能被截断成半截
    JSON，整段 ``json.loads`` 必败。与其整张时间轴丢掉返 None，不如把 ``"relations"``
    数组里已经闭合的 ``{...}`` 逐个抠出来——用户至少看到大部分关系（同关系图/叙事流/
    character-flow 截断抢救思路）。
    """
    idx = text.find('"relations"')
    if idx == -1:
        return None
    start = text.find("[", idx)
    if start == -1:
        return None
    raw_relations: list[Any] = []
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
            raw_relations.append(json.loads(text[i:j]))
        except json.JSONDecodeError:
            pass
        i = j
    relations = _coerce_relations(raw_relations)
    return relations or None


def _parse_timeline(text: str) -> list[dict[str, Any]] | None:
    """解析模型输出的逐对关系时间轴 JSON。正常失败 → 抢救截断 → 仍不行返 None。"""
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
    if isinstance(obj, dict):
        relations = _coerce_relations(obj.get("relations"))
        if relations:
            return relations
    salvaged = _salvage_truncated_relations(candidate)
    if salvaged is not None:
        logger.warning(
            "relationship_timeline: 主解析失败，从截断输出抢救到 %d 对关系",
            len(salvaged),
        )
        return salvaged
    logger.warning("relationship_timeline parse failed; raw head=%r", candidate[:200])
    return None


def _verify_turning_points(
    relations: list[dict[str, Any]], chunks: list[dict[str, Any]]
) -> None:
    """每对关系每个转折的 evidence 当一条 citation 过 verify_citations（原地附加）。

    命中 → ``verified=True`` + 用命中 chunk 的真章号纠偏（不信模型自报章号，同
    long_context / character_flow / narrative_curve）；没命中 → ``verified=False`` +
    chapter 退回模型自报章号（FE 标灰但仍知道在哪章）。转折的章号纠偏后顺带把它在
    points 上的强度锚回去——但 points 本身不动（强度序列是模型给的，转折只是标注）。
    """
    evidence = {
        str(c["chunk_id"]): {"chapter": c.get("chapter", 0), "text": c.get("text", "")}
        for c in chunks
        if c.get("chunk_id")
    }
    for rel in relations:
        tps = rel["turning_points"]
        # 带上每个转折 LLM 自报章号当多命中消歧弱先验（真章号在 verify 后用 chunk_id 覆盖）。
        tp_citations = [{"snippet": tp["evidence"], "chapter": tp["chapter"]} for tp in tps]
        verify_citations(tp_citations, evidence)
        for tp, vc in zip(tps, tp_citations, strict=True):
            tp["verified"] = bool(vc.get("verified", False))
            tp["match_score"] = vc.get("match_score", 0.0)
            cid = vc.get("chunk_id")
            true_chapter = evidence.get(cid, {}).get("chapter") if cid else None
            if isinstance(true_chapter, int) and true_chapter > 0:
                tp["chapter"] = true_chapter  # 命中 chunk 的真章号纠偏
        tps.sort(key=lambda t: t["chapter"])  # 章号纠偏后可能乱序，再排一次


def generate_relationship_timeline(
    *,
    full_text: str,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    max_tokens: int = DEFAULT_TIMELINE_MAX_TOKENS,
    session_id: str | None = None,
) -> list[dict[str, Any]] | None:
    """整本进 context 抽逐对关系的逐章强度 + 转折 + 每个转折原文核验；失败返 ``None``。

    Args:
        full_text: 整本书 cleaned 原文。
        chunks: 全书 chunk dict（含 ``chunk_id`` / ``chapter`` / ``text``），给转折
            evidence 做证据登记表 + 提供章号 ground truth。
        llm_client: duck-typed LLM client（同 AgentLoop / character_flow）。
        model: 模型名。
        max_tokens: 单次 LLM 调用 max_tokens（默认 8000，逐对关系序列长）。
        session_id: 仅签名兼容——本任务关缓存（防坏响应被 poison）。

    Returns:
        ``[{"a": str, "b": str, "relation": str, "points": [{chapter, strength}],
        "turning_points": [{chapter, change, evidence, verified, match_score}]}, ...]``；
        任意失败 ``None``。
    """
    _ = session_id  # 关缓存：本任务出结构化 JSON，坏响应不该被缓存 poison
    system = build_longctx_system(full_text, _SYSTEM_INSTRUCTION)
    messages = [{"role": "user", "content": "请抽这本书主要人物关系随章节的演变。"}]
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
                "relationship_timeline LLM call raised %s: %s (attempt %d)",
                type(exc).__name__, exc, attempt,
            )
            continue
        relations = _parse_timeline(llm_client.extract_final_text(response))
        if relations is not None:
            _verify_turning_points(relations, chunks)
            return relations
        logger.warning(
            "relationship_timeline parse failed (attempt %d/%d)", attempt, _MAX_ATTEMPTS
        )
    return None


def generate_relationship_timeline_exhaustive(
    *,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    max_tokens: int = DEFAULT_TIMELINE_MAX_TOKENS,
    char_budget: int = 40000,
    max_workers: int | None = None,
) -> list[dict[str, Any]] | None:
    """穷尽化：分段→每段抽本段关系→按对拼，覆盖全书每一对关系（1.4）。

    单次整本进 context 抽逐对关系会被 ~12 对的帽和 max_tokens 截断卡住，长书里好多关系
    都漏了。改 map-reduce：每段只抽这段里出现的关系（强度点、转折），同一对关系跨段的
    points / turning_points 按章号并集拼起来。合并用 ``merge_keyed_points``——key 是无向
    人物对（``frozenset({a, b})``），子点字段 points 和 turning_points 各按章并集。合并后
    一次性 ``_verify_turning_points``（转折逐字核验 + 章号纠偏）。

    Returns: 同 ``generate_relationship_timeline``，但覆盖全书所有关系；空 → ``None``。
    """
    outs = run_segments(
        chunks=chunks,
        instruction=_SYSTEM_INSTRUCTION,
        user_msg="请抽下面这段原文里主要人物关系的逐章强度与转折（只抽本段出现的章）。",
        parse_fn=_parse_timeline,
        llm_client=llm_client,
        model=model,
        max_tokens=max_tokens,
        char_budget=char_budget,
        max_workers=max_workers,
    )
    merged = merge_keyed_points(
        outs,
        key_fn=lambda r: frozenset((r["a"], r["b"])),
        point_fields=["points", "turning_points"],
        # 转折同一章可多个(prompt 不限每章一个),按整条去重而非按章,免得同章第二个转折被吞
        multi_per_key_fields=frozenset({"turning_points"}),
    )
    if not merged:
        return None
    _verify_turning_points(merged, chunks)
    return merged


__all__ = [
    "DEFAULT_TIMELINE_MAX_TOKENS",
    "generate_relationship_timeline",
    "generate_relationship_timeline_exhaustive",
]
