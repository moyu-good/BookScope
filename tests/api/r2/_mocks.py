"""``tests/api/r2`` 共用的 OpenAI 形态桩工厂。

ADR-007 把默认 protocol 从 r1（Anthropic ``content_blocks``/``stop_reason``）
切到 r2（OpenAI ``choices``/``finish_reason`` + ``message.tool_calls``）。
``tests/api/r2/`` 下每个测试都要构造 OpenAI 形态响应桩——同一组替身类
``_R2Response`` / ``_R2Choice`` / ``_R2Message`` / ``_R2ToolCall`` 在四个文件
（``test_agent_ask_r2`` / ``test_error_handling_e2e_r2`` / ``test_routes_agent_r2``
/ ``test_review_hint_injection_r2``）里跨 30+ 测试反复出现，所以抽到这里。

抽进来的边界：

- **抽**：纯形态构造（``r2_tool_call_response`` / ``r2_final_text_response``
  / ``R2FakeAdapter`` 替身类）——这些是 OpenAI Python SDK 在 BookScope
  adapter 层的最小 ducktype
- **不抽**：测试编排（``monkeypatch.setattr`` / ``patch`` / ``client.post``）
  ——那是每个测试自己的剧本

命名前缀全部带 ``R2`` / ``r2_``，防与 r1 同语义 helper 混淆。每个测试要的
backends fakes（``_FakeSearchBackend`` 等）保留在各自测试文件——backends 在
r1/r2 之间形态完全相同，与 protocol 无关，与抽 helper 的判断标准（"r2 = OpenAI
choices/tool_calls 形态"）不重合。
"""

from __future__ import annotations

import json
from typing import Any


class R2Usage:
    """OpenAI ``usage`` 替身：``prompt_tokens`` / ``completion_tokens``。"""

    def __init__(self, prompt_tokens: int = 10, completion_tokens: int = 5) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class R2Function:
    """OpenAI ``tool_call.function`` 替身——name + arguments JSON 字符串。"""

    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class R2ToolCall:
    """OpenAI ``ChatCompletionMessageToolCall`` 替身——id + type + function。"""

    def __init__(self, tc_id: str, name: str, arguments: str) -> None:
        self.id = tc_id
        self.type = "function"
        self.function = R2Function(name, arguments)


class R2Message:
    """OpenAI ``ChatCompletionMessage`` 替身。

    含 tool_calls 时 content 通常为 None；纯文本回复时 tool_calls 为 None。
    """

    def __init__(
        self,
        *,
        content: str | None = None,
        tool_calls: list[R2ToolCall] | None = None,
    ) -> None:
        self.role = "assistant"
        self.content = content
        self.tool_calls = tool_calls or None


class R2Choice:
    def __init__(self, message: R2Message, finish_reason: str) -> None:
        self.message = message
        self.finish_reason = finish_reason


class R2Response:
    """OpenAI ``ChatCompletion`` 替身：choices + usage。"""

    def __init__(self, choices: list[R2Choice]) -> None:
        self.choices = choices
        self.usage = R2Usage()


def r2_tool_call_response(
    *,
    name: str,
    arguments: dict[str, Any],
    call_id: str = "call_001",
) -> R2Response:
    """构造一轮 OpenAI 形态 tool_calls 响应（``finish_reason="tool_calls"``）。"""
    tc = R2ToolCall(call_id, name, json.dumps(arguments, ensure_ascii=False))
    msg = R2Message(content=None, tool_calls=[tc])
    return R2Response([R2Choice(msg, finish_reason="tool_calls")])


def r2_final_text_response(
    answer: str,
    citations: list[dict[str, Any]],
) -> R2Response:
    """构造一轮 OpenAI 形态 final answer 响应（``finish_reason="stop"``）。"""
    payload = json.dumps(
        {"answer": answer, "citations": citations}, ensure_ascii=False
    )
    msg = R2Message(content=payload, tool_calls=None)
    return R2Response([R2Choice(msg, finish_reason="stop")])


def r2_raw_text_response(content: str) -> R2Response:
    """构造一轮 OpenAI 形态 ``finish_reason="stop"`` + 任意 content 文本。

    用来测 LLMFormatError 路径（非法 JSON 或缺 citations）。
    """
    msg = R2Message(content=content, tool_calls=None)
    return R2Response([R2Choice(msg, finish_reason="stop")])


class R2FakeAdapter:
    """r2 路径 fake LLM adapter——按队列依次吐 r2 response 或抛固定异常。

    两种模式：

    - 预置 response 序列：依次弹出
    - ``raise_exc=Exc()``：每次 ``messages_create`` 调用都抛同一异常，用来测
      重试链耗尽路径

    可选 ``record_system=True`` 记录每次调用的 ``system`` kw——review hint
    注入测试要断言 ``system_prompt`` 内容。
    """

    def __init__(
        self,
        responses: list[R2Response] | None = None,
        *,
        raise_exc: Exception | None = None,
        record_system: bool = False,
    ) -> None:
        self._responses = list(responses or [])
        self._raise_exc = raise_exc
        self.call_count = 0
        self.last_kwargs: dict[str, Any] | None = None
        self.system_prompts: list[str] = []
        self._record_system = record_system

    def messages_create(self, **kwargs: Any) -> Any:
        self.call_count += 1
        self.last_kwargs = kwargs
        if self._record_system:
            self.system_prompts.append(str(kwargs.get("system", "")))
        if self._raise_exc is not None:
            raise self._raise_exc
        if not self._responses:
            raise AssertionError("R2FakeAdapter ran out of prepared responses")
        return self._responses.pop(0)

    def extract_final_text(self, response: Any) -> str:
        """r2 OpenAI 形态：读 ``choices[0].message.content`` 字符串。

        Backlog B-1 落地后 ``fast_path`` 通过 adapter Protocol 方法拿文本，
        本 fake 自己实现对应形态——跟真实 ``DeepSeekAdapter`` /
        ``AnthropicAdapter`` 在 r2 下的形态一致。
        """
        if response is None:
            return ""
        choices = getattr(response, "choices", None) or []
        if not choices:
            return ""
        message = getattr(choices[0], "message", None)
        if message is None:
            return ""
        content = getattr(message, "content", None)
        if isinstance(content, str):
            return content.strip()
        return ""

    def extract_usage_tokens(self, response: Any) -> tuple[int, int]:
        """r2 OpenAI 形态：``usage.prompt_tokens`` / ``completion_tokens``。"""
        usage = getattr(response, "usage", None)
        if usage is None:
            return 0, 0
        return int(getattr(usage, "prompt_tokens", 0) or 0), int(
            getattr(usage, "completion_tokens", 0) or 0
        )
