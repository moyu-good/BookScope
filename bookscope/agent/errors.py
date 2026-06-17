"""AgentLoop 专有异常分层（ADR-002 约定）。

四类错误按来源分层：
- tool 层：``ToolDispatchError``
- LLM 层：``LLMFormatError``
- 轮次上限：``MaxIterationsExceeded``
- 时间上限：``LoopTimeout``

上层可按类型分别决策（是否展示给用户、是否计入实验失败样本）。
"""

from __future__ import annotations


class AgentError(Exception):
    """AgentLoop 所有专有错误的根基类。

    上层只需 ``except AgentError`` 即可统一捕获 loop 层错误，
    同时保留按子类做精细决策的能力。
    """


class ToolDispatchError(AgentError):
    """tool 调用失败且超出重试上限。

    Attributes:
        tool_name: 触发失败的 tool 名（``search_chunks`` / ``get_chapter_range``
            / ``list_characters_in_chapter`` 之一）。
        underlying: 原始异常；用于日志与排障。
    """

    def __init__(
        self,
        tool_name: str,
        underlying: BaseException,
    ) -> None:
        self.tool_name = tool_name
        self.underlying = underlying
        super().__init__(
            f"tool {tool_name!r} failed and exceeded retry limit: "
            f"{type(underlying).__name__}: {underlying}"
        )


class LLMFormatError(AgentError):
    """LLM 返回格式不合规且重试后仍失败。

    常见原因：final answer 缺 ``citations`` 字段、citation 格式错（缺
    ``chapter`` / ``snippet``）、JSON parse 失败。
    """


class MaxIterationsExceeded(AgentError):
    """超过 ``max_iterations`` 仍未收敛。

    Attributes:
        max_iterations: 触发该错误的上限值。
        partial_evidence: 失败前已查到的原文证据（WP5a）。loop 在抛出前
            从证据登记表填入，每条 ``{"chunk_id", "chapter", "snippet"}``；
            API 层把它带进错误响应，FE ErrorBanner 显示给用户兜底。
    """

    def __init__(self, max_iterations: int) -> None:
        self.max_iterations = max_iterations
        self.partial_evidence: list[dict] = []
        super().__init__(
            f"agent loop exceeded max_iterations={max_iterations} "
            "without producing a final answer"
        )


class LoopTimeout(AgentError):
    """超过 ``timeout_seconds`` 仍未收敛。

    Attributes:
        timeout_seconds: 触发该错误的超时秒数。
        elapsed_seconds: 实际已耗时（秒）。
        partial_evidence: 失败前已查到的原文证据（WP5a，同
            ``MaxIterationsExceeded.partial_evidence``）。
    """

    def __init__(self, timeout_seconds: float, elapsed_seconds: float) -> None:
        self.timeout_seconds = timeout_seconds
        self.elapsed_seconds = elapsed_seconds
        self.partial_evidence: list[dict] = []
        super().__init__(
            f"agent loop exceeded timeout_seconds={timeout_seconds:.1f} "
            f"(elapsed {elapsed_seconds:.1f}s)"
        )


class ProviderError(AgentError):
    """Provider 层通用错误基类。

    所有 adapter（DeepSeek / Anthropic / 未来的 OpenAI 等）在把底层 SDK
    异常往上抛时都应归并到本类层级，使 AgentLoop 可统一 ``except
    ProviderError``。子类按语义细化：认证失败、限流、上下文超限。
    """


class ProviderUnavailable(ProviderError):
    """Provider API 不可达或认证失败。

    常见触发：API key 不合法、endpoint DNS 失败、SDK 抛
    ``AuthenticationError`` / ``APIConnectionError``。上层可据此决定
    是否提示用户去更新 BYOK 凭据。
    """


class RateLimited(ProviderError):
    """Provider 限流。

    上层可据此做 backoff；AgentLoop 本身不做 backoff，只把错误透出。
    """


class ContextLimitExceeded(ProviderError):
    """请求的 token 数超过 provider 的 context window 上限。

    常见触发：携带过多 tool_result 的 message 历史直接把 prompt 撑爆。
    上层可据此提示用户"对话太长，重开一个 session"。
    """


class ContentFiltered(ProviderError):
    """Provider 输出审核 / safety filter 拒绝。

    与 ``RateLimited`` 不同：触发的是**输出内容**而非请求频率。
    与 ``ContextLimitExceeded`` 不同：是**审核拒绝**而非物理上限。

    常见触发：
    - MiniMax HTTP 422 ``output new_sensitive (1027)``
    - Anthropic ``stop_reason='content_filter'``（暂未观察到）
    - OpenAI ``content_policy_violation``

    本错误**默认 retry-safe**——内容审核常常间歇触发，重试一次（可能
    搭配中性化 retry hint）有概率通过。AgentLoop 的内容过滤重试链
    据此判断是否再试。

    Attributes:
        retry_safe: 是否建议上层重试。默认 True。
        original_message: 原始错误消息，用于诊断。
    """

    def __init__(
        self,
        message: str,
        *,
        retry_safe: bool = True,
    ) -> None:
        self.retry_safe = retry_safe
        self.original_message = message
        super().__init__(message)


__all__ = [
    "AgentError",
    "ContentFiltered",
    "ContextLimitExceeded",
    "LLMFormatError",
    "LoopTimeout",
    "MaxIterationsExceeded",
    "ProviderError",
    "ProviderUnavailable",
    "RateLimited",
    "ToolDispatchError",
]
