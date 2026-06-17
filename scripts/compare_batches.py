"""比较两个 batch JSON 的得分差异——给案例研究 / STATE 写作用的对照报告。

用途::

    python scripts/compare_batches.py \\
        --baseline docs/internal/experiments/data/v2-batch-01.json \\
        --candidate docs/internal/experiments/data/v3.1-minimax-batch-01.json

输出：
- 顶层 average_total / 各维度均值差
- 5 题逐题 total + 各维度差
- 候选 vs baseline 在每题上的 winner / loser

不写任何文件，纯 stdout——作者自己 copy 到 STATE / case-study 即可。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

_DIMENSIONS = (
    "structural_judgment",
    "evidence_density",
    "honesty",
    "actionability",
    "cross_chapter_coherence",
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _print_config(label: str, batch: dict[str, Any]) -> None:
    cfg = batch.get("config") or {}
    print(f"  {label}:")
    print(f"    batch_id        = {batch.get('batch_id')}")
    print(f"    generator       = {cfg.get('generator_provider')}/{cfg.get('generator_model')}")
    print(f"    generator_prompt= {cfg.get('generator_prompt')}")
    print(f"    reviewer        = {cfg.get('reviewer_provider')}/{cfg.get('reviewer_model')}")
    print(f"    reviewer_rubric = {cfg.get('reviewer_rubric')}")
    print(f"    limitation      = {cfg.get('limitation', '(none)')}")


def _safe_float(x: Any) -> float | None:
    if isinstance(x, (int, float)):
        return float(x)
    return None


def _summary_diff(base: dict[str, Any], cand: dict[str, Any]) -> None:
    print()
    print("=" * 68)
    print("总体均值对比")
    print("=" * 68)
    bs = base.get("summary") or {}
    cs = cand.get("summary") or {}
    print(f"{'指标':<28} {'baseline':>12} {'candidate':>12} {'Δ':>10}")
    print("-" * 68)

    bt = _safe_float(bs.get("average_total"))
    ct = _safe_float(cs.get("average_total"))
    delta = (ct - bt) if (bt is not None and ct is not None) else None
    sign = "+" if (delta is not None and delta >= 0) else ""
    delta_str = f"{sign}{delta:.2f}" if delta is not None else "n/a"
    print(f"{'average_total (out of 25)':<28} {bt:>12.2f} {ct:>12.2f} {delta_str:>10}")

    for dim in _DIMENSIONS:
        bv = _safe_float((bs.get("average_scores") or {}).get(dim))
        cv = _safe_float((cs.get("average_scores") or {}).get(dim))
        if bv is None or cv is None:
            continue
        d = cv - bv
        s = "+" if d >= 0 else ""
        print(f"  {dim:<26} {bv:>12.2f} {cv:>12.2f} {s}{d:>9.2f}")

    print(f"{'min_total':<28} {_fmt(bs.get('min_total')):>12} {_fmt(cs.get('min_total')):>12}")
    print(f"{'max_total':<28} {_fmt(bs.get('max_total')):>12} {_fmt(cs.get('max_total')):>12}")
    print(
        f"{'success rate':<28} "
        f"{_success_rate(bs):>12} {_success_rate(cs):>12}"
    )
    print(
        f"{'total duration (s)':<28} "
        f"{_fmt(bs.get('total_duration_s')):>12} "
        f"{_fmt(cs.get('total_duration_s')):>12}"
    )
    print(
        f"{'total input tokens':<28} "
        f"{_fmt(bs.get('total_input_tokens')):>12} "
        f"{_fmt(cs.get('total_input_tokens')):>12}"
    )


def _fmt(x: Any) -> str:
    if x is None:
        return "n/a"
    if isinstance(x, float):
        return f"{x:.1f}"
    return str(x)


def _success_rate(summary: dict[str, Any]) -> str:
    sc = summary.get("success_count")
    tot = summary.get("total_questions")
    if sc is None or tot is None:
        if summary.get("all_outcomes_success") is True:
            return "all"
        return "n/a"
    return f"{sc}/{tot}"


def _per_question_diff(base: dict[str, Any], cand: dict[str, Any]) -> None:
    print()
    print("=" * 68)
    print("逐题对比")
    print("=" * 68)
    base_by_id = {q.get("id"): q for q in (base.get("questions") or [])}
    cand_by_id = {q.get("id"): q for q in (cand.get("questions") or [])}
    ids = list(base_by_id.keys())
    # 候选独有题（极少）
    for qid in cand_by_id:
        if qid not in ids:
            ids.append(qid)
    win = lose = tie = 0
    for qid in ids:
        b = base_by_id.get(qid) or {}
        c = cand_by_id.get(qid) or {}
        bt = _safe_float((b.get("review") or {}).get("total"))
        ct = _safe_float((c.get("review") or {}).get("total"))
        bcite = (b.get("smoke") or {}).get("citation_count")
        ccite = (c.get("smoke") or {}).get("citation_count")
        bdur = (b.get("smoke") or {}).get("duration_s")
        cdur = (c.get("smoke") or {}).get("duration_s")
        # tool_call_names 只在新格式有
        ctool = ((c.get("smoke") or {}).get("trace_summary") or {}).get(
            "tool_call_names"
        )
        ctool_n = len(ctool) if isinstance(ctool, list) else None

        delta = None
        verdict = "n/a"
        if bt is not None and ct is not None:
            delta = ct - bt
            if delta > 0.5:
                verdict = "candidate WIN"
                win += 1
            elif delta < -0.5:
                verdict = "candidate LOSE"
                lose += 1
            else:
                verdict = "tie"
                tie += 1

        qtype = b.get("type") or c.get("type") or ""
        print(f"\n  [{qid}] [{qtype}] {verdict}")
        print(
            f"    total : baseline={_fmt(bt)}  candidate={_fmt(ct)}  "
            f"Δ={('+' if (delta is not None and delta >= 0) else '')}"
            f"{_fmt(delta)}"
        )
        print(
            f"    cite  : baseline={_fmt(bcite)}  candidate={_fmt(ccite)}"
            + (f"  tool_calls={ctool_n}" if ctool_n is not None else "")
        )
        print(f"    dur(s): baseline={_fmt(bdur)}  candidate={_fmt(cdur)}")
        # per-dim diff（如果都有）
        bs = (b.get("review") or {}).get("scores") or {}
        cs = (c.get("review") or {}).get("scores") or {}
        if bs and cs:
            for dim in _DIMENSIONS:
                bv = _safe_float(bs.get(dim))
                cv = _safe_float(cs.get(dim))
                if bv is None or cv is None:
                    continue
                d = cv - bv
                if abs(d) >= 0.5:
                    s = "+" if d >= 0 else ""
                    print(f"      {dim}: {bv:.0f} → {cv:.0f} ({s}{d:.0f})")
    print()
    print(f"  汇总: candidate WIN {win} / LOSE {lose} / TIE {tie}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--baseline", type=Path, required=True)
    p.add_argument("--candidate", type=Path, required=True)
    args = p.parse_args()

    if not args.baseline.is_file():
        print(f"baseline 不存在: {args.baseline}", file=sys.stderr)
        return 1
    if not args.candidate.is_file():
        print(f"candidate 不存在: {args.candidate}", file=sys.stderr)
        return 1

    base = _load(args.baseline)
    cand = _load(args.candidate)

    print("=" * 68)
    print("BookScope batch 对照报告")
    print("=" * 68)
    _print_config("baseline ", base)
    _print_config("candidate", cand)

    _summary_diff(base, cand)
    _per_question_diff(base, cand)
    return 0


if __name__ == "__main__":
    sys.exit(main())
