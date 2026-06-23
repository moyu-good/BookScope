"""generate_character_flow_exhaustive 单测 —— 穷尽化(map-reduce)覆盖跨段全部章。

不调真 LLM:monkeypatch 模块里的 mapreduce_per_chapter,直接喂造好的「合并后逐章」数据
(模拟两段拼起来覆盖章 1/2/3),再喂 chunks 让 _verify_pairs 真跑 verify_citations。
chunks 的 text 包含造的 evidence 原文片段,好让命中标 verified 并用真章号纠偏。
"""

from __future__ import annotations

import bookscope.agent.character_flow as cf


class _FakeClient:
    """假 LLM client —— 穷尽化路径里被 mapreduce_per_chapter 桩掉,不会真被调到。"""

    def extract_final_text(self, resp):  # noqa: ANN001, ANN201
        return "{}"


def test_exhaustive_covers_all_chapters_and_verifies(monkeypatch) -> None:  # noqa: ANN001
    # chunks:三章的原文,每章一句证据(同场对的 evidence 要逐字出现在对应 chunk 里)
    chunks = [
        {"chunk_id": "ch1", "chapter": 1, "text": "桃园结义，刘备关羽张飞同心。"},
        {"chunk_id": "ch2", "chapter": 2, "text": "曹操与吕布虎牢关前交手。"},
        {"chunk_id": "ch3", "chapter": 3, "text": "诸葛亮舌战群儒说服孙权。"},
    ]

    # 模拟 map-reduce 已合并好的逐章结果:第一段出章 1/2、第二段出章 3,拼起来三章齐。
    # mapreduce_per_chapter 在被桩前已做过 merge_by_chapter,这里直接给最终合并态。
    merged = [
        {
            "chapter": 1,
            "present": ["刘备", "关羽", "张飞"],
            "pairs": [{"a": "刘备", "b": "关羽", "evidence": "刘备关羽张飞同心", "chapter": 1}],
        },
        {
            "chapter": 2,
            "present": ["曹操", "吕布"],
            "pairs": [
                {"a": "曹操", "b": "吕布", "evidence": "曹操与吕布虎牢关前交手", "chapter": 2}
            ],
        },
        {
            "chapter": 3,
            "present": ["诸葛亮", "孙权"],
            "pairs": [
                {"a": "诸葛亮", "b": "孙权", "evidence": "诸葛亮舌战群儒说服孙权", "chapter": 3}
            ],
        },
    ]

    captured: dict[str, object] = {}

    def _fake_mapreduce(**kwargs):  # noqa: ANN003, ANN202
        # 模拟真 mapreduce 的契约:合并前逐段跑 correct_fn(章号纠偏)。这里 merged 当一段喂。
        captured.update(kwargs)
        correct_fn = kwargs.get("correct_fn")
        if correct_fn is not None:
            correct_fn(merged, kwargs["chunks"])
        return merged

    monkeypatch.setattr(cf, "mapreduce_per_chapter", _fake_mapreduce)

    out = cf.generate_character_flow_exhaustive(
        chunks=chunks, llm_client=_FakeClient(), model="m"
    )

    assert out is not None
    # 覆盖了跨「两段」的全部三章
    assert [c["chapter"] for c in out] == [1, 2, 3]
    # 用对的 instruction / user_msg / parse_fn 调了 map-reduce 壳
    assert captured["instruction"] is cf._SYSTEM_INSTRUCTION
    assert captured["parse_fn"] is cf._parse_flow
    assert "只抽本段出现的章" in captured["user_msg"]
    # 章号纠偏作为 correct_fn 在合并前跑(不再合并后),所以接的必须是 _correct_flow
    assert captured["correct_fn"] is cf._correct_flow
    # 每条同场对都过了 verify_citations:evidence 逐字命中对应 chunk → verified
    for chap in out:
        for pr in chap["pairs"]:
            assert pr["verified"] is True
            assert pr["match_score"] == 1.0


def test_exhaustive_returns_none_on_empty_merge(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(cf, "mapreduce_per_chapter", lambda **_k: [])
    out = cf.generate_character_flow_exhaustive(
        chunks=[{"chunk_id": "c0", "chapter": 1, "text": "x"}],
        llm_client=_FakeClient(),
        model="m",
    )
    assert out is None
