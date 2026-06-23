"""POST /api/agent/spine-evidence(ADR-010 出路 B 的"点开现取")—— 端点测试,不调 LLM。

章脉章级锚视图的边/事件点开时调本端点,从那一章原文现找支撑句。纯检索,验:关系对两名命中、
事件 bigram 命中、本章没有 → found=False、章号不存在 → 空不报错。
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
from bookscope.models.schemas import (
    BookKnowledgeGraph,
    BookText,
    CharacterProfile,
    ChunkResult,
)

_SID = "sess-spine-ev"


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    reset_book_session_store_for_tests()
    yield
    reset_book_session_store_for_tests()


@pytest.fixture()
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app()
    store = BookSessionStore(storage=JSONFileSessionStorage(root=tmp_path / "s"))
    # 章 1 原文带可检索内容,好让取证命中
    raw = "第一章 桃园\n刘备、关羽、张飞在桃园结义。\n第二章 讨董\n曹操起兵讨董卓。"
    book = BookText(title="三国测试", raw_text=raw, language="zh")
    chunks = [
        ChunkResult(index=0, text="刘备、关羽、张飞在桃园结义。", chapter=1),
        ChunkResult(index=1, text="曹操起兵讨董卓。", chapter=2),
    ]
    kg = BookKnowledgeGraph(
        book_title="三国测试", language="zh",
        characters=[CharacterProfile(name="刘备", key_chapter_indices=[1])],
    )
    store.register(_SID, R0BookAssembler(
        book_text=book, chunks=chunks, knowledge_graph=kg, session_vector_store=None,
    ))
    app.dependency_overrides[dep_get_book_session_store] = lambda: store
    with TestClient(app) as c:
        yield c


def _post(client: TestClient, **body) -> dict:  # noqa: ANN003
    resp = client.post("/api/agent/spine-evidence", json={"book_session_id": _SID, **body})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_pair_evidence_found(client: TestClient) -> None:
    out = _post(client, chapter=1, kind="pair", a="刘备", b="关羽")
    assert out["found"] is True
    assert "刘备" in out["evidence"] and "关羽" in out["evidence"]


def test_event_evidence_found(client: TestClient) -> None:
    out = _post(client, chapter=2, kind="event", event="曹操起兵讨伐董卓")
    assert out["found"] is True
    assert "曹操" in out["evidence"]


def test_pair_not_in_chapter_returns_not_found(client: TestClient) -> None:
    out = _post(client, chapter=1, kind="pair", a="孙权", b="周瑜")
    assert out["found"] is False
    assert out["evidence"] == ""


def test_unknown_chapter_returns_empty(client: TestClient) -> None:
    out = _post(client, chapter=999, kind="pair", a="刘备", b="关羽")
    assert out["found"] is False
    assert out["chapter"] == 999


def test_unknown_session_404(client: TestClient) -> None:
    resp = client.post(
        "/api/agent/spine-evidence",
        json={"book_session_id": "nope", "chapter": 1, "kind": "pair", "a": "x", "b": "y"},
    )
    assert resp.status_code == 404
