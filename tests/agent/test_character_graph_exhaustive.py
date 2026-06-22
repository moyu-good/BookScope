"""extract_character_graph_exhaustive 单测（1.4 输出穷尽化 · MAP+REDUCE 编排）。

mock LLM（monkeypatch _invoke_client 给每段一个递增标记）+ 假 client（按段返不同边 JSON），
覆盖:逐段抽 → 合并 → 一次性 verify 的全链路;跨段同对去重;全段解析失败→None;分段预算。
不调真 LLM。
"""

from __future__ import annotations

import json

from bookscope.agent import character_graph as cg

_CHUNKS = [
    {"chunk_id": "c1", "chapter": 2, "text": "刘备与关羽情同手足。"},
    {"chunk_id": "c2", "chapter": 5, "text": "诸葛亮辅佐刘备。"},
]


def _seq_patch(monkeypatch) -> None:  # noqa: ANN001
    """让 _invoke_client 每次调用返一个带递增段号的标记。"""
    state = {"i": 0}

    def _fake(*_a, **_k):  # noqa: ANN002, ANN003
        i = state["i"]
        state["i"] += 1
        return {"_seg": i}

    monkeypatch.setattr(cg, "_invoke_client", _fake)


class _FakeMulti:
    """按段号返不同 final_text 的假 client。"""

    def __init__(self, texts: list[str]) -> None:
        self._texts = list(texts)

    def extract_usage_tokens(self, resp):  # noqa: ANN001
        return (10, 5)

    def extract_final_text(self, resp):  # noqa: ANN001
        i = resp.get("_seg", 0)
        return self._texts[i] if i < len(self._texts) else '{"edges": []}'


def test_exhaustive_maps_per_segment_and_merges(monkeypatch) -> None:  # noqa: ANN001
    _seq_patch(monkeypatch)
    texts = [
        json.dumps(
            {"edges": [{"source": "刘备", "target": "关羽", "relation": "同盟",
                        "strength": 5, "evidence": "刘备与关羽情同手足。"}]},
            ensure_ascii=False,
        ),
        json.dumps(
            {"edges": [{"source": "诸葛亮", "target": "刘备", "relation": "君臣",
                        "strength": 4, "evidence": "诸葛亮辅佐刘备。"}]},
            ensure_ascii=False,
        ),
    ]
    r = cg.extract_character_graph_exhaustive(
        chunks=_CHUNKS, llm_client=_FakeMulti(texts), model="m",
        char_budget=8,
        max_workers=1,
    )
    assert r is not None
    assert len(r.edges) == 2  # 两段各一条、不同对 → 合并后两条
    assert all(e["verified"] for e in r.edges)  # 两条 evidence 都逐字命中
    assert {e["chapter"] for e in r.edges} == {2, 5}  # 章号纠偏到命中 chunk
    assert set(r.nodes) >= {"刘备", "关羽", "诸葛亮"}
    assert r.input_tokens == 20  # 2 段 × 10


def test_exhaustive_dedups_same_pair_across_segments(monkeypatch) -> None:  # noqa: ANN001
    _seq_patch(monkeypatch)
    same = json.dumps(
        {"edges": [{"source": "刘备", "target": "关羽", "relation": "同盟",
                    "strength": 3, "evidence": "刘备与关羽情同手足。"}]},
        ensure_ascii=False,
    )
    r = cg.extract_character_graph_exhaustive(
        chunks=_CHUNKS, llm_client=_FakeMulti([same, same]), model="m",
        char_budget=8,
        max_workers=1,
    )
    assert r is not None
    assert len(r.edges) == 1  # 两段同一对同关系 → 合并成一条


def test_exhaustive_all_segments_unparseable_returns_none(monkeypatch) -> None:  # noqa: ANN001
    _seq_patch(monkeypatch)
    r = cg.extract_character_graph_exhaustive(
        chunks=_CHUNKS, llm_client=_FakeMulti(["不是JSON", "也不是"]), model="m",
        char_budget=8,
        max_workers=1,
    )
    assert r is None


def test_segment_chunks_splits_by_budget() -> None:
    chunks = [{"chunk_id": f"c{i}", "text": "一二三四五"} for i in range(5)]  # 每个 5 字
    assert len(cg._segment_chunks(chunks, char_budget=8)) == 5  # 每段 1 个
    assert len(cg._segment_chunks(chunks, char_budget=12)) == 3  # [c0c1][c2c3][c4]
