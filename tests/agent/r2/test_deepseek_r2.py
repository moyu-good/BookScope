"""r2 DeepSeekAdapter passthrough 单测。

ADR-007 D-3：r2 下 DeepSeekAdapter 退化为 passthrough，但保留若干兜底：
reasoning model ``<think>`` 块 strip、错误归并、内容审查识别、arguments
空串宽容降级。
"""

from __future__ import annotations

from typing import Any

import pytest

from bookscope.agent.adapters.deepseek_r2 import (
    DeepSeekAdapter,
    _looks_like_content_filter,
)
from bookscope.agent.errors import (
    ContentFiltered,
    ProviderError,
)

# ---------------------------------------------------------------------------
# OpenAI SDK 响应替身
# ---------------------------------------------------------------------------


class _FakeUsage:
    def __init__(self, prompt_tokens: int = 100, completion_tokens: int = 50) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _FakeFunction:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class _FakeToolCall:
    def __init__(self, tc_id: str, name: str, arguments: str) -> None:
        self.id = tc_id
        self.type = "function"
        self.function = _FakeFunction(name, arguments)


class _FakeMessage:
    def __init__(
        self,
        content: str | None = None,
        tool_calls: list[_FakeToolCall] | None = None,
    ) -> None:
        self.content = content
        self.tool_calls = tool_calls or None


class _FakeChoice:
    def __init__(self, message: _FakeMessage, finish_reason: str = "stop") -> None:
        self.message = message
        self.finish_reason = finish_reason


class _FakeResponse:
    def __init__(self, choices: list[_FakeChoice]) -> None:
        self.choices = choices
        self.usage = _FakeUsage()


class _FakeCompletions:
    def __init__(self, response: Any, captured: dict[str, Any]) -> None:
        self._response = response
        self._captured = captured

    def create(self, **kwargs: Any) -> Any:
        self._captured.update(kwargs)
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


class _FakeChat:
    def __init__(self, response: Any, captured: dict[str, Any]) -> None:
        self.completions = _FakeCompletions(response, captured)


class _FakeOpenAIClient:
    def __init__(self, response: Any) -> None:
        self.captured: dict[str, Any] = {}
        self.chat = _FakeChat(response, self.captured)


# ---------------------------------------------------------------------------
# 测试：passthrough 不做反向翻译
# ---------------------------------------------------------------------------


def test_deepseek_r2_passthrough_no_anthropic_translation():
    """响应应保留 OpenAI 形态：choices / finish_reason / prompt_tokens。

    跟 r1 的关键区别：r1 把响应翻译成 ``{stop_reason, content[blocks], usage{input_tokens}}``；
    r2 保留 ``{choices[{message, finish_reason}], usage{prompt_tokens}}``。
    """
    fake_response = _FakeResponse(
        choices=[
            _FakeChoice(
                _FakeMessage(content="纯文本回复"),
                finish_reason="stop",
            )
        ],
    )
    fake_client = _FakeOpenAIClient(fake_response)
    adapter = DeepSeekAdapter(api_key="k", openai_client=fake_client)

    result = adapter.messages_create(
        model="deepseek-chat",
        system="sys",
        tools=[],
        messages=[{"role": "user", "content": "Q"}],
        max_tokens=1000,
    )

    # OpenAI 形态字段：choices / usage.prompt_tokens
    assert "choices" in result
    assert "usage" in result
    assert "prompt_tokens" in result["usage"]
    # 没翻译回 Anthropic
    assert "stop_reason" not in result
    assert "content" not in result  # Anthropic 顶层会有 content blocks list
    # choices[0] 保留 finish_reason
    assert result["choices"][0]["finish_reason"] == "stop"


def test_deepseek_r2_strip_thinking_tags_preserved():
    """reasoning model 在 content 里返回 ``<think>...</think>``，应该被抹除。"""
    fake_response = _FakeResponse(
        choices=[
            _FakeChoice(
                _FakeMessage(content="<think>internal reasoning</think>真正的答案"),
                finish_reason="stop",
            )
        ],
    )
    fake_client = _FakeOpenAIClient(fake_response)
    adapter = DeepSeekAdapter(api_key="k", openai_client=fake_client)

    result = adapter.messages_create(
        model="minimax-m2",
        system="",
        tools=[],
        messages=[{"role": "user", "content": "Q"}],
        max_tokens=1000,
    )

    content = result["choices"][0]["message"]["content"]
    assert "<think>" not in content
    assert "internal reasoning" not in content
    assert "真正的答案" in content


def test_deepseek_r2_tool_calls_preserved_with_arguments_as_string():
    """tool_calls 应该原样保留——arguments 是 JSON 字符串而非 dict。"""
    fake_response = _FakeResponse(
        choices=[
            _FakeChoice(
                _FakeMessage(
                    content=None,
                    tool_calls=[
                        _FakeToolCall("call_1", "search_chunks", '{"query":"x"}'),
                    ],
                ),
                finish_reason="tool_calls",
            )
        ],
    )
    fake_client = _FakeOpenAIClient(fake_response)
    adapter = DeepSeekAdapter(api_key="k", openai_client=fake_client)

    result = adapter.messages_create(
        model="deepseek-chat",
        system="",
        tools=[],
        messages=[{"role": "user", "content": "Q"}],
        max_tokens=1000,
    )

    msg = result["choices"][0]["message"]
    assert "tool_calls" in msg
    tc = msg["tool_calls"][0]
    assert tc["id"] == "call_1"
    assert tc["function"]["name"] == "search_chunks"
    # arguments 是原始 JSON 字符串——loop_r2 负责解析
    assert tc["function"]["arguments"] == '{"query":"x"}'
    assert result["choices"][0]["finish_reason"] == "tool_calls"


def test_deepseek_r2_tools_translated_to_openai_function_spec():
    """tools 注入 schema：``{name, description, input_schema}`` → OpenAI function 形态。

    这一层翻译是 adapter 兜底职责（ADR-003 既定），不算违反 D-3 passthrough。
    """
    fake_response = _FakeResponse(
        choices=[_FakeChoice(_FakeMessage(content="ok"), finish_reason="stop")],
    )
    fake_client = _FakeOpenAIClient(fake_response)
    adapter = DeepSeekAdapter(api_key="k", openai_client=fake_client)

    adapter.messages_create(
        model="deepseek-chat",
        system="",
        tools=[
            {
                "name": "search_chunks",
                "description": "do a search",
                "input_schema": {"type": "object", "properties": {}},
            }
        ],
        messages=[{"role": "user", "content": "Q"}],
        max_tokens=1000,
    )

    captured_tools = fake_client.captured["tools"]
    assert captured_tools[0]["type"] == "function"
    assert captured_tools[0]["function"]["name"] == "search_chunks"
    assert captured_tools[0]["function"]["description"] == "do a search"
    assert captured_tools[0]["function"]["parameters"] == {
        "type": "object",
        "properties": {},
    }


def test_deepseek_r2_system_prepended_as_message():
    """非空 system 应该被 prepend 成 ``{"role": "system", ...}``。"""
    fake_response = _FakeResponse(
        choices=[_FakeChoice(_FakeMessage(content="ok"), finish_reason="stop")],
    )
    fake_client = _FakeOpenAIClient(fake_response)
    adapter = DeepSeekAdapter(api_key="k", openai_client=fake_client)

    adapter.messages_create(
        model="deepseek-chat",
        system="SYSTEM PROMPT",
        tools=[],
        messages=[{"role": "user", "content": "Q"}],
        max_tokens=1000,
    )

    sent_messages = fake_client.captured["messages"]
    assert sent_messages[0] == {"role": "system", "content": "SYSTEM PROMPT"}
    assert sent_messages[1] == {"role": "user", "content": "Q"}


# ---------------------------------------------------------------------------
# 错误翻译保留
# ---------------------------------------------------------------------------


class _FakeUnprocessableEntityError(Exception):
    """模拟 openai.UnprocessableEntityError —— 类名匹配触发 422 识别。"""


# 让类名匹配 r1 _translate_error 里的 'UnprocessableEntityError' 检查
_FakeUnprocessableEntityError.__name__ = "UnprocessableEntityError"


def test_deepseek_r2_translate_error_content_filter_preserved():
    """422 + 内容审核关键词应翻译为 ``ContentFiltered``。"""
    exc = _FakeUnprocessableEntityError("output new_sensitive: 1027")
    fake_client = _FakeOpenAIClient(exc)
    adapter = DeepSeekAdapter(api_key="k", openai_client=fake_client)

    with pytest.raises(ContentFiltered):
        adapter.messages_create(
            model="minimax-m2",
            system="",
            tools=[],
            messages=[{"role": "user", "content": "Q"}],
            max_tokens=1000,
        )


def test_deepseek_r2_translate_error_generic_422_becomes_provider_error():
    """422 但非内容审核关键词 → 通用 ProviderError。"""
    exc = _FakeUnprocessableEntityError("unknown 422 reason")
    fake_client = _FakeOpenAIClient(exc)
    adapter = DeepSeekAdapter(api_key="k", openai_client=fake_client)

    with pytest.raises(ProviderError) as ei:
        adapter.messages_create(
            model="deepseek-chat",
            system="",
            tools=[],
            messages=[{"role": "user", "content": "Q"}],
            max_tokens=1000,
        )
    # 不是 ContentFiltered（ContentFiltered 是 ProviderError 子类——
    # 用具体子类断言）
    assert not isinstance(ei.value, ContentFiltered)


def test_deepseek_r2_looks_like_content_filter_helper_still_works():
    """``_looks_like_content_filter`` 被 r2 adapter 复用，行为不变。"""
    assert _looks_like_content_filter("output new_sensitive")
    assert _looks_like_content_filter("content_filter triggered")
    assert _looks_like_content_filter("error code 1027")
    assert not _looks_like_content_filter("rate limit exceeded")
