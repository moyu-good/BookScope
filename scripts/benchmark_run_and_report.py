"""benchmark 一键跑 + Markdown 报告 —— Sprint 5 QA deliverable。

用途：把 ``benchmark_latency.py`` 的单次手动跑包装成「跑 + JSON + Markdown
报告 + 自动比对上次基线」的自动化流程。每个 BE 性能优化 PR 跑一次，跟
最近一份基线对比，回归就挂 PR。

输出（``docs/internal/experiments/data/`` 下成对生成）：

- ``benchmark-<timestamp>.json``  机器可读，schema 见下
- ``benchmark-<timestamp>.md``    人看的报告

JSON schema（``bookscope-benchmark/v2``）::

    {
      "schema": "bookscope-benchmark/v2",
      "timestamp": "2026-05-01T12:34:56",
      "git_commit": "abc1234",
      "git_branch": "r1-agent-loop",
      "questions_count": 5,
      "p50_ms": 120000,
      "p90_ms": 180000,
      "mean_ms": 130000,
      "per_question": [
        {"id": "q1", "duration_ms": 95000, "outcome": "success"},
        ...
      ],
      "config": {
        "provider": "deepseek",
        "prompt_version": "v3.4",
        "max_iterations": 12,
        "questions_path": "...",
        "concurrency": 5,
        "dry_run": false
      }
    }

用法（bash）::

    # 真打 LLM
    DEEPSEEK_API_KEY=sk-... \\
    BOOKSCOPE_SMOKE_EPUB="C:/.../test安史之乱.epub" \\
    python scripts/benchmark_run_and_report.py

    # CI 烟测：不调 LLM，伪 duration 验证脚本可跑通
    BOOKSCOPE_BENCHMARK_DRY_RUN=1 \\
    python scripts/benchmark_run_and_report.py

环境变量：

- ``BOOKSCOPE_BENCHMARK_DRY_RUN``        ``1`` = 伪造 duration，不调 LLM
- ``BOOKSCOPE_BENCHMARK_PROVIDER``       默认 ``deepseek``
- ``BOOKSCOPE_BENCHMARK_PROMPT_VERSION`` 默认 ``v3.4``（仅记录到 config）
- 其他与 ``benchmark_latency.py`` 一致（``DEEPSEEK_API_KEY`` /
  ``BOOKSCOPE_SMOKE_EPUB`` / ``BOOKSCOPE_LOOP_PROMPT_PATH`` 等）
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import os
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

logger = logging.getLogger("benchmark_run_and_report")

# Windows 控制台 UTF-8 兜底
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_DEFAULT_QUESTIONS = (
    _PROJECT_ROOT / "docs" / "experiments" / "data" / "v2-batch-01.json"
)
_BENCHMARK_DIR = _PROJECT_ROOT / "docs" / "experiments" / "data"

SCHEMA_VERSION = "bookscope-benchmark/v2"


def _friendly_path(p: Path) -> str:
    """对项目内路径返回相对路径；项目外（如 tmp_path）返回原始字符串。"""
    try:
        return str(p.relative_to(_PROJECT_ROOT))
    except ValueError:
        return str(p)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="BookScope benchmark 一键跑 + 报告")
    p.add_argument(
        "--questions",
        type=Path,
        default=_DEFAULT_QUESTIONS,
        help="题集 JSON（默认 v2-batch-01 5 题）",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=0,
        help="只跑前 N 题；0=全跑",
    )
    p.add_argument(
        "--concurrency",
        type=int,
        default=5,
        help="并发数（默认 5）",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=_BENCHMARK_DIR,
        help="JSON / Markdown 输出目录",
    )
    p.add_argument(
        "--label",
        default="",
        help="给本次 benchmark 打标签写进文件名",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="不调 LLM，伪造 duration（CI 烟测用）",
    )
    return p.parse_args(argv)


# ---------------------------------------------------------------------------
# Git 元数据
# ---------------------------------------------------------------------------


def _git_meta() -> dict[str, str]:
    """读当前 git commit / branch；非 git 仓返回 unknown。"""
    meta = {"git_commit": "unknown", "git_branch": "unknown"}
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=_PROJECT_ROOT,
            check=False,
            timeout=5,
        )
        if commit.returncode == 0:
            meta["git_commit"] = commit.stdout.strip()
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            cwd=_PROJECT_ROOT,
            check=False,
            timeout=5,
        )
        if branch.returncode == 0:
            meta["git_branch"] = branch.stdout.strip() or "detached"
    except (subprocess.SubprocessError, OSError):
        pass
    return meta


# ---------------------------------------------------------------------------
# 题集加载
# ---------------------------------------------------------------------------


def _load_questions(path: Path, limit: int) -> list[dict[str, Any]]:
    """读题集 JSON，返回 ``[{id, type, question}]``。"""
    if not path.is_file():
        raise FileNotFoundError(f"题集文件不存在: {path}")
    src = json.loads(path.read_text(encoding="utf-8"))
    raw = src.get("questions") or []
    if limit > 0:
        raw = raw[:limit]
    out: list[dict[str, Any]] = []
    for idx, q in enumerate(raw, start=1):
        qid = q.get("id", f"q{idx}")
        qtype = q.get("type", "")
        question = (q.get("smoke") or {}).get("question") or q.get("question")
        if not question:
            continue
        out.append({"id": qid, "type": qtype, "question": question})
    return out


# ---------------------------------------------------------------------------
# Dry-run 伪 runner
# ---------------------------------------------------------------------------


def _fake_run_one(item: dict[str, Any], idx: int) -> dict[str, Any]:
    """dry-run 用：伪造一个 duration，跳过真 LLM 调用。

    duration 用 ``80000 + idx * 10000`` ms，让 P50/P90 有明显层级差，
    便于校验百分位逻辑。
    """
    duration_ms = 80_000 + idx * 10_000
    return {
        "id": item["id"],
        "duration_ms": duration_ms,
        "outcome": "success",
    }


# ---------------------------------------------------------------------------
# 真 runner：复用 benchmark_latency 的 _run_one
# ---------------------------------------------------------------------------


def _real_runner_factory() -> Any:
    """装配 AgentLoop 并返回一个 ``run(item, idx) -> per_question_dict``。

    包装 ``benchmark_latency._run_one`` 的字段为 v2 schema：``duration_ms`` /
    ``outcome``（``success`` / ``failure``）。
    """
    # 延迟 import，避免 dry-run 模式下不必要的依赖加载
    from bookscope.agent import AgentLoop
    from bookscope.agent.backends.r0_assembler import R0BookAssembler
    from scripts.benchmark_latency import _run_one as _legacy_run_one
    from scripts.smoke_test_r1 import (  # type: ignore[import-not-found]
        _build_adapter_and_model,
        _load_book_session,
    )

    provider = os.environ.get("BOOKSCOPE_BENCHMARK_PROVIDER") or os.environ.setdefault(
        "BOOKSCOPE_SMOKE_PROVIDER", "deepseek"
    )
    print(f"[bench] generator provider = {provider}")
    gen_adapter, gen_model = _build_adapter_and_model(provider)
    print(f"[bench] generator model = {gen_model}")

    print("[bench] 加载书 + 装配 backends ...")
    book, chunks, kg, vector_store = _load_book_session()
    assembler = R0BookAssembler(
        book_text=book,
        chunks=chunks,
        knowledge_graph=kg,
        session_vector_store=vector_store,
    )
    backends = assembler.build_all()
    if backends["search"] is None:
        raise RuntimeError("vector store 装配失败")

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

    def _run(item: dict[str, Any], _idx: int) -> dict[str, Any]:
        legacy = _legacy_run_one(
            loop=loop,
            qid=item["id"],
            qtype=item.get("type", ""),
            question=item["question"],
        )
        ok = bool(legacy.get("ok"))
        return {
            "id": legacy.get("id"),
            "duration_ms": int(round((legacy.get("duration_s") or 0) * 1000)),
            "outcome": "success" if ok else "failure",
            "error_type": legacy.get("error_type"),
            "iterations": legacy.get("iterations"),
            "tool_call_count": legacy.get("tool_call_count"),
            "citation_count": legacy.get("citation_count"),
        }

    return _run, provider, gen_model


# ---------------------------------------------------------------------------
# 统计
# ---------------------------------------------------------------------------


def _percentile_ms(values: list[float], pct: float) -> float | None:
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
    """从 per_question 列表抽 P50/P90/mean。"""
    durs = [
        q["duration_ms"]
        for q in per_question
        if q.get("outcome") == "success"
        and isinstance(q.get("duration_ms"), (int, float))
    ]
    if not durs:
        return {"p50_ms": None, "p90_ms": None, "mean_ms": None}
    return {
        "p50_ms": _percentile_ms(durs, 0.5),
        "p90_ms": _percentile_ms(durs, 0.9),
        "mean_ms": round(statistics.fmean(durs), 2),
    }


# ---------------------------------------------------------------------------
# Markdown 渲染
# ---------------------------------------------------------------------------


def _render_markdown(payload: dict[str, Any], prev_path: Path | None) -> str:
    """生成 Markdown 报告。如果 ``prev_path`` 给了，附一段对比。"""
    cfg = payload.get("config", {})
    lines: list[str] = []
    lines.append(f"# BookScope benchmark · {payload['timestamp']}")
    lines.append("")
    lines.append(
        f"- git：commit `{payload.get('git_commit', '?')}` "
        f"branch `{payload.get('git_branch', '?')}`"
    )
    lines.append(f"- 题集：`{cfg.get('questions_path', '?')}`（{payload['questions_count']} 题）")
    lines.append(
        f"- provider / prompt：{cfg.get('provider')} / {cfg.get('prompt_version')}"
    )
    lines.append(
        f"- 并发：{cfg.get('concurrency')}　"
        f"max_iterations：{cfg.get('max_iterations') or '默认'}"
    )
    if cfg.get("dry_run"):
        lines.append("- **dry-run**：未调 LLM，duration 为伪造")
    lines.append("")

    p50 = payload.get("p50_ms")
    p90 = payload.get("p90_ms")
    mean = payload.get("mean_ms")
    lines.append("## 总体延迟")
    lines.append("")
    lines.append(
        f"- 5 题平均 **{(mean / 1000):.1f}s**　"
        f"P50 **{(p50 / 1000):.1f}s**　"
        f"P90 **{(p90 / 1000):.1f}s**"
        if isinstance(p50, (int, float)) and isinstance(p90, (int, float))
        and isinstance(mean, (int, float))
        else "- 无成功样本"
    )
    lines.append("")

    lines.append("## 各题明细")
    lines.append("")
    lines.append("| id | duration (ms) | outcome |")
    lines.append("|---|---|---|")
    for q in payload.get("per_question", []):
        dur = q.get("duration_ms")
        dur_str = f"{dur:.0f}" if isinstance(dur, (int, float)) else "—"
        lines.append(f"| {q.get('id')} | {dur_str} | {q.get('outcome', '?')} |")
    lines.append("")

    if prev_path is not None:
        lines.append("## 对比上次基线")
        lines.append("")
        lines.append(f"- 基线文件：`{prev_path.name}`")
        try:
            prev = json.loads(prev_path.read_text(encoding="utf-8"))
            for label, key in (("P50", "p50_ms"), ("P90", "p90_ms"), ("mean", "mean_ms")):
                old_v = prev.get(key)
                new_v = payload.get(key)
                if isinstance(old_v, (int, float)) and isinstance(new_v, (int, float)) and old_v:
                    pct = (new_v - old_v) / old_v * 100
                    sign = "+" if pct >= 0 else ""
                    lines.append(
                        f"- {label}：{old_v:.0f}ms → {new_v:.0f}ms（{sign}{pct:.1f}%）"
                    )
                else:
                    lines.append(f"- {label}：— → —")
        except (json.JSONDecodeError, OSError) as exc:
            lines.append(f"- 基线解析失败：{exc}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 找上一份 benchmark 用作对比
# ---------------------------------------------------------------------------


def _find_previous(current: Path, output_dir: Path) -> Path | None:
    """在 ``output_dir`` 找最近一份 ``benchmark-*.json``（排除当前）。"""
    candidates = sorted(
        output_dir.glob("benchmark-*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for p in candidates:
        if p.resolve() == current.resolve():
            continue
        # 兼容 v2 schema 即可（缺 p50_ms 的旧文件跳过）
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if "p50_ms" in payload:
            return p
    return None


# ---------------------------------------------------------------------------
# 主流程：拆 build_payload + write_report 便于测试
# ---------------------------------------------------------------------------


def build_payload(
    *,
    questions: list[dict[str, Any]],
    concurrency: int,
    dry_run: bool,
    questions_path: Path,
    label: str = "",
) -> dict[str, Any]:
    """跑 benchmark 并返回 v2 schema payload。

    dry-run 模式下不调 LLM；真模式下调 ``benchmark_latency._run_one``。
    """
    if not questions:
        raise ValueError("题集为空")

    provider_name = "dry-run"
    model_name = "dry-run"
    runner: Any
    if dry_run:
        def runner_dry(item: dict[str, Any], idx: int) -> dict[str, Any]:
            return _fake_run_one(item, idx)
        runner = runner_dry
    else:
        runner, provider_name, model_name = _real_runner_factory()

    per_question: list[dict[str, Any]] = []
    if dry_run or concurrency <= 1:
        for idx, item in enumerate(questions):
            per_question.append(runner(item, idx))
    else:
        with ThreadPoolExecutor(max_workers=concurrency) as ex:
            future_to_idx = {
                ex.submit(runner, item, idx): idx
                for idx, item in enumerate(questions)
            }
            tmp: dict[int, dict[str, Any]] = {}
            for fut in as_completed(future_to_idx):
                idx = future_to_idx[fut]
                tmp[idx] = fut.result()
            for i in range(len(questions)):
                if i in tmp:
                    per_question.append(tmp[i])

    summary = _summarize(per_question)
    git_meta = _git_meta()
    timestamp = _dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    prompt_version = os.environ.get("BOOKSCOPE_BENCHMARK_PROMPT_VERSION", "v3.4")
    max_iter_env = os.environ.get("BOOKSCOPE_SMOKE_MAX_ITER")
    payload: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "timestamp": timestamp,
        "git_commit": git_meta["git_commit"],
        "git_branch": git_meta["git_branch"],
        "questions_count": len(questions),
        "p50_ms": summary["p50_ms"],
        "p90_ms": summary["p90_ms"],
        "mean_ms": summary["mean_ms"],
        "per_question": per_question,
        "config": {
            "provider": provider_name,
            "model": model_name,
            "prompt_version": prompt_version,
            "max_iterations": int(max_iter_env) if max_iter_env else None,
            "questions_path": _friendly_path(questions_path),
            "concurrency": concurrency,
            "dry_run": dry_run,
            "label": label,
        },
    }
    return payload


def write_report(
    payload: dict[str, Any],
    output_dir: Path,
    label: str = "",
) -> tuple[Path, Path]:
    """把 payload 写成 JSON + Markdown，返回 ``(json_path, md_path)``。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    ts_safe = payload["timestamp"].replace(":", "").replace("-", "")
    label_seg = f"-{label}" if label else ""
    json_path = output_dir / f"benchmark-{ts_safe}{label_seg}.json"
    md_path = output_dir / f"benchmark-{ts_safe}{label_seg}.md"

    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    prev_path = _find_previous(json_path, output_dir)
    md = _render_markdown(payload, prev_path)
    md_path.write_text(md, encoding="utf-8")
    return json_path, md_path


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    dry_run = args.dry_run or os.environ.get("BOOKSCOPE_BENCHMARK_DRY_RUN") == "1"

    try:
        questions = _load_questions(args.questions, args.limit)
    except FileNotFoundError as exc:
        print(f"[bench] {exc}", file=sys.stderr)
        return 1

    if not questions:
        print("[bench] 题集为空（缺 question 字段）", file=sys.stderr)
        return 1

    print(f"[bench] mode={'DRY-RUN' if dry_run else 'LIVE'} n={len(questions)} "
          f"concurrency={args.concurrency}")
    t0 = time.monotonic()
    try:
        payload = build_payload(
            questions=questions,
            concurrency=args.concurrency,
            dry_run=dry_run,
            questions_path=args.questions,
            label=args.label,
        )
    except (RuntimeError, ValueError) as exc:
        print(f"[bench] 跑 benchmark 失败: {exc}", file=sys.stderr)
        return 2
    elapsed = time.monotonic() - t0

    json_path, md_path = write_report(payload, args.output_dir, args.label)
    print(f"[bench] JSON → {_friendly_path(json_path)}")
    print(f"[bench] MD   → {_friendly_path(md_path)}")
    print(f"[bench] 总耗时 {elapsed:.1f}s（dry-run 不代表真延迟）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
