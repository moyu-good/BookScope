"""书鉴报告 / 跨文本对照报告路由冒烟测试。

不真调 LLM/章脉/渲染，全部打桩，只验证 HTML 路由能正常返回 200 且带
X-Report-Coverage——专门防「Response 没导入」这类运行时炸在报告端点。
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


def _stub_render(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agent_routes, "render_report", lambda _inp: "<html>ok</html>")


def test_book_report_structure_returns_html(
    client_and_store: tuple[TestClient, BookSessionStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_render(monkeypatch)
    monkeypatch.setattr(agent_routes, "_resolve_assembler", lambda _store, _sid: object())
    monkeypatch.setattr(
        agent_routes,
        "_long_context_inputs",
        lambda _a: ("全文", [{"chunk_id": "c0", "chapter": 1, "text": "原文"}]),
    )
    monkeypatch.setattr(
        agent_routes,
        "spine_build_progress",
        lambda **kw: {"built": 0, "total": 2, "built_chapters": [], "missing_chapters": [1, 2]},
    )
    monkeypatch.setattr(agent_routes, "peek_spine_cache", lambda **kw: None)
    monkeypatch.setattr(agent_routes, "_extract_book_meta", lambda _a: ("测试书", {}))
    monkeypatch.setattr(agent_routes, "build_structure_report", lambda _chunks, _meta: {})

    client, _store = client_and_store
    resp = client.post(
        "/api/agent/book/report",
        json={"book_session_id": "s1", "provider": "deepseek", "api_key": "k" * 12},
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("X-Report-Coverage") == "structure"
    assert "text/html" in resp.headers["content-type"]
    assert "<html>ok</html>" in resp.text


def test_cross_book_report_returns_html(
    client_and_store: tuple[TestClient, BookSessionStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_render(monkeypatch)
    monkeypatch.setattr(agent_routes, "_resolve_assembler", lambda _store, _sid: object())
    monkeypatch.setattr(
        agent_routes,
        "_long_context_inputs",
        lambda _a: ("全文", [{"chunk_id": "c0", "chapter": 1, "text": "原文"}]),
    )
    monkeypatch.setattr(
        agent_routes,
        "spine_build_progress",
        lambda **kw: {"built": 2, "total": 2, "built_chapters": [1, 2], "missing_chapters": []},
    )
    monkeypatch.setattr(agent_routes, "get_or_build_spine", lambda **kw: [{"chapter": 1, "events": ["事件"], "claims": ["主张"]}])
    monkeypatch.setattr(agent_routes, "_extract_book_meta", lambda _a: ("测试书", {}))

    def fake_perspective(*, spine, book_title, slug, llm_client, model):  # type: ignore[no-untyped-def]
        return {"title": book_title, "slug": slug, "summary": "主旨", "stance": "实证", "claims": []}

    monkeypatch.setattr(agent_routes, "build_book_perspective", fake_perspective)
    monkeypatch.setattr(
        agent_routes,
        "cross_book_reason",
        lambda **kw: {"nodes": [], "edges": [], "concept_evolution": [], "disagreements": [], "narrative": ""},
    )
    monkeypatch.setattr(agent_routes, "build_cross_book_report_input", lambda **kw: {})
    monkeypatch.setattr(agent_routes, "build_llm_client_from_params", lambda **_k: object())

    client, _store = client_and_store
    resp = client.post(
        "/api/agent/cross-book/report",
        json={"book_session_ids": ["s1", "s2"], "provider": "deepseek", "api_key": "k" * 12},
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("X-Report-Coverage") == "full"
    assert "text/html" in resp.headers["content-type"]
    assert "<html>ok</html>" in resp.text


def test_cross_book_data_returns_json(
    client_and_store: tuple[TestClient, BookSessionStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """JSON 工作台端点：直接复用 _cross_book_payload，返回结构化数据。"""
    monkeypatch.setattr(
        agent_routes,
        "_cross_book_payload",
        lambda _request, _store: (
            [{"title": "甲", "slug": "a", "stance": "实证", "summary": "主旨", "claims": []}],
            {"nodes": [], "edges": [], "concept_evolution": [], "disagreements": [], "narrative": ""},
            "甲",
        ),
    )
    client, _store = client_and_store
    resp = client.post(
        "/api/agent/cross-book/data",
        json={"book_session_ids": ["s1", "s2"], "provider": "deepseek", "api_key": "k" * 12},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["titles"] == "甲"
    assert body["perspectives"][0]["title"] == "甲"
    assert body["reason"]["edges"] == []
