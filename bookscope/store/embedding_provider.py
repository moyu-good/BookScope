"""Three-tier embedding provider: SiliconFlow API / Local Qwen3 / Local BGE-M3.

Tier 1 (default): SiliconFlow API — free, zero local model download.
Tier 2 (optional): Local Qwen3-Embedding-0.6B — 1.2 GB, instruction-aware.
Tier 3 (advanced): Local BAAI/bge-m3 — 2.2 GB, current production model.

Provider is selected via ``get_embedding_provider()`` which respects:
  1. ``BOOKSCOPE_EMBEDDING_PROVIDER`` env var (explicit override)
  2. Auto-detection: API key present → SiliconFlow; local cache → local model
  3. Fallback: ``None`` (BM25-only)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np
import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Interface every embedding backend must satisfy."""

    @property
    def name(self) -> str:
        """Human-readable provider name."""
        ...

    @property
    def dim(self) -> int:
        """Embedding dimensionality (e.g. 1024)."""
        ...

    def encode_documents(self, texts: list[str]) -> np.ndarray:
        """Encode document texts.  Returns ``(N, dim)`` float32 array."""
        ...

    def encode_queries(self, texts: list[str]) -> np.ndarray:
        """Encode query texts.  Returns ``(N, dim)`` float32 array.

        May prepend task instructions for instruction-aware models.
        """
        ...


# ---------------------------------------------------------------------------
# Tier 1 — SiliconFlow API (free, OpenAI-compatible)
# ---------------------------------------------------------------------------

_SF_BASE_URL = "https://api.siliconflow.cn/v1/embeddings"
_SF_BATCH_SIZE = 32
_SF_TIMEOUT = 30


class SiliconFlowProvider:
    """Embedding via SiliconFlow free API (OpenAI-compatible)."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "BAAI/bge-m3",
    ) -> None:
        self._api_key = api_key or os.environ.get("SILICONFLOW_API_KEY", "")
        self._model = model

    @property
    def name(self) -> str:
        return f"SiliconFlow/{self._model}"

    @property
    def dim(self) -> int:
        return 1024

    # -- core -----------------------------------------------------------------

    def _call_api(self, texts: list[str]) -> list[list[float]]:
        """POST to SiliconFlow and return ordered embedding vectors."""
        all_embeddings: list[tuple[int, list[float]]] = []
        for start in range(0, len(texts), _SF_BATCH_SIZE):
            batch = texts[start : start + _SF_BATCH_SIZE]
            resp = requests.post(
                _SF_BASE_URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": self._model, "input": batch},
                timeout=_SF_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()["data"]
            for item in data:
                all_embeddings.append((start + item["index"], item["embedding"]))

        all_embeddings.sort(key=lambda x: x[0])
        return [emb for _, emb in all_embeddings]

    def encode_documents(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self.dim), dtype=np.float32)
        vecs = self._call_api(texts)
        return np.array(vecs, dtype=np.float32)

    def encode_queries(self, texts: list[str]) -> np.ndarray:
        return self.encode_documents(texts)


# ---------------------------------------------------------------------------
# Tier 2 — Local Qwen3-Embedding-0.6B (instruction-aware)
# ---------------------------------------------------------------------------

_QWEN3_MODEL = "Qwen/Qwen3-Embedding-0.6B"
_QWEN3_QUERY_PREFIX = (
    "Instruct: Given a web search query, retrieve relevant passages "
    "that answer the query\nQuery: "
)
_LOCAL_BATCH_SIZE = 32


class Qwen3LocalProvider:
    """Local Qwen3-Embedding-0.6B with instruction-aware query encoding."""

    def __init__(self) -> None:
        self._model = None

    @property
    def name(self) -> str:
        return f"Local/{_QWEN3_MODEL}"

    @property
    def dim(self) -> int:
        return 1024

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(_QWEN3_MODEL)
            logger.info("Loaded local embedding model: %s", _QWEN3_MODEL)
        return self._model

    def encode_documents(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self.dim), dtype=np.float32)
        model = self._load()
        emb = model.encode(
            texts, show_progress_bar=False, convert_to_numpy=True,
            batch_size=_LOCAL_BATCH_SIZE,
        )
        return np.asarray(emb, dtype=np.float32)

    def encode_queries(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self.dim), dtype=np.float32)
        prefixed = [_QWEN3_QUERY_PREFIX + t for t in texts]
        return self.encode_documents(prefixed)


# ---------------------------------------------------------------------------
# Tier 3 — Local BAAI/bge-m3 (production default)
# ---------------------------------------------------------------------------

_BGE_M3_MODEL = "BAAI/bge-m3"


class BgeM3LocalProvider:
    """Local BAAI/bge-m3 embedding (2.2 GB, 1024-dim, 8192-token context)."""

    def __init__(self) -> None:
        self._model = None

    @property
    def name(self) -> str:
        return f"Local/{_BGE_M3_MODEL}"

    @property
    def dim(self) -> int:
        return 1024

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(_BGE_M3_MODEL)
            logger.info("Loaded local embedding model: %s", _BGE_M3_MODEL)
        return self._model

    def encode_documents(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self.dim), dtype=np.float32)
        model = self._load()
        emb = model.encode(
            texts, show_progress_bar=False, convert_to_numpy=True,
            batch_size=_LOCAL_BATCH_SIZE,
        )
        return np.asarray(emb, dtype=np.float32)

    def encode_queries(self, texts: list[str]) -> np.ndarray:
        return self.encode_documents(texts)


# ---------------------------------------------------------------------------
# HuggingFace cache detection (avoid triggering downloads)
# ---------------------------------------------------------------------------


def _is_model_cached(repo_id: str) -> bool:
    """Check if a HuggingFace model is already downloaded locally."""
    try:
        from huggingface_hub import scan_cache_dir

        cache_info = scan_cache_dir()
        cached_repos = {r.repo_id for r in cache_info.repos}
        return repo_id in cached_repos
    except Exception:
        # huggingface_hub not installed or scan failed — check common path
        hf_home = os.environ.get(
            "HF_HOME",
            os.path.join(Path.home(), ".cache", "huggingface", "hub"),
        )
        # Models are stored as models--{org}--{name}
        folder_name = f"models--{repo_id.replace('/', '--')}"
        return Path(hf_home, folder_name).is_dir()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_embedding_provider() -> EmbeddingProvider | None:
    """Resolve the embedding provider based on configuration.

    Resolution order:
      1. ``BOOKSCOPE_EMBEDDING_PROVIDER`` env var (explicit)
      2. Auto-detect: API key → SiliconFlow; cached model → local
      3. ``None`` (caller should fall back to BM25-only)
    """
    explicit = os.environ.get("BOOKSCOPE_EMBEDDING_PROVIDER", "").strip().lower()

    if explicit == "siliconflow":
        logger.info("Embedding provider: SiliconFlow (explicit)")
        return SiliconFlowProvider()
    if explicit == "local-qwen3":
        logger.info("Embedding provider: Qwen3 local (explicit)")
        return Qwen3LocalProvider()
    if explicit == "local-bge-m3":
        logger.info("Embedding provider: BGE-M3 local (explicit)")
        return BgeM3LocalProvider()
    if explicit:
        logger.warning("Unknown BOOKSCOPE_EMBEDDING_PROVIDER=%r, auto-detecting", explicit)

    # Auto-detect
    if os.environ.get("SILICONFLOW_API_KEY"):
        logger.info("Embedding provider: SiliconFlow (auto — API key found)")
        return SiliconFlowProvider()

    if _is_model_cached(_BGE_M3_MODEL):
        logger.info("Embedding provider: BGE-M3 local (auto — cached)")
        return BgeM3LocalProvider()

    if _is_model_cached(_QWEN3_MODEL):
        logger.info("Embedding provider: Qwen3 local (auto — cached)")
        return Qwen3LocalProvider()

    logger.info("No embedding provider available — BM25-only mode")
    return None
