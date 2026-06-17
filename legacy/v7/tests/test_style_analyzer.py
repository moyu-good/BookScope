"""Unit tests for bookscope.nlp.StyleAnalyzer."""

import pytest

from bookscope.models import ChunkResult, StyleScore
from bookscope.nlp.style_analyzer import StyleAnalyzer

_STYLE_FIELDS = ("avg_sentence_length", "ttr", "noun_ratio", "verb_ratio", "adj_ratio", "adv_ratio")


def make_chunk(text: str, index: int = 0) -> ChunkResult:
    return ChunkResult(index=index, text=text)


PROSE = (
    "The old man walked slowly down the street. "
    "He carried a heavy bag of groceries in his tired arms. "
    "Children played loudly nearby, shouting and laughing without care."
)


class TestAnalyzeChunk:
    def setup_method(self):
        self.analyzer = StyleAnalyzer()

    def test_returns_style_score(self):
        result = self.analyzer.analyze_chunk(make_chunk(PROSE))
        assert isinstance(result, StyleScore)

    def test_empty_text_returns_zeros(self):
        result = self.analyzer.analyze_chunk(make_chunk(""))
        for field in _STYLE_FIELDS:
            assert getattr(result, field) == pytest.approx(0.0)

    def test_whitespace_returns_zeros(self):
        result = self.analyzer.analyze_chunk(make_chunk("   \n  "))
        for field in _STYLE_FIELDS:
            assert getattr(result, field) == pytest.approx(0.0)

    def test_chunk_index_preserved(self):
        result = self.analyzer.analyze_chunk(make_chunk(PROSE, index=7))
        assert result.chunk_index == 7

    def test_ttr_in_range(self):
        result = self.analyzer.analyze_chunk(make_chunk(PROSE))
        assert 0.0 < result.ttr <= 1.0

    def test_ttr_higher_for_diverse_text(self):
        repetitive = "cat cat cat cat cat."
        diverse = "The quick brown fox jumped over the lazy sleeping dog."
        r_rep = self.analyzer.analyze_chunk(make_chunk(repetitive))
        r_div = self.analyzer.analyze_chunk(make_chunk(diverse))
        assert r_div.ttr > r_rep.ttr

    def test_avg_sentence_length_positive(self):
        result = self.analyzer.analyze_chunk(make_chunk(PROSE))
        assert result.avg_sentence_length > 0

    def test_pos_ratios_sum_at_most_one(self):
        result = self.analyzer.analyze_chunk(make_chunk(PROSE))
        total = result.noun_ratio + result.verb_ratio + result.adj_ratio + result.adv_ratio
        assert total <= 1.01  # tiny float tolerance

    def test_all_ratios_non_negative(self):
        result = self.analyzer.analyze_chunk(make_chunk(PROSE))
        for field in ("noun_ratio", "verb_ratio", "adj_ratio", "adv_ratio"):
            assert getattr(result, field) >= 0.0

    def test_noun_ratio_non_zero_for_prose(self):
        result = self.analyzer.analyze_chunk(make_chunk(PROSE))
        assert result.noun_ratio > 0.0

    def test_no_alpha_tokens_returns_avg_sentence_length_only(self):
        """Chunk with only digits/punctuation — no POS tagging, but sentence length set."""
        result = self.analyzer.analyze_chunk(make_chunk("123. 456. 789."))
        assert result.avg_sentence_length > 0.0
        assert result.ttr == pytest.approx(0.0)
        assert result.noun_ratio == pytest.approx(0.0)


class TestAnalyzeBook:
    def setup_method(self):
        self.analyzer = StyleAnalyzer()

    def test_returns_one_score_per_chunk(self):
        chunks = [make_chunk(PROSE, i) for i in range(3)]
        scores = self.analyzer.analyze_book(chunks)
        assert len(scores) == 3

    def test_empty_list(self):
        assert self.analyzer.analyze_book([]) == []

    def test_indices_match(self):
        chunks = [make_chunk(PROSE, i) for i in range(4)]
        scores = self.analyzer.analyze_book(chunks)
        for chunk, score in zip(chunks, scores):
            assert score.chunk_index == chunk.index
