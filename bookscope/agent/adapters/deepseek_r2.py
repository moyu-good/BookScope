"""``bookscope.agent.adapters.deepseek_r2`` —— r2 下 DeepSeek 系 OpenAI 兼容 adapter。

ADR-007 D-3 决策：r2 切到 OpenAI function calling 主格式后，DeepSeek 系
adapter（DeepSeek / MiniMax / GLM / Qwen / Kimi 等 OpenAI 兼容 endpoint）
退化成 passthrough——请求方向去掉 Anthropic→OpenAI 翻译直接 forward
给 ``openai`` SDK，响应方向去掉 OpenAI→Anthropic 反向翻译，转成 plain
dict 返回（字段名保留 OpenAI 原样）。

### 保留下来的怪癖兜底

passthrough **不**等于 "什么都不做"——provider 怪癖兜底必须留：

1. ``_strip_thinking_tags``：reasoning model 在 ``content`` 里 inline
   返回 ``<think>...</think>``，需抹掉（minimax-m2.x / deepseek-r1 /
   qwen-qwq / glm-zero）
2. ``_translate_error`` / ``_looks_like_content_filter`` /
   ``_CONTENT_FILTER_HINTS``：MiniMax 422 内容审查识别 → ``ContentFiltered``
3. ``arguments`` 空串 / ``finish_reason`` 缺省 / ``usage`` 缺失等宽容降级

### 与 r1 实现的关系

不继承 r1 ``DeepSeekAdapter``——继承会把双向翻译方法仍留在类里。本类是
独立实现，从 r1 复用 ``_strip_thinking_tags`` / ``_translate_error`` /
``_looks_like_content_filter`` 等"怪癖兜底" helper（这些 helper 跟形态
无关，安全复用），双向翻译代码（``_to_openai_*`` / ``_from_openai_*``）
完全不引入。
"""

from __future__ import annotations

from typing import Any

from bookscope.agent._internal.deepseek_shared import (
    DEEPSEEK_DEFAULT_BASE_URL,
)
from bookscope.agent._internal.deepseek_shared import (
    looks_like_content_filter as _looks_like_content_filter,
)
from bookscope.agent._internal.deepseek_shared import (
    strip_thinking_tags as _strip_thinking_tags,
)
from bookscope.agent._internal.deepseek_shared import (
    translate_error as _translate_error,
)
from bookscope.agent._internal.loop_shared import (
    read_openai_choice_content as _read_openai_choice_content,
)
from bookscope.agent._internal.loop_shared import (
    read_openai_usage as _read_openai_usage,
)


class DeepSeekAdapter:
    """把 OpenAI 兼容 endpoint 包装成 passthrough ``LLMClient``（r2）。

    构造签名 + ``messages_create`` 方法签名跟 r1 ``DeepSeekAdapter`` 一致，
    使调用方平滑替换。但响应形态从 r1 的 Anthropic 风格 dict
    （``{stop_reason, content[blocks], usage{input_tokens, output_tokens}}``）
    切到 OpenAI 原生 dict（``{choices[{message, finish_reason}],``
    ``usage{prompt_tokens, completion_tokens}}``）。

    Args:
        api_key: provider API key。
        base_url: OpenAI 兼容 endpoint；默认 DeepSeek 官方地址。
        openai_client: 测试用 mock client；生产传 ``None`` 时 lazy import
            ``openai`` 自行构造。
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEEPSEEK_DEFAULT_BASE_URL,
        openai_client: Any | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        if openai_client is not None:
            self._client = openai_client
        else:
            self._client = self._build_default_client(api_key, base_url)

    @staticmethod
    def _build_default_client(api_key: str, base_url: str) -> Any:
        """Lazy import ``openai`` 并构造 client；未装时清晰提示。"""
        try:
            import openai  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(
                "DeepSeekAdapter 需要 openai SDK；请先运行："
                "`pip install openai`"
            ) from exc
        return openai.OpenAI(api_key=api_key, base_url=base_url)

    # ------------------------------------------------------------------
    # 对外方法
    # ------------------------------------------------------------------

    def messages_create(
        self,
        *,
        model: str,
        system: str,
        tools: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        max_tokens: int,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        """Passthrough 调用 OpenAI 兼容 endpoint。

        约定：本方法在 r2 路径下被 ``loop_r2.AgentLoop`` 调用，传入的
        ``messages`` 已经是 OpenAI 形态（``role`` 含 ``user`` / ``assistant``
        / ``tool``；assistant 可能带 ``tool_calls``）。``system`` 单独传入，
        本方法 prepend 一条 ``{"role": "system", ...}``。``tools`` 仍是
        Anthropic 风格 ``{name, description, input_schema}``（``loop_r2.
        _build_tool_schemas`` 注释解释了原因），这里翻译成 OpenAI function
        spec。

        响应转成 plain dict（``ChatCompletion`` → ``{choices, usage}``）
        返回，字段名保留 OpenAI 原样。
        """
        oai_messages: list[dict[str, Any]] = []
        if system:
            oai_messages.append({"role": "system", "content": system})
        oai_messages.extend(messages)

        oai_tools = _tools_to_openai_function_spec(tools) if tools else None

        # temperature 按 DeepSeek 官方场景表调教：抽取 / 分类类调用方传 0.0
        # （官方"代码/数据"档），生成 / 评分类不传走服务端默认 1.0（官方
        # "数据分析"档）。None 时不带该字段，行为与改动前一致。
        create_kwargs: dict[str, Any] = {
            "model": model,
            "messages": oai_messages,
            "max_tokens": max_tokens,
        }
        if oai_tools is not None:
            create_kwargs["tools"] = oai_tools
        if temperature is not None:
            create_kwargs["temperature"] = temperature

        try:
            response = self._client.chat.completions.create(**create_kwargs)
        except Exception as exc:  # noqa: BLE001
            raise _translate_error(exc) from exc

        return _response_to_plain_dict(response)

    # ------------------------------------------------------------------
    # LLMClient Protocol：响应解析（Backlog B-1）
    # ------------------------------------------------------------------

    def extract_final_text(self, response: Any) -> str:
        """从 OpenAI 形态 response 抽 ``choices[0].message.content``。

        DeepSeek 系本来就是 OpenAI 原生形态，passthrough 之后字段名不变。
        """
        return _read_openai_choice_content(response)

    def extract_usage_tokens(self, response: Any) -> tuple[int, int]:
        """抽 ``(prompt_tokens, completion_tokens)``。"""
        return _read_openai_usage(response)


# ---------------------------------------------------------------------------
# tools schema 翻译（保留：本来就该在 adapter 层做）
# ---------------------------------------------------------------------------


def _tools_to_openai_function_spec(
    tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """把 ``{name, description, input_schema}`` 翻译成 OpenAI function spec。

    这不算"协议翻译"——tools 注入 schema 由 adapter 兜底翻译是 ADR-003
    早就规定的职责（loop 层用 Anthropic 风格，adapter 落到 provider 各自
    形态）；ADR-007 D-1 没改这一层职责划分。
    """
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {}),
            },
        }
        for t in tools
    ]


# ---------------------------------------------------------------------------
# 响应转 plain dict（无形态翻译，仅 SDK 对象 → dict + reasoning strip）
# ---------------------------------------------------------------------------


def _response_to_plain_dict(response: Any) -> dict[str, Any]:
    """``ChatCompletion`` SDK 对象 → plain dict（OpenAI 原生形态）。

    与 r1 ``_from_openai_response`` 的关键差异：**不**把 tool_calls 拆成
    ``tool_use`` blocks、**不**把 ``finish_reason`` 映射到 ``stop_reason``、
    **不**重命名 ``prompt_tokens`` / ``completion_tokens``——直接保留 OpenAI
    字段名给 ``loop_r2`` 消费。

    保留的兜底：

    - ``_strip_thinking_tags``：reasoning model ``<think>`` 块抹除
    - ``arguments`` 字符串原样传递（loop_r2 ``_dispatch_tools_parallel``
      负责 JSON 解析 + 空串降级）
    - ``finish_reason`` / ``usage`` 缺省时降级（None / 0）
    """
    if isinstance(response, dict):
        # 测试有时直接传 dict——把它视为已经是目标形态，仅做 think strip
        choices = response.get("choices") or []
        if choices:
            first = choices[0]
            if isinstance(first, dict):
                msg = first.get("message") or {}
                if isinstance(msg, dict):
                    content = msg.get("content")
                    if isinstance(content, str) and content:
                        msg["content"] = _strip_thinking_tags(content) or None
        return response

    choices_out: list[dict[str, Any]] = []
    for choice in getattr(response, "choices", []) or []:
        message = getattr(choice, "message", None)

        content_raw = getattr(message, "content", None) if message else None
        if isinstance(content_raw, str) and content_raw:
            content_clean: str | None = _strip_thinking_tags(content_raw)
            if not content_clean:
                content_clean = None
        else:
            content_clean = content_raw if isinstance(content_raw, str) else None

        tool_calls_out: list[dict[str, Any]] = []
        for tc in getattr(message, "tool_calls", None) or []:
            fn = getattr(tc, "function", None)
            tool_calls_out.append(
                {
                    "id": getattr(tc, "id", "") or "",
                    "type": "function",
                    "function": {
                        "name": getattr(fn, "name", "") if fn else "",
                        # arguments 原样保留（JSON 字符串）；loop_r2 自行 parse
                        "arguments": getattr(fn, "arguments", "") if fn else "",
                    },
                }
            )

        msg_out: dict[str, Any] = {
            "role": "assistant",
            "content": content_clean,
        }
        if tool_calls_out:
            msg_out["tool_calls"] = tool_calls_out

        choices_out.append(
            {
                "message": msg_out,
                "finish_reason": getattr(choice, "finish_reason", None) or "stop",
            }
        )

    usage_raw = getattr(response, "usage", None)
    usage_out: dict[str, Any] = {
        "prompt_tokens": int(getattr(usage_raw, "prompt_tokens", 0) or 0)
        if usage_raw
        else 0,
        "completion_tokens": int(getattr(usage_raw, "completion_tokens", 0) or 0)
        if usage_raw
        else 0,
        # DeepSeek context caching 命中观测：官方在 usage 里给
        # prompt_cache_hit_tokens / prompt_cache_miss_tokens（命中按 1/50 价）。
        # 之前这两字段被直接丢弃——BookScope 从不知道缓存命中率，只能从
        # DeepSeek 后台账单看。保留进 usage 让 trace 记录、batch 元数据透出。
        "prompt_cache_hit_tokens": int(
            getattr(usage_raw, "prompt_cache_hit_tokens", 0) or 0
        )
        if usage_raw
        else 0,
        "prompt_cache_miss_tokens": int(
            getattr(usage_raw, "prompt_cache_miss_tokens", 0) or 0
        )
        if usage_raw
        else 0,
    }

    return {
        "choices": choices_out,
        "usage": usage_out,
    }


__all__ = ["DeepSeekAdapter", "_looks_like_content_filter"]
