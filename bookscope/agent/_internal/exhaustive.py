"""穷尽化(1.4)的可复用件:分段 + 并发 + 按章 map-reduce。

重型逐章功能(多维叙事曲线 / 叙事流……每章带 evidence、多字段)单次调用扛不住整本——
叫它覆盖 120 章会被 max_tokens 截断到几章。改 map-reduce:**按字符预算分段 → 每段单独
逐章抽(段内章少、远不到帽)→ 按章 concat 去重**。章是 disjoint 的,所以"合并"就是拼接 +
去重,比关系图的 edge 合并还简单。

紧凑逐章(节奏曲线:每章只一句)不用这个——拆帽 + 加 max_tokens 单次就够。判据见
memory project_exhaustive_extraction_pattern。
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from bookscope.agent._internal.llm_cache import invoke_client_cached
from bookscope.agent._internal.longctx_system import build_longctx_system

logger = logging.getLogger(__name__)

DEFAULT_CHAR_BUDGET = 40000
DEFAULT_WORKERS = 6
ENV_WORKERS = "BOOKSCOPE_EXHAUSTIVE_WORKERS"


def segment_chunks(
    chunks: list[dict[str, Any]], char_budget: int = DEFAULT_CHAR_BUDGET
) -> list[list[dict[str, Any]]]:
    """按字符预算把全书 chunks 切成若干段（保序，不打散单个 chunk）。"""
    segments: list[list[dict[str, Any]]] = []
    cur: list[dict[str, Any]] = []
    cur_len = 0
    for c in chunks:
        t = str(c.get("text", ""))
        if cur and cur_len + len(t) > char_budget:
            segments.append(cur)
            cur = []
            cur_len = 0
        cur.append(c)
        cur_len += len(t)
    if cur:
        segments.append(cur)
    return segments


def resolve_workers(explicit: int | None, default: int = DEFAULT_WORKERS) -> int:
    """逐段并发数：构造参数 > 环境变量 > 默认；< 1 兜底 1（串行）。"""
    if explicit is not None:
        return max(1, explicit)
    raw = os.environ.get(ENV_WORKERS)
    if not raw or not raw.strip():
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def mapreduce_per_chapter(
    *,
    chunks: list[dict[str, Any]],
    instruction: str,
    user_msg: str,
    parse_fn: Callable[[str], list[dict[str, Any]] | None],
    llm_client: Any,
    model: str,
    max_tokens: int,
    char_budget: int = DEFAULT_CHAR_BUDGET,
    max_workers: int | None = None,
    cache_enabled: bool = True,
) -> list[dict[str, Any]]:
    """按章 map-reduce:分段并发逐章抽 → 按 ``chapter`` concat 去重 → 升序。

    每段用 ``build_longctx_system(段原文, instruction)`` 跑一次（段内章数远小于功能自带的
    ~40 章帽，所以不必改 instruction）。``parse_fn`` 把单段输出解析成 ``[{chapter, ...}]``。
    单段失败 / 解析不出 → 跳过该段，不拖垮整条曲线。校验交给调用方（合并后一次性 verify）。

    缓存默认开：同段同书重看直接命中（map-reduce 下坏段只跳过、不一坏全挂，开缓存安全）。
    """
    segments = segment_chunks(chunks, char_budget)
    if not segments:
        return []

    def run_segment(seg: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seg_text = "".join(str(c.get("text", "")) for c in seg)
        system = build_longctx_system(seg_text, instruction)
        try:
            resp = invoke_client_cached(
                llm_client,
                model=model,
                system=system,
                tools=[],
                messages=[{"role": "user", "content": user_msg}],
                max_tokens=max_tokens,
                cache_enabled=cache_enabled,
            )
        except Exception as exc:  # noqa: BLE001 — 单段失败跳过
            logger.warning("exhaustive 段调用抛 %s: %s；跳过该段", type(exc).__name__, exc)
            return []
        try:
            return parse_fn(llm_client.extract_final_text(resp)) or []
        except Exception as exc:  # noqa: BLE001
            logger.warning("exhaustive 段解析抛 %s；跳过该段", type(exc).__name__)
            return []

    workers = resolve_workers(max_workers)
    if workers <= 1 or len(segments) <= 1:
        outs = [run_segment(s) for s in segments]
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            outs = list(ex.map(run_segment, segments))

    seen: set[int] = set()
    merged: list[dict[str, Any]] = []
    for lst in outs:
        for item in lst:
            ch = item.get("chapter")
            if not isinstance(ch, int) or ch in seen:
                continue
            seen.add(ch)
            merged.append(item)
    merged.sort(key=lambda c: c["chapter"])
    return merged


__all__ = ["segment_chunks", "resolve_workers", "mapreduce_per_chapter", "DEFAULT_CHAR_BUDGET"]
