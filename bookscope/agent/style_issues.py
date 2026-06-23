"""文体级毛病检测：扫一本书的文体毛病——用词重复 / 视角越界 / 支线失踪。

作家发明区——审自己的稿找毛病。长上下文整本进 context、保守地报清楚的文体问题，
每条带原文。

命根子=不 cry wolf：会乱报的审稿工具比没有更糟。两道守卫——
1. prompt 要求保守、宁缺毋滥（probe 实测 anshi 已编辑书平均只报 0.3 条/次）；
2. **每条 snippet 过 verify_citations，核验不过的（编的毛病）直接丢**（同一致性扫描精神，
   不像时间线保留 unverified）。

复用 [[project_wholebook_feature_pattern]] 三守卫。空 issues 是合法结果（书没明显毛病 →
返 []），区别于失败（None）。probe GO：假阳性 0%、原文核验 100%。
"""

from __future__ import annotations

import json
import logging
from typing import Any

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

DEFAULT_STYLE_MAX_TOKENS = 8000
_MAX_ATTEMPTS = 2
_MAX_ISSUES = 40
_VALID_TYPES = {"repetition", "pov", "dropped_thread"}

_SYSTEM_INSTRUCTION = (
    "你是 BookScope 的文体审稿助手。"
    "扫文体级毛病，三类：repetition（用词重复，某词/短语成口头禅）、pov（视角越界，"
    "限知视角写了视角人物不该知道的内心/事）、dropped_thread（支线失踪，埋的支线/人物"
    "后文没交代）。**保守，只报清楚的、宁缺毋滥；没有就别凑。**\n"
    "严格输出 JSON（不要别的话、不要 markdown 代码围栏）：\n"
    '{"issues": [{"type": "repetition|pov|dropped_thread", "what": "问题描述一句", '
    '"chapter": 章号整数, "snippet": "原文逐字片段"}]}\n'
    "snippet 必须是原文里逐字出现的句子。没有清楚的毛病就返回 "
    '{"issues": []}，绝不为凑数编造。'
)


def _resp_field(resp: Any, field: str) -> Any:
    if resp is None:
        return None
    if isinstance(resp, dict):
        return resp.get(field)
    return getattr(resp, field, None)


def _coerce(raw: Any) -> list[dict[str, Any]] | None:
    """结构合法 → list（可能空 = 没毛病，合法）；结构非法 → None。"""
    if not isinstance(raw, dict):
        return None
    items = raw.get("issues")
    if not isinstance(items, list):
        return None
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        snippet = str(item.get("snippet", "")).strip()
        if not snippet:  # 无原文 = 无证据，丢
            continue
        itype = str(item.get("type", "")).strip()
        if itype not in _VALID_TYPES:
            itype = "repetition"
        chapter = item.get("chapter")
        out.append({
            "type": itype,
            "what": str(item.get("what", "")).strip(),
            "chapter": chapter if isinstance(chapter, int) else 0,
            "snippet": snippet,
        })
        if len(out) >= _MAX_ISSUES:
            break
    return out


def _salvage_truncated(text: str) -> list[dict[str, Any]] | None:
    raw_items = salvage_closed_objects(text, '"issues"') or []
    return _coerce({"issues": raw_items}) if raw_items else None


def _parse_issues(text: str) -> list[dict[str, Any]] | None:
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
    if salvaged:
        logger.warning(
            "style_issues: 主解析失败，从截断输出抢救到 %d 条", len(salvaged)
        )
    return salvaged


def generate_style_issues(
    *,
    full_text: str,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    max_tokens: int = DEFAULT_STYLE_MAX_TOKENS,
    session_id: str | None = None,
) -> list[dict[str, Any]] | None:
    """扫书的文体毛病；失败返 ``None``，没毛病返 ``[]``。

    **每条 snippet 过 verify_citations，核验不过的（编的）丢掉**——审稿工具宁可漏报
    不可乱报。留下的标 verified=True + 真章号纠偏。

    Returns:
        ``[{type, what, chapter, snippet, verified}, ...]``（全 verified）；
        ``[]`` = 没扫出核验得了的毛病；``None`` = 解析/调用失败。
    """
    _ = session_id
    evidence_map = {
        str(c["chunk_id"]): {"chapter": c.get("chapter", 0), "text": c.get("text", "")}
        for c in chunks
        if c.get("chunk_id")
    }
    system = build_longctx_system(full_text, _SYSTEM_INSTRUCTION)
    messages = [{"role": "user", "content": "请扫这本书的文体毛病。"}]
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
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "style_issues LLM call raised %s: %s (attempt %d)",
                type(exc).__name__, exc, attempt,
            )
            continue
        issues = _parse_issues(llm_client.extract_final_text(response))
        if issues is None:
            logger.warning(
                "style_issues parse failed (attempt %d/%d)", attempt, _MAX_ATTEMPTS
            )
            continue
        kept: list[dict[str, Any]] = []
        for it in issues:
            # 带上 LLM 自报章号当多命中消歧弱先验（真章号在 verify 后用 chunk_id 覆盖）；
            # chapter 为 0 = 模型没报，不传，退回确定性首个。
            self_ch = it.get("chapter")
            cit: dict[str, Any] = {"snippet": it["snippet"]}
            if isinstance(self_ch, int) and self_ch > 0:
                cit["chapter"] = self_ch
            cits = [cit]
            verify_citations(cits, evidence_map)
            vc = cits[0]
            if not vc.get("verified"):
                continue  # 编的毛病：核验不过，丢
            cid = vc.get("chunk_id")
            true_ch = evidence_map.get(cid, {}).get("chapter") if cid else None
            if isinstance(true_ch, int) and true_ch > 0:
                it["chapter"] = true_ch
            it["verified"] = True
            kept.append(it)
        return kept
    return None


__all__ = ["DEFAULT_STYLE_MAX_TOKENS", "generate_style_issues"]
