"""每书自动出诊断题：据整本书内容生成书内专属的深度诊断题。

feature 1 surface 的是**通用**诊断题（"主角的转变是渐变还是硬扳"）。但用户对**这本**
书不知道具体问什么（哪条支线？哪个人物？哪处设定？）。本模块据整本书内容，出**书内
专属**的诊断题（"安禄山起兵的伏笔前几章埋够了吗"——点名书里的具体元素），降"不会问"
门槛。

覆盖发明区已验证的诊断类型（伏笔 / 人物弧线 / 设定一致性 / 节奏 / 人物关系），每道
实例化到这本书的具体人物 / 支线 / 设定。复用 long_context 形态（整本进 context）。
输出小（~6 题），无截断风险。契约同 long_context：失败返 None。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from bookscope.agent._internal.llm_cache import invoke_client_cached as _invoke_client
from bookscope.agent.utils.json_parsing import (
    extract_first_json_object as _extract_first_json_object,
)
from bookscope.agent.utils.json_parsing import (
    strip_code_fence as _strip_code_fence,
)

logger = logging.getLogger(__name__)

DEFAULT_QUESTIONS_MAX_TOKENS = 4000
"""输出 ~900 token，但 flash reasoning 也算预算且这任务 reasoning 偏重——给到 4000
避免 reasoning + 内容超 2048 致截断（reasoning 吃 token 老坑）。"""

_MAX_ATTEMPTS = 2
"""解析失败重试一次：模型偶发不按 JSON 吐，新调用通常就好。"""

_MAX_QUESTIONS = 8

_SYSTEM_INSTRUCTION = (
    "你是 BookScope 的诊断题助手。下面 === 全书原文 === 之后是一整本书的完整原文。"
    "请据这本书的**具体内容**，出 5-6 道『作家审稿 / 深度阅读会问』的诊断题——"
    "每道都要点名这本书里的**具体人物 / 支线 / 设定 / 章节**，不要泛泛而问。"
    "覆盖这几类（每类至多 1-2 道）：伏笔回收、人物弧线/动机、设定一致性、节奏张力、人物关系。\n"
    "严格输出 JSON（不要别的话、不要 markdown 代码围栏）：\n"
    '{"questions": [{"type": "伏笔回收", "question": "具体到这本书的问题"}]}\n'
    "type 用上面五类之一；question 必须具体到书内元素，能直接拿去问这本书。"
)

_BOOK_DELIMITER = "\n\n=== 全书原文 ===\n"

_VALID_TYPES = {"伏笔回收", "人物弧线", "设定一致性", "节奏张力", "人物关系"}


def _resp_field(resp: Any, field: str) -> Any:
    if resp is None:
        return None
    if isinstance(resp, dict):
        return resp.get(field)
    return getattr(resp, field, None)


def _normalize_type(raw: str) -> str:
    """把模型给的 type 归一到五类之一；不在表里的归"其它"。"""
    raw = (raw or "").strip()
    for t in _VALID_TYPES:
        if t in raw or raw in t:
            return t
    # 容错：常见同义
    if "动机" in raw or "弧线" in raw or "转变" in raw:
        return "人物弧线"
    if "矛盾" in raw or "一致" in raw:
        return "设定一致性"
    if "节奏" in raw or "张力" in raw:
        return "节奏张力"
    if "关系" in raw:
        return "人物关系"
    if "伏笔" in raw or "铺垫" in raw:
        return "伏笔回收"
    return "其它"


def _parse_questions(text: str) -> list[dict[str, str]] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    candidate = _strip_code_fence(raw)
    obj: Any = None
    try:
        obj = json.loads(candidate)
    except json.JSONDecodeError:
        sliced = _extract_first_json_object(candidate)
        if sliced is not None:
            try:
                obj = json.loads(sliced)
            except json.JSONDecodeError:
                obj = None
    if not isinstance(obj, dict):
        return None
    raw_qs = obj.get("questions")
    if not isinstance(raw_qs, list):
        return None
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw_qs:
        if not isinstance(item, dict):
            continue
        q = str(item.get("question", "")).strip()
        if not q or q in seen:
            continue
        seen.add(q)
        out.append({"type": _normalize_type(str(item.get("type", ""))), "question": q})
        if len(out) >= _MAX_QUESTIONS:
            break
    return out or None


def generate_book_questions(
    *,
    full_text: str,
    llm_client: Any,
    model: str,
    max_tokens: int = DEFAULT_QUESTIONS_MAX_TOKENS,
    session_id: str | None = None,
) -> list[dict[str, str]] | None:
    """据整本书生成书内专属诊断题；失败返 ``None``。

    Args:
        full_text: 整本书 cleaned 原文。
        llm_client: duck-typed LLM client（同 AgentLoop）。
        model: 模型名。
        max_tokens: 单次 LLM 调用 max_tokens。
        session_id: 给 L2 缓存用；None 降级直调。同书同 prompt 命中缓存，省重复生成。

    Returns:
        ``[{"type": ..., "question": ...}, ...]``；任意失败 ``None``。
    """
    system = _SYSTEM_INSTRUCTION + _BOOK_DELIMITER + full_text
    messages = [{"role": "user", "content": "请据这本书出书内专属诊断题。"}]
    # cache_enabled=False：模型偶发吐坏 JSON，L2 缓存会把坏响应缓存住致持续失败
    # （poison cache）——本任务每书点一次、关缓存换可靠性。session_id 仅保留签名兼容。
    _ = session_id
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            response = _invoke_client(
                llm_client,
                model=model,
                system=system,
                tools=[],
                messages=messages,
                max_tokens=max_tokens,
                cache_enabled=False,
            )
        except Exception as exc:  # noqa: BLE001 — 包死，重试 / 返 None
            logger.warning(
                "suggested_questions LLM call raised %s: %s (attempt %d)",
                type(exc).__name__, exc, attempt,
            )
            continue
        questions = _parse_questions(llm_client.extract_final_text(response))
        if questions is not None:
            return questions
        logger.warning("suggested_questions parse failed (attempt %d/%d)", attempt, _MAX_ATTEMPTS)
    return None


__all__ = ["DEFAULT_QUESTIONS_MAX_TOKENS", "generate_book_questions"]
