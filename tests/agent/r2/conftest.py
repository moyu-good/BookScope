"""r2 测试共享 fixture：OpenAI 形态 mock client / backend。

ADR-007 D-1 第二波测试基础设施。所有 fixture 都构造 **OpenAI 原生形态**
响应（``{choices: [{message: {content, tool_calls}, finish_reason}], usage}``），
不构造 Anthropic 形态。loop_r2 直接消费这些 OpenAI 形态对象。
"""

from __future__ import annotations

from typing import Any

import pytest

from bookscope.agent.loop_r2 import AgentLoop as R2AgentLoop
from bookscope.agent.tools.schemas import ChapterText, CharacterRef, ChunkMatch

# ---------------------------------------------------------------------------
# OpenAI 形态响应构造 helper
# ---------------------------------------------------------------------------


class _R2Usage:
    """OpenAI ``usage`` 替身：prompt_tokens / completion_tokens 字段名。"""

    def __init__(self, prompt_tokens: int = 0, completion_tokens: int = 0) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _R2Function:
    """OpenAI ``tool_call.function`` 替身——name + arguments(JSON 字符串)。"""

    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class _R2ToolCall:
    """OpenAI ``ChatCompletionMessageToolCall`` 替身——id + function。"""

    def __init__(self, tc_id: str, name: str, arguments: str) -> None:
        self.id = tc_id
        self.type = "function"
        self.function = _R2Function(name, arguments)


class _R2Message:
    """OpenAI ``ChatCompletionMessage`` 替身。

    ``content`` 可为 None（assistant 含 tool_calls 时）或 str。
    ``tool_calls`` 为 None / 空 list 时表示纯文本回复。
    """

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
    def __init__(
        self,
        message: _R2Message,
        finish_reason: str,
    ) -> None:
        self.message = message
        self.finish_reason = finish_reason


class _R2Response:
    """OpenAI ``ChatCompletion`` 替身：choices + usage。"""

    def __init__(
        self,
        choices: list[_R2Choice],
        *,
        prompt_tokens: int = 100,
        completion_tokens: int = 50,
    ) -> None:
        self.choices = choices
        self.usage = _R2Usage(prompt_tokens, completion_tokens)


# ---------------------------------------------------------------------------
# Fake client + backends
# ---------------------------------------------------------------------------


class _R2FakeClient:
    """按预置 OpenAI 形态 response 序列依次吐 response。

    实现 ``messages_create`` 方法（``LLMClient`` Protocol），让 r2 loop
    直接走 adapter 风格的调用入口；不模拟 ``.messages.create`` 旧路径。
    """

    def __init__(self, responses: list[Any]) -> None:
        self._queue: list[Any] = list(responses)
        self.call_count = 0
        self.last_kwargs: dict[str, Any] | None = None

    def messages_create(self, **kwargs: Any) -> Any:
        self.call_count += 1
        self.last_kwargs = kwargs
        if not self._queue:
            raise AssertionError("R2FakeClient ran out of prepared responses")
        item = self._queue.pop(0)
        if callable(item):
            return item(kwargs)
        return item


class _R2FakeSearchBackend:
    def __init__(self, matches: list[ChunkMatch] | None = None) -> None:
        self._matches = matches or []
        self.call_count = 0

    def retrieve(
        self,
        query: str,
        chapter_scope: tuple[int, int] | None,
        character_filter: list[str] | None,
        top_k: int,
    ) -> list[ChunkMatch]:
        self.call_count += 1
        return list(self._matches)


class _R2FakeChapterBackend:
    def __init__(self, chapters: list[ChapterText] | None = None) -> None:
        self._chapters = chapters or []

    def total_words(self, start: int, end: int) -> int:
        return sum(c.word_count for c in self._chapters if start <= c.chapter <= end)

    def get_chapters(self, start: int, end: int) -> list[ChapterText]:
        return [c for c in self._chapters if start <= c.chapter <= end]


class _R2FakeCharactersBackend:
    def __init__(
        self,
        refs_by_chapter: dict[int, list[CharacterRef]] | None = None,
    ) -> None:
        self._refs = refs_by_chapter or {}

    def characters_in(self, chapter: int) -> list[CharacterRef]:
        return list(self._refs.get(chapter, []))


def _make_chunk_match(chapter: int = 1, snippet: str = "原文片段") -> ChunkMatch:
    return ChunkMatch(
        chunk_id=f"r0-chunk-{chapter}",
        chapter=chapter,
        text=snippet,
        relevance_score=1.0,
        contains_characters=[],
        source_version="r0",
    )


def _make_r2_loop(
    client: _R2FakeClient,
    *,
    search_backend: _R2FakeSearchBackend | None = None,
    chapter_backend: _R2FakeChapterBackend | None = None,
    characters_backend: _R2FakeCharactersBackend | None = None,
    max_iterations: int = 8,
    timeout_seconds: float = 90.0,
    tool_retry_limit: int = 2,
    format_retry_limit: int = 1,
    content_filter_retry_limit: int = 2,
    on_event: Any | None = None,
) -> R2AgentLoop:
    return R2AgentLoop(
        client=client,
        search_chunks_backend=search_backend or _R2FakeSearchBackend(),
        chapter_range_backend=chapter_backend or _R2FakeChapterBackend(),
        list_characters_backend=characters_backend or _R2FakeCharactersBackend(),
        max_iterations=max_iterations,
        timeout_seconds=timeout_seconds,
        tool_retry_limit=tool_retry_limit,
        format_retry_limit=format_retry_limit,
        content_filter_retry_limit=content_filter_retry_limit,
        on_event=on_event,
    )


# ---------------------------------------------------------------------------
# pytest fixture：对外暴露给测试模块
# ---------------------------------------------------------------------------


@pytest.fixture
def r2_response_factory():
    """提供构造 ``_R2Response`` 的便利工厂。"""

    def _make(
        *,
        content: str | None = None,
        tool_calls: list[tuple[str, str, str]] | None = None,
        finish_reason: str = "stop",
        prompt_tokens: int = 100,
        completion_tokens: int = 50,
    ) -> _R2Response:
        """构造一个 r2 response。

        tool_calls: list of (id, name, arguments_json_str) 元组——空 list /
        None 时构造纯文本回复。
        """
        tc_objs = (
            [_R2ToolCall(tc_id, name, args) for tc_id, name, args in tool_calls]
            if tool_calls
            else None
        )
        msg = _R2Message(content=content, tool_calls=tc_objs)
        return _R2Response(
            [_R2Choice(msg, finish_reason)],
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    return _make


@pytest.fixture
def r2_fake_client():
    def _build(responses: list[Any]) -> _R2FakeClient:
        return _R2FakeClient(responses)

    return _build


@pytest.fixture
def make_r2_loop():
    return _make_r2_loop


@pytest.fixture
def make_chunk_match():
    return _make_chunk_match


@pytest.fixture
def fake_search_backend():
    return _R2FakeSearchBackend
