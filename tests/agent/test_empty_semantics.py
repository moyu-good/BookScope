"""evidence-first 空值三态(task #29 根一)——书侧整本功能的「空」分三态。

两层测:

1. **纯件**:``classify_scan_result`` / ``is_confirmed_empty`` 把 BE 返回值
   (None / [] / 非空)deterministic 映成三态。命门=``confirmed_empty`` 只在真扫到空时给,
   ``None``(没扫成)绝不冒充确证无。

2. **端点接线**:三个端点(设定一致性 / 伏笔回收 / 实体回溯)空结果时按「扫过全书空」
   (confirmed_*=true)vs「扫失败」(scanned=false、confirmed_*=false)分清。打桩 client +
   章脉 / 扫描函数,不真调 LLM。照 ``tests/api/test_routes_redhead.py`` 范式。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import bookscope.api.routes.agent as agent_routes
from bookscope.agent._internal.empty_semantics import (
    EMPTY_STATUS_CONFIRMED_EMPTY,
    EMPTY_STATUS_PRESENT,
    EMPTY_STATUS_UNVERIFIED,
    classify_scan_result,
    is_confirmed_empty,
)
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

# ── 第一层:纯件三态分类 ──────────────────────────────────────────────────────


def test_classify_scan_result_three_states():
    """None=没扫成→unverified;[]=扫过且空→confirmed_empty;非空→present。"""
    assert classify_scan_result(None) == EMPTY_STATUS_UNVERIFIED
    assert classify_scan_result([]) == EMPTY_STATUS_CONFIRMED_EMPTY
    assert classify_scan_result([{"x": 1}]) == EMPTY_STATUS_PRESENT
    assert classify_scan_result([1, 2, 3]) == EMPTY_STATUS_PRESENT


def test_is_confirmed_empty_only_for_scanned_empty():
    """命门:确证无只在真扫到空([])才 true;None(没扫成)绝不冒充确证无。"""
    assert is_confirmed_empty([]) is True
    assert is_confirmed_empty(None) is False, "没扫成不能冒充确证无(危险的假安心)"
    assert is_confirmed_empty([{"a": 1}]) is False


# ── 第二层:端点接线 ──────────────────────────────────────────────────────────


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
    """注册一本自洽小书(够端点跑通,真扫不真调,数据本身不重要)。"""
    book = BookText(
        title=f"书-{sid}",
        raw_text="第一章\n张三向东走。\n第二章\n李四向西走。",
        language="zh",
    )
    chunks = [
        ChunkResult(index=0, text="张三向东走。", chapter=1),
        ChunkResult(index=1, text="李四向西走。", chapter=2),
    ]
    kg = BookKnowledgeGraph(
        book_title=f"书-{sid}",
        language="zh",
        characters=[CharacterProfile(name="张三", key_chapter_indices=[1])],
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


_BYOK = {"provider": "deepseek", "api_key": "k" * 12}


def _stub_common(monkeypatch: pytest.MonkeyPatch) -> None:
    """打桩 client 构建 + 章脉构建 + 大书闸放行(不真调 LLM)。"""
    monkeypatch.setattr(
        agent_routes, "build_llm_client_from_params", lambda **_k: object()
    )
    monkeypatch.setattr(agent_routes, "get_or_build_spine", lambda **_k: [])
    # 实体回溯 / 一致性扫描有 _book_fits_long_context 大书闸——放行,免得提前 scanned=false。
    monkeypatch.setattr(agent_routes, "_book_fits_long_context", lambda _a: True)


# ── 设定一致性:确证无矛盾 vs 扫失败 ────────────────────────────────────────────


def test_consistency_confirmed_clean_when_scanned_empty(
    client_and_store: tuple[TestClient, BookSessionStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """扫过全书(返 [])且没矛盾 → confirmed_clean=true、scanned=true(确证无矛盾,好消息)。"""
    client, store = client_and_store
    _register(store, "c1")
    _stub_common(monkeypatch)
    monkeypatch.setattr(
        agent_routes, "consistency_scan_from_spine", lambda **_k: []
    )

    resp = client.post(
        "/api/agent/consistency-scan", json={**_BYOK, "book_session_id": "c1"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scanned"] is True
    assert body["confirmed_clean"] is True, "扫过全书没矛盾=确证无矛盾"
    assert body["contradictions"] == []


def test_consistency_unverified_when_scan_failed(
    client_and_store: tuple[TestClient, BookSessionStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """扫失败(返 None)→ confirmed_clean=false、scanned=false(待核,绝不冒充确证无)。"""
    client, store = client_and_store
    _register(store, "c1")
    _stub_common(monkeypatch)
    monkeypatch.setattr(
        agent_routes, "consistency_scan_from_spine", lambda **_k: None
    )

    resp = client.post(
        "/api/agent/consistency-scan", json={**_BYOK, "book_session_id": "c1"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scanned"] is False
    assert body["confirmed_clean"] is False, "扫失败不能冒充确证无矛盾"


def test_consistency_present_when_has_contradictions(
    client_and_store: tuple[TestClient, BookSessionStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """扫出矛盾 → confirmed_clean=false(有结果,不是空)、scanned=true。"""
    client, store = client_and_store
    _register(store, "c1")
    _stub_common(monkeypatch)
    monkeypatch.setattr(
        agent_routes,
        "consistency_scan_from_spine",
        lambda **_k: [
            {
                "topic": "张三方向",
                "conflict": "前向东后向西",
                "a": {"snippet": "张三向东走。", "chapter": 1, "verified": True},
                "b": {"snippet": "张三向西走。", "chapter": 2, "verified": True},
            }
        ],
    )

    resp = client.post(
        "/api/agent/consistency-scan", json={**_BYOK, "book_session_id": "c1"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scanned"] is True
    assert body["confirmed_clean"] is False
    assert len(body["contradictions"]) == 1


# ── 伏笔回收:确证全书没伏笔 vs 扫失败 ──────────────────────────────────────────


def test_foreshadow_confirmed_none_when_scanned_empty(
    client_and_store: tuple[TestClient, BookSessionStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """扫过全书(返 [])且没伏笔 → confirmed_none=true、scanned=true(确证全书没伏笔)。"""
    client, store = client_and_store
    _register(store, "f1")
    _stub_common(monkeypatch)
    monkeypatch.setattr(agent_routes, "foreshadow_from_spine", lambda **_k: [])

    resp = client.post(
        "/api/agent/foreshadow-arcs", json={**_BYOK, "book_session_id": "f1"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scanned"] is True
    assert body["confirmed_none"] is True
    assert body["arcs"] == []


def test_foreshadow_unverified_when_scan_failed(
    client_and_store: tuple[TestClient, BookSessionStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """扫失败(返 None)→ confirmed_none=false、scanned=false(待核)。"""
    client, store = client_and_store
    _register(store, "f1")
    _stub_common(monkeypatch)
    monkeypatch.setattr(agent_routes, "foreshadow_from_spine", lambda **_k: None)

    resp = client.post(
        "/api/agent/foreshadow-arcs", json={**_BYOK, "book_session_id": "f1"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scanned"] is False
    assert body["confirmed_none"] is False, "扫失败不能冒充确证全书没伏笔"


# ── 实体回溯:确证全书未出现 vs 扫失败 ──────────────────────────────────────────


def test_entity_recall_confirmed_absent_when_scanned_empty(
    client_and_store: tuple[TestClient, BookSessionStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """扫过全书(返 [])且没找到 → confirmed_absent=true、scanned=true(确证全书未出现)。"""
    client, store = client_and_store
    _register(store, "e1")
    _stub_common(monkeypatch)
    monkeypatch.setattr(agent_routes, "generate_entity_recall", lambda **_k: [])

    resp = client.post(
        "/api/agent/entity-recall",
        json={**_BYOK, "book_session_id": "e1", "entity": "不存在的人"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scanned"] is True
    assert body["confirmed_absent"] is True
    assert body["appearances"] == []


def test_entity_recall_unverified_when_scan_failed(
    client_and_store: tuple[TestClient, BookSessionStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """扫失败(返 None)→ confirmed_absent=false、scanned=false(待核,绝不冒充确证未出现)。"""
    client, store = client_and_store
    _register(store, "e1")
    _stub_common(monkeypatch)
    monkeypatch.setattr(agent_routes, "generate_entity_recall", lambda **_k: None)

    resp = client.post(
        "/api/agent/entity-recall",
        json={**_BYOK, "book_session_id": "e1", "entity": "张三"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scanned"] is False
    assert body["confirmed_absent"] is False, "扫失败不能冒充确证全书未出现"


def test_entity_recall_present_when_found(
    client_and_store: tuple[TestClient, BookSessionStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """找到出现 → confirmed_absent=false(有结果)、scanned=true。"""
    client, store = client_and_store
    _register(store, "e1")
    _stub_common(monkeypatch)
    monkeypatch.setattr(
        agent_routes,
        "generate_entity_recall",
        lambda **_k: [
            {"order": 1, "chapter": 1, "what": "出场", "snippet": "张三向东走。",
             "verified": True}
        ],
    )

    resp = client.post(
        "/api/agent/entity-recall",
        json={**_BYOK, "book_session_id": "e1", "entity": "张三"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scanned"] is True
    assert body["confirmed_absent"] is False
    assert len(body["appearances"]) == 1


def test_entity_recall_big_book_is_unverified_not_confirmed(
    client_and_store: tuple[TestClient, BookSessionStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """大书闸挡下(没真扫)→ scanned=false、confirmed_absent=false(待核,不是确证无)。

    这是 evidence-first 的命门:书太大根本没扫,空 appearances 绝不能显成"确证全书没有"。
    """
    client, store = client_and_store
    _register(store, "e1")
    monkeypatch.setattr(
        agent_routes, "build_llm_client_from_params", lambda **_k: object()
    )
    # 大书闸返 False:端点提前返回,根本不调 generate_entity_recall。
    monkeypatch.setattr(agent_routes, "_book_fits_long_context", lambda _a: False)

    resp = client.post(
        "/api/agent/entity-recall",
        json={**_BYOK, "book_session_id": "e1", "entity": "张三"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scanned"] is False
    assert body["confirmed_absent"] is False, "没扫(书太大)不能冒充确证全书未出现"
