"""Unit tests for bookscope.models.schemas."""

import pytest

from bookscope.models import BookText, ChunkResult, EmotionScore


class TestBookText:
    def test_word_count_auto(self):
        bt = BookText(title="T", raw_text="hello world foo")
        assert bt.word_count == 3

    def test_word_count_explicit(self):
        bt = BookText(title="T", raw_text="a b c", word_count=99)
        assert bt.word_count == 99

    def test_default_encoding(self):
        assert BookText(title="T", raw_text="x").encoding == "utf-8"

    def test_empty_text_allowed(self):
        bt = BookText(title="T", raw_text="")
        assert bt.word_count == 0


class TestChunkResult:
    def test_word_count_auto(self):
        cr = ChunkResult(index=0, text="one two three")
        assert cr.word_count == 3

    def test_word_count_explicit(self):
        cr = ChunkResult(index=0, text="a b", word_count=7)
        assert cr.word_count == 7


class TestEmotionScore:
    def test_defaults_all_zero(self):
        s = EmotionScore(chunk_index=0)
        for field in ("anger", "anticipation", "disgust", "fear",
                      "joy", "sadness", "surprise", "trust"):
            assert getattr(s, field) == 0.0

    def test_dominant_emotion(self):
        s = EmotionScore(chunk_index=0, joy=0.8, fear=0.1)
        assert s.dominant_emotion == "joy"

    def test_dominant_emotion_all_zero(self):
        # When all scores are 0 the method must still return a string
        s = EmotionScore(chunk_index=0)
        assert isinstance(s.dominant_emotion, str)

    def test_to_dict_keys(self):
        s = EmotionScore(chunk_index=0, anger=0.5)
        d = s.to_dict()
        assert set(d.keys()) == {
            "anger", "anticipation", "disgust", "fear",
            "joy", "sadness", "surprise", "trust",
        }

    def test_to_dict_values(self):
        s = EmotionScore(chunk_index=3, joy=0.6, sadness=0.4)
        assert s.to_dict()["joy"] == pytest.approx(0.6)
        assert s.to_dict()["sadness"] == pytest.approx(0.4)


class TestStyleScore:
    def test_to_dict_keys(self):
        from bookscope.models.schemas import StyleScore

        s = StyleScore(chunk_index=0, ttr=0.5)
        d = s.to_dict()
        assert set(d.keys()) == {
            "avg_sentence_length", "ttr", "noun_ratio",
            "verb_ratio", "adj_ratio", "adv_ratio",
        }

    def test_to_dict_values(self):
        from bookscope.models.schemas import StyleScore

        s = StyleScore(chunk_index=1, ttr=0.75, noun_ratio=0.3)
        assert s.to_dict()["ttr"] == pytest.approx(0.75)
        assert s.to_dict()["noun_ratio"] == pytest.approx(0.3)
