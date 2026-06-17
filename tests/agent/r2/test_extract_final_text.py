"""Backlog B-1：adapter Protocol 响应解析方法单测。

覆盖 ``AnthropicAdapter.extract_final_text`` / ``extract_usage_tokens`` 与
``DeepSeekAdapter.extract_final_text`` / ``extract_usage_tokens``——两者
在 r2 下都吃 OpenAI ``ChatCompletion`` 形态响应（plain dict 或 SDK
风格 ducktype object），共用 ``_internal.loop_shared.read_openai_*``
实现。本测试断言：

1. 两 adapter 在 r2 形态正常 response 下都能抽出干净文本
2. usage 字段名按 OpenAI ``prompt_tokens`` / ``completion_tokens`` 读
3. response 缺字段时优雅降级——文本返空串、usage 返 ``(0, 0)``，不抛
4. dict / SDK object ducktype 两种形态都兼容

不依赖任何 SDK——构造 plain dict / 小 ducktype object 即可。
"""

from __future__ import annotations

from typing import Any

import pytest

from bookscope.agent.adapters.anthropic_r2 import AnthropicAdapter
from bookscope.agent.adapters.deepseek_r2 import DeepSeekAdapter

# ---------------------------------------------------------------------------
# Ducktype 替身：模拟 SDK pydantic 对象的属性访问形态
# ---------------------------------------------------------------------------


class _Usage:
    def __init__(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _Message:
    def __init__(self, content: str | None) -> None:
        self.content = content


class _Choice:
    def __init__(self, message: _Message) -> None:
        self.message = message


class _Response:
    def __init__(
        self,
        choices: list[_Choice] | None,
        usage: _Usage | None,
    ) -> None:
        self.choices = choices or []
        self.usage = usage


# ---------------------------------------------------------------------------
# Adapter 构造小工厂——adapter 构造时不接 SDK，传 dummy client 跳 lazy import
# ---------------------------------------------------------------------------


def _anthropic() -> AnthropicAdapter:
    return AnthropicAdapter(api_key="sk-test", anthropic_client=object())


def _deepseek() -> DeepSeekAdapter:
    return DeepSeekAdapter(api_key="sk-test", openai_client=object())


@pytest.fixture(params=[_anthropic, _deepseek], ids=["anthropic", "deepseek"])
def adapter(request: pytest.FixtureRequest) -> Any:
    """两 adapter 跑同一组形态断言——r2 下行为必须一致。"""
    return request.param()


# ---------------------------------------------------------------------------
# extract_final_text
# ---------------------------------------------------------------------------


class TestExtractFinalText:
    """两 adapter 抽 final 文本——OpenAI ``choices[0].message.content``。"""

    def test_extracts_content_from_plain_dict(self, adapter: Any) -> None:
        """plain dict 形态（``messages_create`` 返回 / L2 缓存反序列化）。"""
        response = {
            "choices": [
                {
                    "message": {"content": "主要角色包括朱元璋。"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20},
        }
        assert adapter.extract_final_text(response) == "主要角色包括朱元璋。"

    def test_extracts_content_from_sdk_object(self, adapter: Any) -> None:
        """SDK 风格 ducktype object——属性访问形态。"""
        response = _Response(
            choices=[_Choice(_Message("故事发生在明朝。"))],
            usage=_Usage(50, 10),
        )
        assert adapter.extract_final_text(response) == "故事发生在明朝。"

    def test_strips_whitespace(self, adapter: Any) -> None:
        """``strip()`` 抹掉首尾空白——下游 JSON 解析对头部 ``\n`` 敏感。"""
        response = {
            "choices": [{"message": {"content": "  含前后空白  \n"}}],
        }
        assert adapter.extract_final_text(response) == "含前后空白"

    def test_missing_choices_returns_empty(self, adapter: Any) -> None:
        """``choices`` 缺失 / 空列表 → 返空串，不抛。"""
        assert adapter.extract_final_text({}) == ""
        assert adapter.extract_final_text({"choices": []}) == ""

    def test_missing_message_returns_empty(self, adapter: Any) -> None:
        """choice 缺 message 字段 → 返空串。"""
        response = {"choices": [{"finish_reason": "stop"}]}
        assert adapter.extract_final_text(response) == ""

    def test_none_content_returns_empty(self, adapter: Any) -> None:
        """``content=None``（纯 tool_calls 场景）→ 返空串。"""
        response = {
            "choices": [
                {
                    "message": {"content": None, "tool_calls": [{"id": "x"}]},
                }
            ]
        }
        assert adapter.extract_final_text(response) == ""

    def test_response_none_returns_empty(self, adapter: Any) -> None:
        """response 本身为 None → 返空串。"""
        assert adapter.extract_final_text(None) == ""


# ---------------------------------------------------------------------------
# extract_usage_tokens
# ---------------------------------------------------------------------------


class TestExtractUsageTokens:
    """两 adapter 抽 token usage——OpenAI ``prompt_tokens`` / ``completion_tokens``。

    Backlog B-1 重要约束：r2 反向翻译已把 Anthropic ``input_tokens`` /
    ``output_tokens`` 重命名为 ``prompt_tokens`` / ``completion_tokens``，
    所以两 adapter 都读后者；不再自适应两套字段名。
    """

    def test_reads_openai_field_names_from_dict(self, adapter: Any) -> None:
        """``prompt_tokens`` / ``completion_tokens`` 从 plain dict 读出。"""
        response = {
            "choices": [{"message": {"content": "x"}}],
            "usage": {"prompt_tokens": 1234, "completion_tokens": 567},
        }
        assert adapter.extract_usage_tokens(response) == (1234, 567)

    def test_reads_openai_field_names_from_sdk_object(self, adapter: Any) -> None:
        """SDK 风格属性访问形态。"""
        response = _Response(
            choices=[_Choice(_Message("x"))],
            usage=_Usage(prompt_tokens=88, completion_tokens=22),
        )
        assert adapter.extract_usage_tokens(response) == (88, 22)

    def test_missing_usage_returns_zero(self, adapter: Any) -> None:
        """``usage`` 字段缺失 → ``(0, 0)``，不抛。"""
        assert adapter.extract_usage_tokens({}) == (0, 0)
        assert adapter.extract_usage_tokens({"choices": []}) == (0, 0)

    def test_none_usage_returns_zero(self, adapter: Any) -> None:
        """``usage=None`` → ``(0, 0)``。"""
        response = _Response(
            choices=[_Choice(_Message("x"))],
            usage=None,
        )
        assert adapter.extract_usage_tokens(response) == (0, 0)

    def test_partial_usage_degrades_gracefully(self, adapter: Any) -> None:
        """单字段缺失 → 缺的那个降级为 0。"""
        response = {"usage": {"prompt_tokens": 100}}
        assert adapter.extract_usage_tokens(response) == (100, 0)

    def test_anthropic_field_names_are_not_read(self, adapter: Any) -> None:
        """r1 字段名 ``input_tokens`` / ``output_tokens`` 不被读取——
        Backlog B-1 删了双字段名 sniffing。response 只挂 r1 字段名时
        usage 视作未填。
        """
        response = {"usage": {"input_tokens": 999, "output_tokens": 999}}
        assert adapter.extract_usage_tokens(response) == (0, 0)


# ---------------------------------------------------------------------------
# Protocol 契约——两 adapter 都暴露这两个方法
# ---------------------------------------------------------------------------


class TestProtocolContract:
    def test_both_adapters_expose_extract_methods(self) -> None:
        """``AnthropicAdapter`` 与 ``DeepSeekAdapter`` 都实现 Protocol 方法。"""
        for adapter in (_anthropic(), _deepseek()):
            assert hasattr(adapter, "extract_final_text")
            assert hasattr(adapter, "extract_usage_tokens")
            assert callable(adapter.extract_final_text)
            assert callable(adapter.extract_usage_tokens)
