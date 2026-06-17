"""Tests for bookscope.eval.answer_metrics — LLM-as-judge with mocked call_llm."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from bookscope.eval.answer_metrics import (
    _clean_llm_response,
    answer_relevancy,
    faithfulness,
)

# ---------------------------------------------------------------------------
# Helper: _clean_llm_response
# ---------------------------------------------------------------------------

class TestCleanLlmResponse:

    def test_strips_markdown_fences(self):
        assert _clean_llm_response('```json\n["a"]\n```') == '["a"]'

    def test_strips_truncation_suffix(self):
        assert _clean_llm_response("0.85 \u2026") == "0.85"

    def test_noop_for_clean_text(self):
        assert _clean_llm_response('["a", "b"]') == '["a", "b"]'

    def test_handles_empty_string(self):
        assert _clean_llm_response("") == ""


# ---------------------------------------------------------------------------
# Faithfulness
# ---------------------------------------------------------------------------

class TestFaithfulness:

    @patch("bookscope.eval.answer_metrics.call_llm")
    def test_fully_faithful(self, mock_llm):
        mock_llm.side_effect = [
            '["Zhu founded Ming.", "He was a peasant."]',
            '["SUPPORTED", "SUPPORTED"]',
        ]
        score = faithfulness(
            answer="Zhu founded Ming. He was a peasant.",
            contexts=["Zhu Yuanzhang founded the Ming Dynasty. He was born a peasant."],
        )
        assert score == pytest.approx(1.0)
        assert mock_llm.call_count == 2

    @patch("bookscope.eval.answer_metrics.call_llm")
    def test_partially_faithful(self, mock_llm):
        mock_llm.side_effect = [
            '["Claim A.", "Claim B."]',
            '["SUPPORTED", "NOT_SUPPORTED"]',
        ]
        score = faithfulness(answer="test", contexts=["ctx"])
        assert score == pytest.approx(0.5)

    @patch("bookscope.eval.answer_metrics.call_llm")
    def test_zero_faithful(self, mock_llm):
        mock_llm.side_effect = [
            '["Claim A."]',
            '["NOT_SUPPORTED"]',
        ]
        score = faithfulness(answer="test", contexts=["ctx"])
        assert score == pytest.approx(0.0)

    @patch("bookscope.eval.answer_metrics.call_llm")
    def test_empty_answer(self, mock_llm):
        score = faithfulness(answer="", contexts=["context"])
        assert score == 0.0
        mock_llm.assert_not_called()

    @patch("bookscope.eval.answer_metrics.call_llm")
    def test_json_parse_failure_returns_zero(self, mock_llm):
        mock_llm.return_value = "this is not json"
        score = faithfulness(answer="something", contexts=["context"])
        assert score == 0.0

    @patch("bookscope.eval.answer_metrics.call_llm")
    def test_handles_fenced_json(self, mock_llm):
        mock_llm.side_effect = [
            '```json\n["Claim A."]\n```',
            '```json\n["SUPPORTED"]\n```',
        ]
        score = faithfulness(answer="test", contexts=["ctx"])
        assert score == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Answer Relevancy
# ---------------------------------------------------------------------------

class TestAnswerRelevancy:

    @patch("bookscope.eval.answer_metrics.call_llm")
    def test_high_relevancy(self, mock_llm):
        mock_llm.return_value = "0.95"
        score = answer_relevancy(question="Who founded Ming?", answer="Zhu Yuanzhang.")
        assert score == pytest.approx(0.95)

    @patch("bookscope.eval.answer_metrics.call_llm")
    def test_low_relevancy(self, mock_llm):
        mock_llm.return_value = "0.1"
        score = answer_relevancy(question="Who founded Ming?", answer="I like apples.")
        assert score == pytest.approx(0.1)

    @patch("bookscope.eval.answer_metrics.call_llm")
    def test_empty_answer(self, mock_llm):
        score = answer_relevancy(question="Q?", answer="")
        assert score == 0.0
        mock_llm.assert_not_called()

    @patch("bookscope.eval.answer_metrics.call_llm")
    def test_parse_failure_returns_zero(self, mock_llm):
        mock_llm.return_value = "not a number"
        score = answer_relevancy(question="Q?", answer="A.")
        assert score == 0.0

    @patch("bookscope.eval.answer_metrics.call_llm")
    def test_clamped_above_one(self, mock_llm):
        mock_llm.return_value = "1.5"
        score = answer_relevancy(question="Q?", answer="A.")
        assert score == 1.0

    @patch("bookscope.eval.answer_metrics.call_llm")
    def test_truncation_suffix_stripped(self, mock_llm):
        mock_llm.return_value = "0.85 \u2026"
        score = answer_relevancy(question="Q?", answer="A.")
        assert score == pytest.approx(0.85)
