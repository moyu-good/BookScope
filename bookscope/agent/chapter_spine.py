"""章脉(ADR-010):整本一次精读出的、带证据的逐章结构,全书功能从它派生视图的单一事实源。

**为什么有这个模块**:关系图 / 叙事流 / 叙事曲线 / 时间线…… 十个全书功能本来各自把整本
map-reduce 一遍,同段原文 input 重发十遍,几百万字书跑不动(见 ADR-010)。改成:整本只精读
一次出章脉,各功能从章脉派生视图(纯计算或一次小调用)。

**分维抽取**(probe 定案,`scripts/probe_chapter_spine.py`:全维一趟短章网文 3/4 段截断,分维 0/4):
- 人物维:每章 在场人物 / 关系 / 人物处境
- 情节维:每章 事件 / 张力 / 情感 / 视角 / 主支线 / 伏笔候选
- 概念维(理论书):每章 主张

每维走 ``mapreduce_per_chapter``(D-7 章闸防输出截断 + 合并前逐段章号纠偏),再按**真章号**
跨维 union 成一条章脉记录。每条记录、每个字段都钉原文证据——没证据不进章脉(立身之本)。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from bookscope.agent._internal.exhaustive import DEFAULT_CHAR_BUDGET, mapreduce_per_chapter
from bookscope.agent.citation_check import build_evidence_map, verify_citations
from bookscope.agent.utils.json_parsing import (
    extract_first_json_object as _extract_first_json_object,
)
from bookscope.agent.utils.json_parsing import salvage_closed_objects
from bookscope.agent.utils.json_parsing import strip_code_fence as _strip_code_fence

logger = logging.getLogger(__name__)

DEFAULT_SPINE_MAX_TOKENS = 8000
"""分维后单维输出比全维一趟小;配 D-7 章闸(每段 ≤12 章)够用,留 reasoning 头。"""

SPINE_SCHEMA_VERSION = "v1"
"""章脉记录结构版本——升级要让缓存整本失效(接 ADR-008 L3,迁移计划第 5 步)。"""


# ── 三维抽取指令 ───────────────────────────────────────────────────────────
_INSTR_CHAR = (
    "你在给一本书做逐章人物精读。只针对下面这段原文,逐章抽,只抽本段出现的章,不臆测、不编造。\n"
    "每章给:\n"
    "1. present:这章在场（有戏份）的人物名数组。\n"
    "2. relations:这章里有互动的人物对数组,每条 {pair:[甲,乙], note:这章他俩之间发生了什么}。\n"
    "3. char_states:这章里主要人物的处境数组,每条 {name:人物, state:他这章处于什么境况}。\n"
    "4. evidence:这章里最能代表上面判定的一句原文逐字片段(原样摘录、不改写)。\n"
    "严格输出 JSON(别的话别说、别加 markdown 围栏):\n"
    '{"chapters":[{"chapter":章号整数,"present":[],"relations":[],"char_states":[],"evidence":""}]}'
)

_INSTR_PLOT = (
    "你在给一本书做逐章情节精读。只针对下面这段原文,逐章抽,只抽本段出现的章,不臆测、不编造。\n"
    "每章给:\n"
    "1. events:这章的关键事件数组,每条一句话。\n"
    "2. tension:张力 0-10 整数,铺垫/过场低、高潮/冲突高。\n"
    "3. sentiment:情感方向 -5 到 5 整数,往上走(喜胜聚)正、往下沉(悲败散)负、平稳 0。\n"
    "4. pov:主导视角人物名;无单一视角(全景)填\"群像\"。\n"
    "5. mainline:推进主线 true,岔开支线/闲笔 false。\n"
    "6. foreshadow:这章的伏笔候选数组,每条 {type:\"埋\"或\"收\", hook:埋/收的是什么}。\n"
    "7. evidence:这章里最能代表上面判定的一句原文逐字片段(原样摘录、不改写)。\n"
    "严格输出 JSON(别的话别说、别加 markdown 围栏):\n"
    '{"chapters":[{"chapter":章号整数,"events":[],"tension":0,"sentiment":0,"pov":"",'
    '"mainline":true,"foreshadow":[],"evidence":""}]}'
)

_INSTR_CONCEPT = (
    "你在给一本理论/论说类书做逐章精读。只针对下面这段原文,逐章抽,只抽本段出现的章,不臆测。\n"
    "每章给:\n"
    "1. claims:这章提出/论证的主张数组,每条一句话。\n"
    "2. evidence:这章里最能代表上面主张的一句原文逐字片段(原样摘录、不改写)。\n"
    "严格输出 JSON(别的话别说、别加 markdown 围栏):\n"
    '{"chapters":[{"chapter":章号整数,"claims":[],"evidence":""}]}'
)

_USER_MSG = "请按上面的要求,只对这段原文逐章抽结构。"

# 每维:(指令, 该维除 chapter/evidence 外要保留的字段, 该字段缺省值)
_DIM_FIELDS: dict[str, dict[str, Any]] = {
    "char": {"present": list, "relations": list, "char_states": list},
    "plot": {"events": list, "tension": int, "sentiment": int, "pov": str,
             "mainline": bool, "foreshadow": list},
    "concept": {"claims": list},
}


def _clamp_int(value: Any, lo: int, hi: int, default: int) -> int:
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _coerce_dim(item: Any, dim: str) -> dict[str, Any] | None:
    """把一条章节 dict 归一成该维该有的字段;chapter 缺/非整数 → 丢(没章号摆不进章脉)。"""
    if not isinstance(item, dict):
        return None
    ch = item.get("chapter")
    if not isinstance(ch, int):
        return None
    out: dict[str, Any] = {"chapter": ch, "evidence": str(item.get("evidence", "")).strip()}
    for field, typ in _DIM_FIELDS[dim].items():
        v = item.get(field)
        if field == "tension":
            out[field] = _clamp_int(v, 0, 10, 0)
        elif field == "sentiment":
            out[field] = _clamp_int(v, -5, 5, 0)
        elif field == "pov":
            out[field] = (v.strip() if isinstance(v, str) else "") or "群像"
        elif field == "mainline":
            out[field] = v if isinstance(v, bool) else True
        elif typ is list:
            out[field] = v if isinstance(v, list) else []
    return out


def _make_parser(dim: str):  # noqa: ANN202 — 返回闭包 parse_fn 喂 mapreduce
    """造一个该维的 parse_fn:strip 围栏 → json.loads → 抠首个 obj → 抢救截断 → 归一。"""

    def _coerce_list(raw: Any) -> list[dict[str, Any]]:
        if not isinstance(raw, list):
            return []
        out: list[dict[str, Any]] = []
        seen: set[int] = set()
        for it in raw:
            c = _coerce_dim(it, dim)
            if c is None or c["chapter"] in seen:
                continue
            seen.add(c["chapter"])
            out.append(c)
        return out

    def _parse(text: str) -> list[dict[str, Any]] | None:
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
            chs = _coerce_list(obj.get("chapters"))
            if chs:
                return chs
        salvaged = _coerce_list(salvage_closed_objects(candidate, '"chapters"') or [])
        if salvaged:
            logger.warning("chapter_spine[%s]: 主解析失败,从截断抢救到 %d 章", dim, len(salvaged))
            return salvaged
        return None

    return _parse


def _correct_by_evidence(records: list[dict[str, Any]], chunks: list[dict[str, Any]]) -> None:
    """合并前逐段把每条记录的章号纠偏成命中 chunk 的真章号(同 narrative,ADR-010 D-2)。

    多卷书正文标题每卷重数,模型照标题给撞号的小章号;若按它先 merge 会丢章。这里用记录的
    chapter 级 evidence 过 verify_citations,命中就用 chunk 的真章号覆盖,并附 verified/match_score。
    """
    evidence = build_evidence_map(chunks)
    citations = [{"snippet": r.get("evidence", ""), "chapter": r.get("chapter")} for r in records]
    verify_citations(citations, evidence)
    for rec, vc in zip(records, citations, strict=True):
        rec["verified"] = bool(vc.get("verified", False))
        rec["match_score"] = vc.get("match_score", 0.0)
        cid = vc.get("chunk_id")
        true_ch = evidence.get(cid, {}).get("chapter") if cid else None
        if isinstance(true_ch, int) and true_ch > 0:
            rec["chapter"] = true_ch


def _merge_dimensions(dim_lists: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """按**真章号**把各维的逐章记录 union 成一条章脉记录(各维字段不重叠,直接并)。

    chapter 级 evidence 保第一条非空;verified 取任一维命中即 True、match_score 取最大。
    """
    by_ch: dict[int, dict[str, Any]] = {}
    order: list[int] = []
    for dim_list in dim_lists:
        for rec in dim_list:
            ch = rec.get("chapter")
            if not isinstance(ch, int):
                continue
            if ch not in by_ch:
                by_ch[ch] = {"chapter": ch, "evidence": "", "verified": False, "match_score": 0.0}
                order.append(ch)
            tgt = by_ch[ch]
            for k, v in rec.items():
                if k == "chapter":
                    continue
                if k == "evidence":
                    if v and not tgt["evidence"]:
                        tgt["evidence"] = v
                elif k == "verified":
                    tgt["verified"] = tgt["verified"] or bool(v)
                elif k == "match_score":
                    tgt["match_score"] = max(tgt["match_score"], v or 0.0)
                else:
                    tgt[k] = v
    return [by_ch[ch] for ch in sorted(order)]


def build_chapter_spine(
    *,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    genre: str = "fiction",
    max_tokens: int = DEFAULT_SPINE_MAX_TOKENS,
    char_budget: int = DEFAULT_CHAR_BUDGET,
    max_workers: int | None = None,
) -> list[dict[str, Any]]:
    """整本一次精读,出带证据的逐章章脉(ADR-010 单一事实源)。

    分维抽取:小说跑 人物维 + 情节维;``genre="theory"`` 加 概念维。每维 ``mapreduce_per_chapter``
    (D-7 章闸 + 合并前 ``_correct_by_evidence`` 纠偏),再按真章号跨维 union。空 → ``[]``。

    Returns: ``[{chapter, present, relations, char_states, events, tension, sentiment, pov,
    mainline, foreshadow, [claims], evidence, verified, match_score}]``,按章号升序。
    """
    dims = [("char", _INSTR_CHAR), ("plot", _INSTR_PLOT)]
    if genre == "theory":
        dims.append(("concept", _INSTR_CONCEPT))

    dim_lists: list[list[dict[str, Any]]] = []
    for dim, instruction in dims:
        recs = mapreduce_per_chapter(
            chunks=chunks,
            instruction=instruction,
            user_msg=_USER_MSG,
            parse_fn=_make_parser(dim),
            llm_client=llm_client,
            model=model,
            max_tokens=max_tokens,
            char_budget=char_budget,
            max_workers=max_workers,
            correct_fn=_correct_by_evidence,
        )
        dim_lists.append(recs)

    return _merge_dimensions(dim_lists)


__all__ = [
    "DEFAULT_SPINE_MAX_TOKENS",
    "SPINE_SCHEMA_VERSION",
    "build_chapter_spine",
]
