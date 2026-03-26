"""Unit tests for bookscope.viz.EmotionTimelineRenderer."""

import plotly.graph_objects as go

from bookscope.models import EmotionScore
from bookscope.viz.chart_data_adapter import ChartDataAdapter
from bookscope.viz.emotion_timeline import EmotionTimelineRenderer


def make_scores(n: int) -> list[EmotionScore]:
    return [EmotionScore(chunk_index=i, joy=i / max(n - 1, 1)) for i in range(n)]


class TestEmotionTimelineRenderer:
    def setup_method(self):
        self.renderer = EmotionTimelineRenderer()

    def test_returns_figure(self):
        data = ChartDataAdapter.emotion_timeline(make_scores(5))
        fig = self.renderer.render(data)
        assert isinstance(fig, go.Figure)

    def test_empty_data_returns_figure(self):
        data = ChartDataAdapter.emotion_timeline([])
        fig = self.renderer.render(data)
        assert isinstance(fig, go.Figure)

    def test_has_eight_traces(self):
        data = ChartDataAdapter.emotion_timeline(make_scores(5))
        fig = self.renderer.render(data)
        assert len(fig.data) == 8

    def test_trace_names_are_capitalized_emotions(self):
        data = ChartDataAdapter.emotion_timeline(make_scores(3))
        fig = self.renderer.render(data)
        names = {t.name for t in fig.data}
        expected = {"Anger", "Anticipation", "Disgust", "Fear",
                    "Joy", "Sadness", "Surprise", "Trust"}
        assert names == expected

    def test_yaxis_range_is_0_to_1(self):
        data = ChartDataAdapter.emotion_timeline(make_scores(5))
        fig = self.renderer.render(data)
        # Plotly stores range as a tuple
        assert tuple(fig.layout.yaxis.range) == (0, 1)

    def test_with_alpha_pure_black(self):
        result = EmotionTimelineRenderer._with_alpha("000000", 0.5)
        assert result == "rgba(0,0,0,0.5)"

    def test_with_alpha_strips_hash(self):
        result = EmotionTimelineRenderer._with_alpha("#ffffff", 1.0)
        assert result == "rgba(255,255,255,1.0)"
