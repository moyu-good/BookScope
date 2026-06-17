"""r2 AnthropicAdapter 反向翻译单测。

ADR-007 D-2 第三波：把 OpenAI 形态请求翻译成 Anthropic 形态喂 SDK，
把 SDK 返回的 Anthropic Message 对象翻回 OpenAI ChatCompletion 形态。

测试组织：
- 请求方向单元测试（系统消息抽出 / tool 消息合并 / tool_calls / tools / tool_choice）
- 响应方向单元测试（content blocks 拆分 / stop_reason 映射 / usage 重命名）
- 端到端 roundtrip 测试（纯文本 / 含 tool_call 两条主路径）
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from bookscope.agent.adapters.anthropic_r2 import (
    AnthropicAdapter,
    _translate_messages_to_anthropic,
    _translate_response_to_openai,
    _translate_tool_choice_to_anthropic,
    _translate_tools_to_anthropic,
)

# ---------------------------------------------------------------------------
# SDK 替身：Anthropic Message / TextBlock / ToolUseBlock / Usage
# ---------------------------------------------------------------------------


class _FakeUsage:
    def __init__(self, input_tokens: int = 100, output_tokens: int = 50) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _FakeTextBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _FakeToolUseBlock:
    def __init__(self, block_id: str, name: str, input_dict: dict[str, Any]) -> None:
        self.type = "tool_use"
        self.id = block_id
        self.name = name
        self.input = input_dict


class _FakeMessage:
    def __init__(
        self,
        *,
        content: list[Any],
        stop_reason: str = "end_turn",
        msg_id: str = "msg_test",
        model: str = "claude-sonnet-4-6",
    ) -> None:
        self.id = msg_id
        self.model = model
        self.role = "assistant"
        self.content = content
        self.stop_reason = stop_reason
        self.usage = _FakeUsage()


class _FakeMessagesEndpoint:
    """模拟 ``anthropic.Anthropic().messages.create``。"""

    def __init__(self, response: Any, captured: dict[str, Any]) -> None:
        self._response = response
        self._captured = captured

    def create(self, **kwargs: Any) -> Any:
        self._captured.update(kwargs)
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


class _FakeAnthropicClient:
    def __init__(self, response: Any) -> None:
        self.captured: dict[str, Any] = {}
        self.messages = _FakeMessagesEndpoint(response, self.captured)


# ---------------------------------------------------------------------------
# 请求方向单元测试
# ---------------------------------------------------------------------------


def test_request_system_message_extraction_to_top_level():
    """OpenAI messages 里的 role=system 抽到顶级 system 字段。"""
    system, anth = _translate_messages_to_anthropic(
        "",
        [
            {"role": "system", "content": "你是助手"},
            {"role": "user", "content": "你好"},
        ],
    )
    assert system == "你是助手"
    assert anth == [{"role": "user", "content": "你好"}]


def test_request_multiple_system_messages_merged():
    """多条 system 消息用 \\n\\n 合并保结构。"""
    system, _ = _translate_messages_to_anthropic(
        "顶级 system",
        [
            {"role": "system", "content": "再一条 system"},
            {"role": "system", "content": "第三条"},
            {"role": "user", "content": "x"},
        ],
    )
    assert system == "顶级 system\n\n再一条 system\n\n第三条"


def test_request_tool_messages_merged_to_user_tool_result_block():
    """连续 role=tool 消息合并成一条 user + N tool_result block。"""
    _, anth = _translate_messages_to_anthropic(
        "",
        [
            {"role": "user", "content": "查一下"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "search", "arguments": '{"q":"a"}'},
                    },
                    {
                        "id": "call_2",
                        "type": "function",
                        "function": {"name": "search", "arguments": '{"q":"b"}'},
                    },
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "结果 A"},
            {"role": "tool", "tool_call_id": "call_2", "content": "结果 B"},
            {"role": "user", "content": "继续"},
        ],
    )
    # 第三条应该是合并的 user + 2 tool_result block
    merged = anth[2]
    assert merged["role"] == "user"
    assert isinstance(merged["content"], list)
    assert len(merged["content"]) == 2
    assert merged["content"][0] == {
        "type": "tool_result",
        "tool_use_id": "call_1",
        "content": "结果 A",
    }
    assert merged["content"][1] == {
        "type": "tool_result",
        "tool_use_id": "call_2",
        "content": "结果 B",
    }
    # 最后一条还是普通 user
    assert anth[3] == {"role": "user", "content": "继续"}


def test_request_assistant_tool_calls_to_content_blocks():
    """assistant.tool_calls → content blocks（text + tool_use）。"""
    _, anth = _translate_messages_to_anthropic(
        "",
        [
            {
                "role": "assistant",
                "content": "我去查",
                "tool_calls": [
                    {
                        "id": "call_abc",
                        "type": "function",
                        "function": {"name": "search", "arguments": '{"q":"foo"}'},
                    }
                ],
            },
        ],
    )
    assert anth[0]["role"] == "assistant"
    blocks = anth[0]["content"]
    assert blocks[0] == {"type": "text", "text": "我去查"}
    assert blocks[1] == {
        "type": "tool_use",
        "id": "call_abc",
        "name": "search",
        "input": {"q": "foo"},
    }


def test_request_tool_call_arguments_json_parse():
    """function.arguments JSON 字符串 → input dict。"""
    _, anth = _translate_messages_to_anthropic(
        "",
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "x",
                        "type": "function",
                        "function": {
                            "name": "f",
                            "arguments": '{"nested": {"k": 1}, "arr": [1,2]}',
                        },
                    }
                ],
            }
        ],
    )
    tool_use = anth[0]["content"][0]
    assert tool_use["input"] == {"nested": {"k": 1}, "arr": [1, 2]}


def test_request_tool_call_arguments_invalid_json_fallback():
    """arguments 不是合法 JSON 时退化 ``{"_raw": original}`` 不 raise。"""
    _, anth = _translate_messages_to_anthropic(
        "",
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "x",
                        "type": "function",
                        "function": {
                            "name": "f",
                            "arguments": "not-json-at-all{",
                        },
                    }
                ],
            }
        ],
    )
    tool_use = anth[0]["content"][0]
    assert tool_use["input"] == {"_raw": "not-json-at-all{"}


def test_request_tools_function_flattened_to_anthropic():
    """OpenAI 嵌套 tools → Anthropic 扁平。"""
    out = _translate_tools_to_anthropic(
        [
            {
                "type": "function",
                "function": {
                    "name": "search",
                    "description": "搜索",
                    "parameters": {"type": "object", "properties": {"q": {"type": "string"}}},
                },
            }
        ]
    )
    assert out == [
        {
            "name": "search",
            "description": "搜索",
            "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}},
        }
    ]


def test_request_tools_already_anthropic_flat_passthrough():
    """已经是 Anthropic 扁平形态时原样保留（loop_r2 当前直接传扁平）。"""
    out = _translate_tools_to_anthropic(
        [{"name": "f", "description": "d", "input_schema": {"type": "object"}}]
    )
    assert out == [{"name": "f", "description": "d", "input_schema": {"type": "object"}}]


def test_request_tool_choice_auto_translation():
    assert _translate_tool_choice_to_anthropic("auto") == {"type": "auto"}


def test_request_tool_choice_required_to_any():
    assert _translate_tool_choice_to_anthropic("required") == {"type": "any"}


def test_request_tool_choice_specific_function_translation():
    result = _translate_tool_choice_to_anthropic(
        {"type": "function", "function": {"name": "search"}}
    )
    assert result == {"type": "tool", "name": "search"}


def test_request_tool_choice_none_drops_field():
    """``"none"`` 翻译成 None 表示调用方不传 tool_choice 字段。"""
    assert _translate_tool_choice_to_anthropic("none") is None


def test_request_tool_choice_unset_returns_none():
    assert _translate_tool_choice_to_anthropic(None) is None


# ---------------------------------------------------------------------------
# 响应方向单元测试
# ---------------------------------------------------------------------------


def test_response_text_blocks_merged_to_content_string():
    """多个 text block 合并为单 content 字符串。"""
    resp = _FakeMessage(
        content=[_FakeTextBlock("第一段"), _FakeTextBlock("第二段")],
        stop_reason="end_turn",
    )
    out = _translate_response_to_openai(resp, model="claude-x")
    assert out["choices"][0]["message"]["content"] == "第一段第二段"


def test_response_tool_use_blocks_to_tool_calls():
    """tool_use block → tool_calls 数组。"""
    resp = _FakeMessage(
        content=[
            _FakeTextBlock("我去查"),
            _FakeToolUseBlock("toolu_xyz", "search", {"q": "foo"}),
        ],
        stop_reason="tool_use",
    )
    out = _translate_response_to_openai(resp, model="claude-x")
    msg = out["choices"][0]["message"]
    assert msg["content"] == "我去查"
    assert msg["tool_calls"][0] == {
        "id": "toolu_xyz",
        "type": "function",
        "function": {"name": "search", "arguments": '{"q": "foo"}'},
    }


def test_response_only_tool_use_content_none():
    """只有 tool_use 没有 text → content=None。"""
    resp = _FakeMessage(
        content=[_FakeToolUseBlock("t1", "search", {"q": "x"})],
        stop_reason="tool_use",
    )
    out = _translate_response_to_openai(resp, model="claude-x")
    assert out["choices"][0]["message"]["content"] is None


def test_response_only_text_tool_calls_none():
    """只有 text 没有 tool_use → tool_calls=None（不写空 list）。"""
    resp = _FakeMessage(
        content=[_FakeTextBlock("纯文本")],
        stop_reason="end_turn",
    )
    out = _translate_response_to_openai(resp, model="claude-x")
    assert out["choices"][0]["message"]["tool_calls"] is None


def test_response_function_arguments_is_json_string():
    """input dict → function.arguments JSON 字符串。"""
    resp = _FakeMessage(
        content=[_FakeToolUseBlock("t", "f", {"a": 1, "b": "中文"})],
        stop_reason="tool_use",
    )
    out = _translate_response_to_openai(resp, model="claude-x")
    args = out["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
    parsed = json.loads(args)
    assert parsed == {"a": 1, "b": "中文"}
    # ensure_ascii=False → 中文不转义
    assert "中文" in args


@pytest.mark.parametrize(
    "stop_reason,expected_finish",
    [
        ("tool_use", "tool_calls"),
        ("end_turn", "stop"),
        ("max_tokens", "length"),
        ("stop_sequence", "stop"),
    ],
)
def test_response_stop_reason_to_finish_reason_mapping(stop_reason, expected_finish):
    resp = _FakeMessage(content=[_FakeTextBlock("x")], stop_reason=stop_reason)
    out = _translate_response_to_openai(resp, model="claude-x")
    assert out["choices"][0]["finish_reason"] == expected_finish


def test_response_usage_field_renamed():
    """input_tokens → prompt_tokens、output_tokens → completion_tokens + total。"""
    resp = _FakeMessage(content=[_FakeTextBlock("x")])
    resp.usage = _FakeUsage(input_tokens=123, output_tokens=45)
    out = _translate_response_to_openai(resp, model="claude-x")
    assert out["usage"] == {
        "prompt_tokens": 123,
        "completion_tokens": 45,
        "total_tokens": 168,
    }


def test_response_has_object_chat_completion_envelope():
    """OpenAI 形态强校验：object=chat.completion、choices[0].index=0。"""
    resp = _FakeMessage(content=[_FakeTextBlock("x")])
    out = _translate_response_to_openai(resp, model="claude-x")
    assert out["object"] == "chat.completion"
    assert out["choices"][0]["index"] == 0


# ---------------------------------------------------------------------------
# 端到端 roundtrip
# ---------------------------------------------------------------------------


def test_anthropic_r2_complete_roundtrip_text_only():
    """纯文本回复：OpenAI 进 → SDK 调用 → OpenAI 出。"""
    fake_resp = _FakeMessage(
        content=[_FakeTextBlock("最终答复")],
        stop_reason="end_turn",
    )
    client = _FakeAnthropicClient(fake_resp)
    adapter = AnthropicAdapter(api_key="fake", anthropic_client=client)

    out = adapter.messages_create(
        model="claude-sonnet-4-6",
        system="你是助手",
        tools=[{"name": "search", "description": "d", "input_schema": {"type": "object"}}],
        messages=[{"role": "user", "content": "问题"}],
        max_tokens=1000,
    )

    # 喂给 SDK 的 kwargs 是 Anthropic 形态
    assert client.captured["system"] == "你是助手"
    assert client.captured["messages"] == [{"role": "user", "content": "问题"}]
    assert client.captured["tools"][0]["name"] == "search"
    assert "input_schema" in client.captured["tools"][0]

    # 返回是 OpenAI 形态
    assert out["object"] == "chat.completion"
    assert out["choices"][0]["message"]["content"] == "最终答复"
    assert out["choices"][0]["message"]["tool_calls"] is None
    assert out["choices"][0]["finish_reason"] == "stop"


def test_anthropic_r2_complete_roundtrip_with_tool_call():
    """含 tool_call 回合：assistant tool_calls 出 → tool 消息回 → 第二轮 SDK 调用。"""
    fake_resp = _FakeMessage(
        content=[
            _FakeTextBlock("查一下"),
            _FakeToolUseBlock("call_first", "search", {"q": "foo"}),
        ],
        stop_reason="tool_use",
    )
    client = _FakeAnthropicClient(fake_resp)
    adapter = AnthropicAdapter(api_key="fake", anthropic_client=client)

    # 模拟 loop_r2 的第二轮调用：含 assistant tool_calls + tool 消息
    out = adapter.messages_create(
        model="claude-sonnet-4-6",
        system="",
        tools=[{"name": "search", "description": "d", "input_schema": {"type": "object"}}],
        messages=[
            {"role": "user", "content": "请帮忙"},
            {
                "role": "assistant",
                "content": "我查一下",
                "tool_calls": [
                    {
                        "id": "call_first",
                        "type": "function",
                        "function": {"name": "search", "arguments": '{"q":"foo"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_first", "content": "搜索结果"},
        ],
        max_tokens=1000,
    )

    # 喂给 SDK 的 messages 翻译形态校验
    sent = client.captured["messages"]
    assert sent[0] == {"role": "user", "content": "请帮忙"}
    # 第二条 assistant 应该是 block 列表
    assert sent[1]["role"] == "assistant"
    assert sent[1]["content"][0] == {"type": "text", "text": "我查一下"}
    assert sent[1]["content"][1] == {
        "type": "tool_use",
        "id": "call_first",
        "name": "search",
        "input": {"q": "foo"},
    }
    # 第三条应该是合并的 user + tool_result
    assert sent[2]["role"] == "user"
    assert sent[2]["content"] == [
        {"type": "tool_result", "tool_use_id": "call_first", "content": "搜索结果"}
    ]

    # 返回形态校验
    assert out["choices"][0]["finish_reason"] == "tool_calls"
    assert out["choices"][0]["message"]["tool_calls"][0]["id"] == "call_first"


# ---------------------------------------------------------------------------
# 构造行为：lazy SDK 依赖
# ---------------------------------------------------------------------------


def test_anthropic_r2_construction_does_not_eagerly_import_sdk():
    """构造时不应该 eager import anthropic SDK——单测路径用 mock 注入。"""
    adapter = AnthropicAdapter(api_key="fake-key", anthropic_client=None)
    assert adapter is not None


def test_anthropic_r2_uses_injected_client():
    """注入的 mock client 应该被直接使用，不触发 SDK lazy import。"""
    client = _FakeAnthropicClient(
        _FakeMessage(content=[_FakeTextBlock("ok")])
    )
    adapter = AnthropicAdapter(api_key="fake", anthropic_client=client)
    adapter.messages_create(
        model="claude-x",
        system="",
        tools=[],
        messages=[{"role": "user", "content": "q"}],
        max_tokens=100,
    )
    assert client.captured["model"] == "claude-x"
