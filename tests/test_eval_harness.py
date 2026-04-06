"""Integration test: evaluate retrieval strategies against a gold QA dataset.

Mocks the embedding model and reranker — no GPU or model downloads needed.
Compares BM25-only, hybrid, and hybrid+reranker on retrieval metrics.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np

from bookscope.eval.dataset import EvalSample
from bookscope.eval.retrieval_metrics import mrr_at_k, ndcg_at_k, recall_at_k
from bookscope.models.schemas import ChunkResult

# ---------------------------------------------------------------------------
# Inline test data
# ---------------------------------------------------------------------------

CHUNKS = [
    ChunkResult(index=0, text="朱元璋原名朱重八出身贫寒农家"),
    ChunkResult(index=1, text="陈友谅是朱元璋争天下的主要对手"),
    ChunkResult(index=2, text="刘伯温辅佐朱元璋建立明朝"),
    ChunkResult(index=3, text="徐达是明朝建国第一名将"),
    ChunkResult(index=4, text="刘伯温精通兵法谋略"),
    ChunkResult(index=5, text="朱元璋推翻元朝建立大明王朝"),
    ChunkResult(index=6, text="鄱阳湖大战是朱元璋与陈友谅的决战"),
    ChunkResult(index=7, text="李白是唐朝最伟大的浪漫主义诗人"),
]

EVAL_SAMPLES = [
    EvalSample(
        question="朱元璋是谁",
        expected_answer="朱元璋是明朝的开国皇帝",
        relevant_chunk_indices=[0, 2, 5],
    ),
    EvalSample(
        question="刘伯温的贡献",
        expected_answer="刘伯温辅佐朱元璋建立明朝",
        relevant_chunk_indices=[2, 4],
    ),
]


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


def _mock_reranker():
    reranker = MagicMock()

    def _predict(pairs, **_kw):
        return np.arange(len(pairs), 0, -1, dtype=np.float32)

    reranker.predict.side_effect = _predict
    return reranker


def _run_eval(store, samples, k=5, enable_rerank=False):
    """Compute average retrieval metrics for a strategy."""
    recalls, mrrs, ndcgs = [], [], []
    for sample in samples:
        results = store.search(sample.question, top_k=k, enable_rerank=enable_rerank)
        retrieved = [chunk.index for chunk, _score in results]
        relevant = set(sample.relevant_chunk_indices)
        recalls.append(recall_at_k(retrieved, relevant, k))
        mrrs.append(mrr_at_k(retrieved, relevant, k))
        ndcgs.append(ndcg_at_k(retrieved, relevant, k))
    return {
        "recall@5": float(np.mean(recalls)),
        "mrr@5": float(np.mean(mrrs)),
        "ndcg@5": float(np.mean(ndcgs)),
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestEvalHarness:

    def test_bm25_only_produces_valid_scores(self):
        from bookscope.store.vector_store import SessionVectorStore

        vs = SessionVectorStore(CHUNKS, enable_vector=False)
        scores = _run_eval(vs, EVAL_SAMPLES, enable_rerank=False)
        for name, val in scores.items():
            assert 0.0 <= val <= 1.0, f"{name} out of range: {val}"

    @patch("bookscope.store.vector_store._get_provider")
    def test_hybrid_produces_valid_scores(self, mock_get_provider):
        mock_get_provider.return_value = _mock_provider()
        from bookscope.store.vector_store import SessionVectorStore

        vs = SessionVectorStore(CHUNKS)
        scores = _run_eval(vs, EVAL_SAMPLES, enable_rerank=False)
        for name, val in scores.items():
            assert 0.0 <= val <= 1.0, f"{name} out of range: {val}"

    @patch("bookscope.store.vector_store._get_reranker")
    @patch("bookscope.store.vector_store._get_provider")
    def test_hybrid_reranker_produces_valid_scores(self, mock_provider, mock_reranker):
        mock_provider.return_value = _mock_provider()
        mock_reranker.return_value = _mock_reranker()
        from bookscope.store.vector_store import SessionVectorStore

        vs = SessionVectorStore(CHUNKS)
        scores = _run_eval(vs, EVAL_SAMPLES, enable_rerank=True)
        for name, val in scores.items():
            assert 0.0 <= val <= 1.0, f"{name} out of range: {val}"

    def test_bm25_recall_nonzero_for_keyword_match(self):
        """BM25 should find chunks containing the query terms."""
        from bookscope.store.vector_store import SessionVectorStore

        vs = SessionVectorStore(CHUNKS, enable_vector=False)
        sample = EVAL_SAMPLES[0]  # "朱元璋是谁" — chunks 0, 2, 5 mention 朱元璋
        results = vs.search(sample.question, top_k=5, enable_rerank=False)
        retrieved = [c.index for c, _ in results]
        relevant = set(sample.relevant_chunk_indices)
        assert recall_at_k(retrieved, relevant, 5) > 0.0

    def test_eval_sample_model_works(self):
        """EvalSample can be constructed and used in eval loop."""
        s = EvalSample(question="Q?", expected_answer="A.", relevant_chunk_indices=[0])
        assert s.question == "Q?"
        assert 0 in s.relevant_chunk_indices
