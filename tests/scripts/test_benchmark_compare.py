"""benchmark_compare.py + benchmark_run_and_report.py 单测。

覆盖：

- 完全一致的两份 JSON → 0% 变化 + STABLE
- P50 下降 30% → IMPROVEMENT 判定 + exit 0
- P50 上涨 25% → REGRESSION 判定 + exit 1
- 缺字段 JSON → 友好错误提示而非 traceback
- benchmark_run_and_report dry-run → JSON + Markdown 都生成且字段对齐
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# 让 scripts/ 可被 import
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts import benchmark_compare, benchmark_run_and_report  # noqa: E402

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _make_payload(
    *,
    p50: float,
    p90: float,
    mean: float,
    timestamp: str = "2026-05-01T12:00:00",
    commit: str = "abc1234",
) -> dict:
    """构造最小可用 v2 schema payload。"""
    return {
        "schema": "bookscope-benchmark/v2",
        "timestamp": timestamp,
        "git_commit": commit,
        "git_branch": "r1-agent-loop",
        "questions_count": 3,
        "p50_ms": p50,
        "p90_ms": p90,
        "mean_ms": mean,
        "per_question": [
            {"id": "q1", "duration_ms": p50 * 0.8, "outcome": "success"},
            {"id": "q2", "duration_ms": p50, "outcome": "success"},
            {"id": "q3", "duration_ms": p90, "outcome": "success"},
        ],
        "config": {
            "provider": "minimax",
            "prompt_version": "v3.4",
            "max_iterations": 12,
            "questions_path": "docs/internal/experiments/data/v2-batch-01.json",
            "concurrency": 5,
            "dry_run": False,
        },
    }


def _write_json(tmp_path: Path, name: str, payload: dict) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# benchmark_compare.main：四个等级判定
# ---------------------------------------------------------------------------


def test_compare_identical_payloads_is_stable(tmp_path, capsys):
    """两份 JSON 完全一致 → P50 变化 0%，STABLE，exit 0。"""
    payload = _make_payload(p50=100_000, p90=150_000, mean=110_000)
    a = _write_json(tmp_path, "prev.json", payload)
    b = _write_json(tmp_path, "curr.json", payload)

    rc = benchmark_compare.main([str(a), str(b)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "STABLE" in out
    assert "+0.0%" in out or "0.0%" in out


def test_compare_improvement_exits_zero(tmp_path, capsys):
    """P50 下降 30% → IMPROVEMENT，exit 0，stdout 含改善段落。"""
    prev = _make_payload(p50=100_000, p90=150_000, mean=110_000)
    curr = _make_payload(p50=70_000, p90=110_000, mean=80_000, commit="def5678")
    prev_path = _write_json(tmp_path, "prev.json", prev)
    curr_path = _write_json(tmp_path, "curr.json", curr)

    rc = benchmark_compare.main([str(prev_path), str(curr_path)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "IMPROVEMENT" in out
    # -30% 应在输出
    assert "-30.0%" in out


def test_compare_regression_exits_one(tmp_path, capsys):
    """P50 上涨 25%（超 20% 阈值）→ REGRESSION，exit 1。"""
    prev = _make_payload(p50=100_000, p90=150_000, mean=110_000)
    curr = _make_payload(p50=125_000, p90=180_000, mean=135_000, commit="bad9999")
    prev_path = _write_json(tmp_path, "prev.json", prev)
    curr_path = _write_json(tmp_path, "curr.json", curr)

    rc = benchmark_compare.main([str(prev_path), str(curr_path)])
    out = capsys.readouterr().out

    assert rc == 1
    assert "REGRESSION" in out
    assert "+25.0%" in out


def test_compare_threshold_override_avoids_false_regression(tmp_path, capsys):
    """阈值改为 30 后，+25% 不再判 REGRESSION。"""
    prev = _make_payload(p50=100_000, p90=150_000, mean=110_000)
    curr = _make_payload(p50=125_000, p90=180_000, mean=135_000)
    prev_path = _write_json(tmp_path, "prev.json", prev)
    curr_path = _write_json(tmp_path, "curr.json", curr)

    rc = benchmark_compare.main(
        [str(prev_path), str(curr_path), "--threshold", "30"]
    )
    out = capsys.readouterr().out

    assert rc == 0
    assert "STABLE" in out


def test_compare_missing_field_friendly_error(tmp_path, capsys):
    """缺字段的 JSON → 友好错误 + exit 2，不抛 KeyError。"""
    bad = {"schema": "bookscope-benchmark/v2", "timestamp": "2026-05-01"}
    good = _make_payload(p50=100_000, p90=150_000, mean=110_000)
    bad_path = _write_json(tmp_path, "bad.json", bad)
    good_path = _write_json(tmp_path, "good.json", good)

    rc = benchmark_compare.main([str(bad_path), str(good_path)])
    err = capsys.readouterr().err

    assert rc == 2
    assert "缺字段" in err
    # 不能让 traceback 冒上来
    assert "Traceback" not in err


def test_compare_missing_file_friendly_error(tmp_path, capsys):
    """不存在的文件 → 友好错误 + exit 2。"""
    good = _make_payload(p50=100_000, p90=150_000, mean=110_000)
    good_path = _write_json(tmp_path, "good.json", good)
    missing = tmp_path / "ghost.json"

    rc = benchmark_compare.main([str(missing), str(good_path)])
    err = capsys.readouterr().err

    assert rc == 2
    assert "不存在" in err


# ---------------------------------------------------------------------------
# benchmark_run_and_report：dry-run 端到端
# ---------------------------------------------------------------------------


def _write_questions_json(tmp_path: Path) -> Path:
    """伪造一份 v2-batch-01 形态的题集。"""
    payload = {
        "batch_id": "test-batch",
        "questions": [
            {"id": "q1", "type": "节奏评估", "smoke": {"question": "Q1?"}},
            {"id": "q2", "type": "支线", "smoke": {"question": "Q2?"}},
            {"id": "q3", "type": "伏笔", "smoke": {"question": "Q3?"}},
        ],
    }
    p = tmp_path / "questions.json"
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return p


def test_run_and_report_dry_run_writes_json_and_markdown(tmp_path, capsys):
    """dry-run 模式跑 → 生成 JSON + Markdown，字段对齐 schema。"""
    qs_path = _write_questions_json(tmp_path)
    out_dir = tmp_path / "out"

    rc = benchmark_run_and_report.main(
        [
            "--questions",
            str(qs_path),
            "--output-dir",
            str(out_dir),
            "--dry-run",
        ]
    )
    assert rc == 0

    json_files = list(out_dir.glob("benchmark-*.json"))
    md_files = list(out_dir.glob("benchmark-*.md"))
    assert len(json_files) == 1
    assert len(md_files) == 1

    payload = json.loads(json_files[0].read_text(encoding="utf-8"))
    # schema 字段全在
    for key in ("schema", "timestamp", "git_commit", "git_branch",
                "questions_count", "p50_ms", "p90_ms", "mean_ms",
                "per_question", "config"):
        assert key in payload, f"缺字段 {key}"
    assert payload["questions_count"] == 3
    assert payload["config"]["dry_run"] is True
    assert len(payload["per_question"]) == 3
    for q in payload["per_question"]:
        assert q["outcome"] == "success"
        assert isinstance(q["duration_ms"], (int, float))

    md_text = md_files[0].read_text(encoding="utf-8")
    assert "BookScope benchmark" in md_text
    assert "dry-run" in md_text
    assert "q1" in md_text


def test_run_and_report_dry_run_payload_compatible_with_compare(tmp_path):
    """dry-run 出的 JSON 直接喂给 benchmark_compare 应能跑通。"""
    qs_path = _write_questions_json(tmp_path)
    out_dir = tmp_path / "out"

    benchmark_run_and_report.main(
        ["--questions", str(qs_path), "--output-dir", str(out_dir), "--dry-run"]
    )
    json_files = list(out_dir.glob("benchmark-*.json"))
    assert len(json_files) == 1

    # 自比自 → STABLE / 0%
    rc = benchmark_compare.main([str(json_files[0]), str(json_files[0])])
    assert rc == 0


def test_run_and_report_missing_questions_file_returns_one(tmp_path, capsys):
    """题集文件不存在 → exit 1 + 友好提示。"""
    rc = benchmark_run_and_report.main(
        [
            "--questions",
            str(tmp_path / "ghost.json"),
            "--output-dir",
            str(tmp_path),
            "--dry-run",
        ]
    )
    err = capsys.readouterr().err
    assert rc == 1
    assert "不存在" in err
