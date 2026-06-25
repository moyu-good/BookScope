"""chapter_spine_consistency.consistency_scan_from_spine 单测(设定一致性·治病二)。

mock invoke_client_cached + 假 client。重点覆盖证据来源两条路:
传 chunks → a/b snippet 各自在那章原文按 topic/conflict 现捞、真讲各自章对立说法 /
现捞不到支撑句整条丢(不 cry wolf) / chunks=None 旧行为=章脉章代表句(向后兼容) /
自洽空数组→[] / 锚不到真章丢 / 同章丢 / 去重 / parse 失败→None / LLM 抛错→None。
不跑真 LLM。
"""

from __future__ import annotations

import json

from bookscope.agent import chapter_spine_consistency as csc

# 真矛盾:第 5 章说左撇子、第 23 章用右手。原文里有真正讲这条矛盾的句子,
# 也混了别的"最显眼"的句子(章代表句)——用来验现捞不会张冠李戴。
_CHUNKS = [
    {"chunk_id": "c5a", "chapter": 5, "text": "安禄山率十万大军压境，三军震动。"},
    {"chunk_id": "c5b", "chapter": 5, "text": "安禄山是个左撇子，平日惯用左手持物。"},
    {"chunk_id": "c23a", "chapter": 23, "text": "这一日朝中议事，群臣争执不休。"},
    {"chunk_id": "c23b", "chapter": 23, "text": "安禄山曾用右手狠狠挥动马鞭督战。"},
]

# 章脉:每章只留一条 evidence = 那章最显眼那件事(刻意取的不是讲矛盾的那句),
# 用来验旧行为(chunks=None)挂的是章代表句、现捞模式挂的是真讲矛盾的句。
_SPINE = [
    {"chapter": 5, "evidence": "安禄山率十万大军压境，三军震动。",
     "char_states": [{"name": "安禄山", "state": "惯用左手"}]},
    {"chapter": 23, "evidence": "这一日朝中议事，群臣争执不休。",
     "char_states": [{"name": "安禄山", "state": "用右手挥鞭"}]},
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

    monkeypatch.setattr(csc, "invoke_client_cached", _fake)


def _scan(payload, *, spine=None, chunks=None, **kw):
    return csc.consistency_scan_from_spine(
        spine=spine if spine is not None else _SPINE,
        chunks=chunks,
        llm_client=_FakeClient(""),
        model="deepseek-v4-flash",
        **kw,
    )


_REAL_PAYLOAD = json.dumps({"contradictions": [{
    "topic": "安禄山惯用手", "conflict": "前说左撇子后用右手",
    "a_chapter": 5, "b_chapter": 23,
}]}, ensure_ascii=False)


def test_chunks_mode_snippet_fetched_per_chapter(monkeypatch):
    """传 chunks:a/b snippet 各自在那章原文按矛盾关键词现捞,真讲各自章的对立说法。"""
    _patch(monkeypatch, _REAL_PAYLOAD)
    out = _scan(_REAL_PAYLOAD, chunks=_CHUNKS)
    assert out is not None
    assert len(out) == 1
    a_snip = out[0]["a"]["snippet"]
    b_snip = out[0]["b"]["snippet"]
    # a 处真讲第 5 章的"左撇子",不是那章最显眼的"率十万大军压境"(病二会挂后者)
    assert "左撇子" in a_snip
    assert "大军压境" not in a_snip
    # b 处真讲第 23 章的"用右手",不是"朝中议事"
    assert "右手" in b_snip
    assert "朝中议事" not in b_snip
    assert out[0]["a"]["chapter"] == 5
    assert out[0]["b"]["chapter"] == 23


def test_chunks_mode_no_support_drops_whole_contradiction(monkeypatch):
    """现捞模式:这条矛盾在某章原文里捞不到任何支撑句 → 整条丢(不 cry wolf)。"""
    _patch(monkeypatch, _REAL_PAYLOAD)
    # 两章原文都跟"惯用手/左撇子/右手"毫无字面交集 → topic、conflict 关键词全不命中
    chunks = [
        {"chunk_id": "x5", "chapter": 5, "text": "春日和煦，园中花开正盛。"},
        {"chunk_id": "x23", "chapter": 23, "text": "夜深人静，唯有更漏声声。"},
    ]
    out = _scan(_REAL_PAYLOAD, chunks=chunks)
    assert out == []  # 捞不到支撑句,被"任一空就丢"守卫拦掉


def test_chunks_mode_one_side_no_support_drops(monkeypatch):
    """现捞模式:只有一处捞得到支撑句、另一处捞不到 → 整条丢(真矛盾要两处都坐实)。"""
    _patch(monkeypatch, _REAL_PAYLOAD)
    chunks = [
        {"chunk_id": "h5", "chapter": 5, "text": "安禄山是个左撇子，惯用左手。"},
        {"chunk_id": "m23", "chapter": 23, "text": "这天风和日丽，与本条矛盾毫不相干。"},
    ]
    out = _scan(_REAL_PAYLOAD, chunks=chunks)
    assert out == []


def test_none_chunks_keeps_old_chapter_representative(monkeypatch):
    """chunks=None 旧行为:snippet 取章脉那章代表句(向后兼容,不报错)。"""
    _patch(monkeypatch, _REAL_PAYLOAD)
    out = _scan(_REAL_PAYLOAD)  # 不传 chunks
    assert out is not None
    assert len(out) == 1
    # 旧行为挂的就是章代表句(那章最显眼的事),保持不变
    assert out[0]["a"]["snippet"] == "安禄山率十万大军压境，三军震动。"
    assert out[0]["b"]["snippet"] == "这一日朝中议事，群臣争执不休。"
    assert out[0]["a"]["verified"] is True
    assert out[0]["b"]["verified"] is True


def test_clean_book_empty_not_none(monkeypatch):
    """自洽书返空数组 → [] 而非 None(区分'没矛盾'和'扫失败')。"""
    _patch(monkeypatch, '{"contradictions": []}')
    assert _scan('{"contradictions": []}', chunks=_CHUNKS) == []


def test_fabricated_chapter_dropped(monkeypatch):
    """章号锚不到章脉真实章(LLM 编的章) → 整条丢。"""
    payload = json.dumps({"contradictions": [{
        "topic": "编的", "conflict": "瞎编", "a_chapter": 999, "b_chapter": 5,
    }]}, ensure_ascii=False)
    _patch(monkeypatch, payload)
    assert _scan(payload, chunks=_CHUNKS) == []


def test_same_chapter_dropped(monkeypatch):
    """两处同章 → 不算前后矛盾,丢。"""
    payload = json.dumps({"contradictions": [{
        "topic": "同章", "conflict": "x", "a_chapter": 5, "b_chapter": 5,
    }]}, ensure_ascii=False)
    _patch(monkeypatch, payload)
    assert _scan(payload, chunks=_CHUNKS) == []


def test_dedup_by_topic(monkeypatch):
    """同 topic 重复 → 只留一条。"""
    payload = json.dumps({"contradictions": [
        {"topic": "安禄山惯用手", "conflict": "前说左撇子后用右手",
         "a_chapter": 5, "b_chapter": 23},
        {"topic": "安禄山惯用手", "conflict": "重复一条",
         "a_chapter": 5, "b_chapter": 23},
    ]}, ensure_ascii=False)
    _patch(monkeypatch, payload)
    out = _scan(payload, chunks=_CHUNKS)
    assert len(out) == 1


def test_parse_failure_returns_none(monkeypatch):
    _patch(monkeypatch, "这不是 JSON")
    assert _scan("这不是 JSON", chunks=_CHUNKS) is None


def test_llm_raises_returns_none(monkeypatch):
    _patch(monkeypatch, "{}", raises=RuntimeError("boom"))
    assert _scan("{}", chunks=_CHUNKS) is None
