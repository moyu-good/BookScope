"""genre 存储 + 懒检测 + /api/sessions 暴露的端到端测试（#10）。

覆盖：
  - set_genre 写回 metadata.json（只动 genre 字段）
  - ensure_genre 首次跑检测 + 缓存 + 写回；第二次直接命中不再调 LLM
  - ensure_genre 从已落盘的 metadata.json 读 genre（跨实例/重启语义）
  - /api/sessions 把 genre 带出来（已检测 → 有值；未检测 → 空串）
  - re-save 不冲掉已检测的 genre

不调真 LLM——通过 monkeypatch detect_genre 注入假题材。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bookscope.agent.backends.r0_assembler import R0BookAssembler
from bookscope.api import create_app
from bookscope.api.book_sessions import BookSessionStore
from bookscope.api.dependencies import (
    get_book_session_store as dep_get_book_session_store,
)
from bookscope.api.dependencies import reset_book_session_store_for_tests
from bookscope.api.session_storage import JSONFileSessionStorage
from bookscope.models.schemas import BookKnowledgeGraph, BookText, ChunkResult


@pytest.fixture(autouse=True)
def _reset_store_between_tests() -> Iterator[None]:
    # L3 book 预热缓存是进程级且按 session_id 做 key——测试间复用同一 id 会串味，
    # 每个测试前后清干净（同 _genre_cache 挂在 assembler 上的语义）。
    from bookscope.agent._internal.book_cache import clear_all

    reset_book_session_store_for_tests()
    clear_all()
    yield
    clear_all()
    reset_book_session_store_for_tests()


def _build_assembler() -> R0BookAssembler:
    book_text = BookText(
        title="制内市场",
        raw_text="第一章 导论\n制内市场是核心机制。\n第二章 机制\n继续论证。",
        language="zh",
    )
    chunks = [
        ChunkResult(index=0, text="第一章 导论 制内市场是核心机制。", chapter=1),
        ChunkResult(index=1, text="第二章 机制 继续论证。", chapter=2),
    ]
    kg = BookKnowledgeGraph(book_title="制内市场", language="zh", characters=[])
    return R0BookAssembler(
        book_text=book_text, chunks=chunks, knowledge_graph=kg,
        session_vector_store=None,
    )


class _FakeClient:
    """ensure_genre 不直接用 client（detect_genre 被 patch），给个占位。"""


def _store(tmp_path: Path) -> BookSessionStore:
    storage = JSONFileSessionStorage(root=tmp_path / "sessions")
    return BookSessionStore(storage=storage)


# ---------------------------------------------------------------------------
# set_genre 写回
# ---------------------------------------------------------------------------


def test_set_genre_writes_only_genre_field(tmp_path: Path) -> None:
    storage = JSONFileSessionStorage(root=tmp_path / "sessions")
    storage.save("s1", _build_assembler())
    storage.set_genre("s1", "理论")

    meta = storage.read_metadata("s1")
    assert meta["genre"] == "理论"
    # 其它字段没被冲掉
    assert meta["book_title"] == "制内市场"
    assert meta["created_at"]


def test_set_genre_on_missing_session_is_silent(tmp_path: Path) -> None:
    storage = JSONFileSessionStorage(root=tmp_path / "sessions")
    # 不存在的 session，set_genre 静默返回不抛
    storage.set_genre("nope", "理论")


# ---------------------------------------------------------------------------
# ensure_genre 懒检测 + 缓存
# ---------------------------------------------------------------------------


def test_ensure_genre_detects_caches_and_persists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    store.register("s1", _build_assembler())

    calls = {"n": 0}

    def _fake_detect(**_k):  # noqa: ANN003
        calls["n"] += 1
        return "理论"

    monkeypatch.setattr(
        "bookscope.agent.genre_detect.detect_genre", _fake_detect
    )

    g1 = store.ensure_genre("s1", llm_client=_FakeClient(), model="m")
    assert g1 == "理论"
    assert calls["n"] == 1
    # 写回了 storage
    assert store._storage.read_metadata("s1")["genre"] == "理论"  # noqa: SLF001

    # 第二次：内存命中，不再调 detect
    g2 = store.ensure_genre("s1", llm_client=_FakeClient(), model="m")
    assert g2 == "理论"
    assert calls["n"] == 1


def test_ensure_genre_reads_persisted_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 模拟"重启"：先落盘 genre，再用新 store 实例读——应从 metadata.json 拿到，不跑检测。
    storage = JSONFileSessionStorage(root=tmp_path / "sessions")
    storage.save("s1", _build_assembler())
    storage.set_genre("s1", "公文")

    fresh_store = BookSessionStore(storage=storage)

    def _boom(**_k):  # noqa: ANN003
        raise AssertionError("已落盘 genre，不该再跑检测")

    monkeypatch.setattr("bookscope.agent.genre_detect.detect_genre", _boom)

    g = fresh_store.ensure_genre("s1", llm_client=_FakeClient(), model="m")
    assert g == "公文"


def test_ensure_genre_missing_session_returns_empty(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.ensure_genre("nope", llm_client=_FakeClient(), model="m") == ""


# ---------------------------------------------------------------------------
# re-save 不冲掉已检测的 genre
# ---------------------------------------------------------------------------


def test_resave_preserves_existing_genre(tmp_path: Path) -> None:
    storage = JSONFileSessionStorage(root=tmp_path / "sessions")
    storage.save("s1", _build_assembler())
    storage.set_genre("s1", "理论")
    # 重新 save（如重传同一本）——genre 应被复用，不被冲成空
    storage.save("s1", _build_assembler())
    assert storage.read_metadata("s1")["genre"] == "理论"


# ---------------------------------------------------------------------------
# /api/sessions 暴露 genre
# ---------------------------------------------------------------------------


def test_sessions_list_carries_genre(tmp_path: Path) -> None:
    app = create_app()
    storage = JSONFileSessionStorage(root=tmp_path / "sessions")
    store = BookSessionStore(storage=storage)
    app.dependency_overrides[dep_get_book_session_store] = lambda: store

    with TestClient(app) as client:
        store.register("s1", _build_assembler())
        # 未检测：genre 为空串
        body = client.get("/api/sessions").json()
        assert body["sessions"][0]["genre"] == ""

        # 检测后落盘：genre 带出来
        storage.set_genre("s1", "理论")
        body2 = client.get("/api/sessions").json()
        assert body2["sessions"][0]["genre"] == "理论"

        # 单个 session 端点也带
        one = client.get("/api/sessions/s1").json()
        assert one["genre"] == "理论"
