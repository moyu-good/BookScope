"""论点结构梳理：拆解一本书的论证骨架——主要主张 + 原文证据 + 所在章节。

学习者发明区——读理论书/论文，抓核心主张、看作者靠什么撑。长上下文整本进 context、
按论证推进列出主要论点，每条带一句原文逐字证据。

复用 [[project_wholebook_feature_pattern]]：长上下文 + 结构化 JSON + 三守卫（够 token /
关缓存 / 重试 + 截断抢救）。每条 evidence 过 verify_citations 标 verified + 真章号纠偏。
probe GO：zhinei 引用真实性 100%、命根子（支撑书反对的主张）假阳性 0%。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from bookscope.agent._internal.exhaustive import merge_by_key, run_segments
from bookscope.agent._internal.llm_cache import invoke_client_cached as _invoke_client
from bookscope.agent._internal.longctx_system import build_longctx_system
from bookscope.agent.citation_check import build_evidence_map, verify_citations
from bookscope.agent.utils.json_parsing import (
    extract_first_json_object as _extract_first_json_object,
)
from bookscope.agent.utils.json_parsing import (
    salvage_closed_objects,
)
from bookscope.agent.utils.json_parsing import (
    strip_code_fence as _strip_code_fence,
)

logger = logging.getLogger(__name__)

DEFAULT_ARGUMENT_MAX_TOKENS = 8000
_MAX_ATTEMPTS = 2
_MAX_CLAIMS = 30

_SYSTEM_INSTRUCTION = (
    "你是 BookScope 的论点梳理助手。"
    "请梳理这本书的主要论点结构——作者主张了什么、靠什么撑。按论证推进顺序排，"
    "每条给：主张（一句）、所在章节、一句原文逐字证据。只据原文、不编。\n"
    "严格输出 JSON（不要别的话、不要 markdown 代码围栏）：\n"
    '{"claims": [{"order": 序号整数, "claim": "主张一句", '
    '"chapter": 章号整数, "evidence": "原文逐字片段"}]}\n'
    "order 从 1 起递增。只列书里真有的主要论点（最多约 20 条），"
    "evidence 必须是原文里逐字出现的句子。"
)


def _resp_field(resp: Any, field: str) -> Any:
    if resp is None:
        return None
    if isinstance(resp, dict):
        return resp.get(field)
    return getattr(resp, field, None)


def _coerce(raw: Any) -> list[dict[str, Any]] | None:
    if not isinstance(raw, dict):
        return None
    items = raw.get("claims")
    if not isinstance(items, list):
        return None
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        claim = str(item.get("claim", "")).strip()
        if not claim:
            continue
        order = item.get("order")
        chapter = item.get("chapter")
        out.append({
            "order": order if isinstance(order, int) else len(out) + 1,
            "claim": claim,
            "chapter": chapter if isinstance(chapter, int) else 0,
            "evidence": str(item.get("evidence", "")).strip(),
        })
        if len(out) >= _MAX_CLAIMS:
            break
    out.sort(key=lambda c: c["order"])
    return out or None


def _salvage_truncated(text: str) -> list[dict[str, Any]] | None:
    """从截断 JSON 抠出 ``claims`` 数组里已闭合的完整对象（同 timeline 抢救）。"""
    raw_items = salvage_closed_objects(text, '"claims"') or []
    return _coerce({"claims": raw_items}) if raw_items else None


def _parse_claims(text: str) -> list[dict[str, Any]] | None:
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
    result = _coerce(obj)
    if result is not None:
        return result
    salvaged = _salvage_truncated(candidate)
    if salvaged:
        logger.warning(
            "argument_structure: 主解析失败，从截断输出抢救到 %d 条", len(salvaged)
        )
    return salvaged


def _verify_claims(claims: list[dict[str, Any]], chunks: list[dict[str, Any]]) -> None:
    """每条 claim 的 evidence 当一条 citation 过 verify_citations（原地附加）。

    命中 → ``verified=True`` + 用命中 chunk 的真章号纠偏（不信模型自报章号）；没命中 →
    ``verified=False``，章号留模型自报的（FE 只在 verified 上盖钤印）。
    """
    evidence_map = build_evidence_map(chunks)
    for cl in claims:
        # 带上 LLM 自报章号当多命中消歧弱先验（真章号在 verify 后用 chunk_id 覆盖）；
        # chapter 为 0 = 模型没报，不传，退回确定性首个。
        self_ch = cl.get("chapter")
        cit: dict[str, Any] = {"snippet": cl["evidence"]}
        if isinstance(self_ch, int) and self_ch > 0:
            cit["chapter"] = self_ch
        cits = [cit]
        verify_citations(cits, evidence_map)
        vc = cits[0]
        cl["verified"] = bool(vc.get("verified", False))
        cid = vc.get("chunk_id")
        true_ch = evidence_map.get(cid, {}).get("chapter") if cid else None
        if isinstance(true_ch, int) and true_ch > 0:
            cl["chapter"] = true_ch


def generate_argument_structure(
    *,
    full_text: str,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    max_tokens: int = DEFAULT_ARGUMENT_MAX_TOKENS,
    session_id: str | None = None,
) -> list[dict[str, Any]] | None:
    """梳理书的论点结构；失败返 ``None``。

    每条 evidence 过 verify_citations 标 verified + 真章号纠偏。保留全部论点（含 evidence
    未命中的，标 verified=False 供用户判断 + 前端只在 verified 上盖钤印）。

    Returns:
        ``[{order, claim, chapter, evidence, verified}, ...]`` 按 order 排；失败 ``None``。
    """
    _ = session_id
    system = build_longctx_system(full_text, _SYSTEM_INSTRUCTION)
    messages = [{"role": "user", "content": "请梳理这本书的主要论点结构。"}]
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
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "argument_structure LLM call raised %s: %s (attempt %d)",
                type(exc).__name__, exc, attempt,
            )
            continue
        claims = _parse_claims(llm_client.extract_final_text(response))
        if claims is None:
            logger.warning(
                "argument_structure parse failed (attempt %d/%d)", attempt, _MAX_ATTEMPTS
            )
            continue
        _verify_claims(claims, chunks)
        return claims
    return None


def generate_argument_structure_exhaustive(
    *,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    max_tokens: int = DEFAULT_ARGUMENT_MAX_TOKENS,
    char_budget: int = 40000,
    max_workers: int | None = None,
) -> list[dict[str, Any]] | None:
    """穷尽化:分段→每段抽本段论点→按 claim 去重拼,覆盖全书(1.4)。

    单次调用带硬帽（prompt 写"最多约 20 条"），长书论点列不全。改 map-reduce:每段只抽本段
    论点，跨段按 claim 去重拼起来。论点不像章节那样 disjoint——同一论点可能在相邻段都被抽到，
    所以按 claim 文本去重。合并后按章号重排再重编 order，最后一次性 ``_verify_claims``。

    Returns: 同 ``generate_argument_structure``,但覆盖全书；空 → ``None``。
    """
    outs = run_segments(
        chunks=chunks,
        instruction=_SYSTEM_INSTRUCTION,
        user_msg="请梳理下面这段原文里出现的主要论点（只列本段的）。",
        parse_fn=_parse_claims,
        llm_client=llm_client,
        model=model,
        max_tokens=max_tokens,
        char_budget=char_budget,
        max_workers=max_workers,
    )
    merged = merge_by_key(outs, key_fn=lambda c: c.get("claim"))
    if not merged:
        return None
    merged.sort(key=lambda c: c["chapter"])  # 段内 order 跨段会重复，按章号重排
    for i, c in enumerate(merged, 1):
        c["order"] = i  # 重排后重新编号 1..N
    _verify_claims(merged, chunks)
    return merged


__all__ = [
    "DEFAULT_ARGUMENT_MAX_TOKENS",
    "generate_argument_structure",
    "generate_argument_structure_exhaustive",
]
