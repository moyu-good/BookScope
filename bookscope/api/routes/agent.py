"""agent ask 端点 —— r1 代际的核心入口。

一次请求的生命周期：

  1. 按 ``book_session_id`` 查 :class:`BookSessionStore`，拿到已装配好
     的 :class:`R0BookAssembler`；找不到 -> 404。
  2. 调 ``assembler.build_all()`` 拿三个 backend。
  3. 按 ``request.provider`` 构造 adapter；SDK 未安装 -> 400。
  4. 实例化 :class:`AgentLoop`，跑 ``query(question)``。
  5. 按 AgentError 分层翻译 HTTP 状态：
       - ProviderUnavailable / AuthenticationError -> 502
       - RateLimited -> 429
       - ContextLimitExceeded -> 413
       - ContentFiltered -> 502
       - MaxIterationsExceeded / LoopTimeout -> 504
       - LLMFormatError -> 502
       - ToolDispatchError / 其它 AgentError -> 500
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from bookscope.agent import (
    AgentError,
    AgentQueryResult,
    ContentFiltered,
    ContextLimitExceeded,
    LLMFormatError,
    LoopTimeout,
    MaxIterationsExceeded,
    ProviderUnavailable,
    RateLimited,
    ToolDispatchError,
    _select_agent_loop_class,
    review_answer,
    route_question,
    run_fast_path,
)
from bookscope.agent.annotations import generate_annotations
from bookscope.agent.argument_structure import generate_argument_structure_exhaustive
from bookscope.agent.backends.r0_assembler import R0BookAssembler
from bookscope.agent.character_arc import generate_character_arc_exhaustive
from bookscope.agent.character_flow import generate_character_flow_exhaustive
from bookscope.agent.character_graph import (
    extract_character_graph_exhaustive,
)
from bookscope.agent.character_voice import generate_character_voice
from bookscope.agent.claim_support import check_claim_support
from bookscope.agent.concept_evolution import generate_concept_evolution
from bookscope.agent.consistency_scan import generate_consistency_scan
from bookscope.agent.entity_recall import generate_entity_recall
from bookscope.agent.events import LoopEvent
from bookscope.agent.foreshadow_arcs import generate_foreshadow_arcs_exhaustive
from bookscope.agent.long_context import run_long_context
from bookscope.agent.motif_tracking import generate_motif_tracking
from bookscope.agent.narrative_curve import generate_narrative_curve_exhaustive
from bookscope.agent.orchestrate import orchestrate
from bookscope.agent.pacing_curve import generate_pacing_curve
from bookscope.agent.question_processor import rewrite_followup
from bookscope.agent.recap import generate_recap
from bookscope.agent.relationship_timeline import (
    generate_relationship_timeline_exhaustive,
)
from bookscope.agent.study_cards import generate_study_cards
from bookscope.agent.style_issues import generate_style_issues
from bookscope.agent.subplot_weave import generate_subplot_weave_exhaustive
from bookscope.agent.suggested_questions import generate_book_questions
from bookscope.agent.timeline import generate_timeline_exhaustive
from bookscope.agent.writing_technique import generate_writing_technique
from bookscope.api.book_sessions import BookSessionNotFound, BookSessionStore
from bookscope.api.conversation_store import (
    ConversationNotFound,
    ConversationStoreError,
    JSONFileConversationStore,
)
from bookscope.api.dependencies import (
    build_llm_client,
    build_llm_client_from_params,
    default_model_for,
    get_book_session_store,
    get_conversation_store,
)
from bookscope.api.schemas import (
    AgentAskRequest,
    AgentAskResponse,
    AnnotationsRequest,
    AnnotationsResponse,
    ArgumentStructureRequest,
    ArgumentStructureResponse,
    ChapterAskRequest,
    ChapterAskResponse,
    CharacterArcRequest,
    CharacterArcResponse,
    CharacterFlowRequest,
    CharacterFlowResponse,
    CharacterGraphRequest,
    CharacterGraphResponse,
    CharacterVoiceRequest,
    CharacterVoiceResponse,
    CheckCitationsRequest,
    CheckCitationsResponse,
    ConceptEvolutionRequest,
    ConceptEvolutionResponse,
    ConsistencyScanRequest,
    ConsistencyScanResponse,
    EntityRecallRequest,
    EntityRecallResponse,
    ForeshadowArcsRequest,
    ForeshadowArcsResponse,
    GraphEdge,
    MotifTrackingRequest,
    MotifTrackingResponse,
    NarrativeCurveRequest,
    NarrativeCurveResponse,
    OrchestrateRequest,
    PacingCurveRequest,
    PacingCurveResponse,
    PreviousReviewHint,
    RecapRequest,
    RecapResponse,
    RelationshipTimelineRequest,
    RelationshipTimelineResponse,
    Review,
    ReviewDimensionScore,
    StudyCardsRequest,
    StudyCardsResponse,
    StyleIssuesRequest,
    StyleIssuesResponse,
    SubplotWeaveRequest,
    SubplotWeaveResponse,
    SuggestQuestionsRequest,
    SuggestQuestionsResponse,
    TimelineRequest,
    TimelineResponse,
    WritingTechniqueRequest,
    WritingTechniqueResponse,
)

logger = logging.getLogger(__name__)

agent_router = APIRouter(tags=["agent"])


@agent_router.post("/agent/ask", response_model=AgentAskResponse)
async def agent_ask(
    request: AgentAskRequest,
    store: BookSessionStore = Depends(get_book_session_store),
    conv_store: JSONFileConversationStore = Depends(get_conversation_store),
) -> AgentAskResponse:
    """执行一次 agent 查询并返回带 citation 的答复。

    错误分层按 ADR-003 约定的 provider / loop 错误体系翻译。
    """
    assembler = _resolve_assembler(store, request.book_session_id)
    backends = assembler.build_all()

    search_backend = backends["search"]
    if search_backend is None:
        # r0 ingest 还没跑向量索引 -> search_chunks 不可用。
        # 当前 AgentLoop 强依赖三个 backend；拒绝本次请求并提示原因。
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "VectorStoreMissing",
                "message": (
                    "book session 未装配 vector store；"
                    "search_chunks backend 不可用，agent loop 无法启动。"
                ),
                "details": None,
            },
        )

    client = _build_client_or_raise(request)
    model = request.model or default_model_for(request.provider)

    # Sprint 5 BE：通识 / 评论 / 摘要 / 评分四类题走 fast path（1 search + 1 LLM）。
    # 启发式判定见 fast_path._route_question；env BOOKSCOPE_FAST_PATH_DISABLED=1
    # 强制全部走 agent_loop。fast path 任意环节失败时返回 None，自动 fallback。
    book_title, language = _extract_book_meta(assembler)

    # 重答时 FE 带回上次 reviewer 批评摘要——拼成 system prompt 追加段
    # 注入 generator。previous_review 为 None / 拼接抛错时这里返 None
    # 不阻断 ask。
    extra_system_prompt = _resolve_extra_system_prompt(request)

    # ADR-009 Phase 1a：定位对话 + 拼前情提要。新对话 recap=None、turn 从 1 起；
    # 追问读上一轮拼 recap、turn 递增。recap 只进 system 可变段，不破缓存前缀。
    conv = _resolve_conversation(request, conv_store)
    # ADR-009 Phase 1b：追问指代消解。有历史时把残句改写成独立可查的完整问题，
    # 改写后的 effective_question 同时喂给路由 / fast_path / agent loop（一处
    # 改写三处受益）；rewritten 存进对话登记表。没历史时 effective=原题、
    # rewritten=None，行为同 Phase 1a 零回归。
    effective_question, rewritten = _resolve_effective_question(
        request, conv, client, model
    )
    # WP-retrieval-routing：能塞下的书 + flag 开 → 整本进 context 直读（exp-009 GO）。
    # 只新问走（追问 recap≠None 交给 agent loop 的多轮）；失败返 None → 落 fast_path/loop。
    if _should_use_long_context(assembler) and conv.recap is None:
        _lc_full, _lc_chunks = _long_context_inputs(assembler)
        lc_result = run_long_context(
            effective_question,
            full_text=_lc_full,
            chunks=_lc_chunks,
            llm_client=client,
            model=model,
            extra_system_prompt=extra_system_prompt,
            session_id=request.book_session_id,
        )
        if lc_result is not None:
            _persist_turn(
                conv_store,
                request.book_session_id,
                conv.conversation_id,
                question=request.question,
                answer=lc_result.answer,
                citations=lc_result.citations,
                rewritten_question=rewritten,
            )
            review = _try_review_or_none(
                client=client,
                model=model,
                question=effective_question,
                answer=lc_result.answer,
                citations=lc_result.citations,
                book_title=book_title,
                language=language,
            )
            return AgentAskResponse(
                answer=lc_result.answer,
                citations=lc_result.citations,
                trace=_serialize_trace(lc_result.trace),
                book_session_id=request.book_session_id,
                conversation_id=conv.conversation_id,
                turn_index=conv.turn_index,
                review=review,
                protocol_version=_resolve_protocol_version(lc_result.trace),
                route_type="long_context",
            )
        logger.info(
            "long_context returned None for session %s; falling back",
            request.book_session_id,
        )

    # Open Q-1：追问（带 conversation_id 拿到了 recap）一律走 agent_loop——
    # fast_path 路由判断看不见历史，会把"哪几章最稀"误判成通识题。新对话第一问
    # （recap=None）照旧可以走 fast_path——此时 effective==原题，没改写。
    decision = route_question(effective_question)
    if decision != "agent_loop" and conv.recap is None:
        fast_result = run_fast_path(
            effective_question,
            search_backend=search_backend,  # type: ignore[arg-type]
            llm_client=client,
            model=model,
            subroute=decision,
            extra_system_prompt=extra_system_prompt,
            session_id=request.book_session_id,
        )
        if fast_result is not None:
            _persist_turn(
                conv_store,
                request.book_session_id,
                conv.conversation_id,
                question=request.question,
                answer=fast_result.answer,
                citations=fast_result.citations,
                rewritten_question=rewritten,
            )
            review = _try_review_or_none(
                client=client,
                model=model,
                question=effective_question,
                answer=fast_result.answer,
                citations=fast_result.citations,
                book_title=book_title,
                language=language,
            )
            return AgentAskResponse(
                answer=fast_result.answer,
                citations=fast_result.citations,
                trace=_serialize_trace(fast_result.trace),
                book_session_id=request.book_session_id,
                conversation_id=conv.conversation_id,
                turn_index=conv.turn_index,
                review=review,
                protocol_version=_resolve_protocol_version(fast_result.trace),
                route_type=decision,
            )
        # fast path 失败 → 落到完整 agent_loop 兜底
        logger.info(
            "fast_path returned None for session %s; falling back to AgentLoop",
            request.book_session_id,
        )

    # ADR-007 D-4：env ``BOOKSCOPE_AGENT_PROTOCOL`` 动态分派 r1 / r2。
    # 每个请求都查 env，让运行中改 env 也能生效（开发调试方便）。
    AgentLoopCls = _select_agent_loop_class()
    loop = AgentLoopCls(
        client=client,
        search_chunks_backend=search_backend,  # type: ignore[arg-type]
        chapter_range_backend=backends["chapter_range"],  # type: ignore[arg-type]
        list_characters_backend=backends["list_characters"],  # type: ignore[arg-type]
        model=model,
        extra_system_prompt=extra_system_prompt,
        session_id=request.book_session_id,
        conversation_context=conv.recap,
        conversation_id=conv.conversation_id,
        turn_index=conv.turn_index,
    )

    result = _run_loop_or_raise(loop, effective_question)
    trace_dict = _serialize_trace(result.trace)

    _persist_turn(
        conv_store,
        request.book_session_id,
        conv.conversation_id,
        question=request.question,
        answer=result.answer,
        citations=result.citations,
        rewritten_question=rewritten,
    )

    review = _try_review_or_none(
        client=client,
        model=model,
        question=effective_question,
        answer=result.answer,
        citations=result.citations,
        book_title=book_title,
        language=language,
    )

    return AgentAskResponse(
        answer=result.answer,
        citations=result.citations,
        trace=trace_dict,
        book_session_id=request.book_session_id,
        conversation_id=conv.conversation_id,
        turn_index=conv.turn_index,
        review=review,
        protocol_version=_resolve_protocol_version(result.trace),
        # fast_path 兜底回 agent_loop 时也落 "agent_loop"——前端凭这字段
        # 决定是否显示"原本判为 fast 但回退到深度题"提示。
        route_type="agent_loop",
    )


@agent_router.post("/agent/ask/stream")
async def agent_ask_stream(
    request: AgentAskRequest,
    store: BookSessionStore = Depends(get_book_session_store),
    conv_store: JSONFileConversationStore = Depends(get_conversation_store),
) -> StreamingResponse:
    """同 ``/agent/ask``，但以 SSE 流式推 ``LoopEvent``。

    每个 event 一帧：``event: <type>\\ndata: <json>\\n\\n``。事件序列含
    ``iteration_start`` / ``tool_use`` / ``tool_result`` / ``format_retry``
    / ``content_filter_retry`` / ``final_answer`` / ``error``。

    Setup-time 错误（book session 不存在 / SDK 缺失 / vector store 缺失）
    仍走 HTTPException 翻译——SSE 头未发，客户端能收到正常状态码。一旦
    流开始，所有 agent loop 错误会以 ``error`` event 推到客户端再关流。

    ADR-009 Phase 1a：多轮对话在这条路上**已完整接通**——前情提要注入、
    trace 盖 conversation_id/turn_index、答完追加轮次都做了。唯一没做的是
    把 conversation_id / turn_index 单独推一帧给 FE（SSE 没有对应事件字段，
    要新增一类 event，得和 FE 约定）——留 TODO。当前 FE 可从 final_answer
    携带的 trace 里读到这两个字段（trace 已含），不阻塞功能。
    """
    assembler = _resolve_assembler(store, request.book_session_id)
    backends = assembler.build_all()

    search_backend = backends["search"]
    if search_backend is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "VectorStoreMissing",
                "message": (
                    "book session 未装配 vector store；"
                    "search_chunks backend 不可用，agent loop 无法启动。"
                ),
                "details": None,
            },
        )

    client = _build_client_or_raise(request)
    model = request.model or default_model_for(request.provider)

    queue: asyncio.Queue[LoopEvent | object] = asyncio.Queue(maxsize=200)
    done_sentinel = object()
    asyncio_loop = asyncio.get_running_loop()

    def _safe_put(item: Any) -> None:
        try:
            queue.put_nowait(item)
        except asyncio.QueueFull:
            # SSE 客户端可能断连或慢消费——丢老的，保 agent 主流程
            logger.warning("SSE event queue full; dropping event")

    def on_event(event: LoopEvent) -> None:
        # AgentLoop 跑在 worker thread；call_soon_threadsafe 跨线程入队
        asyncio_loop.call_soon_threadsafe(_safe_put, event)

    book_title, language = _extract_book_meta(assembler)

    # 重答时 FE 带回上次 reviewer 批评摘要——同步 / 流式两路一致处理。
    extra_system_prompt = _resolve_extra_system_prompt(request)

    # ADR-009 Phase 1a：与同步路同口径——定位对话 + 拼前情提要。
    conv = _resolve_conversation(request, conv_store)
    # ADR-009 Phase 1b：指代消解与同步路同口径——改写在 SSE 流打开**之前**
    # 同步做完（和 _resolve_conversation 一样是 setup-time 工作），改写后的
    # effective_question 喂给路由 / fast_path / agent loop，rewritten 存登记表。
    effective_question, rewritten = _resolve_effective_question(
        request, conv, client, model
    )

    # Sprint 5 BE：fast path 也走 streaming——emit 同样的 LoopEvent
    # 序列让 FE 按统一逻辑显示。fast path 失败时自动 fallback 到 AgentLoop。
    # Open Q-1：追问（recap 非 None）一律走 agent_loop，不走 fast_path。
    decision = route_question(effective_question)
    use_fast_path = decision != "agent_loop" and conv.recap is None

    def run_in_thread_target() -> None:
        result: AgentQueryResult | None = None
        fast_path_already_emitted_route = False
        # WP-retrieval-routing：长上下文路（新问 + 能塞下）。失败 None → 落 fast/loop。
        if _should_use_long_context(assembler) and conv.recap is None:
            _lc_full, _lc_chunks = _long_context_inputs(assembler)
            lc_result = run_long_context(
                effective_question,
                full_text=_lc_full,
                chunks=_lc_chunks,
                llm_client=client,
                model=model,
                extra_system_prompt=extra_system_prompt,
                session_id=request.book_session_id,
                on_event=on_event,
            )
            if lc_result is not None:
                result = lc_result
        if result is None and use_fast_path:
            fast_result = run_fast_path(
                effective_question,
                search_backend=search_backend,  # type: ignore[arg-type]
                llm_client=client,
                model=model,
                on_event=on_event,
                subroute=decision,
                extra_system_prompt=extra_system_prompt,
                session_id=request.book_session_id,
            )
            # fast_path 入口已 emit 过一帧 RouteDecisionEvent，无论成功还是
            # fallback——都不让 AgentLoop 再 emit 一次让 FE 看到两帧路由。
            fast_path_already_emitted_route = True
            if fast_result is not None:
                result = fast_result
            else:
                # fast path 失败 → 走完整 agent loop 兜底；同一 SSE 流里继续 emit
                logger.info(
                    "fast_path returned None for session %s (stream); fallback to AgentLoop",
                    request.book_session_id,
                )
        if result is None:
            # ADR-007 D-4：env 动态分派 r1 / r2。与 /agent/ask 同口径。
            AgentLoopCls = _select_agent_loop_class()
            loop = AgentLoopCls(
                client=client,
                search_chunks_backend=search_backend,  # type: ignore[arg-type]
                chapter_range_backend=backends["chapter_range"],  # type: ignore[arg-type]
                list_characters_backend=backends["list_characters"],  # type: ignore[arg-type]
                model=model,
                on_event=on_event,
                extra_system_prompt=extra_system_prompt,
                session_id=request.book_session_id,
                conversation_context=conv.recap,
                conversation_id=conv.conversation_id,
                turn_index=conv.turn_index,
            )
            result = loop.query(
                effective_question,
                emit_route_decision=not fast_path_already_emitted_route,
            )

        # ADR-009 Phase 1a/1b：答完把这一轮写进对话存储——与同步路一致，
        # 存原题 + 改写后的独立化问题。
        _persist_turn(
            conv_store,
            request.book_session_id,
            conv.conversation_id,
            question=request.question,
            answer=result.answer,
            citations=result.citations,
            rewritten_question=rewritten,
        )

        # WP-reviewcard-userside-removal：评分卡已从用户界面下线（同 provider
        # 自评偏高、5 维只 1 维有区分力，给用户看是误导）。reviewer 评分回路
        # 本身保留——开发期跑 batch、看 prompt 改动有没有用还要靠它——但**不再
        # 通过 SSE 推给用户端**。这里照常跑一次评分并写进日志，供开发者从服务端
        # 日志 / 后续 batch 归档读取；不再 emit review 事件。
        # 注：同步 /agent/ask 端点的 review 字段不受影响（开发 / 案例研究用）。
        review = _try_review_or_none(
            client=client,
            model=model,
            question=effective_question,
            answer=result.answer,
            citations=result.citations,
            book_title=book_title,
            language=language,
        )
        if review is not None:
            logger.info(
                "reviewer 评分（不推给用户）：overall=%d/25 suggest_redo=%s q=%r",
                review.overall_score,
                review.suggest_redo,
                effective_question[:60],
            )

    async def run_loop_in_thread() -> None:
        try:
            await asyncio.to_thread(run_in_thread_target)
        except Exception:  # noqa: BLE001
            # 错误已通过 ErrorEvent 推到 queue；这里只保 task 不爆
            logger.debug("agent loop raised; ErrorEvent already emitted")
        finally:
            asyncio_loop.call_soon_threadsafe(_safe_put, done_sentinel)

    task = asyncio.create_task(run_loop_in_thread())

    async def event_generator() -> Any:
        try:
            while True:
                item = await queue.get()
                if item is done_sentinel:
                    break
                yield _format_sse(item)  # type: ignore[arg-type]
        finally:
            # 客户端断连：取消 task 不行（query 是同步、跑在 thread 里
            # 没 cancellation 钩子），让它自然跑完——callback 里的丢弃
            # 兜底保 agent 主流程不阻塞
            if not task.done():
                # 等到 task 自己结束（不会因为 generator 关闭被卡）；
                # 不 await 让 SSE response close 不阻塞
                pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 让 nginx 类反代关闭缓冲
        },
    )


@agent_router.post("/agent/orchestrate")
async def agent_orchestrate(
    request: OrchestrateRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> StreamingResponse:
    """agent 模式：说目标 → 编排已有分析 → 综合（WP-agent-mode §10），SSE 流式。

    三步（全在 :func:`bookscope.agent.orchestrate.orchestrate` 里，本端点只搭基建）：
    规划（一次 LLM 挑功能）→ 跑（调对应 generate_* 收已核验发现，复用不造新分析）→
    综合（一次 LLM 据发现写带原文证据的回答）。evidence-first：综合每条结论挂得到原文。

    SSE 事件序列（``event: <type>\\ndata: <json>\\n\\n``）：

    - ``plan``：规划挑了哪几个功能 + why
    - ``step``：每个功能跑完一帧（功能名 + 一句话结果 + drill 信息，前端据此点进完整视图）
    - ``synthesis``：综合文 + citations（每条指回某条已核验发现）
    - ``done``：收尾帧，带 trace（token 用量 / 耗时，口径同其它端点）
    - ``error``：出错帧

    Setup-time 错误（session 不存在 / 书太大 / SDK 缺失）走 HTTPException——SSE 头未发，
    客户端能收到正常状态码。只支持塞得进 context 的书（编排的整本功能都要长上下文）。
    """
    assembler = _resolve_assembler(store, request.book_session_id)
    if not _book_fits_long_context(assembler):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_type": "BookTooLargeForOrchestrate",
                "message": (
                    "这本书太大，暂不支持 agent 模式——编排要把整本书进上下文，"
                    "超大书（如几百万字）目前走不了。可以直接用单个分析功能。"
                ),
                "details": None,
            },
        )

    try:
        client = build_llm_client_from_params(
            provider=request.provider,
            api_key=request.api_key,
            base_url=request.base_url,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ProviderSdkMissing",
                "message": str(exc),
                "details": {"provider": request.provider},
            },
        ) from exc
    except Exception as exc:  # noqa: BLE001 — 翻译成 HTTP
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ClientBuildFailed",
                "message": f"{type(exc).__name__}: {exc}",
                "details": {"provider": request.provider},
            },
        ) from exc

    model = request.model or default_model_for(request.provider)
    full_text, chunks = _long_context_inputs(assembler)
    rec = _UsageRecorder(client)

    queue: asyncio.Queue[dict | object] = asyncio.Queue(maxsize=200)
    done_sentinel = object()
    asyncio_loop = asyncio.get_running_loop()

    def _safe_put(item: Any) -> None:
        try:
            queue.put_nowait(item)
        except asyncio.QueueFull:
            logger.warning("orchestrate SSE event queue full; dropping event")

    def on_event(event: dict) -> None:
        # orchestrate 跑在 worker thread；call_soon_threadsafe 跨线程入队
        asyncio_loop.call_soon_threadsafe(_safe_put, event)

    def run_in_thread_target() -> None:
        _t0 = time.monotonic()
        try:
            orchestrate(
                goal=request.goal,
                full_text=full_text,
                chunks=chunks,
                llm_client=rec,
                model=model,
                session_id=request.book_session_id,
                on_event=on_event,
            )
        except Exception as exc:  # noqa: BLE001 — 整体失败 emit error 帧
            logger.warning(
                "orchestrate raised %s: %s", type(exc).__name__, exc
            )
            on_event({
                "type": "error",
                "message": f"{type(exc).__name__}: {exc}",
            })
            return
        # 正常收尾：补一帧 done 带 trace（口径同其它端点）
        on_event({"type": "done", "trace": _run_trace(rec, full_text, _t0)})

    async def run_orchestrate_in_thread() -> None:
        try:
            await asyncio.to_thread(run_in_thread_target)
        finally:
            asyncio_loop.call_soon_threadsafe(_safe_put, done_sentinel)

    task = asyncio.create_task(run_orchestrate_in_thread())

    async def event_generator() -> Any:
        try:
            while True:
                item = await queue.get()
                if item is done_sentinel:
                    break
                yield _format_sse_dict(item)  # type: ignore[arg-type]
        finally:
            if not task.done():
                pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _format_sse_dict(event: dict) -> str:
    """把 orchestrate 的 dict 事件编码成一帧 SSE。

    格式同 ``_format_sse``：``event: <type>\\ndata: <json>\\n\\n``。事件的 ``type``
    字段当 SSE event 名（plan / step / synthesis / done / error）；``data`` 是整个
    事件 dict 的单行 JSON（``ensure_ascii=False`` 保中文可读）。
    """
    event_name = str(event.get("type", "message"))
    payload = json.dumps(event, ensure_ascii=False)
    return f"event: {event_name}\ndata: {payload}\n\n"


def _format_sse(event: LoopEvent) -> str:
    """把 LoopEvent 编码成一帧 SSE。

    格式：``event: <type>\\ndata: <json>\\n\\n``。``data:`` 字段是单行
    JSON（``ensure_ascii=False`` 保中文可读）；``event.type`` 是 Literal
    字面量直接当 SSE event 名。
    """
    payload = json.dumps(asdict(event), ensure_ascii=False)
    return f"event: {event.type}\ndata: {payload}\n\n"


@agent_router.post("/agent/character-graph", response_model=CharacterGraphResponse)
async def agent_character_graph(
    request: CharacterGraphRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> CharacterGraphResponse:
    """抽取一本书的人物/概念关系图（WP-character-graph / WP-exhaustive-extraction）。

    1.4 穷尽化:逐段抽边 + 合并(extract_character_graph_exhaustive),不再整本进一次
    context。**所以不再卡"书太大"**——map-reduce 按段处理,大书(明朝 1069 chunk /
    2535 角色那种)照样能抽,只是段多、耗时长些(并发 + 缓存兜底)。旧的
    ``_book_fits_long_context`` 大书 422 守卫是单次摘要时代的产物,已撤。
    """
    assembler = _resolve_assembler(store, request.book_session_id)

    try:
        client = build_llm_client_from_params(
            provider=request.provider,
            api_key=request.api_key,
            base_url=request.base_url,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ProviderSdkMissing",
                "message": str(exc),
                "details": {"provider": request.provider},
            },
        ) from exc
    except Exception as exc:  # noqa: BLE001 — 翻译成 HTTP
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ClientBuildFailed",
                "message": f"{type(exc).__name__}: {exc}",
                "details": {"provider": request.provider},
            },
        ) from exc

    model = request.model or default_model_for(request.provider)
    full_text, chunks = _long_context_inputs(assembler)
    # 穷尽化(1.4):逐段抽边 + 合并,不再单次摘要硬帽 30 条。人物图把上传时已建好的 KG
    # canonical 角色清单喂进去当节点锚(减别名碎裂);概念图无此清单、由模型逐段自识别。
    known_characters = (
        [c.name for c in assembler._kg.characters]  # noqa: SLF001 — 同既有路由取数惯例
        if request.unit == "person"
        else []
    )
    result = extract_character_graph_exhaustive(
        chunks=chunks,
        llm_client=client,
        model=model,
        known_characters=known_characters,
        unit=request.unit,
        cache_enabled=True,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error_type": "CharacterGraphExtractionFailed",
                "message": "人物关系图抽取失败（模型输出无法解析或调用出错），请重试。",
                "details": None,
            },
        )

    verified_edges = sum(1 for e in result.edges if e.get("verified"))
    return CharacterGraphResponse(
        nodes=result.nodes,
        edges=[GraphEdge(**e) for e in result.edges],
        book_session_id=request.book_session_id,
        trace={
            "duration_ms": result.duration_ms,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "chars": len(full_text),
            "total_edges": len(result.edges),
            "verified_edges": verified_edges,
        },
    )


@agent_router.post("/agent/character-flow", response_model=CharacterFlowResponse)
async def agent_character_flow(
    request: CharacterFlowRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> CharacterFlowResponse:
    """抽一本书的人物叙事流（逐章同场结构，WP-character-narrative-flow，probe GO）。

    1.4 穷尽化：分段并发逐章抽"同场人物 + 同场对" → 按章拼，覆盖全书每一章；每条同场对的
    原文出处过 verify_citations（核不过的标灰）。分段处理，明朝那种塞不进 context 的大书也能
    抽——撤了单次摘要时代的 ``_book_fits_long_context`` 大书返空守卫（同关系图）。
    """
    assembler = _resolve_assembler(store, request.book_session_id)

    try:
        client = build_llm_client_from_params(
            provider=request.provider,
            api_key=request.api_key,
            base_url=request.base_url,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ProviderSdkMissing",
                "message": str(exc),
                "details": {"provider": request.provider},
            },
        ) from exc
    except Exception as exc:  # noqa: BLE001 — 翻译成 HTTP
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ClientBuildFailed",
                "message": f"{type(exc).__name__}: {exc}",
                "details": {"provider": request.provider},
            },
        ) from exc

    model = request.model or default_model_for(request.provider)
    full_text, chunks = _long_context_inputs(assembler)
    rec = _UsageRecorder(client)
    _t0 = time.monotonic()
    chapters = generate_character_flow_exhaustive(
        chunks=chunks,
        llm_client=rec,
        model=model,
    )
    return CharacterFlowResponse(
        chapters=chapters or [],
        scanned=chapters is not None,
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, full_text, _t0),
    )


@agent_router.post("/agent/subplot-weave", response_model=SubplotWeaveResponse)
async def agent_subplot_weave(
    request: SubplotWeaveRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> SubplotWeaveResponse:
    """抽一本书的支线编织结构（支线 + 逐章活跃 + 交汇，WP-subplot-weave，probe GO）。

    1.4 穷尽化：分段并发抽每段支线 + 交汇 → 按支线名并活跃章、按（支线对,章）去重交汇，拼回
    整本编织图。支线 evidence 过 verify_citations（核不过的整条泳道前端淡化，但仍画——支线是
    主观构念）；交汇双端证据都过核验，**两端都命中才画交汇节点**（命根子：编的交汇被滤掉）。
    分段处理，明朝那种塞不进 context 的大书也能抽——撤了 ``_book_fits_long_context`` 守卫。
    """
    assembler = _resolve_assembler(store, request.book_session_id)

    try:
        client = build_llm_client_from_params(
            provider=request.provider,
            api_key=request.api_key,
            base_url=request.base_url,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ProviderSdkMissing",
                "message": str(exc),
                "details": {"provider": request.provider},
            },
        ) from exc
    except Exception as exc:  # noqa: BLE001 — 翻译成 HTTP
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ClientBuildFailed",
                "message": f"{type(exc).__name__}: {exc}",
                "details": {"provider": request.provider},
            },
        ) from exc

    model = request.model or default_model_for(request.provider)
    full_text, chunks = _long_context_inputs(assembler)
    rec = _UsageRecorder(client)
    _t0 = time.monotonic()
    weave = generate_subplot_weave_exhaustive(
        chunks=chunks,
        llm_client=rec,
        model=model,
    )
    return SubplotWeaveResponse(
        subplots=(weave or {}).get("subplots", []),
        intersections=(weave or {}).get("intersections", []),
        scanned=weave is not None,
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, full_text, _t0),
    )


@agent_router.post("/agent/check-citations", response_model=CheckCitationsResponse)
async def agent_check_citations(
    request: CheckCitationsRequest,
) -> CheckCitationsResponse:
    """核每条引用撑不撑得起答案的论述（claim precision，exp-015 GO）。

    前端答完自动调（"只核转述"形态：逐字引用跳过、只核转述/未核验的）。不动 agent
    主路，答案照常秒出、本端点随后补 claim_support 徽标。
    """
    try:
        client = build_llm_client_from_params(
            provider=request.provider,
            api_key=request.api_key,
            base_url=request.base_url,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ProviderSdkMissing",
                "message": str(exc),
                "details": {"provider": request.provider},
            },
        ) from exc
    except Exception as exc:  # noqa: BLE001 — 翻译成 HTTP
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ClientBuildFailed",
                "message": f"{type(exc).__name__}: {exc}",
                "details": {"provider": request.provider},
            },
        ) from exc

    model = request.model or default_model_for(request.provider)
    citations = check_claim_support(
        request.answer,
        request.citations,
        llm_client=client,
        model=model,
    )
    return CheckCitationsResponse(citations=citations)


@agent_router.post("/agent/suggest-questions", response_model=SuggestQuestionsResponse)
async def agent_suggest_questions(
    request: SuggestQuestionsRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> SuggestQuestionsResponse:
    """据整本书出书内专属诊断题（每书自动出题，降"不会问"门槛）。

    整本进 context 让模型据书内具体元素出题。只支持塞得进 context 的书；大书返回空列表
    （前端退回通用诊断题，不报错）。
    """
    assembler = _resolve_assembler(store, request.book_session_id)
    if not _book_fits_long_context(assembler):
        # 大书不硬上——前端有通用诊断题兜底，这里返空不报错
        return SuggestQuestionsResponse(
            questions=[], book_session_id=request.book_session_id
        )

    try:
        client = build_llm_client_from_params(
            provider=request.provider,
            api_key=request.api_key,
            base_url=request.base_url,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ProviderSdkMissing",
                "message": str(exc),
                "details": {"provider": request.provider},
            },
        ) from exc
    except Exception as exc:  # noqa: BLE001 — 翻译成 HTTP
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ClientBuildFailed",
                "message": f"{type(exc).__name__}: {exc}",
                "details": {"provider": request.provider},
            },
        ) from exc

    model = request.model or default_model_for(request.provider)
    full_text, _ = _long_context_inputs(assembler)
    rec = _UsageRecorder(client)
    _t0 = time.monotonic()
    questions = generate_book_questions(
        full_text=full_text,
        llm_client=rec,
        model=model,
        session_id=request.book_session_id,
    )
    # 生成失败 → 返空，前端退回通用诊断题（不报错、不阻断）
    return SuggestQuestionsResponse(
        questions=questions or [],
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, full_text, _t0),
    )


@agent_router.post("/agent/pacing-curve", response_model=PacingCurveResponse)
async def agent_pacing_curve(
    request: PacingCurveRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> PacingCurveResponse:
    """据整本书出逐章节奏张力曲线（节奏可视化，exp-012 GO）。

    整本进 context 让模型逐章打张力分。只支持塞得进 context 的书；大书返空列表。
    """
    assembler = _resolve_assembler(store, request.book_session_id)
    if not _book_fits_long_context(assembler):
        return PacingCurveResponse(points=[], book_session_id=request.book_session_id)

    try:
        client = build_llm_client_from_params(
            provider=request.provider,
            api_key=request.api_key,
            base_url=request.base_url,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ProviderSdkMissing",
                "message": str(exc),
                "details": {"provider": request.provider},
            },
        ) from exc
    except Exception as exc:  # noqa: BLE001 — 翻译成 HTTP
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ClientBuildFailed",
                "message": f"{type(exc).__name__}: {exc}",
                "details": {"provider": request.provider},
            },
        ) from exc

    model = request.model or default_model_for(request.provider)
    full_text, _ = _long_context_inputs(assembler)
    rec = _UsageRecorder(client)
    _t0 = time.monotonic()
    points = generate_pacing_curve(
        full_text=full_text,
        llm_client=rec,
        model=model,
        session_id=request.book_session_id,
    )
    return PacingCurveResponse(
        points=points or [],
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, full_text, _t0),
    )


@agent_router.post("/agent/narrative-curve", response_model=NarrativeCurveResponse)
async def agent_narrative_curve(
    request: NarrativeCurveRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> NarrativeCurveResponse:
    """据整本书逐章抽多维叙事曲线（WP-multidim-narrative-curve，probe GO）。

    1.4 穷尽化：分段并发逐章判张力 + 情感方向 + 主导 POV + 主/支线 → 按章拼，覆盖全书每一章；
    每章判定挂原文片段过 verify_citations（核不过的标低置信）。分段处理，明朝那种塞不进
    context 的大书也能抽——撤了单次摘要时代的 ``_book_fits_long_context`` 大书返空守卫。
    """
    assembler = _resolve_assembler(store, request.book_session_id)

    try:
        client = build_llm_client_from_params(
            provider=request.provider,
            api_key=request.api_key,
            base_url=request.base_url,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ProviderSdkMissing",
                "message": str(exc),
                "details": {"provider": request.provider},
            },
        ) from exc
    except Exception as exc:  # noqa: BLE001 — 翻译成 HTTP
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ClientBuildFailed",
                "message": f"{type(exc).__name__}: {exc}",
                "details": {"provider": request.provider},
            },
        ) from exc

    model = request.model or default_model_for(request.provider)
    full_text, chunks = _long_context_inputs(assembler)
    rec = _UsageRecorder(client)
    _t0 = time.monotonic()
    # 1.4 穷尽化:分段→每段逐章抽→按章拼,覆盖全书每一章(重型逐章单次会截断到几章)。
    chapters = generate_narrative_curve_exhaustive(
        chunks=chunks,
        llm_client=rec,
        model=model,
    )
    return NarrativeCurveResponse(
        chapters=chapters or [],
        scanned=chapters is not None,
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, full_text, _t0),
    )


@agent_router.post("/agent/foreshadow-arcs", response_model=ForeshadowArcsResponse)
async def agent_foreshadow_arcs(
    request: ForeshadowArcsRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> ForeshadowArcsResponse:
    """据整本书抽伏笔→回收弧线（WP-foreshadow-payoff-arcs，伏笔判定 exp-008 GO）。

    1.4 穷尽化：大段 map-reduce 抽每条伏笔的埋点章 + 回收点章 + 两端原文，两端各过
    verify_citations。埋点核不过的整条丢；回收点核不过 / 模型说没回收 = 断弧
    （``status="dangling"``，埋了没回收，前端画灰虚线悬空）。分段处理，明朝那种塞不进
    context 的大书也能抽——撤了 ``_book_fits_long_context`` 守卫。伏笔天生跨章，故用比逐章
    功能大得多的段预算（80k 字）把段数压到最少，让绝大多数埋点+回收落同段、仍能配对。
    """
    assembler = _resolve_assembler(store, request.book_session_id)

    try:
        client = build_llm_client_from_params(
            provider=request.provider,
            api_key=request.api_key,
            base_url=request.base_url,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ProviderSdkMissing",
                "message": str(exc),
                "details": {"provider": request.provider},
            },
        ) from exc
    except Exception as exc:  # noqa: BLE001 — 翻译成 HTTP
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ClientBuildFailed",
                "message": f"{type(exc).__name__}: {exc}",
                "details": {"provider": request.provider},
            },
        ) from exc

    model = request.model or default_model_for(request.provider)
    full_text, chunks = _long_context_inputs(assembler)
    rec = _UsageRecorder(client)
    _t0 = time.monotonic()
    arcs = generate_foreshadow_arcs_exhaustive(
        chunks=chunks,
        llm_client=rec,
        model=model,
    )
    return ForeshadowArcsResponse(
        arcs=arcs or [],
        scanned=arcs is not None,
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, full_text, _t0),
    )


@agent_router.post("/agent/character-arc", response_model=CharacterArcResponse)
async def agent_character_arc(
    request: CharacterArcRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> CharacterArcResponse:
    """给主要角色逐章抽戏份/处境弧线曲线（WP-character-arc-curves，probe GO）。

    1.4 穷尽化：分段并发给主要角色逐章打戏份密度（presence 0-10）+ 处境弧线（fortune -5..+5）
    → 按角色名合并、逐章点跨段并集，每个点挂原文片段过 verify_citations（核不过的标低置信）。
    把已验的 exp-010 弧线分析画成可核验曲线，不重造判定——平稳角色画平、不编波动。分段处理，
    明朝那种塞不进 context 的大书也能抽——撤了 ``_book_fits_long_context`` 守卫。
    """
    assembler = _resolve_assembler(store, request.book_session_id)

    try:
        client = build_llm_client_from_params(
            provider=request.provider,
            api_key=request.api_key,
            base_url=request.base_url,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ProviderSdkMissing",
                "message": str(exc),
                "details": {"provider": request.provider},
            },
        ) from exc
    except Exception as exc:  # noqa: BLE001 — 翻译成 HTTP
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ClientBuildFailed",
                "message": f"{type(exc).__name__}: {exc}",
                "details": {"provider": request.provider},
            },
        ) from exc

    model = request.model or default_model_for(request.provider)
    full_text, chunks = _long_context_inputs(assembler)
    rec = _UsageRecorder(client)
    _t0 = time.monotonic()
    characters = generate_character_arc_exhaustive(
        chunks=chunks,
        llm_client=rec,
        model=model,
    )
    return CharacterArcResponse(
        characters=characters or [],
        scanned=characters is not None,
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, full_text, _t0),
    )


@agent_router.post("/agent/character-voice", response_model=CharacterVoiceResponse)
async def agent_character_voice(
    request: CharacterVoiceRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> CharacterVoiceResponse:
    """给一个角色刻画声口 + 标"这句不像他说的"（WP-character-voice，probe GO）。

    整本进 context 让模型归拢该角色对白、列语言特征（每条挂代表对白）、标 voice drift
    （每条挂那句对白 + 章 + 为什么不像）。features 保留全部（核不过的标低置信），
    drift_items 已 verify-filter（挂不上原文的不报，免得 cry wolf）。命根子写进 prompt：
    合理的剧情驱动口吻变化不报、样本不足明说、不把别人的话算到他头上。
    只支持塞得进 context 的书；大书返空（``scanned=false``，前端提示重试）。
    """
    assembler = _resolve_assembler(store, request.book_session_id)
    if not _book_fits_long_context(assembler):
        return CharacterVoiceResponse(
            character=request.character,
            sample_too_small=False,
            features=[],
            drift_items=[],
            scanned=False,
            book_session_id=request.book_session_id,
        )

    try:
        client = build_llm_client_from_params(
            provider=request.provider,
            api_key=request.api_key,
            base_url=request.base_url,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ProviderSdkMissing",
                "message": str(exc),
                "details": {"provider": request.provider},
            },
        ) from exc
    except Exception as exc:  # noqa: BLE001 — 翻译成 HTTP
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ClientBuildFailed",
                "message": f"{type(exc).__name__}: {exc}",
                "details": {"provider": request.provider},
            },
        ) from exc

    model = request.model or default_model_for(request.provider)
    full_text, chunks = _long_context_inputs(assembler)
    rec = _UsageRecorder(client)
    _t0 = time.monotonic()
    result = generate_character_voice(
        character=request.character,
        full_text=full_text,
        chunks=chunks,
        llm_client=rec,
        model=model,
        session_id=request.book_session_id,
    )
    return CharacterVoiceResponse(
        character=request.character,
        sample_too_small=bool(result and result.get("sample_too_small")),
        features=(result or {}).get("features", []),
        drift_items=(result or {}).get("drift_items", []),
        scanned=result is not None,
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, full_text, _t0),
    )


@agent_router.post(
    "/agent/relationship-timeline", response_model=RelationshipTimelineResponse
)
async def agent_relationship_timeline(
    request: RelationshipTimelineRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> RelationshipTimelineResponse:
    """据整本书逐对主要关系抽演变（WP-relationship-over-time，probe GO）。

    1.4 穷尽化：分段并发逐对关系吐逐章强度 + 关键转折 → 按无向人物对合并、强度点 / 转折跨段
    并集，每个转折挂原文片段过 verify_citations（核不过的标低置信）。分段处理，明朝那种塞不进
    context 的大书也能抽——撤了 ``_book_fits_long_context`` 守卫。
    """
    assembler = _resolve_assembler(store, request.book_session_id)

    try:
        client = build_llm_client_from_params(
            provider=request.provider,
            api_key=request.api_key,
            base_url=request.base_url,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ProviderSdkMissing",
                "message": str(exc),
                "details": {"provider": request.provider},
            },
        ) from exc
    except Exception as exc:  # noqa: BLE001 — 翻译成 HTTP
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ClientBuildFailed",
                "message": f"{type(exc).__name__}: {exc}",
                "details": {"provider": request.provider},
            },
        ) from exc

    model = request.model or default_model_for(request.provider)
    full_text, chunks = _long_context_inputs(assembler)
    rec = _UsageRecorder(client)
    _t0 = time.monotonic()
    relations = generate_relationship_timeline_exhaustive(
        chunks=chunks,
        llm_client=rec,
        model=model,
    )
    return RelationshipTimelineResponse(
        relations=relations or [],
        scanned=relations is not None,
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, full_text, _t0),
    )


@agent_router.post("/agent/consistency-scan", response_model=ConsistencyScanResponse)
async def agent_consistency_scan(
    request: ConsistencyScanRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> ConsistencyScanResponse:
    """扫全书找设定一致性矛盾（exp-011 GO）。

    整本进 context 找前后矛盾，每条两处证据都过原文核验（编的矛盾被滤掉）。
    ``scanned=true`` + 空 = 书自洽；``scanned=false`` = 扫失败/书太大，前端提示重试。
    """
    assembler = _resolve_assembler(store, request.book_session_id)
    if not _book_fits_long_context(assembler):
        return ConsistencyScanResponse(
            contradictions=[], scanned=False, book_session_id=request.book_session_id
        )

    try:
        client = build_llm_client_from_params(
            provider=request.provider,
            api_key=request.api_key,
            base_url=request.base_url,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ProviderSdkMissing",
                "message": str(exc),
                "details": {"provider": request.provider},
            },
        ) from exc
    except Exception as exc:  # noqa: BLE001 — 翻译成 HTTP
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ClientBuildFailed",
                "message": f"{type(exc).__name__}: {exc}",
                "details": {"provider": request.provider},
            },
        ) from exc

    model = request.model or default_model_for(request.provider)
    full_text, chunks = _long_context_inputs(assembler)
    rec = _UsageRecorder(client)
    _t0 = time.monotonic()
    result = generate_consistency_scan(
        full_text=full_text,
        chunks=chunks,
        llm_client=rec,
        model=model,
        session_id=request.book_session_id,
    )
    return ConsistencyScanResponse(
        contradictions=result or [],
        scanned=result is not None,
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, full_text, _t0),
    )


@agent_router.post("/agent/timeline", response_model=TimelineResponse)
async def agent_timeline(
    request: TimelineRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> TimelineResponse:
    """据整本书出按时序的事件时间线（读者发明区）。

    1.4 穷尽化：分段并发梳理事件 → 按事件文字去重、按章重排 + 重编号，每条 evidence 过原文
    核验。分段处理，大书也能跑——撤了 ``_book_fits_long_context`` 守卫。``scanned=false`` = 失败。
    """
    assembler = _resolve_assembler(store, request.book_session_id)

    try:
        client = build_llm_client_from_params(
            provider=request.provider,
            api_key=request.api_key,
            base_url=request.base_url,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ProviderSdkMissing",
                "message": str(exc),
                "details": {"provider": request.provider},
            },
        ) from exc
    except Exception as exc:  # noqa: BLE001 — 翻译成 HTTP
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ClientBuildFailed",
                "message": f"{type(exc).__name__}: {exc}",
                "details": {"provider": request.provider},
            },
        ) from exc

    model = request.model or default_model_for(request.provider)
    full_text, chunks = _long_context_inputs(assembler)
    rec = _UsageRecorder(client)
    _t0 = time.monotonic()
    events = generate_timeline_exhaustive(
        chunks=chunks,
        llm_client=rec,
        model=model,
    )
    return TimelineResponse(
        events=events or [],
        scanned=events is not None,
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, full_text, _t0),
    )


@agent_router.post("/agent/entity-recall", response_model=EntityRecallResponse)
async def agent_entity_recall(
    request: EntityRecallRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> EntityRecallResponse:
    """回溯一个实体在全书的出现轨迹（功能队列第 1 个）。

    整本进 context、按章节先后列出该实体每次出现 + 在做什么 + 一句原文，每处过原文核验。
    ``scanned=false`` = 失败/书太大；``scanned=true`` + 空列表 = 扫过但书里没这个实体（合法）。
    """
    assembler = _resolve_assembler(store, request.book_session_id)
    if not _book_fits_long_context(assembler):
        return EntityRecallResponse(
            entity=request.entity,
            appearances=[],
            scanned=False,
            book_session_id=request.book_session_id,
        )

    try:
        client = build_llm_client_from_params(
            provider=request.provider,
            api_key=request.api_key,
            base_url=request.base_url,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ProviderSdkMissing",
                "message": str(exc),
                "details": {"provider": request.provider},
            },
        ) from exc
    except Exception as exc:  # noqa: BLE001 — 翻译成 HTTP
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ClientBuildFailed",
                "message": f"{type(exc).__name__}: {exc}",
                "details": {"provider": request.provider},
            },
        ) from exc

    model = request.model or default_model_for(request.provider)
    full_text, chunks = _long_context_inputs(assembler)
    rec = _UsageRecorder(client)
    _t0 = time.monotonic()
    appearances = generate_entity_recall(
        entity=request.entity,
        full_text=full_text,
        chunks=chunks,
        llm_client=rec,
        model=model,
        session_id=request.book_session_id,
    )
    return EntityRecallResponse(
        entity=request.entity,
        appearances=appearances or [],
        scanned=appearances is not None,
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, full_text, _t0),
    )


@agent_router.post("/agent/argument-structure", response_model=ArgumentStructureResponse)
async def agent_argument_structure(
    request: ArgumentStructureRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> ArgumentStructureResponse:
    """梳理一本书的论点结构（学习者发明区）。

    1.4 穷尽化：分段并发列每段主要主张 → 按主张文字去重、按章重排 + 重编号，每条过原文核验。
    分段处理，大书也能跑——撤了 ``_book_fits_long_context`` 守卫。``scanned=false`` = 失败。
    """
    assembler = _resolve_assembler(store, request.book_session_id)

    try:
        client = build_llm_client_from_params(
            provider=request.provider,
            api_key=request.api_key,
            base_url=request.base_url,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ProviderSdkMissing",
                "message": str(exc),
                "details": {"provider": request.provider},
            },
        ) from exc
    except Exception as exc:  # noqa: BLE001 — 翻译成 HTTP
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ClientBuildFailed",
                "message": f"{type(exc).__name__}: {exc}",
                "details": {"provider": request.provider},
            },
        ) from exc

    model = request.model or default_model_for(request.provider)
    full_text, chunks = _long_context_inputs(assembler)
    rec = _UsageRecorder(client)
    _t0 = time.monotonic()
    claims = generate_argument_structure_exhaustive(
        chunks=chunks,
        llm_client=rec,
        model=model,
    )
    return ArgumentStructureResponse(
        claims=claims or [],
        scanned=claims is not None,
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, full_text, _t0),
    )


@agent_router.post("/agent/style-issues", response_model=StyleIssuesResponse)
async def agent_style_issues(
    request: StyleIssuesRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> StyleIssuesResponse:
    """扫一本书的文体级毛病（作家发明区：用词重复/视角越界/支线失踪）。

    整本进 context、保守地报清楚的毛病，每条原文核验、编的丢。``scanned=false`` = 失败/
    书太大；``scanned=true`` + 空列表 = 扫过没毛病。
    """
    assembler = _resolve_assembler(store, request.book_session_id)
    if not _book_fits_long_context(assembler):
        return StyleIssuesResponse(
            issues=[], scanned=False, book_session_id=request.book_session_id
        )

    try:
        client = build_llm_client_from_params(
            provider=request.provider,
            api_key=request.api_key,
            base_url=request.base_url,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ProviderSdkMissing",
                "message": str(exc),
                "details": {"provider": request.provider},
            },
        ) from exc
    except Exception as exc:  # noqa: BLE001 — 翻译成 HTTP
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ClientBuildFailed",
                "message": f"{type(exc).__name__}: {exc}",
                "details": {"provider": request.provider},
            },
        ) from exc

    model = request.model or default_model_for(request.provider)
    full_text, chunks = _long_context_inputs(assembler)
    rec = _UsageRecorder(client)
    _t0 = time.monotonic()
    issues = generate_style_issues(
        full_text=full_text,
        chunks=chunks,
        llm_client=rec,
        model=model,
        session_id=request.book_session_id,
    )
    return StyleIssuesResponse(
        issues=issues or [],
        scanned=issues is not None,
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, full_text, _t0),
    )


@agent_router.post("/agent/recap", response_model=RecapResponse)
async def agent_recap(
    request: RecapRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> RecapResponse:
    """无剧透前情回顾（读者发明区）。

    只把第 1..up_to_chapter 章的原文喂进 context（后文物理上不喂 = 结构性无剧透），
    回顾到此为止的前情。``scanned=false`` = 失败/书太大/该章前无可识别原文。
    """
    assembler = _resolve_assembler(store, request.book_session_id)
    if not _book_fits_long_context(assembler):
        return RecapResponse(
            up_to_chapter=request.up_to_chapter,
            points=[],
            scanned=False,
            book_session_id=request.book_session_id,
        )

    # 只取 ≤X 章的 chunk 拼上下文 + 当核验 evidence（后文不喂 = 无剧透的结构保证）
    _full, all_chunks = _long_context_inputs(assembler)
    x = request.up_to_chapter
    partial = [c for c in all_chunks if 1 <= int(c.get("chapter", 0)) <= x]
    if not partial:
        return RecapResponse(
            up_to_chapter=x,
            points=[],
            scanned=False,
            book_session_id=request.book_session_id,
        )
    partial_text = "".join(c["text"] for c in partial)

    try:
        client = build_llm_client_from_params(
            provider=request.provider,
            api_key=request.api_key,
            base_url=request.base_url,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ProviderSdkMissing",
                "message": str(exc),
                "details": {"provider": request.provider},
            },
        ) from exc
    except Exception as exc:  # noqa: BLE001 — 翻译成 HTTP
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ClientBuildFailed",
                "message": f"{type(exc).__name__}: {exc}",
                "details": {"provider": request.provider},
            },
        ) from exc

    model = request.model or default_model_for(request.provider)
    rec = _UsageRecorder(client)
    _t0 = time.monotonic()
    points = generate_recap(
        up_to_chapter=x,
        full_text=partial_text,
        chunks=partial,
        llm_client=rec,
        model=model,
        session_id=request.book_session_id,
    )
    return RecapResponse(
        up_to_chapter=x,
        points=points or [],
        scanned=points is not None,
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, partial_text, _t0),
    )


# 本章导读的预设问（question 留空时用）。
_CHAPTER_DIGEST_Q = (
    "只看这一章的原文：这一章主要发生了什么？有哪些人物登场？挑出三到五个关键处。"
    "每条都引本章原文，不用书外知识、不臆测、不剧透后文。"
)


@agent_router.post("/agent/chapter-ask", response_model=ChapterAskResponse)
async def agent_chapter_ask(
    request: ChapterAskRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> ChapterAskResponse:
    """按章问答 / 本章导读：只把第 ``chapter`` 章原文喂进 context，贴着在读这一章作答。

    复用 ``run_long_context``，把输入从整本缩到单章——本章原文就是证据，citation 在本章内
    verify。``question`` 留空 = 本章导读（预设问）。该章无可识别原文 / 失败 → ``scanned=false``
    （不报错，前端兜底"这章没取到可分析的原文"）。
    """
    assembler = _resolve_assembler(store, request.book_session_id)
    ch = request.chapter
    # 只取本章 chunk 当 context + 证据（其它章物理上不喂 = 按章 scoped 的结构保证）。
    _full, all_chunks = _long_context_inputs(assembler)
    chap_chunks = [c for c in all_chunks if int(c.get("chapter", 0)) == ch]
    if not chap_chunks:
        return ChapterAskResponse(
            chapter=ch,
            answer="",
            citations=[],
            scanned=False,
            book_session_id=request.book_session_id,
        )
    chap_text = "".join(c["text"] for c in chap_chunks)

    try:
        client = build_llm_client_from_params(
            provider=request.provider,
            api_key=request.api_key,
            base_url=request.base_url,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ProviderSdkMissing",
                "message": str(exc),
                "details": {"provider": request.provider},
            },
        ) from exc
    except Exception as exc:  # noqa: BLE001 — 翻译成 HTTP
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ClientBuildFailed",
                "message": f"{type(exc).__name__}: {exc}",
                "details": {"provider": request.provider},
            },
        ) from exc

    model = request.model or default_model_for(request.provider)
    question = request.question.strip() or _CHAPTER_DIGEST_Q
    rec = _UsageRecorder(client)
    _t0 = time.monotonic()
    result = run_long_context(
        question,
        full_text=chap_text,
        chunks=chap_chunks,
        llm_client=rec,
        model=model,
        session_id=request.book_session_id,
    )
    if result is None:
        return ChapterAskResponse(
            chapter=ch,
            answer="",
            citations=[],
            scanned=False,
            book_session_id=request.book_session_id,
            trace=_run_trace(rec, chap_text, _t0),
        )
    return ChapterAskResponse(
        chapter=ch,
        answer=result.answer,
        citations=result.citations,
        scanned=True,
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, chap_text, _t0),
    )


@agent_router.post("/agent/concept-evolution", response_model=ConceptEvolutionResponse)
async def agent_concept_evolution(
    request: ConceptEvolutionRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> ConceptEvolutionResponse:
    """回溯一个概念在全书的演进（学习者发明区）。

    整本进 context、按章节先后列出概念的发展阶段，每条原文核验、核验不过的丢。
    ``scanned=false`` = 失败/书太大；``scanned=true`` + 空列表 = 概念不在书 / 没核验得了的阶段。
    """
    assembler = _resolve_assembler(store, request.book_session_id)
    if not _book_fits_long_context(assembler):
        return ConceptEvolutionResponse(
            concept=request.concept,
            stages=[],
            scanned=False,
            book_session_id=request.book_session_id,
        )

    try:
        client = build_llm_client_from_params(
            provider=request.provider,
            api_key=request.api_key,
            base_url=request.base_url,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ProviderSdkMissing",
                "message": str(exc),
                "details": {"provider": request.provider},
            },
        ) from exc
    except Exception as exc:  # noqa: BLE001 — 翻译成 HTTP
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ClientBuildFailed",
                "message": f"{type(exc).__name__}: {exc}",
                "details": {"provider": request.provider},
            },
        ) from exc

    model = request.model or default_model_for(request.provider)
    full_text, chunks = _long_context_inputs(assembler)
    rec = _UsageRecorder(client)
    _t0 = time.monotonic()
    stages = generate_concept_evolution(
        concept=request.concept,
        full_text=full_text,
        chunks=chunks,
        llm_client=rec,
        model=model,
        session_id=request.book_session_id,
    )
    return ConceptEvolutionResponse(
        concept=request.concept,
        stages=stages or [],
        scanned=stages is not None,
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, full_text, _t0),
    )


@agent_router.post("/agent/motif-tracking", response_model=MotifTrackingResponse)
async def agent_motif_tracking(
    request: MotifTrackingRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> MotifTrackingResponse:
    """追踪一个主题/母题在全书的复现（读者发明区）。

    整本进 context、按章节先后列出母题复现处，每条原文核验、核验不过的丢。
    ``scanned=false`` = 失败/书太大；``scanned=true`` + 空列表 = 母题不在书 / 没核验得了的复现。
    """
    assembler = _resolve_assembler(store, request.book_session_id)
    if not _book_fits_long_context(assembler):
        return MotifTrackingResponse(
            motif=request.motif,
            occurrences=[],
            scanned=False,
            book_session_id=request.book_session_id,
        )

    try:
        client = build_llm_client_from_params(
            provider=request.provider,
            api_key=request.api_key,
            base_url=request.base_url,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ProviderSdkMissing",
                "message": str(exc),
                "details": {"provider": request.provider},
            },
        ) from exc
    except Exception as exc:  # noqa: BLE001 — 翻译成 HTTP
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ClientBuildFailed",
                "message": f"{type(exc).__name__}: {exc}",
                "details": {"provider": request.provider},
            },
        ) from exc

    model = request.model or default_model_for(request.provider)
    full_text, chunks = _long_context_inputs(assembler)
    rec = _UsageRecorder(client)
    _t0 = time.monotonic()
    occurrences = generate_motif_tracking(
        motif=request.motif,
        full_text=full_text,
        chunks=chunks,
        llm_client=rec,
        model=model,
        session_id=request.book_session_id,
    )
    return MotifTrackingResponse(
        motif=request.motif,
        occurrences=occurrences or [],
        scanned=occurrences is not None,
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, full_text, _t0),
    )


@agent_router.post("/agent/writing-technique", response_model=WritingTechniqueResponse)
async def agent_writing_technique(
    request: WritingTechniqueRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> WritingTechniqueResponse:
    """分析一本书的写作手法（学习者发明区：学手艺）。

    整本进 context、列出显著手法 + 原文例子，每条原文核验、核验不过的丢。
    ``scanned=false`` = 失败/书太大；``scanned=true`` + 空列表 = 没核验得了的显著手法。
    """
    assembler = _resolve_assembler(store, request.book_session_id)
    if not _book_fits_long_context(assembler):
        return WritingTechniqueResponse(
            techniques=[], scanned=False, book_session_id=request.book_session_id
        )

    try:
        client = build_llm_client_from_params(
            provider=request.provider,
            api_key=request.api_key,
            base_url=request.base_url,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ProviderSdkMissing",
                "message": str(exc),
                "details": {"provider": request.provider},
            },
        ) from exc
    except Exception as exc:  # noqa: BLE001 — 翻译成 HTTP
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ClientBuildFailed",
                "message": f"{type(exc).__name__}: {exc}",
                "details": {"provider": request.provider},
            },
        ) from exc

    model = request.model or default_model_for(request.provider)
    full_text, chunks = _long_context_inputs(assembler)
    rec = _UsageRecorder(client)
    _t0 = time.monotonic()
    techniques = generate_writing_technique(
        full_text=full_text,
        chunks=chunks,
        llm_client=rec,
        model=model,
        session_id=request.book_session_id,
    )
    return WritingTechniqueResponse(
        techniques=techniques or [],
        scanned=techniques is not None,
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, full_text, _t0),
    )


@agent_router.post("/agent/study-cards", response_model=StudyCardsResponse)
async def agent_study_cards(
    request: StudyCardsRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> StudyCardsResponse:
    """据一本书出知识点卡片（学习者发明区：含启发自测题）。

    整本进 context、列出知识点 + 自测题 + 原文依据，每条原文核验、核验不过的丢。
    ``scanned=false`` = 失败/书太大；``scanned=true`` + 空列表 = 没核验得了的知识点。
    """
    assembler = _resolve_assembler(store, request.book_session_id)
    if not _book_fits_long_context(assembler):
        return StudyCardsResponse(
            cards=[], scanned=False, book_session_id=request.book_session_id
        )

    try:
        client = build_llm_client_from_params(
            provider=request.provider,
            api_key=request.api_key,
            base_url=request.base_url,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ProviderSdkMissing",
                "message": str(exc),
                "details": {"provider": request.provider},
            },
        ) from exc
    except Exception as exc:  # noqa: BLE001 — 翻译成 HTTP
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ClientBuildFailed",
                "message": f"{type(exc).__name__}: {exc}",
                "details": {"provider": request.provider},
            },
        ) from exc

    model = request.model or default_model_for(request.provider)
    full_text, chunks = _long_context_inputs(assembler)
    rec = _UsageRecorder(client)
    _t0 = time.monotonic()
    cards = generate_study_cards(
        full_text=full_text,
        chunks=chunks,
        llm_client=rec,
        model=model,
        session_id=request.book_session_id,
    )
    return StudyCardsResponse(
        cards=cards or [],
        scanned=cards is not None,
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, full_text, _t0),
    )


@agent_router.post("/agent/annotations", response_model=AnnotationsResponse)
async def agent_annotations(
    request: AnnotationsRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> AnnotationsResponse:
    """精读注释层（WP-annotated-reading）——把已有分析按原文位置摆成行间注释。

    **不跑新 LLM 抽取**：按选中的 ``layers`` 调已建的整本书分析当数据源（foreshadow /
    motif / contradiction / entity），收**已核验**的结论映射成注释，verified=false 的
    一律不进（evidence-first）。同时重建有注释那些章的原文供阅读视图显示。只支持塞得进
    context 的书；大书返空（``scanned=[]``，前端提示重试）。v1 按选中 layer 现跑对应源
    （每个整本、几分钟），多 layer 会慢——已知 v1 限制。
    """
    assembler = _resolve_assembler(store, request.book_session_id)
    if not _book_fits_long_context(assembler):
        return AnnotationsResponse(
            annotations=[],
            chapters=[],
            scanned=[],
            book_session_id=request.book_session_id,
        )

    try:
        client = build_llm_client_from_params(
            provider=request.provider,
            api_key=request.api_key,
            base_url=request.base_url,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ProviderSdkMissing",
                "message": str(exc),
                "details": {"provider": request.provider},
            },
        ) from exc
    except Exception as exc:  # noqa: BLE001 — 翻译成 HTTP
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ClientBuildFailed",
                "message": f"{type(exc).__name__}: {exc}",
                "details": {"provider": request.provider},
            },
        ) from exc

    model = request.model or default_model_for(request.provider)
    full_text, chunks = _long_context_inputs(assembler)
    rec = _UsageRecorder(client)
    _t0 = time.monotonic()
    result = generate_annotations(
        layers=request.layers,
        full_text=full_text,
        chunks=chunks,
        llm_client=rec,
        model=model,
        entity=request.entity,
        motif=request.motif,
        session_id=request.book_session_id,
    )
    return AnnotationsResponse(
        annotations=result["annotations"],
        chapters=result["chapters"],
        scanned=result["scanned"],
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, full_text, _t0),
    )


# ---------------------------------------------------------------------------
# 内部工具：尽量让 agent_ask 主体保持扁平可读
# ---------------------------------------------------------------------------


def _should_use_long_context(assembler: R0BookAssembler) -> bool:
    """WP-retrieval-routing：书塞得进 context（exp-009 GO）→ 默认走长上下文直读。

    **2026-06-16 转默认**（WP-agent-token-budget §3.6，作者批"翻"）：三道护栏全绿后
    转默认——回退 0% / 缓存命中 100% / 引用真实性 100%（= RAG，anshi 实测），且快 2–4 倍。
    ``BOOKSCOPE_LONGCTX`` 默认开；显式设 ``off`` / ``0`` / ``false`` / ``no`` 关回 RAG（逃生口）。
    书大小按字符 × 0.68 估 token，≤ ``BOOKSCOPE_LONGCTX_MAX_TOKENS``（默认 60 万）才走；
    估偏大也安全（退回 RAG）。长上下文万一失败还有优雅回退兜底。
    """
    if os.environ.get("BOOKSCOPE_LONGCTX", "on").strip().lower() in (
        "0",
        "off",
        "false",
        "no",
    ):
        return False
    return _book_fits_long_context(assembler)


def _book_fits_long_context(assembler: R0BookAssembler) -> bool:
    """书塞不塞得进 context（字符 × 0.68 估 token ≤ 上限）。纯大小判断，不看 flag。

    人物关系图等"必须整本进 context"的功能用它做大小闸（无视 BOOKSCOPE_LONGCTX
    灰度 flag——那个 flag 只管问答流要不要走长上下文路）。
    """
    try:
        chars = len(assembler._book_text.raw_text)  # noqa: SLF001 — 同 book_cache 既有取法
    except Exception:  # noqa: BLE001
        return False
    max_tokens = int(os.environ.get("BOOKSCOPE_LONGCTX_MAX_TOKENS", "600000"))
    return chars * 0.68 <= max_tokens


def _long_context_inputs(assembler: R0BookAssembler) -> tuple[str, list[dict]]:
    """取整本文本 + 全书 chunks（给 citation 校验当证据 + 章号 ground truth）。

    chapter 填真章号（assembler 的 chunk→chapter 归一化映射，与 RAG 同口径）：
    长上下文模型自报章号会漂（exp-009/010 caveat），snippet verify 命中某 chunk
    后由 ``run_long_context`` 用这里的真章号覆盖模型自报值。映射拿不到的 chunk 退 0。
    """
    full_text = assembler._book_text.raw_text  # noqa: SLF001
    chunk_to_chapter = assembler._compute_chunk_to_chapter_map()  # noqa: SLF001
    chunks = [
        {
            "chunk_id": f"r0-chunk-{c.index}",
            "chapter": chunk_to_chapter.get(c.index, 0),
            "text": c.text,
        }
        for c in assembler._chunks  # noqa: SLF001
    ]
    return full_text, chunks


class _UsageRecorder:
    """把 LLM client 包一层，旁路记下每轮 ``messages_create`` 的 token 用量。

    整本书结构化功能（关系图 / 节奏 / 时间线…）都走 ``client.messages_create``，但生成
    函数只读 final_text、把 usage 丢了。这层透传 response、不改任何返回形态，只按 adapter
    自己的 ``extract_usage_tokens`` 累加 token——给前端"运行过程可视化"出真实用量。

    缓存命中时 ``invoke_client_cached`` 直接返反序列化结果、根本不碰 ``messages_create``，
    所以命中那次记 0 token——这是对的：命中没花钱，用户该看到 0。
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.input_tokens = 0
        self.output_tokens = 0
        self.calls = 0

    def messages_create(self, **kwargs: Any) -> Any:
        resp = self._inner.messages_create(**kwargs)
        try:
            it, ot = self._inner.extract_usage_tokens(resp)
            self.input_tokens += int(it or 0)
            self.output_tokens += int(ot or 0)
            self.calls += 1
        except Exception:  # noqa: BLE001 — 记账失败绝不能拖垮主流程
            pass
        return resp

    def __getattr__(self, name: str) -> Any:
        # extract_final_text / extract_usage_tokens / 其它属性都透传给真 client
        return getattr(self._inner, name)


def _run_trace(rec: _UsageRecorder, full_text: str, started: float) -> dict[str, int]:
    """组装"运行过程"trace：花了多少 token、读了多少字、用了多久。前端据此可视化。"""
    return {
        "input_tokens": rec.input_tokens,
        "output_tokens": rec.output_tokens,
        "chars": len(full_text),
        "duration_ms": int((time.monotonic() - started) * 1000),
    }


def _resolve_assembler(
    store: BookSessionStore,
    session_id: str,
) -> R0BookAssembler:
    """从 store 取 assembler；失败翻译为 HTTP 404。"""
    try:
        return store.get(session_id)
    except BookSessionNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_type": "BookSessionNotFound",
                "message": str(exc),
                "details": {"book_session_id": session_id},
            },
        ) from exc


def _build_client_or_raise(request: AgentAskRequest) -> Any:
    """构造 LLM client；SDK 未装 / 参数非法一律翻译为 HTTP 400。"""
    try:
        return build_llm_client(request)
    except ImportError as exc:
        # 例如用户选 deepseek 但 openai SDK 没装。
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ProviderSdkMissing",
                "message": str(exc),
                "details": {"provider": request.provider},
            },
        ) from exc
    except Exception as exc:  # noqa: BLE001 — 显式捕获以翻译 HTTP
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ClientBuildFailed",
                "message": f"{type(exc).__name__}: {exc}",
                "details": {"provider": request.provider},
            },
        ) from exc


def _run_loop_or_raise(loop: Any, question: str) -> Any:
    """跑 ``AgentLoop.query``；所有已知错误翻译为合适的 HTTP 状态。"""
    try:
        return loop.query(question)
    except ProviderUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error_type": "ProviderUnavailable",
                "message": str(exc),
                "details": None,
            },
        ) from exc
    except RateLimited as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error_type": "RateLimited",
                "message": str(exc),
                "details": None,
            },
        ) from exc
    except ContextLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "error_type": "ContextLimitExceeded",
                "message": str(exc),
                "details": None,
            },
        ) from exc
    except ContentFiltered as exc:
        # provider 内容审核拒绝输出 → 502（与 ProviderUnavailable 同档：
        # provider-level 错误统一 502，前端按 error_type 区分子类，按
        # PM 文案 BYOK provider-agnostic 原则不暴露具体厂商）。
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error_type": "ContentFiltered",
                "message": str(exc),
                "details": None,
            },
        ) from exc
    except MaxIterationsExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={
                "error_type": "MaxIterationsExceeded",
                "message": str(exc),
                "details": {"max_iterations": exc.max_iterations},
                # WP5a：失败前已查到的原文证据；FE ErrorBanner 渲染
                "partial_evidence": getattr(exc, "partial_evidence", []),
            },
        ) from exc
    except LoopTimeout as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={
                "error_type": "LoopTimeout",
                "message": str(exc),
                "details": {
                    "timeout_seconds": exc.timeout_seconds,
                    "elapsed_seconds": exc.elapsed_seconds,
                },
                # WP5a：同 MaxIterationsExceeded
                "partial_evidence": getattr(exc, "partial_evidence", []),
            },
        ) from exc
    except LLMFormatError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error_type": "LLMFormatError",
                "message": str(exc),
                "details": None,
            },
        ) from exc
    except ToolDispatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error_type": "ToolDispatchError",
                "message": str(exc),
                "details": {"tool_name": exc.tool_name},
            },
        ) from exc
    except AgentError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error_type": type(exc).__name__,
                "message": str(exc),
                "details": None,
            },
        ) from exc


_REVIEW_RUBRIC_DIMENSIONS: tuple[str, ...] = (
    "structural_judgment",
    "evidence_density",
    "honesty",
    "actionability",
    "cross_chapter_coherence",
)
"""rubric_v1 五个维度名（与 ``reviewer_rubric_v1.md`` / 校验逻辑一致）。"""

_REVIEW_DIMENSION_LABELS: dict[str, str] = {
    "structural_judgment": "判断而非复述",
    "evidence_density": "证据厚度",
    "honesty": "诚实度",
    "actionability": "可操作",
    "cross_chapter_coherence": "跨章节视野",
}
"""5 维 rubric 维度的中文标签——注入 generator 时改成作者读得懂的人话。"""


def _format_dimension_comments(comments: dict[str, str]) -> str:
    """按固定 rubric 顺序把 5 维评语拼成 bullet 列表。

    维度顺序对齐 ``_REVIEW_RUBRIC_DIMENSIONS``——structural_judgment 在前。
    某维评语缺失 / 空串时整行跳过；全空时返回兜底句"（无 5 维评语）"
    让注入段不出现孤零零标题。
    """
    lines: list[str] = []
    for key in _REVIEW_RUBRIC_DIMENSIONS:
        raw = comments.get(key)
        comment = str(raw).strip() if raw is not None else ""
        if not comment:
            continue
        label = _REVIEW_DIMENSION_LABELS.get(key, key)
        lines.append(f"- {label}：{comment}")
    if not lines:
        return "（无 5 维评语）"
    return "\n".join(lines)


def _format_top_issues(issues: list[str]) -> str:
    """把 top_issues 拼成 bullet 列表；空列表返回"（无）"。"""
    if not issues:
        return "（无）"
    return "\n".join(f"- {issue}" for issue in issues if str(issue).strip())


def _build_review_addendum(prev: PreviousReviewHint) -> str:
    """把上次 reviewer 批评摘要拼成注入 generator 的 system prompt 追加段。

    位置约定：拼到主 system prompt 末尾，让 generator 看到"上一次答这道
    题哪几维没答好"。文案有意写成人话——动词在前、具体维度说出来。
    """
    dim_block = _format_dimension_comments(prev.dimension_comments)
    issues_block = _format_top_issues(list(prev.top_issues))
    return (
        "---\n"
        f"上一次回答这道题，reviewer 评分 {prev.total_score}/25，"
        "并指出以下问题：\n\n"
        "5 维度评语：\n"
        f"{dim_block}\n\n"
        "主要问题：\n"
        f"{issues_block}\n\n"
        "这次重答请针对这些具体问题修正——"
        "不要重复同样的失误。"
    )


def _resolve_extra_system_prompt(request: AgentAskRequest) -> str | None:
    """从 request 抽 ``previous_review`` 转成 generator 的 system prompt 追加段。

    任何异常（字段缺失 / 类型错位 / 拼接失败）都被吞掉返 ``None``——
    主 ask 流程不被阻断，只是失去这次重答带批评的效果。
    """
    prev = request.previous_review
    if prev is None:
        return None
    try:
        return _build_review_addendum(prev)
    except Exception as exc:  # noqa: BLE001 — 注入失败不阻断 ask
        logger.warning(
            "review hint addendum build failed: %s: %s",
            type(exc).__name__,
            exc,
        )
        return None

_SUGGEST_REDO_THRESHOLD: int = 18
"""``overall_score < 18`` 时建议作家带更厚证据重答。

理由：5 维 × 5 分 = 25 分制；阈值 18 等于"5 维平均 3.6/5 以下"——
rubric 把 3 分定义成"判断模糊 / 证据不强 / 语气保留 / 方向不具体"，
平均刚过 3 算可用，跌破 3.6 说明这份答复对作家"不够顶用"，
让前端弹"要不要带更厚证据重答"按钮。
"""


def _extract_book_meta(assembler: Any) -> tuple[str, str]:
    """从 assembler 抽出 ``(book_title, language)``，缺失时给出兜底默认。

    ``R0BookAssembler`` 没暴露公开属性；这里走 ``getattr`` 拿 ``_book_text``
    再读 ``title`` / ``language``，让测试替身可以自己塞 ``book_text``
    属性而无需继承 R0BookAssembler。
    """
    book_text = getattr(assembler, "_book_text", None) or getattr(
        assembler, "book_text", None
    )
    title = getattr(book_text, "title", None) or "unknown"
    language = getattr(book_text, "language", None) or "zh"
    return str(title), str(language)


def _try_review_or_none(
    *,
    client: Any,
    model: str,
    question: str,
    answer: str,
    citations: list[dict],
    book_title: str,
    language: str,
) -> Review | None:
    """跑一次 reviewer，把原始 dict 映射成 Pydantic ``Review``；失败返 None。

    任何异常（``ProviderError`` / ``LLMFormatError`` / 字段缺失等）都被
    吞掉返 ``None``——主 ask 流程不被阻断，只是失去 review 卡片。
    """
    try:
        raw = review_answer(
            client=client,
            model=model,
            question=question,
            answer=answer,
            citations=citations,
            book_title=book_title,
            language=language,
        )
    except Exception as exc:  # noqa: BLE001 — reviewer 不阻断主流程
        logger.warning(
            "reviewer call failed for question=%r: %s: %s",
            question[:80],
            type(exc).__name__,
            exc,
        )
        return None

    try:
        return _review_from_raw_dict(raw)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        logger.warning("reviewer raw dict shape unexpected: %s", exc)
        return None


def _review_from_raw_dict(raw: dict[str, Any]) -> Review:
    """把 ``review_answer`` 的原始 dict 映射成 ``Review``。

    rubric_v1 字段：``scores`` / ``per_dimension_comment`` / ``overall``
    / ``top_issues`` / ``single_most_valuable_improvement``。``review_answer``
    已校验五个 ``scores`` 维度齐全。
    """
    if not isinstance(raw, dict):
        raise TypeError("reviewer raw output is not a dict")
    scores = raw.get("scores")
    if not isinstance(scores, dict):
        raise KeyError("scores")
    comments = raw.get("per_dimension_comment") or {}
    if not isinstance(comments, dict):
        comments = {}

    dimensions: dict[str, ReviewDimensionScore] = {}
    overall_score = 0
    for dim in _REVIEW_RUBRIC_DIMENSIONS:
        score_val = scores.get(dim, 0)
        try:
            score_int = int(score_val)
        except (TypeError, ValueError):
            score_int = 0
        score_int = max(0, min(5, score_int))
        overall_score += score_int
        dimensions[dim] = ReviewDimensionScore(
            score=score_int,
            comment=str(comments.get(dim) or ""),
        )

    top_issues_raw = raw.get("top_issues") or []
    top_issues = [str(item) for item in top_issues_raw if item]

    return Review(
        overall_score=overall_score,
        dimensions=dimensions,
        overall_comment=str(raw.get("overall") or ""),
        top_issues=top_issues,
        suggest_redo=overall_score < _SUGGEST_REDO_THRESHOLD,
    )


def _resolve_protocol_version(trace: Any) -> str:
    """从 LoopTrace 抽 ``protocol_version``；缺失时回退 ``"r1"`` 保向后兼容。

    ADR-007 D-5：LoopTrace 已含 ``protocol_version: Literal["r1", "r2"]``
    字段（默认 ``r1``）。本 helper 把字段值直接透出到 API 响应顶级，方便
    FE / batch 归档脚本 / case-study 引文脚本按代际分支处理，免去再去 trace
    dict 深处摸字段。
    """
    val = getattr(trace, "protocol_version", None)
    if isinstance(val, str) and val in {"r1", "r2"}:
        return val
    return "r1"


# ---------------------------------------------------------------------------
# 多轮对话（ADR-009 Phase 1a）
# ---------------------------------------------------------------------------

_RECAP_MAX_CITATIONS: int = 6
"""前情提要里最多带几条引用——上轮 citations 一般 3-6 条，封顶防膨胀。"""

_RECAP_SNIPPET_MAX_CHARS: int = 200
"""单条引用片段截断长度——前情提要进 system 可变段，控住体积。"""


@dataclass
class _ConversationContext:
    """``_resolve_conversation`` 的返回——一轮请求定位到的对话上下文。

    Attributes:
        conversation_id: 本轮所属对话 id（新对话则是服务端刚生成的）。
        turn_index: 本轮是第几问（从 1 起）。
        recap: 上一轮答案 + 引用拼成的前情提要，注入 system 可变段；
            新对话 / 接不上上文时为 None。
        history: 全部历史轮次（按 turn_index 升序），喂给指代消解改写；
            新对话 / 接不上时为空列表。
    """

    conversation_id: str
    turn_index: int
    recap: str | None
    history: list[dict]


def _resolve_conversation(
    request: AgentAskRequest,
    conv_store: JSONFileConversationStore,
) -> _ConversationContext:
    """定位本轮所属的对话。

    - ``conversation_id=None``（开新对话）：新建一场对话，turn_index=1，
      没有上一轮所以 recap 为 None、history 为空。
    - 带了 conversation_id（追问）：读历史，turn_index = 已有轮数 + 1，
      把**上一轮**的答案和引用拼成前情提要 recap，并带回全部历史轮次供
      指代消解改写参照（ADR-009 Phase 1b）。
    - 续不上的 id（找不到 / 文件坏）当作开新对话兜底——不阻断 ask，只是
      这次接不上上文（多轮场景下劣化为单轮，记日志）。

    recap 只用来注入 system 可变段，绝不进固定前缀（缓存命中靠固定前缀
    逐 token 相同，recap 每轮都变）。
    """
    session_id = request.book_session_id
    if request.conversation_id is None:
        conversation_id = conv_store.create(session_id)
        return _ConversationContext(conversation_id, 1, None, [])

    conversation_id = request.conversation_id
    try:
        turns = conv_store.get_turns(session_id, conversation_id)
    except (ConversationNotFound, ConversationStoreError) as exc:
        logger.warning(
            "conversation %s 续不上（%s）；当作新对话兜底，本轮接不上上文",
            conversation_id,
            exc,
        )
        new_id = conv_store.create(session_id)
        return _ConversationContext(new_id, 1, None, [])

    turn_index = len(turns) + 1
    last_turn = turns[-1] if turns else None
    recap = _build_conversation_recap(last_turn)
    return _ConversationContext(conversation_id, turn_index, recap, turns)


def _resolve_effective_question(
    request: AgentAskRequest,
    conv: _ConversationContext,
    client: Any,
    model: str,
) -> tuple[str, str | None]:
    """追问指代消解：把残句改写成独立可查的完整问题（ADR-009 Phase 1b，D-2）。

    返回 ``(effective_question, rewritten_question)``：

    - ``effective_question``：往下喂给路由 / agent loop / fast_path 的问题。
      改写成功用改写版，否则用原题。
    - ``rewritten_question``：改写结果（None = 没改写 / 改写失败用原题），
      原样存进 conversation_store 的 ``rewritten_question`` 字段。

    没历史（新对话第一问 / 接不上上文）直接返回原题、rewritten=None——
    行为与 Phase 1a 完全一致（零回归）。改写挂了 ``rewrite_followup`` 内部
    已兜底返 None，本函数照样回退原题，不阻断 ask。
    """
    if not conv.history:
        return request.question, None
    rewritten = rewrite_followup(
        request.question,
        client,
        model=model,
        conversation_history=conv.history,
    )
    if rewritten is None:
        return request.question, None
    logger.info(
        "conversation %s turn %d 指代消解：%r → %r",
        conv.conversation_id,
        conv.turn_index,
        request.question[:60],
        rewritten[:60],
    )
    return rewritten, rewritten


def _build_conversation_recap(last_turn: dict | None) -> str | None:
    """把上一轮的答案 + 引用拼成「前情提要」注入段（ADR-009 的 B 能力）。

    上一轮为空（刚 create 还没答过）返回 None。任何拼接异常都吞掉返
    None——接不上上文也不该让这一轮崩。
    """
    if not last_turn:
        return None
    try:
        prev_q = str(last_turn.get("question") or "").strip()
        prev_a = str(last_turn.get("answer") or "").strip()
        if not prev_a:
            return None
        citations = last_turn.get("citations") or []
        cite_block = _format_recap_citations(citations)
        lines = [
            "---",
            "【前情提要】这是一场连续追问，下面是上一轮的问答，"
            "用户这一轮多半是接着它往下问——理解本轮问题时把它当上文：",
            "",
            f"上一问：{prev_q}" if prev_q else "上一问：（略）",
            "",
            "上一轮的回答：",
            prev_a,
        ]
        if cite_block:
            lines += ["", "上一轮引用的原文：", cite_block]
        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001 — 接不上上文不阻断 ask
        logger.warning("前情提要拼接失败：%s: %s", type(exc).__name__, exc)
        return None


def _format_recap_citations(citations: list) -> str:
    """把上一轮 citations 拼成精简列表——封顶条数 + 截断片段防膨胀。"""
    lines: list[str] = []
    for cite in citations[:_RECAP_MAX_CITATIONS]:
        if not isinstance(cite, dict):
            continue
        chapter = cite.get("chapter")
        snippet = str(cite.get("snippet") or "").strip()
        if len(snippet) > _RECAP_SNIPPET_MAX_CHARS:
            snippet = snippet[:_RECAP_SNIPPET_MAX_CHARS] + "…"
        prefix = f"- 第{chapter}章：" if chapter is not None else "- "
        lines.append(f"{prefix}{snippet}")
    return "\n".join(lines)


def _persist_turn(
    conv_store: JSONFileConversationStore,
    session_id: str,
    conversation_id: str,
    *,
    question: str,
    answer: str,
    citations: list[dict],
    rewritten_question: str | None = None,
) -> None:
    """把答完的这一轮写进对话存储；写失败只记日志，不影响已经答好的响应。

    ``question`` 始终存用户**原题**，``rewritten_question`` 存指代消解改写后
    的独立化问题（ADR-009 Phase 1b）；没改写时传 None，落盘存空串（store
    的默认值）——下次拼前情提要用原题，改写过程对用户不可见但留痕可观测。
    """
    try:
        conv_store.append_turn(
            session_id,
            conversation_id,
            question=question,
            answer=answer,
            citations=citations,
            rewritten_question=rewritten_question or "",
        )
    except ConversationStoreError as exc:
        logger.warning(
            "对话 %s 追加轮次失败（%s）；本轮答复已返回，只是没存进对话",
            conversation_id,
            exc,
        )


def _serialize_trace(trace: Any) -> dict:
    """把 LoopTrace 转为 plain dict。

    Pydantic v2 模型用 ``model_dump``；若用户替换为 dataclass（未来 r2）
    则回退到 ``asdict``；兜底做 ``dict(trace)`` 或 ``{}``。
    """
    if hasattr(trace, "model_dump"):
        return trace.model_dump()
    try:
        from dataclasses import asdict, is_dataclass

        if is_dataclass(trace):
            return asdict(trace)
    except Exception:  # noqa: BLE001
        pass
    if isinstance(trace, dict):
        return trace
    return {}


__all__ = ["agent_router"]
