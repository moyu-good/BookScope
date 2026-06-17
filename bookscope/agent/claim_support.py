"""claim precision：核每条引用撑不撑得起答案的论述（exp-015 GO）。

`verify_citations` 只查"snippet 在不在书里"（来源真实性），不查"snippet 撑不撑得起
它配的论断"。本模块补这一层：对每条**非逐字**引用（match_type != "quote"）跑一次
LLM entailment judge，标 ``claim_support``：

- ``"supported"``：原文真正支撑答案的相关论述（逐字引用天然算 supported，跳过省钱）。
- ``"weak"``：原文只是提到相关词、或答案说得比原文更绝对（号称→确实、提到→因果）。
- ``"unchecked"``：judge 调用 / 解析失败——不阻断，标未核。

成本形态 = "只核转述"（作者选）：逐字引用不浪费 judge 调用，把核验花在真有风险的
转述/未核验引用上。judge 只看 (答案, 引用) 一对、不需全书，便宜。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from bookscope.agent._internal.llm_cache import invoke_client_cached as _invoke_client

logger = logging.getLogger(__name__)

DEFAULT_JUDGE_MAX_TOKENS = 2048
"""judge 输出极短（只一个 verdict），但 flash 是 reasoning model、思考也算进预算，
给够避免 reasoning 吃光致空输出（[[reference_reasoning_model_token_budget]]）。"""

_JUDGE_SYSTEM = (
    "你是严谨的事实核查助手。下面给你 BookScope 的一个『答案』和它附带的一段『引用原文』。"
    "判断这段引用原文能不能真正支撑答案里的相关论述。只输出 JSON（不要别的话）："
    '{"verdict": "supported" 或 "weak"}。'
    "原文真正支撑答案的核心主张才算 supported；"
    "只是提到了相关词语、或答案说得比原文更绝对（如把『号称』当『确实』、把『提到』当『因果』），"
    "都算 weak。"
)


def _parse_verdict(text: str) -> str:
    """从 judge 输出抽 verdict。解析不出返 'unchecked'。"""
    raw = (text or "").strip()
    if not raw:
        return "unchecked"
    candidate = raw
    if "{" in candidate and "}" in candidate:
        try:
            obj = json.loads(candidate[candidate.find("{"): candidate.rfind("}") + 1])
            v = str(obj.get("verdict", "")).lower()
            if v in ("supported", "weak"):
                return v
        except (json.JSONDecodeError, AttributeError):
            pass
    low = raw.lower()
    # 先判 weak：supported 是 weak 判定里也可能提到的词
    if "weak" in low:
        return "weak"
    if "supported" in low:
        return "supported"
    return "unchecked"


def _judge_one(
    llm_client: Any, model: str, answer: str, snippet: str, max_tokens: int
) -> str:
    resp = _invoke_client(
        llm_client,
        model=model,
        system=_JUDGE_SYSTEM,
        tools=[],
        messages=[{"role": "user", "content": f"答案：{answer}\n\n引用原文：{snippet}"}],
        max_tokens=max_tokens,
        cache_enabled=False,
    )
    return _parse_verdict(llm_client.extract_final_text(resp))


def check_claim_support(
    answer: str,
    citations: list[dict[str, Any]],
    *,
    llm_client: Any,
    model: str,
    max_tokens: int = DEFAULT_JUDGE_MAX_TOKENS,
) -> list[dict[str, Any]]:
    """给每条 citation 附加 ``claim_support``（原地改 + 返回）。

    只对 ``match_type != "quote"`` 的引用跑 judge（逐字引用天然 supported、跳过）。
    单条 judge 抛错 → 该条标 ``"unchecked"``，不影响其它条、不抛。

    Args:
        answer: 答案全文（当论断上下文）。
        citations: 引用列表，每条至少含 ``snippet`` + ``match_type``。
        llm_client: duck-typed LLM client（同 AgentLoop）。
        model: 模型名。
        max_tokens: judge 单次调用 max_tokens。

    Returns:
        同一批 citation dict（原地附加 ``claim_support`` 后返回）。
    """
    for cit in citations:
        if cit.get("match_type") == "quote":
            cit["claim_support"] = "supported"  # 逐字引用天然可信，省一次 judge
            continue
        snippet = str(cit.get("snippet", ""))
        if not snippet:
            cit["claim_support"] = "unchecked"
            continue
        try:
            cit["claim_support"] = _judge_one(
                llm_client, model, answer, snippet, max_tokens
            )
        except Exception as exc:  # noqa: BLE001 — 单条失败不阻断
            logger.warning("claim_support judge raised %s: %s", type(exc).__name__, exc)
            cit["claim_support"] = "unchecked"
    return citations


__all__ = ["DEFAULT_JUDGE_MAX_TOKENS", "check_claim_support"]
