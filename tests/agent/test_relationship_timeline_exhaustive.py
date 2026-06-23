"""relationship_timeline.generate_relationship_timeline_exhaustive 单测（穷尽化 1.4）。

monkeypatch 该模块里的 run_segments 返回造好的两段数据（不调真 LLM），验证：
同一对关系跨段的 points / turning_points 按章并集合并；转折 evidence 过核验 + 章号纠偏；
空 → None。
"""

from __future__ import annotations

from bookscope.agent import relationship_timeline as rt

# chunk 文本含转折 evidence 片段，好让 _verify_turning_points 逐字命中
_CHUNKS = [
    {"chunk_id": "c1", "chapter": 3,
     "text": "刘备三顾茅庐，终于在草庐中见到诸葛亮，二人促膝长谈，相见恨晚。"},
    {"chunk_id": "c2", "chapter": 9,
     "text": "白帝城中，刘备病重，托孤于诸葛亮，泣曰：君才十倍曹丕，必能安国。"},
]


def test_merges_pairs_across_segments_and_verifies(monkeypatch):
    """两段各抽到同一对「刘备-诸葛亮」的不同章子点 → 按章并集；转折逐字核验 + 真章号纠偏。"""
    # 段 1：初识（章 3）；段 2：托孤（章 9）。同一对关系，子点应并集。
    seg1 = [
        {
            "a": "刘备", "b": "诸葛亮", "relation": "君臣",
            "points": [{"chapter": 3, "strength": 6}],
            "turning_points": [
                {"chapter": 3, "change": "三顾茅庐初识",
                 "evidence": "刘备三顾茅庐，终于在草庐中见到诸葛亮，二人促膝长谈，相见恨晚"},
            ],
        },
    ]
    seg2 = [
        {
            "a": "诸葛亮", "b": "刘备", "relation": "ignored",  # 无向同一对；标量保先出现
            "points": [{"chapter": 9, "strength": 10}],
            "turning_points": [
                {"chapter": 9, "change": "白帝城托孤",
                 "evidence": "白帝城中，刘备病重，托孤于诸葛亮"},
            ],
        },
    ]
    monkeypatch.setattr(rt, "run_segments", lambda **_k: [seg1, seg2])

    r = rt.generate_relationship_timeline_exhaustive(
        chunks=_CHUNKS, llm_client=object(), model="m",
    )
    assert r is not None
    assert len(r) == 1  # 跨段同一对 → 合一
    rel = r[0]
    assert rel["relation"] == "君臣"  # 标量保先出现段的值
    assert [p["chapter"] for p in rel["points"]] == [3, 9]  # 子点跨段并集 + 升序
    tps = rel["turning_points"]
    assert [t["chapter"] for t in tps] == [3, 9]
    assert tps[0]["verified"] is True and tps[0]["chapter"] == 3  # 命中 c1，真章号纠偏
    assert tps[1]["verified"] is True and tps[1]["chapter"] == 9  # 命中 c2


def test_empty_returns_none(monkeypatch):
    """所有段都没抽到关系 → 合并空 → None。"""
    monkeypatch.setattr(rt, "run_segments", lambda **_k: [[], []])
    r = rt.generate_relationship_timeline_exhaustive(
        chunks=_CHUNKS, llm_client=object(), model="m",
    )
    assert r is None
