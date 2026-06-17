"""Tests for ``SessionVectorStore.save_to_dir`` / ``load_from_dir``.

Covers ADR-005 落地要点第 4 步 — roundtrip persistence of BM25 + optional
FAISS index + manifest validation. Vector-enabled cases stub out the
embedding provider via ``monkeypatch`` on ``vector_store._provider`` so the
tests never hit a real API.
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from bookscope.models.schemas import ChunkResult
from bookscope.store import vector_store as vs_module
from bookscope.store.vector_store import (
    SessionVectorStore,
    VectorStoreLoadError,
    VectorStoreProviderMismatch,
)

# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------


class _StubProvider:
    """Deterministic 4-dim provider — enough for FAISS roundtrip without SDKs."""

    def __init__(self, name: str = "stub/embed-v1", dim: int = 4) -> None:
        self._name = name
        self._dim = dim

    @property
    def name(self) -> str:
        return self._name

    @property
    def dim(self) -> int:
        return self._dim

    def _encode(self, texts: list[str]) -> np.ndarray:
        # Hash-based deterministic vectors — same text yields same vector.
        out = np.zeros((len(texts), self._dim), dtype=np.float32)
        for i, t in enumerate(texts):
            h = hash(t)
            for d in range(self._dim):
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
        ChunkResult(index=2, text="第三章 宋江 浔阳楼 题诗"),
    ]


@pytest.fixture
def stub_provider(monkeypatch: pytest.MonkeyPatch) -> _StubProvider:
    provider = _StubProvider()
    monkeypatch.setattr(vs_module, "_provider", provider)
    return provider


@pytest.fixture
def no_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force ``_get_provider()`` to return ``None`` (BM25-only)."""
    monkeypatch.setattr(vs_module, "_provider", None)


def _manifest(path: Path) -> dict[str, Any]:
    with (path / "manifest.json").open("r", encoding="utf-8") as fp:
        return json.load(fp)


# ---------------------------------------------------------------------------
# BM25-only roundtrip (no embedding provider available)
# ---------------------------------------------------------------------------


def test_save_load_bm25_only_roundtrip(
    tmp_path: Path, chunks: list[ChunkResult], no_provider: None
) -> None:
    store = SessionVectorStore(chunks, enable_vector=False)
    assert store.has_bm25 is True
    assert store.has_vector is False

    store.save_to_dir(tmp_path)

    manifest = _manifest(tmp_path)
    assert manifest["version"] == 1
    assert manifest["chunk_count"] == 3
    assert manifest["has_vector"] is False
    assert manifest["embedding_provider"] is None
    assert not (tmp_path / "faiss.index").exists()

    loaded = SessionVectorStore.load_from_dir(tmp_path)
    assert loaded.chunk_count == 3
    assert loaded.has_bm25 is True
    assert loaded.has_vector is False

    # BM25 search must return the same top result as the original store.
    original_hit = store.search_bm25("林冲", top_k=1)
    loaded_hit = loaded.search_bm25("林冲", top_k=1)
    assert len(loaded_hit) == 1
    assert loaded_hit[0][0].index == original_hit[0][0].index
    assert loaded_hit[0][1] == pytest.approx(original_hit[0][1], rel=1e-6)


def test_save_load_empty_chunks_roundtrip(
    tmp_path: Path, no_provider: None
) -> None:
    store = SessionVectorStore([], enable_vector=False)
    store.save_to_dir(tmp_path)

    loaded = SessionVectorStore.load_from_dir(tmp_path)
    assert loaded.chunk_count == 0
    assert loaded.has_vector is False
    assert loaded.search_bm25("anything") == []
    assert loaded.search("anything") == []


# ---------------------------------------------------------------------------
# Hybrid roundtrip (BM25 + FAISS)
# ---------------------------------------------------------------------------


def test_save_load_hybrid_roundtrip_preserves_vector_search(
    tmp_path: Path,
    chunks: list[ChunkResult],
    stub_provider: _StubProvider,
) -> None:
    store = SessionVectorStore(chunks, enable_vector=True)
    assert store.has_vector is True

    original_hits = store.search_vector("武松 打虎", top_k=3)
    assert original_hits, "sanity: stub provider should yield at least one hit"

    store.save_to_dir(tmp_path)

    manifest = _manifest(tmp_path)
    assert manifest["has_vector"] is True
    assert manifest["embedding_provider"] == "stub/embed-v1"
    assert manifest["embedding_dim"] == 4
    assert (tmp_path / "faiss.index").is_file()

    loaded = SessionVectorStore.load_from_dir(tmp_path)
    assert loaded.has_vector is True
    assert loaded.chunk_count == 3

    loaded_hits = loaded.search_vector("武松 打虎", top_k=3)
    assert [h[0].index for h in loaded_hits] == [
        h[0].index for h in original_hits
    ]
    for orig, new in zip(original_hits, loaded_hits):
        assert new[1] == pytest.approx(orig[1], rel=1e-5)


def test_resave_without_vector_removes_stale_faiss_file(
    tmp_path: Path,
    chunks: list[ChunkResult],
    stub_provider: _StubProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store_with = SessionVectorStore(chunks, enable_vector=True)
    store_with.save_to_dir(tmp_path)
    assert (tmp_path / "faiss.index").exists()

    # Now resave a store without vector (BM25-only) into the same directory.
    monkeypatch.setattr(vs_module, "_provider", None)
    store_without = SessionVectorStore(chunks, enable_vector=False)
    store_without.save_to_dir(tmp_path)

    assert not (tmp_path / "faiss.index").exists()
    manifest = _manifest(tmp_path)
    assert manifest["has_vector"] is False


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_load_missing_manifest_raises(tmp_path: Path) -> None:
    with pytest.raises(VectorStoreLoadError, match="manifest.json missing"):
        SessionVectorStore.load_from_dir(tmp_path)


def test_load_corrupted_manifest_raises(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text("{ not valid json", encoding="utf-8")
    with pytest.raises(VectorStoreLoadError, match="unreadable"):
        SessionVectorStore.load_from_dir(tmp_path)


def test_load_unsupported_manifest_version_raises(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(
        json.dumps({"version": 999, "chunk_count": 0, "has_vector": False}),
        encoding="utf-8",
    )
    with pytest.raises(VectorStoreLoadError, match="unsupported manifest version"):
        SessionVectorStore.load_from_dir(tmp_path)


def test_load_missing_chunks_file_raises(
    tmp_path: Path, chunks: list[ChunkResult], no_provider: None
) -> None:
    store = SessionVectorStore(chunks, enable_vector=False)
    store.save_to_dir(tmp_path)
    (tmp_path / "chunks.json").unlink()
    with pytest.raises(VectorStoreLoadError, match="chunks.json missing"):
        SessionVectorStore.load_from_dir(tmp_path)


def test_load_missing_bm25_file_raises(
    tmp_path: Path, chunks: list[ChunkResult], no_provider: None
) -> None:
    store = SessionVectorStore(chunks, enable_vector=False)
    store.save_to_dir(tmp_path)
    (tmp_path / "bm25.pkl").unlink()
    with pytest.raises(VectorStoreLoadError, match="bm25.pkl missing"):
        SessionVectorStore.load_from_dir(tmp_path)


def test_load_missing_faiss_when_manifest_requires_raises(
    tmp_path: Path,
    chunks: list[ChunkResult],
    stub_provider: _StubProvider,
) -> None:
    store = SessionVectorStore(chunks, enable_vector=True)
    store.save_to_dir(tmp_path)
    (tmp_path / "faiss.index").unlink()
    with pytest.raises(VectorStoreLoadError, match="faiss.index missing"):
        SessionVectorStore.load_from_dir(tmp_path)


def test_load_provider_missing_raises_mismatch(
    tmp_path: Path,
    chunks: list[ChunkResult],
    stub_provider: _StubProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SessionVectorStore(chunks, enable_vector=True)
    store.save_to_dir(tmp_path)

    monkeypatch.setattr(vs_module, "_provider", None)
    with pytest.raises(VectorStoreProviderMismatch, match="none is configured"):
        SessionVectorStore.load_from_dir(tmp_path)


def test_load_provider_name_mismatch_raises(
    tmp_path: Path,
    chunks: list[ChunkResult],
    stub_provider: _StubProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SessionVectorStore(chunks, enable_vector=True)
    store.save_to_dir(tmp_path)

    monkeypatch.setattr(vs_module, "_provider", _StubProvider(name="other/v2"))
    with pytest.raises(VectorStoreProviderMismatch, match="stub/embed-v1.*other/v2"):
        SessionVectorStore.load_from_dir(tmp_path)


def test_load_bm25_pickle_corrupted_raises(
    tmp_path: Path, chunks: list[ChunkResult], no_provider: None
) -> None:
    store = SessionVectorStore(chunks, enable_vector=False)
    store.save_to_dir(tmp_path)
    (tmp_path / "bm25.pkl").write_bytes(b"not a valid pickle")
    with pytest.raises(VectorStoreLoadError, match="bm25.pkl failed to load"):
        SessionVectorStore.load_from_dir(tmp_path)


def test_load_chunks_schema_mismatch_raises(
    tmp_path: Path, chunks: list[ChunkResult], no_provider: None
) -> None:
    store = SessionVectorStore(chunks, enable_vector=False)
    store.save_to_dir(tmp_path)
    # Replace chunks.json with invalid ChunkResult payload.
    (tmp_path / "chunks.json").write_text(
        json.dumps({"chunks": [{"index": "not-an-int"}]}),
        encoding="utf-8",
    )
    with pytest.raises(VectorStoreLoadError, match="chunks.json failed"):
        SessionVectorStore.load_from_dir(tmp_path)


# ---------------------------------------------------------------------------
# Manifest structure contract
# ---------------------------------------------------------------------------


def test_manifest_includes_required_fields(
    tmp_path: Path, chunks: list[ChunkResult], no_provider: None
) -> None:
    SessionVectorStore(chunks, enable_vector=False).save_to_dir(tmp_path)
    manifest = _manifest(tmp_path)
    for key in ("version", "chunk_count", "has_vector",
                "embedding_provider", "embedding_dim"):
        assert key in manifest, f"manifest missing {key}"


def test_save_creates_missing_directory(
    tmp_path: Path, chunks: list[ChunkResult], no_provider: None
) -> None:
    target = tmp_path / "nested" / "subdir"
    SessionVectorStore(chunks, enable_vector=False).save_to_dir(target)
    assert (target / "manifest.json").is_file()
    assert (target / "chunks.json").is_file()
    assert (target / "bm25.pkl").is_file()


def test_save_produces_loadable_bm25_pickle(
    tmp_path: Path, chunks: list[ChunkResult], no_provider: None
) -> None:
    SessionVectorStore(chunks, enable_vector=False).save_to_dir(tmp_path)
    with (tmp_path / "bm25.pkl").open("rb") as fp:
        restored = pickle.load(fp)  # noqa: S301 — test-local trusted file
    # Either BM25Okapi or ``None`` (empty chunks) — both are valid shapes.
    assert restored is not None
