"""节奏 / 张力曲线：据整本书逐章判张力高低，出可视化用的结构化曲线（exp-012 GO）。

exp-012 验过 agent 能可靠判节奏（哪章松/哪章紧），且不附和虚假框架。本模块把它做成
逐章张力打分（1-5），供前端画曲线——作家一眼看出拖沓章 / 高潮章。

复用 long_context 形态（整本进 context）。**一开始就焊进结构化输出三教训**（关系图 502 /
每书出题 poison 学到的）：够 max_tokens 防 reasoning 吃 token 截断、cache_enabled=False 防
坏响应被缓存、解析失败重试一次。契约同 long_context：失败返 None。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from bookscope.agent._internal.llm_cache import invoke_client_cached as _invoke_client
from bookscope.agent._internal.longctx_system import build_longctx_system
from bookscope.agent.utils.json_parsing import (
    extract_first_json_object as _extract_first_json_object,
)
from bookscope.agent.utils.json_parsing import (
    strip_code_fence as _strip_code_fence,
)

logger = logging.getLogger(__name__)

DEFAULT_PACING_MAX_TOKENS = 4000
"""逐章打分 + 一句依据，~25-30 章约 1500-2500 token；给 4000 留 reasoning 头。"""

_MAX_ATTEMPTS = 2

_SYSTEM_INSTRUCTION = (
    "你是 BookScope 的节奏分析助手。"
    "请逐章（或逐主要部分）判断节奏张力的高低，给每章打 1-5 分"
    "（1=最松：铺垫/制度/背景多、冲突少；5=最紧：高潮/激烈冲突/转折），"
    "并一句话说明依据（点名这章的具体内容）。只依据原文，不臆测。\n"
    "严格输出 JSON（不要别的话、不要 markdown 代码围栏）：\n"
    '{"chapters": [{"chapter": 章号整数, "tension": 1到5整数, "note": "一句依据"}]}\n'
    "按章号从小到大排列，覆盖主要章节（最多约 40 章）。"
)


def _coerce_points(raw: Any) -> list[dict[str, Any]]:
    """保留 chapter(int) + tension(1-5 int) 齐全的点；note 可缺。按章号排序。"""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        ch = item.get("chapter")
        tn = item.get("tension")
        if not isinstance(ch, int) or not isinstance(tn, int):
            continue
        if ch in seen:
            continue
        seen.add(ch)
        out.append({
            "chapter": ch,
            "tension": max(1, min(5, tn)),  # 夹到 1-5
            "note": str(item.get("note", "")).strip(),
        })
    out.sort(key=lambda p: p["chapter"])
    return out


def _parse_curve(text: str) -> list[dict[str, Any]] | None:
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
        points = _coerce_points(obj.get("chapters"))
        if points:
            return points
    return None


def generate_pacing_curve(
    *,
    full_text: str,
    llm_client: Any,
    model: str,
    max_tokens: int = DEFAULT_PACING_MAX_TOKENS,
    session_id: str | None = None,
) -> list[dict[str, Any]] | None:
    """据整本书出逐章张力曲线；失败返 ``None``。

    Args:
        full_text: 整本书 cleaned 原文。
        llm_client: duck-typed LLM client（同 AgentLoop）。
        model: 模型名。
        max_tokens: 单次 LLM 调用 max_tokens。
        session_id: 仅签名兼容——本任务关缓存（防坏响应被 poison）。

    Returns:
        ``[{"chapter": int, "tension": 1-5, "note": str}, ...]`` 按章号排序；失败 ``None``。
    """
    _ = session_id
    system = build_longctx_system(full_text, _SYSTEM_INSTRUCTION)
    messages = [{"role": "user", "content": "请据这本书出逐章节奏张力曲线。"}]
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
                "pacing_curve LLM call raised %s: %s (attempt %d)",
                type(exc).__name__, exc, attempt,
            )
            continue
        points = _parse_curve(llm_client.extract_final_text(response))
        if points is not None:
            return points
        logger.warning("pacing_curve parse failed (attempt %d/%d)", attempt, _MAX_ATTEMPTS)
    return None


__all__ = ["DEFAULT_PACING_MAX_TOKENS", "generate_pacing_curve"]
