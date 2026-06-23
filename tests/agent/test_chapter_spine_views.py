"""章脉派生视图(ADR-010 第3步)单测 —— 纯投影/聚合,不调 LLM。"""

from __future__ import annotations

from bookscope.agent.chapter_spine_views import (
    narrative_curve_from_spine,
    narrative_flow_from_spine,
    pacing_from_spine,
    relationship_graph_from_spine,
    timeline_from_spine,
)


def _spine() -> list[dict]:
    return [
        {"chapter": 2, "tension": 8, "sentiment": -3, "pov": "甲", "mainline": True,
         "events": [{"event": "甲打乙", "evidence": "x"}], "evidence": "甲打了乙",
         "verified": True, "match_score": 1.0},
        {"chapter": 1, "tension": 2, "sentiment": 1, "pov": "群像", "mainline": False,
         "events": [], "evidence": "开篇", "verified": False, "match_score": 0.3},
    ]


def test_narrative_curve_from_spine_projects_and_sorts() -> None:
    out = narrative_curve_from_spine(_spine())
    assert [c["chapter"] for c in out] == [1, 2]          # 升序
    c2 = next(c for c in out if c["chapter"] == 2)
    assert c2["tension"] == 8 and c2["sentiment"] == -3
    assert c2["pov"] == "甲" and c2["mainline"] is True
    assert c2["verified"] is True and c2["evidence"] == "甲打了乙"


def test_narrative_curve_skips_bad_chapter() -> None:
    out = narrative_curve_from_spine([{"chapter": "x", "tension": 5}, {"chapter": 3, "tension": 5}])
    assert [c["chapter"] for c in out] == [3]


def test_pacing_from_spine_rescales_and_notes() -> None:
    out = pacing_from_spine(_spine())
    c2 = next(c for c in out if c["chapter"] == 2)
    assert c2["tension"] == 4          # 8/10 → round(8/2)=4,钳 1-5
    assert c2["note"] == "甲打乙"      # 取第一个事件
    c1 = next(c for c in out if c["chapter"] == 1)
    assert c1["tension"] == 1          # 2 → round(1)=1
    assert c1["note"] == "开篇"        # 无事件退 evidence


def test_pacing_tension_clamped_to_1_5() -> None:
    spine = [{"chapter": 1, "tension": 0}, {"chapter": 2, "tension": 10}]
    out = pacing_from_spine(spine)
    assert out[0]["tension"] == 1      # 0 → 钳到下限 1
    assert out[1]["tension"] == 5      # 10/2=5


# ── 章级锚视图(出路 B)─────────────────────────────────────────────────────
def _rel_spine() -> list[dict]:
    return [
        {"chapter": 1, "present": ["刘备", "关羽", "张飞"],
         "relations": [{"pair": ["刘备", "关羽"], "note": "结义"},
                       {"pair": ["关羽", "刘备"], "note": "再提"}]},  # 乙-甲 同对,应合并
        {"chapter": 2, "present": ["刘备", "曹操"],
         "relations": [{"pair": ["刘备", "曹操"], "note": "对峙"}]},
    ]


def test_relationship_graph_aggregates_edges_undirected() -> None:
    g = relationship_graph_from_spine(_rel_spine())
    names = {n["name"] for n in g["nodes"]}
    assert names == {"刘备", "关羽", "张飞", "曹操"}
    # 刘备-关羽:章1 两条(含 乙-甲)合成一条边,只记章1 → weight 1
    lk = next(e for e in g["edges"] if {e["source"], e["target"]} == {"刘备", "关羽"})
    assert lk["chapters"] == [1] and lk["weight"] == 1
    assert "结义" in lk["notes"] and "再提" in lk["notes"]
    # 边不带 upfront evidence(出路 B)
    assert "evidence" not in lk


def test_narrative_flow_present_and_pairs() -> None:
    out = narrative_flow_from_spine(_rel_spine())
    assert [c["chapter"] for c in out] == [1, 2]
    c1 = out[0]
    assert c1["present"] == ["刘备", "关羽", "张飞"]
    assert len(c1["pairs"]) == 1                       # 乙-甲 去重成一对
    assert {c1["pairs"][0]["a"], c1["pairs"][0]["b"]} == {"刘备", "关羽"}


def test_timeline_flattens_events_by_chapter() -> None:
    spine = [
        {"chapter": 2, "events": [{"event": "对峙", "evidence": "x"}]},
        {"chapter": 1, "events": [{"event": "结义", "evidence": "y"}, {"event": "起兵"}]},
    ]
    out = timeline_from_spine(spine)
    assert [e["chapter"] for e in out] == [1, 1, 2]    # 按章升序摊平
    assert [e["event"] for e in out] == ["结义", "起兵", "对峙"]
    assert [e["order"] for e in out] == [1, 2, 3]
    assert "evidence" not in out[0]                    # 证据点开现取
