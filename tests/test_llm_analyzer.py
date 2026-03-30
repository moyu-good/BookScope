"""Tests for bookscope.nlp.llm_analyzer."""

import os
from unittest.mock import MagicMock, patch

from bookscope.nlp.llm_analyzer import (
    _build_prompt,
    _cache_key,
    generate_narrative_insight,
)
from bookscope.store import AnalysisResult

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_result(arc_pattern: str = "Icarus") -> AnalysisResult:
    """Minimal AnalysisResult for testing."""
    from bookscope.models import EmotionScore, StyleScore

    emotion_scores = [
        EmotionScore(chunk_index=0, fear=0.6, joy=0.1, sadness=0.2),
        EmotionScore(chunk_index=1, fear=0.5, joy=0.2, sadness=0.3),
    ]
    style_scores = [
        StyleScore(
            chunk_index=0,
            ttr=0.55,
            avg_sentence_length=14.0,
            noun_ratio=0.25,
            verb_ratio=0.18,
            adj_ratio=0.07,
            adv_ratio=0.04,
        ),
    ]
    return AnalysisResult.create(
        book_title="Test Book",
        chunk_strategy="paragraph",
        total_chunks=2,
        total_words=500,
        arc_pattern=arc_pattern,
        detected_lang="en",
        emotion_scores=emotion_scores,
        style_scores=style_scores,
    )


# ---------------------------------------------------------------------------
# Unit tests for helpers
# ---------------------------------------------------------------------------

class TestCacheKey:
    def test_stable_across_calls(self):
        result = _make_result()
        assert _cache_key(result) == _cache_key(result)

    def test_includes_title(self):
        result = _make_result()
        assert "Test_Book" in _cache_key(result) or "Test Book" in _cache_key(result)

    def test_different_for_different_emotion_data(self):
        """Two results with same title but different emotions → different cache keys."""
        from bookscope.models import EmotionScore

        r1 = _make_result()
        r2 = _make_result()
        # Mutate emotion score on r2 to get a different hash
        r2 = r2.model_copy(update={
            "emotion_scores": [EmotionScore(chunk_index=0, joy=0.9)]
        })
        assert _cache_key(r1) != _cache_key(r2)


class TestBuildPrompt:
    def test_contains_arc_label(self):
        result = _make_result("Cinderella")
        prompt = _build_prompt(result, "en")
        assert "Cinderella" in prompt

    def test_english_prompt_requests_english(self):
        result = _make_result()
        prompt = _build_prompt(result, "en")
        assert "English" in prompt

    def test_chinese_prompt_requests_chinese(self):
        result = _make_result()
        prompt = _build_prompt(result, "zh")
        assert "Chinese" in prompt

    def test_contains_top_emotions(self):
        result = _make_result()
        prompt = _build_prompt(result, "en")
        # fear should be top emotion given fixture data
        assert "fear" in prompt


# ---------------------------------------------------------------------------
# Integration: generate_narrative_insight
# ---------------------------------------------------------------------------

class TestGenerateNarrativeInsight:
    def test_successful_response(self):
        """Mock Anthropic returns a complete sentence → returned as-is."""
        result = _make_result()

        mock_message = MagicMock()
        mock_message.content = [MagicMock(text="This thriller grips from the first page.")]

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}):
            with patch("anthropic.Anthropic") as MockAnthropic:
                MockAnthropic.return_value.messages.create.return_value = mock_message
                with patch("bookscope.nlp.llm_analyzer.st", None):
                    text = generate_narrative_insight(result, "en")

        assert text == "This thriller grips from the first page."

    def test_truncated_response_gets_ellipsis(self):
        """Response not ending in sentence punctuation gets ' …' appended."""
        result = _make_result()

        mock_message = MagicMock()
        mock_message.content = [MagicMock(text="The fear builds steadily throughout")]

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}):
            with patch("anthropic.Anthropic") as MockAnthropic:
                MockAnthropic.return_value.messages.create.return_value = mock_message
                with patch("bookscope.nlp.llm_analyzer.st", None):
                    text = generate_narrative_insight(result, "en")

        assert text == "The fear builds steadily throughout …"

    def test_missing_api_key_returns_empty(self):
        """No API key → returns '' (caller hides the card)."""
        result = _make_result()

        with patch.dict(os.environ, {}, clear=True):
            # Ensure ANTHROPIC_API_KEY is not set
            os.environ.pop("ANTHROPIC_API_KEY", None)
            with patch("bookscope.nlp.llm_analyzer._get_api_key", return_value=None):
                text = generate_narrative_insight(result, "en")

        assert text == ""

    def test_api_error_returns_empty(self):
        """APIError → shows warning, returns ''."""
        result = _make_result()

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}):
            with patch("anthropic.Anthropic") as MockAnthropic:
                import anthropic as _anthropic
                MockAnthropic.return_value.messages.create.side_effect = (
                    _anthropic.APIError(
                        message="server error",
                        request=MagicMock(),
                        body=None,
                    )
                )
                with patch("bookscope.nlp.llm_analyzer.st", None):
                    text = generate_narrative_insight(result, "en")

        assert text == ""

    def test_empty_response_string(self):
        """Empty string from API → returns ''."""
        result = _make_result()

        mock_message = MagicMock()
        mock_message.content = [MagicMock(text="")]

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}):
            with patch("anthropic.Anthropic") as MockAnthropic:
                MockAnthropic.return_value.messages.create.return_value = mock_message
                with patch("bookscope.nlp.llm_analyzer.st", None):
                    text = generate_narrative_insight(result, "en")

        assert text == ""
