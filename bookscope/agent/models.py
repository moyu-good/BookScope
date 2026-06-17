"""AgentLoop 的公开数据模型。

本模块只定义 ``AgentQueryResult`` / ``LoopTrace`` 两个 Pydantic 对象，
是 ``AgentLoop.query`` 的返回契约。所有字段都使用 ``Literal`` 或
``list[dict]`` 的宽松类型——trace 字段只用于可观测性，不参与业务逻辑，
因此允许比业务模型更低的结构严格度。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

LoopOutcome = Literal[
    "success",
    "max_iterations",
    "timeout",
    "tool_error",
    "format_error",
    "fast_path_success",
]
"""AgentLoop 单次 query 的最终结局标签。

- ``"success"``：正常拿到带 citation 的 final answer。
- ``"max_iterations"``：超过 ``max_iterations``，中途中止。
- ``"timeout"``：超过 ``timeout_seconds``，中途中止。
- ``"tool_error"``：tool 调用失败且超出重试上限。
- ``"format_error"``：LLM 返回格式不合规且重试后仍失败。
- ``"fast_path_success"``：通识题走快路径（1 search + 1 LLM call）成功
  返回带 citation 的答复。Sprint 5 BE 第二项 deliverable——通识题
  （"主要角色有哪几个"等）不需要走完整 agent loop，启发式分流到
  ``fast_path.run_fast_path`` 直接出答案，dur 目标 < 15 秒。
"""


class LoopTrace(BaseModel):
    """一次 ``AgentLoop.query`` 调用的过程痕迹。

    trace 是 ADR-002 "状态可观察" 原则的落地：每轮迭代、每次 tool 调用都
    被记录，便于回放、diff、实验复盘。允许 ``tool_calls`` 字段为空 dict
    的宽松结构，给后续实验 harness 留扩展空间。
    """

    model_config = ConfigDict(frozen=False)

    iterations: int = Field(
        default=0,
        ge=0,
        description="实际跑了几轮 ``client.messages.create``；0 表示还没跑。",
    )
    tool_calls: list[dict] = Field(
        default_factory=list,
        description=(
            "每次 tool 调用的记录，含 tool_name / input / output_summary / "
            "elapsed_ms / attempt / status，外加 result_chars / result_tokens_est"
            "（WP-agent-token-budget Phase 1：该 tool 结果灌进上下文的新原文体量，"
            "用于按 tool 归因 miss 构成）。"
        ),
    )
    total_input_tokens: int = Field(
        default=0,
        ge=0,
        description="所有 LLM 回复累计的 input token 数；mock client 可回 0。",
    )
    total_output_tokens: int = Field(
        default=0,
        ge=0,
        description="所有 LLM 回复累计的 output token 数；mock client 可回 0。",
    )
    duration_ms: int = Field(
        default=0,
        ge=0,
        description="整个 query 的墙钟时长（毫秒）。",
    )
    content_filter_retries: int = Field(
        default=0,
        ge=0,
        description=(
            "内容审核拒绝（``ContentFiltered``）触发的重试次数。"
            "第 31 轮加：minimax 等 provider 偶发 422 ``output new_sensitive``，"
            "AgentLoop 内部重试若仍失败该次数仍计入这里供诊断。"
        ),
    )
    rate_limit_retries: int = Field(
        default=0,
        ge=0,
        description=(
            "Provider 限流（``RateLimited`` / HTTP 429）触发的重试次数。"
            "Sprint 2 BE-1：AgentLoop 在 transport 层做指数退避重试，"
            "命中次数（含失败）累计在此供诊断。"
        ),
    )
    context_truncations: int = Field(
        default=0,
        ge=0,
        description=(
            "请求 token 超 context window（``ContextLimitExceeded``）"
            "触发的截断重试次数。Sprint 2 BE-2：AgentLoop 自动丢弃中间"
            "的 tool_use / tool_result 对、保留 system 与最后一条 user "
            "message 后重试，命中次数（含失败）累计在此供诊断。"
        ),
    )
    outcome: LoopOutcome = Field(
        default="success",
        description="本次 query 的最终结局标签。",
    )
    protocol_version: Literal["r1", "r2"] = Field(
        default="r1",
        description=(
            "AgentLoop 内部消息协议版本。ADR-007 D-5 决策来源："
            "r1 用 Anthropic tool_use 形态，r2 用 OpenAI function calling 形态。"
            "trace 里 tool_calls 每条记录的字段名按本版本走（r1=tool_use_id，"
            "r2=tool_call_id）。旧数据没该字段时默认 r1，保证向后兼容。"
        ),
    )
    prompt_version: str = Field(
        default="",
        description=(
            "本次 query 实际加载的 loop system prompt 版本（从文件名解析，"
            "env override 也如实反映）。WP0（2026-06-10）加：生产曾静默"
            "冻结 v3.1 三个月无人发现——版本必须是 trace 记录的事实，"
            "不是口头约定。空串 = 旧数据无该字段。"
        ),
    )
    cache_hit_tokens: int = Field(
        default=0,
        ge=0,
        description=(
            "DeepSeek context caching 命中的输入 token 数（命中按 1/50 价）。"
            "2026-06-11 加：之前 adapter 直接丢弃 usage 里的缓存字段，"
            "BookScope 从不观测命中率——缓存优化没有度量盘就是盲调。"
            "非 DeepSeek provider 此值恒 0。"
        ),
    )
    cache_miss_tokens: int = Field(
        default=0,
        ge=0,
        description="DeepSeek context caching 未命中的输入 token 数（全价）。",
    )
    spin_nudges: int = Field(
        default=0,
        ge=0,
        description=(
            "空转检测注入的提示次数（WP5，2026-06-10）。连续 2 轮 "
            "search_chunks 与历史检索重叠时，loop 注入一条'停止新检索、"
            "立即综合'的 user 消息，每次 query 至多 1 次。旧数据无该"
            "字段时默认 0。"
        ),
    )
    conversation_id: str | None = Field(
        default=None,
        description=(
            "本轮所属对话的标识（ADR-009 Phase 1a）。单轮请求（不带"
            "conversation_id）此值为 None。多轮质量衰减分析靠它把同一场"
            "对话的各轮 trace 串起来——跟 WP0 给 trace 加 prompt_version "
            "一样是测量仪器，先于实验落地。旧数据无该字段时默认 None。"
        ),
    )
    turn_index: int = Field(
        default=0,
        ge=0,
        description=(
            "本轮是对话的第几问，从 1 起（ADR-009 Phase 1a）。0 = 单轮"
            "请求或旧数据，没有轮次语义。"
        ),
    )
    forced_synthesis: bool = Field(
        default=False,
        description=(
            "剩余时间不足时是否注入过'立即给出 final answer'提示"
            "（WP5，2026-06-10）。阈值见 loop_shared."
            "FORCED_SYNTHESIS_REMAINING_SECONDS。旧数据无该字段时默认 False。"
        ),
    )


class AgentQueryResult(BaseModel):
    """``AgentLoop.query`` 的最终返回对象。"""

    model_config = ConfigDict(frozen=False)

    answer: str = Field(
        ...,
        description="LLM 综合作答；可能为空串（发生 max_iterations / timeout 时）。",
    )
    citations: list[dict] = Field(
        default_factory=list,
        description=(
            "原文引用列表，每条至少含 ``chapter: int`` + ``snippet: str``。"
            "对应 ADR-001 的 Citation schema 与 ADR-002 的 citation 强制要求。"
            "WP1（2026-06-10）起 loop / fast_path 在返回前附加系统校验字段："
            "``verified: bool`` / ``chunk_id: str|None`` / ``match_score: float``；"
            "fast_path 自动拼的 citation 另带 ``auto_filled: True``。"
        ),
    )
    trace: LoopTrace = Field(
        default_factory=LoopTrace,
        description="过程痕迹；用于可观测性与实验 harness 分析。",
    )


__all__ = ["AgentQueryResult", "LoopOutcome", "LoopTrace"]
