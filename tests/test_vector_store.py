"""Tests for bookscope.store.vector_store (BM25 + FAISS hybrid RAG)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from bookscope.models.schemas import ChunkResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_chunks(texts: list[str]) -> list[ChunkResult]:
    return [ChunkResult(index=i, text=t) for i, t in enumerate(texts)]


def _mock_model(dim: int = 1024):
    """Return a mock SentenceTransformer whose encode() yields deterministic vectors."""
    model = MagicMock()

    def _encode(texts, **_kwargs):
        rng = np.random.RandomState(42)
        vecs = rng.randn(len(texts), dim).astype(np.float32)
        return vecs

    model.encode.side_effect = _encode
    return model


# ---------------------------------------------------------------------------
# BM25 search (no embedding model needed)
# ---------------------------------------------------------------------------

class TestBM25:

    def test_bm25_basic_search(self):
        from bookscope.store.vector_store import SessionVectorStore

        chunks = _make_chunks([
            "朱元璋是明朝的开国皇帝",
            "徐达是明朝的著名将领",
            "李白是唐朝的诗人",
        ])
        vs = SessionVectorStore(chunks, enable_vector=False)
        results = vs.search_bm25("朱元璋")
        assert len(results) > 0
        assert results[0][0].index == 0  # chunk about 朱元璋 ranks first

    def test_bm25_returns_scores(self):
        from bookscope.store.vector_store import SessionVectorStore

        chunks = _make_chunks(["测试文本一", "测试文本二"])
        vs = SessionVectorStore(chunks, enable_vector=False)
        results = vs.search_bm25("测试")
        for chunk, score in results:
            assert isinstance(score, float)
            assert score > 0

    def test_bm25_empty_store(self):
        from bookscope.store.vector_store import SessionVectorStore

        vs = SessionVectorStore([], enable_vector=False)
        assert vs.search_bm25("anything") == []

    def test_bm25_no_match(self):
        from bookscope.store.vector_store import SessionVectorStore

        chunks = _make_chunks(["苹果是一种水果"])
        vs = SessionVectorStore(chunks, enable_vector=False)
        results = vs.search_bm25("量子物理")
        # BM25 returns empty when no tokens overlap
        assert all(score == 0 for _, score in results) or len(results) == 0

    def test_bm25_top_k(self):
        from bookscope.store.vector_store import SessionVectorStore

        chunks = _make_chunks([f"文本{i}" for i in range(20)])
        vs = SessionVectorStore(chunks, enable_vector=False)
        results = vs.search_bm25("文本", top_k=3)
        assert len(results) <= 3

    def test_bm25_chinese_name_matching(self):
        """BM25 should excel at exact Chinese name matching."""
        from bookscope.store.vector_store import SessionVectorStore

        chunks = _make_chunks([
            "朱元璋原名朱重八，出身贫寒",
            "陈友谅是朱元璋的主要对手",
            "刘伯温辅佐朱元璋建立明朝",
            "李世民开创了贞观之治",
        ])
        vs = SessionVectorStore(chunks, enable_vector=False)
        results = vs.search_bm25("朱元璋")
        # All three chunks mentioning 朱元璋 should appear
        matched_indices = {r[0].index for r in results}
        assert {0, 1, 2}.issubset(matched_indices)


# ---------------------------------------------------------------------------
# Vector search (with mocked embedding model)
# ---------------------------------------------------------------------------

class TestVectorSearch:

    @patch("bookscope.store.vector_store._get_model")
    def test_vector_basic(self, mock_get):
        mock_get.return_value = _mock_model()
        from bookscope.store.vector_store import SessionVectorStore

        chunks = _make_chunks(["alpha", "beta", "gamma"])
        vs = SessionVectorStore(chunks)
        assert vs.chunk_count == 3
        assert vs.has_vector

    @patch("bookscope.store.vector_store._get_model")
    def test_vector_search_returns_correct_type(self, mock_get):
        mock_get.return_value = _mock_model()
        from bookscope.store.vector_store import SessionVectorStore

        vs = SessionVectorStore(_make_chunks(["a", "b", "c"]))
        results = vs.search_vector("query")
        assert isinstance(results, list)
        for item in results:
            assert isinstance(item, tuple)
            assert isinstance(item[0], ChunkResult)
            assert isinstance(item[1], float)

    @patch("bookscope.store.vector_store._get_model")
    def test_vector_search_top_k(self, mock_get):
        mock_get.return_value = _mock_model()
        from bookscope.store.vector_store import SessionVectorStore

        vs = SessionVectorStore(_make_chunks(["a", "b", "c", "d", "e"]))
        results = vs.search_vector("query", top_k=2)
        assert len(results) <= 2

    @patch("bookscope.store.vector_store._get_model")
    def test_vector_empty_store(self, mock_get):
        mock_get.return_value = _mock_model()
        from bookscope.store.vector_store import SessionVectorStore

        vs = SessionVectorStore([])
        assert vs.search_vector("anything") == []

    @patch("bookscope.store.vector_store._get_model")
    def test_vector_relevance_ordering(self, mock_get):
        """A query identical to one chunk's embedding should rank it first."""
        dim = 1024
        model = MagicMock()

        chunk_vecs = np.zeros((3, dim), dtype=np.float32)
        chunk_vecs[0, 0] = 1.0
        chunk_vecs[1, 1] = 1.0
        chunk_vecs[2, 2] = 1.0

        call_count = {"n": 0}

        def _encode(texts, **_kw):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return chunk_vecs[: len(texts)]
            q = np.zeros((1, dim), dtype=np.float32)
            q[0, 1] = 1.0
            return q

        model.encode.side_effect = _encode
        mock_get.return_value = model

        from bookscope.store.vector_store import SessionVectorStore

        vs = SessionVectorStore(_make_chunks(["zero", "one", "two"]))
        results = vs.search_vector("match-chunk-1", top_k=3)

        assert results[0][0].index == 1
        assert results[0][1] == pytest.approx(1.0, abs=0.01)

    @patch("bookscope.store.vector_store._get_model")
    def test_vector_scores_are_finite(self, mock_get):
        mock_get.return_value = _mock_model()
        from bookscope.store.vector_store import SessionVectorStore

        vs = SessionVectorStore(_make_chunks(["one", "two", "three"]))
        results = vs.search_vector("test")
        for _, score in results:
            assert np.isfinite(score)


# ---------------------------------------------------------------------------
# Hybrid search (BM25 + vector, RRF fusion)
# ---------------------------------------------------------------------------

class TestHybridSearch:

    @patch("bookscope.store.vector_store._get_model")
    def test_hybrid_returns_results(self, mock_get):
        mock_get.return_value = _mock_model()
        from bookscope.store.vector_store import SessionVectorStore

        chunks = _make_chunks(["朱元璋建立明朝", "徐达北伐中原", "刘伯温运筹帷幄"])
        vs = SessionVectorStore(chunks)
        assert vs.has_bm25
        assert vs.has_vector

        results = vs.search("朱元璋")
        assert len(results) > 0

    @patch("bookscope.store.vector_store._get_model")
    def test_hybrid_top_k(self, mock_get):
        mock_get.return_value = _mock_model()
        from bookscope.store.vector_store import SessionVectorStore

        chunks = _make_chunks([f"内容{i}的描述" for i in range(20)])
        vs = SessionVectorStore(chunks)
        results = vs.search("内容", top_k=3)
        assert len(results) <= 3

    def test_hybrid_falls_back_to_bm25(self):
        """When vector is disabled, search() uses BM25 only."""
        from bookscope.store.vector_store import SessionVectorStore

        # Need 3+ docs: BM25Okapi IDF = log((N-n+0.5)/(n+0.5)),
        # with N=2 and n=1 this is log(1)=0, yielding zero scores.
        chunks = _make_chunks(["朱元璋是皇帝", "李白是诗人", "杜甫是诗圣"])
        vs = SessionVectorStore(chunks, enable_vector=False)
        assert vs.has_bm25
        assert not vs.has_vector

        results = vs.search("朱元璋")
        assert len(results) > 0
        assert results[0][0].index == 0

    def test_hybrid_empty(self):
        from bookscope.store.vector_store import SessionVectorStore

        vs = SessionVectorStore([], enable_vector=False)
        assert vs.search("test") == []


# ---------------------------------------------------------------------------
# RRF fusion
# ---------------------------------------------------------------------------

class TestRRFFusion:

    def test_rrf_merges_both_lists(self):
        from bookscope.store.vector_store import _rrf_fusion

        c0 = ChunkResult(index=0, text="a")
        c1 = ChunkResult(index=1, text="b")
        c2 = ChunkResult(index=2, text="c")

        list_a = [(c0, 0.9), (c1, 0.5)]
        list_b = [(c2, 0.8), (c0, 0.6)]

        results = _rrf_fusion(list_a, list_b, top_k=3)
        assert len(results) == 3
        # c0 appears in both lists → highest RRF score
        assert results[0][0].index == 0

    def test_rrf_top_k_limit(self):
        from bookscope.store.vector_store import _rrf_fusion

        chunks = [ChunkResult(index=i, text=str(i)) for i in range(10)]
        list_a = [(chunks[i], float(10 - i)) for i in range(10)]
        list_b = [(chunks[9 - i], float(10 - i)) for i in range(10)]

        results = _rrf_fusion(list_a, list_b, top_k=3)
        assert len(results) == 3

    def test_rrf_empty_inputs(self):
        from bookscope.store.vector_store import _rrf_fusion

        assert _rrf_fusion([], [], top_k=5) == []

    def test_rrf_one_empty(self):
        from bookscope.store.vector_store import _rrf_fusion

        c0 = ChunkResult(index=0, text="a")
        results = _rrf_fusion([(c0, 0.9)], [], top_k=5)
        assert len(results) == 1
        assert results[0][0].index == 0


# ---------------------------------------------------------------------------
# Singleton model loader
# ---------------------------------------------------------------------------

def test_get_model_singleton():
    """_get_model returns the cached instance when already set."""
    import bookscope.store.vector_store as mod

    old = mod._model
    try:
        sentinel = MagicMock(name="cached-model")
        mod._model = sentinel
        result = mod._get_model()
        assert result is sentinel
    finally:
        mod._model = old


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------

def test_properties_bm25_only():
    from bookscope.store.vector_store import SessionVectorStore

    vs = SessionVectorStore(_make_chunks(["text"]), enable_vector=False)
    assert vs.chunk_count == 1
    assert vs.has_bm25
    assert not vs.has_vector


@patch("bookscope.store.vector_store._get_model")
def test_properties_hybrid(mock_get):
    mock_get.return_value = _mock_model()
    from bookscope.store.vector_store import SessionVectorStore

    vs = SessionVectorStore(_make_chunks(["text"]))
    assert vs.chunk_count == 1
    assert vs.has_bm25
    assert vs.has_vector


# ---------------------------------------------------------------------------
# _build_chat_context (from api/main.py)
# ---------------------------------------------------------------------------

def test_build_context_with_rag():
    """RAG path includes retrieved chunk text in context."""
    from bookscope.api.main import _build_chat_context

    book = MagicMock()
    book.title = "测试书"
    book.language = "zh"

    graph = MagicMock()
    graph.overall_summary = "这是一本测试书"
    graph.characters = []

    chunk = ChunkResult(index=0, text="朱元璋是明朝的开国皇帝。" * 5)
    vs = MagicMock()
    vs.search.return_value = [(chunk, 0.92)]

    ctx = _build_chat_context(book, graph, vs, "朱元璋是谁")
    assert "相关段落" in ctx
    assert "朱元璋" in ctx
    assert "0.92" in ctx


def test_build_context_without_rag_falls_back_to_kg():
    """Without vector store, falls back to chapter summaries."""
    from bookscope.api.main import _build_chat_context

    book = MagicMock()
    book.title = "测试"
    book.language = "zh"

    ch = MagicMock()
    ch.chunk_index = 0
    ch.summary = "第一章摘要"

    graph = MagicMock()
    graph.overall_summary = "全书概要"
    graph.characters = []
    graph.chapter_summaries = [ch]

    ctx = _build_chat_context(book, graph, None, "测试问题")
    assert "第一章摘要" in ctx
    assert "相关段落" not in ctx


def test_build_context_no_graph_no_rag():
    """Minimal context when neither graph nor vector store is available."""
    from bookscope.api.main import _build_chat_context

    book = MagicMock()
    book.title = "空书"
    book.language = "en"

    ctx = _build_chat_context(book, None, None, "hello")
    assert "空书" in ctx
