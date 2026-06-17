"""Unit tests for EmotionHeatmapRenderer and ChartDataAdapter.emotion_heatmap."""

import plotly.graph_objects as go
import pytest

from bookscope.models import ChunkResult, EmotionScore
from bookscope.viz.chart_data_adapter import ChartDataAdapter, EmotionHeatmapData
from bookscope.viz.heatmap import EmotionHeatmapRenderer

_N_EMOTIONS = 8


def make_scores(n: int) -> list[EmotionScore]:
    return [EmotionScore(chunk_index=i, joy=i / max(n - 1, 1)) for i in range(n)]


def make_chunks(n: int, words: int = 50) -> list[ChunkResult]:
    return [ChunkResult(index=i, text=f"{'word ' * words}chunk {i}") for i in range(n)]


class TestEmotionHeatmapAdapter:
    def test_empty_input(self):
        data = ChartDataAdapter.emotion_heatmap([])
        assert data.x == []
        assert len(data.z) == _N_EMOTIONS
        assert len(data.y) == _N_EMOTIONS

    def test_returns_heatmap_data(self):
        assert isinstance(ChartDataAdapter.emotion_heatmap(make_scores(3)), EmotionHeatmapData)

    def test_z_shape(self):
        n = 10
        data = ChartDataAdapter.emotion_heatmap(make_scores(n))
        assert len(data.z) == _N_EMOTIONS
        for row in data.z:
            assert len(row) == n

    def test_x_is_chunk_indices(self):
        data = ChartDataAdapter.emotion_heatmap(make_scores(5))
        assert data.x == [0, 1, 2, 3, 4]

    def test_sorts_by_chunk_index(self):
        scores = [
            EmotionScore(chunk_index=2, joy=0.9),
            EmotionScore(chunk_index=0, joy=0.1),
            EmotionScore(chunk_index=1, joy=0.5),
        ]
        data = ChartDataAdapter.emotion_heatmap(scores)
        assert data.x == [0, 1, 2]
        joy_row = data.z[data.y.index("joy")]
        assert joy_row == [pytest.approx(0.1), pytest.approx(0.5), pytest.approx(0.9)]

    def test_y_contains_all_eight_emotions(self):
        data = ChartDataAdapter.emotion_heatmap(make_scores(3))
        assert set(data.y) == {
            "anger", "anticipation", "disgust", "fear",
            "joy", "sadness", "surprise", "trust",
        }

    def test_no_hover_texts_without_chunks(self):
        data = ChartDataAdapter.emotion_heatmap(make_scores(3))
        assert data.hover_texts == []

    def test_hover_texts_length_matches_chunks(self):
        n = 5
        data = ChartDataAdapter.emotion_heatmap(make_scores(n), chunks=make_chunks(n))
        assert len(data.hover_texts) == n

    def test_hover_texts_are_truncated(self):
        chunks = [ChunkResult(index=0, text="x" * 300)]
        data = ChartDataAdapter.emotion_heatmap(make_scores(1), chunks=chunks, snippet_len=160)
        assert len(data.hover_texts[0]) <= 161  # 160 chars + ellipsis

    def test_hover_texts_contain_chunk_content(self):
        chunks = [ChunkResult(index=0, text="The quick brown fox")]
        data = ChartDataAdapter.emotion_heatmap(make_scores(1), chunks=chunks)
        assert "The quick brown fox" in data.hover_texts[0]

    def test_hover_texts_empty_string_for_missing_chunk_index(self):
        """When a chunk index has no matching ChunkResult, hover text should be ''."""
        scores = [EmotionScore(chunk_index=5, joy=0.5)]
        chunks = [ChunkResult(index=0, text="Wrong chunk")]  # index 0, not 5
        data = ChartDataAdapter.emotion_heatmap(scores, chunks=chunks)
        assert len(data.hover_texts) == 1
        assert data.hover_texts[0] == ""


class TestEmotionHeatmapRenderer:
    def setup_method(self):
        self.renderer = EmotionHeatmapRenderer()

    def test_returns_figure(self):
        data = ChartDataAdapter.emotion_heatmap(make_scores(5))
        assert isinstance(self.renderer.render(data), go.Figure)

    def test_empty_returns_empty_figure(self):
        data = ChartDataAdapter.emotion_heatmap([])
        fig = self.renderer.render(data)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 0

    def test_has_one_heatmap_trace(self):
        data = ChartDataAdapter.emotion_heatmap(make_scores(5))
        fig = self.renderer.render(data)
        assert len(fig.data) == 1
        assert isinstance(fig.data[0], go.Heatmap)

    def test_customdata_present_when_hover_texts_provided(self):
        data = ChartDataAdapter.emotion_heatmap(make_scores(3), chunks=make_chunks(3))
        fig = self.renderer.render(data)
        assert fig.data[0].customdata is not None

    def test_no_customdata_without_hover_texts(self):
        data = ChartDataAdapter.emotion_heatmap(make_scores(3))
        fig = self.renderer.render(data)
        assert fig.data[0].customdata is None

    def test_colorscale_is_blues(self):
        """Heatmap must use the Blues colorscale (not RdYlGn which mapped anger=green).
        Plotly expands named colorscales into (fraction, rgb_string) tuples; verify by
        checking the characteristic first and last colours of the Blues palette."""
        data = ChartDataAdapter.emotion_heatmap(make_scores(5))
        fig = self.renderer.render(data)
        colorscale = fig.data[0].colorscale
        assert colorscale[0][1] == "rgb(247,251,255)"   # lightest Blues colour
        assert colorscale[-1][1] == "rgb(8,48,107)"     # darkest Blues colour

    def test_dynamic_zmax_reflects_data_maximum(self):
        """zmax must be ~1.1× the actual data maximum so colors span real distribution."""
        n = 10
        data = ChartDataAdapter.emotion_heatmap(make_scores(n))
        fig = self.renderer.render(data)
        all_vals = [v for row in data.z for v in row if v is not None]
        expected_zmax = max(all_vals) * 1.1
        assert fig.data[0].zmax == pytest.approx(expected_zmax, rel=1e-6)

    def test_empty_scores_produces_empty_figure(self):
        data = ChartDataAdapter.emotion_heatmap([])
        fig = self.renderer.render(data)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 0
