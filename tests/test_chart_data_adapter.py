"""Unit tests for bookscope.viz.ChartDataAdapter."""

import pytest

from bookscope.models import EmotionScore
from bookscope.viz.chart_data_adapter import ChartDataAdapter, EmotionTimelineData

_EMOTION_FIELDS = ("anger", "anticipation", "disgust", "fear",
                   "joy", "sadness", "surprise", "trust")


def make_score(chunk_index: int, **kwargs) -> EmotionScore:
    return EmotionScore(chunk_index=chunk_index, **kwargs)


class TestEmotionTimeline:
    def test_empty_input(self):
        data = ChartDataAdapter.emotion_timeline([])
        assert data.x == []
        assert set(data.emotions.keys()) == set(_EMOTION_FIELDS)
        for v in data.emotions.values():
            assert v == []

    def test_single_score(self):
        score = make_score(0, joy=0.5)
        data = ChartDataAdapter.emotion_timeline([score])
        assert data.x == [0]
        assert data.emotions["joy"] == [pytest.approx(0.5)]

    def test_x_axis_is_chunk_indices(self):
        scores = [make_score(i) for i in range(5)]
        data = ChartDataAdapter.emotion_timeline(scores)
        assert data.x == [0, 1, 2, 3, 4]

    def test_sorts_by_chunk_index(self):
        scores = [make_score(2, joy=0.2), make_score(0, joy=0.0), make_score(1, joy=0.1)]
        data = ChartDataAdapter.emotion_timeline(scores)
        assert data.x == [0, 1, 2]
        assert data.emotions["joy"] == [pytest.approx(0.0), pytest.approx(0.1), pytest.approx(0.2)]

    def test_all_eight_emotions_present(self):
        data = ChartDataAdapter.emotion_timeline([make_score(0)])
        assert set(data.emotions.keys()) == set(_EMOTION_FIELDS)

    def test_series_length_matches_x(self):
        scores = [make_score(i) for i in range(10)]
        data = ChartDataAdapter.emotion_timeline(scores)
        for series in data.emotions.values():
            assert len(series) == len(data.x) == 10

    def test_returns_emotion_timeline_data(self):
        data = ChartDataAdapter.emotion_timeline([make_score(0)])
        assert isinstance(data, EmotionTimelineData)
