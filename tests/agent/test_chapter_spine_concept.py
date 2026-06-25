"""chapter_spine_concept.concept_evolution_from_spine 单测(概念演进·治病二)。

mock invoke_client_cached + 假 client。重点覆盖证据来源两条路:
传 chunks → 每阶段 snippet 在那章原文按「概念名 + development」现捞、真讲这概念在那章的发展,
不挂那章最显眼的无关事(病二)/ 现捞不到支撑句这阶段丢 / chunks=None 旧行为=章脉章代表句
(向后兼容)/ 概念不在书→[] / 锚不到真章丢 / 同章去重 / 按章序重编 order /
parse 失败→None / LLM 抛错→None。不跑真 LLM。
"""

from __future__ import annotations

import json

from bookscope.agent import chapter_spine_concept as cc

# 概念"权谋"在第 3、12 章发展。原文里既有真讲"权谋"的句子,也混了那章"最显眼"的无关句
# (拿来当章代表句)——用来验现捞挂的是讲权谋的句,不是最显眼的无关句。
_CHUNKS = [
    {"chunk_id": "c3a", "chapter": 3, "text": "大雨倾盆,黄河决堤,沿岸百姓流离失所。"},
    {"chunk_id": "c3b", "chapter": 3, "text": "曹操初识权谋之道,以离间计使二将自相残杀。"},
    {"chunk_id": "c12a", "chapter": 12, "text": "这一年大旱,赤地千里,饿殍遍野。"},
    {"chunk_id": "c12b", "chapter": 12, "text": "权谋至此已成帝王心术,司马懿借刀杀人不露痕迹。"},
]

# 章脉:每章只留一条 evidence = 那章最显眼那件事(刻意取的不是讲权谋的句),
# 用来验旧行为(chunks=None)挂章代表句、现捞模式挂真讲权谋的句。
_SPINE = [
    {"chapter": 3, "evidence": "大雨倾盆,黄河决堤,沿岸百姓流离失所。",
     "claims": ["权谋是乱世立身之本"]},
    {"chapter": 12, "evidence": "这一年大旱,赤地千里,饿殍遍野。",
     "claims": ["权谋深化为帝王心术"]},
]


class _FakeClient:
    def __init__(self, final_text: str) -> None:
        self._final = final_text

    def extract_final_text(self, resp):  # noqa: ANN001
        return resp if isinstance(resp, str) else self._final


def _patch(monkeypatch, text: str, *, raises: Exception | None = None):
    def _fake(*_a, **_k):
        if raises is not None:
            raise raises
        return text

    monkeypatch.setattr(cc, "invoke_client_cached", _fake)


def _evolve(payload, *, concept="权谋", spine=None, chunks=None, **kw):
    return cc.concept_evolution_from_spine(
        concept=concept,
        spine=spine if spine is not None else _SPINE,
        chunks=chunks,
        llm_client=_FakeClient(""),
        model="deepseek-v4-flash",
        **kw,
    )


def _stage(order, chapter, development):  # noqa: ANN001
    return {"order": order, "chapter": chapter, "development": development}


_REAL_PAYLOAD = json.dumps({"stages": [
    _stage(1, 3, "曹操初识权谋,用离间计"),
    _stage(2, 12, "权谋深化为帝王心术,借刀杀人"),
]}, ensure_ascii=False)


def test_chunks_mode_snippet_fetched_per_chapter(monkeypatch):
    """传 chunks:每阶段 snippet 在那章原文按概念+development 现捞,真讲这概念在那章的发展。"""
    _patch(monkeypatch, _REAL_PAYLOAD)
    out = _evolve(_REAL_PAYLOAD, chunks=_CHUNKS)
    assert out is not None
    assert len(out) == 2
    s3 = next(s for s in out if s["chapter"] == 3)
    s12 = next(s for s in out if s["chapter"] == 12)
    # 第 3 章真讲"权谋"的句(离间计),不是那章最显眼的"黄河决堤"(病二会挂后者)
    assert "权谋" in s3["snippet"] and "离间计" in s3["snippet"]
    assert "黄河决堤" not in s3["snippet"]
    # 第 12 章真讲"权谋"深化的句(借刀杀人),不是"大旱"
    assert "权谋" in s12["snippet"] and "借刀杀人" in s12["snippet"]
    assert "大旱" not in s12["snippet"]
    assert s3["verified"] is True and s12["verified"] is True


def test_chunks_mode_no_support_drops_stage(monkeypatch):
    """现捞模式:某阶段在那章原文捞不到任何支撑句 → 丢这阶段(立身之本)。"""
    _patch(monkeypatch, _REAL_PAYLOAD)
    # 两章原文都跟"权谋/离间计/借刀杀人"毫无字面交集 → 概念名、development bigram 全不命中
    chunks = [
        {"chunk_id": "x3", "chapter": 3, "text": "春日和煦,园中百花盛开。"},
        {"chunk_id": "x12", "chapter": 12, "text": "夜深人静,唯有更漏声声。"},
    ]
    out = _evolve(_REAL_PAYLOAD, chunks=chunks)
    assert out == []  # 两阶段都捞不到支撑句,都被守卫丢掉


def test_chunks_mode_one_stage_no_support_kept_other(monkeypatch):
    """现捞模式:一阶段捞得到、另一阶段捞不到 → 只留捞得到的那个(逐阶段独立判)。"""
    _patch(monkeypatch, _REAL_PAYLOAD)
    chunks = [
        {"chunk_id": "h3", "chapter": 3, "text": "曹操初识权谋,以离间计破敌。"},
        {"chunk_id": "m12", "chapter": 12, "text": "这天风和日丽,与本概念毫不相干。"},
    ]
    out = _evolve(_REAL_PAYLOAD, chunks=chunks)
    assert len(out) == 1
    assert out[0]["chapter"] == 3
    assert "权谋" in out[0]["snippet"]


def test_none_chunks_keeps_old_chapter_representative(monkeypatch):
    """chunks=None 旧行为:snippet 取章脉那章代表句(向后兼容,不报错)。"""
    _patch(monkeypatch, _REAL_PAYLOAD)
    out = _evolve(_REAL_PAYLOAD)  # 不传 chunks
    assert out is not None
    assert len(out) == 2
    s3 = next(s for s in out if s["chapter"] == 3)
    s12 = next(s for s in out if s["chapter"] == 12)
    # 旧行为挂的就是章代表句(那章最显眼的事),保持不变
    assert s3["snippet"] == "大雨倾盆,黄河决堤,沿岸百姓流离失所。"
    assert s12["snippet"] == "这一年大旱,赤地千里,饿殍遍野。"
    assert s3["verified"] is True and s12["verified"] is True


def test_order_reindexed_by_chapter(monkeypatch):
    """阶段按 chapter 升序重编 order(不信 LLM 给的 order)。"""
    # LLM 把第 12 章排在前(order 颠倒),结果应按章序重编
    payload = json.dumps({"stages": [
        _stage(1, 12, "权谋深化为帝王心术,借刀杀人"),
        _stage(2, 3, "曹操初识权谋,用离间计"),
    ]}, ensure_ascii=False)
    _patch(monkeypatch, payload)
    out = _evolve(payload, chunks=_CHUNKS)
    assert [s["chapter"] for s in out] == [3, 12]
    assert [s["order"] for s in out] == [1, 2]


def test_concept_not_in_book_empty_not_none(monkeypatch):
    """概念不在书返空数组 → [] 而非 None(区分'书里没这概念'和'扫失败')。"""
    _patch(monkeypatch, '{"stages": []}')
    assert _evolve('{"stages": []}', concept="量子纠缠", chunks=_CHUNKS) == []


def test_fabricated_chapter_dropped(monkeypatch):
    """章号锚不到章脉真实章(LLM 编的章) → 丢这阶段。"""
    payload = json.dumps({"stages": [
        _stage(1, 999, "编的演进"),
        _stage(2, 3, "曹操初识权谋,用离间计"),
    ]}, ensure_ascii=False)
    _patch(monkeypatch, payload)
    out = _evolve(payload, chunks=_CHUNKS)
    assert len(out) == 1
    assert out[0]["chapter"] == 3


def test_same_chapter_deduped(monkeypatch):
    """同章多阶段 → 只留第一个(同章重复阶段没意义)。"""
    payload = json.dumps({"stages": [
        _stage(1, 3, "曹操初识权谋,用离间计"),
        _stage(2, 3, "权谋同章重复一条,借刀杀人"),
    ]}, ensure_ascii=False)
    _patch(monkeypatch, payload)
    out = _evolve(payload, chunks=_CHUNKS)
    assert len(out) == 1
    assert out[0]["chapter"] == 3


def test_empty_concept_returns_none(monkeypatch):
    """概念名空 → None(没法演进)。"""
    _patch(monkeypatch, _REAL_PAYLOAD)
    assert _evolve(_REAL_PAYLOAD, concept="   ", chunks=_CHUNKS) is None


def test_parse_failure_returns_none(monkeypatch):
    _patch(monkeypatch, "这不是 JSON")
    assert _evolve("这不是 JSON", chunks=_CHUNKS) is None


def test_llm_raises_returns_none(monkeypatch):
    _patch(monkeypatch, "{}", raises=RuntimeError("boom"))
    assert _evolve("{}", chunks=_CHUNKS) is None
