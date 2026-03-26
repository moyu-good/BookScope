"""Unit tests + hypothesis property tests for bookscope.ingest.cleaner."""

import unicodedata

from hypothesis import given, settings
from hypothesis import strategies as st

from bookscope.ingest.cleaner import clean


class TestCleanDeterministic:
    def test_empty_string(self):
        assert clean("") == ""

    def test_strips_leading_trailing_whitespace(self):
        assert clean("  hello  ") == "hello"

    def test_collapses_triple_newlines(self):
        result = clean("a\n\n\n\nb")
        assert "\n\n\n" not in result

    def test_preserves_paragraph_break(self):
        result = clean("para one\n\npara two")
        assert "\n\n" in result

    def test_collapses_multiple_spaces(self):
        result = clean("hello     world")
        assert "  " not in result
        assert "hello world" in result

    def test_removes_control_characters(self):
        result = clean("hel\x00lo\x01")
        assert "\x00" not in result
        assert "\x01" not in result

    def test_tabs_normalized_to_spaces(self):
        # Tabs are horizontal whitespace — clean() collapses them to spaces
        result = clean("a\tb")
        assert "\t" not in result
        assert "a b" in result

    def test_nfc_normalization(self):
        # Decomposed é (e + combining accent) → composed é
        decomposed = "e\u0301"
        result = clean(decomposed)
        assert unicodedata.is_normalized("NFC", result)


class TestCleanProperties:
    @given(st.text())
    @settings(max_examples=500)
    def test_never_crashes(self, text: str):
        """clean() must not raise for any input."""
        result = clean(text)
        assert isinstance(result, str)

    @given(st.text())
    @settings(max_examples=300)
    def test_idempotent(self, text: str):
        """Cleaning twice yields the same result as cleaning once."""
        once = clean(text)
        twice = clean(once)
        assert once == twice

    @given(st.text())
    @settings(max_examples=300)
    def test_no_triple_newlines_in_output(self, text: str):
        assert "\n\n\n" not in clean(text)

    @given(st.text())
    @settings(max_examples=300)
    def test_output_is_nfc(self, text: str):
        result = clean(text)
        assert unicodedata.is_normalized("NFC", result)
