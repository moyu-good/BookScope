"""subplot_weave 穷尽化变体单测：跨段合并支线（并活跃章）+ 交汇去重 + 双端核验。

monkeypatch 掉模块里的 ``run_segments`` 喂造好的分段编织图，verify 真跑——chunks 的 text
含支线 / 交汇的 evidence 原文片段，好让 verify_citations 命中。不调真 LLM。
"""

from __future__ import annotations

from typing import Any

import bookscope.agent.subplot_weave as sw


def _chunks() -> list[dict[str, Any]]:
    return [
        {"chunk_id": "c1", "chapter": 1, "text": "甲线索在第一章铺开"},
        {"chunk_id": "c2", "chapter": 5, "text": "乙线索在第五章推进"},
        {"chunk_id": "c3", "chapter": 5, "text": "甲乙两线在第五章交汇了"},
    ]


def test_subplot_exhaustive_merges_and_verifies(monkeypatch) -> None:  # noqa: ANN001
    seg1 = {
        "subplots": [
            {"name": "甲线", "active_chapters": [1], "evidence": "甲线索在第一章铺开"}
        ],
        "intersections": [],
    }
    seg2 = {
        "subplots": [
            {"name": "甲线", "active_chapters": [5], "evidence": ""},  # 同名 → 并活跃章
            {"name": "乙线", "active_chapters": [5], "evidence": "乙线索在第五章推进"},
        ],
        "intersections": [
            {
                "subplots": ["甲线", "乙线"],
                "chapter": 5,
                "a_evidence": "甲乙两线在第五章交汇了",
                "b_evidence": "乙线索在第五章推进",
            }
        ],
    }
    monkeypatch.setattr(sw, "run_segments", lambda **_kw: [[seg1], [seg2]])
    out = sw.generate_subplot_weave_exhaustive(
        chunks=_chunks(), llm_client=object(), model="m"
    )
    assert out is not None
    assert [s["name"] for s in out["subplots"]] == ["甲线", "乙线"]
    jia = out["subplots"][0]
    assert jia["active_chapters"] == [1, 5]  # 跨段并集升序
    assert jia["verified"] is True  # 先出现段缺证据,后段补上 → 核过
    assert len(out["intersections"]) == 1  # 双端都核过 → 保留
    it = out["intersections"][0]
    assert it["a_verified"] and it["b_verified"]


def test_subplot_exhaustive_dedups_intersections(monkeypatch) -> None:  # noqa: ANN001
    inter = {
        "subplots": ["甲线", "乙线"],
        "chapter": 5,
        "a_evidence": "甲乙两线在第五章交汇了",
        "b_evidence": "乙线索在第五章推进",
    }
    seg = {
        "subplots": [
            {"name": "甲线", "active_chapters": [5], "evidence": "甲线索在第一章铺开"},
            {"name": "乙线", "active_chapters": [5], "evidence": "乙线索在第五章推进"},
        ],
        "intersections": [inter],
    }
    # 同一条交汇在两段都被抽到 → 按 (支线对, 章) 去重剩一条
    monkeypatch.setattr(sw, "run_segments", lambda **_kw: [[seg], [dict(seg)]])
    out = sw.generate_subplot_weave_exhaustive(
        chunks=_chunks(), llm_client=object(), model="m"
    )
    assert out is not None
    assert len(out["intersections"]) == 1


def test_subplot_exhaustive_empty_returns_none(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(sw, "run_segments", lambda **_kw: [[], []])
    assert (
        sw.generate_subplot_weave_exhaustive(
            chunks=_chunks(), llm_client=object(), model="m"
        )
        is None
    )
