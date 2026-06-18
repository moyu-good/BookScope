"""annotations.generate_annotations 单测（WP-annotated-reading 编排器）。

mock 掉各数据源 generate_*（monkeypatch annotations 模块里的引用），不跑真 LLM。覆盖契约：

- 每个 layer 调对应源、把已核验结论映射成注释；
- evidence-first：verified=false 的结论不进（foreshadow payoff 未核验、entity 未核验、
  consistency 单侧未核验 都不出现 / 降级）；
- 跨章类带 target_*（伏笔回收 → 回收处、设定矛盾 → b 侧）；
- chapters 只返有注释牵涉到的章（含 target 章）的原文、按章号排序；
- 未知 layer 忽略；entity/motif 没给名字时跳过那一层；
- 单层数据源抛错被跳过、不拖垮整次编排（不在 scanned 里）；
- 按 (chapter, layer) 排序。
"""

from __future__ import annotations

from bookscope.agent import annotations as ann

_CHUNKS = [
    {"chunk_id": "r0-chunk-0", "chapter": 2, "text": "第二章原文。墙角断剑落满灰尘。"},
    {"chunk_id": "r0-chunk-1", "chapter": 4, "text": "第四章原文。白衣郎中看了手相便走。"},
    {"chunk_id": "r0-chunk-2", "chapter": 9, "text": "第九章原文。少年拔起断剑认主。"},
]


def _no_llm(monkeypatch):
    """把四个数据源默认 patch 成返空，单测各自再覆盖需要的那一个。"""
    monkeypatch.setattr(ann, "generate_foreshadow_arcs", lambda **_: None)
    monkeypatch.setattr(ann, "generate_motif_tracking", lambda **_: [])
    monkeypatch.setattr(ann, "generate_consistency_scan", lambda **_: [])
    monkeypatch.setattr(ann, "generate_entity_recall", lambda **_: [])


def _run(layers, **kw):
    return ann.generate_annotations(
        layers=layers,
        full_text="（整本书……）",
        chunks=_CHUNKS,
        llm_client=object(),
        model="deepseek-v4-flash",
        **kw,
    )


def test_foreshadow_resolved_arc_maps_with_target(monkeypatch):
    """已回收实弧 → 埋点处一条注释 + target_* 指向回收处。"""
    _no_llm(monkeypatch)
    monkeypatch.setattr(ann, "generate_foreshadow_arcs", lambda **_: [
        {
            "description": "断剑认主",
            "setup_chapter": 2, "payoff_chapter": 9,
            "setup_evidence": "墙角断剑落满灰尘", "payoff_evidence": "少年拔起断剑认主",
            "status": "resolved", "setup_verified": True, "payoff_verified": True,
            "setup_match_score": 1.0, "payoff_match_score": 1.0,
        },
    ])
    r = _run(["foreshadow"])
    assert r["scanned"] == ["foreshadow"]
    assert len(r["annotations"]) == 1
    a = r["annotations"][0]
    assert a["layer"] == "foreshadow"
    assert a["type"] == "伏笔回收"
    assert a["chapter"] == 2
    assert a["snippet"] == "墙角断剑落满灰尘"
    assert a["target_chapter"] == 9
    assert a["target_snippet"] == "少年拔起断剑认主"
    # chapters：埋点章 + 回收章都返
    assert [c["chapter"] for c in r["chapters"]] == [2, 9]


def test_foreshadow_dangling_arc_no_target(monkeypatch):
    """断弧（埋了没回收）→ 一条注释、无 target。"""
    _no_llm(monkeypatch)
    monkeypatch.setattr(ann, "generate_foreshadow_arcs", lambda **_: [
        {
            "description": "白衣郎中", "setup_chapter": 4, "payoff_chapter": None,
            "setup_evidence": "白衣郎中看了手相便走", "payoff_evidence": "",
            "status": "dangling", "setup_verified": True, "payoff_verified": False,
            "setup_match_score": 1.0, "payoff_match_score": 0.0,
        },
    ])
    r = _run(["foreshadow"])
    a = r["annotations"][0]
    assert a["type"] == "断弧"
    assert a["chapter"] == 4
    assert a["target_chapter"] is None
    assert a["target_snippet"] is None
    assert [c["chapter"] for c in r["chapters"]] == [4]


def test_foreshadow_failure_returns_no_annotations(monkeypatch):
    """数据源返 None（失败）→ 没注释，该层不算 scanned 成功。"""
    _no_llm(monkeypatch)  # foreshadow 默认就是 None
    r = _run(["foreshadow"])
    assert r["annotations"] == []
    assert r["chapters"] == []
    # None 返回不抛错、走 [] 分支，仍记 scanned（跑了、只是没产出）
    assert r["scanned"] == ["foreshadow"]


def test_contradiction_maps_both_sides(monkeypatch):
    """设定矛盾 → a 侧一条注释 + target_* 指向 b 侧。"""
    _no_llm(monkeypatch)
    monkeypatch.setattr(ann, "generate_consistency_scan", lambda **_: [
        {
            "topic": "断剑归属", "conflict": "第2章说断剑无主、第9章说认主",
            "a": {"snippet": "墙角断剑落满灰尘", "chapter": 2, "verified": True},
            "b": {"snippet": "少年拔起断剑认主", "chapter": 9, "verified": True},
        },
    ])
    r = _run(["contradiction"])
    a = r["annotations"][0]
    assert a["layer"] == "contradiction"
    assert a["chapter"] == 2
    assert a["snippet"] == "墙角断剑落满灰尘"
    assert a["target_chapter"] == 9
    assert a["target_snippet"] == "少年拔起断剑认主"
    assert a["summary"] == "第2章说断剑无主、第9章说认主"


def test_contradiction_drops_unverified_side(monkeypatch):
    """一侧未核验 → evidence-first 整条丢。"""
    _no_llm(monkeypatch)
    monkeypatch.setattr(ann, "generate_consistency_scan", lambda **_: [
        {
            "topic": "x", "conflict": "y",
            "a": {"snippet": "墙角断剑落满灰尘", "chapter": 2, "verified": True},
            "b": {"snippet": "编的", "chapter": 9, "verified": False},
        },
    ])
    r = _run(["contradiction"])
    assert r["annotations"] == []


def test_motif_layer_maps_verified_occurrences(monkeypatch):
    """母题复现 → 每处一条注释（只收 verified）。"""
    _no_llm(monkeypatch)
    monkeypatch.setattr(ann, "generate_motif_tracking", lambda **_: [
        {"order": 1, "chapter": 2, "manifestation": "初现",
         "snippet": "墙角断剑落满灰尘", "verified": True},
        {"order": 2, "chapter": 9, "manifestation": "复现",
         "snippet": "编的", "verified": False},
    ])
    r = _run(["motif"], motif="断剑")
    assert len(r["annotations"]) == 1
    a = r["annotations"][0]
    assert a["layer"] == "motif"
    assert "断剑" in a["type"]
    assert a["chapter"] == 2
    assert a["target_chapter"] is None


def test_motif_skipped_without_name(monkeypatch):
    """选 motif 层但没给母题名 → 跳过那层，不报错。"""
    _no_llm(monkeypatch)
    called = {"motif": False}

    def _spy(**_):
        called["motif"] = True
        return []
    monkeypatch.setattr(ann, "generate_motif_tracking", _spy)
    r = _run(["motif"])  # 没给 motif=
    assert r["annotations"] == []
    assert called["motif"] is False  # 没名字根本不调数据源


def test_entity_layer_filters_unverified(monkeypatch):
    """实体出现 → 每处一条注释；entity_recall 保留未核验的，编排器只收 verified。"""
    _no_llm(monkeypatch)
    monkeypatch.setattr(ann, "generate_entity_recall", lambda **_: [
        {"order": 1, "chapter": 2, "what": "登场", "snippet": "墙角断剑落满灰尘", "verified": True},
        {"order": 2, "chapter": 4, "what": "再现", "snippet": "未核验句", "verified": False},
    ])
    r = _run(["entity"], entity="断剑")
    assert len(r["annotations"]) == 1
    assert r["annotations"][0]["chapter"] == 2


def test_unknown_layer_ignored(monkeypatch):
    """未知图层名忽略，不进 scanned。"""
    _no_llm(monkeypatch)
    r = _run(["nope", "foreshadow"])
    assert r["scanned"] == ["foreshadow"]


def test_layer_exception_skipped(monkeypatch):
    """单层数据源抛错 → 跳过那层、不拖垮整次编排，不在 scanned 里。"""
    _no_llm(monkeypatch)

    def _boom(**_):
        raise RuntimeError("source blew up")
    monkeypatch.setattr(ann, "generate_consistency_scan", _boom)
    monkeypatch.setattr(ann, "generate_motif_tracking", lambda **_: [
        {"order": 1, "chapter": 2, "manifestation": "x",
         "snippet": "墙角断剑落满灰尘", "verified": True},
    ])
    r = _run(["contradiction", "motif"], motif="断剑")
    assert "contradiction" not in r["scanned"]
    assert r["scanned"] == ["motif"]
    assert len(r["annotations"]) == 1


def test_annotations_sorted_by_chapter_then_layer(monkeypatch):
    """多层多条 → 按 (chapter, layer) 排序。"""
    _no_llm(monkeypatch)
    monkeypatch.setattr(ann, "generate_foreshadow_arcs", lambda **_: [
        {
            "description": "晚埋", "setup_chapter": 9, "payoff_chapter": None,
            "setup_evidence": "少年拔起断剑认主", "payoff_evidence": "",
            "status": "dangling", "setup_verified": True, "payoff_verified": False,
            "setup_match_score": 1.0, "payoff_match_score": 0.0,
        },
    ])
    monkeypatch.setattr(ann, "generate_motif_tracking", lambda **_: [
        {"order": 1, "chapter": 2, "manifestation": "x",
         "snippet": "墙角断剑落满灰尘", "verified": True},
    ])
    r = _run(["foreshadow", "motif"], motif="断剑")
    chapters_layers = [(a["chapter"], a["layer"]) for a in r["annotations"]]
    assert chapters_layers == [(2, "motif"), (9, "foreshadow")]


def test_empty_layers_returns_empty(monkeypatch):
    _no_llm(monkeypatch)
    r = _run([])
    assert r["annotations"] == []
    assert r["chapters"] == []
    assert r["scanned"] == []
