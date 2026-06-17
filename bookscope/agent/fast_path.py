"""``fast_path`` —— 通识题快路径（Sprint 5 BE 第二项 deliverable）。

设计动机：通识题（"主要角色有哪几个" / "故事发生在哪个朝代" / "全书共
分几章"等）实际只需一次 ``search_chunks`` 加一次 LLM 综合作答即可，没
必要走完整 :class:`bookscope.agent.AgentLoop` 的多轮 tool dispatch。
完整 loop 在通识题上 dur 90-180s；fast path 目标 < 15 秒。

判定方式：题面关键词 + 长度启发式。**不**调一轮 LLM 做分类——那样反
而多一次 latency。诊断题（"主角性格转变是渐变还是硬扳" / "支线 A 的
高潮章在哪"）一律走完整 agent loop，保留多轮 tool 推理能力。

Fallback：fast path 任何环节出问题（search 抛错 / LLM 抛错 / LLM 输
出无法解析），:func:`run_fast_path` 返回 ``None``——调用方据此回退到完
整 ``AgentLoop``，保用户体验不破。

env 旁路：``BOOKSCOPE_FAST_PATH_DISABLED=1`` 强制 :func:`should_use_fast_path`
返回 False，全部走 agent_loop。用于启发式误判时一键回滚。
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Final, Literal

from bookscope.agent._internal.llm_cache import invoke_client_cached as _invoke_client
from bookscope.agent._internal.loop_shared import TOOL_NAME_SEARCH
from bookscope.agent._internal.loop_shared import elapsed_ms as _elapsed_ms
from bookscope.agent._internal.search_cache import search_chunks_cached
from bookscope.agent.citation_check import verify_citations
from bookscope.agent.events import (
    FinalAnswerEvent,
    IterationStartEvent,
    LoopCallback,
    RouteDecisionEvent,
    ToolResultEvent,
    ToolUseEvent,
)
from bookscope.agent.models import AgentQueryResult, LoopTrace
from bookscope.agent.tools import ChunkRetrievalBackend
from bookscope.agent.utils.json_parsing import (
    extract_first_json_object as _extract_first_json_object,
)
from bookscope.agent.utils.json_parsing import (
    strip_code_fence as _strip_code_fence,
)

logger = logging.getLogger(__name__)

# Sprint 5.5：fast 路径分四子类（通识 / 评论 / 摘要 / 评分），各自加载
# 专属 system prompt；保留旧 ``"fast"`` 字面量作向后兼容（route_question
# 不再返回它，但下游若仍传 ``"fast"`` 视同 ``"fast_general"``）。
RouteDecision = Literal[
    "fast_general",
    "fast_review",
    "fast_summary",
    "fast_rating",
    "agent_loop",
]

FAST_SUBROUTES: tuple[str, ...] = (
    "fast_general",
    "fast_review",
    "fast_summary",
    "fast_rating",
)

ENV_DISABLED = "BOOKSCOPE_FAST_PATH_DISABLED"

# 5 类路由的预期耗时区间（秒）——按当前 fast_path 实测体感给。FE 拿到
# 这两个数后用 min 做"正常进度"提示、用 max 做"超时风险"红线提示。
_ROUTE_EXPECTED_DURATION: Final[dict[str, tuple[int, int]]] = {
    "fast_general": (3, 12),
    "fast_review": (5, 15),
    "fast_summary": (5, 15),
    "fast_rating": (3, 10),
    "agent_loop": (30, 90),
}

# 5 类路由的中文人话标签——FE 直接显示。"深度题"对齐作者口语习惯，
# 不写"agent 回路"这种工程术语。
_ROUTE_HUMAN_LABEL: Final[dict[str, str]] = {
    "fast_general": "通识题",
    "fast_review": "评论题",
    "fast_summary": "摘要题",
    "fast_rating": "评分题",
    "agent_loop": "深度题",
}


def build_route_decision_event(route_type: str) -> RouteDecisionEvent:
    """按 ``route_type`` 字面量构造一个 :class:`RouteDecisionEvent`。

    供 ``run_fast_path`` 和 ``AgentLoop.query`` 复用——单一事实源，避免
    两处各自硬编码 duration 表。

    Args:
        route_type: :data:`RouteDecision` 5 类字面量之一。未知值兜底成
            ``agent_loop`` 的标签与时长——保 FE 永远收到合法事件。

    Returns:
        立即可 emit 的 :class:`RouteDecisionEvent` 实例。
    """
    label = _ROUTE_HUMAN_LABEL.get(route_type, _ROUTE_HUMAN_LABEL["agent_loop"])
    duration = _ROUTE_EXPECTED_DURATION.get(
        route_type, _ROUTE_EXPECTED_DURATION["agent_loop"]
    )
    return RouteDecisionEvent(
        route_type=route_type,  # type: ignore[arg-type]
        human_label=label,
        expected_duration_seconds_min=duration[0],
        expected_duration_seconds_max=duration[1],
    )

DEFAULT_FAST_PATH_TOP_K: int = 5
"""fast 路径 search_chunks 的 top_k；通识题 5 段原文足够支撑回答。"""

DEFAULT_FAST_PATH_MAX_TOKENS: int = 1500
"""fast 路径 LLM 单次调用的 max_tokens 上限。

通识题答复一般 1-2 段中文，1500 token 足够还能留 citation 余量。
小于 AgentLoop 默认 4000 是有意为之——通识题不需要长论证。
"""

# ---------------------------------------------------------------------------
# 启发式关键词清单
# ---------------------------------------------------------------------------

# 列举类 / 通识类信号词：题面里出现这些 → 倾向 fast_general
# 注：原 "讲的是" / "讲了什么" / "讲什么" / "主题是" / "是关于" 已移到
# REVIEW_KEYWORDS——评论题路由优先级高于通识。
ENUMERATION_KEYWORDS: tuple[str, ...] = (
    "几个",
    "哪些",
    "哪几",
    "几位",
    "几章",
    "共有",
    "总共",
    "主要角色",
    "主要人物",
    "主角是谁",
    "主人公是谁",
    "故事发生",
    "什么时代",
    "哪个朝代",
    "什么朝代",
    "背景是",
    "什么类型",
    "属于什么",
    "作者是",
    "什么书",
)

# 评论类信号词：题面问"这本书在写什么 / 作者想表达什么"——给观点不给摘要
REVIEW_KEYWORDS: tuple[str, ...] = (
    "讲了什么",
    "讲的是",
    "讲什么",
    "整本书是关于",
    "整本书在",
    "本书在",
    "本书写",
    "作者想表达",
    "作者想说",
    "作者要表达",
    "主题是",
    "核心是",
    "本质是",
    "在写什么",
    "是关于",
    "想传达",
)

# 摘要类信号词：题面要一份带节点的故事梗概
SUMMARY_KEYWORDS: tuple[str, ...] = (
    "概括",
    "梗概",
    "全书内容",
    "故事梗概",
    "故事情节",
    "故事讲",
    "讲了一个",
    "情节概要",
    "内容简介",
    "整本书讲了",
)

# 评分类信号词：题面要"值不值得 / 怎么样 / 推荐吗"
RATING_KEYWORDS: tuple[str, ...] = (
    "怎么样",
    "值不值得",
    "值得看",
    "值得读",
    "推荐吗",
    "推荐么",
    "好书吗",
    "好看吗",
    "写得好",
    "写得怎么",
    "如何评价",
)

# 诊断类 / 判断类信号词：短题（< LENGTH_THRESHOLD_FAST）出现这些 → agent_loop
# 砍 5 类到 2 类后这是兜底短深题的关键——"作者最强的论点是什么？"12 字也是深题
DIAGNOSTIC_KEYWORDS: tuple[str, ...] = (
    "分析",
    "评估",
    "评价",
    "判断",
    "是否",
    "为何",
    "为什么",
    "怎么看",
    "如何看",
    "怎么",
    "如何",
    "渐变",
    "硬扳",
    "铺垫",
    "节奏",
    "支线",
    "伏笔",
    "转变",
    "漂移",
    "对比",
    "比较",
    "异同",
    "相比",
    "一致还是",
    "矛盾",
    "冲突",
    "高潮章",
    "高潮在",
    "动机",
    "权衡",
    "弧光",
    "塑造",
    "论点",
    "最强",
    "意外",
    "独到",
)

LENGTH_THRESHOLD_FAST: int = 30
"""题面字符长度阈值（不含空白）；< 此值才考虑 fast 路径。"""


def should_use_fast_path() -> bool:
    """全局开关检查。env ``BOOKSCOPE_FAST_PATH_DISABLED=1`` → False。"""
    return os.environ.get(ENV_DISABLED, "").strip() != "1"


def _route_question(question: str) -> RouteDecision:
    """启发式分类一道题该走哪条路径。

    路由判定只产生两类：``"fast_general"`` 或 ``"agent_loop"``。
    RouteDecision Literal 仍保留 5 种值（contract 兼容已发出的
    RouteDecisionEvent / FE emoji 表），但当前路由不再细分
    review / summary / rating——这三类的题统统按"短不深"走
    fast_general、按"短带诊断词"走 agent_loop，作者明确反馈"关
    键词区分很差"。

    判定顺序（命中即返回）：

    1. 题面长度 ≥ :data:`LENGTH_THRESHOLD_FAST` → ``"agent_loop"``。
       字数是主信号——长题一律深查。
    2. 含任一 :data:`DIAGNOSTIC_KEYWORDS` → ``"agent_loop"``。短题
       兜底——"作者最强论点"这种 12 字短深题靠诊断词捕住。
    3. 兜底 → ``"fast_general"``。短题无诊断词 = 普通通识题。

    Args:
        question: 用户原始题面。

    Returns:
        :data:`RouteDecision` —— ``"fast_general"`` 或 ``"agent_loop"``。
    """
    stripped = re.sub(r"\s+", "", question)

    if len(stripped) >= LENGTH_THRESHOLD_FAST:
        return "agent_loop"

    for kw in DIAGNOSTIC_KEYWORDS:
        if kw in stripped:
            return "agent_loop"

    return "fast_general"


def route_question(question: str) -> RouteDecision:
    """对外暴露的路由判定。考虑 env 开关；env 关 → 一律 ``agent_loop``。"""
    if not should_use_fast_path():
        return "agent_loop"
    return _route_question(question)


# ---------------------------------------------------------------------------
# fast path system prompt —— v1 兜底 + Sprint 5.5 四类专属模板
# ---------------------------------------------------------------------------

_FAST_PATH_SYSTEM_PROMPT = (
    "你是 BookScope 的快速答复助手。用户问了一道通识类问题——"
    "你会拿到从原书中检索出的若干原文片段，请直接综合作答。\n\n"
    "**硬性约束**：\n"
    "1. 只能基于提供的原文片段作答；片段里没有的信息不要编。\n"
    "2. 答复用 1-2 段简练中文，不要堆砌。\n"
    "3. 输出必须是合法 JSON 对象，结构为：\n"
    '   {"answer": "...", "citations": [{"chapter": <int>, "snippet": "..."}, ...]}\n'
    "4. citations 至少 1 条；snippet 必须从给定原文片段中原样取一句或一段，"
    "不要改写或翻译。\n"
    "5. 不要包裹 markdown 代码围栏，直接输出 JSON。\n"
)
"""v1 兜底 system prompt。subroute 文件读不到时回退到这条。"""

# 4 类专属 prompt 文件路径——以本模块所在目录为锚定，跟 prompts/ 同包
_FAST_PATH_PROMPTS_DIR: Path = Path(__file__).resolve().parent / "prompts" / "fast_path"

_FAST_PATH_PROMPT_PATHS: dict[str, Path] = {
    "fast_general": _FAST_PATH_PROMPTS_DIR / "fast_path_general_v1.md",
    "fast_review": _FAST_PATH_PROMPTS_DIR / "fast_path_review_v1.md",
    "fast_summary": _FAST_PATH_PROMPTS_DIR / "fast_path_summary_v1.md",
    "fast_rating": _FAST_PATH_PROMPTS_DIR / "fast_path_rating_v1.md",
}

# 进程级缓存——第一次读盘后缓存到 dict，避免每次请求都 IO
_PROMPT_CACHE: dict[str, str] = {}


def _load_subroute_prompt(subroute: str) -> str:
    """按 subroute 加载对应 system prompt；读不到 / 未知子类回退到 v1 兜底。

    向后兼容：``"fast"`` 视同 ``"fast_general"``。

    Args:
        subroute: :data:`RouteDecision` 中的 fast 子类字面量。

    Returns:
        prompt 文本。任何异常（路径不存在 / 解码失败）→ 回退 v1 兜底。
    """
    if subroute == "fast":  # 向后兼容旧接口
        subroute = "fast_general"
    if subroute in _PROMPT_CACHE:
        return _PROMPT_CACHE[subroute]
    path = _FAST_PATH_PROMPT_PATHS.get(subroute)
    if path is None:
        logger.warning(
            "fast_path: unknown subroute %r; using v1 fallback prompt", subroute
        )
        return _FAST_PATH_SYSTEM_PROMPT
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning(
            "fast_path: failed reading prompt %s: %s; using v1 fallback",
            path,
            exc,
        )
        return _FAST_PATH_SYSTEM_PROMPT
    _PROMPT_CACHE[subroute] = text
    return text


def _build_chunks_prompt(
    question: str,
    chunk_dicts: list[dict[str, Any]],
) -> str:
    """把检索到的 chunk 拼成一段提示文本。"""
    lines: list[str] = ["以下是从原书检索出的原文片段："]
    for idx, c in enumerate(chunk_dicts, start=1):
        chapter = c.get("chapter", 0)
        text = c.get("text", "")
        lines.append(f"\n[片段{idx}｜章 {chapter}] {text}")
    lines.append(f"\n---\n用户问题：{question}\n请按 system prompt 要求回答。")
    return "\n".join(lines)


def _parse_fast_path_answer(
    text: str,
    fallback_chunks: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    """解析 LLM 输出。失败时降级用题面 chunk 自动拼 citation。

    返回 ``(answer, citations)``。任意环节失败 → 抛 ``ValueError``。
    """
    raw = text.strip()
    if not raw:
        raise ValueError("LLM fast-path response was empty")
    candidate = _strip_code_fence(raw)
    try:
        obj = json.loads(candidate)
    except json.JSONDecodeError:
        sliced = _extract_first_json_object(candidate)
        if sliced is None:
            raise ValueError("fast-path response not valid JSON") from None
        obj = json.loads(sliced)
    if not isinstance(obj, dict):
        raise ValueError("fast-path JSON not an object")
    answer = obj.get("answer")
    citations = obj.get("citations")
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("fast-path missing/empty 'answer'")
    if not isinstance(citations, list) or len(citations) == 0:
        # 降级：从 fallback_chunks 自动拼一条 citation。
        # WP1：auto_filled=True 明示这条是系统定位的，不伪装成 LLM 引用。
        if not fallback_chunks:
            raise ValueError("fast-path no citations and no fallback chunks")
        first = fallback_chunks[0]
        citations = [
            {
                "chapter": int(first.get("chapter", 1)),
                "snippet": str(first.get("text", ""))[:200],
                "auto_filled": True,
            }
        ]
    # 校验每条 citation 形态
    cleaned: list[dict[str, Any]] = []
    for cit in citations:
        if not isinstance(cit, dict):
            continue
        ch = cit.get("chapter")
        sn = cit.get("snippet")
        if not isinstance(ch, int) or not isinstance(sn, str) or not sn:
            continue
        kept = {"chapter": ch, "snippet": sn}
        if cit.get("auto_filled"):
            kept["auto_filled"] = True
        cleaned.append(kept)
    if not cleaned:
        raise ValueError("fast-path citations all malformed")
    return answer.strip(), cleaned


def run_fast_path(
    question: str,
    *,
    search_backend: ChunkRetrievalBackend,
    llm_client: Any,
    model: str,
    max_tokens: int = DEFAULT_FAST_PATH_MAX_TOKENS,
    top_k: int = DEFAULT_FAST_PATH_TOP_K,
    on_event: LoopCallback | None = None,
    subroute: str = "fast_general",
    extra_system_prompt: str | None = None,
    session_id: str | None = None,
) -> AgentQueryResult | None:
    """对题面跑一次"1 search + 1 LLM call"快路径；失败返 ``None``。

    设计契约：

    - 返回 :class:`AgentQueryResult`，``trace.outcome == "fast_path_success"``，
      ``trace.iterations == 1``，``trace.tool_calls`` 含一条 search 调用记录。
    - 任意环节抛错（search 异常 / LLM 异常 / 解析失败）一律捕获并返回
      ``None``，不向上抛——调用方根据 None 回退到完整 ``AgentLoop``。
    - ``on_event`` callback 同 AgentLoop 的语义：emit ``IterationStartEvent``
      / ``ToolUseEvent`` / ``ToolResultEvent`` / ``FinalAnswerEvent`` 让 SSE
      端点能统一处理。callback 异常吞掉记日志。

    Args:
        question: 用户原始题面。
        search_backend: 实现 ``ChunkRetrievalBackend`` 的检索后端。
        llm_client: duck-typed LLM client（同 ``AgentLoop``）。
        model: LLM 模型名。
        max_tokens: 单次 LLM 调用的 max_tokens。
        top_k: search_chunks 的 top_k；默认 5。
        on_event: 可选 streaming callback。
        subroute: fast 子类字面量（``fast_general`` / ``fast_review`` /
            ``fast_summary`` / ``fast_rating``）。决定加载哪份 system prompt。
            未知值 / 读盘失败时静默回退到 v1 兜底 prompt。

    Returns:
        成功时 :class:`AgentQueryResult`；任何失败 ``None``。
    """
    # Sprint 7（2026-05-15）r1 退役后 fast_path 唯一上报 r2。原本读
    # BOOKSCOPE_AGENT_PROTOCOL 做 r1/r2 双轨的兜底逻辑没意义了——同
    # `_select_agent_loop_class` 一起删；env 设为 r1 现在会在那里抛 RuntimeError。
    trace = LoopTrace(protocol_version="r2")
    start = time.monotonic()

    def _safe_emit(event: Any) -> None:
        if on_event is None:
            return
        try:
            on_event(event)
        except Exception:  # noqa: BLE001
            logger.exception("fast_path on_event callback raised; suppressed")

    # Sprint：RouteDecisionEvent 必须比 IterationStartEvent 早。FE 拿到这帧
    # 就立刻显示"评论题，预计 5-15 秒"，让等待有方向感——比一通 spinner
    # 转着不告知任何信息要友好得多。
    _safe_emit(build_route_decision_event(subroute))

    _safe_emit(
        IterationStartEvent(iteration=1, elapsed_ms=_elapsed_ms(start))
    )

    # ---- Step 1: search ----
    search_input = {
        "query": question,
        "chapter_scope": None,
        "character_filter": None,
        "top_k": top_k,
    }
    _safe_emit(
        ToolUseEvent(
            tool_name=TOOL_NAME_SEARCH,
            tool_input=search_input,
            tool_use_id=None,
            iteration=1,
            elapsed_ms=_elapsed_ms(start),
        )
    )
    search_call_start = time.monotonic()
    try:
        # Sprint 8 W1：走 L1 缓存 wrapper；session_id=None 时降级直调。
        matches = search_chunks_cached(
            search_backend,
            session_id=session_id,
            query=question,
            chapter_scope=None,
            character_filter=None,
            top_k=top_k,
        )
    except Exception as exc:  # noqa: BLE001 — 显式包死，触发 fallback
        logger.warning(
            "fast_path search backend raised %s: %s; falling back to agent_loop",
            type(exc).__name__,
            exc,
        )
        _safe_emit(
            ToolResultEvent(
                tool_name=TOOL_NAME_SEARCH,
                output_summary=f"error: {type(exc).__name__}: {exc}",
                status="error",
                attempt=1,
                elapsed_ms=_elapsed_ms(search_call_start),
                error_message=f"{type(exc).__name__}: {exc}",
            )
        )
        return None

    chunk_dicts = [m.model_dump() for m in matches]
    search_elapsed = _elapsed_ms(search_call_start)
    output_summary = f"list[{len(chunk_dicts)}]"
    trace.tool_calls.append(
        {
            "tool_name": TOOL_NAME_SEARCH,
            "input": search_input,
            "output_summary": output_summary,
            "elapsed_ms": search_elapsed,
            "attempt": 1,
            "status": "ok",
        }
    )
    _safe_emit(
        ToolResultEvent(
            tool_name=TOOL_NAME_SEARCH,
            output_summary=output_summary,
            status="ok",
            attempt=1,
            elapsed_ms=search_elapsed,
        )
    )

    if not chunk_dicts:
        # 没检索到任何片段 → fast path 无以为继，回退到 agent_loop
        logger.info("fast_path: empty search result; falling back to agent_loop")
        return None

    # ---- Step 2: 1 次 LLM call ----
    user_prompt = _build_chunks_prompt(question, chunk_dicts)
    messages = [{"role": "user", "content": user_prompt}]
    system_prompt = _load_subroute_prompt(subroute)
    # 重答时 routes 层传入上次 reviewer 批评摘要——直接拼到 subroute
    # 的 system prompt 末尾，让 fast path generator 也能消费批评。
    if extra_system_prompt:
        system_prompt = system_prompt + "\n\n" + extra_system_prompt
    try:
        # Sprint 8 W2：L2 LLM 缓存只在拿到 session_id 时启用——与 L1 同
        # gate；测试 mock 普遍不传 session_id，零侵入。
        response = _invoke_client(
            llm_client,
            model=model,
            system=system_prompt,
            tools=[],  # fast path 不开 tool use
            messages=messages,
            max_tokens=max_tokens,
            cache_enabled=session_id is not None,
        )
    except Exception as exc:  # noqa: BLE001 — 包死触发 fallback
        logger.warning(
            "fast_path LLM call raised %s: %s; falling back to agent_loop",
            type(exc).__name__,
            exc,
        )
        return None

    # 累计 tokens——Backlog B-1（2026-05-15）后由 adapter 自己按 provider 形态
    # 实现 extract_usage_tokens；fast_path 拿 client.extract_usage_tokens 即可，
    # 不再做 r1/r2 形态 sniffing。
    input_tokens, output_tokens = llm_client.extract_usage_tokens(response)
    trace.total_input_tokens += input_tokens
    trace.total_output_tokens += output_tokens
    # DeepSeek 缓存命中观测——与 loop_r2._accumulate_tokens 一致。快路径
    # 之前漏累计，导致走 fast_path 的题 trace 缓存命中恒 0（实际已命中）。
    _usage = _resp_field(response, "usage")
    if _usage is not None:
        trace.cache_hit_tokens += int(
            _resp_field(_usage, "prompt_cache_hit_tokens") or 0
        )
        trace.cache_miss_tokens += int(
            _resp_field(_usage, "prompt_cache_miss_tokens") or 0
        )

    # 抽出最终文本——adapter 按自己形态实现，r2 真实 adapter 走
    # choices[0].message.content；测试 fake 按 r1 content block 形态实现
    # 自己版本，零 sniffing 残留。
    final_text = llm_client.extract_final_text(response)

    try:
        answer, citations = _parse_fast_path_answer(final_text, chunk_dicts)
    except ValueError as exc:
        logger.warning(
            "fast_path parse failed: %s; falling back to agent_loop",
            exc,
        )
        return None

    # WP1：fast path 的候选证据就是这一次 search 的结果——按 chunk_id
    # 登记后给每条 citation 附加 verified / chunk_id / match_score。
    # auto_filled 的那条文本本来取自 chunk，verified 自然为 true。
    evidence = {
        str(c["chunk_id"]): {"chapter": c.get("chapter", 0), "text": c.get("text", "")}
        for c in chunk_dicts
        if c.get("chunk_id")
    }
    citations = verify_citations(citations, evidence)

    trace.iterations = 1
    trace.outcome = "fast_path_success"
    trace.duration_ms = _elapsed_ms(start)

    _safe_emit(
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


def _resp_field(resp: Any, field: str) -> Any:
    """对 dict / 对象两种 response 形态统一取字段（同 loop._resp_field）。"""
    if resp is None:
        return None
    if isinstance(resp, dict):
        return resp.get(field)
    return getattr(resp, field, None)


__all__ = [
    "DEFAULT_FAST_PATH_MAX_TOKENS",
    "DEFAULT_FAST_PATH_TOP_K",
    "ENV_DISABLED",
    "FAST_SUBROUTES",
    "RouteDecision",
    "build_route_decision_event",
    "route_question",
    "run_fast_path",
    "should_use_fast_path",
]
