"""长上下文路径：整本书进 context、单次 LLM 答题（WP-retrieval-routing）。

exp-009 实测 GO：能塞下的书上"长上下文 + 缓存"在缓存命中 / 成本 / 延迟上压
当前 RAG，全局 / 结构题质量 ≥ RAG。本模块是它的生产实现。

结构同 :func:`bookscope.agent.fast_path.run_fast_path`（单次 LLM → parse → verify
→ 拼 :class:`AgentQueryResult`），差别两处：

1. **没有 search 步**——整本 cleaned text 进 system 固定段（稳定前缀，保 DeepSeek
   服务端前缀缓存命中；exp-009 实测第 2 问起命中 ~100%）。
2. **citation 证据用全书 chunks**——snippet 在原文任一 chunk 里匹配即 ``verified``，
   对章号漂移鲁棒（evidence-first 不丢：答案照样过 :func:`verify_citations`）。

契约同 ``run_fast_path``：成功返 :class:`AgentQueryResult`，**任意环节失败返 None**
——调用方据此回退到 RAG agent loop。
"""

from __future__ import annotations

import logging
import time
from typing import Any

from bookscope.agent._internal.llm_cache import invoke_client_cached as _invoke_client
from bookscope.agent._internal.longctx_system import build_longctx_system
from bookscope.agent._internal.loop_shared import elapsed_ms as _elapsed_ms
from bookscope.agent.citation_check import verify_citations
from bookscope.agent.events import FinalAnswerEvent, IterationStartEvent, LoopCallback
from bookscope.agent.models import AgentQueryResult, LoopTrace
from bookscope.agent.utils.json_parsing import parse_final_answer

logger = logging.getLogger(__name__)

DEFAULT_LONGCTX_MAX_TOKENS = 4000

# 答案 JSON 解析失败重试次数（flash 偶发回不合格 JSON，2026-06-16 实测 6 题 2 题翻车）。
_LONGCTX_MAX_ATTEMPTS = 2

# 重试纠正提示——放进 user 消息（不动 system 书前缀，保 DeepSeek 前缀缓存命中）。
_LONGCTX_RETRY_HINT = (
    "\n\n（注意：上一次输出的 JSON 不合格。请严格只输出 JSON："
    "必须含 citations 数组、每条 chapter 用整数、snippet 为原文逐字片段。）"
)

# v1 内联指令（先验证路由，prompt 正式化留给 PE）。要求输出与 loop / fast_path
# 同形的 {answer, citations[{chapter, snippet}]} JSON，好复用 parse_final_answer。
_LONGCTX_SYSTEM_INSTRUCTION = (
    "只根据这本书的原文回答，不用书外知识、不臆测、不编。\n"
    "严格输出 JSON（不要别的话）：\n"
    '{"answer": "你的分析", "citations": [{"chapter": 章节号整数, '
    '"snippet": "原文逐字片段，原样摘录不改写"}]}\n'
    "每个判断都要有 citation 支撑；snippet 必须是原文里逐字出现的句子。"
    "找不到原文依据的结论不要输出。"
)

def _resp_field(resp: Any, field: str) -> Any:
    """dict / 对象两种 response 形态统一取字段（同 fast_path._resp_field）。"""
    if resp is None:
        return None
    if isinstance(resp, dict):
        return resp.get(field)
    return getattr(resp, field, None)


def run_long_context(
    question: str,
    *,
    full_text: str,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    max_tokens: int = DEFAULT_LONGCTX_MAX_TOKENS,
    extra_system_prompt: str | None = None,
    session_id: str | None = None,
    on_event: LoopCallback | None = None,
) -> AgentQueryResult | None:
    """整本书进 context 跑一次 LLM 答题；失败返 ``None``（调用方回退 RAG）。

    Args:
        question: 用户题面（已做指代消解的 effective_question）。
        full_text: 整本书 cleaned 原文（``assembler._book_text.raw_text`` 等）。
        chunks: 全书 chunk dict 列表（含 ``chunk_id`` / ``chapter`` / ``text``），
            仅用于给 citation 做 ``verify_citations`` 证据。
        llm_client: duck-typed LLM client（同 AgentLoop / fast_path）。
        model: 模型名。
        max_tokens: 单次 LLM 调用 max_tokens。
        extra_system_prompt: 重答时的 reviewer 批评摘要等，拼在书之后（变化段，
            不破书的稳定前缀）。
        session_id: 给 L2 缓存用；None 时降级直调。
        on_event: 可选 streaming callback（emit IterationStart / FinalAnswer）。

    Returns:
        成功 :class:`AgentQueryResult`（``trace.outcome == "long_context_success"``）；
        任意失败 ``None``。
    """
    trace = LoopTrace(protocol_version="r2")
    start = time.monotonic()

    def _safe_emit(event: Any) -> None:
        if on_event is None:
            return
        try:
            on_event(event)
        except Exception:  # noqa: BLE001
            logger.exception("long_context on_event callback raised; suppressed")

    _safe_emit(IterationStartEvent(iteration=1, elapsed_ms=_elapsed_ms(start)))

    # book-first：前导 + 整本书构成跨功能稳定前缀（保 DeepSeek 前缀缓存），功能指令
    # 挪到书后；extra（reviewer 批评等变化段）再拼指令之后。
    system = build_longctx_system(
        full_text, _LONGCTX_SYSTEM_INSTRUCTION, suffix=extra_system_prompt
    )

    # 解析失败重试一次：纠正提示放 user 消息（不动 system 书前缀，保前缀缓存命中）。
    answer: str | None = None
    citations: list[dict] | None = None
    for attempt in range(1, _LONGCTX_MAX_ATTEMPTS + 1):
        user_content = question if attempt == 1 else question + _LONGCTX_RETRY_HINT
        try:
            response = _invoke_client(
                llm_client,
                model=model,
                system=system,
                tools=[],
                messages=[{"role": "user", "content": user_content}],
                max_tokens=max_tokens,
                cache_enabled=session_id is not None,
            )
        except Exception as exc:  # noqa: BLE001 — 传输层失败直接回退 RAG
            logger.warning(
                "long_context LLM call raised %s: %s; falling back to RAG",
                type(exc).__name__, exc,
            )
            return None

        input_tokens, output_tokens = llm_client.extract_usage_tokens(response)
        trace.total_input_tokens += input_tokens
        trace.total_output_tokens += output_tokens
        _usage = _resp_field(response, "usage")
        if _usage is not None:
            trace.cache_hit_tokens += int(
                _resp_field(_usage, "prompt_cache_hit_tokens") or 0
            )
            trace.cache_miss_tokens += int(
                _resp_field(_usage, "prompt_cache_miss_tokens") or 0
            )

        final_text = llm_client.extract_final_text(response)
        try:
            # lenient：chapter str→int 强转、坏 citation 单条丢（章号下面会被 chunk
            # 命中覆盖，严格 int 校验在长上下文路无意义）。
            answer, citations = parse_final_answer(final_text, lenient=True)
            break
        except Exception as exc:  # noqa: BLE001 — 解析失败：重试一次再回退 RAG
            logger.warning(
                "long_context parse failed (attempt %d/%d): %s",
                attempt, _LONGCTX_MAX_ATTEMPTS, exc,
            )
            if attempt >= _LONGCTX_MAX_ATTEMPTS:
                return None
    if answer is None or citations is None:
        return None

    # evidence-first：全书 chunks 当证据，snippet 匹配即 verified（章号漂移鲁棒）。
    evidence = {
        str(c["chunk_id"]): {"chapter": c.get("chapter", 0), "text": c.get("text", "")}
        for c in chunks
        if c.get("chunk_id")
    }
    citations = verify_citations(citations, evidence)

    # 章号纠偏（exp-009/010 caveat）：长上下文模型自报章号会漂，但 snippet verify
    # 命中的那个 chunk 才是它真实所在处——用命中 chunk 的真章号覆盖模型自报值，
    # 让显示 / 点击回跳的章号可信。未命中或章号未知（0）的不动，保留模型自报值。
    for cit in citations:
        cid = cit.get("chunk_id")
        if cid and cit.get("verified"):
            true_chapter = evidence.get(cid, {}).get("chapter")
            if isinstance(true_chapter, int) and true_chapter > 0:
                cit["chapter"] = true_chapter

    trace.iterations = 1
    trace.outcome = "long_context_success"
    trace.duration_ms = _elapsed_ms(start)

    _safe_emit(
        FinalAnswerEvent(
            answer=answer,
            citations=citations,
            iterations=trace.iterations,
            duration_ms=trace.duration_ms,
        )
    )
    return AgentQueryResult(answer=answer, citations=citations, trace=trace)


__all__ = ["run_long_context", "DEFAULT_LONGCTX_MAX_TOKENS"]
