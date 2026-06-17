"""端到端延迟基准测试脚本 —— Sprint 1 QA deliverable。

用途：第 33 轮性能优化 sprint 配套的 benchmark 脚本，量化每次优化前后
单题端到端 / batch 总耗时变化。脱掉 reviewer 调用（QA 性能基准只看
generator + tools，不被 reviewer 抖动污染）。

ROADMAP Sprint 1 性能目标：

- batch 5 题：当前 14-20 分钟 → 目标 < 5 分钟
- 单题端到端：当前 2-4 分钟（保持本 sprint）

测量维度（每题）：

- ``duration_s``           query 开始到 final_answer 总耗时
- ``iterations``           agent loop 迭代轮数（即 LLM 调用次数）
- ``tool_call_count``      trace.tool_calls 长度（成功 + 失败）
- ``citation_count``       result.citations 长度
- ``input_tokens`` / ``output_tokens``

汇总维度（batch）：

- 串行 / 并发模式各跑一遍记录 ``batch_duration_s``
- 单题耗时 P50 / P90 / 平均 / max / min（statistics 标准库）
- 跟 ``docs/internal/experiments/data/`` 下最近一份 benchmark JSON 对比（如有）

用法（bash，key 内联）::

    DEEPSEEK_API_KEY=sk-xxx \\
    PYTHONIOENCODING=utf-8 \\
    BOOKSCOPE_LOOP_PROMPT_PATH=bookscope/agent/prompts/loop_system_prompt_v3.4.md \\
    python scripts/benchmark_latency.py

    # 串行模式（debug / 怕被 rate limit）
    python scripts/benchmark_latency.py --serial

    # 限定题数 / 自定义并发数
    python scripts/benchmark_latency.py --limit 3 --concurrency 3

    # 自定义题集
    python scripts/benchmark_latency.py --questions docs/internal/experiments/data/v2-batch-01.json

环境变量（与 run_batch_r1.py 对齐）：

- ``DEEPSEEK_API_KEY``          必填（默认 provider）
- ``BOOKSCOPE_SMOKE_PROVIDER``  generator provider；默认 ``deepseek``
- ``BOOKSCOPE_SMOKE_MODEL``     generator model
- ``BOOKSCOPE_SMOKE_TIMEOUT``   单题超时秒；默认 600
- ``BOOKSCOPE_SMOKE_MAX_ITER``  AgentLoop 最大迭代
- ``BOOKSCOPE_LOOP_PROMPT_PATH`` prompt 路径覆盖
- ``BOOKSCOPE_SMOKE_EPUB``      epub 路径（由 smoke 内部读取）

设计：QA 脚本，零侵入 ``bookscope/`` runtime 代码；只复用 smoke_test_r1
的 ``_load_book_session`` / ``_build_adapter_and_model``。**不调 reviewer**——
benchmark 关心的是 generator 流水线本身，reviewer 是另一套延迟特征。
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
# CLI
# ---------------------------------------------------------------------------

_DEFAULT_QUESTIONS = (
    _PROJECT_ROOT / "docs" / "experiments" / "data" / "exp002-anshi-questions.json"
)
_BENCHMARK_DIR = _PROJECT_ROOT / "docs" / "experiments" / "data"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="BookScope 端到端延迟 benchmark")
    p.add_argument(
        "--questions",
        type=Path,
        default=_DEFAULT_QUESTIONS,
        help="题集 JSON（默认 anshi 5 题）",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=0,
        help="只跑前 N 题；0=全跑",
    )
    p.add_argument(
        "--serial",
        action="store_true",
        help="串行跑（默认并发）",
    )
    p.add_argument(
        "--concurrency",
        type=int,
        default=5,
        help="并发数（默认 5，与 minimax 已验证 5 并发一致）",
    )
    p.add_argument(
        "--label",
        default="",
        help="给本次 benchmark 打标签写进文件名（如 sprint1-pre / sprint1-post）",
    )
    p.add_argument(
        "--no-persist",
        action="store_true",
        help="不写 JSON（只打印报告）",
    )
    return p.parse_args()


# ---------------------------------------------------------------------------
# 单题跑：仅 generator，不调 reviewer
# ---------------------------------------------------------------------------


def _run_one(
    *,
    loop: Any,
    qid: str,
    qtype: str,
    question: str,
) -> dict[str, Any]:
    """跑一道题，记录性能字段。失败时记录错误类型不中断 batch。"""
    from bookscope.agent.errors import AgentError, ContentFiltered

    t0 = time.monotonic()
    try:
        result = loop.query(question)
    except ContentFiltered as exc:
        return {
            "id": qid,
            "type": qtype,
            "ok": False,
            "duration_s": round(time.monotonic() - t0, 2),
            "error_type": "ContentFiltered",
            "error_msg": str(exc)[:300],
        }
    except (AgentError, Exception) as exc:  # noqa: BLE001
        return {
            "id": qid,
            "type": qtype,
            "ok": False,
            "duration_s": round(time.monotonic() - t0, 2),
            "error_type": type(exc).__name__,
            "error_msg": str(exc)[:300],
        }

    elapsed = time.monotonic() - t0
    trace = result.trace
    td = trace.model_dump() if hasattr(trace, "model_dump") else dict(trace)
    tool_calls = td.get("tool_calls") or []
    return {
        "id": qid,
        "type": qtype,
        "ok": True,
        "duration_s": round(elapsed, 2),
        "iterations": td.get("iterations"),
        "tool_call_count": len(tool_calls),
        "tool_call_count_ok": sum(
            1 for tc in tool_calls
            if isinstance(tc, dict) and tc.get("status") == "ok"
        ),
        "citation_count": len(result.citations),
        "input_tokens": td.get("total_input_tokens"),
        "output_tokens": td.get("total_output_tokens"),
        "outcome": td.get("outcome"),
        "content_filter_retries": td.get("content_filter_retries"),
    }


# ---------------------------------------------------------------------------
# 统计
# ---------------------------------------------------------------------------


def _percentile(values: list[float], pct: float) -> float | None:
    """简易百分位：sort + 插值。values 空返回 None。"""
    if not values:
        return None
    if len(values) == 1:
        return round(values[0], 2)
    s = sorted(values)
    k = (len(s) - 1) * pct
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    frac = k - lo
    return round(s[lo] * (1 - frac) + s[hi] * frac, 2)


def _summarize(per_question: list[dict[str, Any]]) -> dict[str, Any]:
    """求 P50 / P90 / 平均 / min / max + tool/iter/citation 平均。"""
    durs = [r["duration_s"] for r in per_question if r.get("ok")]
    iters = [
        r["iterations"] for r in per_question if r.get("ok") and r.get("iterations") is not None
    ]
    tools = [r["tool_call_count"] for r in per_question if r.get("ok")]
    cites = [r["citation_count"] for r in per_question if r.get("ok")]
    in_toks = sum(r.get("input_tokens") or 0 for r in per_question if r.get("ok"))
    out_toks = sum(r.get("output_tokens") or 0 for r in per_question if r.get("ok"))

    n_total = len(per_question)
    n_ok = sum(1 for r in per_question if r.get("ok"))

    return {
        "total_questions": n_total,
        "success_count": n_ok,
        "failure_count": n_total - n_ok,
        "duration_p50_s": _percentile(durs, 0.5),
        "duration_p90_s": _percentile(durs, 0.9),
        "duration_avg_s": round(statistics.fmean(durs), 2) if durs else None,
        "duration_min_s": round(min(durs), 2) if durs else None,
        "duration_max_s": round(max(durs), 2) if durs else None,
        "iterations_avg": round(statistics.fmean(iters), 2) if iters else None,
        "tool_calls_avg": round(statistics.fmean(tools), 2) if tools else None,
        "citation_avg": round(statistics.fmean(cites), 2) if cites else None,
        "total_input_tokens": in_toks,
        "total_output_tokens": out_toks,
    }


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------


def _find_previous_benchmark(current_path: Path) -> Path | None:
    """在 _BENCHMARK_DIR 找最近一份 benchmark-latency-*.json（排除当前）。"""
    candidates = sorted(
        _BENCHMARK_DIR.glob("benchmark-latency-*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for p in candidates:
        if p.resolve() != current_path.resolve():
            return p
    return None


def _format_diff(curr: float | None, prev: float | None) -> str:
    """带符号 delta + 百分比。NA 透传。"""
    if curr is None or prev is None:
        return "—"
    delta = curr - prev
    pct = (delta / prev * 100) if prev else 0
    sign = "+" if delta >= 0 else ""
    return f"{sign}{round(delta, 2)} ({sign}{pct:.1f}%)"


def _render_markdown(
    *,
    summary: dict[str, Any],
    batch_duration_s: float,
    mode: str,
    concurrency: int,
    per_question: list[dict[str, Any]],
    config: dict[str, Any],
    prev: dict[str, Any] | None,
) -> str:
    """生成 markdown 报告（stdout 用）。"""
    lines: list[str] = []
    lines.append("# BookScope 延迟基准测试")
    lines.append("")
    lines.append(f"- 时间：{config['timestamp']}")
    lines.append(f"- 模式：{mode}（concurrency={concurrency}）")
    lines.append(f"- provider / model：{config['provider']} / {config['model']}")
    lines.append(f"- prompt：{config['prompt_path']}")
    lines.append(
        f"- epub：{config['book_title']}"
        f"（{config['word_count']} 字 / {config['chunk_count']} chunk）"
    )
    lines.append(f"- 题集：{config['questions_path']}（{summary['total_questions']} 题）")
    lines.append("")
    lines.append("## 总耗时")
    lines.append("")
    lines.append(f"- batch 总耗时：**{batch_duration_s:.1f}s**（{batch_duration_s / 60:.1f} 分钟）")
    if prev:
        prev_batch = prev.get("batch_duration_s")
        if isinstance(prev_batch, (int, float)):
            lines.append(f"- 对比上次：{_format_diff(batch_duration_s, prev_batch)}")
    lines.append("")
    lines.append("## 单题统计")
    lines.append("")
    lines.append("| 指标 | 当前 | 上次 | 变化 |")
    lines.append("|---|---|---|---|")
    prev_summary = (prev or {}).get("summary") or {}
    for label, key in (
        ("成功率", None),  # 自定义
        ("P50 (s)", "duration_p50_s"),
        ("P90 (s)", "duration_p90_s"),
        ("平均 (s)", "duration_avg_s"),
        ("min (s)", "duration_min_s"),
        ("max (s)", "duration_max_s"),
        ("平均 iter 数", "iterations_avg"),
        ("平均 tool 调用数", "tool_calls_avg"),
        ("平均 citation 数", "citation_avg"),
    ):
        if key is None:
            curr_v = f"{summary['success_count']}/{summary['total_questions']}"
            prev_v = (
                f"{prev_summary.get('success_count', '?')}"
                f"/{prev_summary.get('total_questions', '?')}"
                if prev_summary else "—"
            )
            lines.append(f"| {label} | {curr_v} | {prev_v} | — |")
            continue
        curr_v = summary.get(key)
        prev_v = prev_summary.get(key)
        lines.append(
            f"| {label} | {curr_v if curr_v is not None else '—'} "
            f"| {prev_v if prev_v is not None else '—'} "
            f"| {_format_diff(curr_v, prev_v)} |"
        )
    lines.append("")
    lines.append("## 各题明细")
    lines.append("")
    lines.append("| id | type | ok | dur(s) | iter | tools | cites |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in per_question:
        ok_tag = "OK" if r.get("ok") else f"FAIL({r.get('error_type', '?')})"
        lines.append(
            f"| {r.get('id')} | {r.get('type', '')} | {ok_tag} "
            f"| {r.get('duration_s', '—')} "
            f"| {r.get('iterations', '—')} "
            f"| {r.get('tool_call_count', '—')} "
            f"| {r.get('citation_count', '—')} |"
        )
    lines.append("")
    lines.append(
        f"- token：input={summary.get('total_input_tokens')}"
        f" output={summary.get('total_output_tokens')}"
    )
    if prev:
        lines.append(f"- 对比基线：`{prev.get('_path', '—')}`")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def main() -> int:
    args = _parse_args()

    # --- 题集 ---
    if not args.questions.is_file():
        print(f"[bench] 题集文件不存在: {args.questions}", file=sys.stderr)
        return 1
    src = json.loads(args.questions.read_text(encoding="utf-8"))
    questions = src.get("questions") or []
    if args.limit > 0:
        questions = questions[: args.limit]
    if not questions:
        print("[bench] 题集为空", file=sys.stderr)
        return 1

    # --- prompt override ---
    prompt_override = os.environ.get("BOOKSCOPE_LOOP_PROMPT_PATH")
    prompt_path_recorded = "default"
    if prompt_override:
        from bookscope.agent import loop as _loop_mod
        override_path = Path(prompt_override)
        if not override_path.is_absolute():
            override_path = _PROJECT_ROOT / override_path
        if not override_path.is_file():
            print(
                f"[bench] BOOKSCOPE_LOOP_PROMPT_PATH 不存在: {override_path}",
                file=sys.stderr,
            )
            return 2
        _loop_mod.SYSTEM_PROMPT_PATH = override_path
        prompt_path_recorded = str(override_path.relative_to(_PROJECT_ROOT))
        print(f"[bench] prompt override → {prompt_path_recorded}")

    # --- provider 默认 deepseek ---
    os.environ.setdefault("BOOKSCOPE_SMOKE_PROVIDER", "deepseek")

    from bookscope.agent import AgentLoop
    from bookscope.agent.backends.r0_assembler import R0BookAssembler
    from scripts.smoke_test_r1 import (  # type: ignore[import-not-found]
        _build_adapter_and_model,
        _load_book_session,
    )

    provider = os.environ["BOOKSCOPE_SMOKE_PROVIDER"]
    print(f"[bench] generator provider = {provider}")
    try:
        gen_adapter, gen_model = _build_adapter_and_model(provider)
    except RuntimeError as exc:
        print(f"[bench] generator 配置错误: {exc}", file=sys.stderr)
        return 2
    print(f"[bench] generator model = {gen_model}")

    # --- 加载书 + 装配 backends ---
    print("[bench] 加载书 + 装配 backends ...")
    t_setup = time.monotonic()
    book, chunks, kg, vector_store = _load_book_session()
    assembler = R0BookAssembler(
        book_text=book,
        chunks=chunks,
        knowledge_graph=kg,
        session_vector_store=vector_store,
    )
    backends = assembler.build_all()
    if backends["search"] is None:
        print("[bench] vector store 装配失败", file=sys.stderr)
        return 3
    setup_elapsed = time.monotonic() - t_setup
    print(f"[bench] 装配耗时 {setup_elapsed:.1f}s")

    timeout_seconds = float(os.environ.get("BOOKSCOPE_SMOKE_TIMEOUT", "600"))
    max_iter_env = os.environ.get("BOOKSCOPE_SMOKE_MAX_ITER")
    loop_kwargs: dict[str, Any] = {
        "client": gen_adapter,
        "search_chunks_backend": backends["search"],
        "chapter_range_backend": backends["chapter_range"],
        "list_characters_backend": backends["list_characters"],
        "model": gen_model,
        "timeout_seconds": timeout_seconds,
    }
    if max_iter_env:
        loop_kwargs["max_iterations"] = int(max_iter_env)
    loop = AgentLoop(**loop_kwargs)

    book_title = getattr(book, "title", "?")
    word_count = getattr(book, "word_count", None)

    # --- 跑题 ---
    mode = "serial" if args.serial else "concurrent"
    concurrency = 1 if args.serial else max(1, args.concurrency)
    print(f"[bench] 模式={mode} concurrency={concurrency} n={len(questions)}")
    print("=" * 64)

    tasks = []
    for idx, q in enumerate(questions, start=1):
        qid = q.get("id", f"q{idx}")
        qtype = q.get("type", "")
        question = (q.get("smoke") or {}).get("question") or q.get("question")
        if not question:
            print(f"[bench] [{idx}] {qid} 跳过（缺 question）")
            continue
        tasks.append((qid, qtype, question))

    per_question: list[dict[str, Any]] = []
    t_batch = time.monotonic()

    if args.serial:
        for idx, (qid, qtype, question) in enumerate(tasks, start=1):
            print(f"[bench] [{idx}/{len(tasks)}] {qid} [{qtype}] 开始")
            r = _run_one(loop=loop, qid=qid, qtype=qtype, question=question)
            per_question.append(r)
            tag = "OK" if r.get("ok") else f"FAIL({r.get('error_type')})"
            print(
                f"   → {tag} dur={r.get('duration_s')}s "
                f"iter={r.get('iterations')} tools={r.get('tool_call_count')} "
                f"cites={r.get('citation_count')}"
            )
    else:
        with ThreadPoolExecutor(max_workers=concurrency) as ex:
            future_to_qid = {
                ex.submit(_run_one, loop=loop, qid=qid, qtype=qtype, question=question): qid
                for qid, qtype, question in tasks
            }
            for fut in as_completed(future_to_qid):
                r = fut.result()
                per_question.append(r)
                tag = "OK" if r.get("ok") else f"FAIL({r.get('error_type')})"
                print(
                    f"[bench] {r.get('id')} {tag} dur={r.get('duration_s')}s "
                    f"iter={r.get('iterations')} tools={r.get('tool_call_count')} "
                    f"cites={r.get('citation_count')}"
                )
        # 还原原题序，便于报告对照
        order = {qid: i for i, (qid, _, _) in enumerate(tasks)}
        per_question.sort(key=lambda r: order.get(r.get("id"), 999))

    batch_duration_s = time.monotonic() - t_batch

    # --- 汇总 ---
    summary = _summarize(per_question)

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    config = {
        "timestamp": timestamp,
        "mode": mode,
        "concurrency": concurrency,
        "provider": provider,
        "model": gen_model,
        "prompt_path": prompt_path_recorded,
        "questions_path": str(args.questions.relative_to(_PROJECT_ROOT))
        if args.questions.is_relative_to(_PROJECT_ROOT)
        else str(args.questions),
        "book_title": book_title,
        "word_count": word_count,
        "chunk_count": len(chunks),
        "setup_elapsed_s": round(setup_elapsed, 2),
        "timeout_seconds": timeout_seconds,
        "max_iterations": loop_kwargs.get("max_iterations"),
        "limit": args.limit,
        "label": args.label,
    }

    out_payload = {
        "schema": "bookscope-benchmark-latency/v1",
        "config": config,
        "batch_duration_s": round(batch_duration_s, 2),
        "summary": summary,
        "per_question": per_question,
    }

    # --- 持久化（在找上一份之前写） ---
    out_path: Path | None = None
    if not args.no_persist:
        label_seg = f"-{args.label}" if args.label else ""
        out_path = _BENCHMARK_DIR / f"benchmark-latency-{timestamp}{label_seg}.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(out_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # --- 找上一份对比 ---
    prev_payload: dict[str, Any] | None = None
    prev_path = _find_previous_benchmark(out_path) if out_path else _find_previous_benchmark(
        _BENCHMARK_DIR / "__none__.json"
    )
    if prev_path is not None:
        try:
            prev_payload = json.loads(prev_path.read_text(encoding="utf-8"))
            prev_payload["_path"] = str(prev_path.relative_to(_PROJECT_ROOT))
        except Exception as exc:  # noqa: BLE001
            print(f"[bench] 上次 benchmark 解析失败 {prev_path}: {exc}", file=sys.stderr)
            prev_payload = None

    # --- 报告 ---
    md = _render_markdown(
        summary=summary,
        batch_duration_s=batch_duration_s,
        mode=mode,
        concurrency=concurrency,
        per_question=per_question,
        config=config,
        prev=prev_payload,
    )
    print("=" * 64)
    print(md)
    print("=" * 64)
    if out_path:
        print(f"[bench] 数据写出 → {out_path.relative_to(_PROJECT_ROOT)}")
    print(f"[bench] batch 总耗时 {batch_duration_s:.1f}s（{batch_duration_s / 60:.1f} 分钟）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
