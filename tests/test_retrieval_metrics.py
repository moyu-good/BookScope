"""Tests for bookscope.eval.retrieval_metrics — pure math, no LLM or GPU."""

from __future__ import annotations

import numpy as np
import pytest

from bookscope.eval.retrieval_metrics import (
    hit_rate_at_k,
    mrr_at_k,
    ndcg_at_k,
    recall_at_k,
)

# ---------------------------------------------------------------------------
# Recall@K
# ---------------------------------------------------------------------------

class TestRecallAtK:

    def test_perfect_recall(self):
        assert recall_at_k([0, 1, 2], {0, 1, 2}, k=3) == 1.0

    def test_partial_recall(self):
        assert recall_at_k([0, 3, 4], {0, 1, 2}, k=3) == pytest.approx(1 / 3)

    def test_zero_recall(self):
        assert recall_at_k([3, 4, 5], {0, 1, 2}, k=3) == 0.0

    def test_empty_relevant_set(self):
        assert recall_at_k([0, 1], set(), k=2) == 0.0

    def test_k_smaller_than_retrieved(self):
        assert recall_at_k([0, 1, 2, 3], {3}, k=2) == 0.0

    def test_k_larger_than_retrieved(self):
        assert recall_at_k([0], {0, 1}, k=10) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# MRR@K
# ---------------------------------------------------------------------------

class TestMRRAtK:

    def test_first_position(self):
        assert mrr_at_k([0, 1, 2], {0}, k=3) == 1.0

    def test_second_position(self):
        assert mrr_at_k([1, 0, 2], {0}, k=3) == pytest.approx(0.5)

    def test_third_position(self):
        assert mrr_at_k([1, 2, 0], {0}, k=3) == pytest.approx(1 / 3)

    def test_no_relevant_doc(self):
        assert mrr_at_k([1, 2, 3], {0}, k=3) == 0.0

    def test_multiple_relevant_uses_first(self):
        assert mrr_at_k([3, 0, 1], {0, 1}, k=3) == pytest.approx(0.5)

    def test_empty_relevant_set(self):
        assert mrr_at_k([0, 1], set(), k=2) == 0.0


# ---------------------------------------------------------------------------
# NDCG@K
# ---------------------------------------------------------------------------

class TestNDCGAtK:

    def test_perfect_ranking(self):
        assert ndcg_at_k([0, 1, 2], {0, 1, 2}, k=3) == pytest.approx(1.0)

    def test_inverse_ranking(self):
        score = ndcg_at_k([3, 4, 0], {0, 1}, k=3)
        assert 0.0 < score < 1.0

    def test_no_relevant_docs(self):
        assert ndcg_at_k([3, 4, 5], {0, 1}, k=3) == 0.0

    def test_empty_relevant_set(self):
        assert ndcg_at_k([0, 1, 2], set(), k=3) == 0.0

    def test_single_relevant_at_top(self):
        assert ndcg_at_k([0, 1, 2], {0}, k=3) == pytest.approx(1.0)

    def test_single_relevant_at_bottom(self):
        expected = (1.0 / np.log2(4)) / (1.0 / np.log2(2))
        assert ndcg_at_k([1, 2, 0], {0}, k=3) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Hit Rate@K
# ---------------------------------------------------------------------------

class TestHitRateAtK:

    def test_hit(self):
        assert hit_rate_at_k([0, 1, 2], {0}, k=3) == 1.0

    def test_miss(self):
        assert hit_rate_at_k([1, 2, 3], {0}, k=3) == 0.0

    def test_hit_at_boundary(self):
        assert hit_rate_at_k([1, 2, 0], {0}, k=3) == 1.0

    def test_miss_beyond_k(self):
        assert hit_rate_at_k([1, 2, 0, 3], {0}, k=2) == 0.0

    def test_empty_relevant_set(self):
        assert hit_rate_at_k([0, 1], set(), k=2) == 0.0

    def test_empty_retrieved(self):
        assert hit_rate_at_k([], {0}, k=5) == 0.0
