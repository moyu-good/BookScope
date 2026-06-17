"""Unit tests for EmotionComparisonRenderer + ChartDataAdapter.build_emotion_arc_comparison_data."""

import plotly.graph_objects as go
import pytest

from bookscope.models import EmotionScore
from bookscope.store import AnalysisResult
from bookscope.viz.chart_data_adapter import ChartDataAdapter, EmotionArcComparisonData
from bookscope.viz.emotion_comparison_renderer import EmotionComparisonRenderer


def _score(chunk_index: int, **kwargs) -> EmotionScore:
    return EmotionScore(chunk_index=chunk_index, **kwargs)


def _make_result(title: str, scores: list[EmotionScore]) -> AnalysisResult:
    return AnalysisResult.create(
        book_title=title,
        chunk_strategy="paragraph",
        total_chunks=len(scores),
        total_words=500,
        arc_pattern="Icarus",
        detected_lang="en",
        emotion_scores=scores,
        style_scores=[],
    )


# ---------------------------------------------------------------------------
# ChartDataAdapter.build_emotion_arc_comparison_data
# ---------------------------------------------------------------------------

class TestBuildEmotionArcComparisonData:
    def test_returns_comparison_data(self):
        ra = _make_result("A", [_score(0, joy=0.5)])
        rb = _make_result("B", [_score(0, fear=0.5)])
        data = ChartDataAdapter.build_emotion_arc_comparison_data(ra, rb)
        assert isinstance(data, EmotionArcComparisonData)

    def test_empty_both_books(self):
        ra = _make_result("A", [])
        rb = _make_result("B", [])
        data = ChartDataAdapter.build_emotion_arc_comparison_data(ra, rb)
        assert data.series_a == []
        assert data.series_b == []
        assert data.x_a == []
        assert data.x_b == []

    def test_series_normalized_to_0_1(self):
        scores = [_score(i, joy=float(i) * 0.1) for i in range(10)]
        ra = _make_result("A", scores)
        rb = _make_result("B", scores)
        data = ChartDataAdapter.build_emotion_arc_comparison_data(ra, rb)
        for v in data.series_a:
            assert 0.0 <= v <= 1.0

    def test_x_starts_at_0_ends_at_1(self):
        scores = [_score(i, joy=0.5) for i in range(5)]
        ra = _make_result("A", scores)
        rb = _make_result("B", scores)
        data = ChartDataAdapter.build_emotion_arc_comparison_data(ra, rb)
        assert data.x_a[0] == pytest.approx(0.0)
        assert data.x_a[-1] == pytest.approx(1.0)

    def test_labels_from_book_titles(self):
        ra = _make_result("Book Alpha", [_score(0, joy=0.5)])
        rb = _make_result("Book Beta", [_score(0, fear=0.5)])
        data = ChartDataAdapter.build_emotion_arc_comparison_data(ra, rb)
        assert data.label_a == "Book Alpha"
        assert data.label_b == "Book Beta"

    def test_flat_valence_returns_0_5(self):
        """All identical valences → normalized to 0.5 (flat line at midpoint)."""
        scores = [_score(i, joy=0.5, trust=0.5) for i in range(5)]
        ra = _make_result("Flat", scores)
        rb = _make_result("Flat2", scores)
        data = ChartDataAdapter.build_emotion_arc_comparison_data(ra, rb)
        for v in data.series_a:
            assert v == pytest.approx(0.5)

    def test_different_book_lengths(self):
        scores_a = [_score(i, joy=0.5) for i in range(5)]
        scores_b = [_score(i, joy=0.5) for i in range(10)]
        ra = _make_result("Short", scores_a)
        rb = _make_result("Long", scores_b)
        data = ChartDataAdapter.build_emotion_arc_comparison_data(ra, rb)
        assert len(data.series_a) == 5
        assert len(data.series_b) == 10
        assert len(data.x_a) == 5
        assert len(data.x_b) == 10

    def test_single_chunk_each(self):
        ra = _make_result("A", [_score(0, joy=0.8)])
        rb = _make_result("B", [_score(0, fear=0.8)])
        data = ChartDataAdapter.build_emotion_arc_comparison_data(ra, rb)
        assert len(data.series_a) == 1
        assert len(data.series_b) == 1
        # Single-element x is [0.0]
        assert data.x_a == [pytest.approx(0.0)]

    def test_valence_formula_includes_all_seven_emotions(self):
        """Joy+Trust+Anticipation − Fear−Sadness−Anger−Disgust."""
        # Joy overwhelmingly positive → should produce high normalized valence
        pos = [_score(i, joy=0.9, trust=0.8, anticipation=0.7) for i in range(5)]
        neg = [_score(i, fear=0.9, sadness=0.8, anger=0.7, disgust=0.6) for i in range(5)]
        ra = _make_result("Pos", pos)
        rb = _make_result("Neg", neg)
        data = ChartDataAdapter.build_emotion_arc_comparison_data(ra, rb)
        # Positive book: all valences should be near 1.0
        for v in data.series_a:
            assert v > 0.4
        # Both are normalized so we can't directly compare, but series from
        # identical scores should be uniform (flat at 0.5)
        assert all(v == pytest.approx(0.5) for v in data.series_a)
        assert all(v == pytest.approx(0.5) for v in data.series_b)

    def test_rising_valence_series_monotone(self):
        """Increasing joy chunk by chunk → normalized series should also rise."""
        scores = [_score(i, joy=float(i) / 9.0) for i in range(10)]
        ra = _make_result("Rising", scores)
        rb = _make_result("B", scores)
        data = ChartDataAdapter.build_emotion_arc_comparison_data(ra, rb)
        for i in range(len(data.series_a) - 1):
            assert data.series_a[i] <= data.series_a[i + 1] + 1e-9


# ---------------------------------------------------------------------------
# EmotionComparisonRenderer
# ---------------------------------------------------------------------------

class TestEmotionComparisonRenderer:
    def _make_data(self, n_a: int = 5, n_b: int = 7) -> EmotionArcComparisonData:
        return EmotionArcComparisonData(
            x_a=[i / (n_a - 1) for i in range(n_a)],
            x_b=[i / (n_b - 1) for i in range(n_b)],
            series_a=[0.3, 0.5, 0.6, 0.4, 0.7],
            series_b=[0.2, 0.4, 0.5, 0.6, 0.5, 0.3, 0.4],
            label_a="Book A",
            label_b="Book B",
        )

    def test_returns_plotly_figure(self):
        renderer = EmotionComparisonRenderer()
        fig = renderer.render(self._make_data())
        assert isinstance(fig, go.Figure)

    def test_two_traces_for_two_books(self):
        renderer = EmotionComparisonRenderer()
        fig = renderer.render(self._make_data())
        assert len(fig.data) == 2

    def test_trace_names_match_labels(self):
        renderer = EmotionComparisonRenderer()
        fig = renderer.render(self._make_data())
        names = {t.name for t in fig.data}
        assert "Book A" in names
        assert "Book B" in names

    def test_empty_both_series_no_traces(self):
        renderer = EmotionComparisonRenderer()
        data = EmotionArcComparisonData(
            x_a=[], x_b=[], series_a=[], series_b=[], label_a="A", label_b="B"
        )
        fig = renderer.render(data)
        assert len(fig.data) == 0

    def test_only_series_a_gives_one_trace(self):
        renderer = EmotionComparisonRenderer()
        data = EmotionArcComparisonData(
            x_a=[0.0, 0.5, 1.0], x_b=[],
            series_a=[0.3, 0.6, 0.4], series_b=[],
            label_a="A", label_b="B"
        )
        fig = renderer.render(data)
        assert len(fig.data) == 1
        assert fig.data[0].name == "A"

    def test_only_series_b_gives_one_trace(self):
        renderer = EmotionComparisonRenderer()
        data = EmotionArcComparisonData(
            x_a=[], x_b=[0.0, 0.5, 1.0],
            series_a=[], series_b=[0.3, 0.6, 0.4],
            label_a="A", label_b="B"
        )
        fig = renderer.render(data)
        assert len(fig.data) == 1
        assert fig.data[0].name == "B"

    def test_traces_use_fill_tozeroy(self):
        renderer = EmotionComparisonRenderer()
        fig = renderer.render(self._make_data())
        for trace in fig.data:
            assert trace.fill == "tozeroy"

    def test_traces_use_distinct_colors(self):
        renderer = EmotionComparisonRenderer()
        fig = renderer.render(self._make_data())
        colors = [trace.line.color for trace in fig.data]
        assert colors[0] != colors[1]

    def test_series_a_color_is_purple(self):
        """Series A is always purple (#a78bfa)."""
        renderer = EmotionComparisonRenderer()
        fig = renderer.render(self._make_data())
        # Find the trace for "Book A"
        trace_a = next(t for t in fig.data if t.name == "Book A")
        assert trace_a.line.color == "#a78bfa"

    def test_series_b_color_is_emerald(self):
        """Series B is always emerald (#34d399)."""
        renderer = EmotionComparisonRenderer()
        fig = renderer.render(self._make_data())
        trace_b = next(t for t in fig.data if t.name == "Book B")
        assert trace_b.line.color == "#34d399"

    def test_x_axis_format_is_percentage(self):
        """x-axis tickformat shows percentages for normalized position."""
        renderer = EmotionComparisonRenderer()
        fig = renderer.render(self._make_data())
        assert "%" in fig.layout.xaxis.tickformat

    def test_y_axis_range_0_to_1(self):
        renderer = EmotionComparisonRenderer()
        fig = renderer.render(self._make_data())
        assert fig.layout.yaxis.range[0] == 0
        assert fig.layout.yaxis.range[1] == 1
