"""``RouteDecisionEvent`` SSE 事件单测。

覆盖范围：
1. ``RouteDecisionEvent`` dataclass 形态（frozen / 字段齐全）
2. fast_path 4 子类入口 emit ``RouteDecisionEvent`` 含正确 ``route_type``
   / ``human_label`` / ``expected_duration``
3. ``AgentLoop.query`` 直接走 agent_loop 时 emit "agent_loop" 路由帧
4. fast_path 兜底回 agent_loop 时 ``emit_route_decision=False`` 不重复 emit
5. ``_ROUTE_EXPECTED_DURATION`` / ``_ROUTE_HUMAN_LABEL`` 5 类齐全
6. POST /api/agent/ask 同步响应含 ``route_type``

设计原则同 ``test_fast_path_subroute.py``：不跑真 LLM、本文件单独定义
fakes 保隔离；只验证 emit 行为 + 字段语义，不重测 fast_path 内部逻辑。
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from bookscope.agent.events import (
    LoopEvent,
    RouteDecisionEvent,
)
from bookscope.agent.fast_path import (
    _ROUTE_EXPECTED_DURATION,
    _ROUTE_HUMAN_LABEL,
    FAST_SUBROUTES,
    build_route_decision_event,
    run_fast_path,
)
from bookscope.agent.tools.schemas import ChapterText, CharacterRef, ChunkMatch
from bookscope.api import create_app
from bookscope.api.book_sessions import get_book_session_store
from bookscope.api.dependencies import reset_book_session_store_for_tests
from bookscope.api.routes import agent as agent_route_module

# ---------------------------------------------------------------------------
# Fakes —— 本文件独立定义保测试隔离
# ---------------------------------------------------------------------------


class _FakeUsage:
    def __init__(self) -> None:
        self.input_tokens = 12
        self.output_tokens = 8


class _FakeResponse:
    def __init__(
        self,
        content: list[dict[str, Any]],
        *,
        stop_reason: str = "end_turn",
    ) -> None:
        self.content = content
        self.stop_reason = stop_reason
        self.usage = _FakeUsage()


class _FakeAdapter:
    """r1 风格 fake adapter——见 ``test_fast_path._FakeAdapter`` 注释。"""

    def __init__(self, responses: list[_FakeResponse] | None = None) -> None:
        self._responses = list(responses or [])
        self.call_count = 0

    def messages_create(self, **kwargs: Any) -> Any:
        self.call_count += 1
        if not self._responses:
            raise AssertionError("FakeAdapter ran out of prepared responses")
        return self._responses.pop(0)

    def extract_final_text(self, response: Any) -> str:
        blocks = getattr(response, "content", None) or []
        parts: list[str] = []
        for block in blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                t = block.get("text", "")
                if isinstance(t, str):
                    parts.append(t)
        return "\n".join(parts).strip()

    def extract_usage_tokens(self, response: Any) -> tuple[int, int]:
        usage = getattr(response, "usage", None)
        if usage is None:
            return 0, 0
        return int(getattr(usage, "input_tokens", 0) or 0), int(
            getattr(usage, "output_tokens", 0) or 0
        )


class _FakeSearchBackend:
    def __init__(self, matches: list[ChunkMatch] | None = None) -> None:
        self._matches = matches or [
            ChunkMatch(
                chunk_id="r0-chunk-1",
                chapter=1,
                text="原文片段。",
                relevance_score=1.0,
                contains_characters=[],
                source_version="r0",
            )
        ]

    def retrieve(
        self,
        query: str,
        chapter_scope: tuple[int, int] | None,
        character_filter: list[str] | None,
        top_k: int,
    ) -> list[ChunkMatch]:
        return list(self._matches)


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


def _text_block(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def _final_json(answer: str, citations: list[dict[str, Any]]) -> str:
    return json.dumps({"answer": answer, "citations": citations}, ensure_ascii=False)


def _collect_callback() -> tuple[list[LoopEvent], Any]:
    events: list[LoopEvent] = []

    def on_event(event: LoopEvent) -> None:
        events.append(event)

    return events, on_event


# ---------------------------------------------------------------------------
# 1. dataclass 形态
# ---------------------------------------------------------------------------


class TestRouteDecisionEventDataclass:
    def test_route_decision_event_dataclass_frozen(self) -> None:
        """构造 OK + frozen——尝试改字段抛 FrozenInstanceError。"""
        event = RouteDecisionEvent(
            route_type="fast_general",
            human_label="通识题",
            expected_duration_seconds_min=3,
            expected_duration_seconds_max=12,
        )
        assert event.type == "route_decision"
        assert event.route_type == "fast_general"
        assert event.human_label == "通识题"
        assert event.iteration == 0
        with pytest.raises(dataclasses.FrozenInstanceError):
            event.route_type = "agent_loop"  # type: ignore[misc]

    def test_build_route_decision_event_for_unknown_route_falls_back(self) -> None:
        """未知 route_type 兜底成 agent_loop 的标签与时长——保 FE 永不收到非法事件。"""
        event = build_route_decision_event("not_a_real_route")  # type: ignore[arg-type]
        assert event.human_label == _ROUTE_HUMAN_LABEL["agent_loop"]
        assert event.expected_duration_seconds_min == 30
        assert event.expected_duration_seconds_max == 90


# ---------------------------------------------------------------------------
# 2. fast_path 各子类 emit RouteDecisionEvent
# ---------------------------------------------------------------------------


@pytest.fixture()
def _good_response() -> _FakeResponse:
    return _FakeResponse(
        content=[
            _text_block(
                _final_json(
                    "答复。",
                    [{"chapter": 1, "snippet": "原文片段。"}],
                )
            )
        ]
    )


class TestFastPathEmitsRouteDecision:
    # fast_path 砍 5 类到 2 类后：路由判定只产生 fast_general / agent_loop
    # 两类；review / summary / rating 三类路由不再触发，对应 parametrize
    # 已删。``_ROUTE_HUMAN_LABEL`` / ``_ROUTE_EXPECTED_DURATION`` 5 类齐全
    # 的 contract 兼容测试在 ``TestRouteTablesCompleteness`` 里保留。
    @pytest.mark.parametrize(
        "subroute,question,expected_label,expected_min,expected_max",
        [
            ("fast_general", "主要角色有哪几个", "通识题", 3, 12),
        ],
    )
    def test_fast_subroute_emits_route_decision_first(
        self,
        subroute: str,
        question: str,
        expected_label: str,
        expected_min: int,
        expected_max: int,
        _good_response: _FakeResponse,
    ) -> None:
        """4 个 fast 子类——RouteDecisionEvent 必须是 callback 收到的第一帧。"""
        events, on_event = _collect_callback()
        adapter = _FakeAdapter([_good_response])

        result = run_fast_path(
            question,
            search_backend=_FakeSearchBackend(),
            llm_client=adapter,
            model="deepseek-chat",
            on_event=on_event,
            subroute=subroute,
        )

        assert result is not None
        assert len(events) >= 1
        first = events[0]
        assert isinstance(first, RouteDecisionEvent)
        assert first.route_type == subroute
        assert first.human_label == expected_label
        assert first.expected_duration_seconds_min == expected_min
        assert first.expected_duration_seconds_max == expected_max
        # type 字面量 SSE 编码时用
        assert first.type == "route_decision"

    def test_route_decision_emitted_before_iteration_start(
        self,
        _good_response: _FakeResponse,
    ) -> None:
        """路由帧时序必须早于 iteration_start——FE 才能"先显示路由再显示开始干活"。"""
        events, on_event = _collect_callback()
        adapter = _FakeAdapter([_good_response])

        run_fast_path(
            "主要角色有哪几个",
            search_backend=_FakeSearchBackend(),
            llm_client=adapter,
            model="deepseek-chat",
            on_event=on_event,
            subroute="fast_general",
        )

        # 找 route_decision / iteration_start 的索引
        route_idx = next(
            i for i, e in enumerate(events) if isinstance(e, RouteDecisionEvent)
        )
        iter_idx = next(
            i for i, e in enumerate(events) if e.type == "iteration_start"
        )
        assert route_idx < iter_idx


# ---------------------------------------------------------------------------
# 3. AgentLoop 直接走 agent_loop emit 路由帧的 2 个 case（Sprint 7 删除）
#
# 原 ``TestAgentLoopEmitsRouteDecision`` 用 r1 AgentLoop + Anthropic content_blocks
# 形态桩响应做 emit 时序测试；Sprint 7 删 r1 runtime 时这两个 case 形态不
# 匹配 r2 OpenAI choices 形态 = 删。AgentLoop emit 路由帧的语义覆盖现在
# 由 ``tests/agent/r2/test_loop_r2.py`` 的 r2 等价用例承担。
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 4. _ROUTE_EXPECTED_DURATION / _ROUTE_HUMAN_LABEL 完整性
# ---------------------------------------------------------------------------


class TestRouteTablesCompleteness:
    def test_expected_duration_table_complete(self) -> None:
        """5 种 route_type 都在 _ROUTE_EXPECTED_DURATION 映射里。"""
        expected_keys = {*FAST_SUBROUTES, "agent_loop"}
        assert set(_ROUTE_EXPECTED_DURATION.keys()) == expected_keys
        for key, (mn, mx) in _ROUTE_EXPECTED_DURATION.items():
            assert isinstance(mn, int) and isinstance(mx, int)
            assert 0 < mn <= mx, f"{key}: invalid duration ({mn},{mx})"

    def test_human_label_chinese(self) -> None:
        """5 种 route_type 的 human_label 都是中文且非空。"""
        expected_keys = {*FAST_SUBROUTES, "agent_loop"}
        assert set(_ROUTE_HUMAN_LABEL.keys()) == expected_keys
        for key, label in _ROUTE_HUMAN_LABEL.items():
            assert label, f"{key} label empty"
            # 至少含一个 CJK 字符
            assert any("一" <= c <= "鿿" for c in label), (
                f"{key} label not Chinese: {label!r}"
            )


# ---------------------------------------------------------------------------
# 5. POST /api/agent/ask 同步响应含 route_type
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _detach_storage_and_enable_fast_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BOOKSCOPE_FAST_PATH_DISABLED", raising=False)
    reset_book_session_store_for_tests()
    yield
    reset_book_session_store_for_tests()


@pytest.fixture(autouse=True)
def _disable_reviewer_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        agent_route_module,
        "review_answer",
        lambda **_: (_ for _ in ()).throw(RuntimeError("reviewer disabled in test")),
    )


@pytest.fixture()
def session_id() -> str:
    return "test-route-type"


@pytest.fixture()
def client_with_session(session_id: str) -> tuple[TestClient, _FakeAssembler]:
    app = create_app()
    store = get_book_session_store()
    store.clear()
    assembler = _FakeAssembler()
    store.register(session_id, assembler)  # type: ignore[arg-type]
    with TestClient(app) as c:
        yield c, assembler
    store.clear()


def _install_fake_client(
    monkeypatch: pytest.MonkeyPatch,
    fake_adapter: _FakeAdapter,
) -> None:
    monkeypatch.setattr(
        agent_route_module,
        "build_llm_client",
        lambda request: fake_adapter,
    )


class TestAskResponseIncludesRouteType:
    def test_ask_response_includes_route_type_for_fast_general(
        self,
        client_with_session: tuple[TestClient, _FakeAssembler],
        monkeypatch: pytest.MonkeyPatch,
        session_id: str,
    ) -> None:
        """通识题命中 fast path → 响应 ``route_type`` == ``"fast_general"``。"""
        client, _ = client_with_session
        fake = _FakeAdapter(
            [
                _FakeResponse(
                    content=[
                        _text_block(
                            _final_json(
                                "主要角色有 X。",
                                [{"chapter": 1, "snippet": "原文片段。"}],
                            )
                        )
                    ]
                )
            ]
        )
        _install_fake_client(monkeypatch, fake)

        resp = client.post(
            "/api/agent/ask",
            json={
                "question": "主要角色有哪几个？",
                "book_session_id": session_id,
                "provider": "deepseek",
                "api_key": "sk-test-0123456789",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "route_type" in body
        assert body["route_type"] == "fast_general"

    # NOTE: ``test_ask_response_route_type_agent_loop_for_diagnostic`` 已删——它
    # 走完整 agent_loop 但桩响应是 r1 Anthropic content_blocks 形态，Sprint 7
    # 删 r1 后 r2 loop 读不到 ``choices`` 字段会炸。诊断题走 agent_loop 的
    # route_type 路径覆盖现在由 ``tests/api/r2/`` 下的 r2 mock 套承担。
