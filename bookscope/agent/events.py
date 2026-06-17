"""``LoopEvent`` —— AgentLoop 运行时增量事件流（Sprint 1 streaming）。

设计来源：``docs/internal/sprint-1-streaming-callback-design.md``。每个事件是
frozen dataclass，``type`` 字段是 ``Literal`` 字面量做 discriminated union；
调用方可 ``match event.type`` 也可 ``isinstance``。

LoopTrace 是终态全量快照，本模块是过程增量流——两者互补不重复。
``ToolResultEvent.output_summary`` 等字段必须从 trace 已写入的数据复制，
保证两者一致。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

EventType = Literal[
    "route_decision",
    "question_processed",
    "iteration_start",
    "tool_use",
    "tool_result",
    "format_retry",
    "content_filter_retry",
    "final_answer",
    "review",
    "error",
]


RouteType = Literal[
    "fast_general",
    "fast_review",
    "fast_summary",
    "fast_rating",
    "agent_loop",
]
"""路由判定结果——与 ``fast_path.RouteDecision`` 同 5 类字面量。

之所以在 ``events`` 里再声明一份：避免 ``events`` 反向依赖 ``fast_path``
形成循环 import；FE 端只需要这 5 个字面量。
"""


@dataclass(frozen=True)
class RouteDecisionEvent:
    """路由判定结果——SSE 流第一帧，让 FE 立刻知道命中哪类题 + 预期多久。

    设计动机：作者反馈"思考时间太长但不知道要多久"。fast_path 内部判
    路由是毫秒级；把判定结果立刻 emit 出去，FE 能在 LLM 调用真正发起
    之前就显示"这是评论题，预计 5-15 秒"，让等待有方向感。

    emit 时机：
    - fast 子类：``run_fast_path`` 入口、``IterationStartEvent`` 之前
    - 直接走 agent_loop：``AgentLoop.query`` 入口、第一帧 ``IterationStartEvent``
      之前
    - fast_path 兜底回 agent_loop：fast_path 已 emit 过则 ``AgentLoop.run``
      传 ``emit_route_decision=False`` 抑制重复 emit

    Attributes:
        route_type: 5 类字面量；与 ``fast_path.RouteDecision`` 一致。
        human_label: 中文人话标签——"通识题"/"评论题"/"摘要题"/"评分题"
            /"深度题"。FE 直接显示，免去维护一份字典。
        expected_duration_seconds_min: 预期下限秒数（按实测 fast_path 体感）。
        expected_duration_seconds_max: 预期上限秒数。FE 用 max 做进度条
            黄/红警戒线、超 max 提示"比预期久"。
        iteration: 路由发生在迭代之前，恒为 0；保留字段对齐其他 event 的
            shape，FE 解析时不用 special-case。
    """

    route_type: RouteType
    human_label: str
    expected_duration_seconds_min: int
    expected_duration_seconds_max: int
    iteration: int = 0
    type: Literal["route_decision"] = "route_decision"


@dataclass(frozen=True)
class IterationStartEvent:
    iteration: int = 0
    elapsed_ms: int = 0
    type: Literal["iteration_start"] = "iteration_start"


@dataclass(frozen=True)
class ToolUseEvent:
    tool_name: str
    tool_input: dict[str, Any]
    tool_use_id: str | None = None
    iteration: int = 0
    elapsed_ms: int = 0
    type: Literal["tool_use"] = "tool_use"


@dataclass(frozen=True)
class ToolResultEvent:
    tool_name: str
    output_summary: str
    status: Literal["ok", "error"] = "ok"
    attempt: int = 1
    elapsed_ms: int = 0
    error_message: str | None = None
    type: Literal["tool_result"] = "tool_result"


@dataclass(frozen=True)
class FormatRetryEvent:
    retries_used: int
    reason: str
    type: Literal["format_retry"] = "format_retry"


@dataclass(frozen=True)
class ContentFilterRetryEvent:
    retries_used: int
    type: Literal["content_filter_retry"] = "content_filter_retry"


@dataclass(frozen=True)
class FinalAnswerEvent:
    answer: str
    citations: list[dict]
    iterations: int
    duration_ms: int
    type: Literal["final_answer"] = "final_answer"


@dataclass(frozen=True)
class ErrorEvent:
    """AgentLoop 终态错误事件——SSE 流最后一帧，错误信号 + 已查到的原文兜底。

    ``partial_evidence`` 第 35 轮第二波加：dogfood 撞 LoopTimeout 时 117 秒
    跑完前 3 轮 search 已命中正确角色，第 4 轮 LLM 综合阶段 timeout 一起回滚
    让用户挨空盘——非常糟的体验。改成 emit error 时把 ``trace.tool_calls``
    里的 search 命中摘要带回去，FE ErrorBanner 下方显示「我们查到这些原文
    但没来得及综合」，让等了一两分钟的用户至少看到产物。
    """

    error_type: str
    message: str
    duration_ms: int
    partial_evidence: list[dict] = field(default_factory=list)
    type: Literal["error"] = "error"


@dataclass(frozen=True)
class QuestionProcessedEvent:
    """问题处理引擎产出事件——长题进 agent_loop 前的预处理增量帧。

    设计动机：作者反馈"字数越长你就需要整理问题"。长题往往含多个子问、
    指代不清、或跨章节，直接丢给 agent_loop 会让模型迷路。在 ``query``
    入口处先调一次 LLM 拆题/挑章节/评难度，结果以本事件 emit 给 FE，让
    用户看到"BookScope 把你的问题理解成 X / Y / Z 三个子问"——增加透明
    度，也方便用户在结果不准时回头改 prompt。

    emit 时机：``AgentLoop.query`` 入口、``RouteDecisionEvent`` 之后、第
    一帧 ``IterationStartEvent`` 之前。处理失败 fallback 时**仍 emit**
    一次"原题作单一子问"的事件——FE 永远知道 processor 跑过，区分
    fallback 与未触发。

    Attributes:
        original: 用户原始问题。
        subquestions: 拆出的 1-3 个子问；若 LLM 失败兜底为 ``[original]``。
        recommended_chapters: 推荐查询章节；``None`` 表示全书。FE 用于展
            示"BookScope 觉得这题主要在第 1-3 章"。
        difficulty: simple / medium / complex 难度评估，用户视角。
        duration_seconds: processor 调用耗时（含 LLM 延迟）；fallback 时
            为 0.0。
        iteration: 处理发生在 iteration 0；保留字段对齐其他事件 shape。
    """

    original: str = ""
    subquestions: list[str] = field(default_factory=list)
    recommended_chapters: list[int] | None = None
    difficulty: Literal["simple", "medium", "complex"] = "medium"
    duration_seconds: float = 0.0
    iteration: int = 0
    type: Literal["question_processed"] = "question_processed"


@dataclass(frozen=True)
class ReviewEvent:
    """Sprint 5.5 BE：reviewer agent 接进 user-facing 流程后的评分增量事件。

    在 ``FinalAnswerEvent`` 之后 emit。reviewer 跑一次 LLM 评分耗时
    5-15 秒——SSE 流里这段时间用户已经看到 final_answer，review 卡片
    在答案下方延迟出现，可接受。

    reviewer 失败时**不 emit** 本事件——主 ask 流程不被阻断。
    """

    overall_score: int = 0
    dimensions: dict[str, dict[str, Any]] = field(default_factory=dict)
    overall_comment: str = ""
    top_issues: list[str] = field(default_factory=list)
    suggest_redo: bool = False
    elapsed_ms: int = 0
    type: Literal["review"] = "review"


LoopEvent = (
    RouteDecisionEvent
    | QuestionProcessedEvent
    | IterationStartEvent
    | ToolUseEvent
    | ToolResultEvent
    | FormatRetryEvent
    | ContentFilterRetryEvent
    | FinalAnswerEvent
    | ReviewEvent
    | ErrorEvent
)

LoopCallback = Callable[[LoopEvent], None]


# ---------------------------------------------------------------------------
# IngestEvent —— Sprint 6 第六步：KG ingest 期间的增量进度事件
# ---------------------------------------------------------------------------
#
# 设计来源：Sprint 1 streaming callback hook precedent（``LoopEvent``）。
# 跟 LoopEvent 同 frozen dataclass + Literal type discriminator 模式，但走
# 独立的 union——ingest 流跟 ask 流是两条不同 SSE 端点，事件集互不相交，
# 强行 union 进 LoopEvent 反而让 FE 的 ``LoopEventFE`` 类型膨胀。
#
# emit 时机（在 ``MinimalKGExtractor.extract`` 内）：
#   - ``ingest_started``：``extract`` 入口、book-level cache 判定之前
#   - ``kg_batch_started``：每个 batch 抽取前
#   - ``kg_batch_completed``：每个 batch 抽取完
#   - ``kg_cache_hit``：batch 命中 batch 级缓存（``extract_batch_cached``
#     wrapper 内可观察的命中），或整本命中 book-level 缓存
#   - ``ingest_done``：merge 完成、KG 返出去之前
#   - ``ingest_error``：抽取链路任一步抛异常
#
# book_session_id 字段：上传期间 session_id 还没分配——FE 先用 upload
# request id 占位即可。BE emit 时如果没有 session_id（upload 路径调
# extractor 时还没 register），传空字符串占位，FE 不依赖这字段做主键，
# 只是关联日志。


IngestEventType = Literal[
    "ingest_started",
    "kg_batch_started",
    "kg_batch_completed",
    "kg_cache_hit",
    "ingest_done",
    "ingest_error",
]


@dataclass(frozen=True)
class IngestEvent:
    """KG ingest 期间的增量进度事件——SSE 流帧。

    一个 ingest 生命周期的事件序列例子（5 batch 抽取，1 命中 batch 缓存）::

        ingest_started(total_batches=5)
        kg_batch_started(batch_index=0)
        kg_batch_completed(batch_index=0)
        kg_batch_started(batch_index=1)
        kg_cache_hit(batch_index=1, cached=True)
        kg_batch_completed(batch_index=1)
        ...
        ingest_done()

    Book-level 缓存命中时整链路压缩成两帧::

        ingest_started(total_batches=None)
        kg_cache_hit(batch_index=None, cached=True)  # book-level
        ingest_done()

    Attributes:
        event_type: 6 类字面量；FE 按此做 discriminated union。
        book_session_id: 关联的 book session id。upload 期间还没分配则为
            空串，FE 用作弱关联标识。
        total_batches: ``ingest_started`` 时给出本次抽取的 batch 总数；
            其他 event 留 None。FE 用来算进度百分比。
        batch_index: ``kg_batch_started`` / ``kg_batch_completed`` /
            ``kg_cache_hit`` 携带 batch 索引（0-based）。book-level
            cache hit 时为 None（整本命中没有 batch 概念）。
        cached: ``kg_cache_hit`` 时为 True；其他 event 留 False。FE
            用作 "省 LLM 调用" 提示。
        error_message: ``ingest_error`` 时携带失败原因；其他 event 留 None。
        timestamp: 事件发出时的 Unix 秒（``time.time()``）。FE 用来
            画 ingest 总耗时曲线。
    """

    event_type: IngestEventType
    book_session_id: str = ""
    total_batches: int | None = None
    batch_index: int | None = None
    cached: bool = False
    error_message: str | None = None
    timestamp: float = field(default_factory=time.time)


IngestCallback = Callable[[IngestEvent], None]


__all__ = [
    "EventType",
    "RouteType",
    "RouteDecisionEvent",
    "QuestionProcessedEvent",
    "IterationStartEvent",
    "ToolUseEvent",
    "ToolResultEvent",
    "FormatRetryEvent",
    "ContentFilterRetryEvent",
    "FinalAnswerEvent",
    "ReviewEvent",
    "ErrorEvent",
    "LoopEvent",
    "LoopCallback",
    "IngestEvent",
    "IngestEventType",
    "IngestCallback",
]
