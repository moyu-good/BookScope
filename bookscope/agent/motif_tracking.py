"""主题母题追踪：给一个主题/母题，回溯它在全书的复现，每处带原文。

读者发明区——读名著/密度大的书，看一个母题怎么贯穿全书。长上下文整本进 context、
按章节先后列出母题的复现处，每处带原文。

scope（evidence-first 红线）：只做**原文可锚的母题复现追踪**；典故的外部出处注释靠书外
知识、与"结论钉原文"冲突，v1 不做（见 WP-motif-tracking）。

是 [[concept_evolution]] / [[entity_recall]] 家族（按用户给的单位回溯 + verify-filter +
empty→[] 合法）。命根子=书里没有的母题返空、不编（probe 假阳性 0%）。
复用 [[project_wholebook_feature_pattern]] 三守卫。
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

DEFAULT_MOTIF_MAX_TOKENS = 8000
_MAX_ATTEMPTS = 2
_MAX_OCCURRENCES = 60

_SYSTEM_INSTRUCTION = (
    "你是 BookScope 的母题追踪助手。用户给一个"
    "主题/母题，回溯它在全书的复现——每处在哪章、怎么体现这个母题，按章节先后。只据原文、不编。\n"
    "严格输出 JSON（不要别的话、不要 markdown 代码围栏）：\n"
    '{"occurrences": [{"order": 序号整数, "chapter": 章号整数, '
    '"manifestation": "这处怎么体现该母题", "snippet": "原文逐字片段"}]}\n'
    "order 从 1 起递增；snippet 必须是原文里逐字出现的句子。"
    '**书里没有这个母题就返回 {"occurrences": []}，绝不编造复现。**'
)


def _resp_field(resp: Any, field: str) -> Any:
    if resp is None:
        return None
    if isinstance(resp, dict):
        return resp.get(field)
    return getattr(resp, field, None)


def _coerce(raw: Any) -> list[dict[str, Any]] | None:
    if not isinstance(raw, dict):
        return None
    items = raw.get("occurrences")
    if not isinstance(items, list):
        return None
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        snippet = str(item.get("snippet", "")).strip()
        if not snippet:
            continue
        order = item.get("order")
        chapter = item.get("chapter")
        out.append({
            "order": order if isinstance(order, int) else len(out) + 1,
            "chapter": chapter if isinstance(chapter, int) else 0,
            "manifestation": str(item.get("manifestation", "")).strip(),
            "snippet": snippet,
        })
        if len(out) >= _MAX_OCCURRENCES:
            break
    out.sort(key=lambda o: o["order"])
    return out


def _salvage_truncated(text: str) -> list[dict[str, Any]] | None:
    raw_items = salvage_closed_objects(text, '"occurrences"') or []
    return _coerce({"occurrences": raw_items}) if raw_items else None


def _parse_occurrences(text: str) -> list[dict[str, Any]] | None:
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
            "motif_tracking: 主解析失败，从截断输出抢救到 %d 处", len(salvaged)
        )
    return salvaged


def generate_motif_tracking(
    *,
    motif: str,
    full_text: str,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    max_tokens: int = DEFAULT_MOTIF_MAX_TOKENS,
    session_id: str | None = None,
) -> list[dict[str, Any]] | None:
    """回溯母题的全书复现；失败返 ``None``，母题不在书 / 无核验得了的复现返 ``[]``。

    **核验不过的复现丢**（母题体现常是转述）——只留 verified + 真章号纠偏。
    命根子=书里没有的母题不编复现。

    Returns:
        ``[{order, chapter, manifestation, snippet, verified}, ...]``（全 verified）；
        ``[]`` = 母题不在书 / 没核验得了的复现；``None`` = 解析/调用失败。
    """
    _ = session_id
    motif = (motif or "").strip()
    if not motif:
        return None
    evidence_map = {
        str(c["chunk_id"]): {"chapter": c.get("chapter", 0), "text": c.get("text", "")}
        for c in chunks
        if c.get("chunk_id")
    }
    system = build_longctx_system(full_text, _SYSTEM_INSTRUCTION)
    messages = [{"role": "user", "content": f"请回溯母题「{motif}」在全书的复现。"}]
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
                "motif_tracking LLM call raised %s: %s (attempt %d)",
                type(exc).__name__, exc, attempt,
            )
            continue
        occ = _parse_occurrences(llm_client.extract_final_text(response))
        if occ is None:
            logger.warning(
                "motif_tracking parse failed (attempt %d/%d)", attempt, _MAX_ATTEMPTS
            )
            continue
        kept: list[dict[str, Any]] = []
        for it in occ:
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
                continue
            cid = vc.get("chunk_id")
            true_ch = evidence_map.get(cid, {}).get("chapter") if cid else None
            if isinstance(true_ch, int) and true_ch > 0:
                it["chapter"] = true_ch
            it["verified"] = True
            kept.append(it)
        return kept
    return None


__all__ = ["DEFAULT_MOTIF_MAX_TOKENS", "generate_motif_tracking"]
