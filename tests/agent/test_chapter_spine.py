"""章脉(ADR-010)单测 —— 分维解析 / 归一 / 章号纠偏 / 跨维 union / build 装配。

纯件直接喂数据;build_chapter_spine 把 mapreduce_per_chapter 桩掉,不调真 LLM。
"""

from __future__ import annotations

import json

import bookscope.agent.chapter_spine as cs


# ── 解析 ───────────────────────────────────────────────────────────────────
def test_parse_plot_valid() -> None:
    parse = cs._make_parser("plot")
    text = json.dumps({"chapters": [
        {"chapter": 1, "events": ["打架"], "tension": 8, "sentiment": -2,
         "pov": "甲", "mainline": True, "foreshadow": [], "evidence": "甲打了乙"},
    ]})
    out = parse(text)
    assert out is not None
    assert out[0]["chapter"] == 1
    assert out[0]["tension"] == 8
    assert out[0]["pov"] == "甲"


def test_parse_char_valid() -> None:
    parse = cs._make_parser("char")
    text = json.dumps({"chapters": [
        {"chapter": 2, "present": ["甲", "乙"],
         "relations": [{"pair": ["甲", "乙"], "note": "结义"}],
         "char_states": [], "evidence": "甲乙结义"},
    ]})
    out = parse(text)
    assert out and out[0]["present"] == ["甲", "乙"]
    assert out[0]["relations"][0]["note"] == "结义"


def test_parse_salvages_truncated() -> None:
    # 截断:第二个对象没闭合 + 数组/外层没收尾 → 主 parse 必败,从已闭合的抢救
    parse = cs._make_parser("plot")
    truncated = (
        '{"chapters": [{"chapter": 1, "events": [], "tension": 5, "sentiment": 0, '
        '"pov": "甲", "mainline": true, "foreshadow": [], "evidence": "x"}, '
        '{"chapter": 2, "events": ["未闭合'
    )
    out = parse(truncated)
    assert out is not None
    assert [c["chapter"] for c in out] == [1]  # 抢救到第一章


def test_coerce_drops_non_int_chapter_and_clamps() -> None:
    parse = cs._make_parser("plot")
    text = json.dumps({"chapters": [
        {"chapter": "一", "tension": 5, "evidence": "x"},          # 章号非整数 → 丢
        {"chapter": 3, "tension": 99, "sentiment": -99, "evidence": "y"},  # 钳到 10 / -5
    ]})
    out = parse(text)
    assert [c["chapter"] for c in out] == [3]
    assert out[0]["tension"] == 10
    assert out[0]["sentiment"] == -5
    assert out[0]["pov"] == "群像"          # 缺省
    assert out[0]["mainline"] is True       # 缺省


# ── 章号纠偏 ─────────────────────────────────────────────────────────────────
def test_correct_by_evidence_overrides_chapter() -> None:
    chunks = [
        {"chunk_id": "c1", "chapter": 1, "text": "桃园结义,刘关张同心。"},
        {"chunk_id": "c2", "chapter": 86, "text": "诸葛亮舌战群儒。"},
    ]
    # 模型自报章号 11(多卷书撞号),evidence 命中真第 86 章 → 应纠偏成 86
    records = [{"chapter": 11, "evidence": "诸葛亮舌战群儒"}]
    cs._correct_by_evidence(records, chunks)
    assert records[0]["chapter"] == 86
    assert records[0]["verified"] is True


def test_correct_by_evidence_miss_keeps_self_reported() -> None:
    chunks = [{"chunk_id": "c1", "chapter": 1, "text": "桃园结义。"}]
    records = [{"chapter": 5, "evidence": "查无此句"}]
    cs._correct_by_evidence(records, chunks)
    assert records[0]["chapter"] == 5          # 没命中退回自报
    assert records[0]["verified"] is False


# ── 跨维 union ───────────────────────────────────────────────────────────────
def test_merge_dimensions_unions_fields_by_chapter() -> None:
    char = [{"chapter": 1, "present": ["甲"], "relations": [], "char_states": [],
             "evidence": "e_char", "verified": True, "match_score": 1.0}]
    plot = [{"chapter": 1, "events": ["打"], "tension": 8, "sentiment": -2, "pov": "甲",
             "mainline": True, "foreshadow": [], "evidence": "e_plot",
             "verified": False, "match_score": 0.5}]
    merged = cs._merge_dimensions([char, plot])
    assert len(merged) == 1
    rec = merged[0]
    assert rec["present"] == ["甲"]            # 人物维字段
    assert rec["tension"] == 8                  # 情节维字段
    assert rec["verified"] is True             # 任一维命中即 True
    assert rec["match_score"] == 1.0           # 取最大
    assert rec["evidence"] == "e_char"         # 第一条非空


def test_merge_dimensions_sorts_and_handles_disjoint_chapters() -> None:
    char = [{"chapter": 3, "present": ["甲"], "evidence": "a"},
            {"chapter": 1, "present": ["乙"], "evidence": "b"}]
    plot = [{"chapter": 2, "tension": 5, "evidence": "c"}]
    merged = cs._merge_dimensions([char, plot])
    assert [r["chapter"] for r in merged] == [1, 2, 3]   # 升序


# ── build 装配 ───────────────────────────────────────────────────────────────
class _FakeClient:
    def extract_final_text(self, resp):  # noqa: ANN001, ANN201
        return "{}"


def test_build_chapter_spine_fiction_runs_two_dims(monkeypatch) -> None:  # noqa: ANN001
    calls = []

    def _fake_mapreduce(**kwargs):  # noqa: ANN003, ANN202
        calls.append(kwargs["instruction"])
        # 据指令判断是哪一维,返该维的一条章 1 记录
        if kwargs["instruction"] is cs._INSTR_CHAR:
            return [{"chapter": 1, "present": ["甲"], "evidence": "e",
                     "verified": True, "match_score": 1.0}]
        return [{"chapter": 1, "tension": 7, "evidence": "e2",
                 "verified": True, "match_score": 1.0}]

    monkeypatch.setattr(cs, "mapreduce_per_chapter", _fake_mapreduce)
    spine = cs.build_chapter_spine(chunks=[], llm_client=_FakeClient(), model="m")
    assert len(calls) == 2                       # 小说跑两维,不跑概念维
    assert cs._INSTR_CONCEPT not in calls
    assert len(spine) == 1
    assert spine[0]["present"] == ["甲"]         # 两维 union 到一条
    assert spine[0]["tension"] == 7


def test_build_chapter_spine_theory_adds_concept_dim(monkeypatch) -> None:  # noqa: ANN001
    calls = []

    def _fake_mapreduce(**kwargs):  # noqa: ANN003, ANN202
        calls.append(kwargs["instruction"])
        return []

    monkeypatch.setattr(cs, "mapreduce_per_chapter", _fake_mapreduce)
    cs.build_chapter_spine(chunks=[], llm_client=_FakeClient(), model="m", genre="theory")
    assert len(calls) == 3                       # 理论书加概念维
    assert cs._INSTR_CONCEPT in calls
