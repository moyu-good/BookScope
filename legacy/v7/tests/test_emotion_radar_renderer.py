"""Unit tests for EmotionRadarRenderer + ChartDataAdapter.build_emotion_radar_data."""

import plotly.graph_objects as go
import pytest

from bookscope.models import EmotionScore
from bookscope.viz.chart_data_adapter import ChartDataAdapter, EmotionRadarData
from bookscope.viz.emotion_radar_renderer import EmotionRadarRenderer


def _score(chunk_index: int, **kwargs) -> EmotionScore:
    return EmotionScore(chunk_index=chunk_index, **kwargs)


# ---------------------------------------------------------------------------
# ChartDataAdapter.build_emotion_radar_data
# ---------------------------------------------------------------------------

class TestBuildEmotionRadarData:
    def test_empty_input_returns_empty(self):
        data = ChartDataAdapter.build_emotion_radar_data([])
        assert data.labels == []
        assert data.values == []
        assert data.colors == []

    def test_returns_emotion_radar_data(self):
        scores = [_score(0, joy=0.5)]
        data = ChartDataAdapter.build_emotion_radar_data(scores)
        assert isinstance(data, EmotionRadarData)

    def test_eight_axes(self):
        scores = [_score(i, joy=0.5) for i in range(3)]
        data = ChartDataAdapter.build_emotion_radar_data(scores)
        assert len(data.labels) == 8
        assert len(data.values) == 8
        assert len(data.colors) == 8

    def test_values_in_0_1_range(self):
        scores = [_score(0, joy=1.0, fear=0.5, anger=0.3)]
        data = ChartDataAdapter.build_emotion_radar_data(scores)
        for v in data.values:
            assert 0.0 <= v <= 1.0

    def test_values_are_averages(self):
        scores = [_score(0, joy=0.4), _score(1, joy=0.6)]
        data = ChartDataAdapter.build_emotion_radar_data(scores)
        joy_idx = data.labels.index("Joy")
        assert data.values[joy_idx] == pytest.approx(0.5)

    def test_all_zero_scores_produce_zero_values(self):
        scores = [_score(0)]  # all emotions default to 0.0
        data = ChartDataAdapter.build_emotion_radar_data(scores)
        assert all(v == pytest.approx(0.0) for v in data.values)

    def test_custom_colors_applied(self):
        scores = [_score(0, joy=0.5)]
        data = ChartDataAdapter.build_emotion_radar_data(
            scores, emotion_colors={"joy": "#ffcc00"}
        )
        joy_idx = data.labels.index("Joy")
        assert data.colors[joy_idx] == "#ffcc00"

    def test_fallback_color_for_missing_emotion(self):
        scores = [_score(0)]
        data = ChartDataAdapter.build_emotion_radar_data(scores, emotion_colors={})
        for color in data.colors:
            assert color.startswith("#")

    def test_labels_are_capitalized(self):
        scores = [_score(0)]
        data = ChartDataAdapter.build_emotion_radar_data(scores)
        for label in data.labels:
            assert label[0].isupper()

    def test_single_chunk_equals_its_values(self):
        scores = [_score(0, joy=0.7, fear=0.3)]
        data = ChartDataAdapter.build_emotion_radar_data(scores)
        joy_idx = data.labels.index("Joy")
        fear_idx = data.labels.index("Fear")
        assert data.values[joy_idx] == pytest.approx(0.7)
        assert data.values[fear_idx] == pytest.approx(0.3)


# ---------------------------------------------------------------------------
# EmotionRadarRenderer
# ---------------------------------------------------------------------------

class TestEmotionRadarRenderer:
    def _make_data(self, n: int = 8) -> EmotionRadarData:
        labels = [f"E{i}" for i in range(n)]
        values = [0.1 * (i + 1) for i in range(n)]
        colors = ["#aabbcc"] * n
        return EmotionRadarData(labels=labels, values=values, colors=colors)

    def test_empty_data_returns_empty_figure(self):
        renderer = EmotionRadarRenderer()
        data = EmotionRadarData(labels=[], values=[], colors=[])
        fig = renderer.render(data)
        assert len(fig.data) == 0

    def test_returns_plotly_figure(self):
        renderer = EmotionRadarRenderer()
        fig = renderer.render(self._make_data())
        assert isinstance(fig, go.Figure)

    def test_single_scatterpolar_trace(self):
        renderer = EmotionRadarRenderer()
        fig = renderer.render(self._make_data())
        assert len(fig.data) == 1
        assert isinstance(fig.data[0], go.Scatterpolar)

    def test_polygon_closed_extra_point(self):
        """Renderer adds one extra point to close the polygon."""
        renderer = EmotionRadarRenderer()
        n = 4
        data = EmotionRadarData(
            labels=["Joy", "Fear", "Trust", "Anger"],
            values=[0.5, 0.3, 0.4, 0.2],
            colors=["#aabbcc"] * 4,
        )
        fig = renderer.render(data)
        trace = fig.data[0]
        assert len(trace.theta) == n + 1
        assert len(trace.r) == n + 1
        assert trace.theta[-1] == trace.theta[0]

    def test_polygon_r_first_equals_last(self):
        """r[0] == r[-1] after polygon close."""
        renderer = EmotionRadarRenderer()
        data = EmotionRadarData(
            labels=["Joy", "Fear"],
            values=[0.7, 0.3],
            colors=["#aabbcc", "#bbccdd"],
        )
        fig = renderer.render(data)
        assert fig.data[0].r[0] == pytest.approx(fig.data[0].r[-1])

    def test_fill_is_toself(self):
        renderer = EmotionRadarRenderer()
        fig = renderer.render(self._make_data())
        assert fig.data[0].fill == "toself"

    def test_dominant_color_used_for_fill(self):
        """The dominant (max-value) emotion color anchors the fill."""
        renderer = EmotionRadarRenderer()
        # Joy (index 0) has value 0.9 — dominant
        data = EmotionRadarData(
            labels=["Joy", "Fear"],
            values=[0.9, 0.1],
            colors=["#22c55e", "#ef4444"],  # Joy=green
        )
        fig = renderer.render(data)
        fill_color = fig.data[0].fillcolor
        # rgba derived from #22c55e → r=34
        assert "34" in fill_color

    def test_radial_range_0_to_1(self):
        renderer = EmotionRadarRenderer()
        fig = renderer.render(self._make_data())
        r = fig.layout.polar.radialaxis.range
        assert r[0] == 0
        assert r[1] == 1

    def test_single_label_no_crash(self):
        renderer = EmotionRadarRenderer()
        data = EmotionRadarData(labels=["Joy"], values=[0.5], colors=["#aabbcc"])
        fig = renderer.render(data)
        assert isinstance(fig, go.Figure)
