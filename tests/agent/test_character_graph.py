"""character_graph.extract_character_graph 单测（WP-character-graph）。

mock LLM（monkeypatch _invoke_client）+ 假 client，覆盖契约：
成功拼图 + 边证据校验 / 章号纠偏 / 未命中边 unverified / parse 失败→None /
LLM 抛错→None / 空边→None / nodes 归一 / 边端点补进 nodes / 去代码围栏。
"""

from __future__ import annotations

import json

from bookscope.agent import character_graph as cg

_CHUNKS = [
    {"chunk_id": "c1", "chapter": 2,
     "text": "安禄山身兼范阳平卢河东三镇节度使，唐玄宗对他极为宠信。"},
    {"chunk_id": "c2", "chapter": 5,
     "text": "杨国忠多次进言唐玄宗，请求严查安禄山谋反。"},
]


class _FakeClient:
    def __init__(self, final_text: str, usage=(100, 20)) -> None:
        self._final = final_text
        self._usage = usage

    def extract_usage_tokens(self, resp):  # noqa: ANN001
        return self._usage

    def extract_final_text(self, resp):  # noqa: ANN001
        return self._final


def _patch_invoke(monkeypatch, *, raises: Exception | None = None):
    def _fake(*_a, **_k):
        if raises is not None:
            raise raises
        return {"usage": {}}
    monkeypatch.setattr(cg, "_invoke_client", _fake)


def test_success_builds_graph_and_verifies_edges(monkeypatch):
    graph_json = json.dumps({
        "nodes": [{"name": "安禄山"}, {"name": "唐玄宗"}, {"name": "杨国忠"}],
        "edges": [
            {"source": "安禄山", "target": "唐玄宗", "relation": "君臣",
             "evidence": "唐玄宗对他极为宠信"},
            {"source": "杨国忠", "target": "安禄山", "relation": "政敌",
             "evidence": "杨国忠多次进言唐玄宗，请求严查安禄山谋反"},
        ],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = cg.extract_character_graph(
        full_text="（整本书……）", chunks=_CHUNKS,
        llm_client=_FakeClient(graph_json), model="deepseek-v4-flash",
    )
    assert r is not None
    assert set(r.nodes) >= {"安禄山", "唐玄宗", "杨国忠"}
    assert len(r.edges) == 2
    # 边证据命中 → verified + 用命中 chunk 的真章号
    assert r.edges[0]["verified"] is True
    assert r.edges[0]["chapter"] == 2  # 命中 c1
    assert r.edges[1]["verified"] is True
    assert r.edges[1]["chapter"] == 5  # 命中 c2
    assert r.input_tokens == 100


def test_edge_with_fabricated_evidence_unverified(monkeypatch):
    graph_json = json.dumps({
        "nodes": ["甲", "乙"],
        "edges": [{"source": "甲", "target": "乙", "relation": "同盟",
                   "evidence": "书里根本没有的杜撰句子拿来测假阳性边的情况"}],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = cg.extract_character_graph(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(graph_json), model="m",
    )
    assert r is not None
    assert r.edges[0]["verified"] is False  # 没命中
    assert r.edges[0]["chapter"] == 0  # 未命中不纠偏


def test_parse_failure_returns_none(monkeypatch):
    _patch_invoke(monkeypatch)
    r = cg.extract_character_graph(
        full_text="x", chunks=_CHUNKS,
        llm_client=_FakeClient("这不是 JSON，随便说点别的"), model="m",
    )
    assert r is None


def test_no_edges_returns_none(monkeypatch):
    graph_json = json.dumps({"nodes": ["甲"], "edges": []}, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = cg.extract_character_graph(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(graph_json), model="m",
    )
    assert r is None  # 没边的图没意义


def test_llm_raises_returns_none(monkeypatch):
    _patch_invoke(monkeypatch, raises=RuntimeError("boom"))
    r = cg.extract_character_graph(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient("{}"), model="m",
    )
    assert r is None


def test_edge_endpoint_added_to_nodes(monkeypatch):
    """边引用了 nodes 没列的人物 → 补进 nodes（模型偶尔漏列）。"""
    graph_json = json.dumps({
        "nodes": [{"name": "甲"}],
        "edges": [{"source": "甲", "target": "丙", "relation": "父子", "evidence": "x"}],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = cg.extract_character_graph(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(graph_json), model="m",
    )
    assert r is not None
    assert "丙" in r.nodes


def test_strips_code_fence(monkeypatch):
    inner = json.dumps({
        "nodes": ["甲", "乙"],
        "edges": [{"source": "甲", "target": "乙", "relation": "同僚", "evidence": "y"}],
    }, ensure_ascii=False)
    graph_json = "```json\n" + inner + "\n```"
    _patch_invoke(monkeypatch)
    r = cg.extract_character_graph(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(graph_json), model="m",
    )
    assert r is not None
    assert len(r.edges) == 1


def test_concept_unit_uses_concept_instruction(monkeypatch):
    """unit='concept' → 走概念指令 + 概念 user message（跨题材投影，exp-014）。"""
    captured: dict = {}

    def _fake(_client, **kwargs):
        captured["system"] = kwargs.get("system")
        captured["messages"] = kwargs.get("messages")
        return {"usage": {}}

    monkeypatch.setattr(cg, "_invoke_client", _fake)
    graph_json = json.dumps({
        "nodes": ["制内市场", "国家"],
        "edges": [{"source": "制内市场", "target": "国家", "relation": "定义",
                   "evidence": "z"}],
    }, ensure_ascii=False)
    r = cg.extract_character_graph(
        full_text="全书原文", chunks=_CHUNKS,
        llm_client=_FakeClient(graph_json), model="m", unit="concept",
    )
    assert r is not None
    assert "概念" in captured["system"]  # 用了概念指令不是人物指令
    assert "概念关系图" in captured["messages"][0]["content"]


def test_salvages_truncated_json(monkeypatch):
    """reasoning 吃 token 致 JSON 截断 → 抢救已闭合的边，不整张图丢掉返 None。"""
    truncated = (
        '{"nodes": [{"name": "甲"}, {"name": "乙"}], "edges": ['
        '{"source": "甲", "target": "乙", "relation": "君臣", "evidence": "x"},'
        '{"source": "乙", "target": "丙", "relation": "父子", "evidence": "y"},'
        '{"source": "丙", "target": "丁", "relation": "同盟", "evid'  # 这条被截断
    )
    _patch_invoke(monkeypatch)
    r = cg.extract_character_graph(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(truncated), model="m",
    )
    assert r is not None  # 没整张图丢掉
    assert len(r.edges) == 2  # 抢救到 2 条完整边，截断的第 3 条丢弃
    assert "丙" in r.nodes  # 端点补进 nodes


def test_edge_carries_polarity(monkeypatch):
    """边带 polarity：模型给的三选一原样保留，缺失/非法落「中」（宁可漏不可错报）。"""
    graph_json = json.dumps({
        "nodes": ["唐肃宗", "郭子仪", "安禄山", "史思明", "甲", "乙"],
        "edges": [
            # 君臣但原文亲善 → 友（身份≠立场，这正是要修的君臣误判）
            {"source": "唐肃宗", "target": "郭子仪", "relation": "君臣",
             "polarity": "友", "evidence": "唐玄宗对他极为宠信"},
            {"source": "安禄山", "target": "史思明", "relation": "政敌",
             "polarity": "敌", "evidence": "杨国忠多次进言唐玄宗，请求严查安禄山谋反"},
            {"source": "甲", "target": "乙", "relation": "同僚",
             "evidence": "x"},  # 缺 polarity → 中
            {"source": "乙", "target": "甲", "relation": "亲族",
             "polarity": "暧昧", "evidence": "y"},  # 非三选一 → 中
        ],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = cg.extract_character_graph(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(graph_json), model="m",
    )
    assert r is not None
    pol = [e["polarity"] for e in r.edges]
    assert pol == ["友", "敌", "中", "中"]


def test_malformed_edge_dropped(monkeypatch):
    """缺 source/target/relation 的边丢弃；齐全的保留。"""
    graph_json = json.dumps({
        "nodes": ["甲", "乙"],
        "edges": [
            {"source": "甲", "relation": "x"},  # 缺 target → 丢
            {"source": "甲", "target": "乙", "relation": "同盟", "evidence": "z"},
        ],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = cg.extract_character_graph(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(graph_json), model="m",
    )
    assert r is not None
    assert len(r.edges) == 1
    assert r.edges[0]["target"] == "乙"
