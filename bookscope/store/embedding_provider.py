"""Embedding provider: SiliconFlow API only（ADR-006 之后）.

ADR-006：r1 所有本地 ML 推理全部 API 化。此前的 Tier 2（Qwen3 本地）/
Tier 3（BGE-M3 本地）已下线，仅保留 Tier 1 SiliconFlow API——原因：
`sentence_transformers.SentenceTransformer` 加载 1-2 GB 模型隐含 GPU
依赖，违反"禁 GPU"硬约束，CPU 上首次 encode 数千 chunk 不可接受。

Provider 解析规则：

- 显式：`BOOKSCOPE_EMBEDDING_PROVIDER=siliconflow` 强制启用
- 自动：`SILICONFLOW_API_KEY` 存在即启用
- 兜底：返回 `None`，调用方降级到 BM25-only（`SessionVectorStore`
  在 `enable_vector=True` 但 provider 为 None 时会记 warning 并跑
  BM25-only）
"""

from __future__ import annotations

import logging
import os
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
# SiliconFlow API (OpenAI-compatible)
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
# Factory
# ---------------------------------------------------------------------------


def get_embedding_provider() -> EmbeddingProvider | None:
    """Resolve the embedding provider based on configuration.

    Resolution order:
      1. ``BOOKSCOPE_EMBEDDING_PROVIDER=siliconflow`` (explicit)
      2. Auto-detect: ``SILICONFLOW_API_KEY`` present → SiliconFlow
      3. ``None`` (caller should fall back to BM25-only)
    """
    explicit = os.environ.get("BOOKSCOPE_EMBEDDING_PROVIDER", "").strip().lower()

    if explicit == "siliconflow":
        logger.info("Embedding provider: SiliconFlow (explicit)")
        return SiliconFlowProvider()
    if explicit:
        logger.warning(
            "Unknown BOOKSCOPE_EMBEDDING_PROVIDER=%r "
            "(local tiers removed in ADR-006); auto-detecting",
            explicit,
        )

    if os.environ.get("SILICONFLOW_API_KEY"):
        logger.info("Embedding provider: SiliconFlow (auto — API key found)")
        return SiliconFlowProvider()

    logger.info("No embedding provider available — BM25-only mode")
    return None
