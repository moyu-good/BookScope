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

import json
import logging
import pickle
from pathlib import Path
from typing import TYPE_CHECKING

import jieba
import numpy as np
from rank_bm25 import BM25Okapi

if TYPE_CHECKING:
    from bookscope.models.schemas import ChunkResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Persistence errors
# ---------------------------------------------------------------------------


class VectorStoreLoadError(Exception):
    """Raised when SessionVectorStore.load_from_dir cannot reconstruct state.

    Distinguishes "index is unusable" (manifest missing / corrupted / schema
    bump) from ordinary ``FileNotFoundError``.  Callers can decide whether to
    fall back to a ``None`` vector store or fail hard.
    """


class VectorStoreProviderMismatch(VectorStoreLoadError):
    """Persisted embedding provider differs from (or is absent in) current env.

    Raised by ``load_from_dir`` when ``manifest.has_vector`` is ``True`` but
    the currently-configured embedding provider cannot honour the saved
    index — either no provider is configured, or its ``name`` does not match
    the one recorded in the manifest.  Silent fall-back would let vector
    search answer queries with a different model than the one used to build
    the index, which ADR-005 explicitly forbids.
    """

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_EMBED_DIM = 1024
_RRF_K = 60  # RRF constant (standard value used by Elasticsearch et al.)

# Persistence layout inside <session>/vector_index/
_MANIFEST_FILE = "manifest.json"
_CHUNKS_FILE = "chunks.json"
_BM25_FILE = "bm25.pkl"
_FAISS_FILE = "faiss.index"
_MANIFEST_VERSION = 1

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

    def search(
        self, query: str, top_k: int = 5,
    ) -> list[tuple[ChunkResult, float]]:
        """Hybrid search: RRF fusion of BM25 + vector, or single-source fallback.

        ADR-006：本地 cross-encoder reranker 已下线（违反"禁 GPU"硬约束），
        `enable_rerank` 参数一并移除。如需 rerank 能力请走 ADR-007 的
        API-based RerankerProvider（尚未实现，能力暂归零）。
        """
        has_vector = self._index is not None and self._index.ntotal > 0
        has_bm25 = self._bm25 is not None

        if has_vector and not has_bm25:
            return self.search_vector(query, top_k)
        if has_bm25 and not has_vector:
            return self.search_bm25(query, top_k)
        if not has_vector and not has_bm25:
            return []

        # Hybrid: fetch wider candidate set, then fuse
        fetch_k = min(top_k * 3, len(self._chunks))
        bm25_results = self.search_bm25(query, fetch_k)
        vector_results = self.search_vector(query, fetch_k)

        fused = _rrf_fusion(bm25_results, vector_results, fetch_k)
        return fused[:top_k]

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

    @property
    def retrieval_mode(self) -> str:
        """本 store 实际生效的检索模式（WP2a：降级不再静默）。

        - ``"hybrid"``：FAISS 向量索引可用，``search`` 走 BM25 + 向量 RRF 融合
        - ``"bm25_only"``：embedding 不可用（没配 key、依赖缺失或建索引失败），
          只剩 BM25 关键词检索

        只读不改行为：内部状态就是 ``has_vector``，这里对外吐成字符串，
        供 ``ChunkMatch.retrieval_mode`` 留痕，让分数波动能归因到检索层。
        """
        return "hybrid" if self.has_vector else "bm25_only"

    # ------------------------------------------------------------------
    # Persistence (ADR-005)
    # ------------------------------------------------------------------

    def save_to_dir(self, path: Path | str) -> None:
        """Persist this store to *path* as a self-contained directory.

        Writes four files under *path* (creating it if needed):

        - ``manifest.json`` — version, chunk count, ``has_vector`` flag,
          embedding provider name + dim (when vector index present).
        - ``chunks.json`` — ``[ChunkResult.model_dump()]``.
        - ``bm25.pkl`` — pickled ``BM25Okapi`` instance.  (Safe because
          we write and read our own pickle; never loaded from untrusted
          sources.)
        - ``faiss.index`` — FAISS binary, only when ``has_vector`` is True.

        Any existing files in *path* with these names are overwritten.
        Other files are left untouched so callers can nest ad-hoc debug
        dumps alongside.
        """
        target = Path(path)
        target.mkdir(parents=True, exist_ok=True)

        has_vector = self._index is not None and self._index.ntotal > 0
        embedding_provider_name: str | None = None
        embedding_dim: int | None = None
        if has_vector:
            provider = _get_provider()
            if provider is not None:
                embedding_provider_name = provider.name
                embedding_dim = provider.dim
            else:
                embedding_dim = int(self._index.d)  # type: ignore[union-attr]

        manifest: dict[str, object] = {
            "version": _MANIFEST_VERSION,
            "chunk_count": len(self._chunks),
            "has_vector": has_vector,
            "embedding_provider": embedding_provider_name,
            "embedding_dim": embedding_dim,
        }

        with (target / _CHUNKS_FILE).open("w", encoding="utf-8") as fp:
            json.dump(
                {"chunks": [c.model_dump() for c in self._chunks]},
                fp,
                ensure_ascii=False,
            )

        with (target / _BM25_FILE).open("wb") as fp:
            pickle.dump(self._bm25, fp, protocol=pickle.HIGHEST_PROTOCOL)

        faiss_path = target / _FAISS_FILE
        if has_vector:
            import faiss  # local import: keep vector_store module import-light

            faiss.write_index(self._index, str(faiss_path))
        elif faiss_path.exists():
            # Stale file from a previous save where vector index existed.
            faiss_path.unlink()

        with (target / _MANIFEST_FILE).open("w", encoding="utf-8") as fp:
            json.dump(manifest, fp, ensure_ascii=False, indent=2)

    @classmethod
    def load_from_dir(cls, path: Path | str) -> SessionVectorStore:
        """Reconstruct a ``SessionVectorStore`` previously saved by
        :meth:`save_to_dir`.

        Raises:
            VectorStoreLoadError: manifest missing, unreadable, or from an
                incompatible schema version; BM25 pickle absent; FAISS index
                expected by manifest but file missing.
            VectorStoreProviderMismatch: manifest says ``has_vector`` is True
                but current embedding provider is missing or has a different
                ``name`` than the one recorded at save time.
        """
        from bookscope.models.schemas import ChunkResult

        source = Path(path)
        manifest_path = source / _MANIFEST_FILE
        if not manifest_path.is_file():
            raise VectorStoreLoadError(
                f"manifest.json missing at {manifest_path}"
            )

        try:
            with manifest_path.open("r", encoding="utf-8") as fp:
                manifest = json.load(fp)
        except (OSError, json.JSONDecodeError) as exc:
            raise VectorStoreLoadError(
                f"manifest.json unreadable: {exc}"
            ) from exc

        version = manifest.get("version")
        if version != _MANIFEST_VERSION:
            raise VectorStoreLoadError(
                f"unsupported manifest version {version!r}; "
                f"expected {_MANIFEST_VERSION}"
            )

        # Chunks
        chunks_path = source / _CHUNKS_FILE
        if not chunks_path.is_file():
            raise VectorStoreLoadError(f"chunks.json missing at {chunks_path}")
        try:
            with chunks_path.open("r", encoding="utf-8") as fp:
                chunks_raw = json.load(fp)
            chunks = [
                ChunkResult.model_validate(c)
                for c in chunks_raw.get("chunks", [])
            ]
        except Exception as exc:  # noqa: BLE001 — Pydantic ValidationError etc.
            raise VectorStoreLoadError(
                f"chunks.json failed to deserialise: {exc}"
            ) from exc

        # BM25
        bm25_path = source / _BM25_FILE
        if not bm25_path.is_file():
            raise VectorStoreLoadError(f"bm25.pkl missing at {bm25_path}")
        try:
            with bm25_path.open("rb") as fp:
                bm25 = pickle.load(fp)  # noqa: S301 — project-local pickle
        except Exception as exc:  # noqa: BLE001
            raise VectorStoreLoadError(
                f"bm25.pkl failed to load: {exc}"
            ) from exc

        # FAISS (optional)
        index = None
        has_vector = bool(manifest.get("has_vector"))
        if has_vector:
            expected_provider = manifest.get("embedding_provider")
            current_provider = _get_provider()
            if current_provider is None:
                raise VectorStoreProviderMismatch(
                    "persisted index requires embedding provider "
                    f"{expected_provider!r}, but none is configured"
                )
            if expected_provider and current_provider.name != expected_provider:
                raise VectorStoreProviderMismatch(
                    f"persisted index was built with {expected_provider!r} "
                    f"but current provider is {current_provider.name!r}"
                )

            faiss_path = source / _FAISS_FILE
            if not faiss_path.is_file():
                raise VectorStoreLoadError(
                    f"faiss.index missing at {faiss_path} (manifest says "
                    "has_vector=True)"
                )
            try:
                import faiss

                index = faiss.read_index(str(faiss_path))
            except Exception as exc:  # noqa: BLE001
                raise VectorStoreLoadError(
                    f"faiss.index failed to load: {exc}"
                ) from exc

        return cls._from_components(chunks=chunks, bm25=bm25, index=index)

    @classmethod
    def _from_components(
        cls,
        *,
        chunks: list[ChunkResult],
        bm25: BM25Okapi | None,
        index: object | None,
    ) -> SessionVectorStore:
        """Build a ``SessionVectorStore`` from already-constructed components.

        Bypasses ``__init__`` (which would re-tokenise with jieba and call
        the embedding provider).  Intended only for persistence code paths.
        """
        self = cls.__new__(cls)
        self._chunks = list(chunks)
        self._bm25 = bm25
        self._index = index
        return self


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
