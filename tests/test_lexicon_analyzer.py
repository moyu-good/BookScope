"""Unit tests for bookscope.nlp.LexiconAnalyzer."""

import pytest

from bookscope.models import ChunkResult, EmotionScore
from bookscope.nlp import LexiconAnalyzer

_EMOTION_FIELDS = ("anger", "anticipation", "disgust", "fear",
                   "joy", "sadness", "surprise", "trust")


def make_chunk(text: str, index: int = 0) -> ChunkResult:
    return ChunkResult(index=index, text=text)


class TestAnalyzeChunk:
    def setup_method(self):
        self.analyzer = LexiconAnalyzer()

    def test_returns_emotion_score(self):
        result = self.analyzer.analyze_chunk(make_chunk("The happy child laughed with joy."))
        assert isinstance(result, EmotionScore)

    def test_empty_text_returns_zeros(self):
        result = self.analyzer.analyze_chunk(make_chunk(""))
        for field in _EMOTION_FIELDS:
            assert getattr(result, field) == 0.0

    def test_whitespace_only_returns_zeros(self):
        result = self.analyzer.analyze_chunk(make_chunk("   \n\t  "))
        for field in _EMOTION_FIELDS:
            assert getattr(result, field) == 0.0

    def test_scores_sum_to_one_or_zero(self):
        result = self.analyzer.analyze_chunk(
            make_chunk("The murderer felt rage and fear and disgust.")
        )
        total = sum(getattr(result, f) for f in _EMOTION_FIELDS)
        assert total == pytest.approx(1.0, abs=1e-6) or total == pytest.approx(0.0, abs=1e-6)

    def test_chunk_index_preserved(self):
        result = self.analyzer.analyze_chunk(make_chunk("hello", index=42))
        assert result.chunk_index == 42

    def test_scores_in_range(self):
        result = self.analyzer.analyze_chunk(make_chunk("I love and hate and fear everything."))
        for field in _EMOTION_FIELDS:
            v = getattr(result, field)
            assert 0.0 <= v <= 1.0, f"{field}={v} out of [0,1]"

    def test_unknown_words_return_zeros(self):
        # Nonsense words unlikely to be in the NRC lexicon
        result = self.analyzer.analyze_chunk(make_chunk("xkzqpt wvbfrn mjltzx"))
        total = sum(getattr(result, f) for f in _EMOTION_FIELDS)
        assert total == pytest.approx(0.0, abs=1e-6)


class TestAnalyzeBook:
    def setup_method(self):
        self.analyzer = LexiconAnalyzer()

    def test_returns_one_score_per_chunk(self):
        chunks = [make_chunk("I am happy.", i) for i in range(5)]
        scores = self.analyzer.analyze_book(chunks)
        assert len(scores) == 5

    def test_empty_list(self):
        assert self.analyzer.analyze_book([]) == []

    def test_indices_match(self):
        chunks = [make_chunk("text", i) for i in range(3)]
        scores = self.analyzer.analyze_book(chunks)
        for chunk, score in zip(chunks, scores):
            assert score.chunk_index == chunk.index
