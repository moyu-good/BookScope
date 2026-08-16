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
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response, StreamingResponse

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
from bookscope.report.builders import build_book_report, build_structure_report
from bookscope.agent.book_cross import build_book_perspective, cross_book_reason, build_cross_book_report_input, cross_book_ask
from bookscope.report.service import render_report

from bookscope.agent._internal.chapter_spine_cache import (
    get_or_build_spine,
    peek_spine_cache,
    spine_build_progress,
)
from bookscope.agent._internal.doc_spine_cache import (
    get_or_build_doc_spine,
    peek_doc_spine_cache,
)
from bookscope.agent._internal.empty_semantics import is_confirmed_empty
from bookscope.agent.annotations import generate_annotations
from bookscope.agent.argument_structure import (
    generate_argument_structure_exhaustive,
    generate_argument_tree,
)
from bookscope.agent.backends.r0_assembler import R0BookAssembler
from bookscope.agent.chapter_spine_canon import build_spine_name_map
from bookscope.agent.chapter_spine_concept import concept_evolution_from_spine
from bookscope.agent.chapter_spine_concept_graph import concept_graph_from_spine
from bookscope.agent.chapter_spine_consistency import consistency_scan_from_spine
from bookscope.agent.chapter_spine_dropped_thread import dropped_threads_from_spine
from bookscope.agent.chapter_spine_evidence import evidence_for_event, evidence_for_pair
from bookscope.agent.chapter_spine_foreshadow import foreshadow_from_spine
from bookscope.agent.chapter_spine_relationship import (
    relationship_chronicle_for_pair,
    relationship_pairs_index,
)
from bookscope.agent.chapter_spine_subplot import subplot_weave_from_spine
from bookscope.agent.chapter_spine_timeline import timeline_from_spine
from bookscope.agent.chapter_spine_views import (
    narrative_curve_from_spine,
    narrative_flow_from_spine,
    pacing_from_spine,
    relationship_graph_from_spine,
)
from bookscope.agent.character_arc import generate_character_arc_exhaustive
from bookscope.agent.character_graph import (
    extract_character_graph_exhaustive,
)
from bookscope.agent.character_stance import (
    batch_stance_positions,
    generate_character_stance,
    suggest_stance_axis,
)
from bookscope.agent.character_voice import generate_character_voice
from bookscope.agent.claim_support import check_claim_support
from bookscope.agent.cross_doc import cross_doc_relations_from_spines
from bookscope.agent.cross_doc_views import (
    attach_postures_to_edges,
    dependency_graph_from_cross_doc,
    dependency_postures_from_spines,
    level_consistency_from_spines,
    policy_evolution_from_spines,
    policy_wording_diff_from_spines,
)
from bookscope.agent.doc_spine import build_doc_head_only
from bookscope.agent.entity_recall import generate_entity_recall
from bookscope.agent.events import LoopEvent
from bookscope.agent.genre_detect import (
    genre_to_argument_axis,
    is_narrative_genre,
    is_theory_genre,
)
from bookscope.agent.long_context import run_long_context
from bookscope.agent.meeting_commitments import commitments_across_meetings
from bookscope.agent.meeting_spine import action_ledger_from_meeting
from bookscope.agent.meeting_stance import stances_from_meeting
from bookscope.agent.motif_tracking import generate_motif_tracking
from bookscope.agent.narrative_phases import generate_narrative_phases
from bookscope.agent.orchestrate import orchestrate
from bookscope.agent.question_processor import rewrite_followup
from bookscope.agent.recap import generate_recap
from bookscope.agent.redhead_close_reading import close_reading_from_spine
from bookscope.agent.redhead_format_check import format_check_from_spine
from bookscope.agent.redhead_glossary import glossary_from_spine
from bookscope.agent.redhead_hard_facts import hard_facts_from_spine
from bookscope.agent.redhead_plain import plain_language_from_spine
from bookscope.agent.redhead_relevance import relevance_from_spine
from bookscope.agent.redhead_stakes import stakes_from_doc
from bookscope.agent.redhead_timeline import (
    timeline_from_spine as redhead_timeline_from_spine,
)
from bookscope.agent.scholar_stance import scholar_stance_spectrum
from bookscope.agent.study_cards import generate_study_cards
from bookscope.agent.style_issues import generate_style_issues
from bookscope.agent.suggested_questions import generate_book_questions
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
from bookscope.api.deployment import (
    is_hosted,
    resolve_user_from_token,
    user_owns_session,
)
from bookscope.api.schemas import (
    AgentAskRequest,
    AgentAskResponse,
    BookReportRequest,
    CrossBookReportRequest,
    CrossBookAskRequest,
    CrossBookAskResponse,
    ClusterReportRequest,
    ClusterDiscoverRequest,
    AnnotationsRequest,
    AnnotationsResponse,
    ArgumentStructureRequest,
    ArgumentStructureResponse,
    ArgumentTreeClaim,
    ArgumentTreeRequest,
    ArgumentTreeResponse,
    ArgumentTreeThesis,
    BatchStancePosition,
    BatchStanceRequest,
    BatchStanceResponse,
    BookModeRequest,
    BookModeResponse,
    ChapterAskRequest,
    ChapterAskResponse,
    CharacterArcRequest,
    CharacterArcResponse,
    CharacterFlowRequest,
    CharacterFlowResponse,
    CharacterGraphRequest,
    CharacterGraphResponse,
    CharacterStanceRequest,
    CharacterStanceResponse,
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
    GenreDetectRequest,
    GenreDetectResponse,
    GraphEdge,
    MeetingActionLedgerRequest,
    MeetingActionLedgerResponse,
    MeetingCommitmentsRequest,
    MeetingCommitmentsResponse,
    MeetingStanceRequest,
    MeetingStanceResponse,
    MotifTrackingRequest,
    MotifTrackingResponse,
    NarrativeCurveRequest,
    NarrativeCurveResponse,
    NarrativePhasesRequest,
    NarrativePhasesResponse,
    OrchestrateRequest,
    PacingCurveRequest,
    PacingCurveResponse,
    PreviousReviewHint,
    PrewarmSpineBatchRequest,
    PrewarmSpineBatchResponse,
    PrewarmSpineRequest,
    PrewarmSpineResponse,
    PrewarmSpineStatusResponse,
    RecapRequest,
    RecapResponse,
    RedheadCloseReadingResponse,
    RedheadCrossDocRequest,
    RedheadDependencyGraphResponse,
    RedheadDocStructureRequest,
    RedheadDocStructureResponse,
    RedheadFormatCheckResponse,
    RedheadGlossaryResponse,
    RedheadHardFactsResponse,
    RedheadLevelConsistencyResponse,
    RedheadPlainLanguageRequest,
    RedheadPlainLanguageResponse,
    RedheadPolicyEvolutionRequest,
    RedheadPolicyEvolutionResponse,
    RedheadRelevanceRequest,
    RedheadRelevanceResponse,
    RedheadStakesRequest,
    RedheadStakesResponse,
    RedheadTimelineResponse,
    RelationshipTimelineRequest,
    RelationshipTimelineResponse,
    Review,
    ReviewDimensionScore,
    ScholarStanceAxis,
    ScholarStancePosition,
    ScholarStanceRequest,
    ScholarStanceResponse,
    SpineEvidenceRequest,
    SpineEvidenceResponse,
    StudyCardsRequest,
    StudyCardsResponse,
    StyleIssuesRequest,
    StyleIssuesResponse,
    SubplotWeaveRequest,
    SubplotWeaveResponse,
    SuggestQuestionsRequest,
    SuggestQuestionsResponse,
    SuggestStanceAxisRequest,
    SuggestStanceAxisResponse,
    TimelineRequest,
    TimelineResponse,
    WritingTechniqueRequest,
    WritingTechniqueResponse,
)
from bookscope.ingest.back_matter import exclude_back_matter

logger = logging.getLogger(__name__)


async def _verify_session_ownership(request: Request) -> None:
    """agent_router 级归属守卫(1.6.2 Phase 1c-2)。

    一处覆盖所有吃 session 的 agent 端点:hosted 下校请求 body 里的
    ``book_session_id``(单本)/ ``book_session_ids``(跨文件)归属——不是本人的
    当不存在(404),没登录 401。local 旁路,逐字节不变。

    body 读法:Starlette 把首次读到的 body 缓存进 ``request._body``,故这里
    ``await request.json()`` 之后,端点自己的 Pydantic 解析仍读得到同一份 body,
    不会"吃掉"请求体。非 JSON / 空 body(理论上 agent 端点都是 JSON)直接放行。

    守卫在端点函数(含 LLM 调用)之前跑,归属不过直接 404 / 401,绝不进 agent loop。
    """
    if not is_hosted():
        return
    user = resolve_user_from_token(request.headers.get("authorization"))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="需要登录"
        )
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 — 非 JSON / 空 body:没 session 可校,放行
        return
    if not isinstance(body, dict):
        return
    to_check: list[str] = []
    sid = body.get("book_session_id")
    if isinstance(sid, str) and sid:
        to_check.append(sid)
    sids = body.get("book_session_ids")
    if isinstance(sids, list):
        to_check.extend(s for s in sids if isinstance(s, str) and s)
    for session_id in to_check:
        if not user_owns_session(user, session_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error_type": "BookSessionNotFound",
                    "message": f"book session {session_id!r} not found.",
                    "details": {"session_id": session_id},
                },
            )


agent_router = APIRouter(
    tags=["agent"], dependencies=[Depends(_verify_session_ownership)]
)


# ── 章脉后台预建(性能 Lever B 后端,只加端点不改构建逻辑)──────────────────────
#
# 超长文第一次建章脉要整本 map-reduce(可能十几分钟)。以前是"点第一个整本书功能 →
# 干等"。这里让前端一进分析台就 POST /agent/prewarm-spine,后台线程里跑
# get_or_build_spine、立刻返回;前端轮询 /agent/prewarm-spine/status,建好后
# 叙事曲线/关系图/节奏/时间线等命中缓存秒出。
#
# genre 固定 fiction:12/13 个整本书 viz 端点都走 get_or_build_spine 的默认
# genre="fiction",预建的正好是它们共享的那条 spine 缓存键(theory 概念图是另一条
# 冷门 spine,不是"进台就点"的场景,不预建)。
_PREWARM_GENRE = "fiction"

# 进程内状态:键 = (book_session_id, model, genre),值 = {"status", "chapters", "error"}。
# 单进程内存态,重启丢无妨(丢了顶多再建一次,缓存本身在 SQLite 里也还在)。加锁保线程安全。
_PREWARM_STATE: dict[tuple[str, str, str], dict[str, Any]] = {}
_PREWARM_LOCK = threading.Lock()
# 后台建的线程池;别用会随请求结束就取消的机制(BackgroundTasks / 请求生命周期任务)。
_PREWARM_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="prewarm-spine")


def _prewarm_key(book_session_id: str, model: str) -> tuple[str, str, str]:
    """预建状态键 = (book_session_id, model, genre)。

    book_session_id 一对一定死这本书的 chunks(session 内 chunks 不变),等价于
    spine 缓存键里的 chunks 文本维;model + genre 补齐另两维。genre 固定 fiction。
    """
    return (book_session_id, model, _PREWARM_GENRE)


def _run_prewarm_build(
    *,
    key: tuple[str, str, str],
    chunks: list[dict],
    client: Any,
    model: str,
) -> None:
    """后台线程体:调 get_or_build_spine 建章脉,把结果/错误写回状态。

    构建逻辑一个字不改——就是照 viz 端点同参数(genre=fiction)调 get_or_build_spine。
    命中缓存它立刻返、miss 才真建。失败记进状态(error),绝不静默吞。
    """
    try:
        spine = get_or_build_spine(
            chunks=chunks, llm_client=client, model=model, genre=_PREWARM_GENRE
        )
        with _PREWARM_LOCK:
            _PREWARM_STATE[key] = {
                "status": "done",
                "chapters": len(spine),
                "built_chapters": len(spine),
                "total_chapters": None,
                "error": None,
            }
    except Exception as exc:  # noqa: BLE001 — 后台建失败要记进状态,不能静默吞
        logger.warning(
            "prewarm-spine: 后台建失败 key=%s: %s: %s",
            key,
            type(exc).__name__,
            exc,
        )
        with _PREWARM_LOCK:
            _PREWARM_STATE[key] = {
                "status": "error",
                "chapters": None,
                "built_chapters": None,
                "total_chapters": None,
                "error": f"{type(exc).__name__}: {exc}",
            }


def _start_prewarm_for_session(
    *,
    store: BookSessionStore,
    book_session_id: str,
    client: Any,
    model: str,
) -> str:
    """单本启动后台预建；返回 ``cached`` / ``building`` / ``started``。

    幂等:同一本书(同 model/genre)正在建 → 不重复起,返 building;已在缓存里 →
    返 cached(不用建);否则起后台线程建、返 started。抛出的异常由调用方决定
    （单本端点转 400/404；批量端点记 failed 继续下一本）。
    """
    assembler = _resolve_assembler(store, book_session_id)
    key = _prewarm_key(book_session_id, model)
    _full_text, chunks = _long_context_inputs(assembler)

    # 幂等 1:缓存全命中 → 不用建,直接返 cached(不占 building 坑、不派线程)。
    # 按章渐进:部分命中(progress.built < total)不算完成,继续只建缺章。
    # peek/progress 只**看**缓存、绝不触发构建,同 get_or_build_spine 口径。
    progress = spine_build_progress(chunks=chunks, model=model, genre=_PREWARM_GENRE)
    if progress["built"] >= progress["total"] > 0:
        cached = peek_spine_cache(chunks=chunks, model=model, genre=_PREWARM_GENRE)
        with _PREWARM_LOCK:
            _PREWARM_STATE[key] = {
                "status": "done",
                "chapters": len(cached or []),
                "built_chapters": progress["built"],
                "total_chapters": progress["total"],
                "error": None,
            }
        return "cached"

    # 幂等 2:已有一路在建 → 不重复起。加锁下"看状态 + 占坑"要原子,否则两个并发
    # POST 都看到 idle 会各起一路建同一本书(白建一次)。占 building 坑后再派线程。
    with _PREWARM_LOCK:
        cur = _PREWARM_STATE.get(key)
        if cur is not None and cur["status"] == "building":
            return "building"
        _PREWARM_STATE[key] = {
            "status": "building",
            "chapters": None,
            "built_chapters": progress["built"],
            "total_chapters": progress["total"],
            "error": None,
        }

    # 派后台线程建;别用会随请求结束就取消的机制(BackgroundTasks / 事件循环任务),
    # 十几分钟的构建要独立于本 HTTP 请求活着。立刻返 started,前端轮询 status。
    _PREWARM_EXECUTOR.submit(
        _run_prewarm_build,
        key=key,
        chunks=chunks,
        client=client,
        model=model,
    )
    return "started"


def _build_prewarm_client(
    *,
    provider: str,
    api_key: str,
    base_url: str | None,
) -> Any:
    """按 BYOK 参数建 LLM client；失败统一转 HTTP 400（和单本端点一致）。"""
    try:
        return build_llm_client_from_params(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ProviderSdkMissing",
                "message": str(exc),
                "details": {"provider": provider},
            },
        ) from exc
    except Exception as exc:  # noqa: BLE001 — 翻译成 HTTP
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ClientBuildFailed",
                "message": f"{type(exc).__name__}: {exc}",
                "details": {"provider": provider},
            },
        ) from exc


@agent_router.post("/agent/prewarm-spine", response_model=PrewarmSpineResponse)
def agent_prewarm_spine(
    request: PrewarmSpineRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> PrewarmSpineResponse:
    """后台预建整本书章脉,立刻返回(不阻塞十几分钟的构建)。

    幂等:同一本书(同 model/genre)正在建 → 不重复起,返 building;已在缓存里 →
    返 cached(不用建);否则起后台线程建、返 started。前端拿到 building/started 后
    轮询 /agent/prewarm-spine/status。
    """
    client = _build_prewarm_client(
        provider=request.provider,
        api_key=request.api_key,
        base_url=request.base_url,
    )
    model = request.model or default_model_for(request.provider)
    status = _start_prewarm_for_session(
        store=store,
        book_session_id=request.book_session_id,
        client=client,
        model=model,
    )
    return PrewarmSpineResponse(
        status=status, book_session_id=request.book_session_id
    )


@agent_router.post(
    "/agent/prewarm-spine/batch", response_model=PrewarmSpineBatchResponse
)
def agent_prewarm_spine_batch(
    request: PrewarmSpineBatchRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> PrewarmSpineBatchResponse:
    """一组书统一后台预建章脉（报告中心/书柜来源组「预建整组」）。

    建一次 client，逐本走与单本完全相同的幂等启动；单本失败不阻断整组，
    记进 ``failed`` / ``errors`` 由前端提示。立刻返回，进度继续走
    ``/agent/spine-progress``。
    """
    client = _build_prewarm_client(
        provider=request.provider,
        api_key=request.api_key,
        base_url=request.base_url,
    )
    model = request.model or default_model_for(request.provider)
    resp = PrewarmSpineBatchResponse()
    for sid in request.book_session_ids:
        try:
            status = _start_prewarm_for_session(
                store=store,
                book_session_id=sid,
                client=client,
                model=model,
            )
            getattr(resp, status).append(sid)
        except Exception as exc:  # noqa: BLE001 — 单本失败继续下一本
            resp.failed.append(sid)
            resp.errors[sid] = f"{type(exc).__name__}: {exc}"
    return resp


@agent_router.get(
    "/agent/prewarm-spine/status", response_model=PrewarmSpineStatusResponse
)
def agent_prewarm_spine_status(
    book_session_id: str,
    model: str | None = None,
    provider: str = "deepseek",
    store: BookSessionStore = Depends(get_book_session_store),
) -> PrewarmSpineStatusResponse:
    """轮询章脉后台预建进度。

    status:idle(没建过/不在建) / building(在建) / done(建好缓存就绪) /
    error(建失败,带 error)。model 不传就按 provider 推默认,和 POST 那边一致——
    否则键对不上会永远 idle。归属守卫(_verify_session_ownership)对 GET 无 body
    直接放行,查状态是读操作、无 LLM 调用,不额外鉴权。
    """
    resolved_model = model or default_model_for(provider)
    key = _prewarm_key(book_session_id, resolved_model)
    # 实时缓存进度（building 中也涨：后台按章增量，每章写缓存后这里就能读到）
    try:
        assembler = _resolve_assembler(store, book_session_id)
        _full_text, chunks = _long_context_inputs(assembler)
        progress = spine_build_progress(chunks=chunks, model=resolved_model, genre=_PREWARM_GENRE)
    except Exception:
        progress = {"built": 0, "total": 0}
    with _PREWARM_LOCK:
        cur = _PREWARM_STATE.get(key)
        if cur is None:
            return PrewarmSpineStatusResponse(
                status="idle", chapters=None,
                built_chapters=progress["built"], total_chapters=progress["total"],
                error=None,
            )
        return PrewarmSpineStatusResponse(
            status=cur["status"],
            chapters=cur.get("chapters"),
            built_chapters=progress["built"] or cur.get("built_chapters") or 0,
            total_chapters=progress["total"] or cur.get("total_chapters") or 0,
            error=cur.get("error"),
        )


@agent_router.post("/agent/ask", response_model=AgentAskResponse)
def agent_ask(
    request: AgentAskRequest,
    store: BookSessionStore = Depends(get_book_session_store),
    conv_store: JSONFileConversationStore = Depends(get_conversation_store),
) -> AgentAskResponse:
    """执行一次 agent 查询并返回带 citation 的答复。

    错误分层按 ADR-003 约定的 provider / loop 错误体系翻译。
    """
    assembler = _resolve_assembler(store, request.book_session_id)

    # 按章精读问答：指定 chapter 时只精读该章（单章直读，不依赖全书检索/章脉）
    if request.chapter is not None:
        client = _build_client_or_raise(request)
        model = request.model or default_model_for(request.provider)
        _full_text, chunks = _long_context_inputs(assembler)
        chapter_chunks = [c for c in chunks if c.get("chapter") == request.chapter]
        if not chapter_chunks:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error_type": "ChapterNotFound", "message": f"第 {request.chapter} 章不存在"},
            )
        chapter_text = "\n".join(str(c.get("text", "")) for c in chapter_chunks)
        lc_result = run_long_context(
            request.question,
            full_text=chapter_text,
            chunks=chapter_chunks,
            llm_client=client,
            model=model,
            session_id=request.book_session_id,
        )
        if lc_result is not None:
            return AgentAskResponse(
                answer=lc_result.answer,
                citations=lc_result.citations,
                trace=_serialize_trace(lc_result.trace),
                book_session_id=request.book_session_id,
                route_type="chapter",
            )

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
def agent_character_graph(
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

    # 人物图(1.x 章脉转向 ADR-010 出路 B):从共享章脉的逐章 relations 聚合成边,不再单独跑全书。
    # 边是章级锚——relation 用章脉给的交互短语、strength 用共现章数(可数事实,比 LLM 糊的亲疏分
    # 更立得住)、evidence 留空待前端点开调 /agent/spine-evidence 现取。概念图章脉没有(概念维是
    # claims 不是概念关系),仍走 extract_character_graph_exhaustive 各跑全书。
    if request.unit == "person":
        rec = _UsageRecorder(client)
        _t0 = time.monotonic()
        spine = get_or_build_spine(chunks=chunks, llm_client=rec, model=model)
        # 章脉逐章用原文当下的称呼(玄德/刘备/先主),没合并;先一次 LLM 判同人出别名表,
        # 把碎裂别名收成一个节点(刘备/刘玄德、孔明/诸葛亮)。只发人名清单走缓存、失败返空表不合并。
        name_map = build_spine_name_map(spine=spine, llm_client=rec, model=model)
        # 不设人数帽:一百多回的书几百号人有关系就画几百个(曾错砍到 40,把"太少"造回来了)。
        # relationship_graph_from_spine 已只画有关系的人(去孤立点);密不密是前端缩放的事。
        g = relationship_graph_from_spine(spine, name_map=name_map)

        def _polarity_of(edge: dict[str, Any]) -> str | None:
            # v2 章脉:边带综合 valence → 映射 友/敌/中(前端 edgePolarity 优先用它、不再正则猜)。
            # v1 旧缓存没 valence → None,前端回落 relationKind 正则(保守)。
            v = edge.get("valence")
            if not isinstance(v, (int, float)):
                return None
            return "友" if v > 1 else "敌" if v < -1 else "中"

        edges = [
            GraphEdge(
                source=e["source"],
                target=e["target"],
                # 关系标签:v2 用抽出的关系类型(君臣/敌对…),没有就退回逐章交互短语
                relation=e.get("rel_type") or "、".join(e.get("notes", [])[:2]) or "同场",
                strength=max(1, min(5, int(e.get("weight", 1)))),
                evidence="",
                verified=False,
                chapter=(e["chapters"][0] if e.get("chapters") else 0),
                match_score=0.0,
                polarity=_polarity_of(e),
            )
            for e in g["edges"]
        ]
        trace = _run_trace(rec, full_text, _t0)
        trace["total_edges"] = len(edges)
        return CharacterGraphResponse(
            nodes=[n["name"] for n in g["nodes"]],
            edges=edges,
            book_session_id=request.book_session_id,
            trace=trace,
        )

    # 概念图:章脉概念维(claims)派生,一次全局推理出跨章概念关系(逐段抽看不见跨段勾连)。
    # claims 只在 genre="theory" 章脉里有 → 这条 theory-spine 和人物图等默认 fiction-spine 分裂
    # 缓存(同书两条),是已知取舍:理论书概念图天然要 theory 维、小说功能在理论书上本就不用。
    rec = _UsageRecorder(client)
    _t0 = time.monotonic()
    spine = get_or_build_spine(chunks=chunks, llm_client=rec, model=model, genre="theory")
    g = concept_graph_from_spine(spine=spine, llm_client=rec, model=model, chunks=chunks)
    if g is not None:
        trace = _run_trace(rec, full_text, _t0)
        trace["total_edges"] = len(g["edges"])
        return CharacterGraphResponse(
            nodes=g["nodes"],
            edges=[GraphEdge(**e) for e in g["edges"]],
            book_session_id=request.book_session_id,
            trace=trace,
        )

    # 降级:章脉没 claims(不是理论书 / theory 维没抽出)→ 回老的逐段抽全书。
    result = extract_character_graph_exhaustive(
        chunks=chunks,
        llm_client=client,
        model=model,
        known_characters=[],
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
def agent_character_flow(
    request: CharacterFlowRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> CharacterFlowResponse:
    """抽一本书的人物叙事流（逐章同场结构，WP-character-narrative-flow，probe GO）。

    1.x 章脉转向(ADR-010 出路 B)：从共享章脉派生(``narrative_flow_from_spine``)——逐章的
    present + 同场对(relations)章脉直接有,不再单独跑全书。同场对是**章级锚**:不带 upfront 逐字
    证据,前端点开某条时调 ``/agent/spine-evidence`` 现取那一句(贴 NORTH_STAR 查询时证据现场取)。
    章脉命中缓存秒出。
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
    spine = get_or_build_spine(chunks=chunks, llm_client=rec, model=model)
    # 同人物图:章脉逐章称呼不一,先一次 LLM 判同人合别名(玄德/刘备),再派生叙事流。
    name_map = build_spine_name_map(spine=spine, llm_client=rec, model=model)
    chapters = narrative_flow_from_spine(spine, name_map=name_map)
    return CharacterFlowResponse(
        chapters=chapters or [],
        scanned=bool(spine),
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, full_text, _t0),
    )


@agent_router.post("/agent/subplot-weave", response_model=SubplotWeaveResponse)
def agent_subplot_weave(
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
    # 支线交汇天生跨段——从章脉全书梗概一次全局找(map-reduce 逐段看不见远段交汇)。
    spine = get_or_build_spine(chunks=chunks, llm_client=rec, model=model)
    weave = subplot_weave_from_spine(spine=spine, llm_client=rec, model=model, chunks=chunks)
    return SubplotWeaveResponse(
        subplots=(weave or {}).get("subplots", []),
        intersections=(weave or {}).get("intersections", []),
        scanned=weave is not None,
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, full_text, _t0),
    )


@agent_router.post("/agent/check-citations", response_model=CheckCitationsResponse)
def agent_check_citations(
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
def agent_suggest_questions(
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
def agent_pacing_curve(
    request: PacingCurveRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> PacingCurveResponse:
    """据整本书出逐章节奏张力曲线（节奏可视化，exp-012 GO）。

    1.x 章脉转向(ADR-010):从共享章脉派生(``pacing_from_spine``),不再单独跑全书——所以撤了
    单次摘要时代的 ``_book_fits_long_context`` 大书返空守卫,几百万字书也能出。章脉命中缓存秒出。
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
    spine = get_or_build_spine(chunks=chunks, llm_client=rec, model=model)
    points = pacing_from_spine(spine, chunks=chunks)
    return PacingCurveResponse(
        points=points or [],
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, full_text, _t0),
    )


@agent_router.post("/agent/spine-evidence", response_model=SpineEvidenceResponse)
def agent_spine_evidence(
    request: SpineEvidenceRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> SpineEvidenceResponse:
    """章脉章级锚视图"点开现取"那一句（ADR-010 出路 B）。纯检索、不调 LLM。

    关系图边 / 时间线事件只钉到章号,用户点开时调本端点从那一章原文现找支撑句。找不到返
    ``found=False`` + 空串（evidence-first：没原文不编）。章号不存在也返空、不报错。
    """
    assembler = _resolve_assembler(store, request.book_session_id)
    records = assembler._compute_chapter_records()  # noqa: SLF001 — 同既有取数惯例
    chapter_text = next(
        (r.full_text for r in records if r.chapter == request.chapter), ""
    )
    if not chapter_text:
        return SpineEvidenceResponse(chapter=request.chapter, evidence="", found=False)
    if request.kind == "pair":
        ev = evidence_for_pair(chapter_text, request.a or "", request.b or "")
    else:
        ev = evidence_for_event(chapter_text, request.event or "")
    return SpineEvidenceResponse(chapter=request.chapter, evidence=ev, found=bool(ev))


@agent_router.post("/agent/narrative-curve", response_model=NarrativeCurveResponse)
def agent_narrative_curve(
    request: NarrativeCurveRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> NarrativeCurveResponse:
    """据整本书的章脉派生叙事曲线:逐章事件密度 + 转折(伏笔收束)。

    1.5.3 重做(并掉重复的"节奏"张力图):纵轴不再是 LLM 眼估的张力标量,换成**能数、能锚原文**
    的信号——每章高度 = 事件数 + 伏笔收束数;伏笔在哪章收掉 = 结构转折(朱砂点)。从共享章脉
    派生、命中缓存秒出;每条事件/收束回该章原文核验。张力/情感/POV 等只进选中章明细、标"模型
    判读",不当纵轴(躲开"单标量眼估张力不可信"的病一)。
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
    # 1.5.3 章脉派生:每章事件密度(events 数 + 伏笔收束数)当纵轴,转折=伏笔收束;
    # 张力/情感/POV 降到明细标"模型判读"。命中缓存秒出。
    spine = get_or_build_spine(chunks=chunks, llm_client=rec, model=model)
    chapters = narrative_curve_from_spine(spine, chunks=chunks)
    return NarrativeCurveResponse(
        chapters=chapters or [],
        scanned=bool(spine),
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, full_text, _t0),
    )


@agent_router.post("/agent/foreshadow-arcs", response_model=ForeshadowArcsResponse)
def agent_foreshadow_arcs(
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
    # 伏笔天生跨章（早埋晚收）——从章脉全书「埋/收」清单一次全局配对，不再 map-reduce
    # 逐段盲（逐段看不见别段→只能凑同章 span-0 假伏笔）。spine 多半已为别的功能建过、L2 命中。
    spine = get_or_build_spine(chunks=chunks, llm_client=rec, model=model)
    arcs = foreshadow_from_spine(spine=spine, llm_client=rec, model=model, chunks=chunks)
    # 空值三态(task #29 根一):扫过全书(arcs 是列表)且没抽出伏笔 = 确证全书没埋伏笔,
    # 区别于扫失败(arcs=None)。注:单条弧的 status=dangling 是另一层确证(这条伏笔确证未回收)。
    return ForeshadowArcsResponse(
        arcs=arcs or [],
        scanned=arcs is not None,
        confirmed_none=is_confirmed_empty(arcs),
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, full_text, _t0),
    )


@agent_router.post("/agent/character-arc", response_model=CharacterArcResponse)
def agent_character_arc(
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


@agent_router.post("/agent/narrative-phases", response_model=NarrativePhasesResponse)
def agent_narrative_phases(
    request: NarrativePhasesRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> NarrativePhasesResponse:
    """情节脉络·阶段划分:章脉派生,判书型、叙事型才切阶段、锚原文(WP-narrative-phases)。"""
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
            detail={"error_type": "ProviderSdkMissing", "message": str(exc),
                    "details": {"provider": request.provider}},
        ) from exc
    except Exception as exc:  # noqa: BLE001 — 翻译成 HTTP
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_type": "ClientBuildFailed", "message": f"{type(exc).__name__}: {exc}",
                    "details": {"provider": request.provider}},
        ) from exc

    model = request.model or default_model_for(request.provider)
    full_text, chunks = _long_context_inputs(assembler)
    rec = _UsageRecorder(client)
    _t0 = time.monotonic()
    spine = get_or_build_spine(chunks=chunks, llm_client=rec, model=model)
    result = generate_narrative_phases(spine=spine, chunks=chunks, llm_client=rec, model=model)
    return NarrativePhasesResponse(
        book_type=(result or {}).get("book_type", ""),
        phases=(result or {}).get("phases", []),
        scanned=result is not None,
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, full_text, _t0),
    )


@agent_router.post("/agent/character-voice", response_model=CharacterVoiceResponse)
def agent_character_voice(
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
    # 大书不再返空:声口改跨章采样(下面 spine + present 定位角色出场章、只喂那些章原文),
    # 大书也跑得起,不必再被 _book_fits_long_context 闸挡在门外。

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
    # 声口要对白文本、章脉派生不了——改跨章采样:章脉 present 定位角色出场章,只喂那几章原文
    # (大书也不截断);name_map 合并别名(玄德/刘备)定位更准。spine 多半已为别功能缓存。
    spine = get_or_build_spine(chunks=chunks, llm_client=rec, model=model)
    name_map = build_spine_name_map(spine=spine, llm_client=rec, model=model)
    result = generate_character_voice(
        character=request.character,
        full_text=full_text,
        chunks=chunks,
        llm_client=rec,
        model=model,
        spine=spine,
        name_map=name_map,
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


@agent_router.post("/agent/character-stance", response_model=CharacterStanceResponse)
def agent_character_stance(
    request: CharacterStanceRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> CharacterStanceResponse:
    """给一个角色在可配立场轴上正反取证 + 综合倾向 + 争议度（Toulmin，probe exp024 GO）。

    整本进 context，pro/con 分列（各挂原文过核验）、net 综合倾向、dispute 争议度。争议判断
    不压成单分：两方并陈让读者自己看（evidence-first 机制层）。轴（pos/neg）由调用方按书给。
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
    result = generate_character_stance(
        character=request.character,
        full_text=full_text,
        chunks=chunks,
        llm_client=rec,
        model=model,
        pos_label=request.pos_label,
        neg_label=request.neg_label,
        session_id=request.book_session_id,
    )
    return CharacterStanceResponse(
        character=request.character,
        pos=(result or {}).get("pos", request.pos_label),
        neg=(result or {}).get("neg", request.neg_label),
        pro=(result or {}).get("pro", []),
        con=(result or {}).get("con", []),
        net=(result or {}).get("net", 0),
        dispute=(result or {}).get("dispute", 0),
        dispute_reason=(result or {}).get("dispute_reason", ""),
        scanned=result is not None,
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, full_text, _t0),
    )


@agent_router.post(
    "/agent/suggest-stance-axis", response_model=SuggestStanceAxisResponse
)
def agent_suggest_stance_axis(
    request: SuggestStanceAxisRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> SuggestStanceAxisResponse:
    """据书的节选建议一对立场轴标签（人物志立场象限的默认轴，用户仍可改）。

    轴不写死三国的「尊汉扶主 / 篡逆自立」——拿书名 + 正文前 ~15000 字喂进去，让 LLM 判这本书
    围绕的核心立场 / 阵营对立。判不出（工具书 / 诗集 / 纯理论）返空、不硬造（evidence-first）。
    只取节选不整本——建议轴不需要全书，省 token。
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
    book_title, _ = _extract_book_meta(assembler)
    raw_text = assembler._book_text.raw_text  # noqa: SLF001 — 同 book_cache 既有取法
    sample = raw_text[:15000]
    if book_title and book_title != "unknown":
        sample = f"《{book_title}》\n\n{sample}"
    result = suggest_stance_axis(sample_text=sample, llm_client=client, model=model)
    return SuggestStanceAxisResponse(
        pos=(result or {}).get("pos", ""),
        neg=(result or {}).get("neg", ""),
        scanned=result is not None,
        book_session_id=request.book_session_id,
    )


@agent_router.post("/agent/batch-stance", response_model=BatchStanceResponse)
def agent_batch_stance(
    request: BatchStanceRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> BatchStanceResponse:
    """一次把多个角色同时定位到可配立场轴上（立场格局主视图，probe exp032 GO）。

    批量粗定位：整本进 context，一次调用给每人 net + dispute + 一句依据。net 方向可信、
    dispute 是浅判——真争议由前端点开某人跑 character-stance 的单人 Toulmin 显。轴按书给。
    判不出 / 失败返 scanned=False，前端不画象限、退回按需点人。
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
    full_text, _chunks = _long_context_inputs(assembler)
    positions = batch_stance_positions(
        characters=request.characters,
        pos_label=request.pos_label,
        neg_label=request.neg_label,
        full_text=full_text,
        llm_client=client,
        model=model,
    )
    return BatchStanceResponse(
        positions=[BatchStancePosition(**p) for p in (positions or [])],
        scanned=positions is not None,
        book_session_id=request.book_session_id,
    )


@agent_router.post("/agent/scholar-stance", response_model=ScholarStanceResponse)
def agent_scholar_stance(
    request: ScholarStanceRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> ScholarStanceResponse:
    """理论书镜头：本书跟哪些学者对话、各自站在核心争论的哪一极（probe exp033 GO）。

    一次 book-first 长上下文：模型据本书原文自己定核心争论轴 + 抽对话学者，有立场的摆到轴上、
    逐个挂原文原句过片段核验（绝不整条子串比对，治模型用"……"拼不相邻句的假挂）。抽不出轴 /
    有立场学者 < 2 → scanned=False，前端不画谱（evidence-first：判不出不硬造）。
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
    full_text, _chunks = _long_context_inputs(assembler)
    rec = _UsageRecorder(client)
    _t0 = time.monotonic()
    result = scholar_stance_spectrum(
        full_text=full_text,
        llm_client=rec,
        model=model,
        book_session_id=request.book_session_id,
    )
    axis = result.get("axis")
    return ScholarStanceResponse(
        axis=ScholarStanceAxis(**axis) if axis else None,
        scholars=[ScholarStancePosition(**s) for s in result.get("scholars", [])],
        scanned=bool(result.get("scanned")),
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, full_text, _t0),
    )


@agent_router.post(
    "/agent/relationship-timeline", response_model=RelationshipTimelineResponse
)
def agent_relationship_timeline(
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
    # 1.5.1 关系编年(章脉派生):关系图=全员索引,这里=任一对按需下钻。给了 pair 只算那对(L2 缓存),
    # 没给返便宜的全员对清单(总览,不调 LLM)。别名表跟关系图共享同一张(同输入命中同缓存),两边
    # "谁是谁"对齐——否则"关系图里点的刘备"和"这里查的刘备"对不上、就找不到人。
    spine = get_or_build_spine(chunks=chunks, llm_client=rec, model=model)
    name_map = build_spine_name_map(spine=spine, llm_client=rec, model=model)
    if request.pair_a and request.pair_b:
        rel = relationship_chronicle_for_pair(
            a=request.pair_a,
            b=request.pair_b,
            spine=spine,
            chunks=chunks,
            llm_client=rec,
            model=model,
            name_map=name_map,
        )
        relations: list[dict] = [rel] if rel else []
        pairs: list[dict] = []
        scanned = rel is not None
    else:
        relations = []
        pairs = relationship_pairs_index(spine, name_map)
        scanned = bool(pairs)
    return RelationshipTimelineResponse(
        relations=relations,
        pairs=pairs,
        scanned=scanned,
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, full_text, _t0),
    )


@agent_router.post("/agent/consistency-scan", response_model=ConsistencyScanResponse)
def agent_consistency_scan(
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
    # 矛盾要跨章对比,整本单次大书截断——章脉(紧凑全书结构)一次全局找,扫得到全书。
    spine = get_or_build_spine(chunks=chunks, llm_client=rec, model=model)
    result = consistency_scan_from_spine(spine=spine, llm_client=rec, model=model, chunks=chunks)
    # 空值三态(task #29 根一):扫过全书(result 是列表)且没矛盾 = 确证无矛盾(好消息),
    # 区别于扫失败(result=None → confirmed_clean=False,前端显待核)。
    return ConsistencyScanResponse(
        contradictions=result or [],
        scanned=result is not None,
        confirmed_clean=is_confirmed_empty(result),
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, full_text, _t0),
    )


@agent_router.post("/agent/timeline", response_model=TimelineResponse)
def agent_timeline(
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
    # 时间线命根子=倒叙还原真实故事时序。map-reduce 逐段抽 + 按叙述章号排做不到——章脉
    # 全书事件流一次全局推理判故事时序(timeline_from_spine 按 story_order 排,非章号)。
    spine = get_or_build_spine(chunks=chunks, llm_client=rec, model=model)
    events = timeline_from_spine(spine=spine, llm_client=rec, model=model)
    return TimelineResponse(
        events=events or [],
        scanned=events is not None,
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, full_text, _t0),
    )


@agent_router.post("/agent/entity-recall", response_model=EntityRecallResponse)
def agent_entity_recall(
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
    # 空值三态(task #29 根一):扫过全书(appearances 是列表)且没找到 = 确证全书未出现该实体
    # (这是答案,不是搜漏),区别于扫失败(appearances=None → confirmed_absent=False)。
    return EntityRecallResponse(
        entity=request.entity,
        appearances=appearances or [],
        scanned=appearances is not None,
        confirmed_absent=is_confirmed_empty(appearances),
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, full_text, _t0),
    )


@agent_router.post("/agent/argument-structure", response_model=ArgumentStructureResponse)
def agent_argument_structure(
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
    # #10 题材门控：先检测题材（懒检测 + 缓存到 session），再压到 theory/fiction 轴。
    # 论点结构只对理论/论文跑，小说/历史等叙事题材在 exhaustive 内优雅退场（返 []）。
    genre = store.ensure_genre(request.book_session_id, llm_client=rec, model=model)
    claims = generate_argument_structure_exhaustive(
        chunks=chunks,
        llm_client=rec,
        model=model,
        genre=genre_to_argument_axis(genre or None),
    )
    return ArgumentStructureResponse(
        claims=claims or [],
        scanned=claims is not None,
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, full_text, _t0),
    )


@agent_router.post("/agent/argument-tree", response_model=ArgumentTreeResponse)
def agent_argument_tree(
    request: ArgumentTreeRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> ArgumentTreeResponse:
    """论点结构骨架树：中心论点 + 论点（逻辑角色 + 支撑关系），每条锚原文（probe exp034 GO）。

    一次 book-first 长上下文让模型据原文定中心论点 + 抽论点、连 supports 关系；引文过
    verify_citations 拿章号、_quote_grounded 片段兜底。非论说题材 / 抽不出中心论点 /
    有效论点 < 2 → scanned=False，前端不画树（evidence-first：判不出不硬造）。
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
    # 门控改按 book mode(叙事 / 论述,exp035):论述型就跑论点结构——哪怕题材是"历史",论述型历史
    # (如经济制裁)一样有论证骨架。避免"nav 按 mode 显了论点结构、后端却按 genre 轴判历史=叙事直接
    # 退"的自相矛盾。mode 判不出(空)退回按 genre 的老轴(向后兼容)。
    genre = store.ensure_genre(request.book_session_id, llm_client=rec, model=model)
    mode = store.ensure_book_mode(request.book_session_id, llm_client=rec, model=model)
    axis = (
        "theory"
        if mode == "discursive"
        else "fiction"
        if mode == "narrative"
        else genre_to_argument_axis(genre or None)
    )
    result = generate_argument_tree(
        full_text=full_text,
        chunks=chunks,
        llm_client=rec,
        model=model,
        session_id=request.book_session_id,
        genre=axis,
    )
    thesis = result.get("thesis")
    return ArgumentTreeResponse(
        thesis=ArgumentTreeThesis(**thesis) if thesis else None,
        claims=[ArgumentTreeClaim(**c) for c in result.get("claims", [])],
        scanned=bool(result.get("scanned")),
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, full_text, _t0),
    )


@agent_router.post("/agent/detect-genre", response_model=GenreDetectResponse)
def agent_detect_genre(
    request: GenreDetectRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> GenreDetectResponse:
    """选书时主动测一次题材（懒检测 + 缓存），让前端 nav 按题材显隐。

    一次轻 LLM 调用（书名 + 目录 + 开头一段，小预算），封闭集分类，结果缓存进 session
    metadata——重复调用直接命中缓存不再花钱。测不出退空串（前端按"未分类"全显，向后兼容）。
    检测本身永不抛错（``ensure_genre`` 整体兜底）；只有 session 不存在 / client 建不出来
    才报 HTTP 错。
    """
    _resolve_assembler(store, request.book_session_id)  # 不存在 → 404

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
    genre = store.ensure_genre(
        request.book_session_id, llm_client=client, model=model
    )
    return GenreDetectResponse(
        genre=genre, book_session_id=request.book_session_id
    )


@agent_router.post("/agent/detect-mode", response_model=BookModeResponse)
def agent_detect_book_mode(
    request: BookModeRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> BookModeResponse:
    """选书时判一次叙事型 / 论述型（懒判 + 缓存），前端据此只上对应一套镜头。

    比题材细一维、按内容判（exp035 GO）——分开叙事型历史（明朝→人物镜头）和论述型历史
    （安史 / 经济制裁→思想镜头），治人物镜头与思想镜头在同一本书上重叠。清晰题材（小说 / 理论 等）
    直接映射不调 LLM，只含糊的（历史 / 传记）才真跑一次轻分类。判不出退空串（前端维持题材默认）。
    """
    _resolve_assembler(store, request.book_session_id)  # 不存在 → 404
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
    mode = store.ensure_book_mode(
        request.book_session_id, llm_client=client, model=model
    )
    return BookModeResponse(mode=mode, book_session_id=request.book_session_id)


@agent_router.post("/agent/style-issues", response_model=StyleIssuesResponse)
def agent_style_issues(
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
    # 用词重复 / 视角越界两类局部毛病:整本一次扫。
    issues = generate_style_issues(
        full_text=full_text,
        chunks=chunks,
        llm_client=rec,
        model=model,
        session_id=request.book_session_id,
    )
    # 支线失踪是跨章判断,拆出来章脉派生(算术筛候选 + 一次复核分"忘收尾"vs"正常完结"),
    # 大书不漏报。两类条目同形(type/what/chapter/snippet/verified),合并一起返。
    spine = get_or_build_spine(chunks=chunks, llm_client=rec, model=model)
    dropped = dropped_threads_from_spine(spine=spine, llm_client=rec, model=model, chunks=chunks)
    return StyleIssuesResponse(
        issues=(issues or []) + (dropped or []),
        scanned=issues is not None,
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, full_text, _t0),
    )


@agent_router.post("/agent/recap", response_model=RecapResponse)
def agent_recap(
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
def agent_chapter_ask(
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
def agent_concept_evolution(
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
    # #15 题材门控:概念演进是论说类功能(理论/论文)。叙事/小说里"概念"≈母题,该退场
    # 引导去母题追踪,别硬抽假"概念演进"。genre or None 把空串(没检测出)归一成 None
    # → 按向后兼容照旧跑。返 scanned=True + 空阶段(题材不适用 ≠ 失败)。
    genre = store.ensure_genre(request.book_session_id, llm_client=rec, model=model)
    if not is_theory_genre(genre or None):
        return ConceptEvolutionResponse(
            concept=request.concept,
            stages=[],
            scanned=True,
            book_session_id=request.book_session_id,
            trace=_run_trace(rec, full_text, _t0),
        )
    # 概念演进要按章序串全书,整本单次大书截断——章脉一次全局排阶段(共享那份 spine)。
    spine = get_or_build_spine(chunks=chunks, llm_client=rec, model=model)
    stages = concept_evolution_from_spine(
        concept=request.concept, spine=spine, llm_client=rec, model=model, chunks=chunks
    )
    return ConceptEvolutionResponse(
        concept=request.concept,
        stages=stages or [],
        scanned=stages is not None,
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, full_text, _t0),
    )


@agent_router.post("/agent/motif-tracking", response_model=MotifTrackingResponse)
def agent_motif_tracking(
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
def agent_writing_technique(
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
def agent_study_cards(
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
    # #15 题材门控:知识卡片是论说/工具书功能。叙事(小说/历史)上出"知识点卡"怪,退场。
    # genre 非空且确为叙事才退(空串=没检测出,照旧跑;理论/论文/工具书/公文都正常跑)。
    genre = store.ensure_genre(request.book_session_id, llm_client=rec, model=model)
    if genre and is_narrative_genre(genre):
        return StudyCardsResponse(
            cards=[],
            scanned=True,
            book_session_id=request.book_session_id,
            trace=_run_trace(rec, full_text, _t0),
        )
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
def agent_annotations(
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


def _exclude_back_matter_enabled() -> bool:
    """书末非正文区剔除开关（默认开）。设 ``0`` / ``off`` / ``false`` / ``no`` 关掉当逃生口。"""
    return os.environ.get("BOOKSCOPE_EXCLUDE_BACK_MATTER", "on").strip().lower() not in (
        "0",
        "off",
        "false",
        "no",
    )


def _long_context_inputs(assembler: R0BookAssembler) -> tuple[str, list[dict]]:
    """取整本文本 + 全书 chunks（给 citation 校验当证据 + 章号 ground truth）。

    chapter 填真章号（assembler 的 chunk→chapter 归一化映射，与 RAG 同口径）：
    长上下文模型自报章号会漂（exp-009/010 caveat），snippet verify 命中某 chunk
    后由 ``run_long_context`` 用这里的真章号覆盖模型自报值。映射拿不到的 chunk 退 0。

    **书末非正文区剔除**（#48）：所有整本功能都从这里拿 full_text / chunks，是唯一共享上游。
    在这里过一道 ``exclude_back_matter``——把并进最后一章的参考文献 / 注释 / 附录 / 索引 /
    后记 / 致谢从两侧剔掉，让时间线 / 伏笔 / 章脉等 map-reduce 功能不再把书末区当正文抽。
    识别保守（分章的书 + 严格标题 + 其后无章头 + 落尾部），公文 / 会议 / 单篇不受影响。
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
    if _exclude_back_matter_enabled():
        full_text, chunks = exclude_back_matter(full_text, chunks)
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
        self._lock = threading.Lock()

    def messages_create(self, **kwargs: Any) -> Any:
        resp = self._inner.messages_create(**kwargs)
        try:
            it, ot = self._inner.extract_usage_tokens(resp)
            # 穷尽化 map-reduce 下 6 个线程并发调本方法,累加得加锁——否则非原子的
            # 读-改-写会丢更新,trace 里给前端看的 token 用量少记(同 review 第 1 条)。
            with self._lock:
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


# ════════════════════════════════════════════════════════════════════════════
# 1.6 红头文件垂直(Phase 1):单文件解读 + 三个跨文件视图
# ════════════════════════════════════════════════════════════════════════════
#
# 摄入最简、复用现状(不新建 session 模型):一份公文 = 一个已有的 book session
# (用户照现有 /books/upload 各传一份)。「卷宗」= 客户端传一组 book_session_ids,
# 跨文件端点逐个 resolve assembler → 拿 chunks → 建文脉(get_or_build_doc_spine,
# 同份秒出),凑成文脉栈再跑视图。错误分层 / trace / BYOK client 构建照其它端点抄。


def _build_params_client_or_raise(request: Any) -> Any:
    """按 BYOK 参数构造 LLM client;SDK 未装 / 参数非法翻译为 HTTP 400。

    口径同各整本结构化功能端点内联的那段 try/except(ProviderSdkMissing /
    ClientBuildFailed)。``request`` 只要带 ``provider`` / ``api_key`` / ``base_url``。
    """
    try:
        return build_llm_client_from_params(
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


def _collect_doc_spines(
    store: BookSessionStore,
    session_ids: list[str],
    *,
    llm_client: Any,
    model: str,
) -> list[dict]:
    """逐个 resolve assembler → 拿 chunks → 建文脉(命中缓存秒出),凑成文脉栈。

    每个 session_id 都过 ``_resolve_assembler``(找不到照样翻 404,不静默跳过——卷宗里
    点名的文件必须都在)。同份公文 ``get_or_build_doc_spine`` 命中缓存,跨文件视图逐份建
    文脉时同份只精读一次。``llm_client`` 已被 ``_UsageRecorder`` 包过,token 用量累加进 trace。
    """
    spines: list[dict] = []
    for sid in session_ids:
        assembler = _resolve_assembler(store, sid)
        full_text, chunks = _long_context_inputs(assembler)
        spine = get_or_build_doc_spine(
            chunks=chunks, llm_client=llm_client, model=model, full_text=full_text
        )
        spines.append(spine)
    return spines


@agent_router.post(
    "/agent/redhead/doc-structure",
    response_model=RedheadDocStructureResponse,
)
def agent_redhead_doc_structure(
    request: RedheadDocStructureRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> RedheadDocStructureResponse:
    """单份公文解读:精读一份红头文件出带证据的文脉(头要素 + 逐条款)。

    一份公文 = 一个已有的 book session。从这份的 chunks 建文脉(``get_or_build_doc_spine``,
    同份秒出)。头要素抽不到的留空待核、绝不编;指令类型是带原文撑的四标签、不是打分。
    """
    assembler = _resolve_assembler(store, request.book_session_id)
    client = _build_params_client_or_raise(request)
    model = request.model or default_model_for(request.provider)
    full_text, chunks = _long_context_inputs(assembler)
    rec = _UsageRecorder(client)
    _t0 = time.monotonic()
    # 这个端点被两处共用:公文结构(骨架鸟瞰,只显头要素 + 权威/结构信号,不显条款)+ 办事清单
    # (要条款当待办)。所以用 head_only 分流,别让公文结构陪跑那两分多钟的条款 map-reduce(#43):
    #   · head_only=True(公文结构):先 peek 缓存——逐条精读/办事清单建过完整文脉就直接用(含条款);
    #     没建过就只建 head 骨架秒出,那两分钟留给用户真点逐条精读时。
    #   · head_only=False(办事清单,默认):照旧建/取完整文脉(含条款),向后兼容。
    if request.head_only:
        spine = peek_doc_spine_cache(chunks=chunks, model=model)
        if spine is None:
            spine = build_doc_head_only(
                chunks=chunks, llm_client=rec, model=model, full_text=full_text
            )
    else:
        spine = get_or_build_doc_spine(
            chunks=chunks, llm_client=rec, model=model, full_text=full_text
        )
    head = spine.get("head") or []
    clauses = spine.get("clauses") or []
    return RedheadDocStructureResponse(
        head=head,
        clauses=clauses,
        structure_read=spine.get("structure_read"),
        # 头要素永远出 8 条骨架,所以 scanned 看「有没有抽到真东西」:任一头要素有值 或 有条款。
        scanned=bool(clauses) or any(str(el.get("value", "")).strip() for el in head),
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, full_text, _t0),
    )


@agent_router.post(
    "/agent/redhead/dependency-graph",
    response_model=RedheadDependencyGraphResponse,
)
def agent_redhead_dependency_graph(
    request: RedheadCrossDocRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> RedheadDependencyGraphResponse:
    """依据链关联网:一卷宗逐份建文脉 → 一次全局推文件间关系 → 整成星图(谁连谁)。

    ``cross_doc_relations_from_spines`` 推关系(锚回真实字号,编不出来的丢),
    ``dependency_graph_from_cross_doc`` 纯聚合成 nodes/edges。不足两份相关文件 / 推不出
    任何关系 → 空态(scanned=false),不硬画。
    """
    client = _build_params_client_or_raise(request)
    model = request.model or default_model_for(request.provider)
    rec = _UsageRecorder(client)
    _t0 = time.monotonic()
    spines = _collect_doc_spines(
        store, request.book_session_ids, llm_client=rec, model=model
    )
    cross = cross_doc_relations_from_spines(
        doc_spines=spines, llm_client=rec, model=model
    )
    graph = dependency_graph_from_cross_doc(cross)
    # 博弈姿态(深6):给依据/落实边判忠实落实/层层加码/打折扣(独立 LLM pass,锚下位 vs 上位原文对照);
    # attach 纯合并贴回边上(向后兼容,匹配不上的边不挂)。
    if graph is not None:
        postures = dependency_postures_from_spines(
            cross_doc_result=cross, doc_spines=spines, llm_client=rec, model=model
        )
        graph = attach_postures_to_edges(graph, postures)
    return RedheadDependencyGraphResponse(
        nodes=(graph or {}).get("nodes", []),
        edges=(graph or {}).get("edges", []),
        scanned=graph is not None,
        trace=_run_trace(rec, "", _t0),
    )


@agent_router.post(
    "/agent/redhead/policy-evolution",
    response_model=RedheadPolicyEvolutionResponse,
)
def agent_redhead_policy_evolution(
    request: RedheadPolicyEvolutionRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> RedheadPolicyEvolutionResponse:
    """政策演变:一卷宗逐份建文脉 → 一次 LLM 按成文日期序排演变(每阶段标改了什么)。

    ``policy_evolution_from_spines`` 锚回真实字号、每阶段 snippet 取那份文脉已核 evidence
    (锚不到原文的阶段丢)。主题(topic)可选;主题不在这摞文件返空 + scanned=true,
    一次推理失败 / 没可锚文件返 scanned=false。
    """
    client = _build_params_client_or_raise(request)
    model = request.model or default_model_for(request.provider)
    rec = _UsageRecorder(client)
    _t0 = time.monotonic()
    spines = _collect_doc_spines(
        store, request.book_session_ids, llm_client=rec, model=model
    )
    stages = policy_evolution_from_spines(
        doc_spines=spines, llm_client=rec, model=model, topic=request.topic
    )
    # 措辞 diff(逐字比):政策的新闻在 delta 里(鼓励→应当=升格、严格→合理=松绑),与阶段并列。
    wording_diffs = policy_wording_diff_from_spines(
        doc_spines=spines, llm_client=rec, model=model, topic=request.topic
    )
    return RedheadPolicyEvolutionResponse(
        stages=stages or [],
        wording_diffs=wording_diffs or [],
        scanned=stages is not None,
        trace=_run_trace(rec, "", _t0),
    )


@agent_router.post(
    "/agent/redhead/level-consistency",
    response_model=RedheadLevelConsistencyResponse,
)
def agent_redhead_level_consistency(
    request: RedheadCrossDocRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> RedheadLevelConsistencyResponse:
    """上下级一致性核查:一卷宗逐份建文脉 → 一次 LLM 找上下级要求对不上的地方。

    ``level_consistency_from_spines`` 按机关层级判上下级、双向守卫(两侧 snippet 都取已核
    evidence,任一坐实不了的整条丢,不 cry wolf)。题材自适应:全平级 / 单文件 / 层级全未知
    (没上下级落差)返 scanned=false,这个视图本就该掉;都一致返空 + scanned=true。
    """
    client = _build_params_client_or_raise(request)
    model = request.model or default_model_for(request.provider)
    rec = _UsageRecorder(client)
    _t0 = time.monotonic()
    spines = _collect_doc_spines(
        store, request.book_session_ids, llm_client=rec, model=model
    )
    conflicts = level_consistency_from_spines(
        doc_spines=spines, llm_client=rec, model=model
    )
    return RedheadLevelConsistencyResponse(
        conflicts=conflicts or [],
        scanned=conflicts is not None,
        trace=_run_trace(rec, "", _t0),
    )


@agent_router.post(
    "/agent/redhead/plain-language",
    response_model=RedheadPlainLanguageResponse,
)
def agent_redhead_plain_language(
    request: RedheadPlainLanguageRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> RedheadPlainLanguageResponse:
    """大白话翻译:公文体翻人话,核原文不核白话。mode=clauses 逐条款摘译 / fulltext 整篇逐句(#22);
    命中措辞刻度的条目带 nuance 点弦外之意(如"原则上"→有口子),弦外只在原文真有该词时才点。"""
    assembler = _resolve_assembler(store, request.book_session_id)
    client = _build_params_client_or_raise(request)
    model = request.model or default_model_for(request.provider)
    full_text, chunks = _long_context_inputs(assembler)
    rec = _UsageRecorder(client)
    _t0 = time.monotonic()
    result = plain_language_from_spine(
        chunks=chunks, llm_client=rec, model=model, full_text=full_text, mode=request.mode
    )
    items = result.get("items") or []
    return RedheadPlainLanguageResponse(
        mode=result.get("mode", request.mode),
        items=items,
        scanned=bool(items),
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, full_text, _t0),
    )


@agent_router.post(
    "/agent/redhead/close-reading",
    response_model=RedheadCloseReadingResponse,
)
def agent_redhead_close_reading(
    request: RedheadDocStructureRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> RedheadCloseReadingResponse:
    """逐条精读(公文整合 centerpiece):一份公文一次出每条的大白话 + 结构标签 + 内联术语 + 对原文。

    整合 1+2(设计稿 WP-redhead-consolidation):原先大白话 / 名词解释 / 公文结构条款三个 tab 啃的是
    同一批原文条款,合到一张卡。后端合成,三件套全从同一份文脉派生——大白话改写吃条款事项+原文、
    结构标签直接取条款骨架(不重抽)、术语全文挑出后按原句归到对应条款。核的是原文不是白话;术语
    核不过的不挂;命中措辞刻度才点弦外之意。
    """
    assembler = _resolve_assembler(store, request.book_session_id)
    client = _build_params_client_or_raise(request)
    model = request.model or default_model_for(request.provider)
    full_text, chunks = _long_context_inputs(assembler)
    rec = _UsageRecorder(client)
    _t0 = time.monotonic()
    result = close_reading_from_spine(
        chunks=chunks, llm_client=rec, model=model, full_text=full_text
    )
    items = result.get("items") or []
    return RedheadCloseReadingResponse(
        items=items,
        scanned=bool(items),
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, full_text, _t0),
    )


@agent_router.post(
    "/agent/redhead/relevance",
    response_model=RedheadRelevanceResponse,
)
def agent_redhead_relevance(
    request: RedheadRelevanceRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> RedheadRelevanceResponse:
    """跟我相关:据用户身份(role)筛出这份公文里跟他相关的条款 + 对他的义务/利好/条件。

    **已退役(1.6 整合 3,设计稿 WP-redhead-consolidation 整合 3)**:逻辑已并进「利害与风向」
    (``/redhead/stakes`` 输出的 related_clauses 段,身份可选)。前端入口 + 组件已撤;端点 +
    ``relevance_from_spine`` 暂留一个版本周期,不再单独对外亮出。
    """
    assembler = _resolve_assembler(store, request.book_session_id)
    client = _build_params_client_or_raise(request)
    model = request.model or default_model_for(request.provider)
    full_text, chunks = _long_context_inputs(assembler)
    rec = _UsageRecorder(client)
    _t0 = time.monotonic()
    result = relevance_from_spine(
        chunks=chunks, role=request.role, llm_client=rec, model=model, full_text=full_text
    )
    items = result.get("items") or []
    return RedheadRelevanceResponse(
        role=result.get("role", request.role),
        items=items,
        scanned=bool(items),
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, full_text, _t0),
    )


@agent_router.post("/agent/redhead/stakes", response_model=RedheadStakesResponse)
def agent_redhead_stakes(
    request: RedheadStakesRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> RedheadStakesResponse:
    """利害与风向:先列跟你相关的条款,再按角色研判机会/风险(带含金量)+ 透出的信号(弦外之音)。

    整合 3(设计稿 WP-redhead-consolidation):吸收原「跟我相关」——输出多一段 related_clauses
    (跟这身份直接相关的条款,事实底座)。身份可选,不填给通用版(面向一般读者研判)。
    相关条款/机会/风险=证据层(锚原文核验);信号=评估层(标研判+置信度+原文基础,绝不盖鉴印)。
    含金量按开环/闭环判:闭环(有主体+时限+考核罚则)=真金白银,开环(纯号召)=空头倡导。
    """
    assembler = _resolve_assembler(store, request.book_session_id)
    client = _build_params_client_or_raise(request)
    model = request.model or default_model_for(request.provider)
    full_text, chunks = _long_context_inputs(assembler)
    rec = _UsageRecorder(client)
    _t0 = time.monotonic()
    result = stakes_from_doc(
        chunks=chunks, role=request.role, llm_client=rec, model=model, full_text=full_text
    )
    related = result.get("related_clauses") or []
    opportunities = result.get("opportunities") or []
    risks = result.get("risks") or []
    signals = result.get("signals") or []
    return RedheadStakesResponse(
        role=result.get("role", request.role),
        related_clauses=related,
        opportunities=opportunities,
        risks=risks,
        signals=signals,
        recommendation=result.get("recommendation", ""),
        scanned=bool(related or opportunities or risks or signals),
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, full_text, _t0),
    )


@agent_router.post(
    "/agent/redhead/hard-facts",
    response_model=RedheadHardFactsResponse,
)
def agent_redhead_hard_facts(
    request: RedheadDocStructureRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> RedheadHardFactsResponse:
    """硬信息提取表:把散落全文的时限/数字指标/适用范围/生效废止/责任主体聚成速查表。"""
    assembler = _resolve_assembler(store, request.book_session_id)
    client = _build_params_client_or_raise(request)
    model = request.model or default_model_for(request.provider)
    full_text, chunks = _long_context_inputs(assembler)
    rec = _UsageRecorder(client)
    _t0 = time.monotonic()
    result = hard_facts_from_spine(
        chunks=chunks, llm_client=rec, model=model, full_text=full_text
    )
    facts = result.get("facts") or []
    return RedheadHardFactsResponse(
        facts=facts,
        scanned=bool(facts),
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, full_text, _t0),
    )


@agent_router.post(
    "/agent/meeting/action-ledger",
    response_model=MeetingActionLedgerResponse,
)
def agent_meeting_action_ledger(
    request: MeetingActionLedgerRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> MeetingActionLedgerResponse:
    """行动项台账 / 我的行动项:一份会议记录精读一次出会脉,派生「谁·做什么·何时·落实哪条决议」清单。

    会议命根子不是「谁说了什么」(几百轮口水话),是「定了什么、谁要去做什么」(三五条干货)。
    loose_end(owner 空或 due 空)是会议最大黑洞,台账置顶;含金量按开环/闭环判,叶子档是会议版
    「空头表态」。传 owner 就只返该身份的行动项(我的行动项)。owner/due 抽不到留空、绝不编人。
    """
    assembler = _resolve_assembler(store, request.book_session_id)
    client = _build_params_client_or_raise(request)
    model = request.model or default_model_for(request.provider)
    full_text, chunks = _long_context_inputs(assembler)
    rec = _UsageRecorder(client)
    _t0 = time.monotonic()
    result = action_ledger_from_meeting(
        chunks=chunks,
        llm_client=rec,
        model=model,
        full_text=full_text,
        form=request.form,
        owner=request.owner,
    )
    action_items = result.get("action_items") or []
    decisions = result.get("decisions") or []
    head = result.get("head") or []
    # scanned=精读成功:抽到任一行动项 / 决议,或头要素抽到了东西(读过这份会议)。
    head_has_value = any(str(el.get("value", "")).strip() for el in head)
    return MeetingActionLedgerResponse(
        form=result.get("form", "纪要"),
        head=head,
        decisions=decisions,
        action_items=action_items,
        open_issues=result.get("open_issues") or [],
        owner=result.get("owner"),
        scanned=bool(action_items or decisions or head_has_value),
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, full_text, _t0),
    )


@agent_router.post(
    "/agent/meeting/stance",
    response_model=MeetingStanceResponse,
)
def agent_meeting_stance(
    request: MeetingStanceRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> MeetingStanceResponse:
    """立场与弦外(1.7 会议·第四炮):读一场会的逐字稿,挖字面底下的真实态度 + 言下之意。

    前面四块回答「定了什么、谁要办什么」,立场与弦外回答「大家心里到底怎么想、表态有几分真」——
    会议比公文多出的一维(多方角力)。整个是**评估层**(同公文信号段):每条立场/弦外标研判 +
    引原话基础 + 置信度,**绝不盖鉴印**;basis 一条都核不到就丢整条(命门)。
    position 五态 / 弦外六类 / 含金量三档 / verdict 三态都是封闭集,落不进退最保守。
    **纪要退场**:纪要是编辑稿读不出语气 → 返空 + 提示传逐字稿(绝不在概括句上硬编)。
    """
    assembler = _resolve_assembler(store, request.book_session_id)
    client = _build_params_client_or_raise(request)
    model = request.model or default_model_for(request.provider)
    full_text, chunks = _long_context_inputs(assembler)
    rec = _UsageRecorder(client)
    _t0 = time.monotonic()
    result = stances_from_meeting(
        chunks=chunks,
        llm_client=rec,
        model=model,
        full_text=full_text,
        form=request.form,
    )
    topics = result.get("topics") or []
    # scanned=精读成功:抽到任一立场/弦外,或任一议题确证一致无弦外(确证无也是扫过了)。
    has_any = any(
        t.get("stances") or t.get("subtexts")
        or t.get("verdict") == "确证一致无弦外"
        for t in topics
    )
    return MeetingStanceResponse(
        form=result.get("form", "纪要"),
        form_note=result.get("form_note", ""),
        topics=topics,
        summary=result.get("summary", ""),
        scanned=has_any,
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, full_text, _t0),
    )


def _collect_meeting_inputs(
    store: BookSessionStore,
    session_ids: list[str],
) -> tuple[list[list[dict]], list[str]]:
    """逐个 resolve assembler → 拿 (full_text, chunks),凑成多场会的输入栈。

    每个 session_id 都过 ``_resolve_assembler``(找不到照样翻 404,不静默跳过——卷宗里点名的
    会议必须都在)。返 ``(各场 chunks, 各场 full_text)`` 两条同序 list,喂给
    ``commitments_across_meetings``(它内部逐场建会脉、跨会追)。
    """
    chunks_stack: list[list[dict]] = []
    full_texts: list[str] = []
    for sid in session_ids:
        assembler = _resolve_assembler(store, sid)
        full_text, chunks = _long_context_inputs(assembler)
        chunks_stack.append(chunks)
        full_texts.append(full_text)
    return chunks_stack, full_texts


@agent_router.post(
    "/agent/meeting/commitments",
    response_model=MeetingCommitmentsResponse,
)
def agent_meeting_commitments(
    request: MeetingCommitmentsRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> MeetingCommitmentsResponse:
    """跨会承诺—兑现追踪(1.7 杀手价值):多场会摆一起,追「谁承诺了、后来兑现没」。

    单场会的行动项台账只看一场;这里把一卷宗的好几场会按时间串起来,沿时间线追每条承诺的下落——
    张三 6 月说「下周交鉴权」,7 月的会还没影,这条就标「逾期 / 未兑现」捞出来。跟公文跨文件的依据
    链网一个道理:价值在跨单元的连线。

    ``commitments_across_meetings`` 逐场建会脉(承诺=行动项)→ 一次全局推理跨会判兑现 → 锚回真实
    承诺 + 核兑现证据(更晚会议的已核原话,锚不到降「未知」)+ 逾期 BE 据 due 纯算。死守 evidence-
    first:判不出兑现没就标「进行中 / 未知」,绝不猜「兑现」(假阳性=骗用户说做完了,最坏)。
    传 owner 就只返该身份的承诺(我的承诺)。不足 2 场会 / 一条承诺都没抽到 → 空态。
    """
    client = _build_params_client_or_raise(request)
    model = request.model or default_model_for(request.provider)
    chunks_stack, full_texts = _collect_meeting_inputs(store, request.book_session_ids)
    rec = _UsageRecorder(client)
    _t0 = time.monotonic()
    result = commitments_across_meetings(
        meeting_chunks=chunks_stack,
        llm_client=rec,
        model=model,
        meeting_full_texts=full_texts,
        owner=request.owner,
    )
    commitments = (result or {}).get("commitments", [])
    return MeetingCommitmentsResponse(
        commitments=commitments,
        meetings=(result or {}).get("meetings", []),
        owners=(result or {}).get("owners", []),
        owner=request.owner.strip() if (request.owner and request.owner.strip()) else None,
        # scanned=成功跨会追到了(有承诺台账)。result None=不足2场/无承诺=空态。
        scanned=result is not None,
        trace=_run_trace(rec, "", _t0),
    )


@agent_router.post(
    "/agent/redhead/timeline",
    response_model=RedheadTimelineResponse,
)
def agent_redhead_timeline(
    request: RedheadDocStructureRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> RedheadTimelineResponse:
    """关键时间轴:抽这份公文里的时间节点(申报/实施/过渡/生效/废止)排成时序。

    **已退役(1.6 整合 4,设计稿 WP-redhead-consolidation 整合 4)**:时间类硬事实并进「要点提取」
    (``/redhead/hard-facts`` 的时限/生效废止两类 + 前端「时序视图」切换)。前端入口 + 组件已撤;
    端点 + ``timeline_from_spine`` 暂留一个版本周期,不再单独对外亮出。
    """
    assembler = _resolve_assembler(store, request.book_session_id)
    client = _build_params_client_or_raise(request)
    model = request.model or default_model_for(request.provider)
    full_text, chunks = _long_context_inputs(assembler)
    rec = _UsageRecorder(client)
    _t0 = time.monotonic()
    result = redhead_timeline_from_spine(
        chunks=chunks, llm_client=rec, model=model, full_text=full_text
    )
    nodes = result.get("nodes") or []
    return RedheadTimelineResponse(
        nodes=nodes,
        scanned=bool(nodes),
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, full_text, _t0),
    )


@agent_router.post(
    "/agent/redhead/glossary",
    response_model=RedheadGlossaryResponse,
)
def agent_redhead_glossary(
    request: RedheadDocStructureRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> RedheadGlossaryResponse:
    """名词解释:挑出这份公文里普通人看不懂的术语/政策黑话,用人话释义。

    **已退役(1.6 整合,设计稿 WP-redhead-consolidation 整合 2)**:术语逻辑已内联进「逐条精读」
    (``/redhead/close-reading``,术语锚在出现它的那条上)。前端入口 + 组件已撤;端点 + ``glossary_
    from_spine`` 暂留(逐条精读复用它全文挑词的逻辑),不再单独对外亮出。将来若实测要「全文术语
    总览」,在逐条精读加折叠区,不复活本入口。
    """
    assembler = _resolve_assembler(store, request.book_session_id)
    client = _build_params_client_or_raise(request)
    model = request.model or default_model_for(request.provider)
    full_text, chunks = _long_context_inputs(assembler)
    rec = _UsageRecorder(client)
    _t0 = time.monotonic()
    result = glossary_from_spine(
        chunks=chunks, llm_client=rec, model=model, full_text=full_text
    )
    terms = result.get("terms") or []
    return RedheadGlossaryResponse(
        terms=terms,
        scanned=bool(terms),
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, full_text, _t0),
    )


@agent_router.post(
    "/agent/redhead/format-check",
    response_model=RedheadFormatCheckResponse,
)
def agent_redhead_format_check(
    request: RedheadDocStructureRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> RedheadFormatCheckResponse:
    """规范性自检:对照 GB/T 9704 看这份公文该有的要素齐不齐、文种对不对(有国标当标准答案)。"""
    assembler = _resolve_assembler(store, request.book_session_id)
    client = _build_params_client_or_raise(request)
    model = request.model or default_model_for(request.provider)
    full_text, chunks = _long_context_inputs(assembler)
    rec = _UsageRecorder(client)
    _t0 = time.monotonic()
    result = format_check_from_spine(
        chunks=chunks, llm_client=rec, model=model, full_text=full_text
    )
    checks = result.get("checks") or []
    return RedheadFormatCheckResponse(
        checks=checks,
        summary=result.get("summary") or {},
        scanned=bool(checks),
        book_session_id=request.book_session_id,
        trace=_run_trace(rec, full_text, _t0),
    )


@agent_router.post("/agent/book/report")
def agent_book_report(
    request: BookReportRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> Response:
    """书鉴报告：章脉缓存 → 书鉴风格 HTML 报告（P1）。

    只读缓存（peek），章脉没建过就 404 提示先跑分析 / 预建——报告不主动触发全书精读。
    返回完整 HTML 页面（media_type=text/html），前端可直接下载/新窗口打开。
    """
    assembler = _resolve_assembler(store, request.book_session_id)
    model = request.model or default_model_for(request.provider)
    _, chunks = _long_context_inputs(assembler)
    # 按章渐进：有部分缓存就出部分报告（报告里标"已覆盖 N/M 章"）；一章都没有就出
    # 秒级零 LLM 结构版（章节 + 首段），绝不干等——深度版由后台预建补上。
    book_title, _ = _extract_book_meta(assembler)
    display_title = book_title if book_title and book_title != "unknown" else "本书"
    progress = spine_build_progress(chunks=chunks, model=model, genre="fiction")
    total = progress["total"]
    built = progress["built"]
    spine = peek_spine_cache(chunks=chunks, model=model, genre="fiction")

    if not spine:
        inp = build_structure_report(chunks, {
            "title": f"《{display_title}》书鉴报告（结构版）",
            "seal": "书 鉴",
            "nav_title": "书鉴 · 报告导航",
            "unit_label": "章",
            "generated_by": f"书鉴 BookScope · 《{display_title}》",
        })
        html = render_report(inp)
        return Response(content=html, media_type="text/html; charset=utf-8", headers={"X-Report-Coverage": "structure"})
    else:
        subtitle = f"已覆盖 {built}/{total} 章" if total else f"{len(spine)} 章"
        if built < total:
            subtitle += "（后台继续补建中，可稍后重新生成查看更全版本）"
        inp = build_book_report(spine, {
            "title": f"《{display_title}》书鉴报告",
            "subtitle": subtitle,
            "seal": "书 鉴",
            "nav_title": "书鉴 · 报告导航",
            "unit_label": "章",
            "generated_by": f"书鉴 BookScope · 《{display_title}》",
        })
        coverage = "full" if built >= total else f"partial:{built}/{total}"
        html = render_report(inp)
        return Response(content=html, media_type="text/html; charset=utf-8", headers={"X-Report-Coverage": coverage})


def _cross_book_payload(
    request: CrossBookReportRequest,
    store: BookSessionStore,
) -> tuple[list[dict], dict, str]:
    """跨文本对照共用逻辑：校验全就绪 → 建 client → 每本 perspective → 全局 reason。

    返回 ``(perspectives, reason, titles)``，供 HTML 报告与 JSON 工作台复用。
    """
    model = request.model or default_model_for(request.provider)
    assemblers = []
    progress_list = []
    for sid in request.book_session_ids:
        assembler = _resolve_assembler(store, sid)
        _full_text, chunks = _long_context_inputs(assembler)
        progress = spine_build_progress(chunks=chunks, model=model, genre="fiction")
        progress_list.append({"session_id": sid, **progress})
        if progress["total"] == 0 or progress["built"] < progress["total"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error_type": "SpineNotReady",
                    "message": "有文档章脉未建完，先等预建完成再对照",
                    "progress": progress_list,
                },
            )
        assemblers.append((sid, assembler, chunks))

    client = _build_prewarm_client(
        provider=request.provider,
        api_key=request.api_key,
        base_url=request.base_url,
    )
    perspectives = []
    for sid, assembler, chunks in assemblers:
        spine = get_or_build_spine(chunks=chunks, llm_client=client, model=model, genre="fiction")
        book_title, _ = _extract_book_meta(assembler)
        slug = sid[-8:]
        perspectives.append(build_book_perspective(
            spine=spine, book_title=book_title or sid, slug=slug,
            llm_client=client, model=model,
        ))

    reason = cross_book_reason(perspectives=perspectives, llm_client=client, model=model)
    titles = " × ".join(p.get("title", "") for p in perspectives)
    return perspectives, reason, titles


@agent_router.post("/agent/cross-book/report")
def agent_cross_book_report(
    request: CrossBookReportRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> Response:
    """多本书 / 文档簇对照报告（P2 跨文本泛化）。

    每本先取章脉（全部命中才继续；没全建返回 409 + 进度），提炼书级主张（轻 LLM），
    再做一次跨文本对照推理，出书鉴对照报告。跨文本关系是研判（不盖「鉴」印）。
    """
    perspectives, reason, titles = _cross_book_payload(request, store)
    inp = build_cross_book_report_input(
        perspectives=perspectives, reason=reason,
        meta={
            "title": f"跨文本对照 · {titles}",
            "seal": "书 鉴",
            "nav_title": "对照 · 报告导航",
            "unit_label": "份",
            "generated_by": f"书鉴 BookScope · 跨文本对照（{len(perspectives)} 份）",
        },
    )
    html = render_report(inp)
    return Response(content=html, media_type="text/html; charset=utf-8", headers={"X-Report-Coverage": "full"})


@agent_router.post("/agent/cross-book/data")
def agent_cross_book_data(
    request: CrossBookReportRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> dict:
    """跨文本对照 JSON 数据端点：给前端「对照工作台」用。

    与 /agent/cross-book/report 同一套逻辑，只返回结构化数据
    （perspectives + reason + titles），不渲染 HTML。
    """
    perspectives, reason, titles = _cross_book_payload(request, store)
    return {
        "perspectives": perspectives,
        "reason": reason,
        "titles": titles,
    }


@agent_router.post("/agent/cross-book/ask", response_model=CrossBookAskResponse)
def agent_cross_book_ask(
    request: CrossBookAskRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> CrossBookAskResponse:
    """跨文本对照追问：在多书观点骨架 + 已有对照结论上回答，不重读全文。"""
    model = request.model or default_model_for(request.provider)
    try:
        client = build_llm_client_from_params(
            provider=request.provider,
            api_key=request.api_key,
            base_url=request.base_url,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_type": "ProviderSdkMissing", "message": str(exc)},
        ) from exc

    perspectives = []
    for sid in request.book_session_ids:
        assembler = _resolve_assembler(store, sid)
        _full_text, chunks = _long_context_inputs(assembler)
        spine = peek_spine_cache(chunks=chunks, model=model, genre="fiction")
        if not spine:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error_type": "SpineNotReady",
                    "message": "有文档章脉未建完，先等预建完成再追问",
                },
            )
        book_title, _ = _extract_book_meta(assembler)
        perspectives.append(build_book_perspective(
            spine=spine, book_title=book_title or sid, slug=sid[-8:],
            llm_client=client, model=model,
        ))

    reason = cross_book_reason(perspectives=perspectives, llm_client=client, model=model)
    result = cross_book_ask(
        perspectives=perspectives, reason=reason, question=request.question,
        llm_client=client, model=model,
    )
    return CrossBookAskResponse(answer=result.get("answer", ""), sources=result.get("sources", []))


@agent_router.get("/agent/spine-progress")
def agent_spine_progress(
    ids: str,
    model: str | None = None,
    provider: str = "deepseek",
    store: BookSessionStore = Depends(get_book_session_store),
) -> dict:
    """批量查询多本书章脉进度（纯读缓存，绝不构建）。书柜徽章用。

    返回 {"books": [{session_id, built, total, ready}]}。
    """
    resolved_model = model or default_model_for(provider)
    out = []
    for sid in [x for x in ids.split(",") if x]:
        try:
            assembler = _resolve_assembler(store, sid)
            _full_text, chunks = _long_context_inputs(assembler)
            progress = spine_build_progress(chunks=chunks, model=resolved_model, genre="fiction")
            # 预建失败也带出来，前端可以显示「预建失败」而不是永远 not ready
            key = _prewarm_key(sid, resolved_model)
            with _PREWARM_LOCK:
                cur = _PREWARM_STATE.get(key)
            error = cur.get("error") if cur and cur.get("status") == "error" else None
            out.append({
                "session_id": sid,
                "built": progress["built"],
                "total": progress["total"],
                "ready": progress["total"] > 0 and progress["built"] >= progress["total"],
                "error": error,
            })
        except Exception:  # noqa: BLE001 — 单本失败给空，不阻断批量
            out.append({"session_id": sid, "built": 0, "total": 0, "ready": False, "error": None})
    return {"books": out}


@agent_router.post("/agent/cluster/report")
def agent_cluster_report(
    request: ClusterReportRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> Response:
    """来源组（簇）总览报告：列组内每本书 + 章脉状态，纯聚合秒出。

    不调 LLM；给文档簇管理一个可分享的交付物（书鉴风格 HTML）。
    """
    model = request.model or default_model_for(request.provider)
    nodes = []
    spines = {}
    e1 = {}
    ready = 0
    for sid in request.book_session_ids:
        try:
            assembler = _resolve_assembler(store, sid)
            _full_text, chunks = _long_context_inputs(assembler)
            progress = spine_build_progress(chunks=chunks, model=model, genre="fiction")
            book_title, _ = _extract_book_meta(assembler)
            slug = sid[-8:]
            status = (
                "章脉就绪"
                if progress["total"] > 0 and progress["built"] >= progress["total"]
                else f"章脉 {progress['built']}/{progress['total']}"
                if progress["total"] > 0
                else "待构建"
            )
            if progress["total"] > 0 and progress["built"] >= progress["total"]:
                ready += 1
            nodes.append({"slug": slug, "label": (book_title or sid)[:20], "stance": status})
            spines[slug] = {
                "_title": book_title or sid,
                "_slug": slug,
                "core_thesis": f"{status} · 来源：{getattr(assembler, 'source_folder', '手动上传')}",
                "theoretical_stance": {"label": "", "inference": False},
                "method": "",
                "key_citations": [],
            }
            e1[slug] = {"quotes": []}
        except Exception:  # noqa: BLE001 — 单本失败跳过
            continue

    total = len(request.book_session_ids)
    inp = {
        "layout": "crossdoc",
        "meta": {
            "title": f"簇总览 · {request.cluster_name}",
            "subtitle": f"{len(nodes)}/{total} 本 · {ready} 本就绪 · 可整组对照 / 逐本出报告",
            "seal": "书 鉴",
            "nav_title": "簇 · 总览",
            "unit_label": "本",
            "generated_by": f"书鉴 BookScope · 簇总览（{request.cluster_name}）",
        },
        "nodes": nodes,
        "edges": [],
        "concept_evolution": [],
        "disagreements": [],
        "narrative": f"来源组《{request.cluster_name}》共 {total} 本。就绪 {ready} 本，"
                     f"可对这些书做跨文本对照、逐本出书鉴报告、文档簇问答。",
        "spines": spines,
        "e1": e1,
        "quality": {"e2_mean": 0, "e3": None},
    }
    html = render_report(inp)
    return Response(content=html, media_type="text/html; charset=utf-8", headers={"X-Report-Coverage": "full"})


def _dedupe_cluster_edges(edges: list[dict]) -> list[dict]:
    """按 (from,to,relation) 去重，保留第一条 rationale。"""
    seen: set[tuple[str, str, str]] = set()
    out: list[dict] = []
    for e in edges:
        key = (str(e.get("from", "")), str(e.get("to", "")), str(e.get("relation", "")))
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


def _merge_cluster_concepts(items: list[dict]) -> list[dict]:
    """把两两对照里的概念演进按概念名合并，stage 按 (paper,stage) 去重。

    返回出现次数最多的前 5 个概念——比直接取前 N 条 pair 结果更有簇代表性。
    """
    merged: dict[str, list[dict]] = {}
    for item in items:
        name = str(item.get("concept", "")).strip()
        if not name:
            continue
        stages = merged.setdefault(name, [])
        existing = {(str(x.get("paper", "")), str(x.get("stage", ""))) for x in stages}
        for st in item.get("stages", []):
            key = (str(st.get("paper", "")), str(st.get("stage", "")))
            if key not in existing:
                stages.append(st)
                existing.add(key)
    arr = [{"concept": k, "stages": v} for k, v in merged.items()]
    arr.sort(key=lambda x: len(x["stages"]), reverse=True)
    return arr[:5]


def _merge_cluster_disputes(items: list[dict]) -> list[dict]:
    """把两两对照里的分歧按问题合并，side 按 (paper,stance) 去重。

    返回涉及书最多的前 5 个问题——簇级分歧比单对更完整。
    """
    merged: dict[str, list[dict]] = {}
    for item in items:
        q = str(item.get("question", "")).strip()
        if not q:
            continue
        sides = merged.setdefault(q, [])
        existing = {(str(x.get("paper", "")), str(x.get("stance", ""))) for x in sides}
        for sd in item.get("sides", []):
            key = (str(sd.get("paper", "")), str(sd.get("stance", "")))
            if key not in existing:
                sides.append(sd)
                existing.add(key)
    arr = [{"question": k, "sides": v} for k, v in merged.items()]
    arr.sort(key=lambda x: len(x["sides"]), reverse=True)
    return arr[:5]


def _cluster_discover_payload(
    request: ClusterDiscoverRequest,
    store: BookSessionStore,
) -> dict:
    """簇关系自动发现共用逻辑：全就绪校验 → perspectives → 两两聚合整理。

    返回 dict 供 HTML 报告与 JSON 工作台复用。
    """
    model = request.model or default_model_for(request.provider)
    client = _build_prewarm_client(
        provider=request.provider,
        api_key=request.api_key,
        base_url=request.base_url,
    )

    # 取每本 perspective（缓存命中秒出）；必须整本全就绪——部分章脉做簇关系
    # 会漏掉未建章的主张，误导整组关系网。先扫一遍全部进度，未就绪一次报全。
    progress_list = []
    assemblers = []
    not_ready = False
    for sid in request.book_session_ids:
        assembler = _resolve_assembler(store, sid)
        _full_text, chunks = _long_context_inputs(assembler)
        progress = spine_build_progress(chunks=chunks, model=model, genre="fiction")
        progress_list.append({"session_id": sid, **progress})
        assemblers.append((sid, assembler, chunks))
        if progress["total"] == 0 or progress["built"] < progress["total"]:
            not_ready = True
    if not_ready:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_type": "SpineNotReady",
                "message": "有文档章脉未建完，先等预建完成再自动发现",
                "progress": progress_list,
            },
        )
    perspectives = []
    for sid, assembler, chunks in assemblers:
        spine = peek_spine_cache(chunks=chunks, model=model, genre="fiction")
        book_title, _ = _extract_book_meta(assembler)
        perspectives.append(build_book_perspective(
            spine=spine, book_title=book_title or sid, slug=sid[-8:],
            llm_client=client, model=model,
        ))

    # 两两对照聚合
    from itertools import combinations

    nodes = []
    seen_slugs = set()
    edges = []
    concepts = []
    disputes = []
    pair_count = 0
    for a, b in combinations(perspectives, 2):
        reason = cross_book_reason(perspectives=[a, b], llm_client=client, model=model)
        for n in reason.get("nodes", []):
            if n.get("slug") not in seen_slugs:
                seen_slugs.add(n["slug"])
                nodes.append(n)
        edges.extend(reason.get("edges", []))
        concepts.extend(reason.get("concept_evolution", []))
        disputes.extend(reason.get("disagreements", []))
        pair_count += 1

    if not nodes:
        # 兜底：perspective 本身当节点
        nodes = [
            {"slug": p.get("slug", ""), "label": p.get("title", ""), "stance": p.get("stance", "")}
            for p in perspectives if p.get("slug")
        ]

    # 聚合后整理：边去重，概念/分歧按主题合并排序（簇级比单对更完整）
    edges = _dedupe_cluster_edges(edges)
    concepts = _merge_cluster_concepts(concepts)
    disputes = _merge_cluster_disputes(disputes)
    narrative = (
        f"《{request.cluster_name}》共 {len(nodes)} 本，两两对照 {pair_count} 对，"
        f"发现 {len(edges)} 条关系（继承/反驳/补充/落地/检验）。关系为 LLM 研判，锚到各书主张。"
    )
    return {
        "cluster_name": request.cluster_name,
        "perspectives": perspectives,
        "nodes": nodes,
        "edges": edges,
        "concepts": concepts,
        "disputes": disputes,
        "pair_count": pair_count,
        "narrative": narrative,
    }


@agent_router.post("/agent/cluster/discover")
def agent_cluster_discover(
    request: ClusterDiscoverRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> Response:
    """自动发现簇内两两关系：每对书一次跨文本对照，聚合关系网。

    成本 = C(n,2) 次轻 LLM（perspective 缓存命中则只付 reason）。输出书鉴风格
    对照报告：nodes=全部书，edges=所有 pair 的继承/反驳/补充/落地/检验。
    """
    payload = _cluster_discover_payload(request, store)
    nodes = payload["nodes"]
    edges = payload["edges"]
    concepts = payload["concepts"]
    disputes = payload["disputes"]
    perspectives = payload["perspectives"]
    pair_count = payload["pair_count"]
    title = f"簇关系网 · {request.cluster_name}"
    inp = {
        "layout": "crossdoc",
        "meta": {
            "title": title,
            "subtitle": f"{len(nodes)} 本 · {len(edges)} 条关系（{pair_count} 对两两对照）· 关系为研判",
            "seal": "书 鉴",
            "nav_title": "簇关系 · 导航",
            "unit_label": "本",
            "generated_by": f"书鉴 BookScope · 自动发现（{request.cluster_name}）",
        },
        "nodes": nodes,
        "edges": edges,
        "concept_evolution": concepts,
        "disagreements": disputes,
        "narrative": payload["narrative"],
        "spines": {
            p.get("slug", f"b{i}"): {
                "_title": p.get("title", ""),
                "_slug": p.get("slug", f"b{i}"),
                "core_thesis": p.get("summary", ""),
                "theoretical_stance": {"label": p.get("stance", ""), "inference": True},
                "method": "",
                "key_citations": [
                    {"quote": c.get("claim", ""), "role": f"第{c.get('chapter','?')}章"}
                    for c in p.get("claims", [])[:5] if c.get("claim")
                ],
            }
            for i, p in enumerate(perspectives)
        },
        "e1": {
            p.get("slug", f"b{i}"): {
                "quotes": [{"quote": c.get("claim", ""), "verified": False} for c in p.get("claims", [])[:5] if c.get("claim")]
            }
            for i, p in enumerate(perspectives)
        },
        "quality": {"e2_mean": 0, "e3": None},
    }
    html = render_report(inp)
    return Response(content=html, media_type="text/html; charset=utf-8", headers={"X-Report-Coverage": "full"})


@agent_router.post("/agent/cluster/discover/data")
def agent_cluster_discover_data(
    request: ClusterDiscoverRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> dict:
    """簇关系发现 JSON 数据端点：给前端「簇工作台」用。

    与 /agent/cluster/discover 同一套两两聚合逻辑，返回结构化数据不渲染 HTML。
    """
    return _cluster_discover_payload(request, store)


__all__ = ["agent_router"]
