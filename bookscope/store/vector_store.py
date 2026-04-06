"""Per-session FAISS vector store with BM25 hybrid retrieval.

Combines two retrieval strategies via Reciprocal Rank Fusion (RRF):

1. **BM25** (keyword) — jieba tokenization + BM25Okapi scoring.
   Zero model dependency; excels at exact name/term matching.
2. **Vector** (semantic) — pluggable embedding provider (1024-dim).
   Catches paraphrases and semantic similarity.

BM25 is always available.  Vector search is optional — when no embedding
provider is configured (or deps are missing), search falls back to BM25-only.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

import jieba
import numpy as np
from rank_bm25 import BM25Okapi

if TYPE_CHECKING:
    from bookscope.models.schemas import ChunkResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_EMBED_DIM = 1024
_RRF_K = 60  # RRF constant (standard value used by Elasticsearch et al.)

_RERANKER_NAME = os.environ.get(
    "BOOKSCOPE_RERANKER_MODEL", "BAAI/bge-reranker-v2-m3",
)
_RERANKER_CHAR_LIMIT = 2048  # approx 512 tokens for the cross-encoder

# ---------------------------------------------------------------------------
# Lazy singleton for the embedding provider
# ---------------------------------------------------------------------------

_UNSET = object()
_provider = _UNSET


def _get_provider():
    """Return (and cache) the embedding provider, or *None* for BM25-only."""
    global _provider  # noqa: PLW0603
    if _provider is _UNSET:
        from bookscope.store.embedding_provider import get_embedding_provider

        _provider = get_embedding_provider()
        if _provider is not None:
            logger.info("Embedding provider ready: %s", _provider.name)
    return _provider


# ---------------------------------------------------------------------------
# Lazy singleton for the cross-encoder reranker
# ---------------------------------------------------------------------------

_reranker = None


def _get_reranker():
    """Return (and cache) the CrossEncoder reranker model."""
    global _reranker  # noqa: PLW0603
    if _reranker is None:
        from sentence_transformers import CrossEncoder

        _reranker = CrossEncoder(_RERANKER_NAME)
        logger.info("Loaded reranker model: %s", _RERANKER_NAME)
    return _reranker


# ---------------------------------------------------------------------------
# SessionVectorStore
# ---------------------------------------------------------------------------


class SessionVectorStore:
    """Per-session hybrid retriever: BM25 + optional FAISS vector search."""

    def __init__(
        self,
        chunks: list[ChunkResult],
        *,
        enable_vector: bool = True,
    ) -> None:
        self._chunks = list(chunks)

        # --- BM25 index (always built, zero model dependency) ---
        if self._chunks:
            tokenized = [list(jieba.cut(c.text)) for c in self._chunks]
            self._bm25 = BM25Okapi(tokenized)
        else:
            self._bm25 = None

        # --- FAISS vector index (optional) ---
        self._index = None
        if enable_vector and self._chunks:
            try:
                self._index = self._build_faiss_index()
            except Exception:
                logger.warning("FAISS vector index unavailable, using BM25-only")
        elif not self._chunks and enable_vector:
            try:
                import faiss
                self._index = faiss.IndexFlatIP(_EMBED_DIM)
            except ImportError:
                pass

    def _build_faiss_index(self):
        """Encode chunks and build FAISS IndexFlatIP."""
        import faiss

        provider = _get_provider()
        if provider is None:
            raise RuntimeError("No embedding provider available")

        texts = [c.text for c in self._chunks]
        embeddings = provider.encode_documents(texts)

        # L2-normalise so inner-product == cosine similarity
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        embeddings = embeddings / norms

        index = faiss.IndexFlatIP(embeddings.shape[1])
        index.add(embeddings)
        return index

    # ------------------------------------------------------------------
    # Search methods
    # ------------------------------------------------------------------

    def search_bm25(
        self, query: str, top_k: int = 5,
    ) -> list[tuple[ChunkResult, float]]:
        """BM25 keyword search using jieba tokenization."""
        if not self._bm25 or not self._chunks:
            return []

        tokens = list(jieba.cut(query))
        scores = self._bm25.get_scores(tokens)

        top_indices = np.argsort(scores)[::-1][:top_k]
        results: list[tuple[ChunkResult, float]] = []
        for idx in top_indices:
            if scores[idx] > 0:
                results.append((self._chunks[idx], float(scores[idx])))
        return results

    def search_vector(
        self, query: str, top_k: int = 5,
    ) -> list[tuple[ChunkResult, float]]:
        """FAISS vector similarity search."""
        if self._index is None or self._index.ntotal == 0:
            return []

        provider = _get_provider()
        if provider is None:
            return []

        q_vec = provider.encode_queries([query])
        norm = np.linalg.norm(q_vec)
        if norm > 0:
            q_vec = q_vec / norm

        k = min(top_k, self._index.ntotal)
        scores, indices = self._index.search(q_vec, k)

        results: list[tuple[ChunkResult, float]] = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
            results.append((self._chunks[idx], float(score)))
        return results

    def rerank(
        self,
        query: str,
        candidates: list[tuple[ChunkResult, float]],
        top_k: int = 5,
    ) -> list[tuple[ChunkResult, float]]:
        """Re-score *candidates* using the cross-encoder reranker."""
        if not candidates:
            return []

        reranker = _get_reranker()
        pairs = [
            (query, chunk.text[:_RERANKER_CHAR_LIMIT])
            for chunk, _score in candidates
        ]
        scores = reranker.predict(pairs)

        ranked = sorted(
            zip(candidates, scores), key=lambda x: x[1], reverse=True,
        )
        return [
            (chunk, float(score))
            for (chunk, _old_score), score in ranked[:top_k]
        ]

    def search(
        self, query: str, top_k: int = 5, *, enable_rerank: bool = True,
    ) -> list[tuple[ChunkResult, float]]:
        """Hybrid search: RRF fusion of BM25 + vector, optional cross-encoder rerank."""
        has_vector = self._index is not None and self._index.ntotal > 0
        has_bm25 = self._bm25 is not None

        # Single-source fallbacks
        if has_vector and not has_bm25:
            results = self.search_vector(query, top_k * 3 if enable_rerank else top_k)
            return self._maybe_rerank(query, results, top_k, enable_rerank)
        if has_bm25 and not has_vector:
            results = self.search_bm25(query, top_k * 3 if enable_rerank else top_k)
            return self._maybe_rerank(query, results, top_k, enable_rerank)
        if not has_vector and not has_bm25:
            return []

        # Hybrid: fetch wider candidate set, then fuse
        fetch_k = min(top_k * 3, len(self._chunks))
        bm25_results = self.search_bm25(query, fetch_k)
        vector_results = self.search_vector(query, fetch_k)

        fused = _rrf_fusion(bm25_results, vector_results, fetch_k)
        return self._maybe_rerank(query, fused, top_k, enable_rerank)

    def _maybe_rerank(
        self,
        query: str,
        candidates: list[tuple[ChunkResult, float]],
        top_k: int,
        enable_rerank: bool,
    ) -> list[tuple[ChunkResult, float]]:
        """Apply cross-encoder reranking if enabled, with graceful fallback."""
        if not enable_rerank or not candidates:
            return candidates[:top_k]
        try:
            return self.rerank(query, candidates, top_k)
        except Exception:
            logger.warning("Reranker unavailable, falling back to RRF-only")
            return candidates[:top_k]

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    @property
    def has_vector(self) -> bool:
        return self._index is not None and self._index.ntotal > 0

    @property
    def has_bm25(self) -> bool:
        return self._bm25 is not None


# ---------------------------------------------------------------------------
# Reciprocal Rank Fusion
# ---------------------------------------------------------------------------


def _rrf_fusion(
    results_a: list[tuple[ChunkResult, float]],
    results_b: list[tuple[ChunkResult, float]],
    top_k: int,
) -> list[tuple[ChunkResult, float]]:
    """Merge two ranked lists using RRF.  score(d) = Σ 1/(k + rank_i(d))"""
    chunk_map: dict[int, ChunkResult] = {}
    rrf_scores: dict[int, float] = {}

    for rank, (chunk, _score) in enumerate(results_a):
        idx = chunk.index
        chunk_map[idx] = chunk
        rrf_scores[idx] = rrf_scores.get(idx, 0.0) + 1.0 / (_RRF_K + rank + 1)

    for rank, (chunk, _score) in enumerate(results_b):
        idx = chunk.index
        chunk_map[idx] = chunk
        rrf_scores[idx] = rrf_scores.get(idx, 0.0) + 1.0 / (_RRF_K + rank + 1)

    sorted_indices = sorted(rrf_scores, key=lambda i: rrf_scores[i], reverse=True)
    return [(chunk_map[i], rrf_scores[i]) for i in sorted_indices[:top_k]]
