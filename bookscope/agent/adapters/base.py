"""``LLMClient`` Protocol —— provider-agnostic LLM 客户端接口。

ADR-003 的核心抽象：所有 provider adapter 实现一个同步方法
``messages_create(...)`` 跟两个响应解析方法 ``extract_final_text`` /
``extract_usage_tokens``。``AgentLoop`` / ``fast_path`` 都通过这个接口
与底层模型对话、读响应，完全不依赖任何具体 SDK 或响应形态。

Backlog B-1（2026-05-15 上线）把 ``extract_final_text`` /
``extract_usage_tokens`` 从原模块级 helper 下沉到 adapter——之前的
helper 靠"看响应有没有 ``choices`` 字段"做 r1 / r2 双形态 sniffing；
Sprint 7 r1 退役后双形态兼容废，把抽取逻辑彻底丢回各自 adapter，
每个 adapter 按自己 provider 形态读，零 sniffing 残留。

Protocol 标记 ``@runtime_checkable``，测试里用
``isinstance(adapter, LLMClient)`` 做结构校验。
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LLMClient(Protocol):
    """Provider-agnostic LLM 客户端接口。

    所有 provider 通过 adapter 实现此 Protocol，使 ``AgentLoop``
    完全不依赖任何具体 SDK。方法签名刻意固定为**关键字参数**，避免
    位置参数歧义；返回形态刻意用 plain ``dict`` 而不是 Pydantic 模型，
    因为 loop 层还要做 content-block 枚举，dict 访问最灵活。
    """

    def messages_create(
        self,
        *,
        model: str,
        system: str,
        tools: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        max_tokens: int,
    ) -> dict[str, Any]:
        """同步调用一轮 LLM。返回 Anthropic 风格的 response dict。

        输入形态（Anthropic 风格，loop 产生）：

        - ``system``：system prompt 字符串
        - ``tools``：``[{"name", "description", "input_schema"}]``
          其中 ``input_schema`` 是 JSON Schema dict。
        - ``messages``：user/assistant 交替的消息列表；content 可为
          字符串或 content blocks 列表；block ``type`` 可能是
          ``"text"`` / ``"tool_use"`` / ``"tool_result"``。

        返回形态（Anthropic 风格，loop 消费）::

            {
              "stop_reason": "tool_use" | "end_turn" | "max_tokens",
              "content": [
                {"type": "text", "text": "..."} 或
                {"type": "tool_use", "id": "...",
                 "name": "...", "input": {...}}
              ],
              "usage": {"input_tokens": N, "output_tokens": M}
            }

        Raises:
            ProviderUnavailable: API 认证失败或网络不可达。
            RateLimited: provider 限流。
            ContextLimitExceeded: 请求 token 超过 context window。
            ProviderError: 其它 provider 层错误。
        """
        ...

    def extract_final_text(self, response: Any) -> str:
        """从 ``messages_create`` 返回的响应里抽 final answer 文本。

        每个 adapter 按自己 provider 形态实现——r2 下 ``AnthropicAdapter``
        / ``DeepSeekAdapter`` 都吐 OpenAI plain dict，读
        ``choices[0].message.content`` 字符串；测试 fake 可按 r1 风格
        (``content`` block list) 实现自己的形态读取。

        Args:
            response: 同 ``messages_create`` 返回值；允许 dict / SDK 对象
                ducktype，本方法负责兼容。

        Returns:
            纯文本（``strip()``）；解析不出来返空串——调用方据空串走
            fallback 路径，不抛。
        """
        ...

    def extract_usage_tokens(self, response: Any) -> tuple[int, int]:
        """从响应里抽 ``(input_tokens, output_tokens)`` 元组。

        各 provider 字段名差异（OpenAI ``prompt_tokens`` /
        ``completion_tokens`` vs Anthropic ``input_tokens`` /
        ``output_tokens``）由各自 adapter 实现兜底；缺字段降级
        ``(0, 0)``，不抛。
        """
        ...


__all__ = ["LLMClient"]
