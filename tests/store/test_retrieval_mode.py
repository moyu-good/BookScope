"""``SessionVectorStore.retrieval_mode`` 单测（WP2a 检索降级可见）。

三条路径：

1. embedding provider 可用 → 建出 FAISS 索引 → ``"hybrid"``
2. 没配 provider 但 ``enable_vector=True`` → 建索引抛错被吞（现有降级分支）
   → ``"bm25_only"``
3. 显式 ``enable_vector=False`` → ``"bm25_only"``

provider 的 stub 方式沿用 ``test_vector_store_persistence.py``：monkeypatch
``vector_store._provider``，不碰真 API。
"""

from __future__ import annotations

import numpy as np
import pytest

from bookscope.models.schemas import ChunkResult
from bookscope.store import vector_store as vs_module
from bookscope.store.vector_store import SessionVectorStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _StubProvider:
    """确定性 4 维向量 provider，够 FAISS 建索引用，不依赖任何 SDK。"""

    name = "stub/embed-v1"
    dim = 4

    def _encode(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            h = hash(t)
            for d in range(self.dim):
                out[i, d] = float(((h >> (d * 8)) & 0xFF) - 128) / 128.0
        return out

    def encode_documents(self, texts: list[str]) -> np.ndarray:
        return self._encode(texts)

    def encode_queries(self, texts: list[str]) -> np.ndarray:
        return self._encode(texts)


@pytest.fixture
def chunks() -> list[ChunkResult]:
    return [
        ChunkResult(index=0, text="第一章 林冲 雪夜 山神庙"),
        ChunkResult(index=1, text="第二章 武松 景阳岗 打虎"),
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_retrieval_mode_hybrid_when_embedding_available(
    chunks: list[ChunkResult], monkeypatch: pytest.MonkeyPatch
) -> None:
    """provider 可用、FAISS 索引建成 → "hybrid"。"""
    monkeypatch.setattr(vs_module, "_provider", _StubProvider())
    store = SessionVectorStore(chunks, enable_vector=True)
    assert store.has_vector is True
    assert store.retrieval_mode == "hybrid"


def test_retrieval_mode_bm25_only_when_no_provider(
    chunks: list[ChunkResult], monkeypatch: pytest.MonkeyPatch
) -> None:
    """没配 embedding provider（等价于无 SILICONFLOW_API_KEY）时，
    建索引抛错走现有降级分支 → "bm25_only"。
    """
    monkeypatch.setattr(vs_module, "_provider", None)
    store = SessionVectorStore(chunks, enable_vector=True)
    assert store.has_vector is False
    assert store.has_bm25 is True
    assert store.retrieval_mode == "bm25_only"


def test_retrieval_mode_bm25_only_when_vector_disabled(
    chunks: list[ChunkResult], monkeypatch: pytest.MonkeyPatch
) -> None:
    """显式关掉向量检索 → "bm25_only"。"""
    monkeypatch.setattr(vs_module, "_provider", None)
    store = SessionVectorStore(chunks, enable_vector=False)
    assert store.retrieval_mode == "bm25_only"
