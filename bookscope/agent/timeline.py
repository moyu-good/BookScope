"""时间线 / 事件梳理：据整本书按时序梳理主要事件，每条带原文出处。

读者发明区——读复杂叙事（多线、倒叙、人物众多）容易乱时序。本模块抽全书主要事件、
按时间先后排，每条带所在章节 + 一句原文依据。

复用 [[project_wholebook_feature_pattern]]：长上下文整本进 context + 结构化 JSON +
三守卫（够 token / 关缓存 / 重试）。每条事件的 evidence 过 verify_citations，标 verified
+ 用命中 chunk 真章号纠偏（evidence-first：事件也要落到原文）。
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
    strip_code_fence as _strip_code_fence,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMELINE_MAX_TOKENS = 8000
"""时间线 30 事件 × 整句证据是长输出（≈关系图体量），4000 会被 reasoning+内容撑爆截断。"""
_MAX_ATTEMPTS = 2
_MAX_EVENTS = 40

_SYSTEM_INSTRUCTION = (
    "你是 BookScope 的时间线梳理助手。下面 === 全书原文 === 之后是一整本书的全文。"
    "请按**时间先后**梳理书中的主要事件——多线叙事 / 倒叙也要还原成真实发生顺序。"
    "每条给：事件、发生时间（书里写明的，没写就留空）、所在章节、一句原文依据。\n"
    "严格输出 JSON（不要别的话、不要 markdown 代码围栏）：\n"
    '{"events": [{"order": 序号整数, "time": "时间或空字符串", "event": "事件一句话", '
    '"chapter": 章号整数, "evidence": "原文逐字片段"}]}\n'
    "order 从 1 起、按真实时间先后递增。只列书里真有的主要事件（最多约 30 条），"
    "evidence 必须是原文里逐字出现的句子。"
)

_BOOK_DELIMITER = "\n\n=== 全书原文 ===\n"


def _resp_field(resp: Any, field: str) -> Any:
    if resp is None:
        return None
    if isinstance(resp, dict):
        return resp.get(field)
    return getattr(resp, field, None)


def _coerce(raw: Any) -> list[dict[str, Any]] | None:
    if not isinstance(raw, dict):
        return None
    items = raw.get("events")
    if not isinstance(items, list):
        return None
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        event = str(item.get("event", "")).strip()
        if not event:
            continue
        order = item.get("order")
        out.append({
            "order": order if isinstance(order, int) else len(out) + 1,
            "time": str(item.get("time", "")).strip(),
            "event": event,
            "chapter": item.get("chapter", 0) if isinstance(item.get("chapter"), int) else 0,
            "evidence": str(item.get("evidence", "")).strip(),
        })
        if len(out) >= _MAX_EVENTS:
            break
    out.sort(key=lambda e: e["order"])
    return out or None


def _salvage_truncated(text: str) -> list[dict[str, Any]] | None:
    """从截断的 JSON 里抠出 "events" 数组中已闭合的完整事件对象（同关系图 502 的抢救）。

    时间线是长输出，reasoning + 内容可能撑爆 max_tokens 截断成半截 JSON，整段 loads 必败。
    括号匹配逐个抠完整 {...}，拼部分时间线，比整张丢掉返空好。
    """
    idx = text.find('"events"')
    if idx == -1:
        return None
    start = text.find("[", idx)
    if start == -1:
        return None
    raw_events: list[Any] = []
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
            raw_events.append(json.loads(text[i:j]))
        except json.JSONDecodeError:
            pass
        i = j
    return _coerce({"events": raw_events}) if raw_events else None


def _parse_timeline(text: str) -> list[dict[str, Any]] | None:
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
    # 兜底：截断输出抢救完整事件
    salvaged = _salvage_truncated(candidate)
    if salvaged:
        logger.warning("timeline: 主解析失败，从截断输出抢救到 %d 个事件", len(salvaged))
    return salvaged


def generate_timeline(
    *,
    full_text: str,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    max_tokens: int = DEFAULT_TIMELINE_MAX_TOKENS,
    session_id: str | None = None,
) -> list[dict[str, Any]] | None:
    """据整本书出按时序的事件列表；失败返 ``None``。

    每条事件的 evidence 过 verify_citations，标 verified + 真章号。保留全部事件（含 evidence
    未命中的，标 verified=False 供用户判断；时间线重完整性，不像矛盾扫描那样硬滤）。

    Returns:
        ``[{order, time, event, chapter, evidence, verified}, ...]`` 按 order 排；失败 ``None``。
    """
    _ = session_id
    evidence_map = {
        str(c["chunk_id"]): {"chapter": c.get("chapter", 0), "text": c.get("text", "")}
        for c in chunks
        if c.get("chunk_id")
    }
    system = _SYSTEM_INSTRUCTION + _BOOK_DELIMITER + full_text
    messages = [{"role": "user", "content": "请据这本书按时序梳理主要事件。"}]
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
                "timeline LLM call raised %s: %s (attempt %d)",
                type(exc).__name__, exc, attempt,
            )
            continue
        events = _parse_timeline(llm_client.extract_final_text(response))
        if events is None:
            logger.warning("timeline parse failed (attempt %d/%d)", attempt, _MAX_ATTEMPTS)
            continue
        for ev in events:
            # 带上 LLM 自报章号当多命中消歧弱先验（真章号在 verify 后用 chunk_id 覆盖）；
            # chapter 为 0 = 模型没报，不传，退回确定性首个。
            self_ch = ev.get("chapter")
            cit: dict[str, Any] = {"snippet": ev["evidence"]}
            if isinstance(self_ch, int) and self_ch > 0:
                cit["chapter"] = self_ch
            cits = [cit]
            verify_citations(cits, evidence_map)
            vc = cits[0]
            ev["verified"] = bool(vc.get("verified", False))
            cid = vc.get("chunk_id")
            true_ch = evidence_map.get(cid, {}).get("chapter") if cid else None
            if isinstance(true_ch, int) and true_ch > 0:
                ev["chapter"] = true_ch
        return events
    return None


__all__ = ["DEFAULT_TIMELINE_MAX_TOKENS", "generate_timeline"]
