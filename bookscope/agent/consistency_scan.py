"""设定一致性扫描：主动扫全书找前后矛盾（exp-011 GO）。

exp-011 验过 agent 能找跨章设定矛盾（找到率 100% + 假阳性 0%），但之前只能"问"才
触发。本模块做成主动扫描：列出全书的设定/人物前后矛盾，每条带两处对照原文 + 章号。

**命根子是双向的**（exp-011）：既要找得到真矛盾，又**绝不能编**书里不存在的矛盾——
编矛盾的功能比没有更糟（让作家去改本来没错的地方）。代码层焊两道命根子守卫：
1. prompt 明列"不算矛盾"的三种（号称/实有、不同史料来源、视角/时间变化）——顺手解决
   exp-011 CP2 暴露的"实有X号称Y被误判矛盾"过敏。
2. 每条矛盾的两处证据都过 verify_citations，**两处都核验命中才保留**——编的矛盾没真
   原文支撑，自然被丢。

复用 [[project_wholebook_feature_pattern]]：长上下文整本进 context + 结构化 JSON +
三可靠性守卫（够 token / 关缓存 / 重试）。anshi 等自洽出版书上正确行为是扫出极少/0。
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

DEFAULT_SCAN_MAX_TOKENS = 4000
_MAX_ATTEMPTS = 2

_SYSTEM_INSTRUCTION = (
    "你是 BookScope 的设定一致性检查助手。"
    "请扫描全书，找出**真正的前后矛盾**——同一个设定 / 人物 / 事实，在不同章节前后说法"
    "打架（如第 5 章说某人是左撇子、第 80 章用右手）。\n"
    "**只列真矛盾，宁缺毋滥。** 以下都【不算】矛盾，绝不要列：\n"
    "① 同一事物的不同口径（如『实有十五万、对外号称二十万』——这是自洽的）；\n"
    "② 不同史料 / 来源给的不同数字（作者并列引用多方记载，不是自相矛盾）；\n"
    "③ 不同视角 / 不同时间点的合理变化（人物成长、立场随事件演变）。\n"
    "严格输出 JSON（不要别的话、不要 markdown 代码围栏）：\n"
    '{"contradictions": [{"topic": "矛盾涉及的设定", "conflict": "一句话说矛盾在哪", '
    '"a": {"snippet": "前一处原文逐字", "chapter": 章号整数}, '
    '"b": {"snippet": "后一处原文逐字", "chapter": 章号整数}}]}\n'
    "snippet 必须是原文里逐字出现的句子。"
    "书里没有真矛盾，就返回空数组：{\"contradictions\": []}。"
)


def _resp_field(resp: Any, field: str) -> Any:
    if resp is None:
        return None
    if isinstance(resp, dict):
        return resp.get(field)
    return getattr(resp, field, None)


def _coerce(raw: Any) -> list[dict[str, Any]] | None:
    """解析 contradictions；合法 JSON（含空数组）返 list，结构不对返 None。"""
    if not isinstance(raw, dict):
        return None
    items = raw.get("contradictions")
    if not isinstance(items, list):
        return None
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        a = item.get("a")
        b = item.get("b")
        if not isinstance(a, dict) or not isinstance(b, dict):
            continue
        a_snip = str(a.get("snippet", "")).strip()
        b_snip = str(b.get("snippet", "")).strip()
        if not a_snip or not b_snip:
            continue
        out.append({
            "topic": str(item.get("topic", "")).strip(),
            "conflict": str(item.get("conflict", "")).strip(),
            "a": {"snippet": a_snip, "chapter": a.get("chapter", 0)},
            "b": {"snippet": b_snip, "chapter": b.get("chapter", 0)},
        })
    return out  # 空 list 合法（自洽书）


def _parse_scan(text: str) -> list[dict[str, Any]] | None:
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
    return _coerce(obj)


def _verify_side(side: dict[str, Any], evidence: dict[str, dict]) -> bool:
    """核验一处证据：snippet 命中原文则 verified、用命中 chunk 真章号纠偏。"""
    # 带上这处证据的 LLM 自报章号当多命中消歧弱先验（真章号在 verify 后用 chunk_id 覆盖）；
    # 章号缺/非正整数时不传，退回确定性首个。
    self_ch = side.get("chapter")
    cit: dict[str, Any] = {"snippet": side["snippet"]}
    if isinstance(self_ch, int) and self_ch > 0:
        cit["chapter"] = self_ch
    cits = [cit]
    verify_citations(cits, evidence)
    vc = cits[0]
    side["verified"] = bool(vc.get("verified", False))
    side["match_type"] = vc.get("match_type", "none")
    cid = vc.get("chunk_id")
    true_ch = evidence.get(cid, {}).get("chapter") if cid else None
    if isinstance(true_ch, int) and true_ch > 0:
        side["chapter"] = true_ch
    return side["verified"]


def generate_consistency_scan(
    *,
    full_text: str,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    max_tokens: int = DEFAULT_SCAN_MAX_TOKENS,
    session_id: str | None = None,
) -> list[dict[str, Any]] | None:
    """扫全书找设定矛盾；失败返 ``None``，自洽书返 ``[]``（空但成功）。

    每条矛盾两处证据都过 verify_citations，**两处都命中才保留**（命根子：编的矛盾没
    真原文）。返回的矛盾按 topic 去重。

    Returns:
        矛盾列表（可空——自洽书）；解析失败返 ``None``（调用方区分"没矛盾"和"扫失败"）。
    """
    _ = session_id
    evidence = {
        str(c["chunk_id"]): {"chapter": c.get("chapter", 0), "text": c.get("text", "")}
        for c in chunks
        if c.get("chunk_id")
    }
    system = build_longctx_system(full_text, _SYSTEM_INSTRUCTION)
    messages = [{"role": "user", "content": "请扫描全书的设定一致性，列出真正的前后矛盾。"}]
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
                "consistency_scan LLM call raised %s: %s (attempt %d)",
                type(exc).__name__, exc, attempt,
            )
            continue
        parsed = _parse_scan(llm_client.extract_final_text(response))
        if parsed is None:
            logger.warning("consistency_scan parse failed (attempt %d/%d)", attempt, _MAX_ATTEMPTS)
            continue
        # 命根子守卫：两处证据都核验命中才保留（编的矛盾过不了）。
        kept: list[dict[str, Any]] = []
        seen: set[str] = set()
        for c in parsed:
            a_ok = _verify_side(c["a"], evidence)
            b_ok = _verify_side(c["b"], evidence)
            key = c["topic"] or c["conflict"]
            if a_ok and b_ok and key not in seen:
                seen.add(key)
                kept.append(c)
        return kept  # 可空（自洽书 / 候选全被命根子守卫滤掉）
    return None


__all__ = ["DEFAULT_SCAN_MAX_TOKENS", "generate_consistency_scan"]
