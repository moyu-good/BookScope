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


# ── 病二:证据要现捞、真讲"这章为什么紧/缓",不挂章代表句 ─────────────────────
def _evidence_spine() -> list[dict]:
    """高张力章(决战)和低张力章(休整),各自 events/char_states 指向原文里不同的句。"""
    return [
        {"chapter": 5, "tension": 9, "sentiment": -4, "pov": "甲", "mainline": True,
         "events": [{"event": "甲乙两军决战于城下"}],
         "char_states": [{"name": "甲", "state": "陷入苦战"}],
         # 章代表句故意写成跟张力无关的闲笔,验证不再被挂上来
         "evidence": "这章最显眼是城外有人卖酒。", "verified": True, "match_score": 1.0},
        {"chapter": 1, "tension": 2, "sentiment": 1, "pov": "群像", "mainline": False,
         "events": [{"event": "众人在营中休整饮酒"}],
         "char_states": [{"name": "甲", "state": "暂得喘息"}],
         "evidence": "开篇随便一句。", "verified": False, "match_score": 0.3},
    ]


def _chunks() -> list[dict]:
    return [
        {"chapter": 5, "text": "城外有人卖酒。甲乙两军决战于城下,杀声震天,甲陷入苦战。"},
        {"chapter": 1, "text": "天色尚早。众人在营中休整饮酒,甲暂得喘息,谈笑风生。"},
    ]


def test_narrative_curve_evidence_fetched_explains_tension() -> None:
    out = narrative_curve_from_spine(_evidence_spine(), chunks=_chunks())
    hi = next(c for c in out if c["chapter"] == 5)
    # 高张力章 evidence 必须真讲"为什么紧"(决战/苦战),不是章代表句那句卖酒闲笔
    assert "决战" in hi["evidence"] or "苦战" in hi["evidence"]
    assert hi["evidence"] != "这章最显眼是城外有人卖酒。"
    assert hi["verified"] is True
    lo = next(c for c in out if c["chapter"] == 1)
    # 低张力章 evidence 真讲"为什么缓"(休整)
    assert "休整" in lo["evidence"]
    assert lo["verified"] is True


def test_narrative_curve_evidence_empty_marks_unverified() -> None:
    # 原文里压根捞不到支撑句(章原文跟 events/char_states 完全不沾)→ 空串 + verified=False,不硬塞
    spine = [{"chapter": 7, "tension": 8, "events": [{"event": "甲乙决战"}],
              "char_states": [{"name": "甲", "state": "苦战"}], "evidence": "章代表句"}]
    chunks = [{"chapter": 7, "text": "完全无关的一段描写风景的文字。"}]
    out = narrative_curve_from_spine(spine, chunks=chunks)
    assert out[0]["evidence"] == ""
    assert out[0]["verified"] is False


def test_narrative_curve_chunks_none_keeps_old_behavior() -> None:
    # chunks=None(默认)时退回章代表句、向后兼容(老调用方不传 chunks 不报错、行为不变)
    out = narrative_curve_from_spine(_spine())
    c2 = next(c for c in out if c["chapter"] == 2)
    assert c2["evidence"] == "甲打了乙"      # 章代表句原样
    assert c2["verified"] is True


def test_pacing_note_fetched_when_no_event() -> None:
    # 没事件时 note 现捞、真讲这章动静,不退到章代表句
    spine = [{"chapter": 5, "tension": 9, "events": [],
              "char_states": [{"name": "甲", "state": "陷入苦战"}],
              "evidence": "这章最显眼是城外有人卖酒。"}]
    chunks = [{"chapter": 5, "text": "城外有人卖酒。甲乙两军决战于城下,甲陷入苦战。"}]
    out = pacing_from_spine(spine, chunks=chunks)
    assert "苦战" in out[0]["note"]
    assert out[0]["note"] != "这章最显眼是城外有人卖酒。"


def test_pacing_note_prefers_first_event_even_with_chunks() -> None:
    # 有事件时 note 仍用首个事件(那本就是这章发生了什么,不是章代表句)
    out = pacing_from_spine(_evidence_spine(), chunks=_chunks())
    hi = next(c for c in out if c["chapter"] == 5)
    assert hi["note"] == "甲乙两军决战于城下"


def test_pacing_chunks_none_keeps_old_behavior() -> None:
    # chunks=None 时无事件退回章代表句,老行为不变
    out = pacing_from_spine(_spine())
    c1 = next(c for c in out if c["chapter"] == 1)
    assert c1["note"] == "开篇"


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
    # 关系图只画有关系的人:张飞 present 但没进任何 relation → 去孤立点丢掉(不是 bug,是关系图本义)
    assert names == {"刘备", "关羽", "曹操"}
    assert "张飞" not in names
    # 刘备-关羽:章1 两条(含 乙-甲)合成一条边,只记章1 → weight 1
    lk = next(e for e in g["edges"] if {e["source"], e["target"]} == {"刘备", "关羽"})
    assert lk["chapters"] == [1] and lk["weight"] == 1
    assert "结义" in lk["notes"] and "再提" in lk["notes"]
    # 边不带 upfront evidence(出路 B)
    assert "evidence" not in lk


def test_relationship_graph_no_default_cap() -> None:
    # 一百多回的书有几百号人有关系,默认不砍——50 个互相有关系的人应全画出来(不再默认砍到 40)
    spine = [
        {"chapter": i, "present": [f"甲{i}", f"乙{i}"],
         "relations": [{"pair": [f"甲{i}", f"乙{i}"], "note": "x"}]}
        for i in range(50)
    ]
    g = relationship_graph_from_spine(spine)
    assert len({n["name"] for n in g["nodes"]}) == 100   # 50 对 = 100 个人,全在,没被砍到 40


def test_narrative_flow_present_and_pairs() -> None:
    out = narrative_flow_from_spine(_rel_spine())
    assert [c["chapter"] for c in out] == [1, 2]
    c1 = out[0]
    assert c1["present"] == ["刘备", "关羽", "张飞"]
    assert len(c1["pairs"]) == 1                       # 乙-甲 去重成一对
    assert {c1["pairs"][0]["a"], c1["pairs"][0]["b"]} == {"刘备", "关羽"}


def test_relationship_graph_canonicalizes_aliases() -> None:
    # 玄德/先主 应并到 刘备(name_map 来自 KG),别名碎裂收掉
    spine = [
        {"chapter": 1, "present": ["玄德", "关羽"],
         "relations": [{"pair": ["玄德", "关羽"], "note": "结义"}]},
        {"chapter": 2, "present": ["先主", "曹操"],
         "relations": [{"pair": ["先主", "曹操"], "note": "对峙"}]},
    ]
    nm = {"玄德": "刘备", "先主": "刘备", "刘备": "刘备"}
    g = relationship_graph_from_spine(spine, name_map=nm)
    names = {n["name"] for n in g["nodes"]}
    assert "玄德" not in names and "先主" not in names      # 别名没漏
    assert "刘备" in names
    # 刘备-关羽、刘备-曹操 两条边(玄德/先主 都归到刘备)
    edge_pairs = {frozenset((e["source"], e["target"])) for e in g["edges"]}
    assert {"刘备", "关羽"} in edge_pairs and {"刘备", "曹操"} in edge_pairs


def test_relationship_graph_top_n_keeps_most_connected() -> None:
    # 甲是中心(跟乙丙丁都有边),戊只跟己有一条弱边。top_n=3 应保住甲乙丙丁里连接度高的、砍掉边角
    spine = [
        {"chapter": 1, "present": ["甲", "乙", "丙", "丁"],
         "relations": [{"pair": ["甲", "乙"], "note": "x"}, {"pair": ["甲", "丙"], "note": "x"},
                       {"pair": ["甲", "丁"], "note": "x"}]},
        {"chapter": 2, "present": ["甲", "乙"], "relations": [{"pair": ["甲", "乙"], "note": "y"}]},
        {"chapter": 9, "present": ["戊", "己"], "relations": [{"pair": ["戊", "己"], "note": "z"}]},
    ]
    g = relationship_graph_from_spine(spine, top_n=3)
    names = {n["name"] for n in g["nodes"]}
    assert len(names) == 3
    assert "甲" in names                         # 连接度最高,必留
    assert "戊" not in names and "己" not in names  # 边角弱边,砍掉
    # 留下的边都在保留节点之间
    for e in g["edges"]:
        assert e["source"] in names and e["target"] in names


def test_relationship_graph_top_n_noop_when_under_limit() -> None:
    spine = [{"chapter": 1, "present": ["甲", "乙"],
              "relations": [{"pair": ["甲", "乙"], "note": "x"}]}]
    g = relationship_graph_from_spine(spine, top_n=40)
    assert {n["name"] for n in g["nodes"]} == {"甲", "乙"}   # 没超限,全留


def test_narrative_flow_canonicalizes_aliases() -> None:
    spine = [{"chapter": 1, "present": ["玄德", "刘备", "关羽"],
              "relations": [{"pair": ["玄德", "关羽"], "note": "x"}]}]
    nm = {"玄德": "刘备"}
    out = narrative_flow_from_spine(spine, name_map=nm)
    assert out[0]["present"] == ["刘备", "关羽"]            # 玄德+刘备 去重成刘备
    assert {out[0]["pairs"][0]["a"], out[0]["pairs"][0]["b"]} == {"刘备", "关羽"}


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
