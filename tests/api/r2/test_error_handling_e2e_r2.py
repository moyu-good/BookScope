"""r2 路径错误链端到端测试。

ADR-007 Sprint 6 默认切 r2 后，``tests/api/test_error_handling_e2e.py`` 整
套 6 个错误兜底测试仍按 r1 Anthropic 形态写——靠 ``tests/api/conftest.py``
autouse 锁 r1 兜底跑。本文件是 r2 路径的等价错误测试。

第一波（commit ``2d96e90``）只放了 1 个 ContentFiltered case 作范式模板。
本轮（Sprint 6 QA 第二波）按同 pattern 补 4 个核心错误测试：

1. ``content_filtered_after_retries`` —— 重试上限耗尽 → 502（原范式）
2. ``provider_unavailable`` —— Adapter 抛 ProviderError → 502
3. ``rate_limited_after_retries`` —— RateLimited 重试耗尽 → 429
4. ``context_limit_exceeded_after_retries`` —— ContextLimit 截断重试耗尽 → 413
   （r2 下截断 helper 是 ``_truncate_messages_r2`` windowing 1+N pair）
5. ``max_iterations_exceeded`` —— MaxIter → 504

``test_envelope_marker_check_via_json_string`` 不翻——元测试 r1/r2 共享同一
个 envelope 实现，复制无价值。

异常路径 r1/r2 共享同一套 ``bookscope.agent.errors`` 类型，形态差异只在
response 桩侧。本文件 adapter 桩每次调用都抛固定异常，response 形态无需
构造。
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from bookscope.agent.errors import (
    ContentFiltered,
    ContextLimitExceeded,
    ProviderUnavailable,
    RateLimited,
)
from bookscope.agent.tools.schemas import ChapterText, CharacterRef, ChunkMatch
from bookscope.api import create_app
from bookscope.api.book_sessions import get_book_session_store
from bookscope.api.dependencies import reset_book_session_store_for_tests
from bookscope.api.routes import agent as agent_route_module

# ---------------------------------------------------------------------------
# envelope 体检关键字（复制自 r1 等价测试，保口径一致）
# ---------------------------------------------------------------------------

_STACK_TRACE_MARKERS: tuple[str, ...] = (
    "Traceback",
    'File "',
    "line ",
    "Exception",
    ".py",
    "raise ",
    "site-packages",
)

_PROVIDER_NAMES: tuple[str, ...] = (
    "MiniMax",
    "DeepSeek",
    "Anthropic",
    "OpenAI",
)


def _assert_no_stack_or_provider_leak(body_text: str) -> None:
    """envelope 不漏 stack trace 字面量 / provider 名。"""
    for marker in _STACK_TRACE_MARKERS:
        assert marker not in body_text, (
            f"response body 不应包含 stack trace 标记 {marker!r}：{body_text}"
        )
    for provider in _PROVIDER_NAMES:
        assert provider not in body_text, (
            f"response body 不应暴露 provider 名 {provider!r}：{body_text}"
        )


# ---------------------------------------------------------------------------
# Fake adapter / backends —— 注意：本 case 只测异常路径，response 桩内容
# 不会被消费，所以不构造 r2 response 形态；adapter 每次调用都抛同一异常。
# ---------------------------------------------------------------------------


class _R2Usage:
    def __init__(self) -> None:
        self.prompt_tokens = 10
        self.completion_tokens = 5


class _R2Function:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class _R2ToolCall:
    def __init__(self, tc_id: str, name: str, arguments: str) -> None:
        self.id = tc_id
        self.type = "function"
        self.function = _R2Function(name, arguments)


class _R2Message:
    def __init__(
        self,
        *,
        content: str | None = None,
        tool_calls: list[_R2ToolCall] | None = None,
    ) -> None:
        self.role = "assistant"
        self.content = content
        self.tool_calls = tool_calls or None


class _R2Choice:
    def __init__(self, message: _R2Message, finish_reason: str) -> None:
        self.message = message
        self.finish_reason = finish_reason


class _R2Response:
    def __init__(self, choices: list[_R2Choice]) -> None:
        self.choices = choices
        self.usage = _R2Usage()


def _r2_tool_call_response(name: str, arguments: dict[str, Any]) -> _R2Response:
    """单 tool_calls 响应（``finish_reason=tool_calls``）——用于 MaxIter 测试。"""
    tc = _R2ToolCall("call_001", name, json.dumps(arguments, ensure_ascii=False))
    msg = _R2Message(content=None, tool_calls=[tc])
    return _R2Response([_R2Choice(msg, finish_reason="tool_calls")])


class _R2FakeAdapter:
    """r2 路径 fake adapter——支持 raise_exc / 预置 response 序列两种模式。

    异常路径 r1/r2 共享同一套 ``bookscope.agent.errors`` 类型；MaxIter 测试
    不抛异常而是让 adapter 永远返 tool_calls 响应。
    """

    def __init__(
        self,
        responses: list[_R2Response] | None = None,
        *,
        raise_exc: Exception | None = None,
    ) -> None:
        self._responses = list(responses or [])
        self._raise_exc = raise_exc
        self.call_count = 0

    def messages_create(self, **_: Any) -> Any:
        self.call_count += 1
        if self._raise_exc is not None:
            raise self._raise_exc
        if not self._responses:
            raise AssertionError("_R2FakeAdapter ran out of prepared responses")
        return self._responses.pop(0)


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
                text="片段。",
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _detach_session_storage() -> None:
    """``_FakeAssembler`` 不可序列化，解绑 storage。"""
    reset_book_session_store_for_tests()
    yield
    reset_book_session_store_for_tests()


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """把 r2 loop 的 ``time.sleep`` patch 成 no-op。

    r2 ``loop_r2.py`` 在 rate-limit 退避里用 ``time.sleep``；ContentFiltered
    本身不退避但仍直接 patch loop_r2 模块的 ``time.sleep``，保后续在本文件
    增量加 RateLimited / ContextLimitExceeded case 时不被退避序列拖慢。
    """

    def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("bookscope.agent.loop_r2.time.sleep", _no_sleep)


@pytest.fixture()
def session_id() -> str:
    return "err-r2-test-session"


@pytest.fixture()
def client_with_session(session_id: str):
    app = create_app()
    store = get_book_session_store()
    store.clear()
    store.register(session_id, _FakeAssembler())  # type: ignore[arg-type]
    with TestClient(app) as c:
        yield c
    store.clear()


def _install_fake_client(
    monkeypatch: pytest.MonkeyPatch,
    fake_adapter: _R2FakeAdapter,
) -> None:
    def _fake_build(_request: Any) -> Any:
        return fake_adapter

    monkeypatch.setattr(agent_route_module, "build_llm_client", _fake_build)


def _post_ask(client: TestClient, session_id: str) -> Any:
    """对 ``/api/agent/ask`` 发最小合法请求；题面含"分析"避开 fast_path。"""
    return client.post(
        "/api/agent/ask",
        json={
            "question": "分析这道测试题",
            "book_session_id": session_id,
            "provider": "deepseek",
            "api_key": "sk-test-0123456789",
        },
    )


# ---------------------------------------------------------------------------
# r2 路径：ContentFiltered 重试上限耗尽后翻 502
# ---------------------------------------------------------------------------


def test_r2_content_filtered_after_retries_envelope(
    client_with_session: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    session_id: str,
) -> None:
    """r2 ContentFiltered 重试链：原始 1 次 + 默认 2 次重试 = 3 次都失败 → 502。

    断言点：

    - HTTP 502 + ``error_type == "ContentFiltered"``
    - adapter 被调 3 次（1 + ``content_filter_retry_limit=2``）
    - envelope 不漏 stack trace / provider 名

    这条覆盖 ``loop_r2._invoke_with_content_filter_retry`` 链路；r1 等价
    case 在 ``tests/api/test_error_handling_e2e.py::test_content_filtered_after_retries_envelope``。
    """
    fake = _R2FakeAdapter(
        raise_exc=ContentFiltered("output new_sensitive (1027)")
    )
    _install_fake_client(monkeypatch, fake)

    resp = _post_ask(client_with_session, session_id)

    assert resp.status_code == 502, resp.text
    body = resp.json()
    assert body["detail"]["error_type"] == "ContentFiltered"
    # 原始 1 次 + 默认 2 次重试 = 3 次调用
    assert fake.call_count == 3, (
        f"r2 ContentFiltered 应触发 3 次调用（1 + 2 retries），实际 {fake.call_count}"
    )
    _assert_no_stack_or_provider_leak(resp.text)
    # 另一道保险：JSON 字符串序列化口径
    serialized = json.dumps(resp.json(), ensure_ascii=False)
    _assert_no_stack_or_provider_leak(serialized)


# ---------------------------------------------------------------------------
# r2 路径：ProviderUnavailable —— 第一次就抛，不重试
# ---------------------------------------------------------------------------


def test_provider_unavailable_envelope_r2(
    client_with_session: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    session_id: str,
) -> None:
    """r2 adapter 抛 ``ProviderUnavailable`` → HTTP 502 + envelope 干净。

    ``ProviderUnavailable`` 在 loop 层不重试（认证失败重试无意义），
    第一次就向上抛到 ``_run_loop_or_raise`` 翻译成 502。r1/r2 行为一致。
    """
    fake = _R2FakeAdapter(raise_exc=ProviderUnavailable("authentication failed"))
    _install_fake_client(monkeypatch, fake)

    resp = _post_ask(client_with_session, session_id)

    assert resp.status_code == 502, resp.text
    body = resp.json()
    assert body["detail"]["error_type"] == "ProviderUnavailable"
    assert fake.call_count == 1, "ProviderUnavailable 不应触发重试"
    _assert_no_stack_or_provider_leak(resp.text)


# ---------------------------------------------------------------------------
# r2 路径：RateLimited —— BE-1 退避重试上限耗尽后翻 429
# ---------------------------------------------------------------------------


def test_rate_limited_after_retries_envelope_r2(
    client_with_session: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    session_id: str,
) -> None:
    """r2 RateLimited 重试链耗尽 → HTTP 429 + envelope 干净。

    默认 ``rate_limit_retry_limit=3``：原始 1 次 + 重试 3 次 = 4 次调用。
    退避 ``time.sleep`` 已在 ``_no_real_sleep`` autouse fixture 中 patch 成
    no-op（patch 路径是 ``bookscope.agent.loop_r2.time.sleep``）。
    """
    fake = _R2FakeAdapter(raise_exc=RateLimited("429 Too Many Requests"))
    _install_fake_client(monkeypatch, fake)

    resp = _post_ask(client_with_session, session_id)

    assert resp.status_code == 429, resp.text
    body = resp.json()
    assert body["detail"]["error_type"] == "RateLimited"
    assert fake.call_count == 4, (
        f"r2 RateLimited 应调 adapter 4 次（1 + 3 retries），实际 {fake.call_count}"
    )
    _assert_no_stack_or_provider_leak(resp.text)


# ---------------------------------------------------------------------------
# r2 路径：ContextLimitExceeded —— ``_truncate_messages_r2`` 截断重试耗尽翻 413
# ---------------------------------------------------------------------------


def test_context_limit_exceeded_after_retries_envelope_r2(
    client_with_session: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    session_id: str,
) -> None:
    """r2 ContextLimitExceeded 截断重试耗尽 → HTTP 413 + envelope 干净。

    r2 下截断 helper 是 ``_truncate_messages_r2``（ADR-007 D-1 改动点 4），
    用"assistant 含 tool_calls + 后续 N 条 role=tool 消息"成组丢弃的 1+N
    pair windowing 替代 r1 的两两配对扫描。

    默认 ``context_truncate_retry_limit=1``：原始 1 次 + 截断重试 1 次 = 2
    次调用都失败后向上抛 → 413。
    """
    fake = _R2FakeAdapter(
        raise_exc=ContextLimitExceeded("prompt exceeds 200k tokens")
    )
    _install_fake_client(monkeypatch, fake)

    resp = _post_ask(client_with_session, session_id)

    assert resp.status_code == 413, resp.text
    body = resp.json()
    assert body["detail"]["error_type"] == "ContextLimitExceeded"
    assert fake.call_count == 2, (
        f"r2 ContextLimit 应调 adapter 2 次（1 + 1 truncate retry），"
        f"实际 {fake.call_count}"
    )
    _assert_no_stack_or_provider_leak(resp.text)


# ---------------------------------------------------------------------------
# r2 路径：MaxIterationsExceeded —— adapter 永远返 tool_calls 不收敛
# ---------------------------------------------------------------------------


def test_max_iterations_exceeded_envelope_r2(
    client_with_session: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    session_id: str,
) -> None:
    """r2 adapter 永远返 tool_calls → 不收敛 → HTTP 504 + envelope 干净。

    与 r1 等价测试的差异：r2 用 ``finish_reason="tool_calls"`` +
    ``message.tool_calls`` 数组替代 r1 的 ``stop_reason="tool_use"`` +
    ``content`` 里的 tool_use block。默认 ``max_iterations=12``，准备 30 个
    响应足够触发上限；response body 应含 ``details.max_iterations`` 字段。
    """
    responses = [
        _r2_tool_call_response("search_chunks", {"query": "x"}) for _ in range(30)
    ]
    fake = _R2FakeAdapter(responses)
    _install_fake_client(monkeypatch, fake)

    resp = _post_ask(client_with_session, session_id)

    assert resp.status_code == 504, resp.text
    body = resp.json()
    assert body["detail"]["error_type"] == "MaxIterationsExceeded"
    assert isinstance(body["detail"]["details"]["max_iterations"], int)
    _assert_no_stack_or_provider_leak(resp.text)
