"""Unit tests for ChartDataAdapter.style_radar and StyleRadarRenderer."""

import plotly.graph_objects as go
import pytest

from bookscope.models import StyleScore
from bookscope.viz.chart_data_adapter import ChartDataAdapter, StyleRadarData
from bookscope.viz.style_radar import StyleRadarRenderer


def make_style(idx: int, **kwargs) -> StyleScore:
    return StyleScore(chunk_index=idx, **kwargs)


class TestStyleRadarAdapter:
    def test_empty_returns_empty(self):
        data = ChartDataAdapter.style_radar([])
        assert data.labels == []
        assert data.values == []
        assert data.raw_means == {}

    def test_returns_style_radar_data(self):
        assert isinstance(ChartDataAdapter.style_radar([make_style(0)]), StyleRadarData)

    def test_six_labels(self):
        data = ChartDataAdapter.style_radar([make_style(0)])
        assert len(data.labels) == 6

    def test_six_values(self):
        data = ChartDataAdapter.style_radar([make_style(0)])
        assert len(data.values) == 6

    def test_values_in_range(self):
        scores = [make_style(i, ttr=0.5, noun_ratio=0.2, verb_ratio=0.15) for i in range(5)]
        data = ChartDataAdapter.style_radar(scores)
        for v in data.values:
            assert 0.0 <= v <= 1.0

    def test_raw_means_match_input(self):
        scores = [make_style(i, ttr=0.6) for i in range(4)]
        data = ChartDataAdapter.style_radar(scores)
        assert data.raw_means["ttr"] == pytest.approx(0.6)


class TestStyleRadarRenderer:
    def setup_method(self):
        self.renderer = StyleRadarRenderer()

    def test_returns_figure(self):
        data = ChartDataAdapter.style_radar([make_style(0, ttr=0.5)])
        assert isinstance(self.renderer.render(data), go.Figure)

    def test_empty_data_returns_empty_figure(self):
        data = ChartDataAdapter.style_radar([])
        fig = self.renderer.render(data)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 0

    def test_has_one_trace(self):
        data = ChartDataAdapter.style_radar([make_style(0, ttr=0.5, noun_ratio=0.3)])
        fig = self.renderer.render(data)
        assert len(fig.data) == 1

    def test_trace_is_scatterpolar(self):
        data = ChartDataAdapter.style_radar([make_style(0)])
        fig = self.renderer.render(data)
        assert isinstance(fig.data[0], go.Scatterpolar)
