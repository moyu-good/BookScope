"""generate_character_arc_exhaustive 单测 —— 穷尽化(map-reduce 带子点型)。

不调真 LLM:monkeypatch 模块里的 run_segments,喂造好的「每段」输出(同一角色跨两段、各带
不同章的 points),走真的 merge_keyed_points 合并 + 真的 _verify_points。断言:角色按名合并、
points 跨段按章并集升序、evidence 逐字命中 chunk → verified + 真章号纠偏。
"""

from __future__ import annotations

import bookscope.agent.character_arc as ca


class _FakeClient:
    """假 LLM client —— 穷尽化路径里被 run_segments 桩掉,不会真被调到。"""

    def extract_final_text(self, resp):  # noqa: ANN001, ANN201
        return "{}"


def test_exhaustive_merges_chars_and_unions_points(monkeypatch) -> None:  # noqa: ANN001
    # 四章原文,每章一句证据;evidence 要逐字出现在对应 chunk 里才命中标 verified
    chunks = [
        {"chunk_id": "a1", "chapter": 1, "text": "刘备织席贩履，曹操举兵讨董。"},
        {"chunk_id": "a2", "chapter": 2, "text": "刘备三顾茅庐请诸葛亮。"},
        {"chunk_id": "a3", "chapter": 5, "text": "刘备称帝于成都，曹操已殁。"},
        {"chunk_id": "a4", "chapter": 1, "text": "曹操挟天子以令诸侯。"},
    ]

    # 模拟 run_segments 的输出:list[每段条目列表]。
    # 第一段:刘备(章 1,2) + 曹操(章 1);第二段:刘备(章 2 重复 + 章 5)。
    # 合并后刘备 points 应跨段按章并集升序 [1,2,5],章 2 保先出现段的值。
    outs = [
        [
            {
                "name": "刘备",
                "points": [
                    {"chapter": 1, "presence": 8, "fortune": -2,
                     "evidence": "刘备织席贩履"},
                    {"chapter": 2, "presence": 9, "fortune": 1,
                     "evidence": "刘备三顾茅庐请诸葛亮"},
                ],
            },
            {
                "name": "曹操",
                "points": [
                    {"chapter": 1, "presence": 7, "fortune": 3,
                     "evidence": "曹操举兵讨董"},
                ],
            },
        ],
        [
            {
                "name": "刘备",
                "points": [
                    {"chapter": 2, "presence": 99, "fortune": 99,
                     "evidence": "重复章应被丢"},
                    {"chapter": 5, "presence": 10, "fortune": 4,
                     "evidence": "刘备称帝于成都"},
                ],
            },
        ],
    ]

    captured: dict[str, object] = {}

    def _fake_run_segments(**kwargs):  # noqa: ANN003, ANN202
        captured.update(kwargs)
        return outs

    monkeypatch.setattr(ca, "run_segments", _fake_run_segments)

    out = ca.generate_character_arc_exhaustive(
        chunks=chunks, llm_client=_FakeClient(), model="m"
    )

    assert out is not None
    # 按角色名合并,首见顺序:刘备、曹操
    assert [c["name"] for c in out] == ["刘备", "曹操"]

    liubei = next(c for c in out if c["name"] == "刘备")
    # 跨「两段」的 points 按章并集 + 升序
    assert [p["chapter"] for p in liubei["points"]] == [1, 2, 5]
    # 章 2 跨段重复 → 保先出现段的值(presence=9,不是第二段的 99)
    assert next(p for p in liubei["points"] if p["chapter"] == 2)["presence"] == 9
    # evidence 逐字命中 chunk → verified
    for p in liubei["points"]:
        assert p["verified"] is True
        assert p["match_score"] == 1.0

    # 用对的 instruction / user_msg / parse_fn 调了 run_segments
    assert captured["instruction"] is ca._SYSTEM_INSTRUCTION
    assert captured["parse_fn"] is ca._parse_arc
    assert "只抽本段出现的章" in captured["user_msg"]


def test_exhaustive_returns_none_on_empty(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(ca, "run_segments", lambda **_k: [])
    out = ca.generate_character_arc_exhaustive(
        chunks=[{"chunk_id": "c0", "chapter": 1, "text": "x"}],
        llm_client=_FakeClient(),
        model="m",
    )
    assert out is None
