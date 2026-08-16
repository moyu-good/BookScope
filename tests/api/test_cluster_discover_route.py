"""POST /api/agent/cluster/discover 路由测试。

不真调 LLM/章脉：``_resolve_assembler`` / ``_long_context_inputs`` /
``spine_build_progress`` / ``peek_spine_cache`` / ``build_book_perspective`` /
``cross_book_reason`` / ``build_llm_client_from_params`` 全部打桩。
验证：整组全就绪 → 200 HTML + 聚合后的关系网；有书未就绪 → 409 + 每本进度。
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


def _stub_full_ready(
    monkeypatch: pytest.MonkeyPatch,
    *,
    built: int = 2,
    total: int = 2,
) -> None:
    """把簇发现依赖全部打桩成'两本就绪 + 一对关系'。"""
    monkeypatch.setattr(agent_routes, "_resolve_assembler", lambda _store, _sid: object())
    monkeypatch.setattr(
        agent_routes,
        "_long_context_inputs",
        lambda _a: ("全文", [{"chunk_id": "c0", "chapter": 1, "text": "原文"}]),
    )
    monkeypatch.setattr(
        agent_routes,
        "spine_build_progress",
        lambda **kw: {"built": built, "total": total, "built_chapters": [], "missing_chapters": []},
    )
    monkeypatch.setattr(
        agent_routes,
        "peek_spine_cache",
        lambda **kw: [{"chapter": 1, "events": ["事件"], "claims": ["主张"]}],
    )
    monkeypatch.setattr(
        agent_routes,
        "build_llm_client_from_params",
        lambda **_k: object(),
    )

    def fake_perspective(*, spine, book_title, slug, llm_client, model):  # type: ignore[no-untyped-def]
        return {
            "title": book_title,
            "slug": slug,
            "summary": "主旨",
            "stance": "实证",
            "claims": [{"claim": "主张", "chapter": 1, "kind": "方法"}],
        }

    monkeypatch.setattr(agent_routes, "build_book_perspective", fake_perspective)

    def fake_reason(*, perspectives, llm_client, model):  # type: ignore[no-untyped-def]
        return {
            "nodes": [
                {"slug": p["slug"], "label": p["title"], "stance": p["stance"]}
                for p in perspectives
            ],
            "edges": [
                {"from": perspectives[0]["slug"], "to": perspectives[1]["slug"], "relation": "继承", "rationale": "锚到主张"},
            ],
            "concept_evolution": [{"concept": "法治", "stages": [{"paper": perspectives[0]["slug"], "stage": "提出", "claim": "主张", "evidence": "锚"}]}],
            "disagreements": [{"question": "政府角色", "sides": [{"paper": perspectives[0]["slug"], "stance": "小政府", "evidence": "锚"}]}],
            "narrative": "两本都重视法治。",
        }

    monkeypatch.setattr(agent_routes, "cross_book_reason", fake_reason)


def test_cluster_discover_full_ready_returns_html(
    client_and_store: tuple[TestClient, BookSessionStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_full_ready(monkeypatch)
    client, _store = client_and_store
    resp = client.post(
        "/api/agent/cluster/discover",
        json={
            "book_session_ids": ["s1", "s2"],
            "cluster_name": "政治学组",
            "provider": "deepseek",
            "api_key": "k" * 12,
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("X-Report-Coverage") == "full"
    assert "text/html" in resp.headers["content-type"]
    body = resp.text
    assert "簇关系网" in body
    assert "继承" in body
    assert "法治" in body
    assert "政府角色" in body


def test_cluster_discover_partial_ready_returns_409(
    client_and_store: tuple[TestClient, BookSessionStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_full_ready(monkeypatch, built=1, total=2)
    client, _store = client_and_store
    resp = client.post(
        "/api/agent/cluster/discover",
        json={
            "book_session_ids": ["s1", "s2"],
            "cluster_name": "政治学组",
            "provider": "deepseek",
            "api_key": "k" * 12,
        },
    )
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["error_type"] == "SpineNotReady"
    assert len(detail["progress"]) == 2
