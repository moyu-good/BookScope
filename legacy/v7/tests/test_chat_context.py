"""Unit tests for Chat Tab helper functions (_build_context, _context_cache_key).

These functions live in app/tabs/chat.py. Streamlit is available in the test
environment (used by test_compare_page.py via AppTest), so direct imports work.
"""

from types import SimpleNamespace

from app.tabs.chat import _build_context, _context_cache_key

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _chunks(*texts: str):
    """Return minimal chunk-like objects matching the duck-type expected by chat.py."""
    return [SimpleNamespace(text=t) for t in texts]


# ---------------------------------------------------------------------------
# _build_context
# ---------------------------------------------------------------------------

class TestBuildContext:
    def test_empty_returns_empty_string(self):
        assert _build_context([]) == ""

    def test_returns_string(self):
        ctx = _build_context(_chunks("Hello world."))
        assert isinstance(ctx, str)

    def test_single_chunk_included(self):
        ctx = _build_context(_chunks("The lighthouse stood tall."))
        assert "lighthouse" in ctx

    def test_excerpt_headers_included(self):
        """Context includes [Excerpt N of M] labels."""
        ctx = _build_context(_chunks(*["Text."] * 3))
        assert "Excerpt" in ctx

    def test_at_most_eight_excerpts(self):
        """Even with 20 chunks, at most 8 excerpts are sampled."""
        chunks = _chunks(*[f"Chunk {i}." for i in range(20)])
        ctx = _build_context(chunks)
        # Count "Excerpt" occurrences
        count = ctx.count("[Excerpt")
        assert count <= 8

    def test_exactly_eight_when_more_than_eight(self):
        chunks = _chunks(*[f"Chunk {i}." for i in range(16)])
        ctx = _build_context(chunks)
        count = ctx.count("[Excerpt")
        assert count == 8

    def test_fewer_than_eight_chunks_all_included(self):
        chunks = _chunks(*[f"Chunk {i}." for i in range(5)])
        ctx = _build_context(chunks)
        count = ctx.count("[Excerpt")
        assert count == 5

    def test_chunk_text_truncated_to_budget(self):
        """Each chunk's text is capped — very long chunks should not dominate."""
        long_text = "word " * 2000  # ~10,000 chars
        ctx = _build_context(_chunks(long_text))
        # The context should be well under 10,000 characters
        assert len(ctx) < 5000

    def test_total_context_within_budget(self):
        """Total context stays within ~CONTEXT_CHARS limit."""
        from app.tabs.chat import _CONTEXT_CHARS
        chunks = _chunks(*["The quick brown fox jumps over the lazy dog. " * 50] * 10)
        ctx = _build_context(chunks)
        # Allow some header overhead but must stay reasonable
        assert len(ctx) < _CONTEXT_CHARS * 2

    def test_uniformly_sampled_includes_first(self):
        """First chunk (index 0) should always appear in context."""
        chunks = _chunks(*[f"Distinct_{i}" for i in range(10)])
        ctx = _build_context(chunks)
        assert "Distinct_0" in ctx

    def test_newline_separation_between_excerpts(self):
        """Excerpts separated by double newlines."""
        chunks = _chunks("First chunk.", "Second chunk.", "Third chunk.")
        ctx = _build_context(chunks)
        assert "\n\n" in ctx


# ---------------------------------------------------------------------------
# _context_cache_key
# ---------------------------------------------------------------------------

class TestContextCacheKey:
    def test_same_chunks_same_key(self):
        chunks = _chunks("Hello world.", "Second sentence.")
        assert _context_cache_key(chunks) == _context_cache_key(chunks)

    def test_returns_string_starting_with_prefix(self):
        chunks = _chunks("Hello.")
        key = _context_cache_key(chunks)
        assert key.startswith("chat_ctx_")

    def test_different_texts_different_key(self):
        a = _chunks("Book about dragons.")
        b = _chunks("Book about wizards.")
        assert _context_cache_key(a) != _context_cache_key(b)

    def test_empty_chunks_returns_key(self):
        key = _context_cache_key([])
        assert isinstance(key, str)
        assert key.startswith("chat_ctx_")

    def test_key_is_short(self):
        """Cache key should be reasonably short (prefix + 8 hex chars)."""
        key = _context_cache_key(_chunks("Hello."))
        assert len(key) < 30

    def test_order_matters(self):
        """Different ordering of same texts may produce different key (based on first 40 chars)."""
        a = _chunks("AAAA", "BBBB")
        b = _chunks("BBBB", "AAAA")
        # These may differ depending on first-char sampling; at minimum no crash
        assert isinstance(_context_cache_key(a), str)
        assert isinstance(_context_cache_key(b), str)
