"""Sprint 6 KG 缓存 probe scripts 单测。

覆盖：

- ``probe_kg_cache_timing.py`` CLI 参数解析正确
- ``probe_kg_cache_quality.py`` CLI 参数解析正确
- timing 撤回：warm vs empty speedup 不足 10x → ``validation_failed=True``
- quality 撤回：5 维度任一题 std > 0.5 → ``validation_failed=True``

不真跑 LLM——直接喂数据点给纯函数 ``evaluate_speedup`` /
``compare_quality_runs``。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 让 scripts/ 可被 import
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts import probe_kg_cache_quality, probe_kg_cache_timing  # noqa: E402

# ---------------------------------------------------------------------------
# timing probe CLI
# ---------------------------------------------------------------------------


class TestTimingProbeCLI:
    """timing probe CLI 参数解析。"""

    def test_parse_args_anshi_empty(self) -> None:
        args = probe_kg_cache_timing._parse_args(
            ["--book", "anshi", "--cache-state", "empty"]
        )
        assert args.book == "anshi"
        assert args.cache_state == "empty"
        assert args.runs == 3  # 默认
        assert args.output is None

    def test_parse_args_mingchao_warm_custom_runs(self) -> None:
        args = probe_kg_cache_timing._parse_args(
            [
                "--book",
                "mingchao",
                "--cache-state",
                "warm",
                "--runs",
                "5",
            ]
        )
        assert args.book == "mingchao"
        assert args.cache_state == "warm"
        assert args.runs == 5

    def test_parse_args_output_path(self, tmp_path: Path) -> None:
        out = tmp_path / "custom.json"
        args = probe_kg_cache_timing._parse_args(
            [
                "--book",
                "anshi",
                "--cache-state",
                "empty",
                "--output",
                str(out),
            ]
        )
        assert args.output == out

    def test_parse_args_rejects_unknown_book(self) -> None:
        with pytest.raises(SystemExit):
            probe_kg_cache_timing._parse_args(
                ["--book", "wukong", "--cache-state", "empty"]
            )

    def test_parse_args_rejects_unknown_state(self) -> None:
        with pytest.raises(SystemExit):
            probe_kg_cache_timing._parse_args(
                ["--book", "anshi", "--cache-state", "stale"]
            )

    def test_parse_args_requires_book(self) -> None:
        with pytest.raises(SystemExit):
            probe_kg_cache_timing._parse_args(["--cache-state", "empty"])

    def test_parse_args_requires_cache_state(self) -> None:
        with pytest.raises(SystemExit):
            probe_kg_cache_timing._parse_args(["--book", "anshi"])


# ---------------------------------------------------------------------------
# quality probe CLI
# ---------------------------------------------------------------------------


class TestQualityProbeCLI:
    """quality probe CLI 参数解析。"""

    def test_parse_args_anshi_empty(self) -> None:
        args = probe_kg_cache_quality._parse_args(
            ["--book", "anshi", "--cache-state", "empty"]
        )
        assert args.book == "anshi"
        assert args.cache_state == "empty"

    def test_parse_args_mingchao_warm(self) -> None:
        args = probe_kg_cache_quality._parse_args(
            ["--book", "mingchao", "--cache-state", "warm"]
        )
        assert args.book == "mingchao"
        assert args.cache_state == "warm"

    def test_parse_args_rejects_unknown_book(self) -> None:
        with pytest.raises(SystemExit):
            probe_kg_cache_quality._parse_args(
                ["--book", "huainanzi", "--cache-state", "empty"]
            )

    def test_parse_args_rejects_unknown_state(self) -> None:
        with pytest.raises(SystemExit):
            probe_kg_cache_quality._parse_args(
                ["--book", "anshi", "--cache-state", "lukewarm"]
            )


# ---------------------------------------------------------------------------
# timing 撤回逻辑
# ---------------------------------------------------------------------------


class TestTimingValidationFailure:
    """timing speedup 撤回判定。"""

    def test_warm_much_faster_passes(self) -> None:
        """warm 50s vs empty 5s → speedup 10x，过线。

        empty=50s mean / warm=5s mean = 10.0 speedup —— 命中 ≥ 10x 阈值，
        validation_failed=False。
        """
        failed, reason, speedup = probe_kg_cache_timing.evaluate_speedup(
            empty_mean_seconds=50.0,
            warm_mean_seconds=5.0,
        )
        assert failed is False
        assert reason is None
        assert speedup == pytest.approx(10.0)

    def test_warm_much_much_faster_passes(self) -> None:
        """warm 0.1s vs empty 60s → speedup 600x，过线。"""
        failed, reason, speedup = probe_kg_cache_timing.evaluate_speedup(
            empty_mean_seconds=60.0,
            warm_mean_seconds=0.1,
        )
        assert failed is False
        assert reason is None
        assert speedup == pytest.approx(600.0)

    def test_warm_only_2x_faster_fails(self) -> None:
        """warm 25s vs empty 50s → speedup 2x，命中撤回阈值。

        2x < 10x → validation_failed=True + cache_speedup_below_10x。
        """
        failed, reason, speedup = probe_kg_cache_timing.evaluate_speedup(
            empty_mean_seconds=50.0,
            warm_mean_seconds=25.0,
        )
        assert failed is True
        assert reason == probe_kg_cache_timing.FAILURE_REASON_SPEEDUP
        assert speedup == pytest.approx(2.0)

    def test_warm_slower_than_empty_fails(self) -> None:
        """warm 70s vs empty 50s → speedup < 1，命中撤回阈值。

        缓存命中比空跑还慢——大概率是缓存层 bug 导致同时跑缓存查询 + LLM 调用。
        """
        failed, reason, speedup = probe_kg_cache_timing.evaluate_speedup(
            empty_mean_seconds=50.0,
            warm_mean_seconds=70.0,
        )
        assert failed is True
        assert reason == probe_kg_cache_timing.FAILURE_REASON_SPEEDUP
        assert speedup < 1.0

    def test_custom_min_speedup_override(self) -> None:
        """min_speedup 自定义——5x 阈值下 6x speedup 过线。"""
        failed, _, speedup = probe_kg_cache_timing.evaluate_speedup(
            empty_mean_seconds=60.0,
            warm_mean_seconds=10.0,
            min_speedup=5.0,
        )
        assert failed is False
        assert speedup == pytest.approx(6.0)

    def test_empty_run_zero_seconds_marked_as_anomaly(self) -> None:
        """empty mean 极小（接近 0）→ 数据异常，标 failure。

        理论上 empty 跑（0 LLM call 也得算下 + 落 SQLite）不可能秒级。
        """
        failed, reason, _ = probe_kg_cache_timing.evaluate_speedup(
            empty_mean_seconds=0.0,
            warm_mean_seconds=1.0,
        )
        assert failed is True
        assert reason == "empty_run_too_fast_to_measure"

    def test_warm_zero_seconds_passes_with_inf_speedup(self) -> None:
        """warm 0s 是合理的——纯磁盘 IO 可能在测量精度以下。

        speedup 视为 inf，validation_failed=False。
        """
        failed, _, speedup = probe_kg_cache_timing.evaluate_speedup(
            empty_mean_seconds=30.0,
            warm_mean_seconds=0.0,
        )
        assert failed is False
        assert speedup == float("inf")


# ---------------------------------------------------------------------------
# quality 撤回逻辑
# ---------------------------------------------------------------------------


def _make_qs(scores_list: list[dict[str, float]]) -> list[dict]:
    """构造 questions 数组，每题 ``review.scores`` 填指定 dict。"""
    return [
        {
            "id": f"q{i+1}",
            "review": {"scores": scores},
        }
        for i, scores in enumerate(scores_list)
    ]


class TestQualityValidationFailure:
    """quality 跨缓存状态评分 std 撤回判定。"""

    def test_identical_scores_pass(self) -> None:
        """empty 与 warm 跑分逐题完全相同 → 全维度 std=0，过线。"""
        scores = {
            "structural_judgment": 4.0,
            "evidence_density": 3.5,
            "honesty": 4.5,
            "actionability": 3.0,
            "cross_chapter_coherence": 4.0,
        }
        empty = _make_qs([scores] * 5)
        warm = _make_qs([scores] * 5)
        failed, reason, per_dim = probe_kg_cache_quality.compare_quality_runs(
            empty_questions=empty,
            warm_questions=warm,
        )
        assert failed is False
        assert reason is None
        for dim in probe_kg_cache_quality.QUALITY_DIMENSIONS:
            assert per_dim[dim] == 0.0

    def test_tiny_diff_within_threshold_passes(self) -> None:
        """各题各维度差 0.2-0.3 分 → std ≤ 0.5，过线。"""
        empty = _make_qs(
            [
                {
                    "structural_judgment": 4.0,
                    "evidence_density": 3.5,
                    "honesty": 4.5,
                    "actionability": 3.0,
                    "cross_chapter_coherence": 4.0,
                }
                for _ in range(5)
            ]
        )
        warm = _make_qs(
            [
                {
                    "structural_judgment": 4.2,
                    "evidence_density": 3.3,
                    "honesty": 4.5,
                    "actionability": 3.2,
                    "cross_chapter_coherence": 4.0,
                }
                for _ in range(5)
            ]
        )
        failed, reason, _ = probe_kg_cache_quality.compare_quality_runs(
            empty_questions=empty,
            warm_questions=warm,
        )
        assert failed is False
        assert reason is None

    def test_big_diff_in_one_dimension_fails(self) -> None:
        """structural_judgment 维度题间差距大（0/0/0/3/3）→ std > 0.5，触发撤回。

        diffs=[0,0,0,3,3] → stdev ≈ 1.64，远高于 0.5 阈值。
        """
        empty = _make_qs(
            [
                {"structural_judgment": 4.0},
                {"structural_judgment": 4.0},
                {"structural_judgment": 4.0},
                {"structural_judgment": 4.0},
                {"structural_judgment": 4.0},
            ]
        )
        warm = _make_qs(
            [
                {"structural_judgment": 4.0},
                {"structural_judgment": 4.0},
                {"structural_judgment": 4.0},
                {"structural_judgment": 1.0},
                {"structural_judgment": 1.0},
            ]
        )
        failed, reason, per_dim = probe_kg_cache_quality.compare_quality_runs(
            empty_questions=empty,
            warm_questions=warm,
        )
        assert failed is True
        assert reason == probe_kg_cache_quality.FAILURE_REASON_DIVERGED
        assert per_dim["structural_judgment"] > 0.5

    def test_one_question_huge_diff_fails(self) -> None:
        """单题 single-dimension 差 3 分 → 视为绝对差代理 std，触发撤回。

        diffs=[3.0]（只有 1 个题对照样本），按规则当 std 代理用——3.0 > 0.5。
        """
        empty = _make_qs([{"honesty": 5.0}])
        warm = _make_qs([{"honesty": 2.0}])
        failed, reason, per_dim = probe_kg_cache_quality.compare_quality_runs(
            empty_questions=empty,
            warm_questions=warm,
        )
        assert failed is True
        assert reason == probe_kg_cache_quality.FAILURE_REASON_DIVERGED
        assert per_dim["honesty"] == pytest.approx(3.0)

    def test_custom_max_std_override(self) -> None:
        """自定义 max_std=2.0 → 中等差距过线。"""
        empty = _make_qs([{"honesty": 5.0}, {"honesty": 5.0}, {"honesty": 5.0}])
        warm = _make_qs([{"honesty": 4.0}, {"honesty": 4.0}, {"honesty": 4.0}])
        failed, _, _ = probe_kg_cache_quality.compare_quality_runs(
            empty_questions=empty,
            warm_questions=warm,
            max_std=2.0,
        )
        # 三题差 1.0 完全一致 → stdev=0 → 过线
        assert failed is False

    def test_missing_scores_dict_skipped(self) -> None:
        """空 review / 没 scores 的题应该跳过不算 std，不抛错。"""
        empty = _make_qs([{"honesty": 4.0}])
        # warm 这题 review 缺失
        warm = [{"id": "q1", "review": {}}]
        failed, _, per_dim = probe_kg_cache_quality.compare_quality_runs(
            empty_questions=empty,
            warm_questions=warm,
        )
        # 没数据点 → std=0.0 → 不 fail
        assert failed is False
        assert per_dim["honesty"] == 0.0
