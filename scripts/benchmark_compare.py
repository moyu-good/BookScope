"""benchmark 数据点对比 —— Sprint 5 QA deliverable。

用途：把两份 ``benchmark_run_and_report.py`` 输出的 JSON 拿来比较，输出
Markdown 段落 + 性能回归判定。CI 在每个 PR 跑完新 benchmark 之后调用
本脚本对比上一次基线，若 P50 退化超过阈值（默认 20%）则 ``exit 1``
让 PR 检查挂掉。

用法（bash）::

    python scripts/benchmark_compare.py \\
        docs/internal/experiments/data/benchmark-20260501-120000.json \\
        docs/internal/experiments/data/benchmark-20260501-130000.json

    # 自定义回归阈值（百分比，默认 20）
    python scripts/benchmark_compare.py prev.json curr.json --threshold 15

输出：

- stdout 一段 Markdown：P50/P90/mean 三档变化 + 单题表
- 退出码：0 = 无回归 / 改善；1 = REGRESSION（P50 上涨超阈值）

字段约定（见 ``benchmark_run_and_report.py``）：

- ``timestamp`` / ``git_commit`` / ``git_branch``
- ``questions_count`` / ``p50_ms`` / ``p90_ms`` / ``mean_ms``
- ``per_question[]``：``{id, duration_ms, outcome}``
- ``config``：``{provider, prompt_version, max_iterations}``
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger("benchmark_compare")

# 性能回归阈值默认 20%。理由：minimax 单次延迟 std≈10-15%（第 33 轮第五部分
# baseline noise 测量），阈值若 <15% 容易被 noise 触发误报；阈值 >25% 会
# 漏过有意义的回归。20% 在 noise 与敏感度之间取平衡。
# 可通过 ``--threshold`` 覆盖，CI 不同环境（如冷启动机器）可调宽。
DEFAULT_REGRESSION_THRESHOLD_PCT = 20.0

REQUIRED_FIELDS = ("p50_ms", "p90_ms", "mean_ms", "per_question")


# ---------------------------------------------------------------------------
# JSON 加载 / 校验
# ---------------------------------------------------------------------------


def _load_benchmark(path: Path) -> dict[str, Any]:
    """读 benchmark JSON 并校验必需字段。

    缺字段时抛 ``ValueError`` 友好提示，而不是让 KeyError 冒到顶部。
    """
    if not path.is_file():
        raise FileNotFoundError(f"benchmark 文件不存在: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"benchmark JSON 解析失败 {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"benchmark JSON 顶层不是 object: {path}")
    missing = [f for f in REQUIRED_FIELDS if f not in payload]
    if missing:
        raise ValueError(
            f"benchmark JSON 缺字段 {missing}: {path}（schema 是否旧版本？）"
        )
    return payload


# ---------------------------------------------------------------------------
# 对比计算
# ---------------------------------------------------------------------------


def _pct_change(old: float | None, new: float | None) -> float | None:
    """新值相对旧值的百分比变化。任一缺失返回 None。"""
    if old is None or new is None:
        return None
    if old == 0:
        return None
    return (new - old) / old * 100.0


def _format_delta(old: float | None, new: float | None) -> str:
    """带符号 ms + 百分比。None 透传 '—'。"""
    if old is None or new is None:
        return "—"
    delta = new - old
    pct = _pct_change(old, new)
    sign = "+" if delta >= 0 else ""
    pct_str = f"{sign}{pct:.1f}%" if pct is not None else "—"
    return f"{sign}{delta:.0f}ms ({pct_str})"


def _classify(p50_pct: float | None, threshold_pct: float) -> str:
    """根据 P50 百分比变化判定等级。

    - REGRESSION：P50 上涨超过阈值
    - IMPROVEMENT：P50 下降超过阈值
    - STABLE：阈值范围内（含未知）
    """
    if p50_pct is None:
        return "STABLE"
    if p50_pct > threshold_pct:
        return "REGRESSION"
    if p50_pct < -threshold_pct:
        return "IMPROVEMENT"
    return "STABLE"


# ---------------------------------------------------------------------------
# Markdown 渲染
# ---------------------------------------------------------------------------


def _render_compare_markdown(
    *,
    prev: dict[str, Any],
    curr: dict[str, Any],
    threshold_pct: float,
) -> tuple[str, str]:
    """生成对比 Markdown 段落 + 判定 verdict。

    返回 ``(markdown, verdict)``，verdict ∈ {REGRESSION, IMPROVEMENT, STABLE}。
    """
    p50_pct = _pct_change(prev.get("p50_ms"), curr.get("p50_ms"))
    verdict = _classify(p50_pct, threshold_pct)

    lines: list[str] = []
    lines.append("# benchmark 对比报告")
    lines.append("")
    lines.append(f"- 基线：`{prev.get('timestamp', '?')}` "
                 f"(commit `{prev.get('git_commit', '?')}`)")
    lines.append(f"- 当前：`{curr.get('timestamp', '?')}` "
                 f"(commit `{curr.get('git_commit', '?')}`)")
    lines.append(f"- 回归阈值：P50 变化超过 ±{threshold_pct:.0f}%")
    lines.append(f"- **判定：{verdict}**")
    lines.append("")

    lines.append("## 总体延迟")
    lines.append("")
    lines.append("| 指标 | 基线 | 当前 | 变化 |")
    lines.append("|---|---|---|---|")
    for label, key in (("P50 (ms)", "p50_ms"), ("P90 (ms)", "p90_ms"), ("mean (ms)", "mean_ms")):
        old_v = prev.get(key)
        new_v = curr.get(key)
        old_str = f"{old_v:.0f}" if isinstance(old_v, (int, float)) else "—"
        new_str = f"{new_v:.0f}" if isinstance(new_v, (int, float)) else "—"
        lines.append(f"| {label} | {old_str} | {new_str} | {_format_delta(old_v, new_v)} |")
    lines.append("")

    # 单题对比（按 id 对齐）
    lines.append("## 单题 dur 变化")
    lines.append("")
    lines.append("| id | 基线 (ms) | 当前 (ms) | 变化 | outcome |")
    lines.append("|---|---|---|---|---|")
    prev_by_id = {q.get("id"): q for q in (prev.get("per_question") or []) if isinstance(q, dict)}
    curr_by_id = {q.get("id"): q for q in (curr.get("per_question") or []) if isinstance(q, dict)}
    all_ids = list(curr_by_id.keys()) + [i for i in prev_by_id if i not in curr_by_id]
    for qid in all_ids:
        old_q = prev_by_id.get(qid, {})
        new_q = curr_by_id.get(qid, {})
        old_dur = old_q.get("duration_ms")
        new_dur = new_q.get("duration_ms")
        outcome = new_q.get("outcome", old_q.get("outcome", "?"))
        old_str = f"{old_dur:.0f}" if isinstance(old_dur, (int, float)) else "—"
        new_str = f"{new_dur:.0f}" if isinstance(new_dur, (int, float)) else "—"
        lines.append(
            f"| {qid} | {old_str} | {new_str} | {_format_delta(old_dur, new_dur)} | {outcome} |"
        )
    lines.append("")

    if verdict == "REGRESSION":
        lines.append(
            f"> **REGRESSION**：P50 从 {prev.get('p50_ms'):.0f}ms 上涨到 "
            f"{curr.get('p50_ms'):.0f}ms（{p50_pct:+.1f}%），超过 ±{threshold_pct:.0f}% "
            "阈值。本 PR 视为性能回归，需要排查后再合并。"
        )
    elif verdict == "IMPROVEMENT":
        lines.append(
            f"> **IMPROVEMENT**：P50 从 {prev.get('p50_ms'):.0f}ms 降到 "
            f"{curr.get('p50_ms'):.0f}ms（{p50_pct:+.1f}%），优化生效。"
        )
    else:
        lines.append(
            f"> **STABLE**：P50 变化在 ±{threshold_pct:.0f}% 阈值内，视为 noise。"
        )

    return "\n".join(lines), verdict


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="BookScope benchmark 数据点对比")
    p.add_argument("baseline", type=Path, help="基线 benchmark JSON 路径")
    p.add_argument("current", type=Path, help="当前 benchmark JSON 路径")
    p.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_REGRESSION_THRESHOLD_PCT,
        help=f"回归阈值百分比（默认 {DEFAULT_REGRESSION_THRESHOLD_PCT:.0f}）",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        prev = _load_benchmark(args.baseline)
        curr = _load_benchmark(args.current)
    except (FileNotFoundError, ValueError) as exc:
        print(f"[bench-compare] {exc}", file=sys.stderr)
        return 2

    md, verdict = _render_compare_markdown(
        prev=prev, curr=curr, threshold_pct=args.threshold
    )
    print(md)

    if verdict == "REGRESSION":
        print(
            f"\n[bench-compare] REGRESSION 检测到，exit 1（阈值 {args.threshold:.0f}%）",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
