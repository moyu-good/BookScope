"""foreshadow_arcs 穷尽化变体单测：大段 map-reduce → 按（描述,埋点章）去重 → 两端核验。

monkeypatch 掉模块里的 ``run_segments`` 喂造好的分段弧列表，verify 真跑——chunks 的 text
含埋点 / 回收点 evidence 原文，好让 verify_citations 命中。不调真 LLM。
"""

from __future__ import annotations

from typing import Any

import bookscope.agent.foreshadow_arcs as fa


def _chunks() -> list[dict[str, Any]]:
    return [
        {"chunk_id": "c1", "chapter": 2, "text": "他袖中藏了一封密信"},  # 埋点
        {"chunk_id": "c2", "chapter": 9, "text": "密信终于被当众拆开"},  # 回收点
        {"chunk_id": "c3", "chapter": 3, "text": "墙上挂着一把旧剑"},  # 另一处埋点(断弧)
    ]


def test_foreshadow_exhaustive_dedups_sorts_verifies(monkeypatch) -> None:  # noqa: ANN001
    seg1 = [
        {
            "description": "密信",
            "setup_chapter": 2,
            "payoff_chapter": 9,
            "setup_evidence": "他袖中藏了一封密信",
            "payoff_evidence": "密信终于被当众拆开",
        },
        {
            "description": "旧剑",
            "setup_chapter": 3,
            "payoff_chapter": None,
            "setup_evidence": "墙上挂着一把旧剑",
            "payoff_evidence": "",
        },
    ]
    seg2 = [  # 密信跨段重复 → 应被去重
        {
            "description": "密信",
            "setup_chapter": 2,
            "payoff_chapter": 9,
            "setup_evidence": "他袖中藏了一封密信",
            "payoff_evidence": "密信终于被当众拆开",
        }
    ]
    monkeypatch.setattr(fa, "run_segments", lambda **_kw: [seg1, seg2])
    out = fa.generate_foreshadow_arcs_exhaustive(
        chunks=_chunks(), llm_client=object(), model="m"
    )
    assert out is not None
    # 去重后按 setup_chapter 升序 → 密信(2) 在前,旧剑(3) 在后
    assert [a["setup_chapter"] for a in out] == [2, 3]
    assert out[0]["status"] == "resolved"  # 密信回收点核过
    assert out[1]["status"] == "dangling"  # 旧剑断弧


def test_foreshadow_exhaustive_drops_unverified_setup(monkeypatch) -> None:  # noqa: ANN001
    seg = [
        {
            "description": "幻影",
            "setup_chapter": 1,
            "payoff_chapter": None,
            "setup_evidence": "书里根本没有这句话",
            "payoff_evidence": "",
        }
    ]
    monkeypatch.setattr(fa, "run_segments", lambda **_kw: [seg])
    out = fa.generate_foreshadow_arcs_exhaustive(
        chunks=_chunks(), llm_client=object(), model="m"
    )
    assert out == []  # 埋点核不过 → 整条丢


def test_foreshadow_exhaustive_empty_returns_none(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(fa, "run_segments", lambda **_kw: [[], []])
    assert (
        fa.generate_foreshadow_arcs_exhaustive(
            chunks=_chunks(), llm_client=object(), model="m"
        )
        is None
    )
