"""人物弧线曲线：整本进 context、给主要角色逐章抽"戏份密度 + 处境弧线"结构化 JSON。

设计：WP-character-arc-curves。

把已经验过、跑得稳的人物弧线**分析**（exp-010 GO：渐变 vs 硬扳判定，准确率 100% /
假阳性 0%）画成两条**看得见的曲线**——这份做可视化，不重造那个判定：

- **戏份密度**（presence，0-10）：某角色在某章出场 / 被提及的强度。一眼看出谁何时主导
  这本书、谁中途隐没又回来。
- **处境弧线**（fortune，-5..+5）：某角色这章过得顺不顺（顺↑ / 逆↓）。连成线就是
  Vonnegut 式人物升降曲线——渐变=平滑爬升、硬扳=直角拐弯。

结构同 :func:`bookscope.agent.narrative_curve.generate_narrative_curve`，差别两处：

1. **出 per 角色逐章序列**——``{"characters": [{"name": 角色名, "points": [{"chapter": N,
   "presence": 0-10, "fortune": -5..+5, "evidence": 原文片段}]}]}``，而不是全书逐章一条。
2. **每个逐章点挂原文证据**——每个 point 的 ``evidence`` 当一条 citation 过
   :func:`verify_citations`：命中某 chunk → ``verified=True`` + 用命中 chunk 的真章号
   纠偏；``verified=False`` 的点留着但前端标低置信（核不过不当确定结论画），evidence-first。

**克制（设计 §2 / §4 划清边界）**：平稳角色就画平、不编波动；处境没大起落的章 fortune
填 0。这是可视化，不是重做 exp-010 的"动机漂移"判定——系统提示明确不诱导编弧线。

整本书结构化功能模式三可靠性守卫照搬：够 max_tokens 防 reasoning 吃 token 截断、
``cache_enabled=False`` 防坏响应被 poison、解析失败重试一次 + 截断抢救。契约同
``generate_narrative_curve``：成功返 list[角色 dict]，**任意环节失败返 None**。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from bookscope.agent._internal.exhaustive import merge_keyed_points, run_segments
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

DEFAULT_ARC_MAX_TOKENS = 8000
"""多角色 × 逐章两维 + evidence 比单条曲线长——给 8000 留 reasoning 头，防截断/空。"""

_MAX_ATTEMPTS = 2

_SYSTEM_INSTRUCTION = (
    "请挑出这本书的主要角色（约 3-6 个，戏份最重、最值得画弧线的），"
    "给每个角色逐章梳理两条曲线——每章给这个角色两个数值：\n"
    "1. presence（戏份密度，0-10 整数）：这章这个角色出场 / 被提及的强度。"
    "这章是主角、戏份很重填高分；这章没出场 / 只一笔带过填低分甚至 0。\n"
    "2. fortune（处境弧线，-5 到 +5 整数）：这章这个角色过得顺不顺、命运往上还是往下。"
    "得势、得救、达成所愿往上走（正数）；落难、失败、受挫往下沉（负数）；"
    "这章处境没明显起落就填 0——**不要为了让曲线好看而编造不存在的波动**，"
    "一个全程平稳的角色，曲线本就该是平的。\n"
    "3. note（处境一句话）：这章这个角色处境上**具体发生了什么**，一句话说清"
    "（如\"潼关失守、弃长安、马嵬赐死贵妃\"），只据原文摘要、不空泛——"
    "**绝不写\"转折向好 / 转坏\"这类方向词，要具体的事**；这章没明显起落可留空。\n"
    "只依据原文，不臆测、不编造。每个数值点给一条最能支撑你这章这个角色判定的"
    "原文逐字片段当证据；这个角色这章没出场就不必给这一章的点。\n"
    "严格输出 JSON（不要别的话、不要 markdown 代码围栏）：\n"
    '{"characters": [{"name": "角色名", "points": [{"chapter": 章号整数, '
    '"presence": 0-10整数, "fortune": -5到5整数, '
    '"note": "这章处境上具体发生了什么，一句话；没起落可留空", '
    '"evidence": "支撑这章这个角色判定的原文逐字片段，原样摘录不改写"}]}]}\n'
    "每个角色的 points 按章号从小到大排列，覆盖该角色出场的主要章节（每个角色最多约 40 个点）；"
    "evidence 是原文里逐字出现的句子。宁可少而准，不必穷尽。"
)


def _clamp_int(value: Any, lo: int, hi: int, default: int) -> int:
    """把模型给的数值钳到 [lo, hi] 整数；非数 / 缺失退 default。"""
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _coerce_point(item: Any) -> dict[str, Any] | None:
    """把一个逐章点归一成 ``{chapter, presence, fortune, note, evidence}``。

    chapter 缺/非整数 → 丢（曲线点没章号没法摆横轴）；presence 钳到 0-10、
    fortune 钳到 -5..5、note（处境一句话，可空）、evidence 可缺（缺则 verified 自然 False）。
    """
    if not isinstance(item, dict):
        return None
    ch = item.get("chapter")
    if not isinstance(ch, int):
        return None
    return {
        "chapter": ch,
        "presence": _clamp_int(item.get("presence"), 0, 10, 0),
        "fortune": _clamp_int(item.get("fortune"), -5, 5, 0),
        "note": str(item.get("note", "")).strip(),
        "evidence": str(item.get("evidence", "")).strip(),
    }


def _coerce_points(raw: Any) -> list[dict[str, Any]]:
    """保留 chapter 齐全的点；去重同章号；按章号升序。"""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for item in raw:
        pt = _coerce_point(item)
        if pt is None or pt["chapter"] in seen:
            continue
        seen.add(pt["chapter"])
        out.append(pt)
    out.sort(key=lambda p: p["chapter"])
    return out


def _coerce_character(item: Any) -> dict[str, Any] | None:
    """把一条角色 dict 归一成 ``{name, points}``。

    name 缺/空 → 丢；points 归一后为空 → 丢（没点的角色画不出曲线）。
    """
    if not isinstance(item, dict):
        return None
    name = str(item.get("name", "")).strip()
    if not name:
        return None
    points = _coerce_points(item.get("points"))
    if not points:
        return None
    return {"name": name, "points": points}


def _coerce_characters(raw: Any) -> list[dict[str, Any]]:
    """保留 name + points 齐全的角色；去重同名（保先出现的）。"""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        ch = _coerce_character(item)
        if ch is None or ch["name"] in seen:
            continue
        seen.add(ch["name"])
        out.append(ch)
    return out


def _salvage_truncated_characters(text: str) -> list[dict[str, Any]] | None:
    """从截断的 JSON 里抢救已吐完的完整角色对象。

    flash 把 reasoning_content 算进 max_tokens，多角色逐章结构一大就可能被截断成
    半截 JSON，整段 ``json.loads`` 必败。与其整张图丢掉返 None，不如把 ``"characters"``
    数组里已经闭合的 ``{...}`` 逐个抠出来——用户至少看到大部分角色（同叙事曲线截断抢救）。
    """
    raw_characters = salvage_closed_objects(text, '"characters"') or []
    characters = _coerce_characters(raw_characters)
    return characters or None


def _parse_arc(text: str) -> list[dict[str, Any]] | None:
    """解析模型输出的人物弧线 JSON。正常失败 → 抢救截断的角色 → 仍不行返 None。"""
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
        characters = _coerce_characters(obj.get("characters"))
        if characters:
            return characters
    salvaged = _salvage_truncated_characters(candidate)
    if salvaged is not None:
        logger.warning(
            "character_arc: 主解析失败，从截断输出抢救到 %d 个角色", len(salvaged)
        )
        return salvaged
    logger.warning("character_arc parse failed; raw head=%r", candidate[:200])
    return None


def _verify_points(
    characters: list[dict[str, Any]], chunks: list[dict[str, Any]]
) -> None:
    """每个角色每个逐章点的 evidence 当一条 citation 过 verify_citations（原地附加）。

    命中 → ``verified=True`` + 用命中 chunk 的真章号纠偏（不信模型自报章号，同
    long_context / narrative_curve）；没命中 → ``verified=False``（FE 把这个点标低
    置信/淡化），point 退回模型自报的章号。章号纠偏后每个角色的点再排一次序。
    """
    evidence = build_evidence_map(chunks)
    for char in characters:
        points = char["points"]
        # 带上每个点 LLM 自报章号当多命中消歧弱先验（真章号在 verify 后用 chunk_id 覆盖）。
        citations = [{"snippet": p["evidence"], "chapter": p["chapter"]} for p in points]
        verify_citations(citations, evidence)
        for pt, vc in zip(points, citations, strict=True):
            pt["verified"] = bool(vc.get("verified", False))
            pt["match_score"] = vc.get("match_score", 0.0)
            cid = vc.get("chunk_id")
            true_chapter = evidence.get(cid, {}).get("chapter") if cid else None
            if isinstance(true_chapter, int) and true_chapter > 0:
                pt["chapter"] = true_chapter  # 命中 chunk 的真章号纠偏
        points.sort(key=lambda p: p["chapter"])  # 章号纠偏后可能乱序，再排一次


def generate_character_arc(
    *,
    full_text: str,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    max_tokens: int = DEFAULT_ARC_MAX_TOKENS,
    session_id: str | None = None,
) -> list[dict[str, Any]] | None:
    """整本进 context 给主要角色抽逐章戏份 + 处境弧线 + 每点原文核验；失败返 ``None``。

    Args:
        full_text: 整本书 cleaned 原文。
        chunks: 全书 chunk dict（含 ``chunk_id`` / ``chapter`` / ``text``），给每个点
            evidence 做证据登记表 + 提供章号 ground truth。
        llm_client: duck-typed LLM client（同 AgentLoop / narrative_curve）。
        model: 模型名。
        max_tokens: 单次 LLM 调用 max_tokens（默认 8000，多角色逐章结构长）。
        session_id: 仅签名兼容——本任务关缓存（防坏响应被 poison）。

    Returns:
        ``[{"name": str, "points": [{"chapter": int, "presence": 0-10, "fortune": -5..5,
        "evidence": str, "verified": bool, "match_score": float}]}, ...]``；
        每个角色的 points 按章号排序；任意失败 ``None``。
    """
    _ = session_id  # 关缓存：本任务出结构化 JSON，坏响应不该被缓存 poison
    system = build_longctx_system(full_text, _SYSTEM_INSTRUCTION)
    messages = [
        {"role": "user", "content": "请给这本书的主要角色逐章抽戏份与处境弧线曲线。"}
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
                "character_arc LLM call raised %s: %s (attempt %d)",
                type(exc).__name__, exc, attempt,
            )
            continue
        characters = _parse_arc(llm_client.extract_final_text(response))
        if characters is not None:
            _verify_points(characters, chunks)
            return characters
        logger.warning(
            "character_arc parse failed (attempt %d/%d)", attempt, _MAX_ATTEMPTS
        )
    return None


def generate_character_arc_exhaustive(
    *,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    max_tokens: int = DEFAULT_ARC_MAX_TOKENS,
    char_budget: int = 40000,
    max_workers: int | None = None,
) -> list[dict[str, Any]] | None:
    """穷尽化:分段→每段抽各角色逐章点→逐段章号纠偏→按角色名合并、点按真章号并集(1.4)。

    重型(多角色 × 逐章两维 + evidence)单次会被 max_tokens 截断,大书漏掉后半本的章。
    改 map-reduce:每段抽本段出场角色的逐章点,按角色名合并。

    **章号纠偏在合并前逐段做**:多卷书正文标题每卷重数,模型照标题给点撞号的小章号,若按它先
    merge,同角色后段的点会跟前段撞章被去重丢(同 narrative 的整章丢,这里丢点)。逐段先把每个点
    ``_verify_points`` 纠偏成命中 chunk 的真章号,再按真章号并集——后段的点才不丢。

    Returns: 同 ``generate_character_arc``,但覆盖全书所有章;空 → ``None``。
    """
    outs = run_segments(
        chunks=chunks,
        instruction=_SYSTEM_INSTRUCTION,
        user_msg="请给下面这段原文里出场的主要角色逐章抽戏份与处境弧线（只抽本段出现的章）。",
        parse_fn=_parse_arc,
        llm_client=llm_client,
        model=model,
        max_tokens=max_tokens,
        char_budget=char_budget,
        max_workers=max_workers,
    )
    for seg in outs:  # 合并前逐段把点的章号纠偏成真章号,免得跨段撞号被去重
        _verify_points(seg, chunks)
    merged = merge_keyed_points(outs, key_fn=lambda c: c["name"], point_fields=["points"])
    return merged or None


__all__ = [
    "DEFAULT_ARC_MAX_TOKENS",
    "generate_character_arc",
    "generate_character_arc_exhaustive",
]
