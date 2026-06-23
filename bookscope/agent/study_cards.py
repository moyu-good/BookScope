"""知识点卡片：据书出知识点卡片，每张含知识点 + 启发自测题 + 原文依据。

学习者发明区——拿书学东西，要可自测的卡片。长上下文整本进 context、列出书的知识点，
每张配一道启发式自测题（"先想后翻"）+ 一句原文依据。

scope：v1 是"卡片 + 自测题"（自测，不是 AI 实时多轮追问）；完整互动启发对话留后续
（见 WP-study-cards）。是 [[writing_technique]] 形态（一键 + verify-filter）：snippet 核验
不过的丢。命根子=不编书里没教的知识点（probe：量子计算/光合作用 假阳性 0%）。
复用 [[project_wholebook_feature_pattern]] 三守卫。
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

DEFAULT_STUDY_CARDS_MAX_TOKENS = 8000
_MAX_ATTEMPTS = 2
_MAX_CARDS = 30

_SYSTEM_INSTRUCTION = (
    "你是 BookScope 的学习卡片助手。据书出知识点"
    "卡片，每张给：知识点名、解释、一道启发式自测题（启发读者自己想，不是直接给答案）、"
    "一句原文逐字依据、所在章节。只据原文、不编。\n"
    "严格输出 JSON（不要别的话、不要 markdown 代码围栏）：\n"
    '{"cards": [{"order": 序号整数, "concept": "知识点名", "point": "解释", '
    '"question": "启发自测题", "snippet": "原文逐字依据", "chapter": 章号整数}]}\n'
    "order 从 1 起递增；snippet 必须是原文里逐字出现的句子。"
    '没有可锚到原文的知识点就返回 {"cards": []}，绝不编造。'
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
    items = raw.get("cards")
    if not isinstance(items, list):
        return None
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        snippet = str(item.get("snippet", "")).strip()
        concept = str(item.get("concept", "")).strip()
        if not snippet or not concept:
            continue
        order = item.get("order")
        chapter = item.get("chapter")
        out.append({
            "order": order if isinstance(order, int) else len(out) + 1,
            "concept": concept,
            "point": str(item.get("point", "")).strip(),
            "question": str(item.get("question", "")).strip(),
            "chapter": chapter if isinstance(chapter, int) else 0,
            "snippet": snippet,
        })
        if len(out) >= _MAX_CARDS:
            break
    out.sort(key=lambda c: c["order"])
    return out


def _salvage_truncated(text: str) -> list[dict[str, Any]] | None:
    raw_items = salvage_closed_objects(text, '"cards"') or []
    return _coerce({"cards": raw_items}) if raw_items else None


def _parse_cards(text: str) -> list[dict[str, Any]] | None:
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
            "study_cards: 主解析失败，从截断输出抢救到 %d 张", len(salvaged)
        )
    return salvaged


def generate_study_cards(
    *,
    full_text: str,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    max_tokens: int = DEFAULT_STUDY_CARDS_MAX_TOKENS,
    session_id: str | None = None,
) -> list[dict[str, Any]] | None:
    """据书出知识点卡片；失败返 ``None``，没核验得了的知识点返 ``[]``。

    **依据 snippet 核验不过的卡片丢**——只留 verified + 真章号纠偏。命根子=不编没教的知识点。

    Returns:
        ``[{order, concept, point, question, chapter, snippet, verified}, ...]``（全 verified）；
        ``[]`` = 没核验得了的知识点；``None`` = 解析/调用失败。
    """
    _ = session_id
    evidence_map = build_evidence_map(chunks)
    system = build_longctx_system(full_text, _SYSTEM_INSTRUCTION)
    messages = [{"role": "user", "content": "请据这本书出知识点卡片。"}]
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
                "study_cards LLM call raised %s: %s (attempt %d)",
                type(exc).__name__, exc, attempt,
            )
            continue
        cards = _parse_cards(llm_client.extract_final_text(response))
        if cards is None:
            logger.warning(
                "study_cards parse failed (attempt %d/%d)", attempt, _MAX_ATTEMPTS
            )
            continue
        kept: list[dict[str, Any]] = []
        for it in cards:
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


__all__ = ["DEFAULT_STUDY_CARDS_MAX_TOKENS", "generate_study_cards"]
