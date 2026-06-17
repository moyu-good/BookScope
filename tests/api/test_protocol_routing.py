"""API 层 r2 协议路由测试（ADR-007 D-4 · Sprint 7 r1 删除后剩 r2 单线）。

覆盖：

1. ``_select_agent_loop_class()`` env 未设时返回 r2 ``loop_r2.AgentLoop``
2. env ``BOOKSCOPE_AGENT_PROTOCOL=r2`` 时返回 r2 ``loop_r2.AgentLoop``
3. env 设成其他值兜底回 r2
4. POST ``/api/agent/ask`` 在 r2 路径下响应含 ``protocol_version="r2"``

Sprint 7 删 r1 mock 测试时一起把 r1 env 路由 case + r1 端到端 case 删掉
——r1 runtime 即将下线（步骤 ③），保留 r1 case 一删就炸。第 4 个用例用
monkeypatch 把 ``AgentLoop.query`` 替成桩，避开真 LLM / 真 backend 依赖；
同样 monkeypatch 掉 ``build_llm_client`` 让构造跳过 SDK 校验。
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from bookscope.agent import _select_agent_loop_class
from bookscope.agent.loop_r2 import AgentLoop as _R2AgentLoop
from bookscope.agent.models import AgentQueryResult, LoopTrace
from bookscope.agent.tools.schemas import ChapterText, CharacterRef, ChunkMatch
from bookscope.api import create_app
from bookscope.api.book_sessions import get_book_session_store
from bookscope.api.dependencies import reset_book_session_store_for_tests
from bookscope.api.routes import agent as agent_route_module

# ---------------------------------------------------------------------------
# 任务 1：_select_agent_loop_class 单测
# ---------------------------------------------------------------------------


def test_default_protocol_is_r2(monkeypatch: pytest.MonkeyPatch) -> None:
    """env 未设时返回 r2 ``loop_r2.AgentLoop``（Sprint 6 默认切换 · ADR-007 已批准）。"""
    monkeypatch.delenv("BOOKSCOPE_AGENT_PROTOCOL", raising=False)
    assert _select_agent_loop_class() is _R2AgentLoop


def test_protocol_r2_routes_to_loop_r2(monkeypatch: pytest.MonkeyPatch) -> None:
    """env=r2 显式与默认一致——返回 ``loop_r2.AgentLoop``。"""
    monkeypatch.setenv("BOOKSCOPE_AGENT_PROTOCOL", "r2")
    assert _select_agent_loop_class() is _R2AgentLoop


def test_protocol_other_values_fall_back_to_r2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """env 设成无关字符串时退到默认 r2，不抛错。"""
    monkeypatch.setenv("BOOKSCOPE_AGENT_PROTOCOL", "experimental-r3")
    assert _select_agent_loop_class() is _R2AgentLoop


# ---------------------------------------------------------------------------
# 任务 1c / 1d：API 响应含 protocol_version
# ---------------------------------------------------------------------------


class _FakeSearchBackend:
    def retrieve(
        self,
        query: str,
        chapter_scope: tuple[int, int] | None,
        character_filter: list[str] | None,
        top_k: int,
    ) -> list[ChunkMatch]:
        return [
            ChunkMatch(
                chunk_id="r0-chunk-1",
                chapter=1,
                text="朱元璋称帝。",
                relevance_score=1.0,
                contains_characters=[],
                source_version="r0",
            )
        ]


class _FakeChapterBackend:
    def total_words(self, start: int, end: int) -> int:
        return 100

    def get_chapters(self, start: int, end: int) -> list[ChapterText]:
        return []


class _FakeCharactersBackend:
    def characters_in(self, chapter: int) -> list[CharacterRef]:
        return []


class _FakeAssembler:
    def build_all(self) -> dict[str, Any]:
        return {
            "search": _FakeSearchBackend(),
            "chapter_range": _FakeChapterBackend(),
            "list_characters": _FakeCharactersBackend(),
        }


@pytest.fixture(autouse=True)
def _disable_fast_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """走完整 AgentLoop，避开 fast path 启发式分流。"""
    monkeypatch.setenv("BOOKSCOPE_FAST_PATH_DISABLED", "1")


@pytest.fixture(autouse=True)
def _disable_reviewer(monkeypatch: pytest.MonkeyPatch) -> None:
    """让 reviewer 调用失败被吞掉，避开 review 路径的额外 mock。"""
    monkeypatch.setattr(
        agent_route_module,
        "review_answer",
        lambda **_: (_ for _ in ()).throw(RuntimeError("reviewer disabled in test")),
    )


@pytest.fixture(autouse=True)
def _detach_session_storage() -> None:
    """每个 case 解绑 JSONFileSessionStorage——_FakeAssembler 不可序列化。"""
    reset_book_session_store_for_tests()
    yield
    reset_book_session_store_for_tests()


@pytest.fixture()
def session_id() -> str:
    return "test-proto-routing-session"


@pytest.fixture()
def client_with_session(
    session_id: str,
) -> tuple[TestClient, _FakeAssembler]:
    """注册 fake assembler 后给出 TestClient。"""
    app = create_app()
    store = get_book_session_store()
    store.clear()
    assembler = _FakeAssembler()
    store.register(session_id, assembler)  # type: ignore[arg-type]
    with TestClient(app) as c:
        yield c, assembler
    store.clear()


def _install_loop_stub(
    monkeypatch: pytest.MonkeyPatch,
    *,
    protocol_version: str,
) -> None:
    """把两个 AgentLoop class 的 ``query`` 都替换成桩。

    桩返回 ``AgentQueryResult``，``LoopTrace.protocol_version`` 按参数设置。
    端到端不依赖真 LLM 或真 backend。同时把 ``build_llm_client`` 替成返回
    占位 client，跳过 SDK / api_key 校验。
    """
    def _fake_build(request: Any) -> Any:
        return object()  # client 桩——loop.query 也是桩，不会真用

    monkeypatch.setattr(agent_route_module, "build_llm_client", _fake_build)

    def _fake_query(self: Any, question: str) -> AgentQueryResult:
        trace = LoopTrace(protocol_version=protocol_version)  # type: ignore[arg-type]
        trace.outcome = "success"
        trace.iterations = 1
        trace.duration_ms = 1
        return AgentQueryResult(
            answer=f"stub answer for {question}",
            citations=[{"chapter": 1, "snippet": "stub"}],
            trace=trace,
        )

    monkeypatch.setattr(_R2AgentLoop, "query", _fake_query)


def test_ask_response_includes_protocol_version_r2(
    client_with_session: tuple[TestClient, _FakeAssembler],
    monkeypatch: pytest.MonkeyPatch,
    session_id: str,
) -> None:
    """env=r2 下，响应顶级含 ``protocol_version="r2"``，且走的是 r2 loop。"""
    monkeypatch.setenv("BOOKSCOPE_AGENT_PROTOCOL", "r2")
    _install_loop_stub(monkeypatch, protocol_version="r2")

    # 追加断言：构造路径走的是 r2 类
    constructed_classes: list[type] = []
    original_init_r2 = _R2AgentLoop.__init__

    def _spy_init_r2(self: Any, *args: Any, **kwargs: Any) -> None:
        constructed_classes.append(type(self))
        original_init_r2(self, *args, **kwargs)

    monkeypatch.setattr(_R2AgentLoop, "__init__", _spy_init_r2)

    client, _ = client_with_session
    resp = client.post(
        "/api/agent/ask",
        json={
            "question": "第一章讲了什么？",
            "book_session_id": session_id,
            "provider": "deepseek",
            "api_key": "sk-test-0123456789",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["protocol_version"] == "r2"
    assert _R2AgentLoop in constructed_classes, (
        "API 层应在 r2 env 下构造 r2 AgentLoop，但实际未触发 r2 __init__"
    )
