"""Unit tests + hypothesis property tests for bookscope.ingest.chunker."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from bookscope.ingest.chunker import chunk
from bookscope.models import BookText


def make_book(text: str) -> BookText:
    return BookText(title="test", raw_text=text)


PARA_TEXT = (
    "The old man sat by the fire.\n\n"
    "He thought of the years that had passed him by.\n\n"
    "Outside, the wind was cold and the stars were bright.\n\n"
    "Nothing would ever be the same again."
)


class TestParagraphStrategy:
    def test_returns_chunks(self):
        chunks = chunk(make_book(PARA_TEXT), strategy="paragraph", min_words=5)
        assert len(chunks) >= 1

    def test_indices_are_sequential(self):
        chunks = chunk(make_book(PARA_TEXT), strategy="paragraph", min_words=5)
        for i, c in enumerate(chunks):
            assert c.index == i

    def test_min_words_filters_short_paragraphs(self):
        text = "Hi.\n\nThis is a much longer paragraph with plenty of words in it."
        chunks = chunk(make_book(text), strategy="paragraph", min_words=10)
        for c in chunks:
            assert c.word_count >= 10

    def test_empty_text_returns_empty(self):
        assert chunk(make_book(""), strategy="paragraph") == []


class TestFixedStrategy:
    def test_returns_chunks(self):
        words = " ".join([f"word{i}" for i in range(200)])
        chunks = chunk(make_book(words), strategy="fixed", word_limit=50)
        assert len(chunks) >= 1

    def test_chunk_size_respected(self):
        words = " ".join([f"w{i}" for i in range(500)])
        chunks = chunk(make_book(words), strategy="fixed", word_limit=100)
        # All but the last chunk should be at most word_limit words
        for c in chunks[:-1]:
            assert c.word_count <= 100

    def test_indices_sequential(self):
        words = " ".join([f"w{i}" for i in range(200)])
        chunks = chunk(make_book(words), strategy="fixed", word_limit=50)
        for i, c in enumerate(chunks):
            assert c.index == i

    def test_empty_text_returns_empty(self):
        assert chunk(make_book(""), strategy="fixed") == []

    def test_overlap_produces_more_chunks_than_no_overlap(self):
        words = " ".join([f"w{i}" for i in range(200)])
        # Fixed strategy always uses 50% overlap
        chunks = chunk(make_book(words), strategy="fixed", word_limit=50)
        # With 50% overlap and 200 words: ~(200/(50//2)) windows minus edge
        assert len(chunks) > 200 // 50


class TestInvalidStrategy:
    def test_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown chunking strategy"):
            chunk(make_book("Some text here with enough words"), strategy="bogus")


class TestChunkProperties:
    @given(st.text(min_size=0, max_size=2000))
    @settings(max_examples=200)
    def test_paragraph_never_crashes(self, text: str):
        result = chunk(make_book(text), strategy="paragraph", min_words=5)
        assert isinstance(result, list)

    @given(st.text(min_size=0, max_size=2000))
    @settings(max_examples=200)
    def test_fixed_never_crashes(self, text: str):
        result = chunk(make_book(text), strategy="fixed", word_limit=50)
        assert isinstance(result, list)

    @given(st.text(min_size=100, max_size=2000))
    @settings(max_examples=200)
    def test_indices_always_sequential(self, text: str):
        for strategy in ("paragraph", "fixed"):
            chunks = chunk(make_book(text), strategy=strategy, min_words=5, word_limit=50)
            for i, c in enumerate(chunks):
                assert c.index == i
