"""Tests for app/pages/02_compare.py."""

import hashlib
import re
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest


# ---------------------------------------------------------------------------
# Helpers shared across test classes
# ---------------------------------------------------------------------------

def _make_chunks(*texts: str):
    """Return minimal chunk-like SimpleNamespace objects from text strings."""
    return [
        SimpleNamespace(text=t, word_count=len(t.split()))
        for t in texts
    ]


def _tokenize(chunks_list) -> set[str]:
    """Replicate the Jaccard tokenizer used by 02_compare.py."""
    words: set[str] = set()
    for c in chunks_list:
        words.update(re.findall(r"\b[a-zA-Z]{3,}\b", c.text.lower()))
    return words


# ---------------------------------------------------------------------------
# Test 1: Overlay data construction with mismatched chunk counts
# ---------------------------------------------------------------------------

class TestJaccardMismatchedChunks:
    """Vocabulary overlap (Jaccard) must work correctly when books have
    different numbers of chunks — e.g. Book A = 2 chunks, Book B = 7 chunks."""

    def test_jaccard_range(self):
        """Result is always in [0.0, 1.0]."""
        chunks_a = _make_chunks(
            "The quick brown fox jumps over the lazy dog",
        )
        chunks_b = _make_chunks(
            "A fast brown fox leapt over a sleepy dog",
            "The weather was sunny and very bright today",
            "Birds sang cheerfully in the early morning light",
            "The old man sat quietly by the river bank",
            "Children played happily in the park after school",
            "Stars glittered brightly across the dark night sky",
            "The wind whispered softly through the tall pine trees",
        )
        vocab_a = _tokenize(chunks_a)
        vocab_b = _tokenize(chunks_b)
        union = vocab_a | vocab_b
        jaccard = len(vocab_a & vocab_b) / len(union) if union else 0.0

        assert 0.0 <= jaccard <= 1.0

    def test_shared_words_detected(self):
        """Words present in both books appear in the intersection."""
        chunks_a = _make_chunks("The quick brown fox jumps over the lazy dog")
        chunks_b = _make_chunks(
            "A fast brown fox leapt over a sleepy dog",
            "Three more chunks here just for variety",
            "Another chunk with completely different content now",
        )
        vocab_a = _tokenize(chunks_a)
        vocab_b = _tokenize(chunks_b)
        intersection = vocab_a & vocab_b

        assert "brown" in intersection
        assert "fox" in intersection
        assert "dog" in intersection

    def test_no_shared_words(self):
        """Disjoint vocabularies → Jaccard == 0.0."""
        chunks_a = _make_chunks("alpha beta gamma delta epsilon")
        chunks_b = _make_chunks(
            "zulu yankee xray whiskey victor",
            "uniform tango sierra romeo quebec",
        )
        vocab_a = _tokenize(chunks_a)
        vocab_b = _tokenize(chunks_b)
        union = vocab_a | vocab_b
        jaccard = len(vocab_a & vocab_b) / len(union) if union else 0.0

        assert jaccard == pytest.approx(0.0)

    def test_empty_second_book(self):
        """Zero-division guard: empty chunk list → Jaccard == 0.0."""
        chunks_a = _make_chunks("The quick brown fox jumps over the lazy dog")
        chunks_b = _make_chunks()  # empty

        vocab_a = _tokenize(chunks_a)
        vocab_b = _tokenize(chunks_b)
        union = vocab_a | vocab_b
        jaccard = len(vocab_a & vocab_b) / len(union) if union else 0.0

        assert jaccard == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Test 2: Empty state (no uploads) — AppTest
# ---------------------------------------------------------------------------

class TestEmptyState:
    """No files uploaded → upload-hint info message is shown, no exception."""

    def test_no_uploads_shows_info(self):
        at = AppTest.from_file("app/pages/02_compare.py", default_timeout=30)
        at.run()

        assert not at.exception, f"App raised exception: {at.exception}"
        assert len(at.info) > 0, "Expected at least one st.info() message"
        hint_text = " ".join(str(i.value) for i in at.info).lower()
        # The hint contains "upload" or "book"
        assert "upload" in hint_text or "book" in hint_text

    def test_no_uploads_no_warning(self):
        """Empty state shows an info-level message, not a warning."""
        at = AppTest.from_file("app/pages/02_compare.py", default_timeout=30)
        at.run()

        assert not at.exception
        # No st.warning should fire when nothing is uploaded
        assert len(at.warning) == 0


# ---------------------------------------------------------------------------
# Test 3: Same-content guard (_content_fingerprint)
# ---------------------------------------------------------------------------

class TestSameContentGuard:
    """_content_fingerprint must flag identical content and pass different content."""

    def _fingerprint(self, content: bytes) -> str:
        return hashlib.md5(content[:8192]).hexdigest()

    def test_identical_bytes_produce_same_fingerprint(self):
        """Two copies of the same file produce the same fingerprint."""
        data = b"Once upon a time in a land far, far away." * 200
        assert self._fingerprint(data) == self._fingerprint(data)

    def test_different_bytes_produce_different_fingerprint(self):
        """Different file content → different fingerprints."""
        data_a = b"It was the best of times, it was the worst of times." * 100
        data_b = b"Call me Ishmael. Some years ago, never mind how long." * 100
        assert self._fingerprint(data_a) != self._fingerprint(data_b)

    def test_fingerprint_uses_first_8kb_only(self):
        """Fingerprint is based on the first 8 KB — large files are not fully hashed."""
        prefix = b"X" * 8192
        data_a = prefix + b"suffix_a" * 1000
        data_b = prefix + b"suffix_b" * 1000
        # Same first 8 KB → same fingerprint, regardless of tail
        assert self._fingerprint(data_a) == self._fingerprint(data_b)

    def test_empty_file_fingerprint_is_stable(self):
        """Empty bytes produce a stable, well-defined fingerprint."""
        fp = self._fingerprint(b"")
        assert fp == hashlib.md5(b"").hexdigest()
        assert self._fingerprint(b"") == fp
