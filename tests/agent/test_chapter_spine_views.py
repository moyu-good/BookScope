"""章脉派生视图(ADR-010 第3步)单测 —— 纯投影/聚合,不调 LLM。"""

from __future__ import annotations

from bookscope.agent.chapter_spine_views import (
    narrative_curve_from_spine,
    pacing_from_spine,
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
