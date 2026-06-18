"""实体回溯快查：给一个实体，回溯它在全书的所有出现处，每处带原文出处。

读长书时"这人/这物之前在哪出现过、做过啥"靠手动翻——费劲又易漏。给一个实体（人物/
地点/物件/概念），长上下文读全书、按章节先后列出每次出现 + 该处在做什么 + 一句原文依据。

复用 [[project_wholebook_feature_pattern]]：长上下文整本进 context + 结构化 JSON +
三守卫（够 token / 关缓存 / 重试 + 截断抢救）。每处 evidence 过 verify_citations，标
verified + 用命中 chunk 真章号纠偏（evidence-first：出现也要落到原文）。

与 timeline 的两点不同：
1. **实体放 user 消息**（system = 指令 + 书，跨不同实体查询不变 → DeepSeek 前缀缓存命中）。
2. **空 appearances 是合法结果**（实体不在书里 → 返回 ``[]``），区别于解析失败（``None``）——
   这是命根子：不为不存在的实体编造出现（probe 实测假阳性 0%）。
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

DEFAULT_ENTITY_RECALL_MAX_TOKENS = 8000
"""高频实体出现多（probe 实测安禄山单次 41 处），长输出，配截断抢救。"""
_MAX_ATTEMPTS = 2
_MAX_APPEARANCES = 60

_SYSTEM_INSTRUCTION = (
    "你是 BookScope 的实体回溯助手。下面 === 全书原文 === 之后是一整本书的全文。"
    "用户会给一个实体（人物 / 地点 / 物件 / 概念）。请只根据这本书的原文，回溯该实体"
    "在全书的所有出现处，按章节先后排列。每处给：所在章节、该处在做什么（一句）、"
    "一句原文逐字依据。\n"
    "严格输出 JSON（不要别的话、不要 markdown 代码围栏）：\n"
    '{"appearances": [{"order": 序号整数, "chapter": 章号整数, '
    '"what": "该处在做什么", "snippet": "原文逐字片段"}]}\n'
    "order 从 1 起、按章节先后递增；snippet 必须是原文里逐字出现的句子。"
    '**书里没有这个实体就返回 {"appearances": []}——绝不为不存在的实体编造出现或原文。**'
)

_BOOK_DELIMITER = "\n\n=== 全书原文 ===\n"


def _resp_field(resp: Any, field: str) -> Any:
    if resp is None:
        return None
    if isinstance(resp, dict):
        return resp.get(field)
    return getattr(resp, field, None)


def _coerce(raw: Any) -> list[dict[str, Any]] | None:
    """结构合法（含 ``appearances`` 列表）→ 收编后的 list（**可能为空 = 合法"没找到"**）；
    结构非法（非 dict / 无 appearances 列表）→ ``None``（触发抢救/重试）。"""
    if not isinstance(raw, dict):
        return None
    items = raw.get("appearances")
    if not isinstance(items, list):
        return None
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        snippet = str(item.get("snippet", "")).strip()
        if not snippet:  # 无原文片段 = 无证据，丢
            continue
        order = item.get("order")
        chapter = item.get("chapter")
        out.append({
            "order": order if isinstance(order, int) else len(out) + 1,
            "chapter": chapter if isinstance(chapter, int) else 0,
            "what": str(item.get("what", "")).strip(),
            "snippet": snippet,
        })
        if len(out) >= _MAX_APPEARANCES:
            break
    out.sort(key=lambda a: a["order"])
    return out  # 空列表是合法结果（实体不在书里），不返 None


def _salvage_truncated(text: str) -> list[dict[str, Any]] | None:
    """从截断的 JSON 里抠出 ``appearances`` 数组中已闭合的完整对象（同 timeline 抢救）。

    高频实体出现多，输出可能超 max_tokens 截断成半截 JSON。括号匹配逐个抠完整 {...}，
    拼部分轨迹，比整张丢掉返空好（probe 实测杨国忠超高频会截断）。
    """
    idx = text.find('"appearances"')
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
    return _coerce({"appearances": raw_items}) if raw_items else None


def _parse_appearances(text: str) -> list[dict[str, Any]] | None:
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
            "entity_recall: 主解析失败，从截断输出抢救到 %d 处", len(salvaged)
        )
    return salvaged


def generate_entity_recall(
    *,
    entity: str,
    full_text: str,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    max_tokens: int = DEFAULT_ENTITY_RECALL_MAX_TOKENS,
    session_id: str | None = None,
) -> list[dict[str, Any]] | None:
    """回溯实体的全书出现处；失败返 ``None``，实体不在书里返 ``[]``。

    每处 evidence 过 verify_citations 标 verified + 真章号纠偏。保留全部出现（含未命中的，
    标 verified=False 供用户判断 + 前端只在 verified 上盖钤印）。

    Returns:
        ``[{order, chapter, what, snippet, verified}, ...]`` 按 order 排；
        ``[]`` = 书里没这个实体（合法）；``None`` = 解析/调用失败。
    """
    _ = session_id
    entity = (entity or "").strip()
    if not entity:
        return None
    evidence_map = {
        str(c["chunk_id"]): {"chapter": c.get("chapter", 0), "text": c.get("text", "")}
        for c in chunks
        if c.get("chunk_id")
    }
    system = _SYSTEM_INSTRUCTION + _BOOK_DELIMITER + full_text
    messages = [{"role": "user", "content": f"请回溯实体「{entity}」在全书的出现处。"}]
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
                "entity_recall LLM call raised %s: %s (attempt %d)",
                type(exc).__name__, exc, attempt,
            )
            continue
        appearances = _parse_appearances(llm_client.extract_final_text(response))
        if appearances is None:
            logger.warning(
                "entity_recall parse failed (attempt %d/%d)", attempt, _MAX_ATTEMPTS
            )
            continue
        for ap in appearances:
            # 带上 LLM 自报章号当多命中消歧弱先验（真章号在 verify 后用 chunk_id 覆盖）；
            # chapter 为 0 = 模型没报，不传，退回确定性首个。
            self_ch = ap.get("chapter")
            cit: dict[str, Any] = {"snippet": ap["snippet"]}
            if isinstance(self_ch, int) and self_ch > 0:
                cit["chapter"] = self_ch
            cits = [cit]
            verify_citations(cits, evidence_map)
            vc = cits[0]
            ap["verified"] = bool(vc.get("verified", False))
            cid = vc.get("chunk_id")
            true_ch = evidence_map.get(cid, {}).get("chapter") if cid else None
            if isinstance(true_ch, int) and true_ch > 0:
                ap["chapter"] = true_ch
        return appearances
    return None


__all__ = ["DEFAULT_ENTITY_RECALL_MAX_TOKENS", "generate_entity_recall"]
