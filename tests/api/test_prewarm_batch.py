"""POST /api/agent/prewarm-spine/batch 路由测试。

不真调 LLM：``_build_prewarm_client`` / ``_start_prewarm_for_session`` 都打桩，
只验证批量端点把每本的启动结果正确分类（started/building/cached/failed）。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import bookscope.api.routes.agent as agent_routes
from bookscope.api import create_app
from bookscope.api.book_sessions import BookSessionStore
from bookscope.api.dependencies import (
    get_book_session_store as dep_get_book_session_store,
)
from bookscope.api.dependencies import reset_book_session_store_for_tests
from bookscope.api.session_storage import JSONFileSessionStorage


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


def test_batch_prewarm_classifies_statuses(
    client_and_store: tuple[TestClient, BookSessionStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _store = client_and_store
    monkeypatch.setattr(agent_routes, "_build_prewarm_client", lambda **_k: object())

    def fake_start(*, store, book_session_id, client, model):  # type: ignore[no-untyped-def]
        if book_session_id == "s1":
            return "started"
        if book_session_id == "s2":
            return "building"
        if book_session_id == "s3":
            return "cached"
        raise RuntimeError("boom")

    monkeypatch.setattr(agent_routes, "_start_prewarm_for_session", fake_start)

    resp = client.post(
        "/api/agent/prewarm-spine/batch",
        json={
            "book_session_ids": ["s1", "s2", "s3", "s4"],
            "provider": "deepseek",
            "api_key": "k" * 12,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["started"] == ["s1"]
    assert body["building"] == ["s2"]
    assert body["cached"] == ["s3"]
    assert body["failed"] == ["s4"]
    assert "s4" in body["errors"]
    assert body["errors"]["s4"] == "RuntimeError: boom"


def test_batch_prewarm_client_failure_returns_400(
    client_and_store: tuple[TestClient, BookSessionStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _store = client_and_store

    def boom(**_k):
        raise ImportError("sdk missing")

    monkeypatch.setattr(agent_routes, "build_llm_client_from_params", boom)
    resp = client.post(
        "/api/agent/prewarm-spine/batch",
        json={
            "book_session_ids": ["s1"],
            "provider": "deepseek",
            "api_key": "k" * 12,
        },
    )
    assert resp.status_code == 400, resp.text
    assert "ProviderSdkMissing" in resp.text
