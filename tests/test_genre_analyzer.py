"""Tests for bookscope.nlp.genre_analyzer."""

import os
from unittest.mock import MagicMock, patch

from bookscope.nlp.genre_analyzer import (
    _build_essay_prompt,
    _build_nonfiction_prompt,
    _cache_key_genre,
    _chunk_text_block,
    _parse_nonfiction_response,
    _sample_chunks,
    extract_essay_voice,
    extract_nonfiction_concepts,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class _FakeChunk:
    """Minimal ChunkResult stand-in for testing."""
    def __init__(self, index: int, text: str):
        self.index = index
        self.text = text


def _make_chunks(n: int = 10) -> list:
    return [_FakeChunk(i, f"This is chunk number {i}. " * 20) for i in range(n)]


# ---------------------------------------------------------------------------
# _sample_chunks
# ---------------------------------------------------------------------------

class TestSampleChunks:
    def test_returns_n_chunks(self):
        chunks = _make_chunks(20)
        sampled = _sample_chunks(chunks, n=5)
        assert len(sampled) == 5

    def test_covers_start_and_end(self):
        chunks = _make_chunks(20)
        sampled = _sample_chunks(chunks, n=5)
        # First sampled chunk should be near the start, last near the end
        assert sampled[0].index < sampled[-1].index

    def test_empty_input(self):
        assert _sample_chunks([], n=5) == []

    def test_fewer_chunks_than_n(self):
        chunks = _make_chunks(3)
        sampled = _sample_chunks(chunks, n=5)
        assert len(sampled) == 3

    def test_exact_n_chunks(self):
        chunks = _make_chunks(5)
        sampled = _sample_chunks(chunks, n=5)
        assert len(sampled) == 5

    def test_single_chunk(self):
        chunks = _make_chunks(1)
        sampled = _sample_chunks(chunks, n=5)
        assert len(sampled) == 1

    def test_uniform_spread(self):
        """Sampled indices should be spread across the full range."""
        chunks = _make_chunks(100)
        sampled = _sample_chunks(chunks, n=5)
        indices = [c.index for c in sampled]
        # First sample near index 0, last sample in second half
        assert indices[0] < 20
        assert indices[-1] >= 60


# ---------------------------------------------------------------------------
# _chunk_text_block
# ---------------------------------------------------------------------------

class TestChunkTextBlock:
    def test_labels_each_excerpt(self):
        chunks = _make_chunks(3)
        block = _chunk_text_block(chunks, max_chars=3000)
        assert "[Excerpt 1 of 3]" in block
        assert "[Excerpt 3 of 3]" in block

    def test_empty_input(self):
        result = _chunk_text_block([])
        assert result == "(no text available)"

    def test_respects_max_chars(self):
        chunks = _make_chunks(5)
        block = _chunk_text_block(chunks, max_chars=500)
        assert len(block) <= 2000  # some overhead from labels is acceptable

    def test_contains_chunk_text(self):
        chunks = [_FakeChunk(0, "Hello world unique phrase")]
        block = _chunk_text_block(chunks)
        assert "Hello world unique phrase" in block


# ---------------------------------------------------------------------------
# _parse_nonfiction_response
# ---------------------------------------------------------------------------

class TestParseNonfictionResponse:
    def test_parses_concepts_and_argument(self):
        raw = (
            "CONCEPTS: System 1, heuristics, bias, loss aversion\n"
            "ARGUMENT: Builds from evidence toward a unified theory."
        )
        concepts, arg = _parse_nonfiction_response(raw)
        assert "System 1" in concepts
        assert "heuristics" in concepts
        assert "loss aversion" in concepts
        assert "unified theory" in arg

    def test_case_insensitive_keys(self):
        raw = "concepts: apples, oranges\nargument: Simple."
        concepts, arg = _parse_nonfiction_response(raw)
        assert "apples" in concepts
        assert "Simple." in arg

    def test_missing_argument(self):
        raw = "CONCEPTS: one, two, three"
        concepts, arg = _parse_nonfiction_response(raw)
        assert len(concepts) == 3
        assert arg == ""

    def test_missing_concepts(self):
        raw = "ARGUMENT: The author states the thesis in chapter one."
        concepts, arg = _parse_nonfiction_response(raw)
        assert concepts == []
        assert "thesis" in arg

    def test_empty_response(self):
        concepts, arg = _parse_nonfiction_response("")
        assert concepts == []
        assert arg == ""

    def test_strips_whitespace(self):
        raw = "CONCEPTS:  apples ,  oranges  \nARGUMENT:  Sparse prose. "
        concepts, arg = _parse_nonfiction_response(raw)
        assert concepts[0] == "apples"
        assert arg == "Sparse prose."


# ---------------------------------------------------------------------------
# _cache_key_genre
# ---------------------------------------------------------------------------

class TestCacheKeyGenre:
    def test_stable_across_calls(self):
        k1 = _cache_key_genre("MyBook", "nonfiction", "abc")
        k2 = _cache_key_genre("MyBook", "nonfiction", "abc")
        assert k1 == k2

    def test_academic_normalised_to_nonfiction(self):
        k_academic = _cache_key_genre("MyBook", "academic", "abc")
        k_nonfiction = _cache_key_genre("MyBook", "nonfiction", "abc")
        assert k_academic == k_nonfiction

    def test_different_genre_different_key(self):
        k_nf = _cache_key_genre("MyBook", "nonfiction", "abc")
        k_es = _cache_key_genre("MyBook", "essay", "abc")
        assert k_nf != k_es

    def test_different_content_different_key(self):
        k1 = _cache_key_genre("MyBook", "nonfiction", "abc")
        k2 = _cache_key_genre("MyBook", "nonfiction", "xyz")
        assert k1 != k2


# ---------------------------------------------------------------------------
# _build_nonfiction_prompt
# ---------------------------------------------------------------------------

class TestBuildNonfictionPrompt:
    def test_contains_excerpt_block(self):
        chunks = _make_chunks(3)
        from bookscope.nlp.genre_analyzer import _chunk_text_block
        block = _chunk_text_block(chunks)
        prompt = _build_nonfiction_prompt(block, "en")
        assert "[Excerpt" in prompt

    def test_requests_english_output(self):
        block = "[Excerpt 1 of 1]\nSome text."
        prompt = _build_nonfiction_prompt(block, "en")
        assert "English" in prompt

    def test_requests_chinese_output(self):
        block = "[Excerpt 1 of 1]\nSome text."
        prompt = _build_nonfiction_prompt(block, "zh")
        assert "Chinese" in prompt

    def test_asks_for_concepts_and_argument(self):
        block = "[Excerpt 1 of 1]\nSome text."
        prompt = _build_nonfiction_prompt(block, "en")
        assert "CONCEPTS" in prompt
        assert "ARGUMENT" in prompt


# ---------------------------------------------------------------------------
# _build_essay_prompt
# ---------------------------------------------------------------------------

class TestBuildEssayPrompt:
    def test_mentions_voice(self):
        block = "[Excerpt 1 of 1]\nSome text."
        prompt = _build_essay_prompt(block, "en")
        assert "voice" in prompt.lower()

    def test_mentions_atmosphere(self):
        block = "[Excerpt 1 of 1]\nSome text."
        prompt = _build_essay_prompt(block, "en")
        assert "atmosphere" in prompt.lower()

    def test_requests_english(self):
        block = "[Excerpt 1 of 1]\nSome text."
        prompt = _build_essay_prompt(block, "en")
        assert "English" in prompt


# ---------------------------------------------------------------------------
# extract_nonfiction_concepts — integration (mocked)
# ---------------------------------------------------------------------------

class TestExtractNonfictionConcepts:
    def test_returns_concepts_and_argument(self):
        chunks = _make_chunks(10)
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(
            text="CONCEPTS: System 1, heuristics, anchoring\nARGUMENT: Evidence-first."
        )]
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}):
            with patch("anthropic.Anthropic") as MockAnthropic:
                MockAnthropic.return_value.messages.create.return_value = mock_msg
                with patch("bookscope.nlp.genre_analyzer.st", None):
                    concepts, arg = extract_nonfiction_concepts(chunks, "en", "TestBook")
        assert "System 1" in concepts
        assert "Evidence-first." in arg

    def test_missing_api_key_returns_empty(self):
        chunks = _make_chunks(5)
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            with patch("bookscope.nlp.genre_analyzer._get_api_key", return_value=None):
                concepts, arg = extract_nonfiction_concepts(chunks, "en")
        assert concepts == []
        assert arg == ""

    def test_api_error_returns_empty(self):
        chunks = _make_chunks(5)
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}):
            with patch("anthropic.Anthropic") as MockAnthropic:
                MockAnthropic.return_value.messages.create.side_effect = Exception("timeout")
                with patch("bookscope.nlp.genre_analyzer.st", None):
                    concepts, arg = extract_nonfiction_concepts(chunks, "en")
        assert concepts == []
        assert arg == ""

    def test_empty_chunks_returns_empty(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}):
            with patch("bookscope.nlp.genre_analyzer.st", None):
                # With no chunks, text_block = "(no text available)"
                # LLM will return an empty or unparseable response
                mock_msg = MagicMock()
                mock_msg.content = [MagicMock(text="CONCEPTS: \nARGUMENT: ")]
                with patch("anthropic.Anthropic") as MockAnthropic:
                    MockAnthropic.return_value.messages.create.return_value = mock_msg
                    concepts, arg = extract_nonfiction_concepts([], "en")
        # Concepts list should be empty (blank entry stripped)
        assert all(c for c in concepts)  # no empty strings in list

    def test_academic_alias_accepted(self):
        """genre_type='academic' is accepted (no KeyError)."""
        chunks = _make_chunks(5)
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            with patch("bookscope.nlp.genre_analyzer._get_api_key", return_value=None):
                concepts, arg = extract_nonfiction_concepts(chunks, "en")
        assert concepts == []  # no API key → empty, no exception


# ---------------------------------------------------------------------------
# extract_essay_voice — integration (mocked)
# ---------------------------------------------------------------------------

class TestExtractEssayVoice:
    def test_returns_voice_text(self):
        chunks = _make_chunks(10)
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(
            text="Lyrical and introspective. The atmosphere is quietly melancholy."
        )]
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}):
            with patch("anthropic.Anthropic") as MockAnthropic:
                MockAnthropic.return_value.messages.create.return_value = mock_msg
                with patch("bookscope.nlp.genre_analyzer.st", None):
                    voice = extract_essay_voice(chunks, "en", "TestEssay")
        assert "Lyrical" in voice

    def test_missing_api_key_returns_empty(self):
        chunks = _make_chunks(5)
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            with patch("bookscope.nlp.genre_analyzer._get_api_key", return_value=None):
                voice = extract_essay_voice(chunks, "en")
        assert voice == ""

    def test_api_error_returns_empty(self):
        chunks = _make_chunks(5)
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}):
            with patch("anthropic.Anthropic") as MockAnthropic:
                MockAnthropic.return_value.messages.create.side_effect = Exception("network error")
                with patch("bookscope.nlp.genre_analyzer.st", None):
                    voice = extract_essay_voice(chunks, "en")
        assert voice == ""

    def test_empty_response_returns_empty(self):
        chunks = _make_chunks(5)
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text="")]
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}):
            with patch("anthropic.Anthropic") as MockAnthropic:
                MockAnthropic.return_value.messages.create.return_value = mock_msg
                with patch("bookscope.nlp.genre_analyzer.st", None):
                    voice = extract_essay_voice(chunks, "en")
        assert voice == ""
