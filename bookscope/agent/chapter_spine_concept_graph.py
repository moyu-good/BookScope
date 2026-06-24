"""概念关系图 = 章脉派生(轻 LLM)。ADR-010 出路 B 的一个视图。

**为什么改章脉派生**:概念之间的勾连天生**跨章**——一个概念在第三章提出、第八章用来反驳
另一个概念、第十五章又被某个更大的框架收编。这种关系藏在两段不同的论证里,**逐段看不见**。
老实现概念图走 ``extract_character_graph_exhaustive``,按字符预算把全书切段、每段单独抽段内
关系再合并;每段只看得见自己那几章,跨段的概念关联系统性漏报。这是定义级错——概念关系的命根子
就是跨段,而 map-reduce 恰恰把跨段切断了。

做法:从章脉**每章 claims**(理论书概念维,``genre="theory"`` 才抽)收全书主张清单当紧凑输入,
**一次全局 LLM 调用**让模型先从这些主张里识别核心概念、再推出概念之间的关系网。一次看全书既不像
map-reduce 跨段瞎、也不像整本喂原文大书截断——跨章的概念勾连就该这么抽。

**只对理论书**:概念维只在 ``genre="theory"`` 的章脉里有(``rec.get("claims")``);小说章脉没有
claims,这个视图返 ``None``。端点接线时这会和别处默认 fiction-genre 的共享 spine 分裂缓存——见
``concept_graph_from_spine`` docstring 的"端点接线"段。

**证据**:每条边锚到章脉里**真有这个概念论证**的章(LLM 自报哪章、用真章集校验防编),evidence
取那章章脉已核验的章级证据,verified 据"锚到的章是不是真在章脉里"。形态对齐 character-graph 端点
要的 ``{nodes:[名], edges:[{source, target, relation, strength, evidence, verified, chapter,
match_score}]}``(同 :class:`bookscope.api.schemas.GraphEdge`)。配对失败 / 解析不出 / 没 claims
→ 返 ``None``,端点照走(不 break)。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from bookscope.agent._internal.llm_cache import invoke_client_cached
from bookscope.agent.utils.json_parsing import (
    extract_first_json_object,
    salvage_closed_objects,
    strip_code_fence,
)

logger = logging.getLogger(__name__)

DEFAULT_GRAPH_MAX_TOKENS = 24000
"""边条数 ∝ 概念对数 + reasoning 头,给足防截断。

deepseek-v4-flash 是 reasoning 模型,reasoning_content 算进 max_tokens(见
[[reference_reasoning_model_token_budget]])。一次推理全书概念关系网,内容长 + reasoning 重;
给 24000 覆盖理论书几十个核心概念的关系网 + 余量,更大的书超了靠 ``_parse_graph`` 截断抢救兜底。"""

_MAX_CLAIMS_PER_CH = 5
"""每章 claims 取前几条进输入,够定位概念又不撑爆 input(同 chapter_spine_concept)。"""

_GRAPH_INSTR = (
    "下面 chapters 是一本理论 / 论说书逐章的主张(claims):每章列了这章提出 / 论证的核心主张,"
    "并标了章号。\n"
    "请通读全书主张,先识别贯穿全书的**核心概念**(术语 / 范畴 / 理论构件),再梳理这些概念"
    "**之间的关系网**——哪个概念定义 / 包含 / 支撑 / 对立 / 因果 / 递进于哪个概念。\n"
    "- 概念之间的关系常常**跨章**:一个概念在某章提出、在另一章才和别的概念勾连。请据全书主张"
    "判断,别只看单章。\n"
    "- 每条关系标 chapter:这条概念关系**最能被看出**的那一章章号(必须是上面出现过的真实章号)。\n"
    "- 只连主张里**确实有论证关联**的概念;书里没有直接关系的概念之间不要硬连。只据给出的主张、"
    "不编。\n"
    "- 宁可少而准:只列最重要的核心概念与关系(最多约 30 条边),图太大既看不清也容易超出输出长度。\n"
    "strength 按主张里两概念关联的紧密度判:5=最紧密(定义 / 包含 / 强因果),3=一般(支撑 / 递进),"
    "1=最弱(偶尔并提 / 弱关联)。拿不准给 3。\n"
    "relation 用一个词概括关系类型(定义 / 包含 / 对立 / 因果 / 递进 / 支撑 等)。\n"
    "source 和 target 必须是 nodes 里出现过的概念名。\n"
    "严格输出 JSON(别的话别说、别加 markdown 代码围栏):\n"
    '{"nodes":[{"name":"概念名"}],'
    '"edges":[{"source":"概念A","target":"概念B","relation":"关系类型","strength":1到5整数,'
    '"chapter":这条关系最能被看出的章号整数}]}'
)


def _collect_claims(
    spine: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], set[int], dict[int, str]]:
    """从章脉收 逐章主张清单 + 有主张的章集 + 章号→已核验证据。

    只取有 ``claims``(理论书概念维)的章——小说章脉没这个字段,自然收成空。原文证据不进输入
    (只在出结果时按章号取章脉那章已核验的 evidence)。返回 (digest, 有主张的章集, 章号→evidence)。
    """
    digest: list[dict[str, Any]] = []
    claim_chs: set[int] = set()
    evidence: dict[int, str] = {}
    for rec in spine:
        if not isinstance(rec, dict):
            continue
        ch = rec.get("chapter")
        if not isinstance(ch, int):
            continue
        cl = rec.get("claims")
        if not isinstance(cl, list):
            continue
        claims = [str(c).strip() for c in cl[:_MAX_CLAIMS_PER_CH] if str(c).strip()]
        if not claims:
            continue
        digest.append({"章": ch, "claims": claims})
        claim_chs.add(ch)
        evidence[ch] = str(rec.get("evidence", "")).strip()
    return digest, claim_chs, evidence


def _parse_graph(text: str) -> tuple[list[str], list[dict[str, Any]]] | None:
    """解析 ``{"nodes":[...],"edges":[...]}``;三层兜底(直解析 / 切首个对象 / 截断抢救)。

    成功返 (nodes, edges);彻底解析不出返 ``None``。nodes 归一成 list[str]、edges 原样
    (字段在 ``concept_graph_from_spine`` 里再清洗)。
    """
    raw = (text or "").strip()
    if not raw:
        return None
    candidate = strip_code_fence(raw)
    obj: Any = None
    try:
        obj = json.loads(candidate)
    except json.JSONDecodeError:
        sliced = extract_first_json_object(candidate)
        if sliced is not None:
            try:
                obj = json.loads(sliced)
            except json.JSONDecodeError:
                obj = None
    if isinstance(obj, dict) and isinstance(obj.get("edges"), list):
        return _coerce_nodes(obj.get("nodes")), obj["edges"]
    salvaged = salvage_closed_objects(candidate, '"edges"')
    if salvaged:
        logger.warning(
            "chapter_spine_concept_graph: 主解析失败,从截断抢救到 %d 条边", len(salvaged)
        )
        return [], salvaged
    return None


def _coerce_nodes(raw_nodes: Any) -> list[str]:
    """nodes 可能是 ``[{"name":"X"}]`` 或 ``["X"]``——都归一成去重的 list[str]。"""
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


def concept_graph_from_spine(
    *,
    spine: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    max_tokens: int = DEFAULT_GRAPH_MAX_TOKENS,
    cache_enabled: bool = True,
) -> dict[str, Any] | None:
    """章脉全书主张一次 LLM 推概念关系网 → ``{nodes, edges}``。无 claims / 失败返 ``None``。

    形态对齐 character-graph 端点要的:``nodes`` 是概念名 list[str];``edges`` 每条
    ``{source, target, relation, strength, evidence, verified, chapter, match_score}``
    (同 :class:`bookscope.api.schemas.GraphEdge`)。

    每条边的 chapter 必须是章脉里**真有主张**的章(LLM 自报,用真章集校验,锚不到真实章的边丢——
    防 LLM 编章号);evidence 取那章章脉已核验的章级证据;``verified=True`` 当且仅当锚到了真实章
    且那章有证据。source/target 都要落在 nodes 里(模型漏列的端点补进 nodes)。

    **端点接线**:概念维只在 ``genre="theory"`` 的章脉里有,所以端点调本视图前要
    ``get_or_build_spine(..., genre="theory")``。这会和别处(人物图等)默认 fiction-genre 的
    共享章脉**分裂缓存**——同一本书会建两条章脉(fiction 一条 / theory 一条)。这是已知取舍:
    理论书的概念图天然要 theory-spine,而人物图 / 节奏 / 时间线这些小说功能在理论书上本就不该用,
    分裂不浪费多少(理论书一般不会同时点人物图)。主 Claude 据此决定端点怎么接。
    """
    digest, claim_chs, evidence = _collect_claims(spine)
    if not claim_chs:
        return None  # 没 claims:小说章脉 / 没跑 theory 维,概念图不适用

    user_content = json.dumps({"chapters": digest}, ensure_ascii=False)
    try:
        resp = invoke_client_cached(
            llm_client,
            model=model,
            system=_GRAPH_INSTR,
            tools=[],
            messages=[{"role": "user", "content": user_content}],
            max_tokens=max_tokens,
            cache_enabled=cache_enabled,
        )
        text = llm_client.extract_final_text(resp)
    except Exception as exc:  # noqa: BLE001 — 调用失败降级返 None,不 break 端点
        logger.warning(
            "chapter_spine_concept_graph: 推理调用抛 %s: %s;返 None", type(exc).__name__, exc
        )
        return None

    parsed = _parse_graph(text)
    if parsed is None:
        return None
    nodes, raw_edges = parsed

    edges: list[dict[str, Any]] = []
    for e in raw_edges:
        if not isinstance(e, dict):
            continue
        source = str(e.get("source", "")).strip()
        target = str(e.get("target", "")).strip()
        relation = str(e.get("relation", "")).strip()
        if not source or not target or source == target or not relation:
            continue
        ch = e.get("chapter")
        anchored = isinstance(ch, int) and ch in claim_chs  # 锚到真有主张的章(防编)
        snip = evidence.get(ch, "") if anchored else ""
        raw_strength = e.get("strength")
        strength = raw_strength if isinstance(raw_strength, int) else 3
        strength = max(1, min(5, strength))  # 夹到 1-5,缺失 / 越界落 3 档
        edges.append({
            "source": source,
            "target": target,
            "relation": relation,
            "strength": strength,
            "evidence": snip,
            "verified": bool(anchored and snip),
            "chapter": ch if anchored else 0,
            "match_score": 1.0 if (anchored and snip) else 0.0,
        })

    if not edges:
        return None

    # 边端点里没在 nodes 出现的概念补进 nodes(模型偶尔漏列);保序去重。
    known = set(nodes)
    for e in edges:
        for endpoint in (e["source"], e["target"]):
            if endpoint not in known:
                known.add(endpoint)
                nodes.append(endpoint)

    edges.sort(key=lambda x: (-x["strength"], x["source"]))
    return {"nodes": nodes, "edges": edges}


__all__ = ["DEFAULT_GRAPH_MAX_TOKENS", "concept_graph_from_spine"]
