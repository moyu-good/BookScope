"""POST /api/agent/redhead/* 四个红头文件端点的契约测试(1.6 Phase 1)。

只测端点自身的接线——resolve assembler、建文脉、多 session 收集、派生视图、拼响应——
不真调 LLM:``build_llm_client_from_params`` / ``get_or_build_doc_spine`` / 三个跨文件视图
函数 / ``cross_doc_relations_from_spines`` 全打桩。验请求→响应形状 + 多 session 收集 +
空态 + 缺 session 404 + SDK 缺失 400。

照 ``test_routes_chapter_ask.py`` 的范式:注册真 ``R0BookAssembler``(带 chunks),
monkeypatch 派生层。
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
    """注册一份「公文」session(一份 = 一个 book session,Phase 1 摄入最简)。"""
    book = BookText(
        title=f"公文-{sid}",
        raw_text="X发〔2024〕5号\n关于试点工作的通知\n第一条 应当于6月底前完成。",
        language="zh",
    )
    chunks = [ChunkResult(index=0, text="应当于6月底前完成。", chapter=1)]
    kg = BookKnowledgeGraph(
        book_title=f"公文-{sid}",
        language="zh",
        characters=[CharacterProfile(name="财政部", key_chapter_indices=[1])],
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


# BYOK 公共字段(api_key 至少 8 位过 min_length 校验)。
_BYOK = {"provider": "deepseek", "api_key": "k" * 12}

# 一份典型文脉桩(单文件解读 + 跨文件视图都从它派生)。
_FAKE_SPINE = {
    "schema_version": "v1",
    "head": [
        {"field": "发文字号", "value": "X发〔2024〕5号", "evidence": "X发〔2024〕5号",
         "verified": True, "match_score": 1.0},
        {"field": "文种", "value": "通知", "evidence": "通知", "verified": True,
         "match_score": 1.0},
    ],
    "clauses": [
        {"chapter": 1, "matter": "试点工作", "instruction_type": "硬要求", "actor": "财政部",
         "deadline": "6月底前", "basis_ref": "", "evidence": "应当于6月底前完成。",
         "verified": True, "match_score": 1.0},
    ],
}


def _stub_client_and_spine(monkeypatch: pytest.MonkeyPatch) -> None:
    """打桩 client 构建 + 文脉构建(不真调 LLM)。各端点共用。"""
    monkeypatch.setattr(
        agent_routes, "build_llm_client_from_params", lambda **_k: object()
    )
    monkeypatch.setattr(
        agent_routes,
        "get_or_build_doc_spine",
        lambda **_k: dict(_FAKE_SPINE),
    )


# ── 单文件解读 /agent/redhead/doc-structure ──────────────────────────────────


def test_doc_structure_success_returns_head_and_clauses(
    client_and_store: tuple[TestClient, BookSessionStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """成功路:返这份公文的文脉(head + clauses),scanned=true。"""
    client, store = client_and_store
    _register(store, "d1")
    _stub_client_and_spine(monkeypatch)

    resp = client.post(
        "/api/agent/redhead/doc-structure",
        json={**_BYOK, "book_session_id": "d1"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["book_session_id"] == "d1"
    assert body["scanned"] is True
    assert body["head"][0]["field"] == "发文字号"
    assert body["clauses"][0]["instruction_type"] == "硬要求"
    assert "input_tokens" in body["trace"]


def test_doc_structure_empty_spine_scanned_false(
    client_and_store: tuple[TestClient, BookSessionStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """头要素全留空 + 没条款 → scanned=false(读过但没抽到真东西)。"""
    client, store = client_and_store
    _register(store, "d1")
    monkeypatch.setattr(
        agent_routes, "build_llm_client_from_params", lambda **_k: object()
    )
    monkeypatch.setattr(
        agent_routes,
        "get_or_build_doc_spine",
        lambda **_k: {
            "schema_version": "v1",
            "head": [
                {"field": "发文字号", "value": "", "evidence": "", "verified": False,
                 "match_score": 0.0},
            ],
            "clauses": [],
        },
    )

    resp = client.post(
        "/api/agent/redhead/doc-structure",
        json={**_BYOK, "book_session_id": "d1"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scanned"] is False
    assert body["clauses"] == []


def test_doc_structure_missing_session_404(
    client_and_store: tuple[TestClient, BookSessionStore],
) -> None:
    """session 不存在 → 404 envelope。"""
    client, _ = client_and_store
    resp = client.post(
        "/api/agent/redhead/doc-structure",
        json={**_BYOK, "book_session_id": "nope"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_type"] == "BookSessionNotFound"


def test_doc_structure_sdk_missing_400(
    client_and_store: tuple[TestClient, BookSessionStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """provider SDK 缺失(build 抛 ImportError)→ 400 ProviderSdkMissing。"""
    client, store = client_and_store
    _register(store, "d1")

    def _raise_import(**_k):  # type: ignore[no-untyped-def]
        raise ImportError("openai SDK 没装")

    monkeypatch.setattr(agent_routes, "build_llm_client_from_params", _raise_import)

    resp = client.post(
        "/api/agent/redhead/doc-structure",
        json={**_BYOK, "book_session_id": "d1"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error_type"] == "ProviderSdkMissing"


# ── 依据链网 /agent/redhead/dependency-graph ─────────────────────────────────


def test_dependency_graph_collects_all_sessions_and_returns_graph(
    client_and_store: tuple[TestClient, BookSessionStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """多 session 都建文脉 → cross_doc → 整成星图;验收集了全部 session。"""
    client, store = client_and_store
    _register(store, "a1")
    _register(store, "a2")
    _stub_client_and_spine(monkeypatch)

    seen_spine_count: dict = {}

    def _fake_cross(*, doc_spines, **_k):  # type: ignore[no-untyped-def]
        seen_spine_count["n"] = len(doc_spines)
        return {"relations": [{"from_doc": "甲", "to_doc": "乙", "kind": "依据"}],
                "docs": []}

    monkeypatch.setattr(agent_routes, "cross_doc_relations_from_spines", _fake_cross)
    monkeypatch.setattr(
        agent_routes,
        "dependency_graph_from_cross_doc",
        lambda _c: {"nodes": [{"id": "甲", "kind": "文件"}],
                    "edges": [{"source": "甲", "target": "乙", "kind": "依据"}]},
    )

    resp = client.post(
        "/api/agent/redhead/dependency-graph",
        json={**_BYOK, "book_session_ids": ["a1", "a2"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert seen_spine_count["n"] == 2  # 两份 session 都建了文脉收进栈
    assert body["scanned"] is True
    assert body["nodes"][0]["id"] == "甲"
    assert body["edges"][0]["kind"] == "依据"


def test_dependency_graph_empty_state_scanned_false(
    client_and_store: tuple[TestClient, BookSessionStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """推不出关系(graph None)→ 空态 scanned=false,不报错。"""
    client, store = client_and_store
    _register(store, "a1")
    _stub_client_and_spine(monkeypatch)
    monkeypatch.setattr(
        agent_routes, "cross_doc_relations_from_spines", lambda **_k: None
    )
    monkeypatch.setattr(
        agent_routes, "dependency_graph_from_cross_doc", lambda _c: None
    )

    resp = client.post(
        "/api/agent/redhead/dependency-graph",
        json={**_BYOK, "book_session_ids": ["a1"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scanned"] is False
    assert body["nodes"] == []
    assert body["edges"] == []


def test_dependency_graph_one_missing_session_404(
    client_and_store: tuple[TestClient, BookSessionStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """卷宗里有一份 session 不存在 → 404(点名的文件必须都在,不静默跳过)。"""
    client, store = client_and_store
    _register(store, "a1")
    _stub_client_and_spine(monkeypatch)
    monkeypatch.setattr(
        agent_routes, "cross_doc_relations_from_spines", lambda **_k: None
    )
    monkeypatch.setattr(
        agent_routes, "dependency_graph_from_cross_doc", lambda _c: None
    )

    resp = client.post(
        "/api/agent/redhead/dependency-graph",
        json={**_BYOK, "book_session_ids": ["a1", "ghost"]},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_type"] == "BookSessionNotFound"


# ── 政策演变 /agent/redhead/policy-evolution ─────────────────────────────────


def test_policy_evolution_passes_topic_and_returns_stages(
    client_and_store: tuple[TestClient, BookSessionStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """成功路:topic 透传给派生函数,返 stages,scanned=true。"""
    client, store = client_and_store
    _register(store, "p1")
    _register(store, "p2")
    _stub_client_and_spine(monkeypatch)

    captured: dict = {}

    def _fake_policy(*, doc_spines, topic, **_k):  # type: ignore[no-untyped-def]
        captured["n"] = len(doc_spines)
        captured["topic"] = topic
        return [{"order": 1, "doc": "甲", "change": "确立试点", "snippet": "原文。",
                 "verified": True}]

    monkeypatch.setattr(agent_routes, "policy_evolution_from_spines", _fake_policy)

    resp = client.post(
        "/api/agent/redhead/policy-evolution",
        json={**_BYOK, "book_session_ids": ["p1", "p2"], "topic": "试点"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert captured["n"] == 2
    assert captured["topic"] == "试点"
    assert body["scanned"] is True
    assert body["stages"][0]["doc"] == "甲"


def test_policy_evolution_topic_optional_empty_state(
    client_and_store: tuple[TestClient, BookSessionStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """不带 topic + 派生返 None → scanned=false 空态;topic 透传为 None。"""
    client, store = client_and_store
    _register(store, "p1")
    _stub_client_and_spine(monkeypatch)
    captured: dict = {}

    def _fake_policy(*, topic, **_k):  # type: ignore[no-untyped-def]
        captured["topic"] = topic
        return None

    monkeypatch.setattr(agent_routes, "policy_evolution_from_spines", _fake_policy)

    resp = client.post(
        "/api/agent/redhead/policy-evolution",
        json={**_BYOK, "book_session_ids": ["p1"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert captured["topic"] is None
    assert body["scanned"] is False
    assert body["stages"] == []


# ── 上下级一致性 /agent/redhead/level-consistency ────────────────────────────


def test_level_consistency_returns_conflicts(
    client_and_store: tuple[TestClient, BookSessionStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """成功路:返 conflicts,scanned=true。"""
    client, store = client_and_store
    _register(store, "l1")
    _register(store, "l2")
    _stub_client_and_spine(monkeypatch)

    def _fake_level(*, doc_spines, **_k):  # type: ignore[no-untyped-def]
        assert len(doc_spines) == 2
        return [{"topic": "试点范围", "detail": "下位扩大了范围", "deviation": "加码",
                 "upper": {"doc": "甲", "clause": 1, "snippet": "原文1。", "verified": True},
                 "lower": {"doc": "乙", "clause": 2, "snippet": "原文2。", "verified": True}}]

    monkeypatch.setattr(agent_routes, "level_consistency_from_spines", _fake_level)

    resp = client.post(
        "/api/agent/redhead/level-consistency",
        json={**_BYOK, "book_session_ids": ["l1", "l2"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scanned"] is True
    assert body["conflicts"][0]["deviation"] == "加码"


def test_level_consistency_no_hierarchy_scanned_false(
    client_and_store: tuple[TestClient, BookSessionStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """全平级/单文件(派生返 None)→ scanned=false 空态(题材自适应该掉)。"""
    client, store = client_and_store
    _register(store, "l1")
    _stub_client_and_spine(monkeypatch)
    monkeypatch.setattr(
        agent_routes, "level_consistency_from_spines", lambda **_k: None
    )

    resp = client.post(
        "/api/agent/redhead/level-consistency",
        json={**_BYOK, "book_session_ids": ["l1"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scanned"] is False
    assert body["conflicts"] == []


def test_level_consistency_all_consistent_empty_scanned_true(
    client_and_store: tuple[TestClient, BookSessionStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """都一致(派生返空 list,非 None)→ scanned=true + 空 conflicts。"""
    client, store = client_and_store
    _register(store, "l1")
    _register(store, "l2")
    _stub_client_and_spine(monkeypatch)
    monkeypatch.setattr(
        agent_routes, "level_consistency_from_spines", lambda **_k: []
    )

    resp = client.post(
        "/api/agent/redhead/level-consistency",
        json={**_BYOK, "book_session_ids": ["l1", "l2"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scanned"] is True
    assert body["conflicts"] == []
