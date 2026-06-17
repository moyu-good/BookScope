"""``bookscope.agent._internal.deepseek_shared`` —— r1 / r2 DeepSeek 系
adapter 共用 helper（"怪癖兜底" 层）。

Sprint 7 ③a 把 r1 ``adapters/deepseek.py`` 的 ``DEEPSEEK_DEFAULT_BASE_URL``
+ ``_strip_thinking_tags`` + ``_looks_like_content_filter`` +
``_translate_error`` 抽到这里，让 r2 ``adapters/deepseek_r2.py`` 不再
import r1 物理文件。

这一层与形态无关，纯 provider 怪癖（reasoning model 的 ``<think>`` 块、
MiniMax 422 内容审查识别、openai SDK 异常归并）——所以 r1 / r2 双轨期共用
是安全的。
"""

from __future__ import annotations

import re

from bookscope.agent.errors import (
    ContentFiltered,
    ContextLimitExceeded,
    ProviderError,
    ProviderUnavailable,
    RateLimited,
)

DEEPSEEK_DEFAULT_BASE_URL = "https://api.deepseek.com/v1"

# Reasoning models（minimax-m2.x / deepseek-r1 / qwen-qwq / glm-zero 等）会把
# 思考链 inline 在 content 里以 <think>...</think> 段返回，污染下游 JSON
# parse。这里在 OpenAI→Anthropic 转换层抹掉。non-reasoning model 的 content
# 不含此标签，相当于 no-op。
_THINK_BLOCK_RE = re.compile(r"<think\b[^>]*>.*?</think>", re.DOTALL | re.IGNORECASE)
_OPEN_THINK_RE = re.compile(r"<think\b[^>]*>.*", re.DOTALL | re.IGNORECASE)


def strip_thinking_tags(text: str) -> str:
    """删除 <think>...</think> 块。无标签时原样返回。"""
    if "<think" not in text.lower():
        return text
    cleaned = _THINK_BLOCK_RE.sub("", text)
    # 兜底：模型 stop 在 think 内部（max_tokens 截断），抹掉残留开放段
    cleaned = _OPEN_THINK_RE.sub("", cleaned)
    return cleaned.strip()


_CONTENT_FILTER_HINTS: tuple[str, ...] = (
    "new_sensitive",
    "content_filter",
    "content_policy",
    "moderation",
    "safety_violation",
    "1027",  # MiniMax 内部码
)


def looks_like_content_filter(msg: str) -> bool:
    """判断错误消息是否为内容审核类。

    匹配 minimax / OpenAI / 其他 OpenAI 兼容 provider 的常见提示词。
    宁可放过（误判为非审核 → 走普通 ProviderError），不要扩大化。
    """
    lowered = msg.lower()
    return any(h in lowered for h in _CONTENT_FILTER_HINTS)


def translate_error(exc: Exception) -> ProviderError:
    """把 openai SDK 异常归并为 ``ProviderError`` 子类。

    判断策略按优先级：
    1. 按类名匹配（``AuthenticationError`` / ``RateLimitError`` /
       ``BadRequestError``）——不直接 isinstance，以避免顶层依赖 openai。
    2. ``BadRequestError`` + 错误消息含 "context length" / "context_length"
       → ``ContextLimitExceeded``；否则按 ``ProviderError``。
    3. ``UnprocessableEntityError`` + content filter 提示词 → ``ContentFiltered``。
    4. 其它 → ``ProviderError``。
    """
    class_name = type(exc).__name__
    msg = str(exc)

    if class_name == "AuthenticationError":
        return ProviderUnavailable(f"DeepSeek 认证失败: {msg}")
    if class_name == "APIConnectionError":
        return ProviderUnavailable(f"DeepSeek 连接失败: {msg}")
    if class_name == "RateLimitError":
        return RateLimited(f"DeepSeek 限流: {msg}")
    if class_name == "BadRequestError":
        lowered = msg.lower()
        if "context length" in lowered or "context_length" in lowered:
            return ContextLimitExceeded(f"DeepSeek 上下文超限: {msg}")
        return ProviderError(f"DeepSeek 请求错误: {msg}")
    if class_name == "UnprocessableEntityError":
        # MiniMax HTTP 422 主用于内容审查拒绝（``output new_sensitive`` 等）。
        # 同样形态在其他 OpenAI 兼容 provider 上也会出现。
        if looks_like_content_filter(msg):
            return ContentFiltered(f"输出审核拒绝: {msg}")
        return ProviderError(f"DeepSeek 请求被拒（422）: {msg}")
    return ProviderError(f"DeepSeek provider 错误: {class_name}: {msg}")
