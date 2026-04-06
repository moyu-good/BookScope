"""Tests for cross-encoder reranking in bookscope.store.vector_store."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest  # noqa: F401 — used by pytest.approx

from bookscope.models.schemas import ChunkResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_chunks(texts: list[str]) -> list[ChunkResult]:
    return [ChunkResult(index=i, text=t) for i, t in enumerate(texts)]


def _mock_reranker(scores: list[float] | None = None):
    """Return a mock CrossEncoder whose predict() yields deterministic scores."""
    reranker = MagicMock()

    def _predict(pairs, **_kwargs):
        if scores is not None:
            return np.array(scores[: len(pairs)], dtype=np.float32)
        # Default: descending scores (first candidate highest)
        return np.arange(len(pairs), 0, -1, dtype=np.float32)

    reranker.predict.side_effect = _predict
    return reranker


def _mock_provider(dim: int = 1024):
    provider = MagicMock()
    provider.name = "Mock/test-model"
    provider.dim = dim

    def _encode(texts):
        rng = np.random.RandomState(42)
        return rng.randn(len(texts), dim).astype(np.float32)

    provider.encode_documents.side_effect = _encode
    provider.encode_queries.side_effect = _encode
    return provider


# ---------------------------------------------------------------------------
# Reranker singleton
# ---------------------------------------------------------------------------

class TestGetReranker:

    def test_singleton_caches_model(self):
        import bookscope.store.vector_store as mod

        old = mod._reranker
        try:
            sentinel = MagicMock(name="cached-reranker")
            mod._reranker = sentinel
            result = mod._get_reranker()
            assert result is sentinel
        finally:
            mod._reranker = old

    @patch("bookscope.store.vector_store.CrossEncoder", create=True)
    def test_singleton_loads_on_first_call(self, mock_cls):
        import bookscope.store.vector_store as mod

        old = mod._reranker
        try:
            mod._reranker = None
            # Patch the lazy import path
            with patch(
                "bookscope.store.vector_store.CrossEncoder", mock_cls, create=True,
            ):
                # Force re-import inside _get_reranker
                mock_ce = MagicMock()
                with patch.dict(
                    "sys.modules",
                    {"sentence_transformers": MagicMock(CrossEncoder=mock_ce)},
                ):
                    mod._reranker = None
                    mod._get_reranker()
                    mock_ce.assert_called_once_with(mod._RERANKER_NAME)
        finally:
            mod._reranker = old


# ---------------------------------------------------------------------------
# rerank() method
# ---------------------------------------------------------------------------

class TestRerank:

    @patch("bookscope.store.vector_store._get_reranker")
    @patch("bookscope.store.vector_store._get_provider")
    def test_rerank_basic_ordering(self, mock_model, mock_reranker):
        mock_model.return_value = _mock_provider()
        # Score chunk at index 2 highest
        mock_reranker.return_value = _mock_reranker([0.1, 0.3, 0.9])
        from bookscope.store.vector_store import SessionVectorStore

        chunks = _make_chunks(["alpha", "beta", "gamma"])
        vs = SessionVectorStore(chunks, enable_vector=False)

        candidates = [(chunks[0], 0.5), (chunks[1], 0.4), (chunks[2], 0.3)]
        results = vs.rerank("query", candidates, top_k=3)

        assert results[0][0].index == 2  # highest reranker score
        assert results[0][1] == pytest.approx(0.9, abs=0.01)

    @patch("bookscope.store.vector_store._get_reranker")
    def test_rerank_empty_candidates(self, mock_reranker):
        from bookscope.store.vector_store import SessionVectorStore

        vs = SessionVectorStore([], enable_vector=False)
        assert vs.rerank("q", [], top_k=5) == []
        mock_reranker.assert_not_called()

    @patch("bookscope.store.vector_store._get_reranker")
    @patch("bookscope.store.vector_store._get_provider")
    def test_rerank_top_k_respected(self, mock_model, mock_reranker):
        mock_model.return_value = _mock_provider()
        mock_reranker.return_value = _mock_reranker()
        from bookscope.store.vector_store import SessionVectorStore

        chunks = _make_chunks([f"text{i}" for i in range(10)])
        vs = SessionVectorStore(chunks, enable_vector=False)

        candidates = [(c, 0.5) for c in chunks]
        results = vs.rerank("query", candidates, top_k=3)
        assert len(results) == 3

    @patch("bookscope.store.vector_store._get_reranker")
    @patch("bookscope.store.vector_store._get_provider")
    def test_rerank_scores_are_cross_encoder_scores(self, mock_model, mock_reranker):
        mock_model.return_value = _mock_provider()
        mock_reranker.return_value = _mock_reranker([0.7, 0.2])
        from bookscope.store.vector_store import SessionVectorStore

        chunks = _make_chunks(["a", "b"])
        vs = SessionVectorStore(chunks, enable_vector=False)

        candidates = [(chunks[0], 99.0), (chunks[1], 88.0)]  # old scores
        results = vs.rerank("q", candidates)
        # Returned scores should be cross-encoder scores, not old ones
        assert results[0][1] == pytest.approx(0.7, abs=0.01)
        assert results[1][1] == pytest.approx(0.2, abs=0.01)

    @patch("bookscope.store.vector_store._get_reranker")
    @patch("bookscope.store.vector_store._get_provider")
    def test_rerank_preserves_chunk_identity(self, mock_model, mock_reranker):
        mock_model.return_value = _mock_provider()
        mock_reranker.return_value = _mock_reranker([0.5, 0.9])
        from bookscope.store.vector_store import SessionVectorStore

        chunks = _make_chunks(["first", "second"])
        vs = SessionVectorStore(chunks, enable_vector=False)

        candidates = [(chunks[0], 1.0), (chunks[1], 0.5)]
        results = vs.rerank("q", candidates)
        # chunk at index 1 should be first (score 0.9)
        assert results[0][0] is chunks[1]

    @patch("bookscope.store.vector_store._get_reranker")
    @patch("bookscope.store.vector_store._get_provider")
    def test_rerank_truncates_long_text(self, mock_model, mock_reranker):
        mock_model.return_value = _mock_provider()
        captured_pairs = []
        reranker = MagicMock()

        def _predict(pairs, **_kw):
            captured_pairs.extend(pairs)
            return np.array([0.5] * len(pairs), dtype=np.float32)

        reranker.predict.side_effect = _predict
        mock_reranker.return_value = reranker

        from bookscope.store.vector_store import _RERANKER_CHAR_LIMIT, SessionVectorStore

        long_text = "x" * 5000
        chunks = _make_chunks([long_text])
        vs = SessionVectorStore(chunks, enable_vector=False)

        vs.rerank("q", [(chunks[0], 1.0)])
        assert len(captured_pairs[0][1]) == _RERANKER_CHAR_LIMIT


# ---------------------------------------------------------------------------
# search() with reranking
# ---------------------------------------------------------------------------

class TestSearchWithReranking:

    @patch("bookscope.store.vector_store._get_reranker")
    def test_search_bm25_only_with_rerank(self, mock_reranker):
        mock_reranker.return_value = _mock_reranker()
        from bookscope.store.vector_store import SessionVectorStore

        chunks = _make_chunks([
            "朱元璋建立明朝",
            "徐达北伐中原成功",
            "刘伯温运筹帷幄助朱元璋",
        ])
        vs = SessionVectorStore(chunks, enable_vector=False)
        results = vs.search("朱元璋", top_k=2, enable_rerank=True)
        assert len(results) <= 2
        mock_reranker.return_value.predict.assert_called()

    @patch("bookscope.store.vector_store._get_reranker")
    def test_search_rerank_disabled(self, mock_reranker):
        from bookscope.store.vector_store import SessionVectorStore

        chunks = _make_chunks([
            "朱元璋建立明朝",
            "李白是唐朝诗人",
            "杜甫是诗圣称号",
        ])
        vs = SessionVectorStore(chunks, enable_vector=False)
        results = vs.search("朱元璋", top_k=2, enable_rerank=False)
        assert len(results) <= 2
        mock_reranker.return_value.predict.assert_not_called()

    @patch("bookscope.store.vector_store._get_reranker")
    def test_search_rerank_fallback_on_error(self, mock_reranker):
        mock_reranker.side_effect = RuntimeError("model download failed")
        from bookscope.store.vector_store import SessionVectorStore

        chunks = _make_chunks([
            "朱元璋建立明朝",
            "李白是唐朝诗人",
            "杜甫是诗圣称号",
        ])
        vs = SessionVectorStore(chunks, enable_vector=False)
        # Should NOT raise — falls back to RRF/BM25-only
        results = vs.search("朱元璋", top_k=2, enable_rerank=True)
        assert isinstance(results, list)

    @patch("bookscope.store.vector_store._get_reranker")
    @patch("bookscope.store.vector_store._get_provider")
    def test_search_hybrid_with_rerank(self, mock_model, mock_reranker):
        mock_model.return_value = _mock_provider()
        mock_reranker.return_value = _mock_reranker()
        from bookscope.store.vector_store import SessionVectorStore

        chunks = _make_chunks(["朱元璋是明朝皇帝", "李白是唐朝诗人", "杜甫诗圣称号"])
        vs = SessionVectorStore(chunks)
        results = vs.search("朱元璋", top_k=2, enable_rerank=True)
        assert len(results) <= 2
        mock_reranker.return_value.predict.assert_called()

    def test_search_empty_with_rerank(self):
        from bookscope.store.vector_store import SessionVectorStore

        vs = SessionVectorStore([], enable_vector=False)
        assert vs.search("test", enable_rerank=True) == []

    def test_search_default_enables_rerank(self):
        """Verify enable_rerank defaults to True in signature."""
        import inspect  # noqa: PLC0415

        from bookscope.store.vector_store import SessionVectorStore

        sig = inspect.signature(SessionVectorStore.search)
        param = sig.parameters["enable_rerank"]
        assert param.default is True
