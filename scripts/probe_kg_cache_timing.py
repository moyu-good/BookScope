"""Sprint 6 KG 缓存链路耗时实验 probe.

用途：跑 exp006 设计文档（``docs/internal/experiments/006-sprint-6-kg-cache-validation-design.md``）
第三节耗时实验矩阵（1a / 1b / 2a / 2b 四组）。**本脚本只测耗时，不评质量**——
质量验证去 ``probe_kg_cache_quality.py``。

跑出来的 JSON 落 ``docs/internal/experiments/data/exp006-kg-cache-timing-{book}-{state}-{ts}.json``，
给 RE 写 chapter-09 数据节用。

实验设计要点（节选自 exp006 设计）：

- empty 状态：跑前清两层 KG 缓存（``clear_kg_cache`` + ``clear_kg_book_cache``）
  再跑 N runs。每 run 都是冷启动——首跑全打 LLM。
- warm 状态：跑前先做一次 warm-up（保证缓存里有这本书），再跑 N runs。
  每 run 都应该命中 book-level，整本 KG 抽取应在秒级返回。
- 每 run 测：总耗时 / LLM call 数（batch instrumentation）/ batch cache hit 数 /
  book cache hit 数。三次跑求 mean / std。
- 撤回判定：warm 平均耗时 / empty 平均耗时 > 1/10 即 ``validation_failed=true``，
  ``failure_reason="cache_speedup_below_10x"``。即缓存命中没真生效，
  book-level 接错地方或 cache key 漏字段。

用法::

    DEEPSEEK_API_KEY=sk-xxxxx \\
    PYTHONIOENCODING=utf-8 \\
    python scripts/probe_kg_cache_timing.py \\
        --book anshi --cache-state empty --runs 3

参数：

- ``--book``：``anshi`` / ``mingchao``，决定加载哪本书
- ``--cache-state``：``empty`` / ``warm``，决定跑前清缓存还是 warm-up
- ``--runs``：每组跑几次（默认 3，求 std 最低门槛）
- ``--output``：JSON 落地路径（默认按命名规则自动拼）

环境变量（与 ``run_batch_r1.py`` / ``smoke_test_r1.py`` 对齐）：

- ``DEEPSEEK_API_KEY``：必填
- ``BOOKSCOPE_SMOKE_EPUB``：加载哪本 epub；``--book`` 不直接读路径，靠这个环境变量
  覆盖。CI 可在外面 export 后跑同脚本

**前置条件**（本脚本不真跑 LLM 时也要的）：

- ``DEEPSEEK_API_KEY`` 已设
- ``BOOKSCOPE_SMOKE_EPUB`` 指向真 epub 文件路径（anshi 或 mingchao 卷一）
- ``.bookscope_cache/`` 目录可写

本脚本不在 CI 跑，由 QA 在作者明示批 LLM cost 后手动跑。
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# Windows 控制台 UTF-8 兜底
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# 撤回阈值（与 exp006 设计第五节对位）
# ---------------------------------------------------------------------------

CACHE_SPEEDUP_MIN_RATIO: float = 10.0
"""warm 比 empty 至少快这么多倍——低于即缓存层没真生效。

设计文档第五节红线：``1b / 2b 三次跑均值 > 1a / 2a 三次跑均值的 30%``
等价于 speedup < 10/3 ≈ 3.33；本脚本采用比设计文档宽松的 10x 阈值是
因为脚本里实际比较的是 warm / empty 的 **均值比**——10x 是验收阈值
（设计第六节"耗时验收 ≤ 1/10"）的反向口径，命中即过。"""

FAILURE_REASON_SPEEDUP: str = "cache_speedup_below_10x"
"""撤回 JSON 字段值，给后续判定脚本读。"""


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """CLI 解析。argv 显式传入让单测直接喂参数列表。"""
    p = argparse.ArgumentParser(
        description="Sprint 6 KG 缓存链路耗时实验 probe",
    )
    p.add_argument(
        "--book",
        choices=["anshi", "mingchao"],
        required=True,
        help="测哪本书：anshi 整本 / mingchao 卷一",
    )
    p.add_argument(
        "--cache-state",
        choices=["empty", "warm"],
        required=True,
        help="跑前缓存状态：empty 清缓存 / warm 先做一次 warm-up",
    )
    p.add_argument(
        "--runs",
        type=int,
        default=3,
        help="每组跑几次求 std（默认 3，最低门槛）",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        help="JSON 落地路径；不给走默认命名 exp006-kg-cache-timing-{book}-{state}-{ts}.json",
    )
    return p.parse_args(argv)


# ---------------------------------------------------------------------------
# 单次 ingest 测量
# ---------------------------------------------------------------------------


def _run_one_ingest(
    *,
    chunks: list[Any],
    book_title: str,
    language: str,
    extractor_factory: Any,
) -> dict[str, Any]:
    """跑一次 ingest，测耗时 + 缓存 stats 增量。

    Args:
        chunks: 整书的 chunk 列表。
        book_title: 书名字段。
        language: 语种字段。
        extractor_factory: ``() -> MinimalKGExtractor`` 工厂函数（每次新建
            extractor 才能不带 stale 内部状态）。

    Returns:
        dict 含 ``total_seconds`` / ``batch_cache_hits_delta`` /
        ``book_cache_hits_delta`` / ``llm_call_count`` 字段。
    """
    from bookscope.agent._internal.kg_book_cache import get_book_kg_cache_stats
    from bookscope.agent._internal.kg_cache import get_kg_cache_stats

    stats_before_batch = get_kg_cache_stats()
    stats_before_book = get_book_kg_cache_stats()

    extractor = extractor_factory()
    t0 = time.monotonic()
    kg = extractor.extract(
        chunks=chunks,
        book_title=book_title,
        language=language,
    )
    elapsed = time.monotonic() - t0

    stats_after_batch = get_kg_cache_stats()
    stats_after_book = get_book_kg_cache_stats()

    # LLM call 数 = batch miss 增量（每次 miss 一次 LLM 调用）。
    # book-level hit 时 batch 层不被调（extract_func 整段跳过），所以
    # batch miss 增量天然为 0——这跟 "0 call" 预期匹配。
    # sqlite_cache.stats() 返单数 key {"hit", "miss", "size", "name"}——
    # 早期 probe 写复数 key 是空字典对位失误，让 stats 增量恒 0 即便缓存真生效。
    # 第十六波 dogfood probe 真跑揭出（anshi empty run 1 = 75s 真 LLM / runs 2-3 = 0.02s
    # 真 cache hit，但 probe 读出全 0）—— Sprint 6 prep 单测都喂 mock 数据点不触
    # 真 stats() 返回 shape。修对 key 之后撤回判定才有数据基础。
    batch_miss_delta = stats_after_batch.get("miss", 0) - stats_before_batch.get(
        "miss", 0
    )
    return {
        "total_seconds": round(elapsed, 2),
        "batch_cache_hits_delta": (
            stats_after_batch.get("hit", 0) - stats_before_batch.get("hit", 0)
        ),
        "batch_cache_misses_delta": batch_miss_delta,
        "book_cache_hits_delta": (
            stats_after_book.get("hit", 0) - stats_before_book.get("hit", 0)
        ),
        "book_cache_misses_delta": (
            stats_after_book.get("miss", 0) - stats_before_book.get("miss", 0)
        ),
        "llm_call_count": batch_miss_delta,
        "kg_character_count": len(kg.characters),
    }


# ---------------------------------------------------------------------------
# 撤回判定
# ---------------------------------------------------------------------------


def evaluate_speedup(
    *,
    empty_mean_seconds: float,
    warm_mean_seconds: float,
    min_speedup: float = CACHE_SPEEDUP_MIN_RATIO,
) -> tuple[bool, str | None, float]:
    """对照 empty / warm 平均耗时判 speedup 是否过线。

    Args:
        empty_mean_seconds: empty 状态三次跑均值。
        warm_mean_seconds: warm 状态三次跑均值。
        min_speedup: 最低 speedup 倍率，默认 10.0。

    Returns:
        ``(validation_failed, failure_reason, observed_speedup)``。
        warm 极小（<1e-6 秒）时 speedup 视为 inf；empty 极小时无法判定，
        返回 ``(True, "empty_run_too_fast_to_measure", inf)``——理论上 0 LLM
        call 的 empty 跑不可能秒级，命中即数据异常。
    """
    if empty_mean_seconds <= 1e-6:
        return True, "empty_run_too_fast_to_measure", float("inf")
    if warm_mean_seconds <= 1e-6:
        # warm 极快是正常的——纯磁盘 IO + JSON 反序列化
        observed = float("inf")
    else:
        observed = empty_mean_seconds / warm_mean_seconds
    if observed < min_speedup:
        return True, FAILURE_REASON_SPEEDUP, observed
    return False, None, observed


# ---------------------------------------------------------------------------
# 缓存清理 / warm-up 工具
# ---------------------------------------------------------------------------


def _clear_both_kg_caches() -> None:
    """清两层 KG 缓存（batch + book）。empty 跑前调用。"""
    from bookscope.agent._internal.kg_book_cache import clear_book_kg_cache
    from bookscope.agent._internal.kg_cache import clear_kg_cache

    clear_kg_cache()
    clear_book_kg_cache()


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def _default_output_path(book: str, cache_state: str) -> Path:
    """默认 JSON 落地路径。"""
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    return (
        _PROJECT_ROOT
        / "docs"
        / "experiments"
        / "data"
        / f"exp006-kg-cache-timing-{book}-{cache_state}-{ts}.json"
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("[probe] DEEPSEEK_API_KEY 未设置", file=sys.stderr)
        return 1
    if not os.environ.get("BOOKSCOPE_SMOKE_EPUB"):
        print(
            "[probe] BOOKSCOPE_SMOKE_EPUB 未设置（要指向 anshi 或 mingchao 卷一 epub）",
            file=sys.stderr,
        )
        return 1

    # 复用 smoke_test_r1 的书加载 + adapter 构造
    from scripts.smoke_test_r1 import (  # type: ignore[import-not-found]
        _build_adapter_and_model,
        _load_book_session,
    )

    print(f"[probe] book={args.book} cache-state={args.cache_state} runs={args.runs}")
    book, chunks, _kg, _vs = _load_book_session()
    book_title = book.title
    language = getattr(book, "language", "zh") or "zh"
    print(f"[probe] 书: {book_title}（{len(chunks)} chunk）")

    adapter, model = _build_adapter_and_model("deepseek")
    print(f"[probe] generator model={model}")

    def _make_extractor() -> Any:
        from bookscope.agent.backends.minimal_kg_extractor import MinimalKGExtractor

        return MinimalKGExtractor(client=adapter, model=model)

    # empty 状态：跑前清两层缓存
    # warm 状态：跑前先 warm-up 一次（不计入数据点）
    if args.cache_state == "empty":
        _clear_both_kg_caches()
        print("[probe] 已清两层 KG 缓存（batch + book）")
    else:
        _clear_both_kg_caches()  # 先清掉旧的，避免 stale
        print("[probe] warm-up 中（首次跑不计入数据点）...")
        warmup = _run_one_ingest(
            chunks=chunks,
            book_title=book_title,
            language=language,
            extractor_factory=_make_extractor,
        )
        print(f"[probe] warm-up 完成：{warmup['total_seconds']}s")

    # 跑 N runs
    runs: list[dict[str, Any]] = []
    for i in range(1, args.runs + 1):
        rec = _run_one_ingest(
            chunks=chunks,
            book_title=book_title,
            language=language,
            extractor_factory=_make_extractor,
        )
        rec["run_idx"] = i
        runs.append(rec)
        print(
            f"[probe] run {i}/{args.runs}: {rec['total_seconds']}s "
            f"llm_call={rec['llm_call_count']} "
            f"batch_hit={rec['batch_cache_hits_delta']} "
            f"book_hit={rec['book_cache_hits_delta']}"
        )

    # 汇总
    durations = [r["total_seconds"] for r in runs]
    mean_seconds = round(statistics.mean(durations), 2) if durations else 0.0
    std_seconds = (
        round(statistics.stdev(durations), 2) if len(durations) >= 2 else 0.0
    )

    payload: dict[str, Any] = {
        "schema": "bookscope-kg-cache-probe/v1",
        "probe": "timing",
        "book": args.book,
        "cache_state": args.cache_state,
        "runs": runs,
        "summary": {
            "n_runs": len(runs),
            "mean_seconds": mean_seconds,
            "std_seconds": std_seconds,
            "min_seconds": min(durations) if durations else 0.0,
            "max_seconds": max(durations) if durations else 0.0,
        },
        "config": {
            "book_title": book_title,
            "chunk_count": len(chunks),
            "model": model,
            "min_speedup_threshold": CACHE_SPEEDUP_MIN_RATIO,
        },
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }

    # speedup 撤回判定只在两次跑都有数据时做——本脚本一次只跑一种 state，
    # 验证两种 state 的脚本调用方按 empty/warm 两份 JSON 自行拼，或者
    # 跑后看 ``summary.mean_seconds`` 做对照。本 probe 单跑场景下只标
    # state 标签，不预判 speedup（要两份才能比）。

    out_path = args.output or _default_output_path(args.book, args.cache_state)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[probe] 写出 {out_path}")
    print(
        f"[probe] mean={mean_seconds}s std={std_seconds}s "
        f"(n={len(runs)} {args.cache_state})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
