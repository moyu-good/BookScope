"""chapter_spine_subplot.subplot_weave_from_spine 单测（病二·证据张冠李戴的修复）。

mock invoke_client_cached + 假 client，覆盖证据现捞契约：
传 chunks → 支线 evidence 按线名在最早活跃章原文现捞 / 交汇 a_evidence≠b_evidence 各讲各线 /
现捞不到 → 空 + verified=False；chunks=None → 旧行为(章代表句、a/b 同句)向后兼容。
另覆盖 parse 失败→None / 没支线→None / LLM 抛错→None。
不跑真 LLM。
"""

from __future__ import annotations

import json

from bookscope.agent import chapter_spine_subplot as csub

# 同一章里两条线各有自己的原句——现捞要能分到不同句、各讲各线（治"a/b 同句"那条额外的病）。
_CHUNKS = [
    {"chunk_id": "c3", "chapter": 3,
     "text": "孔明出山辅佐玄德，定鼎天下大计。此外无关之事若干，不表。"},
    {"chunk_id": "c7", "chapter": 7,
     "text": "周瑜整顿水军于江东，厉兵秣马，备战在即。别有闲笔一段。"},
    {"chunk_id": "c12", "chapter": 12,
     "text": "孔明出山之策初见成效，定鼎之基已立。周瑜备战赤壁，水军列阵江上。鲁肃居中调停。"},
]

# 章脉：events 给现捞拼 query，evidence 是章代表句（chunks=None 时的旧证据来源）。
_SPINE = [
    {"chapter": 3, "evidence": "第3章章代表句（与孔明出山无关的最显眼那件事）。",
     "events": [{"event": "孔明献策"}], "present": ["孔明", "玄德"]},
    {"chapter": 7, "evidence": "第7章章代表句。",
     "events": [{"event": "周瑜点兵"}], "present": ["周瑜"]},
    {"chapter": 12, "evidence": "第12章章代表句（这章最显眼的别的事）。",
     "events": [{"event": "两线交汇"}], "present": ["孔明", "周瑜", "鲁肃"]},
]


class _FakeClient:
    def extract_final_text(self, resp):  # noqa: ANN001
        return resp if isinstance(resp, str) else ""


def _patch(monkeypatch, text: str, *, raises: Exception | None = None):
    def _fake(*_a, **_k):
        if raises is not None:
            raise raises
        return text

    monkeypatch.setattr(csub, "invoke_client_cached", _fake)


def _weave_json():
    return json.dumps({
        "subplots": [
            {"name": "孔明出山线", "active_chapters": [3, 12]},
            {"name": "周瑜备战线", "active_chapters": [7, 12]},
        ],
        "intersections": [
            {"subplots": ["孔明出山线", "周瑜备战线"], "chapter": 12},
        ],
    }, ensure_ascii=False)


def _run(monkeypatch, payload, *, chunks=None, spine=None):
    _patch(monkeypatch, payload)
    return csub.subplot_weave_from_spine(
        spine=spine if spine is not None else _SPINE,
        llm_client=_FakeClient(),
        model="deepseek-v4-flash",
        chunks=chunks,
    )


def test_with_chunks_subplot_evidence_fresh_caught(monkeypatch):
    """传 chunks → 支线 evidence 按线名在最早活跃章原文现捞，不是章代表句。"""
    r = _run(monkeypatch, _weave_json(), chunks=_CHUNKS)
    assert r is not None
    by_name = {s["name"]: s for s in r["subplots"]}
    km = by_name["孔明出山线"]
    # 最早活跃章是第3章；现捞到的应是真讲"孔明出山"的那句，不是第3章章代表句。
    assert "孔明出山" in km["evidence"]
    assert "章代表句" not in km["evidence"]
    assert km["verified"] is True
    zy = by_name["周瑜备战线"]
    assert "周瑜" in zy["evidence"] and "备战" in zy["evidence"]
    assert "章代表句" not in zy["evidence"]


def test_with_chunks_intersection_a_b_evidence_differ(monkeypatch):
    """传 chunks → 交汇 a_evidence / b_evidence 按两条线名各自现捞，两句不同、各讲各线。"""
    r = _run(monkeypatch, _weave_json(), chunks=_CHUNKS)
    assert len(r["intersections"]) == 1
    it = r["intersections"][0]
    # 这是这次修复的核心：旧实现两端回退到同一条章代表句，现在两端各讲各线。
    assert it["a_evidence"] != it["b_evidence"]
    assert "孔明出山" in it["a_evidence"]            # a 线 = 孔明出山线
    assert "周瑜" in it["b_evidence"] and "备战" in it["b_evidence"]  # b 线 = 周瑜备战线
    assert "章代表句" not in it["a_evidence"]
    assert "章代表句" not in it["b_evidence"]
    assert it["a_verified"] is True and it["b_verified"] is True


def test_with_chunks_no_support_unverified(monkeypatch):
    """某线在锚定章原文里捞不到任何讲它的句子 → evidence 空、verified=False（不硬塞）。"""
    payload = json.dumps({
        "subplots": [
            # 第7章原文只讲周瑜备战，没有"祭祀典礼"半个字 → 捞不到。
            {"name": "祭祀典礼线", "active_chapters": [7]},
        ],
        "intersections": [],
    }, ensure_ascii=False)
    r = _run(monkeypatch, payload, chunks=_CHUNKS)
    assert r is not None
    sp = r["subplots"][0]
    assert sp["evidence"] == ""
    assert sp["verified"] is False
    assert sp["match_score"] == 0.0


def test_without_chunks_backward_compatible(monkeypatch):
    """chunks=None → 旧行为：支线 evidence 取章代表句，交汇 a/b_evidence 同句（向后兼容）。"""
    r = _run(monkeypatch, _weave_json(), chunks=None)
    assert r is not None
    km = next(s for s in r["subplots"] if s["name"] == "孔明出山线")
    # 旧行为：取最早活跃章（第3章）的章脉证据 = 章代表句
    assert km["evidence"] == "第3章章代表句（与孔明出山无关的最显眼那件事）。"
    assert km["verified"] is True
    it = r["intersections"][0]
    # 旧行为：交汇两端都回退到交汇章（第12章）章代表句，a/b 同句
    assert it["a_evidence"] == it["b_evidence"]
    assert it["a_evidence"] == "第12章章代表句（这章最显眼的别的事）。"


def test_parse_failure_returns_none(monkeypatch):
    r = _run(monkeypatch, "这不是 JSON，随便说点别的", chunks=_CHUNKS)
    assert r is None


def test_no_subplots_returns_none(monkeypatch):
    payload = json.dumps({"subplots": [], "intersections": []}, ensure_ascii=False)
    r = _run(monkeypatch, payload, chunks=_CHUNKS)
    assert r is None


def test_llm_raises_returns_none(monkeypatch):
    _patch(monkeypatch, "{}", raises=RuntimeError("boom"))
    r = csub.subplot_weave_from_spine(
        spine=_SPINE, llm_client=_FakeClient(), model="m", chunks=_CHUNKS,
    )
    assert r is None
