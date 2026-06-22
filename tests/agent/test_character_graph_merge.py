"""_merge_graph_segments —— 穷尽化(1.4)REDUCE 合并的纯函数单测。

钉死合并语义:节点并集去重、边按规范化无向 key 去重、保 strength 最大 + 有 evidence 优先、
不设 30 帽(穷尽)。不调 LLM。
"""

from __future__ import annotations

from bookscope.agent.character_graph import (
    EXHAUSTIVE_MAX_EDGES,
    _merge_graph_segments,
)


def _edge(
    source: str,
    target: str,
    relation: str,
    *,
    strength: int = 3,
    evidence: str = "",
    chapter: int | None = None,
) -> dict:
    e: dict = {
        "source": source,
        "target": target,
        "relation": relation,
        "strength": strength,
        "evidence": evidence,
    }
    if chapter is not None:
        e["chapter"] = chapter
    return e


def test_merge_unions_nodes_dedup() -> None:
    segs = [
        (["刘备", "关羽"], []),
        (["关羽", "张飞"], []),
    ]
    nodes, _ = _merge_graph_segments(segs)
    assert nodes == ["刘备", "关羽", "张飞"]  # 并集、保序、去重


def test_merge_dedup_same_pair_relation_undirected() -> None:
    """同一对人物同一关系,跨段、且 source/target 反向 → 合并成一条。"""
    segs = [
        (["刘备", "关羽"], [_edge("刘备", "关羽", "君臣", strength=4, evidence="桃园")]),
        (["关羽", "刘备"], [_edge("关羽", "刘备", "君臣", strength=5)]),
    ]
    _, edges = _merge_graph_segments(segs)
    assert len(edges) == 1
    # 保 strength 最大;原有有 evidence 的那条不被无 evidence 的覆盖
    assert edges[0]["strength"] == 5
    assert edges[0]["evidence"] == "桃园"


def test_merge_prefers_edge_with_evidence() -> None:
    """已有边无 evidence、新边有 → 整条换成有 evidence 的(evidence 要逐字核验)。"""
    segs = [
        (["甲", "乙"], [_edge("甲", "乙", "同僚", strength=4, evidence="")]),
        (["甲", "乙"], [_edge("甲", "乙", "同僚", strength=2, evidence="原文片段")]),
    ]
    _, edges = _merge_graph_segments(segs)
    assert len(edges) == 1
    assert edges[0]["evidence"] == "原文片段"


def test_merge_keeps_different_relations_between_same_pair() -> None:
    segs = [
        (["甲", "乙"], [_edge("甲", "乙", "君臣"), _edge("甲", "乙", "亲族")]),
    ]
    _, edges = _merge_graph_segments(segs)
    assert len(edges) == 2  # 不同关系不合并


def test_merge_no_30_cap_keeps_all() -> None:
    """旧单次的 30 帽不再生效:40 条边全留(< 安全帽)。"""
    edges_in = [_edge(f"p{i}", f"p{i}b", "同僚") for i in range(40)]
    _, edges = _merge_graph_segments([([], edges_in)])
    assert len(edges) == 40


def test_merge_safety_cap_truncates_by_strength() -> None:
    """超高位安全帽 → 按 strength 降序截断(防爆,不当摘要)。"""
    weak = [_edge(f"w{i}", f"w{i}b", "弱", strength=1) for i in range(EXHAUSTIVE_MAX_EDGES)]
    strong = [_edge("强A", "强B", "强", strength=5)]
    _, edges = _merge_graph_segments([(([]), weak + strong)])
    assert len(edges) == EXHAUSTIVE_MAX_EDGES
    # 最强的那条必须留下(没被截掉)
    assert any(e["relation"] == "强" for e in edges)


def test_merge_drops_incomplete_edges() -> None:
    segs = [([], [{"source": "甲", "target": "", "relation": "x"}, _edge("甲", "乙", "同僚")])]
    _, edges = _merge_graph_segments(segs)
    assert len(edges) == 1
    assert edges[0]["target"] == "乙"
