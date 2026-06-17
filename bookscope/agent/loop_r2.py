"""``bookscope.agent.loop_r2`` —— r2 主循环（OpenAI function calling 主格式）。

ADR-007 D-1 决策来源：把 AgentLoop 内部消息形态从 Anthropic tool_use
切到 OpenAI function calling，让多数派 provider 0 翻译成本接入。

### 与 r1 ``loop.py`` 的关系

r2 不继承 r1 ``AgentLoop`` —— 继承会把 Anthropic 形态的方法实现带进
r2 路径，混淆消息形态。改成独立 class，``query`` / 构造 / prompt 加载
/ 计时 / token 累计 / 超时检查 / final answer JSON 解析等**非 5 处改动**
方法直接从 r1 copy（行为不变），5 处改动点按本文件下面的注释重写：

1. ``_extract_tool_calls`` —— 从 ``choices[0].message.tool_calls`` 读
   工具调用，替代 r1 的 ``_extract_content_blocks`` + ``tool_use`` block 筛选
2. ``_dispatch_tools_parallel`` —— 写回 N 条独立 ``role="tool"`` 消息，
   严格按 tool_calls 顺序对应（OpenAI 规约：tool_calls / role=tool 消息
   一一对应，乱序会被 422）
3. ``_append_assistant_message`` —— assistant 含 tool_calls 时
   ``{"role": "assistant", "content": str|None, "tool_calls": [...]}``；
   tool_calls 为空时不带 ``tool_calls`` 字段（OpenAI 强校验）
4. ``_truncate_messages_r2`` —— 配对扫描改成"assistant 含 tool_calls +
   后续 N 条 role=tool 消息"成组丢弃；N 由该 assistant 的 tool_calls 数量
   决定，连续性不满足就停止丢弃免得伤无关历史
5. ``_classify_finish_reason`` —— 用 ``finish_reason`` 取代 r1 的
   ``stop_reason``：``tool_calls`` 继续 loop；``stop`` 走 final answer 解析；
   ``length`` 视为输出截断（按 r1 同样的失败语义）

### 4 个 ``_autofix_*`` + ``_parse_final_answer``

ADR-007 Open Q-4 未决定下沉到 adapter，第二波继续在 loop 层用。Sprint 7
第一步把这些 helper 从 r1 ``loop.py`` 抽到
``bookscope.agent.utils.json_parsing``——本文件现在直接调
``parse_final_answer`` / ``autofix_*``，不再借道
``_R1AgentLoop._parse_final_answer`` 这条诡异 classmethod 路径。
``_parse_final_answer`` 在 r1 / r2 形态下完全一致（都是从纯文本中抽 JSON
对象），所以归位到 utils 是 zero-behavior 的搬家。

### 双轨期约定

- r1 路径完全不动（``loop.py``）
- env ``BOOKSCOPE_AGENT_PROTOCOL`` 默认 ``r1``，r2 只在显式开启时启用
- ``LoopTrace.protocol_version`` 由 r2 ``AgentLoop`` 构造时显式置 ``"r2"``
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from bookscope.agent._internal.llm_cache import (
    invoke_client_cached as _invoke_client,
)
from bookscope.agent._internal.loop_shared import (
    CONTEXT_TRUNCATE_KEEP_LAST,
    DEFAULT_CONTENT_FILTER_RETRY_LIMIT,
    DEFAULT_CONTEXT_TRUNCATE_RETRY_LIMIT,
    DEFAULT_FORMAT_RETRY_LIMIT,
    DEFAULT_MAX_ITERATIONS,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_RATE_LIMIT_RETRY_LIMIT,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_TOOL_RETRY_LIMIT,
    FORCED_SYNTHESIS_REMAINING_SECONDS,
    QUESTION_PROCESSING_LENGTH_THRESHOLD,
    RATE_LIMIT_BACKOFF_BASE_SECONDS,
    TOOL_NAME_CHAPTER_RANGE,
    TOOL_NAME_LIST_CHARACTERS,
    TOOL_NAME_SEARCH,
    TOOL_PARALLEL_MAX_WORKERS,
)
from bookscope.agent._internal.loop_shared import (
    current_prompt_version as _current_prompt_version,
)
from bookscope.agent._internal.loop_shared import (
    elapsed_ms as _elapsed_ms,
)
from bookscope.agent._internal.loop_shared import (
    load_citation_format_hint as _load_citation_format_hint,
)
from bookscope.agent._internal.loop_shared import (
    load_system_prompt as _load_system_prompt,
)
from bookscope.agent._internal.loop_shared import (
    measure_output_size as _measure_output_size,
)
from bookscope.agent._internal.loop_shared import (
    question_processing_enabled as _question_processing_enabled,
)
from bookscope.agent._internal.loop_shared import (
    resp_field as _resp_field,
)
from bookscope.agent._internal.loop_shared import (
    summarise_output as _summarise_output,
)
from bookscope.agent._internal.search_cache import search_chunks_cached
from bookscope.agent.citation_check import verify_citations
from bookscope.agent.errors import (
    ContentFiltered,
    ContextLimitExceeded,
    LLMFormatError,
    LoopTimeout,
    MaxIterationsExceeded,
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
    QuestionProcessedEvent,
    ToolResultEvent,
    ToolUseEvent,
)
from bookscope.agent.models import AgentQueryResult, LoopTrace
from bookscope.agent.question_processor import (
    build_system_addendum,
    process_question,
)
from bookscope.agent.tools import (
    ChapterTextBackend,
    CharacterIndexBackend,
    ChunkRetrievalBackend,
    GetChapterRangeInput,
    ListCharactersInChapterInput,
    SearchChunksInput,
    get_chapter_range,
    list_characters_in_chapter,
)
from bookscope.agent.utils.json_parsing import parse_final_answer

# ---------------------------------------------------------------------------
# WP5 空转检测 + 剩时强制综合（设计稿 docs/internal/design/WP5-loop-convergence.md）
# ---------------------------------------------------------------------------

SPIN_CONSECUTIVE_ROUNDS: int = 2
"""连续多少轮检索与历史重叠才算空转。第 1 轮重叠可能只是模型换角度
验证，连续第 2 轮重叠才注入提示。"""

SPIN_TOP_IDS_OVERLAP_RATIO: float = 2 / 3
"""top-3 chunk_ids 交集占比阈值——两次 search 即便 query 措辞不同，
返回的前三条 chunk 有 2/3 以上相同就视为"查的是同一处"。"""

SPIN_TOP_IDS_COUNT: int = 3
"""每次 search 取前几条 chunk_id 参与重叠判断。"""

SPIN_NUDGE_MESSAGE: str = (
    "系统提示：检索已重复，请停止新检索，立即基于已有证据综合作答。"
)

FORCED_SYNTHESIS_MESSAGE: str = (
    "系统提示：时间预算将尽，请立即基于已有证据给出 final answer。"
)

# 单条 search 的指纹：(归一化 query, top-3 chunk_ids)
_SearchRecord = tuple[str, frozenset[str]]


def _normalise_query(query: str) -> str:
    """query 归一化：去首尾空白、压缩中间空白、小写。

    只做最便宜的归一化——空转判定不用 LLM（设计稿"不做什么"第 3 条），
    措辞真不同但语义相同的情况交给 chunk_ids 交集那条腿兜。
    """
    return " ".join(query.strip().lower().split())


def _search_overlaps(a: _SearchRecord, b: _SearchRecord) -> bool:
    """两条 search 指纹是否重叠：query 完全相同，或 top-3 ids 交集 ≥ 2/3。"""
    query_a, ids_a = a
    query_b, ids_b = b
    if query_a and query_a == query_b:
        return True
    if ids_a and ids_b:
        inter = len(ids_a & ids_b)
        denom = max(len(ids_a), len(ids_b))
        return inter / denom >= SPIN_TOP_IDS_OVERLAP_RATIO
    return False


def _build_round_search_record(
    tool_calls: list[Any],
    new_chunk_ids: list[str],
) -> _SearchRecord | None:
    """从本轮 tool_calls 与新登记的 chunk_id 构造一条 search 指纹。

    本轮没有 ``search_chunks`` 调用时返回 ``None``——``get_chapter_range`` /
    ``list_characters_in_chapter`` 不算空转信号。query 取本轮所有 search 的
    归一化文本排序拼接，chunk_ids 取本轮新登记的前 ``SPIN_TOP_IDS_COUNT``
    个真 chunk（按检索返回序，调用方已剔除 ``chapter-`` 伪 id）。
    """
    queries: list[str] = []
    for tc in tool_calls:
        if _tc_function_field(tc, "name") != TOOL_NAME_SEARCH:
            continue
        args_raw = _tc_function_field(tc, "arguments") or "{}"
        try:
            query = json.loads(args_raw).get("query", "")
        except (json.JSONDecodeError, TypeError, AttributeError):
            query = ""
        if query:
            queries.append(_normalise_query(query))
    if not queries:
        return None
    return (
        " ".join(sorted(queries)),
        frozenset(new_chunk_ids[:SPIN_TOP_IDS_COUNT]),
    )


# ---------------------------------------------------------------------------
# OpenAI 形态字段访问 helpers
# ---------------------------------------------------------------------------


def _msg_field(msg: Any, field: str) -> Any:
    """从 ``choices[0].message`` 取字段；兼容 dict / SDK 对象两种形态。

    OpenAI SDK 返回 ``ChatCompletionMessage`` 对象时走 ``getattr``；测试
    传 plain dict 时走 ``.get``。
    """
    if msg is None:
        return None
    if isinstance(msg, dict):
        return msg.get(field)
    return getattr(msg, field, None)


def _tc_field(tc: Any, field: str) -> Any:
    """从单个 ``tool_call`` 取字段；兼容 dict / SDK 对象。

    OpenAI ``ChatCompletionMessageToolCall`` 的 function 是嵌套对象，
    访问 ``function.name`` 这种串联调用前需要先拿到 function 本身。
    """
    if tc is None:
        return None
    if isinstance(tc, dict):
        return tc.get(field)
    return getattr(tc, field, None)


def _tc_function_field(tc: Any, field: str) -> Any:
    """从 ``tool_call.function`` 取字段（``name`` / ``arguments``）。"""
    fn = _tc_field(tc, "function")
    if fn is None:
        return None
    if isinstance(fn, dict):
        return fn.get(field)
    return getattr(fn, field, None)


# ---------------------------------------------------------------------------
# r2 AgentLoop
# ---------------------------------------------------------------------------


class AgentLoop:
    """r2 代理主循环（ADR-007 D-1，OpenAI function calling 主格式）。

    构造签名跟 r1 ``AgentLoop`` 一致，可平滑替换。差异全部在内部消息形态
    与 stop / tool 判断逻辑。

    Args:
        client: 任意 LLMClient 形态 client。对 r2，期望响应是 OpenAI 兼容
            ``ChatCompletion`` 对象（带 ``.choices[0].message.tool_calls``
            / ``.finish_reason`` 字段），或等价 dict。
        其余参数语义同 r1。
    """

    def __init__(
        self,
        client: Any,
        search_chunks_backend: ChunkRetrievalBackend,
        chapter_range_backend: ChapterTextBackend,
        list_characters_backend: CharacterIndexBackend,
        *,
        model: str = DEFAULT_MODEL,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        tool_retry_limit: int = DEFAULT_TOOL_RETRY_LIMIT,
        format_retry_limit: int = DEFAULT_FORMAT_RETRY_LIMIT,
        content_filter_retry_limit: int = DEFAULT_CONTENT_FILTER_RETRY_LIMIT,
        rate_limit_retry_limit: int | None = None,
        context_truncate_retry_limit: int | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        on_event: LoopCallback | None = None,
        extra_system_prompt: str | None = None,
        session_id: str | None = None,
        conversation_context: str | None = None,
        conversation_id: str | None = None,
        turn_index: int = 0,
    ) -> None:
        self._client = client
        self._search_backend = search_chunks_backend
        # Sprint 8 W1：L1 search_chunks 缓存只在拿到 session_id 时启用——
        # None 走 transparent backend 调用（老测试无侵入）。
        self._session_id = session_id
        self._chapter_backend = chapter_range_backend
        self._characters_backend = list_characters_backend
        self._model = model
        self._max_iterations = max_iterations
        self._timeout_seconds = timeout_seconds
        self._tool_retry_limit = tool_retry_limit
        self._format_retry_limit = format_retry_limit
        self._content_filter_retry_limit = content_filter_retry_limit
        self._rate_limit_retry_limit = (
            rate_limit_retry_limit
            if rate_limit_retry_limit is not None
            else DEFAULT_RATE_LIMIT_RETRY_LIMIT
        )
        self._context_truncate_retry_limit = (
            context_truncate_retry_limit
            if context_truncate_retry_limit is not None
            else DEFAULT_CONTEXT_TRUNCATE_RETRY_LIMIT
        )
        self._max_tokens = max_tokens
        self._on_event = on_event
        # ADR-009 Phase 1a 多轮对话：
        # - conversation_context = 追问时拼好的「前情提要」（上一轮答案 +
        #   引用）。它每轮都变，所以**绝不能**和 extra_system_prompt 一样拼进
        #   base_prompt——那会进 fixed_system 固定前缀，把刚修好的 DeepSeek
        #   缓存命中打破。query() 里它接在 fixed_system + addendum 之后，
        #   单独占 system 末尾的可变段。
        # - conversation_id / turn_index 只用来盖 trace，多轮质量分析靠它们
        #   把同一场对话的各轮 trace 串起来。
        self._conversation_context = conversation_context
        self._conversation_id = conversation_id
        self._turn_index = turn_index

        # prompt 加载共享给 r1 / r2 双轨期使用——Sprint 7 ③a 后真定义在
        # ``_internal.loop_shared``，r2 直接调模块级函数，不再借道
        # ``_R1AgentLoop._load_*`` 这种 mixin 路径。
        # WP0：实例化时记下实际生效的 prompt 版本（含 env override），
        # 每次 query 写进 LoopTrace——版本是记录的事实，不是口头约定。
        self._prompt_version: str = _current_prompt_version()
        base_prompt = _load_system_prompt(self)
        # 重答时 routes 层传入上次 reviewer 批评摘要——与 r1 同样直接拼到
        # 主 system prompt 末尾。
        if extra_system_prompt:
            base_prompt = base_prompt + "\n\n" + extra_system_prompt
        self._system_prompt: str = base_prompt
        self._citation_format_hint: str = _load_citation_format_hint(self)
        # 与 r1 同：``query`` 入口按问题处理引擎结果重写本字段；先给默认值。
        self._effective_system_prompt: str = self._system_prompt

    # ------------------------------------------------------------------
    # 对外入口
    # ------------------------------------------------------------------

    def _emit(self, event: Any) -> None:
        """callback 异常吞掉记日志（与 r1 同行为）。"""
        if self._on_event is None:
            return
        try:
            self._on_event(event)
        except Exception:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).exception(
                "on_event callback raised; suppressed to protect loop"
            )

    def _run_question_processor_if_eligible(self, question: str) -> str:
        """与 r1 ``AgentLoop._run_question_processor_if_eligible`` 完全同行为。

        见 r1 版本 docstring。复述实现是因为 r2 不继承 r1（继承会把整套
        Anthropic 形态方法带进 r2，混淆消息形态）。
        """
        if not _question_processing_enabled():
            return ""
        if len(question.strip()) < QUESTION_PROCESSING_LENGTH_THRESHOLD:
            return ""
        processed = process_question(
            question, client=self._client, model=self._model
        )
        self._emit(
            QuestionProcessedEvent(
                iteration=0,
                original=processed.original_question,
                subquestions=list(processed.subquestions),
                recommended_chapters=(
                    list(processed.recommended_chapters)
                    if processed.recommended_chapters is not None
                    else None
                ),
                difficulty=processed.difficulty,
                duration_seconds=processed.processing_duration_seconds,
            )
        )
        return build_system_addendum(processed)

    def query(
        self,
        question: str,
        *,
        emit_route_decision: bool = True,
    ) -> AgentQueryResult:
        """运行一次 r2 agent loop 并返回带 citation 的答复。

        与 r1 的差异点见模块 docstring 列出的 5 处改动。

        Args:
            question: 用户题面。
            emit_route_decision: 入口是否 emit ``RouteDecisionEvent``。同
                r1 ``AgentLoop.query`` 的语义——fast_path 兜底回 agent_loop
                时调用方传 ``False`` 抑制重复 emit。
        """
        trace = LoopTrace(
            protocol_version="r2",
            prompt_version=self._prompt_version,
            conversation_id=self._conversation_id,
            turn_index=self._turn_index,
        )
        start = time.monotonic()

        # WP1 证据登记表：本次 query 内所有工具返回的原文，
        # ``{chunk_id: {"chapter": int, "text": str}}``。final answer 的
        # citation 靠它做系统比对（verify_citations）；超时 / 轮次超限时
        # 取前 5 条作 partial_evidence 带回去（WP5a）。只活在 query 作用
        # 域内，不进 trace——trace 仍只存 summary，避免膨胀。
        evidence_registry: dict[str, dict] = {}

        if emit_route_decision:
            from bookscope.agent.fast_path import build_route_decision_event

            self._emit(build_route_decision_event("agent_loop"))

        # 问题处理引擎：与 r1 行为完全对齐。
        # DeepSeek 缓存适配（2026-06-11）：system 前缀必须每次逐 token 相同
        # 才命中缓存（命中按 1/50 价）。所以把**固定**内容全部前置进 system，
        # **每题变化**的内容（问题分析 addendum）放 system 末尾、问题本身放
        # user message——让 base_prompt(~15KB) + citation_hint(~2KB) 这 17KB
        # 固定前缀稳定命中，只有小块 addendum / question 算新内容。
        # 关键改动：citation_hint 从 user message 移进 system（它本就固定，
        # 之前和每题变化的 question 绑在一条 user message 里，把整条 user
        # 拖成"新内容"全价计费）。
        system_addendum = self._run_question_processor_if_eligible(question)
        fixed_system = f"{self._system_prompt}\n\n---\n{self._citation_format_hint}"
        if system_addendum:
            # 变化的 addendum 接在固定段之后——token 级缓存下固定前缀仍命中
            self._effective_system_prompt = fixed_system + "\n\n" + system_addendum
        else:
            self._effective_system_prompt = fixed_system
        # ADR-009 Phase 1a：追问的前情提要也接在可变段末尾（addendum 之后），
        # 同样绝不进 fixed_system——它每轮都变，进固定前缀就把缓存打破了。
        if self._conversation_context:
            self._effective_system_prompt = (
                self._effective_system_prompt + "\n\n" + self._conversation_context
            )

        tools_schema = self._build_tool_schemas()
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": question}
        ]

        format_retries_used = 0

        # WP5 空转检测状态：每轮一条 search 指纹存档；连续与上一轮重叠
        # 的轮数计数；两类提示各自最多注入一次、互不挤占。
        search_history: list[_SearchRecord] = []
        consecutive_spin_rounds = 0
        spin_nudge_injected = False
        forced_synthesis_injected = False

        try:
            for iteration in range(1, self._max_iterations + 1):
                self._check_timeout(start, trace)
                self._emit(
                    IterationStartEvent(
                        iteration=iteration,
                        elapsed_ms=_elapsed_ms(start),
                    )
                )

                # WP5 剩时强制综合：每轮开始算剩余时间，快花完就提示模型
                # 立即综合，而不是等超时硬切。
                remaining_seconds = self._timeout_seconds - (
                    time.monotonic() - start
                )
                if (
                    not forced_synthesis_injected
                    and remaining_seconds < FORCED_SYNTHESIS_REMAINING_SECONDS
                ):
                    messages.append(
                        {"role": "user", "content": FORCED_SYNTHESIS_MESSAGE}
                    )
                    trace.forced_synthesis = True
                    forced_synthesis_injected = True

                response = self._invoke_with_context_truncate_retry(
                    tools_schema=tools_schema,
                    messages=messages,
                    trace=trace,
                    start=start,
                )
                trace.iterations = iteration
                self._accumulate_tokens(trace, response)

                # ADR-007 D-1 改动点 1 + 5：读 message + tool_calls。
                # 注：tool_calls 非空 == finish_reason="tool_calls"（OpenAI 规约），
                # 用 tool_calls 列表存在与否驱动 loop 比读 finish_reason 字符串更强
                # （某些 provider 在工具调用时不准确写 finish_reason）。仅在 final
                # answer 解析失败 / max_iterations 等错误诊断里才用得到 finish_reason，
                # 留 ``_extract_finish_reason`` 给后续诊断 hook 用。
                message = self._extract_message(response)
                tool_calls = self._extract_tool_calls(message)

                if tool_calls:
                    # ADR-007 D-1 改动点 3：assistant 含 tool_calls 时
                    # content 可能 None / 空字符串；不带 tool_calls 字段
                    # 时直接走纯文本分支
                    self._append_assistant_message_r2(messages, message, tool_calls)

                    # ADR-007 D-1 改动点 2：N 条独立 role=tool 消息追加
                    before_keys = set(evidence_registry)
                    self._dispatch_tools_parallel(
                        tool_calls=tool_calls,
                        iteration=iteration,
                        messages=messages,
                        trace=trace,
                        start=start,
                        evidence_registry=evidence_registry,
                    )

                    # WP5 空转检测：抽本轮 search 指纹，与上一轮连续重叠到
                    # 阈值就注入"停止检索、立即综合"提示——别让 loop 一直
                    # 查同一处空转到 timeout。每 query 至多注入一次。
                    if not spin_nudge_injected:
                        new_keys = [
                            k
                            for k in evidence_registry
                            if k not in before_keys
                            and not k.startswith("chapter-")
                        ]
                        record = _build_round_search_record(tool_calls, new_keys)
                        if record is not None:
                            if search_history and _search_overlaps(
                                record, search_history[-1]
                            ):
                                consecutive_spin_rounds += 1
                            else:
                                consecutive_spin_rounds = 0
                            search_history.append(record)
                            if (
                                consecutive_spin_rounds + 1
                                >= SPIN_CONSECUTIVE_ROUNDS
                            ):
                                messages.append(
                                    {
                                        "role": "user",
                                        "content": SPIN_NUDGE_MESSAGE,
                                    }
                                )
                                trace.spin_nudges += 1
                                spin_nudge_injected = True
                    continue

                # 没 tool_calls → 尝试 parse final answer
                final_text = self._extract_text_from_message(message)
                try:
                    answer, citations = parse_final_answer(final_text)
                except LLMFormatError as exc_fe:
                    if format_retries_used >= self._format_retry_limit:
                        trace.outcome = "format_error"
                        trace.duration_ms = _elapsed_ms(start)
                        exc_fe.trace = trace  # type: ignore[attr-defined]
                        exc_fe.raw_text = final_text  # type: ignore[attr-defined]
                        self._emit(
                            ErrorEvent(
                                error_type="LLMFormatError",
                                message=str(exc_fe),
                                duration_ms=trace.duration_ms,
                            )
                        )
                        raise
                    format_retries_used += 1
                    self._emit(
                        FormatRetryEvent(
                            retries_used=format_retries_used,
                            reason=str(exc_fe),
                        )
                    )
                    # 把上一轮 assistant 文本回写 + 一条补正提示
                    messages.append(
                        {
                            "role": "assistant",
                            "content": final_text,
                        }
                    )
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "上一次回复的 JSON 格式不合规：缺少 citations 字段、"
                                "citations 为空、或 citation 条目缺 chapter/snippet。"
                                "请严格按照 citation_format_v1 的 JSON schema 重新回复，"
                                "不要再调用任何 tool。"
                            ),
                        }
                    )
                    continue

                # WP1：组装结果前对每条 citation 比对证据登记表，附加
                # verified / chunk_id / match_score。只标注不执法——
                # unverified 的引用照常返回，先观测分布。
                citations = verify_citations(citations, evidence_registry)

                trace.outcome = "success"
                trace.duration_ms = _elapsed_ms(start)
                # finish_reason == "length" 不阻塞 success 路径——只要 JSON
                # 成功 parse 出 answer + citations 就视为成功（与 r1 同处理）
                self._emit(
                    FinalAnswerEvent(
                        answer=answer,
                        citations=citations,
                        iterations=trace.iterations,
                        duration_ms=trace.duration_ms,
                    )
                )
                return AgentQueryResult(
                    answer=answer,
                    citations=citations,
                    trace=trace,
                )

            # 循环走完还没 return → 超过 max_iterations
            trace.outcome = "max_iterations"
            trace.duration_ms = _elapsed_ms(start)
            exc_mi = MaxIterationsExceeded(self._max_iterations)
            exc_mi.trace = trace  # type: ignore[attr-defined]
            # WP5a：已查到的证据随错误带回去，用户不挨空盘
            exc_mi.partial_evidence = _build_partial_evidence(evidence_registry)
            self._emit(
                ErrorEvent(
                    error_type="MaxIterationsExceeded",
                    message=str(exc_mi),
                    duration_ms=trace.duration_ms,
                    partial_evidence=exc_mi.partial_evidence,
                )
            )
            raise exc_mi
        except LoopTimeout as exc_to:
            trace.outcome = "timeout"
            trace.duration_ms = _elapsed_ms(start)
            exc_to.trace = trace  # type: ignore[attr-defined]
            # WP5a：同 max_iterations——timeout 前几轮 search 的命中带回去
            exc_to.partial_evidence = _build_partial_evidence(evidence_registry)
            self._emit(
                ErrorEvent(
                    error_type="LoopTimeout",
                    message=str(exc_to),
                    duration_ms=trace.duration_ms,
                    partial_evidence=exc_to.partial_evidence,
                )
            )
            raise
        except ToolDispatchError as exc_td:
            trace.outcome = "tool_error"
            trace.duration_ms = _elapsed_ms(start)
            exc_td.trace = trace  # type: ignore[attr-defined]
            self._emit(
                ErrorEvent(
                    error_type="ToolDispatchError",
                    message=str(exc_td),
                    duration_ms=trace.duration_ms,
                )
            )
            raise

    # ------------------------------------------------------------------
    # ADR-007 D-1 改动点 1：读 OpenAI 形态 tool_calls
    # ------------------------------------------------------------------

    def _extract_message(self, response: Any) -> Any:
        """从 OpenAI ``ChatCompletion`` 响应里取出第一条 choice 的 message。

        测试 mock 直接传 dict / 简化对象都支持。
        """
        choices = _resp_field(response, "choices")
        if not choices:
            return None
        first = choices[0]
        return _msg_field(first, "message") if isinstance(first, dict) else getattr(
            first, "message", None
        )

    def _extract_tool_calls(self, message: Any) -> list[Any]:
        """从 message 取 ``tool_calls`` list；空 / None 都归 ``[]``。"""
        tc = _msg_field(message, "tool_calls")
        if tc is None:
            return []
        if isinstance(tc, list):
            return list(tc)
        return [tc]

    def _extract_finish_reason(self, response: Any) -> str | None:
        """从 ``choices[0].finish_reason`` 取出 OpenAI 终止原因。"""
        choices = _resp_field(response, "choices")
        if not choices:
            return None
        first = choices[0]
        if isinstance(first, dict):
            return first.get("finish_reason")
        return getattr(first, "finish_reason", None)

    def _extract_text_from_message(self, message: Any) -> str:
        """从 message.content 取纯文本（可能是 str / None / 空）。"""
        content = _msg_field(message, "content")
        if isinstance(content, str):
            return content.strip()
        return ""

    # ------------------------------------------------------------------
    # ADR-007 D-1 改动点 3：assistant 含 tool_calls 时的消息形态
    # ------------------------------------------------------------------

    def _append_assistant_message_r2(
        self,
        messages: list[dict[str, Any]],
        message: Any,
        tool_calls: list[Any],
    ) -> None:
        """追加一条 r2 assistant 消息，带 tool_calls。

        OpenAI 强校验：assistant 消息若有 tool_calls，``content`` 允许
        ``None`` 但 ``tool_calls`` 字段必须是 list 且至少一项。无 tool_calls
        时**不写** ``tool_calls`` 字段。
        """
        content = _msg_field(message, "content")
        # content 形态规整：None / 空串 → None；非空 str → 原样
        if isinstance(content, str) and content == "":
            content = None
        elif content is not None and not isinstance(content, str):
            content = str(content)

        oai_tool_calls = [
            {
                "id": _tc_field(tc, "id") or "",
                "type": "function",
                "function": {
                    "name": _tc_function_field(tc, "name") or "",
                    "arguments": _tc_function_field(tc, "arguments") or "",
                },
            }
            for tc in tool_calls
        ]
        messages.append(
            {
                "role": "assistant",
                "content": content,
                "tool_calls": oai_tool_calls,
            }
        )

    # ------------------------------------------------------------------
    # ADR-007 D-1 改动点 2：写回 N 条独立 role=tool 消息（严格保序）
    # ------------------------------------------------------------------

    def _dispatch_tools_parallel(
        self,
        *,
        tool_calls: list[Any],
        iteration: int,
        messages: list[dict[str, Any]],
        trace: LoopTrace,
        start: float,
        evidence_registry: dict[str, dict] | None = None,
    ) -> None:
        """N 个 tool_calls 并发派发；按 tool_calls 顺序追加 N 条 role=tool。

        关键约束（chapter-06 + r1 同名方法教训）：

        1. **顺序严格对应 tool_calls**——OpenAI 要求 ``role=tool`` 消息按
           tool_calls 顺序紧跟 assistant 消息后。用 ``dict[future, idx]``
           收集结果按 idx 写回，不走 ``as_completed``。
        2. **ToolUseEvent emit 顺序也按 tool_calls 顺序**——派发前同步 emit
           完所有 ToolUseEvent，再启动并发。
        3. **任一 tool 抛 ToolDispatchError 即整 query 失败**——保留 r1 行为。
        4. **单 tool 退化**——避开 ThreadPoolExecutor 开销。
        5. **证据登记在收集完结果后做**（WP1）——并发的是 tool 调用本身，
           登记表写入只发生在本方法所在线程，不需要加锁。
        """
        self._check_timeout(start, trace)

        # 派发前一次性 emit 所有 ToolUseEvent。
        tool_metas: list[tuple[str, str, dict[str, Any]]] = []
        for tc in tool_calls:
            tool_name = str(_tc_function_field(tc, "name") or "")
            tool_call_id = str(_tc_field(tc, "id") or "")
            raw_args = _tc_function_field(tc, "arguments") or ""
            # OpenAI arguments 是 JSON 字符串；空串 / 解析失败时降级为空 dict
            # （兼容 DeepSeek / MiniMax 某些 reasoning model 给空串的怪癖）
            try:
                parsed_input = json.loads(raw_args) if raw_args else {}
            except json.JSONDecodeError:
                parsed_input = {}
            if not isinstance(parsed_input, dict):
                parsed_input = {}
            tool_metas.append((tool_name, tool_call_id, parsed_input))
            self._emit(
                ToolUseEvent(
                    tool_name=tool_name,
                    tool_input=parsed_input,
                    tool_use_id=tool_call_id or None,
                    iteration=iteration,
                    elapsed_ms=_elapsed_ms(start),
                )
            )

        n = len(tool_metas)

        if n == 1:
            tool_name, _tool_call_id, normalised_input = tool_metas[0]
            outputs: list[Any] = [
                self._dispatch_tool_with_retry(
                    tool_name=tool_name,
                    tool_input=normalised_input,
                    trace=trace,
                    start=start,
                )
            ]
        else:
            outputs = [None] * n
            max_workers = min(n, TOOL_PARALLEL_MAX_WORKERS)
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_idx = {
                    executor.submit(
                        self._dispatch_tool_with_retry,
                        tool_name=meta[0],
                        tool_input=meta[2],
                        trace=trace,
                        start=start,
                    ): idx
                    for idx, meta in enumerate(tool_metas)
                }
                for future, idx in future_to_idx.items():
                    outputs[idx] = future.result()

        # WP1：所有结果已在本线程收齐，逐个登记原文证据
        if evidence_registry is not None:
            for meta, output in zip(tool_metas, outputs):
                _register_evidence(evidence_registry, meta[0], output)

        # 按 tool_calls 顺序追加 N 条独立 role=tool 消息
        for i in range(n):
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_metas[i][1],
                    "content": json.dumps(outputs[i], ensure_ascii=False),
                }
            )

    def _dispatch_tool_with_retry(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        trace: LoopTrace,
        start: float,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """单 tool 重试逻辑（与 r1 行为一致）。"""
        attempts = self._tool_retry_limit + 1
        last_error: BaseException | None = None
        for attempt in range(1, attempts + 1):
            self._check_timeout(start, trace)
            call_start = time.monotonic()
            try:
                output = self._dispatch_tool(tool_name, tool_input)
                call_elapsed = _elapsed_ms(call_start)
                output_summary = _summarise_output(output)
                # WP-agent-token-budget Phase 1：量这条 tool 结果灌进上下文的
                # 新原文体量（首发即 miss 的来源），按 tool 归因 miss 构成。
                result_chars, result_tokens_est = _measure_output_size(output)
                trace.tool_calls.append(
                    {
                        "tool_name": tool_name,
                        "input": tool_input,
                        "output_summary": output_summary,
                        "elapsed_ms": call_elapsed,
                        "attempt": attempt,
                        "status": "ok",
                        "result_chars": result_chars,
                        "result_tokens_est": result_tokens_est,
                    }
                )
                self._emit(
                    ToolResultEvent(
                        tool_name=tool_name,
                        output_summary=output_summary,
                        status="ok",
                        attempt=attempt,
                        elapsed_ms=call_elapsed,
                    )
                )
                return output
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                call_elapsed = _elapsed_ms(call_start)
                error_summary = f"error: {type(exc).__name__}: {exc}"
                trace.tool_calls.append(
                    {
                        "tool_name": tool_name,
                        "input": tool_input,
                        "output_summary": error_summary,
                        "elapsed_ms": call_elapsed,
                        "attempt": attempt,
                        "status": "error",
                        "result_chars": len(error_summary),
                        "result_tokens_est": 0,
                    }
                )
                self._emit(
                    ToolResultEvent(
                        tool_name=tool_name,
                        output_summary=error_summary,
                        status="error",
                        attempt=attempt,
                        elapsed_ms=call_elapsed,
                        error_message=f"{type(exc).__name__}: {exc}",
                    )
                )
                if attempt >= attempts:
                    break
        assert last_error is not None
        raise ToolDispatchError(tool_name=tool_name, underlying=last_error)

    def _dispatch_tool(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """分发到对应 backend（与 r1 行为一致）。"""
        if tool_name == TOOL_NAME_SEARCH:
            params = SearchChunksInput(**tool_input)
            # Sprint 8 W1：走 L1 缓存 wrapper；session_id=None 时降级。
            matches = search_chunks_cached(
                self._search_backend,
                session_id=self._session_id,
                query=params.query,
                chapter_scope=params.chapter_scope,
                character_filter=params.character_filter,
                top_k=params.top_k,
            )
            return [m.model_dump() for m in matches]
        if tool_name == TOOL_NAME_CHAPTER_RANGE:
            params = GetChapterRangeInput(**tool_input)
            chapters = get_chapter_range(params, self._chapter_backend)
            return [c.model_dump() for c in chapters]
        if tool_name == TOOL_NAME_LIST_CHARACTERS:
            params = ListCharactersInChapterInput(**tool_input)
            refs = list_characters_in_chapter(params, self._characters_backend)
            return [r.model_dump() for r in refs]
        raise ValueError(f"unknown tool_name: {tool_name!r}")

    # ------------------------------------------------------------------
    # tool schema 与 r1 一致
    # ------------------------------------------------------------------

    def _build_tool_schemas(self) -> list[dict[str, Any]]:
        """r2 仍把 tool schema 用 Anthropic 风格交给 adapter；adapter 自行翻译。

        理由：ADR-007 D-1 只切了**消息**形态，没切 tool 注入形态——
        r1 ``_build_tool_schemas`` 返回的是 ``{name, description, input_schema}``
        Anthropic 风格，DeepSeekAdapter r1 已经会翻译成 OpenAI function 形态；
        r2 下 DeepSeekAdapter passthrough 走 OpenAI 原生 tools spec，但
        tool 注入这一层先保持 r1 形态最低改动，由 r2 adapter 在 passthrough
        前做一次 schema 翻译（第二波 r2 adapter 实现里处理）。

        注：本决策与 ADR-007 D-1 不冲突——D-1 明文针对 messages / tool_use
        / tool_result 形态；tool 注入的 schema 形态本来就由 adapter 兜底
        翻译，loop 层不应关心。
        """
        return [
            {
                "name": TOOL_NAME_SEARCH,
                "description": (
                    "按自然语言 query 在 chunk 层做语义检索，"
                    "可选章节范围与角色过滤；返回带原文片段的 top-k 结果。"
                ),
                "input_schema": SearchChunksInput.model_json_schema(),
            },
            {
                "name": TOOL_NAME_CHAPTER_RANGE,
                "description": (
                    "按章节范围拉取完整原文；合计字数超过 20 万字会被拒绝。"
                ),
                "input_schema": GetChapterRangeInput.model_json_schema(),
            },
            {
                "name": TOOL_NAME_LIST_CHARACTERS,
                "description": (
                    "列出某章节中出现的角色及其出场分布，"
                    "用于后续 search_chunks 的 character_filter 前置探查。"
                ),
                "input_schema": ListCharactersInChapterInput.model_json_schema(),
            },
        ]

    # ------------------------------------------------------------------
    # 重试 / context truncate / 计时（与 r1 同结构，唯一差是 truncate 改 r2）
    # ------------------------------------------------------------------

    def _invoke_with_context_truncate_retry(
        self,
        *,
        tools_schema: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        trace: LoopTrace,
        start: float,
    ) -> Any:
        """与 r1 同语义：context 超限 → 截断 → 再试。

        差异：截断函数换成 ``_truncate_messages_r2``（按 r2 配对语义）。
        """
        attempts = 0
        while True:
            self._check_timeout(start, trace)
            try:
                return self._invoke_with_rate_limit_retry(
                    tools_schema=tools_schema,
                    messages=messages,
                    trace=trace,
                    start=start,
                )
            except ContextLimitExceeded as exc:
                attempts += 1
                trace.context_truncations = attempts
                if attempts > self._context_truncate_retry_limit:
                    self._emit(
                        ErrorEvent(
                            error_type="ContextLimitExceeded",
                            message=str(exc),
                            duration_ms=_elapsed_ms(start),
                        )
                    )
                    raise
                truncated = _truncate_messages_r2(messages)
                messages.clear()
                messages.extend(truncated)
                continue

    def _invoke_with_rate_limit_retry(
        self,
        *,
        tools_schema: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        trace: LoopTrace,
        start: float,
    ) -> Any:
        """指数退避 rate limit 重试（与 r1 一致）。"""
        attempts = 0
        while True:
            self._check_timeout(start, trace)
            try:
                return self._invoke_with_content_filter_retry(
                    tools_schema=tools_schema,
                    messages=messages,
                    trace=trace,
                    start=start,
                )
            except RateLimited as exc:
                attempts += 1
                trace.rate_limit_retries = attempts
                if attempts > self._rate_limit_retry_limit:
                    self._emit(
                        ErrorEvent(
                            error_type="RateLimited",
                            message=str(exc),
                            duration_ms=_elapsed_ms(start),
                        )
                    )
                    raise
                backoff_seconds = RATE_LIMIT_BACKOFF_BASE_SECONDS * (
                    2 ** (attempts - 1)
                )
                time.sleep(backoff_seconds)
                continue

    def _invoke_with_content_filter_retry(
        self,
        *,
        tools_schema: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        trace: LoopTrace,
        start: float,
    ) -> Any:
        """内容审核重试（与 r1 一致）。"""
        attempts = 0
        last_exc: ContentFiltered | None = None
        while True:
            self._check_timeout(start, trace)
            system_to_use = self._effective_system_prompt
            if attempts >= 2:
                system_to_use = self._effective_system_prompt + (
                    "\n\n[内部重试提示] 上一次输出被 provider 内容审核拦截。"
                    "请用中性、学术化的措辞展开同一答复——避免直接重复"
                    "题面里的敏感词（如'宣传''神话'等），改用'传播'"
                    "'叙事建构''史料还原'等学术术语。其余分析逻辑不变。"
                )
            try:
                # Sprint 8 W2：L2 LLM 缓存只在拿到 session_id 时启用——
                # 与 L1 同 gate；测试 mock 普遍不传 session_id，零侵入。
                return _invoke_client(
                    self._client,
                    model=self._model,
                    system=system_to_use,
                    tools=tools_schema,
                    messages=messages,
                    max_tokens=self._max_tokens,
                    cache_enabled=self._session_id is not None,
                )
            except ContentFiltered as exc:
                attempts += 1
                trace.content_filter_retries = attempts
                last_exc = exc
                if attempts > self._content_filter_retry_limit:
                    self._emit(
                        ErrorEvent(
                            error_type="ContentFiltered",
                            message=str(exc),
                            duration_ms=_elapsed_ms(start),
                        )
                    )
                    raise
                self._emit(ContentFilterRetryEvent(retries_used=attempts))
                continue
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("unreachable")

    def _check_timeout(self, start: float, trace: LoopTrace) -> None:
        elapsed = time.monotonic() - start
        if elapsed > self._timeout_seconds:
            raise LoopTimeout(
                timeout_seconds=self._timeout_seconds,
                elapsed_seconds=elapsed,
            )

    def _accumulate_tokens(self, trace: LoopTrace, response: Any) -> None:
        """OpenAI 形态 usage 字段：``prompt_tokens`` / ``completion_tokens``。

        r1 同名方法读 ``input_tokens`` / ``output_tokens``（Anthropic 风格）；
        r2 改读 OpenAI 字段名，缺失时降级 0。
        """
        usage = _resp_field(response, "usage")
        if usage is None:
            return
        # 兼容两种字段名：r2 原生用 OpenAI 命名；测试 / adapter 可能也回
        # Anthropic 风格 input_tokens / output_tokens
        input_tokens = (
            _resp_field(usage, "prompt_tokens")
            or _resp_field(usage, "input_tokens")
            or 0
        )
        output_tokens = (
            _resp_field(usage, "completion_tokens")
            or _resp_field(usage, "output_tokens")
            or 0
        )
        trace.total_input_tokens += int(input_tokens)
        trace.total_output_tokens += int(output_tokens)
        # DeepSeek context caching 命中观测——缺字段降级 0（非 DeepSeek
        # provider / 测试 mock 没有这俩字段时不影响）。
        trace.cache_hit_tokens += int(
            _resp_field(usage, "prompt_cache_hit_tokens") or 0
        )
        trace.cache_miss_tokens += int(
            _resp_field(usage, "prompt_cache_miss_tokens") or 0
        )


# ---------------------------------------------------------------------------
# WP1 证据登记 + WP5a partial_evidence（设计稿 docs/internal/design/WP1-citation-trust-chain.md）
# ---------------------------------------------------------------------------


PARTIAL_EVIDENCE_LIMIT: int = 5
"""partial_evidence 最多带几条登记证据。"""

_PARTIAL_EVIDENCE_SNIPPET_CHARS: int = 200
"""partial_evidence 每条 snippet 截断长度。"""


def _register_evidence(
    registry: dict[str, dict],
    tool_name: str,
    output: dict[str, Any] | list[dict[str, Any]],
) -> None:
    """把一次 tool 调用的返回登记进证据登记表。

    - ``search_chunks``：每条 ChunkMatch 按 ``chunk_id`` 登记 chapter + text
    - ``get_chapter_range``：每章按 ``"chapter-{N}"`` 伪 id 登记完整原文
    - ``list_characters_in_chapter``：不登记（没有原文）

    输出形态异常（缺字段 / 类型不对）的条目静默跳过——登记表是观测
    设施，不能反过来弄崩主循环。
    """
    if not isinstance(output, list):
        return
    if tool_name == TOOL_NAME_SEARCH:
        for item in output:
            if not isinstance(item, dict):
                continue
            chunk_id = item.get("chunk_id")
            text = item.get("text")
            if not chunk_id or not isinstance(text, str):
                continue
            registry[str(chunk_id)] = {
                "chapter": item.get("chapter", 0),
                "text": text,
            }
    elif tool_name == TOOL_NAME_CHAPTER_RANGE:
        for item in output:
            if not isinstance(item, dict):
                continue
            chapter = item.get("chapter")
            text = item.get("full_text")
            if chapter is None or not isinstance(text, str):
                continue
            registry[f"chapter-{chapter}"] = {
                "chapter": chapter,
                "text": text,
            }


def _build_partial_evidence(registry: dict[str, dict]) -> list[dict]:
    """从登记表取前 5 条，构造 ErrorEvent.partial_evidence 的列表。

    每条 ``{"chunk_id", "chapter", "snippet"}``——snippet 截 200 字给
    FE ErrorBanner 显示"我们查到这些原文但没来得及综合"。
    """
    out: list[dict] = []
    for chunk_id, entry in registry.items():
        if len(out) >= PARTIAL_EVIDENCE_LIMIT:
            break
        out.append(
            {
                "chunk_id": chunk_id,
                "chapter": entry.get("chapter", 0),
                "snippet": str(entry.get("text", ""))[:_PARTIAL_EVIDENCE_SNIPPET_CHARS],
            }
        )
    return out


# ---------------------------------------------------------------------------
# ADR-007 D-1 改动点 4：r2 配对扫描截断
# ---------------------------------------------------------------------------


def _truncate_messages_r2(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """r2 配对丢弃：assistant 含 tool_calls + 后续 N 条 role=tool 成组。

    与 r1 的差异：

    - r1 配对："assistant 含 tool_use block" + 紧随的 "user 含 tool_result block"
      （永远是 1+1 = 2 条）
    - r2 配对："assistant 含 tool_calls"（含 N 个 tool_call）+ 紧随的 N 条
      ``role="tool"`` 消息（1+N = N+1 条）

    扫描算法（保 r1 的 progressed flag 防"输入正好 ≤ KEEP_LAST 不动 →
    retry 死循环"陷阱）：

    1. system 保留在最前
    2. 最后一条 message 永远保留
    3. 从最早的中间 message 开始，遇到 ``role=assistant`` + 非空
       ``tool_calls`` → 计算 N = len(tool_calls)，要求后续严格连续 N 条
       ``role=tool`` 消息一起丢弃；连续性不满足就停止丢弃，免得伤无关历史
    4. 遇到非 assistant-with-tool_calls 的中间 message（早期 user 追问 /
       assistant 纯文本回复），单条丢弃即可
    5. 至少进行一次丢弃才进入"剩余总长度 ≤ KEEP_LAST 即停"的判断
    """
    if not messages:
        return []

    system_msgs: list[dict[str, Any]] = []
    body: list[dict[str, Any]] = list(messages)
    while body and body[0].get("role") == "system":
        system_msgs.append(body.pop(0))

    if not body:
        return list(system_msgs)

    last_msg = body[-1]
    middle = body[:-1]

    def _is_assistant_with_tool_calls(msg: dict[str, Any]) -> int:
        """若是 assistant 含 N 个 tool_calls 返回 N；否则返回 0。"""
        if msg.get("role") != "assistant":
            return 0
        tc = msg.get("tool_calls")
        if not isinstance(tc, list) or not tc:
            return 0
        return len(tc)

    def _is_role_tool(msg: dict[str, Any]) -> bool:
        return msg.get("role") == "tool"

    progressed = False
    while middle:
        total_len = len(system_msgs) + len(middle) + 1
        if progressed and total_len <= CONTEXT_TRUNCATE_KEEP_LAST:
            break
        first = middle[0]
        n = _is_assistant_with_tool_calls(first)
        if n > 0:
            # 严格要求后续 N 条都是 role=tool；不一致就不动这一组
            if len(middle) >= 1 + n and all(
                _is_role_tool(middle[i]) for i in range(1, 1 + n)
            ):
                middle = middle[1 + n:]
                progressed = True
                continue
            # 连续性不满足：停止丢弃，避免伤无关历史
            break
        # 非 assistant-with-tool_calls 的早期消息：单条丢弃
        middle = middle[1:]
        progressed = True

    return [*system_msgs, *middle, last_msg]


__all__ = ["AgentLoop"]
