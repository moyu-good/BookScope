"""题材门控端点测试（#14 detect-genre + #15 论说/叙事专属功能门控）。

不真调 LLM——``build_llm_client_from_params`` 给 ``object()`` 桩、``detect_genre`` 打桩
注入假题材、派生层（spine / cards）打桩。验：

  - POST /agent/detect-genre 把检测出的题材回出来 + 缺 session 404
  - 概念演进（论说必需）对小说退场（scanned=True + 空阶段），且**不**碰章脉派生（省一次推理）
  - 概念演进对理论书正常跑
  - 知识卡片（论说/工具书）对小说退场，且**不**碰生成层
  - 知识卡片对理论书正常跑

照 ``test_routes_redhead.py`` / ``test_genre_storage.py`` 的范式。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

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
from bookscope.models.schemas import BookKnowledgeGraph, BookText, ChunkResult

# BYOK 公共字段（api_key 至少 8 位过 min_length 校验）。
_BYOK = {"provider": "deepseek", "api_key": "k" * 12}


@pytest.fixture(autouse=True)
def _reset_store() -> Iterator[None]:
    from bookscope.agent._internal.book_cache import clear_all

    reset_book_session_store_for_tests()
    clear_all()
    yield
    clear_all()
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
    """注册一份小书（塞得进 long context，门控前的 _book_fits_long_context 通过）。"""
    book = BookText(
        title=f"书-{sid}",
        raw_text="第一章 导论\n核心机制是关键。\n第二章 展开\n继续。",
        language="zh",
    )
    chunks = [
        ChunkResult(index=0, text="第一章 导论 核心机制是关键。", chapter=1),
        ChunkResult(index=1, text="第二章 展开 继续。", chapter=2),
    ]
    kg = BookKnowledgeGraph(book_title=f"书-{sid}", language="zh", characters=[])
    store.register(
        sid,
        R0BookAssembler(
            book_text=book, chunks=chunks, knowledge_graph=kg,
            session_vector_store=None,
        ),
    )


def _patch_genre(monkeypatch: pytest.MonkeyPatch, genre: str) -> None:
    """打桩客户端 + 题材检测（ensure_genre 内部局部 import detect_genre，patch 源模块）。"""
    monkeypatch.setattr(
        agent_routes, "build_llm_client_from_params", lambda **_k: object()
    )
    monkeypatch.setattr(
        "bookscope.agent.genre_detect.detect_genre", lambda **_k: genre
    )


# ── #14 detect-genre 端点 ────────────────────────────────────────────────────


def test_detect_genre_returns_detected(
    client_and_store: tuple[TestClient, BookSessionStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, store = client_and_store
    _register(store, "s1")
    _patch_genre(monkeypatch, "小说")

    resp = client.post(
        "/api/agent/detect-genre", json={**_BYOK, "book_session_id": "s1"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["genre"] == "小说"
    assert body["book_session_id"] == "s1"


def test_detect_genre_missing_session_404(
    client_and_store: tuple[TestClient, BookSessionStore],
) -> None:
    client, _ = client_and_store
    resp = client.post(
        "/api/agent/detect-genre", json={**_BYOK, "book_session_id": "nope"}
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_type"] == "BookSessionNotFound"


# ── #15 概念演进（论说必需）题材门控 ─────────────────────────────────────────


def test_concept_evolution_retires_on_fiction(
    client_and_store: tuple[TestClient, BookSessionStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """小说上概念演进退场：scanned=True + 空阶段，且不碰章脉派生（省一次推理）。"""
    client, store = client_and_store
    _register(store, "s1")
    _patch_genre(monkeypatch, "小说")

    def _boom(**_k):  # noqa: ANN003 — 证明门控退场后不再走派生
        raise AssertionError("题材不对，不该建章脉")

    monkeypatch.setattr(agent_routes, "get_or_build_spine", _boom)

    resp = client.post(
        "/api/agent/concept-evolution",
        json={**_BYOK, "book_session_id": "s1", "concept": "市场"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scanned"] is True
    assert body["stages"] == []


def test_concept_evolution_runs_on_theory(
    client_and_store: tuple[TestClient, BookSessionStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """理论书上概念演进正常跑（门控不误伤）。"""
    client, store = client_and_store
    _register(store, "s1")
    _patch_genre(monkeypatch, "理论")
    monkeypatch.setattr(agent_routes, "get_or_build_spine", lambda **_k: {})
    monkeypatch.setattr(
        agent_routes,
        "concept_evolution_from_spine",
        lambda **_k: [{"stage": "导论提出", "chapter": 1, "verified": True}],
    )

    resp = client.post(
        "/api/agent/concept-evolution",
        json={**_BYOK, "book_session_id": "s1", "concept": "市场"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scanned"] is True
    assert len(body["stages"]) == 1


# ── #15 知识卡片（论说/工具书）题材门控 ──────────────────────────────────────


def test_study_cards_retires_on_fiction(
    client_and_store: tuple[TestClient, BookSessionStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """小说上知识卡片退场：scanned=True + 空卡片，且不碰生成层。"""
    client, store = client_and_store
    _register(store, "s1")
    _patch_genre(monkeypatch, "历史")  # 历史属叙事类，照样退场

    def _boom(**_k):  # noqa: ANN003
        raise AssertionError("题材不对，不该生成卡片")

    monkeypatch.setattr(agent_routes, "generate_study_cards", _boom)

    resp = client.post(
        "/api/agent/study-cards", json={**_BYOK, "book_session_id": "s1"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scanned"] is True
    assert body["cards"] == []


def test_study_cards_runs_on_theory(
    client_and_store: tuple[TestClient, BookSessionStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """理论书上知识卡片正常跑（门控不误伤）。"""
    client, store = client_and_store
    _register(store, "s1")
    _patch_genre(monkeypatch, "理论")
    monkeypatch.setattr(
        agent_routes,
        "generate_study_cards",
        lambda **_k: [{"point": "核心机制", "verified": True}],
    )

    resp = client.post(
        "/api/agent/study-cards", json={**_BYOK, "book_session_id": "s1"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scanned"] is True
    assert len(body["cards"]) == 1
