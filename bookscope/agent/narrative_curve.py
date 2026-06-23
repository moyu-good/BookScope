"""多维叙事曲线：整本进 context、逐章抽"张力 + 情感方向 + 主导 POV + 主/支线"结构化 JSON。

设计：WP-multidim-narrative-curve。

probe GO（POV 83% / 情感方向 83% / 假阳性 0/9）：agent 能逐章可靠判定"这章情感往上还是
往下""这章主 POV 是谁""这章推主线还是铺支线"，且不顺着诱导瞎标。本模块把它从单段 probe
做成整本逐章抽取的生产实现——给前端在节奏曲线之上叠维，画整本书的"形状"
（Vonnegut「故事的形状」+ Reagan 情感弧线，但做成逐章可核验的判读而非词典法统计）。

结构同 :func:`bookscope.agent.character_flow.generate_character_flow`，差别两处：

1. **出逐章多维**——``{"chapters": [{"chapter": N, "tension": 0-10, "sentiment": -5..+5,
   "pov": 主导视角人物名, "mainline": bool, "evidence": 原文片段}]}``，而不是同场关系。
2. **每章判定挂原文证据**——每章的 ``evidence`` 当一条 citation 过
   :func:`verify_citations`：命中某 chunk → ``verified=True`` + 用命中 chunk 的真章号
   纠偏；``verified=False`` 的章留着但标灰（FE 把核不过的维度标低置信/不画），evidence-first。

整本书结构化功能模式三可靠性守卫照搬：够 max_tokens 防 reasoning 吃 token 截断、
``cache_enabled=False`` 防坏响应被 poison、解析失败重试一次 + 截断抢救。契约同
``generate_character_flow``：成功返 list[章节 dict]，**任意环节失败返 None**。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from bookscope.agent._internal.exhaustive import mapreduce_per_chapter
from bookscope.agent._internal.llm_cache import invoke_client_cached as _invoke_client
from bookscope.agent._internal.longctx_system import build_longctx_system
from bookscope.agent.citation_check import verify_citations
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

DEFAULT_CURVE_MAX_TOKENS = 8000
"""逐章四维 + evidence 比单点判断长——给 8000 留 reasoning 头，防截断/空（同关系图/叙事流）。"""

_MAX_ATTEMPTS = 2

_SYSTEM_INSTRUCTION = (
    "请逐章梳理这本书的「叙事曲线」——每章判定四个维度：\n"
    "1. tension（张力，0-10 整数）：这章剧情绷得紧不紧。铺垫/过场章低，高潮/冲突章高。\n"
    "2. sentiment（情感方向，-5 到 +5 整数）：这章整体往上走（喜、胜、聚，正数）"
    "还是往下沉（悲、败、散，负数）；基本平稳填 0。\n"
    "3. pov（主导视角）：这章主要从谁的眼睛看、跟着谁走。给那个人物的称呼；"
    "若无明确单一人物视角（如全景叙述）填\"群像\"。\n"
    "4. mainline（主/支线，true/false）：这章是在推进故事主线（true），"
    "还是岔开去写支线/闲笔（false）。\n"
    "只依据原文，不臆测、不编造。每章给一条最能支撑你这章判定的原文逐字片段当证据。\n"
    "严格输出 JSON（不要别的话、不要 markdown 代码围栏）：\n"
    '{"chapters": [{"chapter": 章号整数, "tension": 0-10整数, '
    '"sentiment": -5到5整数, "pov": "主导视角人物名", "mainline": true或false, '
    '"evidence": "支撑这章判定的原文逐字片段，原样摘录不改写"}]}\n'
    "按章号从小到大排列，覆盖主要章节（最多约 40 章）；evidence 是原文里逐字出现的句子。"
    "宁可少而准，不必穷尽。"
)


def _clamp_int(value: Any, lo: int, hi: int, default: int) -> int:
    """把模型给的数值钳到 [lo, hi] 整数；非数 / 缺失退 default。"""
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _coerce_chapter(item: Any) -> dict[str, Any] | None:
    """把一条章节 dict 归一成 ``{chapter, tension, sentiment, pov, mainline, evidence}``。

    chapter 缺/非整数 → 丢（曲线点没章号没法摆横轴）；tension 钳到 0-10、
    sentiment 钳到 -5..5、pov 归一成字符串（空退"群像"）、mainline 归一成 bool
    （非 bool 退 True，主线偏多更安全）、evidence 可缺（缺则 verified 自然 False）。
    """
    if not isinstance(item, dict):
        return None
    ch = item.get("chapter")
    if not isinstance(ch, int):
        return None

    pov = str(item.get("pov", "")).strip() or "群像"
    raw_main = item.get("mainline")
    mainline = raw_main if isinstance(raw_main, bool) else True

    return {
        "chapter": ch,
        "tension": _clamp_int(item.get("tension"), 0, 10, 0),
        "sentiment": _clamp_int(item.get("sentiment"), -5, 5, 0),
        "pov": pov,
        "mainline": mainline,
        "evidence": str(item.get("evidence", "")).strip(),
    }


def _coerce_chapters(raw: Any) -> list[dict[str, Any]]:
    """保留 chapter 齐全的章节；去重同章号；按章号升序。"""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for item in raw:
        ch = _coerce_chapter(item)
        if ch is None or ch["chapter"] in seen:
            continue
        seen.add(ch["chapter"])
        out.append(ch)
    out.sort(key=lambda c: c["chapter"])
    return out


def _salvage_truncated_chapters(text: str) -> list[dict[str, Any]] | None:
    """从截断的 JSON 里抢救已吐完的完整章节对象。

    flash 把 reasoning_content 算进 max_tokens，逐章结构一大就可能被截断成半截 JSON，
    整段 ``json.loads`` 必败。与其整张曲线丢掉返 None，不如把 ``"chapters"`` 数组里
    已经闭合的 ``{...}`` 逐个抠出来——用户至少看到大部分章节（同关系图/叙事流截断抢救）。
    """
    raw_chapters = salvage_closed_objects(text, '"chapters"') or []
    chapters = _coerce_chapters(raw_chapters)
    return chapters or None


def _parse_curve(text: str) -> list[dict[str, Any]] | None:
    """解析模型输出的逐章曲线 JSON。正常失败 → 抢救截断的章节 → 仍不行返 None。"""
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
        chapters = _coerce_chapters(obj.get("chapters"))
        if chapters:
            return chapters
    salvaged = _salvage_truncated_chapters(candidate)
    if salvaged is not None:
        logger.warning(
            "narrative_curve: 主解析失败，从截断输出抢救到 %d 章", len(salvaged)
        )
        return salvaged
    logger.warning("narrative_curve parse failed; raw head=%r", candidate[:200])
    return None


def _verify_chapters(
    chapters: list[dict[str, Any]], chunks: list[dict[str, Any]]
) -> None:
    """每章的 evidence 当一条 citation 过 verify_citations（原地附加）。

    命中 → ``verified=True`` + 用命中 chunk 的真章号纠偏（不信模型自报章号，同
    long_context / character_flow）；没命中 → ``verified=False``（FE 把这章的维度
    标低置信/不画），chapter 退回模型自报的章号。
    """
    evidence = {
        str(c["chunk_id"]): {"chapter": c.get("chapter", 0), "text": c.get("text", "")}
        for c in chunks
        if c.get("chunk_id")
    }
    # 带上每章 LLM 自报章号当多命中消歧弱先验（真章号在 verify 后用 chunk_id 覆盖）。
    citations = [{"snippet": c["evidence"], "chapter": c["chapter"]} for c in chapters]
    verify_citations(citations, evidence)
    for chap, vc in zip(chapters, citations, strict=True):
        chap["verified"] = bool(vc.get("verified", False))
        chap["match_score"] = vc.get("match_score", 0.0)
        cid = vc.get("chunk_id")
        true_chapter = evidence.get(cid, {}).get("chapter") if cid else None
        if isinstance(true_chapter, int) and true_chapter > 0:
            chap["chapter"] = true_chapter  # 命中 chunk 的真章号纠偏
    chapters.sort(key=lambda c: c["chapter"])  # 章号纠偏后可能乱序，再排一次


def generate_narrative_curve(
    *,
    full_text: str,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    max_tokens: int = DEFAULT_CURVE_MAX_TOKENS,
    session_id: str | None = None,
) -> list[dict[str, Any]] | None:
    """整本进 context 抽逐章多维曲线 + 每章原文核验；失败返 ``None``。

    Args:
        full_text: 整本书 cleaned 原文。
        chunks: 全书 chunk dict（含 ``chunk_id`` / ``chapter`` / ``text``），给每章
            evidence 做证据登记表 + 提供章号 ground truth。
        llm_client: duck-typed LLM client（同 AgentLoop / character_flow）。
        model: 模型名。
        max_tokens: 单次 LLM 调用 max_tokens（默认 8000，逐章四维结构长）。
        session_id: 仅签名兼容——本任务关缓存（防坏响应被 poison）。

    Returns:
        ``[{"chapter": int, "tension": 0-10, "sentiment": -5..5, "pov": str,
        "mainline": bool, "evidence": str, "verified": bool, "match_score": float},
        ...]`` 按章号排序；任意失败 ``None``。
    """
    _ = session_id  # 关缓存：本任务出结构化 JSON，坏响应不该被缓存 poison
    system = build_longctx_system(full_text, _SYSTEM_INSTRUCTION)
    messages = [{"role": "user", "content": "请逐章抽这本书的多维叙事曲线。"}]
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
                "narrative_curve LLM call raised %s: %s (attempt %d)",
                type(exc).__name__, exc, attempt,
            )
            continue
        chapters = _parse_curve(llm_client.extract_final_text(response))
        if chapters is not None:
            _verify_chapters(chapters, chunks)
            return chapters
        logger.warning(
            "narrative_curve parse failed (attempt %d/%d)", attempt, _MAX_ATTEMPTS
        )
    return None


def generate_narrative_curve_exhaustive(
    *,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    max_tokens: int = DEFAULT_CURVE_MAX_TOKENS,
    char_budget: int = 40000,
    max_workers: int | None = None,
) -> list[dict[str, Any]] | None:
    """穷尽化:分段→每段逐章抽→按章拼,覆盖全书每一章(1.4)。

    重型逐章(每章带 evidence/四维)单次会被 max_tokens 截断到几章——三国 cap-lift 后只 8 章。
    改 map-reduce:每段章数远小于 40 帽,段内用现有 prompt 即可,拼起来覆盖全书。合并后一次性
    ``_verify_chapters``(逐字核验 + 章号纠偏)。

    Returns: 同 ``generate_narrative_curve``,但覆盖全书所有章;空 → ``None``。
    """
    merged = mapreduce_per_chapter(
        chunks=chunks,
        instruction=_SYSTEM_INSTRUCTION,
        user_msg="请逐章抽下面这段原文的多维叙事曲线（只抽本段出现的章）。",
        parse_fn=_parse_curve,
        llm_client=llm_client,
        model=model,
        max_tokens=max_tokens,
        char_budget=char_budget,
        max_workers=max_workers,
    )
    if not merged:
        return None
    _verify_chapters(merged, chunks)
    return merged


__all__ = [
    "DEFAULT_CURVE_MAX_TOKENS",
    "generate_narrative_curve",
    "generate_narrative_curve_exhaustive",
]
