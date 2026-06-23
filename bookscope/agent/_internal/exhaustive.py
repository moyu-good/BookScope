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


def run_segments(
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
) -> list[list[dict[str, Any]]]:
    """map 引擎：按字符预算分段 → 并发逐段抽 → 返回**每段**解析出的条目列表（不合并）。

    每段用 ``build_longctx_system(段原文, instruction)`` 跑一次（段内条目数远小于功能自带的
    ~40 帽，所以不必改 instruction）。``parse_fn`` 把单段输出解析成 ``[{...}]``。单段失败 /
    解析不出 → 该段返 ``[]``，不拖垮整体。reduce（合并）由调用方按各功能的 key 决定，所以这里
    只返回 ``list[每段条目列表]``，保段序（段按章序排，所以"先出现"= 章靠前的段）。

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
        return [run_segment(s) for s in segments]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(run_segment, segments))


def merge_by_chapter(outs: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """reduce（逐章型）：跨段按 ``chapter`` concat 去重（保先出现）→ 升序。

    章是 disjoint 的（每段一段连续章），合并就是拼接 + 按章去重。用于 character_flow /
    narrative_curve 这类"每章一条"的逐章功能。
    """
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


def merge_by_key(
    outs: list[list[dict[str, Any]]], *, key_fn: Callable[[dict[str, Any]], Any]
) -> list[dict[str, Any]]:
    """reduce（列表型）：跨段把条目 concat，按 ``key_fn(item)`` 去重（保先出现）。

    用于 timeline / foreshadow / argument 这类"全书一批条目"的列表功能——同一条目可能在
    相邻段都被抽到（如跨段的事件、伏笔），按身份 key 去重。``key_fn`` 返回 ``None`` 的条目
    丢弃。``order`` 之类的序号字段由调用方在合并后重排（段内序号跨段会重复）。
    """
    seen: set[Any] = set()
    merged: list[dict[str, Any]] = []
    for lst in outs:
        for item in lst:
            try:
                k = key_fn(item)
            except Exception:  # noqa: BLE001 — key 取不出就当无法去重，丢
                continue
            if k is None or k in seen:
                continue
            seen.add(k)
            merged.append(item)
    return merged


def merge_keyed_points(
    outs: list[list[dict[str, Any]]],
    *,
    key_fn: Callable[[dict[str, Any]], Any],
    point_fields: list[str],
    point_key: str = "chapter",
) -> list[dict[str, Any]]:
    """reduce（带子点型）：按 ``key_fn`` 合并条目，每个条目内的子点列表跨段按章并集。

    用于 character_arc（key=角色名，子点=points）/ relationship_timeline（key=无向对，
    子点=points + turning_points）这类"每个实体一串逐章子点"的功能。合并规则：

    - 标量字段（name / relation / a / b …）：保先出现段的值（段按章序，先=靠前章）。
    - ``point_fields`` 里每个字段：跨段把子点列表 concat，按 ``point_key``（默认 chapter）
      去重（保先出现）+ 升序。段是 disjoint 章区间，所以同实体在不同段的子点天然不撞章。

    ``key_fn`` 返回 ``None`` 的条目丢弃。
    """
    order: list[Any] = []
    bucket: dict[Any, dict[str, Any]] = {}
    for lst in outs:
        for item in lst:
            try:
                k = key_fn(item)
            except Exception:  # noqa: BLE001
                continue
            if k is None:
                continue
            if k not in bucket:
                merged_item = {kk: vv for kk, vv in item.items() if kk not in point_fields}
                for f in point_fields:
                    merged_item[f] = []
                bucket[k] = merged_item
                order.append(k)
            tgt = bucket[k]
            for f in point_fields:
                src = item.get(f)
                if not isinstance(src, list):
                    continue
                seen_pts = {p.get(point_key) for p in tgt[f] if isinstance(p, dict)}
                for p in src:
                    if not isinstance(p, dict):
                        continue
                    pk = p.get(point_key)
                    if pk in seen_pts:
                        continue
                    seen_pts.add(pk)
                    tgt[f].append(p)
    out: list[dict[str, Any]] = []
    for k in order:
        item = bucket[k]
        for f in point_fields:
            item[f].sort(
                key=lambda p: p.get(point_key)
                if isinstance(p.get(point_key), int)
                else 0
            )
        out.append(item)
    return out


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
    """按章 map-reduce 便捷壳：``run_segments`` + ``merge_by_chapter``。

    用于 character_flow / narrative_curve 这类"每章一条"的逐章功能。校验交给调用方
    （合并后一次性 verify）。子点型 / 列表型功能改用 ``run_segments`` + 对应 merge。
    """
    outs = run_segments(
        chunks=chunks,
        instruction=instruction,
        user_msg=user_msg,
        parse_fn=parse_fn,
        llm_client=llm_client,
        model=model,
        max_tokens=max_tokens,
        char_budget=char_budget,
        max_workers=max_workers,
        cache_enabled=cache_enabled,
    )
    return merge_by_chapter(outs)


__all__ = [
    "segment_chunks",
    "resolve_workers",
    "run_segments",
    "merge_by_chapter",
    "merge_by_key",
    "merge_keyed_points",
    "mapreduce_per_chapter",
    "DEFAULT_CHAR_BUDGET",
]
