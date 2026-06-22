"""POST /api/agent/chapter-ask 端到端测试（按章问答 / 本章导读）。

只测端点自身的逻辑——按章过滤 chunk、调 run_long_context、拼响应——不真调 LLM：
``_long_context_inputs`` / ``run_long_context`` / ``build_llm_client_from_params`` 都打桩。
覆盖:成功路(只喂本章原文)、该章无原文(scanned=false 不报错)、缺 session(404)。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import bookscope.api.routes.agent as agent_routes
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


@pytest.fixture(autouse=True)
def _reset_store() -> Iterator[None]:
    reset_book_session_store_for_tests()
    yield
    reset_book_session_store_for_tests()


@pytest.fixture()
def client_and_store(
    tmp_path: Path,
) -> Iterator[tuple[TestClient, BookSessionStore]]:
    app = create_app()
    storage = JSONFileSessionStorage(root=tmp_path / "sessions")
    store = BookSessionStore(storage=storage)
    app.dependency_overrides[dep_get_book_session_store] = lambda: store
    with TestClient(app) as client:
        yield client, store


def _register(store: BookSessionStore, sid: str) -> None:
    book = BookText(
        title="测试书",
        raw_text="第一章 开端\n甲乙。\n第二章 发展\n丙丁。",
        language="zh",
    )
    chunks = [
        ChunkResult(index=0, text="甲乙。", chapter=1),
        ChunkResult(index=1, text="丙丁。", chapter=2),
    ]
    kg = BookKnowledgeGraph(
        book_title="测试书",
        language="zh",
        characters=[CharacterProfile(name="甲", key_chapter_indices=[1])],
    )
    store.register(
        sid,
        R0BookAssembler(
            book_text=book,
            chunks=chunks,
            knowledge_graph=kg,
            session_vector_store=None,
        ),
    )


_BODY = {"provider": "deepseek", "api_key": "k" * 12}


def test_chapter_ask_success_scopes_to_chapter(
    client_and_store: tuple[TestClient, BookSessionStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """成功路:只把目标章的 chunk 拼成 full_text 喂给 run_long_context,回 answer+citations。"""
    client, store = client_and_store
    _register(store, "s1")

    # 两章 chunk(章号已填);端点应只取 chapter==1 的那条
    monkeypatch.setattr(
        agent_routes, "_long_context_inputs",
        lambda _a: ("整本", [
            {"chunk_id": "c0", "chapter": 1, "text": "第一章的原文。"},
            {"chunk_id": "c1", "chapter": 2, "text": "第二章的原文。"},
        ]),
    )
    monkeypatch.setattr(agent_routes, "build_llm_client_from_params", lambda **_k: object())
    captured: dict = {}

    def _fake_lc(question, *, full_text, chunks, **_kw):  # type: ignore[no-untyped-def]
        captured["question"] = question
        captured["full_text"] = full_text
        captured["chunks"] = chunks
        return SimpleNamespace(
            answer="第一章讲了甲乙登场。",
            citations=[{"chapter": 1, "snippet": "第一章的原文。", "verified": True}],
            trace=SimpleNamespace(),
        )

    monkeypatch.setattr(agent_routes, "run_long_context", _fake_lc)

    resp = client.post(
        "/api/agent/chapter-ask",
        json={**_BODY, "book_session_id": "s1", "chapter": 1, "question": "这章谁登场？"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["chapter"] == 1
    assert body["scanned"] is True
    assert body["answer"] == "第一章讲了甲乙登场。"
    assert body["citations"][0]["chapter"] == 1
    # 关键:只喂了第一章原文(不含第二章)
    assert captured["full_text"] == "第一章的原文。"
    assert all(c["chapter"] == 1 for c in captured["chunks"])
    assert captured["question"] == "这章谁登场？"


def test_chapter_ask_blank_question_uses_digest_preset(
    client_and_store: tuple[TestClient, BookSessionStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """question 留空 = 本章导读:用预设问。"""
    client, store = client_and_store
    _register(store, "s1")
    monkeypatch.setattr(
        agent_routes, "_long_context_inputs",
        lambda _a: ("整本", [{"chunk_id": "c0", "chapter": 1, "text": "第一章的原文。"}]),
    )
    monkeypatch.setattr(agent_routes, "build_llm_client_from_params", lambda **_k: object())
    seen: dict = {}

    def _fake_lc(question, **_kw):  # type: ignore[no-untyped-def]
        seen["question"] = question
        return SimpleNamespace(answer="导读。", citations=[], trace=SimpleNamespace())

    monkeypatch.setattr(agent_routes, "run_long_context", _fake_lc)
    resp = client.post(
        "/api/agent/chapter-ask",
        json={**_BODY, "book_session_id": "s1", "chapter": 1, "question": "  "},
    )
    assert resp.status_code == 200, resp.text
    assert "这一章主要发生了什么" in seen["question"]


def test_chapter_ask_no_text_in_chapter_returns_scanned_false(
    client_and_store: tuple[TestClient, BookSessionStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """目标章没有可识别原文 → scanned=false,不报错、不调 LLM。"""
    client, store = client_and_store
    _register(store, "s1")
    monkeypatch.setattr(
        agent_routes, "_long_context_inputs",
        lambda _a: ("整本", [{"chunk_id": "c0", "chapter": 1, "text": "只有第一章。"}]),
    )

    def _boom(*_a, **_k):  # run_long_context 不该被调到
        raise AssertionError("run_long_context should not be called when chapter has no text")

    monkeypatch.setattr(agent_routes, "run_long_context", _boom)
    resp = client.post(
        "/api/agent/chapter-ask",
        json={**_BODY, "book_session_id": "s1", "chapter": 9},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scanned"] is False
    assert body["answer"] == ""
    assert body["citations"] == []


def test_chapter_ask_missing_session_returns_404(
    client_and_store: tuple[TestClient, BookSessionStore],
) -> None:
    """session 不存在 → 404 envelope。"""
    client, _ = client_and_store
    resp = client.post(
        "/api/agent/chapter-ask",
        json={**_BODY, "book_session_id": "nope", "chapter": 1},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_type"] == "BookSessionNotFound"
