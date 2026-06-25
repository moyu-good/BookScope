"""chapter_spine_concept_graph.concept_graph_from_spine 单测（病二修复:证据现捞）。

重点验:
- 传 chunks 时每条边 evidence 在锚定章原文里按 source/target/relation 现捞,真讲这两个概念
  这种关系(不是章代表句);锚不到 / 原文里捞不到 → verified=False、evidence 空。
- chunks=None 保旧行为:evidence 取章脉那章代表句、向后兼容不报错。
- 无 claims → None / 解析失败 → None。
mock invoke_client_cached + 假 client,不跑真 LLM。
"""

from __future__ import annotations

import json

from bookscope.agent import chapter_spine_concept_graph as cg

# 章脉:理论书概念维(每章 claims),evidence 是「这章最显眼那件事」的章代表句。
# 故意让章代表句讲的是别的概念(制内市场),好暴露「张冠李戴」——边讲的是 A↔B,
# 旧实现却把这条无关的章代表句挂上去。
_SPINE = [
    {
        "chapter": 3,
        "evidence": "本章最显眼的论断是制内市场重塑了激励结构。",
        "claims": ["国家能力决定发展路径", "财政集权是国家能力的基础"],
    },
    {
        "chapter": 8,
        "evidence": "第八章着重谈了官僚激励的扭曲。",
        "claims": ["市场化改革依赖产权保护", "产权保护反过来制约国家汲取"],
    },
]

# 全书原文:第 3 章真有「国家能力 包含 财政集权」这句;第 8 章真有「产权保护 制约 国家汲取」。
# 每章都另塞一句无关但显眼的句子(对应章代表句),验现捞不会错抓它。
_CHUNKS = [
    {"chunk_id": "c3a", "chapter": 3,
     "text": "国家能力包含财政集权这一核心维度，没有汲取就没有治理。"},
    {"chunk_id": "c3b", "chapter": 3,
     "text": "本章最显眼的论断是制内市场重塑了激励结构。"},
    {"chunk_id": "c8a", "chapter": 8,
     "text": "产权保护会制约国家汲取，二者长期处于张力之中。"},
    {"chunk_id": "c8b", "chapter": 8,
     "text": "第八章着重谈了官僚激励的扭曲。"},
]


class _FakeClient:
    def extract_final_text(self, resp):  # noqa: ANN001
        return resp if isinstance(resp, str) else ""


def _patch(monkeypatch, text: str, *, raises: Exception | None = None) -> None:
    def _fake(*_a, **_k):
        if raises is not None:
            raise raises
        return text

    monkeypatch.setattr(cg, "invoke_client_cached", _fake)


def _run(*, spine=None, chunks=None):  # noqa: ANN001
    return cg.concept_graph_from_spine(
        spine=spine if spine is not None else _SPINE,
        chunks=chunks,
        llm_client=_FakeClient(),
        model="deepseek-v4-flash",
    )


def _edge(source, target, relation, chapter, strength=3):  # noqa: ANN001
    return {
        "source": source, "target": target, "relation": relation,
        "strength": strength, "chapter": chapter,
    }


_TWO_EDGES = json.dumps({
    "nodes": [
        {"name": "国家能力"}, {"name": "财政集权"},
        {"name": "产权保护"}, {"name": "国家汲取"},
    ],
    "edges": [
        _edge("国家能力", "财政集权", "包含", 3, 5),
        _edge("产权保护", "国家汲取", "制约", 8, 3),
    ],
}, ensure_ascii=False)


def test_with_chunks_evidence_is_value_specific(monkeypatch):
    """传 chunks:边 evidence 真讲这两个概念这种关系,不是章代表句(制内市场那句)。"""
    _patch(monkeypatch, _TWO_EDGES)
    g = _run(chunks=_CHUNKS)
    assert g is not None
    edges = {(e["source"], e["target"]): e for e in g["edges"]}

    e1 = edges[("国家能力", "财政集权")]
    assert "国家能力" in e1["evidence"] and "财政集权" in e1["evidence"]
    assert "制内市场" not in e1["evidence"]  # 没挂上无关的章代表句
    assert e1["verified"] is True and e1["chapter"] == 3

    e2 = edges[("产权保护", "国家汲取")]
    assert "产权保护" in e2["evidence"] and "国家汲取" in e2["evidence"]
    assert "官僚激励" not in e2["evidence"]  # 第 8 章的章代表句也没被挂上
    assert e2["verified"] is True and e2["chapter"] == 8


def test_with_chunks_unfound_marks_unverified(monkeypatch):
    """传 chunks 但锚定章原文里压根没这两个概念 → evidence 空、verified=False。"""
    # 这条边锚到第 3 章(真有主张),但「量子纠缠↔测不准」在第 3 章原文里捞不到。
    edges_json = json.dumps({
        "nodes": [{"name": "量子纠缠"}, {"name": "测不准"}],
        "edges": [_edge("量子纠缠", "测不准", "因果", 3)],
    }, ensure_ascii=False)
    _patch(monkeypatch, edges_json)
    g = _run(chunks=_CHUNKS)
    assert g is not None and len(g["edges"]) == 1
    e = g["edges"][0]
    assert e["evidence"] == ""  # 捞不到不硬塞章代表句
    assert e["verified"] is False
    assert e["match_score"] == 0.0


def test_chunks_none_keeps_chapter_representative(monkeypatch):
    """chunks=None(默认):向后兼容,evidence 退回章脉那章代表句、不报错。"""
    _patch(monkeypatch, _TWO_EDGES)
    g = _run()  # 不传 chunks
    assert g is not None
    edges = {(e["source"], e["target"]): e for e in g["edges"]}

    e1 = edges[("国家能力", "财政集权")]
    assert e1["evidence"] == "本章最显眼的论断是制内市场重塑了激励结构。"  # 旧行为=章代表句
    assert e1["verified"] is True and e1["chapter"] == 3


def test_edge_anchored_to_fake_chapter_dropped_evidence(monkeypatch):
    """LLM 编了个不在 claim_chs 的章号 → anchored=False、evidence 空、verified=False。"""
    edges_json = json.dumps({
        "nodes": [{"name": "国家能力"}, {"name": "财政集权"}],
        "edges": [_edge("国家能力", "财政集权", "包含", 99)],
    }, ensure_ascii=False)
    _patch(monkeypatch, edges_json)
    g = _run(chunks=_CHUNKS)
    assert g is not None and len(g["edges"]) == 1
    e = g["edges"][0]
    assert e["verified"] is False and e["evidence"] == "" and e["chapter"] == 0


def test_no_claims_returns_none(monkeypatch):
    """小说章脉(没 claims)→ 概念图不适用,返 None。"""
    _patch(monkeypatch, _TWO_EDGES)
    fiction_spine = [{"chapter": 1, "evidence": "刘备三顾茅庐。", "relations": []}]
    assert _run(spine=fiction_spine, chunks=_CHUNKS) is None


def test_parse_failure_returns_none(monkeypatch):
    _patch(monkeypatch, "这不是 JSON")
    assert _run(chunks=_CHUNKS) is None
