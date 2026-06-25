"""chapter_spine_relationship.relationship_timeline_from_spine 单测（1.5.1 关系编年）。

mock invoke_client_cached + 假 client，覆盖新契约：
总判(verdict) + 逐幕编年(beats) / 不对称按需(asymmetric=false 清空两 view) / valence 钳值 /
beat 章号锚到真有 note 的章 + 同章去重 + 排序 / 每幕 evidence 核验 + 章号纠偏 /
编的 evidence unverified / pivot_chapter 锚回某幕 / 无幕丢这对 / 无成戏对→None /
MIN_CHAPTERS_PER_PAIR 过滤 / parse 失败→None / LLM 抛错→None / 截断抢救 / 去代码围栏。
不跑真 LLM。
"""

from __future__ import annotations

import json

from bookscope.agent import chapter_spine_relationship as csr

_CHUNKS = [
    {"chunk_id": "c5", "chapter": 5,
     "text": "刘备与曹操同在帐中，纵论天下大势。"},
    {"chunk_id": "c21", "chapter": 21,
     "text": "曹操曰：今天下英雄，惟使君与操耳！刘备闻言失箸。"},
    {"chunk_id": "c50", "chapter": 50,
     "text": "曹操引败军，望华容道奔走，刘备军大胜。"},
]

_SPINE = [
    {"chapter": 5, "evidence": "操与刘备、关羽、张飞同在帐中，纵论天下大势。",
     "relations": [{"pair": ["刘备", "曹操"], "note": "讨董同盟，初识，各怀心思"}]},
    {"chapter": 21, "evidence": "操曰：今天下英雄，惟使君与操耳！玄德闻言失箸。",
     "relations": [{"pair": ["曹操", "刘备"], "note": "煮酒论英雄，曹操点破刘备之志"}]},
    {"chapter": 50, "evidence": "操引败军，望华容道奔走。",
     "relations": [{"pair": ["刘备", "曹操"], "note": "赤壁对决，正式成敌"}]},
]


class _FakeClient:
    def __init__(self, final_text: str) -> None:
        self._final = final_text

    def extract_final_text(self, resp):  # noqa: ANN001
        return resp if isinstance(resp, str) else self._final


def _patch(monkeypatch, text: str | list[str], *, raises: Exception | None = None):
    seq = [text] if isinstance(text, str) else list(text)

    def _fake(*_a, **_k):
        if raises is not None:
            raise raises
        return seq.pop(0)

    monkeypatch.setattr(csr, "invoke_client_cached", _fake)


def _run(payload, *, spine=None, chunks=None, name_map=None, **kw):
    return csr.relationship_timeline_from_spine(
        spine=spine if spine is not None else _SPINE,
        chunks=chunks if chunks is not None else _CHUNKS,
        llm_client=_FakeClient(""),
        model="deepseek-v4-flash",
        name_map=name_map if name_map is not None else {},  # 空表免得触发 build_spine_name_map
        **kw,
    )


def test_success_builds_verdict_and_beats(monkeypatch):
    payload = json.dumps({
        "verdict": {
            "essence": "互为镜像的枭雄，注定两立",
            "arc": "从同盟到死敌",
            "asymmetric": True,
            "view_a_on_b": "刘备始终提防曹操",
            "view_b_on_a": "曹操始终高看刘备",
            "sharp_point": "煮酒论英雄是关系枢纽",
            "pivot_chapter": 21,
        },
        "beats": [
            {"chapter": 5, "scene": "讨董同盟", "state": "同盟·各怀心思",
             "valence": 2, "change": ""},
            {"chapter": 21, "scene": "煮酒论英雄", "state": "转折·识破",
             "valence": -1, "change": "曹操点破刘备之志，刘备生脱身之意"},
            {"chapter": 50, "scene": "赤壁对决", "state": "死敌·分庭抗礼",
             "valence": -5, "change": "正式开战"},
        ],
    }, ensure_ascii=False)
    _patch(monkeypatch, payload)
    r = _run(payload)
    assert r is not None
    rels = r["relations"]
    assert len(rels) == 1
    rel = rels[0]
    assert {rel["a"], rel["b"]} == {"刘备", "曹操"}
    v = rel["verdict"]
    assert v["essence"].startswith("互为镜像")
    assert v["asymmetric"] is True
    assert v["view_a_on_b"] and v["view_b_on_a"]
    assert v["pivot_chapter"] == 21
    beats = rel["beats"]
    assert [b["chapter"] for b in beats] == [5, 21, 50]
    assert beats[1]["verified"] is True  # 命中 c21
    assert beats[2]["verified"] is True  # 命中 c50
    assert beats[0]["valence"] == 2
    assert beats[0]["evidence"]  # 从章脉补了原文


def test_symmetric_clears_views(monkeypatch):
    """asymmetric=false → 两个 view 强制清空（不硬编不对称）。"""
    payload = json.dumps({
        "verdict": {"essence": "x", "arc": "y", "asymmetric": False,
                    "view_a_on_b": "模型嘴上对称还硬填了", "view_b_on_a": "也填了",
                    "sharp_point": "z", "pivot_chapter": 5},
        "beats": [{"chapter": 5, "scene": "s", "state": "同盟", "valence": 3, "change": ""}],
    }, ensure_ascii=False)
    _patch(monkeypatch, payload)
    r = _run(payload)
    v = r["relations"][0]["verdict"]
    assert v["asymmetric"] is False
    assert v["view_a_on_b"] == ""
    assert v["view_b_on_a"] == ""


def test_valence_clamped(monkeypatch):
    payload = json.dumps({
        "verdict": {"asymmetric": False},
        "beats": [
            {"chapter": 5, "scene": "a", "state": "x", "valence": 99, "change": ""},
            {"chapter": 21, "scene": "b", "state": "y", "valence": -99, "change": ""},
            {"chapter": 50, "scene": "c", "state": "z", "valence": "敌", "change": ""},
        ],
    }, ensure_ascii=False)
    _patch(monkeypatch, payload)
    beats = _run(payload)["relations"][0]["beats"]
    assert beats[0]["valence"] == 5
    assert beats[1]["valence"] == -5
    assert beats[2]["valence"] == 0  # 非数退 0


def test_beats_anchored_sorted_deduped(monkeypatch):
    """beat 章号锚到真有 note 的章、乱序排回、同章去重、越界退最近一章。"""
    payload = json.dumps({
        "verdict": {"asymmetric": False},
        "beats": [
            {"chapter": 50, "scene": "晚", "state": "x", "valence": -5, "change": ""},
            {"chapter": 5, "scene": "早", "state": "y", "valence": 2, "change": ""},
            {"chapter": 5, "scene": "同章重复", "state": "dup", "valence": 1, "change": ""},
            {"chapter": 999, "scene": "越界", "state": "z", "valence": 0, "change": ""},
        ],
    }, ensure_ascii=False)
    _patch(monkeypatch, payload)
    beats = _run(payload)["relations"][0]["beats"]
    chs = [b["chapter"] for b in beats]
    assert chs == sorted(chs)  # 升序
    assert chs.count(5) == 1  # 同章去重
    assert 50 in chs  # 999 越界锚到最近真有 note 的章（50）
    assert all(c in {5, 21, 50} for c in chs)  # 全锚到真有 note 的章


def test_chapter_without_pair_unverified(monkeypatch):
    """某章原文里压根没提这对人 → 该幕 evidence 空、verified=False（不硬塞无关原文）。"""
    chunks = [
        {"chunk_id": "x5", "chapter": 5, "text": "这一章只讲别的事，与这对人毫无关系。"},
        {"chunk_id": "x21", "chapter": 21, "text": "曹操与刘备青梅煮酒，刘备失箸。"},
    ]
    spine = [
        {"chapter": 5, "evidence": "无关。",
         "relations": [{"pair": ["刘备", "曹操"], "note": "n1"}]},
        {"chapter": 21, "evidence": "煮酒。",
         "relations": [{"pair": ["刘备", "曹操"], "note": "n2"}]},
    ]
    payload = json.dumps({
        "verdict": {"asymmetric": False},
        "beats": [
            {"chapter": 5, "scene": "a", "state": "x", "valence": 0, "change": ""},
            {"chapter": 21, "scene": "b", "state": "y", "valence": -2, "change": ""},
        ],
    }, ensure_ascii=False)
    _patch(monkeypatch, payload)
    beats = _run(payload, spine=spine, chunks=chunks)["relations"][0]["beats"]
    by_ch = {b["chapter"]: b for b in beats}
    assert by_ch[5]["evidence"] == "" and by_ch[5]["verified"] is False  # 没提这对人
    assert by_ch[21]["verified"] is True  # 真讲这对人的那句


def test_stray_single_name_no_event_unverified(monkeypatch):
    """某章只零星提到一个名字、又不讲这件事(零字面重叠)→ 不当证据,空、verified=False。"""
    chunks = [
        {"chunk_id": "s5", "chapter": 5, "text": "曹操在朝中与百官议事，商讨迁都之策。"},
        {"chunk_id": "s21", "chapter": 21, "text": "曹操与刘备青梅煮酒，纵论天下英雄。"},
    ]
    spine = [
        {"chapter": 5, "evidence": "x",
         "relations": [{"pair": ["刘备", "曹操"], "note": "n1"}]},
        {"chapter": 21, "evidence": "y",
         "relations": [{"pair": ["刘备", "曹操"], "note": "n2"}]},
    ]
    payload = json.dumps({
        "verdict": {"asymmetric": False},
        "beats": [
            {"chapter": 5, "scene": "二人初次结盟共讨", "state": "x", "valence": 3, "change": ""},
            {"chapter": 21, "scene": "青梅煮酒论英雄", "state": "y", "valence": 1, "change": ""},
        ],
    }, ensure_ascii=False)
    _patch(monkeypatch, payload)
    beats = _run(payload, spine=spine, chunks=chunks)["relations"][0]["beats"]
    by = {b["chapter"]: b for b in beats}
    assert by[5]["evidence"] == "" and by[5]["verified"] is False  # 只蹭"曹操"、不讲这件事
    assert by[21]["evidence"] and by[21]["verified"] is True  # 两人都在那句


def test_alias_evidence_via_name_map(monkeypatch):
    """原文用别名（玄德/孟德），name_map 反查别名也能在原文里捞到这对人的句子。"""
    chunks = [
        {"chunk_id": "a5", "chapter": 5, "text": "玄德与孟德青梅煮酒，纵论天下英雄。"},
        {"chunk_id": "a8", "chapter": 8, "text": "孟德疑玄德有异志，玄德唯韬光养晦。"},
    ]
    spine = [
        {"chapter": 5, "evidence": "x",
         "relations": [{"pair": ["玄德", "孟德"], "note": "煮酒"}]},
        {"chapter": 8, "evidence": "y",
         "relations": [{"pair": ["玄德", "孟德"], "note": "猜忌"}]},
    ]
    name_map = {"玄德": "刘备", "孟德": "曹操"}
    payload = json.dumps({
        "verdict": {"asymmetric": False},
        "beats": [
            {"chapter": 5, "scene": "煮酒", "state": "x", "valence": 2, "change": ""},
            {"chapter": 8, "scene": "猜忌", "state": "y", "valence": -1, "change": ""},
        ],
    }, ensure_ascii=False)
    _patch(monkeypatch, payload)
    rel = _run(payload, spine=spine, chunks=chunks, name_map=name_map)["relations"][0]
    assert {rel["a"], rel["b"]} == {"刘备", "曹操"}  # 别名归并到 canonical
    for b in rel["beats"]:
        assert b["evidence"]  # 别名命中，捞到了原文
        assert b["verified"] is True


def test_pivot_anchored_to_nearest_beat(monkeypatch):
    """pivot_chapter 不在任何幕 → 退到最近一幕。"""
    payload = json.dumps({
        "verdict": {"asymmetric": False, "sharp_point": "x", "pivot_chapter": 40},
        "beats": [
            {"chapter": 5, "scene": "a", "state": "x", "valence": 1, "change": ""},
            {"chapter": 50, "scene": "b", "state": "y", "valence": -5, "change": ""},
        ],
    }, ensure_ascii=False)
    _patch(monkeypatch, payload)
    v = _run(payload)["relations"][0]["verdict"]
    assert v["pivot_chapter"] == 50  # 40 离 50 比离 5 近


def test_no_beats_drops_pair(monkeypatch):
    payload = json.dumps({"verdict": {"essence": "x"}, "beats": []}, ensure_ascii=False)
    _patch(monkeypatch, payload)
    assert _run(payload) is None  # 唯一的对没幕 → None


def test_no_relations_in_spine_returns_none(monkeypatch):
    """非叙事书：章脉里没有成戏的人物对 → None（端点返空态）。"""
    spine = [{"chapter": 1, "evidence": "纯论述，无人物互动。", "relations": []}]
    _patch(monkeypatch, "{}")
    assert _run("{}", spine=spine) is None


def test_min_chapters_filter(monkeypatch):
    """只在 1 章露面的对（< MIN_CHAPTERS_PER_PAIR）被滤掉。"""
    spine = [
        {"chapter": 5, "evidence": _CHUNKS[0]["text"],
         "relations": [{"pair": ["甲", "乙"], "note": "只此一面"}]},
    ]
    _patch(monkeypatch, "{}")
    assert _run("{}", spine=spine) is None


def test_parse_failure_returns_none(monkeypatch):
    _patch(monkeypatch, "这不是 JSON，随便说点别的")
    assert _run("x") is None


def test_llm_raises_returns_none(monkeypatch):
    _patch(monkeypatch, "{}", raises=RuntimeError("boom"))
    assert _run("x") is None


def test_salvages_truncated_beats(monkeypatch):
    """reasoning 吃 token 致 JSON 截断 → 抢救已闭合的幕，不整对丢掉。"""
    truncated = (
        '{"verdict": {"essence": "x", "asymmetric": false}, "beats": ['
        '{"chapter": 5, "scene": "a", "state": "同盟", "valence": 2, "change": ""},'
        '{"chapter": 21, "scene": "b", "state": "转折", "valence": -1, "change": "点破"},'
        '{"chapter": 50, "scene": "c", "sta'  # 截断
    )
    _patch(monkeypatch, truncated)
    r = _run(truncated)
    assert r is not None
    chs = [b["chapter"] for b in r["relations"][0]["beats"]]
    assert 5 in chs and 21 in chs
    assert 50 not in chs  # 截断的那幕丢弃


def test_strips_code_fence(monkeypatch):
    inner = json.dumps({
        "verdict": {"asymmetric": False},
        "beats": [{"chapter": 5, "scene": "a", "state": "x", "valence": 1, "change": ""}],
    }, ensure_ascii=False)
    _patch(monkeypatch, "```json\n" + inner + "\n```")
    r = _run(inner)
    assert r is not None
    assert len(r["relations"][0]["beats"]) == 1


def test_pairs_index_lists_all_pairs_no_llm():
    """全员对清单不调 LLM:列出每对 + 互动章 + 章数,按章数降序(给关系图下钻的选择器)。"""
    idx = csr.relationship_pairs_index(_SPINE, name_map={})
    assert len(idx) == 1
    e = idx[0]
    assert {e["a"], e["b"]} == {"刘备", "曹操"}
    assert e["chapters"] == [5, 21, 50]
    assert e["first"] == 5 and e["last"] == 50 and e["count"] == 3


def test_chronicle_for_pair_success(monkeypatch):
    """按需算指定一对的编年:复用全局推理 + 证据核验,返单条 {a,b,verdict,beats}。"""
    payload = json.dumps({
        "verdict": {"essence": "x", "arc": "y", "asymmetric": False,
                    "sharp_point": "z", "pivot_chapter": 21},
        "beats": [
            {"chapter": 5, "scene": "s", "state": "同盟", "valence": 2, "change": ""},
            {"chapter": 21, "scene": "煮酒", "state": "转折", "valence": -1, "change": "点破"},
        ],
    }, ensure_ascii=False)
    _patch(monkeypatch, payload)
    rel = csr.relationship_chronicle_for_pair(
        a="刘备", b="曹操", spine=_SPINE, chunks=_CHUNKS,
        llm_client=_FakeClient(""), model="m", name_map={},
    )
    assert rel is not None
    assert {rel["a"], rel["b"]} == {"刘备", "曹操"}
    assert len(rel["beats"]) == 2
    assert rel["verdict"]["pivot_chapter"] == 21


def test_chronicle_for_pair_not_found(monkeypatch):
    """章脉里没有这对人 → None(端点返空,前端显'这对没演变')。"""
    _patch(monkeypatch, "{}")
    rel = csr.relationship_chronicle_for_pair(
        a="张三", b="李四", spine=_SPINE, chunks=_CHUNKS,
        llm_client=_FakeClient(""), model="m", name_map={},
    )
    assert rel is None


def test_chronicle_for_pair_below_min(monkeypatch):
    """只在 1 章互动的对 < MIN_CHAPTERS_PER_PAIR → None(没演变可铺)。"""
    spine = [
        {"chapter": 5, "evidence": "x", "relations": [{"pair": ["甲", "乙"], "note": "n"}]},
    ]
    _patch(monkeypatch, "{}")
    rel = csr.relationship_chronicle_for_pair(
        a="甲", b="乙", spine=spine, chunks=_CHUNKS,
        llm_client=_FakeClient(""), model="m", name_map={},
    )
    assert rel is None
