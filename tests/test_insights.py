"""Unit tests for bookscope.insights."""

import pytest

from bookscope.insights import (
    compute_readability,
    compute_sparkline_points,
    extract_character_names,
    extract_key_themes,
    first_person_density,
)
from bookscope.models import ChunkResult


# ── Helpers ──────────────────────────────────────────────────────────────────

def _chunks(texts):
    return [ChunkResult(index=i, text=t) for i, t in enumerate(texts)]


class _FakeStyleScore:
    def __init__(self, chunk_index, ttr=0.5, avg_sentence_length=15.0,
                 noun_ratio=0.25, verb_ratio=0.20, adj_ratio=0.08, adv_ratio=0.05):
        self.chunk_index = chunk_index
        self.ttr = ttr
        self.avg_sentence_length = avg_sentence_length
        self.noun_ratio = noun_ratio
        self.verb_ratio = verb_ratio
        self.adj_ratio = adj_ratio
        self.adv_ratio = adv_ratio


# ── extract_character_names ───────────────────────────────────────────────────

class TestExtractCharacterNames:
    def test_basic_english(self):
        texts = [
            "Elizabeth met Darcy at the ball. Elizabeth was surprised.",
            "Darcy looked at Elizabeth. Elizabeth smiled at Darcy.",
            "Elizabeth and Darcy danced all night.",
        ] * 5
        names = extract_character_names(_chunks(texts), lang="en")
        assert "Elizabeth" in names
        assert "Darcy" in names

    def test_cjk_returns_empty(self):
        texts = ["这是一本中文小说。"] * 10
        assert extract_character_names(_chunks(texts), lang="zh") == []
        assert extract_character_names(_chunks(texts), lang="ja") == []

    def test_stopwords_excluded(self):
        # "Chapter" should not appear as a character name
        texts = ["Chapter One begins here. Chapter Two follows."] * 10
        names = extract_character_names(_chunks(texts), lang="en")
        assert "Chapter" not in names
        assert "One" not in names

    def test_empty_chunks_returns_empty(self):
        assert extract_character_names([], lang="en") == []

    def test_top_n_respected(self):
        texts = [
            f"Harry met Hermione. Ron joined Harry. Harry and Ron laughed."
        ] * 20
        names = extract_character_names(_chunks(texts), top_n=2, lang="en")
        assert len(names) <= 2


# ── extract_key_themes ────────────────────────────────────────────────────────

class TestExtractKeyThemes:
    def test_returns_list(self):
        texts = [
            "quantum physics studies subatomic particles and quantum mechanics.",
            "quantum theory explains quantum phenomena through mathematical models.",
            "particles interact through quantum fields and quantum forces.",
        ] * 5
        chunks = _chunks(texts)
        scores = [_FakeStyleScore(i) for i in range(len(chunks))]
        themes = extract_key_themes(chunks, scores)
        assert isinstance(themes, list)

    def test_stopwords_absent(self):
        texts = ["the and or but in on at to for of with by from is are"] * 20
        chunks = _chunks(texts)
        scores = [_FakeStyleScore(i) for i in range(len(chunks))]
        themes = extract_key_themes(chunks, scores)
        for word in themes:
            assert word not in ("the", "and", "but", "from")

    def test_empty_returns_empty(self):
        assert extract_key_themes([], []) == []

    def test_top_n_respected(self):
        texts = [f"democracy freedom justice equality liberty peace"] * 20
        chunks = _chunks(texts)
        scores = [_FakeStyleScore(i) for i in range(len(chunks))]
        themes = extract_key_themes(chunks, scores, top_n=3)
        assert len(themes) <= 3


# ── compute_readability ───────────────────────────────────────────────────────

class TestComputeReadability:
    def test_empty_returns_moderate(self):
        score, label, confidence = compute_readability([])
        assert score == 0.5
        assert confidence == 0.0

    def test_returns_three_tuple(self):
        scores = [_FakeStyleScore(i) for i in range(5)]
        result = compute_readability(scores)
        assert len(result) == 3

    def test_confidence_low_for_few_chunks(self):
        scores = [_FakeStyleScore(0)]
        _, _, confidence = compute_readability(scores)
        assert confidence < 0.5

    def test_confidence_high_for_many_chunks(self):
        scores = [_FakeStyleScore(i) for i in range(15)]
        _, _, confidence = compute_readability(scores)
        assert confidence == 1.0

    def test_score_range(self):
        scores = [_FakeStyleScore(i) for i in range(10)]
        score, _, _ = compute_readability(scores)
        assert 0.0 <= score <= 1.0

    def test_dense_text_scores_higher(self):
        easy = [_FakeStyleScore(i, ttr=0.30, avg_sentence_length=8.0, noun_ratio=0.15)
                for i in range(10)]
        hard = [_FakeStyleScore(i, ttr=0.80, avg_sentence_length=35.0, noun_ratio=0.45)
                for i in range(10)]
        score_easy, _, _ = compute_readability(easy)
        score_hard, _, _ = compute_readability(hard)
        assert score_hard > score_easy

    def test_label_accessible(self):
        easy = [_FakeStyleScore(i, ttr=0.30, avg_sentence_length=8.0, noun_ratio=0.15)
                for i in range(10)]
        _, label, _ = compute_readability(easy, ui_lang="en")
        assert label == "Accessible"

    def test_label_specialist(self):
        hard = [_FakeStyleScore(i, ttr=0.85, avg_sentence_length=40.0, noun_ratio=0.45)
                for i in range(10)]
        _, label, _ = compute_readability(hard, ui_lang="en")
        assert label == "Specialist"

    def test_zh_labels(self):
        scores = [_FakeStyleScore(i) for i in range(10)]
        _, label, _ = compute_readability(scores, ui_lang="zh")
        assert label in ("通俗易读", "一般难度", "较有难度", "专业级")


# ── compute_sparkline_points ──────────────────────────────────────────────────

class TestComputeSparklinePoints:
    def test_empty_returns_flat_line(self):
        result = compute_sparkline_points([])
        assert "0," in result
        # Should be a valid "x,y x,y" string
        parts = result.split()
        assert len(parts) == 2

    def test_flat_series_returns_midline(self):
        # All same values → zero range → flat midpoint
        result = compute_sparkline_points([0.5, 0.5, 0.5])
        parts = result.split()
        assert len(parts) == 2  # flat line: two points

    def test_normal_series(self):
        pts = compute_sparkline_points([0.0, 0.5, 1.0])
        pairs = pts.split()
        assert len(pairs) == 3
        for pair in pairs:
            x, y = pair.split(",")
            assert 0 <= float(x) <= 200
            assert 0 <= float(y) <= 40

    def test_single_value_no_crash(self):
        result = compute_sparkline_points([0.7])
        assert "," in result

    def test_custom_dimensions(self):
        pts = compute_sparkline_points([0.0, 1.0], width=100, height=20)
        pairs = pts.split()
        for pair in pairs:
            x, y = pair.split(",")
            assert float(x) <= 100
            assert float(y) <= 20


# ── first_person_density ──────────────────────────────────────────────────────

class TestFirstPersonDensity:
    def test_high_first_person_english(self):
        texts = ["I went to the market. I bought apples. I came home. My bag was heavy."] * 5
        density = first_person_density(_chunks(texts), lang="en")
        assert density > 0.05

    def test_zero_first_person(self):
        texts = ["The cat sat on the mat. The dog ran away. Birds flew overhead."] * 5
        density = first_person_density(_chunks(texts), lang="en")
        assert density == 0.0

    def test_chinese_first_person(self):
        texts = ["我去了市场。我买了苹果。我回了家。我的包很重。"] * 5
        density = first_person_density(_chunks(texts), lang="zh")
        assert density > 0.0

    def test_japanese_first_person(self):
        texts = ["私は市場に行きました。私はりんごを買いました。"] * 5
        density = first_person_density(_chunks(texts), lang="ja")
        assert density > 0.0

    def test_empty_chunks_returns_zero(self):
        assert first_person_density([], lang="en") == 0.0

    def test_returns_fraction(self):
        texts = ["I am here. You are there."] * 5
        density = first_person_density(_chunks(texts), lang="en")
        assert 0.0 <= density <= 1.0
