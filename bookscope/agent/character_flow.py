"""人物叙事流图：整本进 context、逐章抽"同场人物 + 同场对"结构化 JSON。

设计：WP-character-narrative-flow。

probe GO（同场抽取 recall 88% / 假阳性 0%）：agent 能从原文可靠判定"某章里哪些人物同场、
有直接互动"，且不把"只是分别被提到、各在各的场景"硬凑成同场。本模块把它从单段 probe
做成整本逐章抽取的生产实现——给前端画 storyline（横轴章节、每人一条横线、同场聚束）。

结构同 :func:`bookscope.agent.character_graph.extract_character_graph`，差别两处：

1. **出逐章结构**——``{"chapters": [{"chapter": N, "present": [人名], "pairs": [{a, b,
   evidence}]}]}``，而不是一张全书静态关系网。
2. **同场判定挂原文证据**——每条 ``pair`` 的 ``evidence`` 当一条 citation 过
   :func:`verify_citations`：命中某 chunk → ``verified=True`` + 用命中 chunk 的真章号
   纠偏；``verified=False`` 的同场对留着但标灰（FE 不画进束/画虚线），evidence-first。

整本书结构化功能模式三可靠性守卫照搬：够 max_tokens 防 reasoning 吃 token 截断、
``cache_enabled=False`` 防坏响应被 poison、解析失败重试一次 + 截断抢救。契约同
``generate_pacing_curve``：成功返 list[章节 dict]，**任意环节失败返 None**。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from bookscope.agent._internal.exhaustive import mapreduce_per_chapter
from bookscope.agent._internal.llm_cache import invoke_client_cached as _invoke_client
from bookscope.agent._internal.longctx_system import build_longctx_system
from bookscope.agent.citation_check import verify_citations
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

DEFAULT_FLOW_MAX_TOKENS = 8000
"""逐章 present + pairs 比单点判断长——给 8000 留 reasoning 头，防截断/空（同关系图）。"""

_MAX_ATTEMPTS = 2

_SYSTEM_INSTRUCTION = (
    "请逐章梳理人物的同场关系——每章里哪些人物**同场出现、有直接互动**"
    "（同一场景里照面、对话、交手才算；只是分别被提到、各在各的场景，不算同场）。"
    "只依据原文，不臆测、不编造书里不存在的同场。\n"
    "严格输出 JSON（不要别的话、不要 markdown 代码围栏）：\n"
    '{"chapters": [{"chapter": 章号整数, '
    '"present": ["这章出场的主要人物名"], '
    '"pairs": [{"a": "人物A", "b": "人物B", '
    '"evidence": "证明这两人这章同场的原文逐字片段，原样摘录不改写"}]}]}\n'
    "present 列这章登场的主要人物；pairs 列这章里同场互动的人物对，每对必须带 evidence，"
    "且 evidence 是原文里逐字出现的句子。a 和 b 都要在本章 present 里出现。"
    "没有直接同场互动的人物之间不要硬配对。"
    "按章号从小到大排列，覆盖主要章节（最多约 40 章）；"
    "每章只列最重要的核心人物与同场对，宁可少而准，不必穷尽次要人物。"
)


def _coerce_chapter(item: Any) -> dict[str, Any] | None:
    """把一条章节 dict 归一成 ``{chapter:int, present:list[str], pairs:list[dict]}``。

    chapter 缺/非整数 → 丢；present 归一成去重 list[str]；pairs 保留 a/b 齐全的对，
    evidence 可缺（缺则后续 verified 自然 False）。
    """
    if not isinstance(item, dict):
        return None
    ch = item.get("chapter")
    if not isinstance(ch, int):
        return None

    present: list[str] = []
    seen: set[str] = set()
    raw_present = item.get("present")
    if isinstance(raw_present, list):
        for p in raw_present:
            name = ""
            if isinstance(p, dict):
                name = str(p.get("name", "")).strip()
            elif isinstance(p, str):
                name = p.strip()
            if name and name not in seen:
                seen.add(name)
                present.append(name)

    pairs: list[dict[str, Any]] = []
    raw_pairs = item.get("pairs")
    if isinstance(raw_pairs, list):
        for p in raw_pairs:
            if not isinstance(p, dict):
                continue
            a = str(p.get("a", "")).strip()
            b = str(p.get("b", "")).strip()
            if not a or not b or a == b:
                continue
            pairs.append({
                "a": a,
                "b": b,
                "evidence": str(p.get("evidence", "")).strip(),
                "chapter": ch,
            })

    # 把 pairs 端点里没在 present 出现的人物补进 present（模型偶尔漏列）
    for pr in pairs:
        for endpoint in (pr["a"], pr["b"]):
            if endpoint not in seen:
                seen.add(endpoint)
                present.append(endpoint)

    return {"chapter": ch, "present": present, "pairs": pairs}


def _coerce_chapters(raw: Any) -> list[dict[str, Any]]:
    """保留 chapter 齐全的章节；去重同章号；按章号升序。"""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for item in raw:
        ch = _coerce_chapter(item)
        if ch is None or ch["chapter"] in seen:
            continue
        seen.add(ch["chapter"])
        out.append(ch)
    out.sort(key=lambda c: c["chapter"])
    return out


def _salvage_truncated_chapters(text: str) -> list[dict[str, Any]] | None:
    """从截断的 JSON 里抢救已吐完的完整章节对象。

    flash 把 reasoning_content 算进 max_tokens，逐章结构一大就可能被截断成半截 JSON，
    整段 ``json.loads`` 必败。与其整张图丢掉返 None，不如把 ``"chapters"`` 数组里已经
    闭合的 ``{...}`` 逐个抠出来——用户至少看到大部分章节（同关系图截断抢救思路）。
    """
    raw_chapters = salvage_closed_objects(text, '"chapters"') or []
    chapters = _coerce_chapters(raw_chapters)
    return chapters or None


def _parse_flow(text: str) -> list[dict[str, Any]] | None:
    """解析模型输出的逐章流图 JSON。正常失败 → 抢救截断的章节 → 仍不行返 None。"""
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
    if isinstance(obj, dict):
        chapters = _coerce_chapters(obj.get("chapters"))
        if chapters:
            return chapters
    salvaged = _salvage_truncated_chapters(candidate)
    if salvaged is not None:
        logger.warning(
            "character_flow: 主解析失败，从截断输出抢救到 %d 章", len(salvaged)
        )
        return salvaged
    logger.warning("character_flow parse failed; raw head=%r", candidate[:200])
    return None


def _verify_pairs(
    chapters: list[dict[str, Any]], chunks: list[dict[str, Any]]
) -> None:
    """每章每条同场对的 evidence 当一条 citation 过 verify_citations（原地附加）。

    命中 → ``verified=True`` + 用命中 chunk 的真章号纠偏（不信模型自报章号，同
    long_context / character_graph）；没命中 → ``verified=False`` + chapter 退回
    模型自报的章号（FE 标灰但仍知道在哪章）。
    """
    evidence = {
        str(c["chunk_id"]): {"chapter": c.get("chapter", 0), "text": c.get("text", "")}
        for c in chunks
        if c.get("chunk_id")
    }
    for chap in chapters:
        pairs = chap["pairs"]
        # 带上每条同场对 LLM 自报章号当多命中消歧弱先验（真章号在 verify 后用 chunk_id 覆盖）。
        pair_citations = [{"snippet": p["evidence"], "chapter": p["chapter"]} for p in pairs]
        verify_citations(pair_citations, evidence)
        for pr, vc in zip(pairs, pair_citations, strict=True):
            pr["verified"] = bool(vc.get("verified", False))
            pr["match_score"] = vc.get("match_score", 0.0)
            cid = vc.get("chunk_id")
            true_chapter = evidence.get(cid, {}).get("chapter") if cid else None
            if isinstance(true_chapter, int) and true_chapter > 0:
                pr["chapter"] = true_chapter  # 命中 chunk 的真章号纠偏


def generate_character_flow(
    *,
    full_text: str,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    max_tokens: int = DEFAULT_FLOW_MAX_TOKENS,
    session_id: str | None = None,
) -> list[dict[str, Any]] | None:
    """整本进 context 抽逐章同场结构 + 每条同场对原文核验；失败返 ``None``。

    Args:
        full_text: 整本书 cleaned 原文。
        chunks: 全书 chunk dict（含 ``chunk_id`` / ``chapter`` / ``text``），给同场对
            evidence 做证据登记表 + 提供章号 ground truth。
        llm_client: duck-typed LLM client（同 AgentLoop / character_graph）。
        model: 模型名。
        max_tokens: 单次 LLM 调用 max_tokens（默认 8000，逐章结构长）。
        session_id: 仅签名兼容——本任务关缓存（防坏响应被 poison）。

    Returns:
        ``[{"chapter": int, "present": [str], "pairs": [{a, b, evidence, verified,
        match_score, chapter}]}, ...]`` 按章号排序；任意失败 ``None``。
    """
    _ = session_id  # 关缓存：本任务出结构化 JSON，坏响应不该被缓存 poison
    system = build_longctx_system(full_text, _SYSTEM_INSTRUCTION)
    messages = [{"role": "user", "content": "请逐章抽这本书的人物同场叙事流。"}]
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
                "character_flow LLM call raised %s: %s (attempt %d)",
                type(exc).__name__, exc, attempt,
            )
            continue
        chapters = _parse_flow(llm_client.extract_final_text(response))
        if chapters is not None:
            _verify_pairs(chapters, chunks)
            return chapters
        logger.warning(
            "character_flow parse failed (attempt %d/%d)", attempt, _MAX_ATTEMPTS
        )
    return None


def generate_character_flow_exhaustive(
    *,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    max_tokens: int = DEFAULT_FLOW_MAX_TOKENS,
    char_budget: int = 40000,
    max_workers: int | None = None,
) -> list[dict[str, Any]] | None:
    """穷尽化:分段→每段逐章抽同场流→按章拼,覆盖全书每一章(1.4)。

    重型逐章(每章带 present + pairs + evidence)单次会被 max_tokens 截断到几章——大书只够几章。
    改 map-reduce:每段章数远小于 40 帽,段内沿用现有 prompt,拼起来覆盖全书。合并后一次性
    ``_verify_pairs``(逐字核验 + 章号纠偏)。

    Returns: 同 ``generate_character_flow``,但覆盖全书所有章;空 → ``None``。
    """
    merged = mapreduce_per_chapter(
        chunks=chunks,
        instruction=_SYSTEM_INSTRUCTION,
        user_msg="请逐章抽下面这段原文的人物同场叙事流（只抽本段出现的章）。",
        parse_fn=_parse_flow,
        llm_client=llm_client,
        model=model,
        max_tokens=max_tokens,
        char_budget=char_budget,
        max_workers=max_workers,
    )
    if not merged:
        return None
    _verify_pairs(merged, chunks)
    return merged


__all__ = [
    "DEFAULT_FLOW_MAX_TOKENS",
    "generate_character_flow",
    "generate_character_flow_exhaustive",
]
