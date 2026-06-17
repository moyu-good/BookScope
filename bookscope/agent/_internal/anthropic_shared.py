"""``bookscope.agent._internal.anthropic_shared`` —— r1 / r2 Anthropic
adapter 共用 helper。

Sprint 7 ③a 把 r1 ``adapters/anthropic.py`` 的 ``_translate_error`` 抽到
这里，让 r2 ``adapters/anthropic_r2.py`` 不再 import r1 物理文件。
"""

from __future__ import annotations

from bookscope.agent.errors import (
    ContextLimitExceeded,
    ProviderError,
    ProviderUnavailable,
    RateLimited,
)


def translate_error(exc: Exception) -> ProviderError:
    """``anthropic`` SDK 异常 → ``ProviderError`` 子类。

    用类名匹配以避免顶层硬依赖 ``anthropic``；触发场景见 SDK 文档：
    ``AuthenticationError`` / ``APIConnectionError`` / ``RateLimitError``
    / ``BadRequestError``。
    """
    class_name = type(exc).__name__
    msg = str(exc)

    if class_name == "AuthenticationError":
        return ProviderUnavailable(f"Anthropic 认证失败: {msg}")
    if class_name == "APIConnectionError":
        return ProviderUnavailable(f"Anthropic 连接失败: {msg}")
    if class_name == "RateLimitError":
        return RateLimited(f"Anthropic 限流: {msg}")
    if class_name == "BadRequestError":
        lowered = msg.lower()
        if "context length" in lowered or "too long" in lowered or "max_tokens" in lowered:
            return ContextLimitExceeded(f"Anthropic 上下文超限: {msg}")
        return ProviderError(f"Anthropic 请求错误: {msg}")
    return ProviderError(f"Anthropic provider 错误: {class_name}: {msg}")
