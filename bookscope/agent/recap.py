"""无剧透情节回顾：给"读到第 X 章"，回顾到此为止的前情，绝不剧透后文。

读者发明区——追更/慢读回来忘了前情，又怕被剧透。**无剧透靠结构保证**：调用方只把第
1..X 章的原文喂进来（后文物理上不在 context），模型编都没法编后文。本模块同 timeline——
长上下文 + 结构化 JSON + 三守卫 + verify + 章号纠偏，只是上下文是"截到 X 章"的部分原文。

probe GO（anshi 截第 15 章）：引用真实性 100%、后文泄漏 0、问结局老实说"读到第15章为止"。
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
    salvage_closed_objects,
)
from bookscope.agent.utils.json_parsing import (
    strip_code_fence as _strip_code_fence,
)

logger = logging.getLogger(__name__)

DEFAULT_RECAP_MAX_TOKENS = 8000
_MAX_ATTEMPTS = 2
_MAX_POINTS = 40

_BOOK_DELIMITER = "\n\n=== 读到此处的原文 ===\n"


def _system_instruction(up_to_chapter: int) -> str:
    return (
        "你是 BookScope 的前情回顾助手。下面 === 读到此处的原文 === 之后是一本书"
        f"**读到第 {up_to_chapter} 章为止**的原文（后文没有给你）。回顾到此为止的关键"
        "人物、事件、线索，按时序排。只据给出的原文、不臆测、不编、不提后文。\n"
        "严格输出 JSON（不要别的话、不要 markdown 代码围栏）：\n"
        '{"points": [{"order": 序号整数, "point": "前情要点一句", '
        '"chapter": 章号整数, "snippet": "原文逐字片段"}]}\n'
        "order 从 1 起递增。snippet 必须是给出原文里逐字出现的句子。"
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
    items = raw.get("points")
    if not isinstance(items, list):
        return None
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        point = str(item.get("point", "")).strip()
        if not point:
            continue
        order = item.get("order")
        chapter = item.get("chapter")
        out.append({
            "order": order if isinstance(order, int) else len(out) + 1,
            "point": point,
            "chapter": chapter if isinstance(chapter, int) else 0,
            "snippet": str(item.get("snippet", "")).strip(),
        })
        if len(out) >= _MAX_POINTS:
            break
    out.sort(key=lambda p: p["order"])
    return out or None


def _salvage_truncated(text: str) -> list[dict[str, Any]] | None:
    raw_items = salvage_closed_objects(text, '"points"') or []
    return _coerce({"points": raw_items}) if raw_items else None


def _parse_points(text: str) -> list[dict[str, Any]] | None:
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
        logger.warning("recap: 主解析失败，从截断输出抢救到 %d 条", len(salvaged))
    return salvaged


def generate_recap(
    *,
    up_to_chapter: int,
    full_text: str,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    max_tokens: int = DEFAULT_RECAP_MAX_TOKENS,
    session_id: str | None = None,
) -> list[dict[str, Any]] | None:
    """回顾读到第 ``up_to_chapter`` 章为止的前情；失败返 ``None``。

    ``full_text`` / ``chunks`` 由调用方**截到 ≤X 章**后传入（后文不喂 = 结构性无剧透）。
    每条 point 的 snippet 过 verify_citations（对照的也只有 ≤X 的 chunks）+ 真章号纠偏。

    Returns:
        ``[{order, point, chapter, snippet, verified}, ...]`` 按 order 排；失败 ``None``。
    """
    _ = session_id
    evidence_map = {
        str(c["chunk_id"]): {"chapter": c.get("chapter", 0), "text": c.get("text", "")}
        for c in chunks
        if c.get("chunk_id")
    }
    system = _system_instruction(up_to_chapter) + _BOOK_DELIMITER + full_text
    messages = [{"role": "user", "content": "请回顾到目前为止的前情。"}]
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
                "recap LLM call raised %s: %s (attempt %d)",
                type(exc).__name__, exc, attempt,
            )
            continue
        points = _parse_points(llm_client.extract_final_text(response))
        if points is None:
            logger.warning("recap parse failed (attempt %d/%d)", attempt, _MAX_ATTEMPTS)
            continue
        for pt in points:
            # 带上 LLM 自报章号当多命中消歧弱先验（真章号在 verify 后用 chunk_id 覆盖）；
            # chapter 为 0 = 模型没报，不传，退回确定性首个。
            self_ch = pt.get("chapter")
            cit: dict[str, Any] = {"snippet": pt["snippet"]}
            if isinstance(self_ch, int) and self_ch > 0:
                cit["chapter"] = self_ch
            cits = [cit]
            verify_citations(cits, evidence_map)
            vc = cits[0]
            pt["verified"] = bool(vc.get("verified", False))
            cid = vc.get("chunk_id")
            true_ch = evidence_map.get(cid, {}).get("chapter") if cid else None
            if isinstance(true_ch, int) and true_ch > 0:
                pt["chapter"] = true_ch
        return points
    return None


__all__ = ["DEFAULT_RECAP_MAX_TOKENS", "generate_recap"]
