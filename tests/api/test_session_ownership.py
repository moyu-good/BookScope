"""文档归属 / 数据隔离 e2e + 单测(1.6.2 Phase 1c)。

命门两条:
1. **local 模式所有 books/sessions 端点行为不变**——不要登录、列全部、谁都能读删(零回归)。
2. **hosted 模式按 owner 隔离**——只列 / 只读 / 只删自己的;没登录 401;别人的当不存在(404)。

复用 test_routes_sessions 的手工装配,不调真 LLM、不走 ingest。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bookscope.agent.backends.r0_assembler import R0BookAssembler
from bookscope.api import auth, create_app, deployment
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


def _build_assembler(book_title: str, language: str = "zh") -> R0BookAssembler:
    book_text = BookText(
        title=book_title,
        raw_text="第一章 开端\n测试文本。\n第二章 发展\n继续。",
        language=language,
    )
    chunks = [
        ChunkResult(index=0, text="第一章 开端 测试文本。", chapter=1),
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


def _hdr(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    reset_book_session_store_for_tests()
    deployment._reset_accounts_store()
    yield
    reset_book_session_store_for_tests()
    deployment._reset_accounts_store()


@pytest.fixture
def hosted(
    monkeypatch, tmp_path: Path
) -> Iterator[tuple[TestClient, BookSessionStore]]:
    monkeypatch.setenv("BOOKSCOPE_DEPLOYMENT_MODE", "hosted")
    monkeypatch.setenv("BOOKSCOPE_AUTH_SECRET", "test-secret")
    monkeypatch.setenv("BOOKSCOPE_ACCOUNTS_DB", str(tmp_path / "acc.db"))
    monkeypatch.setenv("BOOKSCOPE_RATELIMIT_DISABLED", "1")
    deployment._reset_accounts_store()
    app = create_app()
    store = BookSessionStore(storage=JSONFileSessionStorage(root=tmp_path / "sessions"))
    app.dependency_overrides[dep_get_book_session_store] = lambda: store
    with TestClient(app) as client:
        yield client, store


# ---- hosted 隔离(命门) ----

def test_hosted_isolation_list_get_delete(hosted):
    client, store = hosted
    acc = deployment.get_accounts_store()
    a = acc.create_user(email="a@x.com", password="pw123456")
    b = acc.create_user(email="b@x.com", password="pw123456")
    store.register("a-sess", _build_assembler("A 的书"))
    store.register("b-sess", _build_assembler("B 的书"))
    acc.add_document(owner_user_id=a.id, doc_id="a-sess", title="A 的书")
    acc.add_document(owner_user_id=b.id, doc_id="b-sess", title="B 的书")
    ta, tb = auth.issue_token(a.id), auth.issue_token(b.id)

    # 各自只列到自己的
    ra = client.get("/api/sessions", headers=_hdr(ta)).json()
    assert [s["session_id"] for s in ra["sessions"]] == ["a-sess"]
    rb = client.get("/api/sessions", headers=_hdr(tb)).json()
    assert [s["session_id"] for s in rb["sessions"]] == ["b-sess"]

    # A 读 B 的 → 404(当不存在);读自己的 → 200
    assert client.get("/api/sessions/b-sess", headers=_hdr(ta)).status_code == 404
    assert client.get("/api/sessions/a-sess", headers=_hdr(ta)).status_code == 200
    # 目录 / 章节同样隔离
    assert client.get("/api/sessions/b-sess/toc", headers=_hdr(ta)).status_code == 404
    assert (
        client.get("/api/sessions/b-sess/chapters/1", headers=_hdr(ta)).status_code
        == 404
    )

    # A 删 B 的 → 404(删不动别人的)
    assert client.delete("/api/sessions/b-sess", headers=_hdr(ta)).status_code == 404
    assert acc.owns(owner_user_id=b.id, doc_id="b-sess") is True  # 还在
    # A 删自己的 → 204,归属记录连带没了
    assert client.delete("/api/sessions/a-sess", headers=_hdr(ta)).status_code == 204
    assert acc.owns(owner_user_id=a.id, doc_id="a-sess") is False
    assert client.get("/api/sessions", headers=_hdr(ta)).json()["sessions"] == []


def test_hosted_requires_login(hosted):
    client, store = hosted
    store.register("x-sess", _build_assembler("某书"))
    # 没令牌 → 401(require_user 在 hosted 拦)
    assert client.get("/api/sessions").status_code == 401
    assert client.get("/api/sessions/x-sess").status_code == 401
    assert client.get("/api/sessions/x-sess/toc").status_code == 401
    assert client.delete("/api/sessions/x-sess").status_code == 401


def test_hosted_bad_token_401(hosted):
    client, _ = hosted
    assert client.get("/api/sessions", headers=_hdr("garbage")).status_code == 401


# ---- local 零回归 ----

def test_local_unchanged(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("BOOKSCOPE_DEPLOYMENT_MODE", raising=False)
    monkeypatch.setenv("BOOKSCOPE_RATELIMIT_DISABLED", "1")
    app = create_app()
    store = BookSessionStore(storage=JSONFileSessionStorage(root=tmp_path / "sessions"))
    app.dependency_overrides[dep_get_book_session_store] = lambda: store
    with TestClient(app) as client:
        store.register("s1", _build_assembler("书一"))
        store.register("s2", _build_assembler("书二"))
        # 无令牌也能列到全部、能读、能删——本地版逐字节不变
        body = client.get("/api/sessions").json()
        assert {s["session_id"] for s in body["sessions"]} == {"s1", "s2"}
        assert client.get("/api/sessions/s1").status_code == 200
        assert client.delete("/api/sessions/s2").status_code == 204


# ---- helper local 旁路单测 ----

def test_helpers_local_bypass(monkeypatch):
    monkeypatch.delenv("BOOKSCOPE_DEPLOYMENT_MODE", raising=False)
    assert deployment.owned_session_ids(None) is None  # 不过滤
    assert deployment.user_owns_session(None, "x") is True  # 恒放行
    # record / forget 在 local 是 no-op,不碰账号库、不抛
    deployment.record_ownership(None, "x", "t")
    deployment.forget_ownership(None, "x")
