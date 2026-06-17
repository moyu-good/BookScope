"""GET /api/sessions / GET /api/sessions/{id} / DELETE 路由端到端测试。

覆盖：

  - list 空 → 200 + ``{"sessions": []}``
  - list 单 session → 元数据完整
  - list 多 session（≥ 2）→ 按 session_id 排序
  - get 存在的 session → 200 + 完整字段
  - get 不存在 → 404 + envelope
  - delete 存在的 session → 204；后续 list 不再出现
  - delete 不存在 → 404 + envelope

测试用 ``TestClient`` + tmp_path 注入的 :class:`JSONFileSessionStorage`，
不调真 LLM，不走 ingest 流程；session 通过现成 :class:`BookText` /
:class:`ChunkResult` / :class:`BookKnowledgeGraph` 装配出
:class:`R0BookAssembler` 后直接 ``store.register(...)``——这样 metadata.json
会被 storage 真实写出，能验证 GET/list 的元数据回读路径。
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
from bookscope.api.dependencies import (
    reset_book_session_store_for_tests,
)
from bookscope.api.session_storage import JSONFileSessionStorage
from bookscope.models.schemas import (
    BookKnowledgeGraph,
    BookText,
    CharacterProfile,
    ChunkResult,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_store_between_tests() -> Iterator[None]:
    """每个测试前后把共享 BookSessionStore 重置干净。"""
    reset_book_session_store_for_tests()
    yield
    reset_book_session_store_for_tests()


@pytest.fixture()
def client_and_store(
    tmp_path: Path,
) -> Iterator[tuple[TestClient, BookSessionStore]]:
    """带 tmp_path JSONFileSessionStorage 的 TestClient + store 对。"""
    app = create_app()
    storage = JSONFileSessionStorage(root=tmp_path / "sessions")
    store = BookSessionStore(storage=storage)
    app.dependency_overrides[dep_get_book_session_store] = lambda: store

    with TestClient(app) as client:
        yield client, store


# ---------------------------------------------------------------------------
# Helpers：手工装配 R0BookAssembler 并注册到 store
# ---------------------------------------------------------------------------


def _build_assembler(book_title: str, language: str = "zh") -> R0BookAssembler:
    """造一个最小可注册的 :class:`R0BookAssembler`。

    chunks 给两个章节占位；KG 给一个空角色清单；vector_store 留 None
    （session_storage.save 会把 vector_index_dir 清掉，也是合法路径）。
    """
    book_text = BookText(
        title=book_title,
        raw_text="第一章 开端\n这是测试文本。\n第二章 发展\n继续。",
        language=language,
    )
    chunks = [
        ChunkResult(index=0, text="第一章 开端 这是测试文本。", chapter=1),
        ChunkResult(index=1, text="第二章 发展 继续。", chapter=2),
    ]
    kg = BookKnowledgeGraph(
        book_title=book_title,
        language=language,
        characters=[CharacterProfile(name="主角", key_chapter_indices=[1])],
    )
    return R0BookAssembler(
        book_text=book_text,
        chunks=chunks,
        knowledge_graph=kg,
        session_vector_store=None,
    )


def _register_session(
    store: BookSessionStore,
    session_id: str,
    book_title: str,
    language: str = "zh",
) -> None:
    """注册一个测试 session 到 store（同时写 storage 落盘 metadata.json）。"""
    store.register(session_id, _build_assembler(book_title, language))


# ---------------------------------------------------------------------------
# GET /api/sessions
# ---------------------------------------------------------------------------


def test_list_sessions_empty_returns_200(
    client_and_store: tuple[TestClient, BookSessionStore],
) -> None:
    """空 store 也返回 200，不是 404。"""
    client, _ = client_and_store
    resp = client.get("/api/sessions")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"sessions": []}


def test_list_sessions_single_session_returns_full_metadata(
    client_and_store: tuple[TestClient, BookSessionStore],
) -> None:
    """单个 session 的所有元数据字段都应填充。"""
    client, store = client_and_store
    _register_session(store, "sess-001", book_title="单本测试")

    resp = client.get("/api/sessions")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["sessions"], list)
    assert len(body["sessions"]) == 1

    item = body["sessions"][0]
    assert item["session_id"] == "sess-001"
    assert item["book_title"] == "单本测试"
    assert item["language"] == "zh"
    # storage 写入的 ISO-8601 戳；只验证非空，不绑死格式
    assert item["created_at"]
    assert item["last_accessed_at"]


def test_list_sessions_multiple_sessions_sorted(
    client_and_store: tuple[TestClient, BookSessionStore],
) -> None:
    """多个 session 应按 session_id 升序返回。"""
    client, store = client_and_store
    _register_session(store, "sess-c", book_title="书 C")
    _register_session(store, "sess-a", book_title="书 A")
    _register_session(store, "sess-b", book_title="书 B")

    resp = client.get("/api/sessions")
    assert resp.status_code == 200
    ids = [s["session_id"] for s in resp.json()["sessions"]]
    assert ids == ["sess-a", "sess-b", "sess-c"]


# ---------------------------------------------------------------------------
# GET /api/sessions/{session_id}
# ---------------------------------------------------------------------------


def test_get_session_existing_returns_full_metadata(
    client_and_store: tuple[TestClient, BookSessionStore],
) -> None:
    """存在的 session 返回完整元数据 + 200。"""
    client, store = client_and_store
    _register_session(store, "abc123", book_title="详情测试", language="zh")

    resp = client.get("/api/sessions/abc123")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["session_id"] == "abc123"
    assert body["book_title"] == "详情测试"
    assert body["language"] == "zh"
    assert body["created_at"]
    assert body["last_accessed_at"]
    # 不暴露内部细节
    assert "chunks" not in body
    assert "vector_index" not in body
    assert "characters" not in body


def test_get_session_missing_returns_404_envelope(
    client_and_store: tuple[TestClient, BookSessionStore],
) -> None:
    """不存在的 session → 404 + envelope（与 agent 路由一致的格式）。"""
    client, _ = client_and_store
    resp = client.get("/api/sessions/does-not-exist")
    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert detail["error_type"] == "BookSessionNotFound"
    assert "does-not-exist" in detail["message"] or "not found" in detail["message"].lower()
    assert detail["details"]["session_id"] == "does-not-exist"


# ---------------------------------------------------------------------------
# DELETE /api/sessions/{session_id}
# ---------------------------------------------------------------------------


def test_delete_session_existing_returns_204_and_disappears(
    client_and_store: tuple[TestClient, BookSessionStore],
) -> None:
    """删除成功 → 204；后续 list 不再出现。"""
    client, store = client_and_store
    _register_session(store, "to-delete", book_title="待删除")
    _register_session(store, "to-keep", book_title="保留")

    resp = client.delete("/api/sessions/to-delete")
    assert resp.status_code == 204
    # 204 不应该有响应体
    assert resp.content == b""

    # store 内存 + storage 都已删
    assert not store.has("to-delete")
    # 另一条还在
    assert store.has("to-keep")

    # list 端点也对齐
    list_body = client.get("/api/sessions").json()
    ids = [s["session_id"] for s in list_body["sessions"]]
    assert "to-delete" not in ids
    assert "to-keep" in ids


def test_delete_session_missing_returns_404_envelope(
    client_and_store: tuple[TestClient, BookSessionStore],
) -> None:
    """删除不存在的 session → 404 + envelope（不是静默 204）。"""
    client, _ = client_and_store
    resp = client.delete("/api/sessions/never-existed")
    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert detail["error_type"] == "BookSessionNotFound"
    assert detail["details"]["session_id"] == "never-existed"
