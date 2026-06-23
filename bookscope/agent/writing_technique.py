"""写作手法分析：分析作者的写作手法——怎么论证/结构/铺陈/用语，每个配原文例子。

学习者发明区——学手艺，看高手怎么写。长上下文整本进 context、列出书里显著的写作手法，
每条带原文例子。

是 [[style_issues]] 的形态（一键 + verify-filter + empty→[] 合法）：手法例子常转述，
**核验不过的丢、只留逐字锚得住的**。命根子=不编书里没用的手法（probe：第二人称/意识流
假阳性 0%）。复用 [[project_wholebook_feature_pattern]] 三守卫。
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

DEFAULT_WRITING_TECHNIQUE_MAX_TOKENS = 8000
_MAX_ATTEMPTS = 2
_MAX_TECHNIQUES = 30

_SYSTEM_INSTRUCTION = (
    "你是 BookScope 的写作手法分析助手。分析作者的"
    "主要写作手法——怎么论证、怎么结构、怎么铺陈/用语。每条给：手法名、怎么用的、一句原文"
    "逐字例子、所在章节。只据原文、不编，不评优劣。\n"
    "严格输出 JSON（不要别的话、不要 markdown 代码围栏）：\n"
    '{"techniques": [{"order": 序号整数, "technique": "手法名", "how": "怎么用的", '
    '"snippet": "原文逐字例子", "chapter": 章号整数}]}\n'
    "order 从 1 起递增；snippet 必须是原文里逐字出现的句子。"
    '没有显著手法就返回 {"techniques": []}，绝不编造。'
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
    items = raw.get("techniques")
    if not isinstance(items, list):
        return None
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        snippet = str(item.get("snippet", "")).strip()
        technique = str(item.get("technique", "")).strip()
        if not snippet or not technique:
            continue
        order = item.get("order")
        chapter = item.get("chapter")
        out.append({
            "order": order if isinstance(order, int) else len(out) + 1,
            "technique": technique,
            "how": str(item.get("how", "")).strip(),
            "chapter": chapter if isinstance(chapter, int) else 0,
            "snippet": snippet,
        })
        if len(out) >= _MAX_TECHNIQUES:
            break
    out.sort(key=lambda t: t["order"])
    return out


def _salvage_truncated(text: str) -> list[dict[str, Any]] | None:
    raw_items = salvage_closed_objects(text, '"techniques"') or []
    return _coerce({"techniques": raw_items}) if raw_items else None


def _parse_techniques(text: str) -> list[dict[str, Any]] | None:
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
            "writing_technique: 主解析失败，从截断输出抢救到 %d 条", len(salvaged)
        )
    return salvaged


def generate_writing_technique(
    *,
    full_text: str,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    max_tokens: int = DEFAULT_WRITING_TECHNIQUE_MAX_TOKENS,
    session_id: str | None = None,
) -> list[dict[str, Any]] | None:
    """分析书的写作手法；失败返 ``None``，没核验得了的手法返 ``[]``。

    **核验不过的手法丢**（例子常转述）——只留 verified + 真章号纠偏。命根子=不编没用的手法。

    Returns:
        ``[{order, technique, how, chapter, snippet, verified}, ...]``（全 verified）；
        ``[]`` = 没核验得了的手法；``None`` = 解析/调用失败。
    """
    _ = session_id
    evidence_map = {
        str(c["chunk_id"]): {"chapter": c.get("chapter", 0), "text": c.get("text", "")}
        for c in chunks
        if c.get("chunk_id")
    }
    system = build_longctx_system(full_text, _SYSTEM_INSTRUCTION)
    messages = [{"role": "user", "content": "请分析这本书的主要写作手法。"}]
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
                "writing_technique LLM call raised %s: %s (attempt %d)",
                type(exc).__name__, exc, attempt,
            )
            continue
        techs = _parse_techniques(llm_client.extract_final_text(response))
        if techs is None:
            logger.warning(
                "writing_technique parse failed (attempt %d/%d)", attempt, _MAX_ATTEMPTS
            )
            continue
        kept: list[dict[str, Any]] = []
        for it in techs:
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


__all__ = ["DEFAULT_WRITING_TECHNIQUE_MAX_TOKENS", "generate_writing_technique"]
