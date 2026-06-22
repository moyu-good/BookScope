"""跨章概念演进对照：给一个概念，回溯它在全书怎么一步步发展。

学习者发明区——读理论书跟一个核心概念从提出到展开到深化。长上下文整本进 context、
按章节先后列出概念的演进阶段，每阶段带原文。

是 [[entity_recall]] 的近亲（按概念回溯 + verify + empty→[] 合法），但**带 verify-filter
守卫**：probe 实测抽象概念（如"国家"）模型易给非逐字 snippet，所以**核验不过的阶段直接丢、
只留核验过的**（同 style_issues，不像 entity_recall 保留 unverified）。命根子=书里没有的
概念返空、不编（probe 假阳性 0%）。

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
    strip_code_fence as _strip_code_fence,
)

logger = logging.getLogger(__name__)

DEFAULT_CONCEPT_EVOLUTION_MAX_TOKENS = 8000
_MAX_ATTEMPTS = 2
_MAX_STAGES = 50

_SYSTEM_INSTRUCTION = (
    "你是 BookScope 的概念演进助手。用户会给一个"
    "概念，回溯它在全书怎么一步步发展——每个阶段在哪章、概念被怎么用/深化/转义，按章节"
    "先后。只据原文、不编。\n"
    "严格输出 JSON（不要别的话、不要 markdown 代码围栏）：\n"
    '{"stages": [{"order": 序号整数, "chapter": 章号整数, '
    '"development": "这一处概念怎么发展", "snippet": "原文逐字片段"}]}\n'
    "order 从 1 起递增；snippet 必须是原文里逐字出现的句子。"
    '**书里没有这个概念就返回 {"stages": []}，绝不编造演进。**'
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
    items = raw.get("stages")
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
            "development": str(item.get("development", "")).strip(),
            "snippet": snippet,
        })
        if len(out) >= _MAX_STAGES:
            break
    out.sort(key=lambda s: s["order"])
    return out


def _salvage_truncated(text: str) -> list[dict[str, Any]] | None:
    idx = text.find('"stages"')
    if idx == -1:
        return None
    start = text.find("[", idx)
    if start == -1:
        return None
    raw_items: list[Any] = []
    i = start + 1
    n = len(text)
    while i < n:
        while i < n and text[i] not in "{]":
            i += 1
        if i >= n or text[i] == "]":
            break
        depth = 0
        in_str = False
        esc = False
        closed = False
        j = i
        while j < n:
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
            break
        try:
            raw_items.append(json.loads(text[i:j]))
        except json.JSONDecodeError:
            pass
        i = j
    return _coerce({"stages": raw_items}) if raw_items else None


def _parse_stages(text: str) -> list[dict[str, Any]] | None:
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
            "concept_evolution: 主解析失败，从截断输出抢救到 %d 阶段", len(salvaged)
        )
    return salvaged


def generate_concept_evolution(
    *,
    concept: str,
    full_text: str,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    max_tokens: int = DEFAULT_CONCEPT_EVOLUTION_MAX_TOKENS,
    session_id: str | None = None,
) -> list[dict[str, Any]] | None:
    """回溯概念的全书演进；失败返 ``None``，概念不在书里 / 无核验得了的阶段返 ``[]``。

    **核验不过的阶段丢**（probe：抽象概念模型易给非逐字 snippet）——只留 verified，
    + 真章号纠偏。命根子=书里没有的概念不编演进。

    Returns:
        ``[{order, chapter, development, snippet, verified}, ...]``（全 verified）；
        ``[]`` = 概念不在书 / 没核验得了的阶段；``None`` = 解析/调用失败。
    """
    _ = session_id
    concept = (concept or "").strip()
    if not concept:
        return None
    evidence_map = {
        str(c["chunk_id"]): {"chapter": c.get("chapter", 0), "text": c.get("text", "")}
        for c in chunks
        if c.get("chunk_id")
    }
    system = build_longctx_system(full_text, _SYSTEM_INSTRUCTION)
    messages = [{"role": "user", "content": f"请回溯概念「{concept}」在全书的演进。"}]
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
                "concept_evolution LLM call raised %s: %s (attempt %d)",
                type(exc).__name__, exc, attempt,
            )
            continue
        stages = _parse_stages(llm_client.extract_final_text(response))
        if stages is None:
            logger.warning(
                "concept_evolution parse failed (attempt %d/%d)", attempt, _MAX_ATTEMPTS
            )
            continue
        kept: list[dict[str, Any]] = []
        for st in stages:
            # 带上 LLM 自报章号当多命中消歧弱先验（真章号在 verify 后用 chunk_id 覆盖）；
            # chapter 为 0 = 模型没报，不传，退回确定性首个。
            self_ch = st.get("chapter")
            cit: dict[str, Any] = {"snippet": st["snippet"]}
            if isinstance(self_ch, int) and self_ch > 0:
                cit["chapter"] = self_ch
            cits = [cit]
            verify_citations(cits, evidence_map)
            vc = cits[0]
            if not vc.get("verified"):
                continue  # 核验不过（抽象概念易给非逐字）：丢
            cid = vc.get("chunk_id")
            true_ch = evidence_map.get(cid, {}).get("chapter") if cid else None
            if isinstance(true_ch, int) and true_ch > 0:
                st["chapter"] = true_ch
            st["verified"] = True
            kept.append(st)
        return kept
    return None


__all__ = ["DEFAULT_CONCEPT_EVOLUTION_MAX_TOKENS", "generate_concept_evolution"]
