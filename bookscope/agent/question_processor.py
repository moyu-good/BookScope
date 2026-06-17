"""问题处理引擎 —— 长题进 agent_loop 前的预处理。

设计动机（作者反馈）："字数越长你就需要整理问题，需要一个问题的处理
引擎，然后继续处理才对。"

长题（≥ 30 字）往往含多个子问、指代不清、或跨章节。直接丢给 agent_loop
会让 LLM 检索时迷路，绕一堆 tool 调用还不一定收敛。在 ``query`` 入口
前先做一次轻量 LLM 拆题：

1. 把题拆成 1-3 个独立可查的子问
2. 推荐章节范围（题指向具体章 / 跨章铺垫 / 全书）
3. 评估难度 simple / medium / complex

输出以 ``ProcessedQuestion`` dataclass 返回；调用方把子问作为 system
context addendum 注入主 loop。

### 兜底原则

processor 整段 try/except 包死——LLM 调用失败、JSON 解析失败、超时、
字段非法，**一律返回 fallback** ``ProcessedQuestion``（subquestions=
[original]、recommended_chapters=None、difficulty="medium"）。

不阻断 agent_loop 主流程是硬约束：processor 是锦上添花的预处理，不是
关键路径。挂了就当没跑过，原题照样进 agent_loop。
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal, Protocol

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

DEFAULT_MODEL: str | None = None
"""processor 默认 model——None 表示沿用调用方传进来的 client 的默认。

之所以不写死具体模型名：BookScope 是 provider-agnostic 的，processor
用什么模型由上层路由决定。本模块只接 LLMClient Protocol。"""

_PROCESSOR_TEMPERATURE: float = 0.0
"""题型分类温度。DeepSeek 官方调教表：结构化判断类用 0.0 求确定性。"""

DEFAULT_TIMEOUT_SECONDS: float = 10.0
"""processor 单次调用超时。设 10s——长于这个时间不如直接 fallback，
不能让预处理把整个 query 拖死。"""

DEFAULT_MAX_TOKENS: int = 2048
"""processor max_tokens。

deepseek-v4-flash 是 reasoning model——``max_tokens`` 把 ``reasoning_content``
一起算进预算。拆题这步的 reasoning 实测要 590~800+ token，再叠上 JSON 正文
~150 token，原来的 800 根本不够：reasoning 还没想完就撞上限，``finish_reason``
返 ``length``、正文 ``content`` 返空串，processor 只能 fallback。

exp008 烟测复现：800 时同一道伏笔题 3 次跑有 2 次 reasoning 直接吃满 800、
content 返空。调到 2048 给 reasoning 留够余地，正文 JSON 才有空间吐出来。
这是 reasoning model 的通病，跟 ``REWRITE_MAX_TOKENS`` 同一个根（那条已因同样
原因从 300 调到 800）。"""

MAX_SUBQUESTIONS: int = 3
"""子问数量上限——超过截断到前 3 个。prompt 里也说了限制，这里是兜底。"""

PROMPT_PATH: Path = (
    Path(__file__).parent / "prompts" / "question_processor_v1.md"
)

# ---------------------------------------------------------------------------
# 指代消解（ADR-009 Phase 1b，D-2）
# ---------------------------------------------------------------------------

REWRITE_PROMPT_PATH: Path = (
    Path(__file__).parent / "prompts" / "question_processor_v2.md"
)
"""追问改写 prompt。v1 管单轮拆题不动，v2 单独管多轮指代消解——两件不同
的活分两份 prompt，v1 的 schema 与单轮行为保持逐字节不变（同 loop / rubric
的版本对照纪律）。"""

REWRITE_MAX_TOKENS: int = 800
"""改写只输出一句话，但 deepseek-v4-flash 有 reasoning，思考会先吃 token。
2026-06-11 真实 3 轮追问链验收发现：300 token 时第三问"综合前面"这类
改写偶发 fallback（reasoning 吃光预算、正文返空 → response missing
content）。调到 800（与拆题同档）给 reasoning 留余地，消除间歇 fallback。"""

REWRITE_HISTORY_MAX_TURNS: int = 3
"""改写时最多看上几轮——指代基本指向最近一两轮，喂太多反而稀释重点
且涨 token。"""

REWRITE_HISTORY_ANSWER_MAX_CHARS: int = 400
"""每轮答案截断长度——改写只需要答案大意定位指代，不需要全文。"""

_VALID_DIFFICULTIES: frozenset[str] = frozenset({"simple", "medium", "complex"})


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class _LLMClientLike(Protocol):
    """processor 期望的 client 形态——与 ``agent.adapters.base.LLMClient`` 同形。

    刻意复述一份避免循环 import；运行期不强制 isinstance 校验。
    """

    def messages_create(
        self,
        *,
        model: str,
        system: str,
        tools: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        max_tokens: int,
    ) -> Any: ...


# ---------------------------------------------------------------------------
# 输出 dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProcessedQuestion:
    """问题处理结果。

    Attributes:
        original_question: 用户原题。
        subquestions: 拆出的 1-3 个子问；fallback 时为 ``[original]``。
        recommended_chapters: 推荐查询章节升序数组；``None`` 表示全书。
        difficulty: 用户视角难度评估。
        processing_duration_seconds: processor 调用耗时。fallback 时 0.0。
        rewritten_question: 追问指代消解后的独立化问题（ADR-009 Phase 1b）。
            ``None`` = 单轮 / 没改写（无对话历史，或改写失败 fallback 用原题）。
            非 None 时是"不看历史也能独立读懂"的完整问题，喂给检索与路由。
    """

    original_question: str
    subquestions: list[str] = field(default_factory=list)
    recommended_chapters: list[int] | None = None
    difficulty: Literal["simple", "medium", "complex"] = "medium"
    processing_duration_seconds: float = 0.0
    rewritten_question: str | None = None


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def process_question(
    question: str,
    client: Any,
    *,
    model: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    conversation_history: list[dict] | None = None,
) -> ProcessedQuestion:
    """长题预处理：拆子问 + 推荐章节 + 评难度（多轮时先做指代消解）。

    Args:
        question: 用户原题。
        client: LLMClient 风格 client（有 ``messages_create`` 方法）；为兼容
            老 ``.messages.create(...)`` duck-typed client 也走兜底。
        model: 覆盖 model 名；None 时由调用方 client 自决（通常是 client
            实例化时的默认）。
        timeout: 单次调用超时秒数。本函数自己**不**强制 timeout——交给
            上层 client 的 transport 层处理；这里保留参数只是为了 trace /
            未来扩展。
        conversation_history: 上几轮的问答（ADR-009 Phase 1b）。每条形如
            ``{"question": ..., "answer": ...}``（对齐 conversation_store 存的
            turns 结构）。**有历史**时先把当前追问改写成独立可查的完整问题，
            改写结果填进 ``rewritten_question`` 并据此拆子问；**无历史 / None**
            时行为与单轮完全一致，``rewritten_question`` 留 None（零回归）。

    Returns:
        ``ProcessedQuestion``。失败一律 fallback，**不抛异常**——processor
        是预处理，不能阻断主流程。
    """
    start = time.monotonic()

    # ADR-009 Phase 1b：有对话历史先做指代消解，把残句追问改写成独立问题。
    # 改写失败回退原题（rewrite_followup 内部已兜底返 None）。后续拆题、
    # 推荐章节、难度评估都基于这句独立化的问题——一处改写三处受益。
    rewritten = rewrite_followup(
        question, client, model=model, conversation_history=conversation_history
    )
    effective_question = rewritten if rewritten is not None else question

    try:
        system_prompt = _load_prompt()
        response = _invoke_processor_client(
            client,
            model=model,
            system=system_prompt,
            user_message=effective_question,
            max_tokens=DEFAULT_MAX_TOKENS,
        )
        raw_text = _extract_text(response)
        parsed = _parse_processor_json(raw_text)
        subquestions, recommended_chapters, difficulty = _sanitize_fields(
            parsed,
            original=effective_question,
        )
        duration = time.monotonic() - start
        return ProcessedQuestion(
            original_question=question,
            subquestions=subquestions,
            recommended_chapters=recommended_chapters,
            difficulty=difficulty,
            processing_duration_seconds=duration,
            rewritten_question=rewritten,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "question_processor fallback: %s: %s",
            type(exc).__name__,
            exc,
        )
        fallback = _build_fallback(question)
        # 拆题挂了，但改写若成功仍带回——检索 / 路由还能用上独立化的问题。
        if rewritten is not None:
            fallback = replace(fallback, rewritten_question=rewritten)
        return fallback


def rewrite_followup(
    question: str,
    client: Any,
    *,
    model: str | None = None,
    conversation_history: list[dict] | None = None,
) -> str | None:
    """把带指代的追问改写成不看历史也能独立读懂的完整问题（ADR-009 D-2）。

    检索层（BM25 / 向量搜索）和路由判断都看不见对话历史，"具体哪几章最稀"
    这种残句直接丢给它们会查歪。这里凭上几轮的问答把指代和省略补全，让
    改写后的独立问题同时喂给检索、路由、登记表。

    Args:
        question: 当前这一问（可能带指代）。
        client: 同 ``process_question`` 的 LLMClient 风格 client。
        model: 覆盖 model 名。
        conversation_history: 上几轮问答，每条 ``{"question", "answer"}``。

    Returns:
        改写后的独立问题字符串；**没历史可参照 / 改写失败 / 改写结果为空**
        一律返回 ``None``——表示"按原题处理"。**不抛异常**：改写是锦上添花，
        挂了就当没改写，原题照样往下走（D-2 兜底原则）。
    """
    recent = _recent_history(conversation_history)
    if not recent:
        return None
    try:
        system_prompt = _load_rewrite_prompt()
        user_message = _build_rewrite_user_message(question, recent)
        response = _invoke_processor_client(
            client,
            model=model,
            system=system_prompt,
            user_message=user_message,
            max_tokens=REWRITE_MAX_TOKENS,
        )
        rewritten = _extract_text(response).strip()
        rewritten = _clean_rewrite_output(rewritten)
        if not rewritten:
            return None
        return rewritten
    except Exception as exc:  # noqa: BLE001 — 改写失败不阻断主流程
        logger.warning(
            "followup rewrite fallback（用原题）: %s: %s",
            type(exc).__name__,
            exc,
        )
        return None


def build_system_addendum(processed: ProcessedQuestion) -> str:
    """根据 processor 结果生成 system prompt 拼接段。

    被 agent_loop 在 query 入口处拼到 ``system_prompt`` 后面，提示 LLM
    用户实际想查什么。fallback 情况下（subquestions == [original]、
    recommended_chapters is None）依然 emit 一个简短段——避免主 loop
    判断 fallback 状态。

    Returns:
        多行字符串，开头有换行；调用方直接 ``system + addendum``。
    """
    lines: list[str] = ["", "---", "## 问题处理引擎的预拆解"]
    if len(processed.subquestions) > 1:
        lines.append("用户原题已被拆成以下子问，按需依次查证：")
        for i, sq in enumerate(processed.subquestions, 1):
            lines.append(f"{i}. {sq}")
    else:
        lines.append(f"用户问题：{processed.subquestions[0]}")
    if processed.recommended_chapters:
        chapters_str = ", ".join(str(c) for c in processed.recommended_chapters)
        lines.append(f"推荐优先查询章节：第 {chapters_str} 章。")
    lines.append(f"难度评估：{processed.difficulty}。")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# 内部 helper
# ---------------------------------------------------------------------------


def _load_prompt() -> str:
    """读 prompt 文件；缺失直接抛——由外层 try 兜底 fallback。"""
    return PROMPT_PATH.read_text(encoding="utf-8")


def _load_rewrite_prompt() -> str:
    """读追问改写 prompt（v2）；缺失直接抛——由外层 try 兜底返 None。"""
    return REWRITE_PROMPT_PATH.read_text(encoding="utf-8")


def _recent_history(conversation_history: list[dict] | None) -> list[dict]:
    """从对话历史里取最近几轮有效问答，供改写参照。

    - None / 空 → 空列表（无历史 = 不改写，process_question 走单轮零回归路）。
    - 非 list、或元素不是带 question/answer 的 dict 一律过滤掉。
    - 只保留最近 ``REWRITE_HISTORY_MAX_TURNS`` 轮——指代基本指向最近一两轮。
    """
    if not isinstance(conversation_history, list):
        return []
    valid: list[dict] = []
    for turn in conversation_history:
        if not isinstance(turn, dict):
            continue
        q = str(turn.get("question") or "").strip()
        a = str(turn.get("answer") or "").strip()
        if not q and not a:
            continue
        valid.append({"question": q, "answer": a})
    return valid[-REWRITE_HISTORY_MAX_TURNS:]


def _build_rewrite_user_message(question: str, recent: list[dict]) -> str:
    """把历史问答 + 当前追问拼成改写 prompt 的 user message。

    答案按 ``REWRITE_HISTORY_ANSWER_MAX_CHARS`` 截断——改写只需要大意定位
    指代，不需要全文。
    """
    lines: list[str] = ["对话历史（从早到晚）："]
    for turn in recent:
        q = turn["question"]
        a = turn["answer"]
        if len(a) > REWRITE_HISTORY_ANSWER_MAX_CHARS:
            a = a[:REWRITE_HISTORY_ANSWER_MAX_CHARS] + "…"
        if q:
            lines.append(f"> 问：{q}")
        if a:
            lines.append(f"> 答：{a}")
        lines.append("")
    lines.append("这一问：")
    lines.append(f"> {question}")
    lines.append("")
    lines.append("请只输出改写后的那一句独立完整问题。")
    return "\n".join(lines)


def _clean_rewrite_output(text: str) -> str:
    """清掉模型偶尔多嘴的包装——代码围栏、"改写为："前缀、首尾引号。

    改写 prompt 已经要求只输出一行纯文本，这里只做轻量兜底，命不中就原样
    返回。多行时取第一非空行（模型偶尔会附一句解释）。
    """
    raw = text.strip()
    if raw.startswith("```"):
        body = raw.splitlines()
        if len(body) >= 2 and body[-1].strip().startswith("```"):
            raw = "\n".join(body[1:-1]).strip()
    # 取第一非空行——附带解释的情况下问题本身在第一行
    for line in raw.splitlines():
        candidate = line.strip()
        if candidate:
            raw = candidate
            break
    for prefix in ("改写为：", "改写为:", "改写后：", "改写后:", "输出："):
        if raw.startswith(prefix):
            raw = raw[len(prefix):].strip()
    raw = raw.strip("　 ").strip("“”\"'「」")
    return raw.strip()


def _build_fallback(question: str) -> ProcessedQuestion:
    """统一构造 fallback ProcessedQuestion。"""
    return ProcessedQuestion(
        original_question=question,
        subquestions=[question],
        recommended_chapters=None,
        difficulty="medium",
        processing_duration_seconds=0.0,
    )


def _invoke_processor_client(
    client: Any,
    *,
    model: str | None,
    system: str,
    user_message: str,
    max_tokens: int,
) -> Any:
    """调一次 LLM。兼容 LLMClient Protocol 与老 ``.messages.create(...)``。

    与 ``loop._invoke_client`` 同套兼容逻辑；不复用是为了避免 processor
    反向 import loop 形成依赖回路。
    """
    messages = [{"role": "user", "content": user_message}]
    effective_model = model if model is not None else "deepseek-v4-flash"
    if hasattr(client, "messages_create"):
        return client.messages_create(
            model=effective_model,
            system=system,
            tools=[],
            messages=messages,
            max_tokens=max_tokens,
            # 题型分类是结构化判断——按 DeepSeek 官方调教表用 0.0 求确定性，
            # 同一道题反复跑应路由到同一题型。
            temperature=_PROCESSOR_TEMPERATURE,
        )
    return client.messages.create(
        model=effective_model,
        system=system,
        tools=[],
        messages=messages,
        max_tokens=max_tokens,
    )


def _extract_text(response: Any) -> str:
    """从 LLM response 抽出文本，两种形态都接。

    r2 默认 protocol 下 DeepSeek 系 adapter 返回 OpenAI 原生形态
    （``choices[0].message.content`` 字符串）；Anthropic adapter 与历史
    桩返回 Anthropic 形态（``content`` 是 text block 列表）。两种都要兜住，
    否则 processor / 追问改写在生产（DeepSeek）一律拿不到文本只能 fallback。

    response 形态宽容：dict / SDK 对象都接；两种形态都抽不出文本则抛
    ValueError 让上层 fallback。
    """
    # OpenAI 形态优先：choices[0].message.content（r2 生产默认）
    openai_text = _extract_openai_text(response)
    if openai_text is not None:
        return openai_text

    # choices 在、但 message.content 为空：reasoning model（flash）把
    # max_tokens 吃光（finish_reason=length），正文返空串/None。单独报这个
    # 真根因——之前一律报 "missing choices and content"，choices 明明在，
    # 会把排查带去 adapter 形态方向（exp008 烟测就被这条假错误带歪过）。
    # 治本在 DEFAULT_MAX_TOKENS / REWRITE_MAX_TOKENS 给够预算，这里只是把
    # 错因说准，方便 fallback 日志一眼看出是 token 截断不是响应畸形。
    if _has_openai_choices(response):
        raise ValueError(
            "OpenAI choices 在但 message.content 为空——"
            "多半是 reasoning model 推理吃光 max_tokens 被截断（finish_reason=length）"
        )

    # Anthropic 形态：content 是 text block 列表
    content = _resp_field(response, "content")
    if content is None:
        raise ValueError("response missing both 'choices' and 'content' fields")
    if not isinstance(content, list):
        content = [content]
    parts: list[str] = []
    for block in content:
        if _block_type(block) == "text":
            text = _block_field(block, "text")
            if isinstance(text, str):
                parts.append(text)
    if not parts:
        raise ValueError("response contains no text block")
    return "\n".join(parts).strip()


def _extract_openai_text(response: Any) -> str | None:
    """抽 OpenAI 形态 ``choices[0].message.content``；非该形态返 None。

    返回 None（不抛）让 ``_extract_text`` 回落到 Anthropic 分支——只有
    确实是 OpenAI 形态且取到非空字符串才返回。
    """
    choices = _resp_field(response, "choices")
    if not isinstance(choices, list) or not choices:
        return None
    message = _block_field(choices[0], "message")
    if message is None:
        return None
    content = _block_field(message, "content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    return None


def _has_openai_choices(response: Any) -> bool:
    """response 是否带非空 OpenAI ``choices`` 列表（不看 content 有没有内容）。

    用来区分"OpenAI 形态但正文空"（reasoning 截断）和"压根不是 OpenAI 形态"
    （该走 Anthropic 分支）两种情况，让 ``_extract_text`` 报准错因。
    """
    choices = _resp_field(response, "choices")
    return isinstance(choices, list) and bool(choices)


def _parse_processor_json(text: str) -> dict[str, Any]:
    """解析 processor 输出 JSON。失败抛——上层 fallback。

    dogfood 实测 minimax M2.7 等 reasoning model 返回经常带 ``<think>...</think>``
    内联 reasoning，或者 JSON 前后裹一段解释文字。三层兜底依次剥：

    1. ```json ... ``` 围栏
    2. ``<think>...</think>`` reasoning block（reasoning model 内联思考）
    3. 第一个完整 ``{...}`` JSON object（应付前后有解释文字）
    """
    raw = text.strip()

    # 1. 围栏剥
    if raw.startswith("```"):
        lines = raw.splitlines()
        if len(lines) >= 2 and lines[-1].strip().startswith("```"):
            raw = "\n".join(lines[1:-1]).strip()

    # 2. <think>...</think> 剥（reasoning model 内联思考块）
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

    # 3. 找第一个完整 {...} JSON object
    extracted = _extract_first_json_object(raw)
    if extracted is not None:
        raw = extracted

    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise ValueError("processor JSON is not an object")
    return obj


# 私有别名转调 utils 公共版本——第 35 轮第三波抽公共后，外部
# 单测里 `from ... import _extract_first_json_object` 的代码继续可用。
from bookscope.agent.utils import (  # noqa: E402 — 兼容别名必须放文件尾，见上方注释
    extract_first_json_object as _extract_first_json_object,
)


def _sanitize_fields(
    parsed: dict[str, Any],
    *,
    original: str,
) -> tuple[list[str], list[int] | None, Literal["simple", "medium", "complex"]]:
    """把 LLM 输出 normalise 成保守的合法值。

    硬约束（任何一项不达标直接 fallback 该字段）：
    - subquestions：必须是非空 list[str]，截断到前 3 个；空 list → [original]
    - recommended_chapters：必须是 list[int]（或 null）；非法 → None
    - difficulty：必须在 3 个枚举值内；非法 → "medium"
    """
    raw_sq = parsed.get("subquestions")
    if isinstance(raw_sq, list):
        subquestions = [str(x).strip() for x in raw_sq if isinstance(x, str) and x.strip()]
        if not subquestions:
            subquestions = [original]
        elif len(subquestions) > MAX_SUBQUESTIONS:
            subquestions = subquestions[:MAX_SUBQUESTIONS]
    else:
        subquestions = [original]

    raw_chapters = parsed.get("recommended_chapters")
    recommended_chapters: list[int] | None
    if raw_chapters is None:
        recommended_chapters = None
    elif isinstance(raw_chapters, list) and all(
        isinstance(c, int) and not isinstance(c, bool) for c in raw_chapters
    ):
        recommended_chapters = list(raw_chapters) if raw_chapters else None
    else:
        recommended_chapters = None

    raw_diff = parsed.get("difficulty")
    difficulty: Literal["simple", "medium", "complex"]
    if isinstance(raw_diff, str) and raw_diff in _VALID_DIFFICULTIES:
        difficulty = raw_diff  # type: ignore[assignment]
    else:
        difficulty = "medium"

    return subquestions, recommended_chapters, difficulty


def _resp_field(resp: Any, key: str) -> Any:
    if resp is None:
        return None
    if isinstance(resp, dict):
        return resp.get(key)
    return getattr(resp, key, None)


def _block_type(block: Any) -> str | None:
    if isinstance(block, dict):
        return block.get("type")
    return getattr(block, "type", None)


def _block_field(block: Any, key: str) -> Any:
    if isinstance(block, dict):
        return block.get(key)
    return getattr(block, key, None)


__all__ = [
    "ProcessedQuestion",
    "process_question",
    "rewrite_followup",
    "build_system_addendum",
    "DEFAULT_TIMEOUT_SECONDS",
    "MAX_SUBQUESTIONS",
]
