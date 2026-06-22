"""_internal/exhaustive.py —— 按章 map-reduce 可复用件单测(分段 + 按章 concat 去重)。

mock LLM(monkeypatch invoke_client_cached 给每段递增标记)+ 假 client(按段返不同章 JSON)。
不调真 LLM。
"""

from __future__ import annotations

import json

import bookscope.agent._internal.exhaustive as ex


def test_segment_chunks_splits_by_budget() -> None:
    chunks = [{"chunk_id": f"c{i}", "text": "一二三四五"} for i in range(5)]  # 每个 5 字
    assert len(ex.segment_chunks(chunks, char_budget=8)) == 5  # 每段 1 个
    assert len(ex.segment_chunks(chunks, char_budget=12)) == 3  # [c0c1][c2c3][c4]
    assert len(ex.segment_chunks([], 40)) == 0


def test_resolve_workers() -> None:
    assert ex.resolve_workers(3) == 3
    assert ex.resolve_workers(0) == 1  # < 1 兜底 1
    assert ex.resolve_workers(None, default=6) == 6


class _FakeMulti:
    def __init__(self, texts: list[str]) -> None:
        self._texts = list(texts)

    def extract_usage_tokens(self, resp):  # noqa: ANN001
        return (10, 5)

    def extract_final_text(self, resp):  # noqa: ANN001
        i = resp.get("_seg", 0)
        return self._texts[i] if i < len(self._texts) else '{"chapters": []}'


def _seq_patch(monkeypatch) -> None:  # noqa: ANN001
    state = {"i": 0}

    def _fake(*_a, **_k):  # noqa: ANN002, ANN003
        i = state["i"]
        state["i"] += 1
        return {"_seg": i}

    monkeypatch.setattr(ex, "invoke_client_cached", _fake)


def _parse(text: str):  # noqa: ANN202
    try:
        return json.loads(text).get("chapters", [])
    except Exception:
        return []


def test_mapreduce_concats_and_dedups_by_chapter(monkeypatch) -> None:  # noqa: ANN001
    _seq_patch(monkeypatch)
    chunks = [{"chunk_id": "c0", "text": "甲"}, {"chunk_id": "c1", "text": "乙"}]
    texts = [
        json.dumps({"chapters": [{"chapter": 2, "v": "a"}, {"chapter": 1, "v": "a"}]}),
        json.dumps({"chapters": [{"chapter": 3, "v": "b"}, {"chapter": 2, "v": "dup"}]}),
    ]
    out = ex.mapreduce_per_chapter(
        chunks=chunks, instruction="x", user_msg="y", parse_fn=_parse,
        llm_client=_FakeMulti(texts), model="m", max_tokens=100,
        char_budget=1, max_workers=1,  # char_budget=1 → 每 chunk 一段
    )
    # 1,2,3 各一条;章 2 跨段重复 → 只留首见(第一段的 "a")
    assert [c["chapter"] for c in out] == [1, 2, 3]
    assert next(c for c in out if c["chapter"] == 2)["v"] == "a"


def test_mapreduce_skips_unparseable_segment(monkeypatch) -> None:  # noqa: ANN001
    _seq_patch(monkeypatch)
    chunks = [{"chunk_id": "c0", "text": "甲"}, {"chunk_id": "c1", "text": "乙"}]
    out = ex.mapreduce_per_chapter(
        chunks=chunks, instruction="x", user_msg="y", parse_fn=_parse,
        llm_client=_FakeMulti(["不是JSON", json.dumps({"chapters": [{"chapter": 5}]})]),
        model="m", max_tokens=100, char_budget=1, max_workers=1,
    )
    assert [c["chapter"] for c in out] == [5]  # 坏段跳过,好段保留
