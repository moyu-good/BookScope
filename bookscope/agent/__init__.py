"""`bookscope.agent` — 查询时智能代理 r2 代际入口。

本包承担查询时 agent loop 的全部职责：在用户发起提问的那一刻启动一个受控
的 agent 循环，调用 ADR-001 定义的三个核心 tool（search_chunks /
get_chapter_range / list_characters_in_chapter）从 r0 预处理产物中拉取
必要的原文片段，完成带 citation 的答案。

### 代际状态

- r1 代际（Anthropic ``tool_use`` content_block 主格式）已于 Sprint 7
  （2026-05-15）退役 —— 三个 runtime 文件 ``loop.py`` /
  ``adapters/anthropic.py`` / ``adapters/deepseek.py`` 真 ``git rm``，
  共享 symbol 已抽到 :mod:`bookscope.agent._internal` /
  :mod:`bookscope.agent.utils.json_parsing` 等纯函数模块
- r2 代际（OpenAI function calling 主格式）是当前唯一 runtime ——
  :class:`bookscope.agent.loop_r2.AgentLoop` 是 ``AgentLoop`` 的唯一实现

### Provider 抽象

``AgentLoop`` 通过 :class:`LLMClient` Protocol 与底层模型对话，不依赖任何
具体 SDK。默认 provider 是 :class:`DeepSeekAdapter`，备选
:class:`AnthropicAdapter`，两者都已升级为 r2 形态（见
``adapters/deepseek_r2.py`` / ``adapters/anthropic_r2.py``）。
"""

from bookscope.agent.adapters import (
    AnthropicAdapter,
    DeepSeekAdapter,
    LLMClient,
)
from bookscope.agent.errors import (
    AgentError,
    ContentFiltered,
    ContextLimitExceeded,
    LLMFormatError,
    LoopTimeout,
    MaxIterationsExceeded,
    ProviderError,
    ProviderUnavailable,
    RateLimited,
    ToolDispatchError,
)
from bookscope.agent.events import (
    ContentFilterRetryEvent,
    ErrorEvent,
    FinalAnswerEvent,
    FormatRetryEvent,
    IterationStartEvent,
    LoopCallback,
    LoopEvent,
    ReviewEvent,
    RouteDecisionEvent,
    RouteType,
    ToolResultEvent,
    ToolUseEvent,
)
from bookscope.agent.fast_path import (
    build_route_decision_event,
    route_question,
    run_fast_path,
)
from bookscope.agent.loop_r2 import AgentLoop
from bookscope.agent.models import AgentQueryResult, LoopOutcome, LoopTrace
from bookscope.agent.reviewer import review_answer


def _select_agent_loop_class() -> type[AgentLoop]:
    """返回当前默认 :class:`AgentLoop` 实现。

    Sprint 7（2026-05-15）r1 退役后只剩 r2 一条路径。本 helper 保留是
    为了将来 r3 / 后续代际切换沿用同一抽象（一个集中点改 import），不需
    要散在调用方各处。

    ``BOOKSCOPE_AGENT_PROTOCOL`` 环境变量：

    - 不设 / 等于 ``"r2"`` / 任何未识别值：返回 r2 ``AgentLoop``
    - 显式设为 ``"r1"``：抛 :class:`RuntimeError`，提示 r1 已退役。这条
      检查只为给从 Sprint 6 时代留下来 export 这条 env 的用户一个清楚
      的错误消息，避免它们以为 r1 还能跑只是被静默忽略。
    """
    import os

    protocol = os.environ.get("BOOKSCOPE_AGENT_PROTOCOL", "r2")
    if protocol == "r1":
        raise RuntimeError(
            "r1 protocol decommissioned at Sprint 7 (2026-05-15). "
            "Unset BOOKSCOPE_AGENT_PROTOCOL or set it to 'r2'. "
            "See docs/internal/case-study/chapter-05-decommissioning-bidirectional-adapter.md "
            "for the full migration history."
        )
    return AgentLoop


__all__ = [
    "AgentError",
    "AgentLoop",
    "AgentQueryResult",
    "AnthropicAdapter",
    "ContentFilterRetryEvent",
    "ContentFiltered",
    "ContextLimitExceeded",
    "DeepSeekAdapter",
    "ErrorEvent",
    "FinalAnswerEvent",
    "FormatRetryEvent",
    "IterationStartEvent",
    "LLMClient",
    "LLMFormatError",
    "LoopCallback",
    "LoopEvent",
    "LoopOutcome",
    "LoopTimeout",
    "LoopTrace",
    "MaxIterationsExceeded",
    "ProviderError",
    "ProviderUnavailable",
    "RateLimited",
    "ReviewEvent",
    "RouteDecisionEvent",
    "RouteType",
    "ToolDispatchError",
    "ToolResultEvent",
    "ToolUseEvent",
    "_select_agent_loop_class",
    "build_route_decision_event",
    "review_answer",
    "route_question",
    "run_fast_path",
]
