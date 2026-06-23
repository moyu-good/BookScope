"""timeline.generate_timeline_exhaustive 单测（穷尽化 1.4）。

monkeypatch 该模块里的 run_segments 返回造好的两段数据（不调真 LLM），验证：
同名事件跨段去重（保先出现）；合并后按真章号重排 + order 从 1 重编号；evidence 过核验；
空 → None。
"""

from __future__ import annotations

from bookscope.agent import timeline as tl

# chunk 文本含事件 evidence 片段，好让 _verify_events 逐字命中
_CHUNKS = [
    {"chunk_id": "c1", "chapter": 4, "text": "天宝十四载十一月，安禄山在范阳起兵反唐。"},
    {"chunk_id": "c2", "chapter": 9, "text": "灵宝之战唐军大败，潼关失守。"},
]


def test_dedups_events_and_renumbers(monkeypatch):
    """跨段同名事件去重；合并后按真章号重排，order 从 1 重编。"""
    # 段内 order 都从 1 起（跨段会撞）；「安禄山起兵」两段都抽到 → 去重保先出现。
    seg1 = [
        {"order": 1, "time": "天宝十四载十一月", "event": "安禄山起兵",
         "chapter": 8, "evidence": "天宝十四载十一月，安禄山在范阳起兵反唐。"},
    ]
    seg2 = [
        {"order": 1, "time": "", "event": "安禄山起兵",  # 跨段重复 → 去重
         "chapter": 8, "evidence": "重复的句子不影响去重"},
        {"order": 2, "time": "天宝十五载六月", "event": "灵宝之战大败",
         "chapter": 8, "evidence": "灵宝之战唐军大败，潼关失守。"},
    ]
    monkeypatch.setattr(tl, "run_segments", lambda **_k: [seg1, seg2])

    out = tl.generate_timeline_exhaustive(
        chunks=_CHUNKS, llm_client=object(), model="m",
    )
    assert out is not None
    assert len(out) == 2  # 「安禄山起兵」去重，只剩两条
    assert [e["event"] for e in out] == ["安禄山起兵", "灵宝之战大败"]  # 按真章号 4<9 排
    assert [e["order"] for e in out] == [1, 2]  # 重编号
    assert out[0]["time"] == "天宝十四载十一月"  # 保先出现段的标量值
    assert out[0]["verified"] is True and out[0]["chapter"] == 4  # 命中 c1，真章号纠偏
    assert out[1]["verified"] is True and out[1]["chapter"] == 9  # 命中 c2


def test_empty_returns_none(monkeypatch):
    """所有段都没抽到事件 → 合并空 → None。"""
    monkeypatch.setattr(tl, "run_segments", lambda **_k: [[], []])
    out = tl.generate_timeline_exhaustive(
        chunks=_CHUNKS, llm_client=object(), model="m",
    )
    assert out is None
