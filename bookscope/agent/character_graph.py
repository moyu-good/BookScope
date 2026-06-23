"""人物关系图抽取：整本进 context、单次 LLM 吐结构化关系图 JSON（WP-character-graph）。

exp-013 验证 GO：agent 能从整本书抽出全面、每条边带原文证据的人物关系网，且不编
书里不存在的关系。本模块是它的生产实现。

结构同 :func:`bookscope.agent.long_context.run_long_context`（整本进 system 固定段、
缓存友好），差别两处：

1. **要结构化 JSON 图**——``{"nodes": [...], "edges": [{source, target, relation,
   evidence}]}``，省下游 parse 散文。
2. **max_tokens 默认 8000**——exp-013 实测图输出 ~5000-6000 token，4000 会截断/空。
3. **边粒度证据校验**——每条 edge 的 ``evidence`` 当一条 citation 过
   :func:`verify_citations`：命中某 chunk → ``verified=True`` + 用命中 chunk 的真
   章号填 ``chapter``（同 long_context 的章号纠偏思路，提到边粒度）。

契约同 ``run_long_context``：成功返 :class:`CharacterGraphResult`，**任意环节失败返
None**——调用方据此报错 / 回退。
"""

from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from bookscope.agent._internal.exhaustive import segment_chunks
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

DEFAULT_GRAPH_MAX_TOKENS = 8000
"""图输出比单点判断长得多——exp-013 实测 ~5000-6000 token，4000 截断/空。"""

_PERSON_SYSTEM_INSTRUCTION = (
    "请梳理书中主要人物之间的关系网，只依据原文，不臆测、不编造书里不存在的关系。\n"
    "严格输出 JSON（不要别的话、不要 markdown 代码围栏）：\n"
    '{"nodes": [{"name": "人物名"}], '
    '"edges": [{"source": "人物A", "target": "人物B", '
    '"relation": "关系类型（君臣/政敌/父子/同盟/同僚/亲族/师徒等）", '
    '"strength": 关系亲疏强度1到5的整数, '
    '"evidence": "证明这条关系的原文逐字片段，原样摘录不改写"}]}\n'
    "strength 按原文体现的亲疏判：5=最紧密（父子/生死同盟/夫妻），3=一般（同僚/君臣），"
    "1=最疏远（点头之交/远亲/敌对但少交集）。只据原文判，拿不准给 3。\n"
    "每条 edge 必须带 evidence，且 evidence 是原文里逐字出现的句子。"
    "source 和 target 必须是 nodes 里出现过的人物名。"
    "书里没有直接关系的人物之间不要硬连。"
    "只列最重要的核心人物与关系（最多约 30 条边），宁可少而准，不必穷尽次要人物——"
    "图太大既看不清也容易超出输出长度。"
)

# 概念图：人物图的跨题材投影（exp-014 GO）。分析单位从人物换成概念，
# 关系类型换成概念逻辑关系，其余机制（JSON 形态 + 边粒度证据）完全一致。
_CONCEPT_SYSTEM_INSTRUCTION = (
    "请梳理书中核心概念之间的关系网，只依据原文，不臆测、不编造书里不存在的关系。\n"
    "严格输出 JSON（不要别的话、不要 markdown 代码围栏）：\n"
    '{"nodes": [{"name": "概念名"}], '
    '"edges": [{"source": "概念A", "target": "概念B", '
    '"relation": "关系类型（定义/包含/对立/因果/递进/支撑等）", '
    '"strength": 关联紧密度1到5的整数, '
    '"evidence": "证明这条关系的原文逐字片段，原样摘录不改写"}]}\n'
    "strength 按原文里两概念的关联紧密度判：5=最紧密（定义/包含/强因果），3=一般"
    "（支撑/递进），1=最弱（偶尔并提/弱关联）。只据原文判，拿不准给 3。\n"
    "每条 edge 必须带 evidence，且 evidence 是原文里逐字出现的句子。"
    "source 和 target 必须是 nodes 里出现过的概念名。"
    "书里没有直接论证关系的概念之间不要硬连。"
    "只列最重要的核心概念与关系（最多约 30 条边），宁可少而准，不必穷尽次要概念——"
    "图太大既看不清也容易超出输出长度。"
)

_INSTRUCTION_BY_UNIT: dict[str, str] = {
    "person": _PERSON_SYSTEM_INSTRUCTION,
    "concept": _CONCEPT_SYSTEM_INSTRUCTION,
}

_USER_MSG_BY_UNIT: dict[str, str] = {
    "person": "请抽取这本书的人物关系图。",
    "concept": "请抽取这本书的概念关系图。",
}

@dataclass(frozen=True)
class CharacterGraphResult:
    """抽取结果。``edges`` 每条含 source/target/relation/evidence + 校验后的
    verified/chapter/match_score。"""

    nodes: list[str]
    edges: list[dict[str, Any]]
    duration_ms: int
    input_tokens: int
    output_tokens: int


def _resp_field(resp: Any, field: str) -> Any:
    if resp is None:
        return None
    if isinstance(resp, dict):
        return resp.get(field)
    return getattr(resp, field, None)


def _coerce_nodes(raw_nodes: Any) -> list[str]:
    """nodes 可能是 [{"name": "X"}] 或 ["X"]——都归一成去重的 list[str]。"""
    names: list[str] = []
    seen: set[str] = set()
    if not isinstance(raw_nodes, list):
        return names
    for item in raw_nodes:
        name = ""
        if isinstance(item, dict):
            name = str(item.get("name", "")).strip()
        elif isinstance(item, str):
            name = item.strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def _coerce_edges(raw_edges: Any) -> list[dict[str, Any]]:
    """保留 source/target/relation 齐全的边；evidence 可缺（缺则 verified 自然 False）。"""
    edges: list[dict[str, Any]] = []
    if not isinstance(raw_edges, list):
        return edges
    for item in raw_edges:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source", "")).strip()
        target = str(item.get("target", "")).strip()
        relation = str(item.get("relation", "")).strip()
        if not source or not target or not relation:
            continue
        raw_strength = item.get("strength")
        strength = raw_strength if isinstance(raw_strength, int) else 3
        strength = max(1, min(5, strength))  # 夹到 1-5，缺失/越界落 3 档
        edges.append({
            "source": source,
            "target": target,
            "relation": relation,
            "strength": strength,
            "evidence": str(item.get("evidence", "")).strip(),
        })
    return edges


def _finalize_nodes(nodes: list[str], edges: list[dict[str, Any]]) -> list[str]:
    """把边端点里没在 nodes 出现的人物/概念补进 nodes（模型偶尔漏列）。"""
    known = set(nodes)
    for e in edges:
        for endpoint in (e["source"], e["target"]):
            if endpoint not in known:
                known.add(endpoint)
                nodes.append(endpoint)
    return nodes


# 穷尽化(1.4)合并后的边数安全帽——远高于旧单次的 30 帽,只防爆、不当摘要用。
EXHAUSTIVE_MAX_EDGES = 300


def _merge_graph_segments(
    segments: list[tuple[list[str], list[dict[str, Any]]]],
    *,
    max_edges: int = EXHAUSTIVE_MAX_EDGES,
) -> tuple[list[str], list[dict[str, Any]]]:
    """REDUCE：把逐段抽出的 (nodes, edges) 合并成一张去重的图（WP-exhaustive-extraction）。

    - **节点**：并集，保序去重。
    - **边**：按规范化无向 key ``(min(s,t), max(s,t), relation)`` 去重——同一对人物的同一种
      关系只留一条；合并时保 ``strength`` 最大、优先留**有 evidence** 的那条（evidence 要逐字
      核验，没 evidence 的边 verified 永远 False）。每条边保留它首次出现时带的 ``chapter``。
    - **不设 30 帽**（穷尽）；只留高位 ``max_edges`` 安全帽防爆，超了按 strength 降序截断。

    纯函数、不调 LLM——REDUCE 的正确性先在这里钉死，MAP（逐段 LLM 抽边）再往上接。
    """
    nodes: list[str] = []
    seen_nodes: set[str] = set()
    by_key: dict[tuple[str, str, str], dict[str, Any]] = {}

    for seg_nodes, seg_edges in segments:
        for n in seg_nodes:
            if n and n not in seen_nodes:
                seen_nodes.add(n)
                nodes.append(n)
        for raw in seg_edges:
            source = str(raw.get("source", "")).strip()
            target = str(raw.get("target", "")).strip()
            relation = str(raw.get("relation", "")).strip()
            if not source or not target or not relation:
                continue
            a, b = (source, target) if source <= target else (target, source)
            key = (a, b, relation)
            existing = by_key.get(key)
            if existing is None:
                by_key[key] = dict(raw)
                continue
            # 已有同 key 边：没 evidence 而新边有 → 整条换成有 evidence 的；否则保 strength 最大
            if not existing.get("evidence") and raw.get("evidence"):
                by_key[key] = dict(raw)
            else:
                new_s = raw.get("strength", 3)
                if isinstance(new_s, int) and new_s > existing.get("strength", 3):
                    existing["strength"] = new_s

    edges = sorted(
        by_key.values(),
        key=lambda e: e.get("strength", 3) if isinstance(e.get("strength"), int) else 3,
        reverse=True,
    )
    if len(edges) > max_edges:
        edges = edges[:max_edges]
    return _finalize_nodes(nodes, edges), edges


def _salvage_truncated_graph(
    text: str,
) -> tuple[list[str], list[dict[str, Any]]] | None:
    """从截断的 JSON 里抢救已吐完的完整边对象。

    flash 把 reasoning_content 算进 max_tokens，图一大内容就可能被截断成半截 JSON，
    整段 ``json.loads`` 必败。与其整张图丢掉返 502，不如把 ``"edges"`` 数组里已经
    闭合的 ``{...}`` 逐个抠出来拼个部分图——用户至少看到大部分关系。
    """
    raw_edges = salvage_closed_objects(text, '"edges"') or []
    edges = _coerce_edges(raw_edges)
    if not edges:
        return None
    return _finalize_nodes([], edges), edges


def _parse_graph(text: str) -> tuple[list[str], list[dict[str, Any]]] | None:
    """解析模型输出的图 JSON。正常失败 → 抢救截断的边 → 仍不行返 None。"""
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
        edges = _coerce_edges(obj.get("edges"))
        if edges:
            return _finalize_nodes(_coerce_nodes(obj.get("nodes")), edges), edges
    # 兜底：截断输出抢救完整的边（reasoning 吃 token 致内容截断时不全军覆没）
    salvaged = _salvage_truncated_graph(candidate)
    if salvaged is not None:
        logger.warning(
            "character_graph: 主解析失败，从截断输出抢救到 %d 条边", len(salvaged[1])
        )
        return salvaged
    logger.warning("character_graph parse failed; raw head=%r", candidate[:200])
    return None


def extract_character_graph(
    *,
    full_text: str,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    unit: str = "person",
    max_tokens: int = DEFAULT_GRAPH_MAX_TOKENS,
    session_id: str | None = None,
) -> CharacterGraphResult | None:
    """整本进 context 抽一次关系图；失败返 ``None``。

    ``unit`` 选分析单位：``"person"`` 抽人物关系图（默认），``"concept"`` 抽概念
    关系图（exp-014 GO 的跨题材投影）。两者共用同一抽取/解析/边校验机制，只换
    system 指令里的"节点是什么 + 关系类型"。未知 unit 回退 person。

    Args:
        full_text: 整本书 cleaned 原文。
        chunks: 全书 chunk dict（含 ``chunk_id`` / ``chapter`` / ``text``），给边
            evidence 做证据登记表 + 提供章号 ground truth。
        llm_client: duck-typed LLM client（同 AgentLoop / long_context）。
        model: 模型名。
        unit: ``"person"`` | ``"concept"``。决定抽人物图还是概念图。
        max_tokens: 单次 LLM 调用 max_tokens（默认 8000，图输出长）。
        session_id: 给 L2 缓存用；None 时降级直调。

    Returns:
        成功 :class:`CharacterGraphResult`；任意失败 ``None``。
    """
    start = time.monotonic()
    instruction = _INSTRUCTION_BY_UNIT.get(unit, _PERSON_SYSTEM_INSTRUCTION)
    user_msg = _USER_MSG_BY_UNIT.get(unit, _USER_MSG_BY_UNIT["person"])
    system = build_longctx_system(full_text, instruction)
    messages = [{"role": "user", "content": user_msg}]

    try:
        response = _invoke_client(
            llm_client,
            model=model,
            system=system,
            tools=[],
            messages=messages,
            max_tokens=max_tokens,
            cache_enabled=session_id is not None,
        )
    except Exception as exc:  # noqa: BLE001 — 包死返 None
        logger.warning(
            "character_graph LLM call raised %s: %s; returning None",
            type(exc).__name__, exc,
        )
        return None

    input_tokens, output_tokens = llm_client.extract_usage_tokens(response)
    final_text = llm_client.extract_final_text(response)

    parsed = _parse_graph(final_text)
    if parsed is None:
        logger.warning("character_graph parse failed; returning None")
        return None
    nodes, edges = parsed

    # 边粒度证据校验：每条 edge 的 evidence 当一条 citation 过 verify_citations。
    evidence = build_evidence_map(chunks)
    edge_citations = [{"snippet": e["evidence"]} for e in edges]
    verify_citations(edge_citations, evidence)
    for edge, vc in zip(edges, edge_citations, strict=True):
        edge["verified"] = bool(vc.get("verified", False))
        edge["match_score"] = vc.get("match_score", 0.0)
        # 章号纠偏：命中 chunk 的真章号才是 ground truth（同 long_context）。
        cid = vc.get("chunk_id")
        true_chapter = evidence.get(cid, {}).get("chapter") if cid else None
        edge["chapter"] = true_chapter if isinstance(true_chapter, int) and true_chapter > 0 else 0

    duration_ms = int((time.monotonic() - start) * 1000)
    return CharacterGraphResult(
        nodes=nodes,
        edges=edges,
        duration_ms=duration_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


# 穷尽化(1.4)分段预算:每段原文的字符上限,控单次 LLM 输入大小。一章范围量级。
SEGMENT_CHAR_BUDGET = 40000

# 逐段抽取的并发数——三国 ~16 段串行要 8+ 分钟(延迟是产品级问题),必须并发。
DEFAULT_SEGMENT_WORKERS = 6
ENV_SEGMENT_WORKERS = "BOOKSCOPE_GRAPH_SEGMENT_WORKERS"


def _resolve_segment_workers(explicit: int | None) -> int:
    """决定逐段抽取并发数：构造参数 > 环境变量 > 默认 6；< 1 兜底成 1（串行）。"""
    if explicit is not None:
        return max(1, explicit)
    raw = os.environ.get(ENV_SEGMENT_WORKERS)
    if not raw or not raw.strip():
        return DEFAULT_SEGMENT_WORKERS
    try:
        return max(1, int(raw))
    except ValueError:
        logger.warning(
            "Invalid %s=%r; 用默认 %d", ENV_SEGMENT_WORKERS, raw, DEFAULT_SEGMENT_WORKERS
        )
        return DEFAULT_SEGMENT_WORKERS


def _verify_edges_against_chunks(
    edges: list[dict[str, Any]], chunks: list[dict[str, Any]]
) -> None:
    """对每条边的 evidence 跑 verify_citations（逐字核验）+ 章号纠偏。原地改 edges。"""
    evidence = build_evidence_map(chunks)
    edge_citations = [{"snippet": e.get("evidence", "")} for e in edges]
    verify_citations(edge_citations, evidence)
    for edge, vc in zip(edges, edge_citations, strict=True):
        edge["verified"] = bool(vc.get("verified", False))
        edge["match_score"] = vc.get("match_score", 0.0)
        cid = vc.get("chunk_id")
        true_chapter = evidence.get(cid, {}).get("chapter") if cid else None
        if isinstance(true_chapter, int) and true_chapter > 0:
            edge["chapter"] = true_chapter
        else:
            edge.setdefault("chapter", 0)


def _build_segment_system(segment_text: str, known_names: list[str], unit: str) -> str:
    """逐段抽边的 system：已知人物清单 + 本段原文 + "本段内穷尽抽关系"指令。"""
    word = "概念" if unit == "concept" else "人物"
    rel_hint = (
        "（定义/包含/对立/因果/递进/支撑等）"
        if unit == "concept"
        else "（君臣/政敌/父子/同盟/同僚/亲族/师徒等）"
    )
    names = "、".join(known_names[:120]) if known_names else "（无预设清单，自行从本段识别）"
    return (
        f"你在读一本书的其中一段原文。已知{word}有：{names}。\n"
        f"只从下面这段原文里，抽这些{word}之间【在本段出现】的关系——本段内尽量抽全、"
        f"不设条数上限，宁可多列也别漏。只依据本段原文、不臆测、不用本段外的知识。\n"
        "严格输出 JSON（不要别的话、不要 markdown 代码围栏）：\n"
        '{"edges": [{"source": "名A", "target": "名B", '
        f'"relation": "关系类型{rel_hint}", '
        '"strength": 关系亲疏1到5整数, '
        '"evidence": "本段原文里逐字出现的句子，原样摘录不改写"}]}\n'
        f"source / target 尽量用上面清单里的名字。本段没有可依据原文的关系就返回 "
        '{"edges": []}。\n\n'
        f"=== 本段原文 ===\n{segment_text}"
    )


def extract_character_graph_exhaustive(
    *,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    known_characters: list[str] | None = None,
    unit: str = "person",
    max_tokens: int = DEFAULT_GRAPH_MAX_TOKENS,
    char_budget: int = SEGMENT_CHAR_BUDGET,
    cache_enabled: bool = True,
    max_workers: int | None = None,
) -> CharacterGraphResult | None:
    """穷尽化（1.4）：逐段抽边 + 合并，不再单次摘要硬帽 30 条（WP-exhaustive-extraction）。

    把全书按字符预算切段，每段单独抽段内关系（段小、可段内穷尽、不设上限），再用
    :func:`_merge_graph_segments` 跨段去重合并，最后一次性 verify。节点底座来自 ``chunks``
    里出现的人物 + 边端点；``known_characters``（上传时 KG 的 canonical 角色清单）喂进每段
    prompt 当锚，减少别名碎裂。任一段失败跳过该段，不让整图全军覆没；全失败返 ``None``。

    缓存（``cache_enabled``，默认开）：逐段调用走 L2，**同一本书重看关系图直接命中、不重跑
    N 段**（省钱省延迟——这是作者反复强调的缓存目标）。与单次摘要"关缓存防 poison"守卫不冲突：
    map-reduce 下某段坏 JSON 只是**跳过该段**（graceful），不像单次那样一坏全挂，所以这里缓存
    是安全的。每段 system 含该段原文 → L2 key 各异、不会串段。
    """
    start = time.monotonic()
    segments = segment_chunks(chunks, char_budget)
    if not segments:
        return None
    known = known_characters or []

    def _run_segment(
        seg: list[dict[str, Any]],
    ) -> tuple[tuple[list[str], list[dict[str, Any]]] | None, int, int]:
        """抽一段：返 (parsed|None, in_tok, out_tok)。单段失败 → (None, 0, 0)，不拖垮整图。"""
        seg_text = "".join(str(c.get("text", "")) for c in seg)
        system = _build_segment_system(seg_text, known, unit)
        try:
            response = _invoke_client(
                llm_client,
                model=model,
                system=system,
                tools=[],
                messages=[{"role": "user", "content": "请抽本段关系。"}],
                max_tokens=max_tokens,
                cache_enabled=cache_enabled,
            )
        except Exception as exc:  # noqa: BLE001 — 单段失败跳过
            logger.warning(
                "exhaustive graph: 段 LLM 调用抛 %s: %s；跳过该段",
                type(exc).__name__, exc,
            )
            return None, 0, 0
        it, ot = llm_client.extract_usage_tokens(response)
        return _parse_graph(llm_client.extract_final_text(response)), it or 0, ot or 0

    # 并发逐段抽——串行 N 段在三国是 8+ 分钟，必须并发（延迟是产品级问题）。
    workers = _resolve_segment_workers(max_workers)
    if workers <= 1 or len(segments) <= 1:
        outs = [_run_segment(s) for s in segments]
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            outs = list(ex.map(_run_segment, segments))

    seg_results: list[tuple[list[str], list[dict[str, Any]]]] = []
    in_tok = 0
    out_tok = 0
    for parsed, it, ot in outs:
        in_tok += it
        out_tok += ot
        if parsed is not None:
            seg_results.append(parsed)

    if not seg_results:
        return None
    nodes, edges = _merge_graph_segments(seg_results)
    _verify_edges_against_chunks(edges, chunks)
    return CharacterGraphResult(
        nodes=nodes,
        edges=edges,
        duration_ms=int((time.monotonic() - start) * 1000),
        input_tokens=in_tok,
        output_tokens=out_tok,
    )


__all__ = [
    "CharacterGraphResult",
    "DEFAULT_GRAPH_MAX_TOKENS",
    "extract_character_graph",
    "extract_character_graph_exhaustive",
]
