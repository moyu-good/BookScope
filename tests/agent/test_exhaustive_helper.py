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


# ── reduce 合并件（纯函数，直接喂 outs，不过 LLM）─────────────────────────────


def test_merge_by_chapter_dedups_and_sorts() -> None:
    outs = [
        [{"chapter": 2, "v": "a"}, {"chapter": 1, "v": "a"}],
        [{"chapter": 3, "v": "b"}, {"chapter": 2, "v": "dup"}],
    ]
    out = ex.merge_by_chapter(outs)
    assert [c["chapter"] for c in out] == [1, 2, 3]
    assert next(c for c in out if c["chapter"] == 2)["v"] == "a"  # 保先出现


def test_merge_by_key_dedups_keeps_first() -> None:
    outs = [
        [{"event": "赤壁", "x": 1}, {"event": "官渡", "x": 1}],
        [{"event": "赤壁", "x": 2}, {"event": "夷陵", "x": 3}],  # 赤壁跨段重复
    ]
    out = ex.merge_by_key(outs, key_fn=lambda e: e["event"])
    assert [e["event"] for e in out] == ["赤壁", "官渡", "夷陵"]
    assert out[0]["x"] == 1  # 保先出现段的值


def test_merge_by_key_drops_none_key() -> None:
    outs = [[{"event": "赤壁"}, {"noevent": True}]]
    out = ex.merge_by_key(outs, key_fn=lambda e: e.get("event"))
    assert [e.get("event") for e in out] == ["赤壁"]  # key=None 丢


def test_merge_keyed_points_unions_subpoints_by_chapter() -> None:
    # 同一角色「刘备」跨两段，各带不同章的 points；标量 name 保先出现
    outs = [
        [{"name": "刘备", "points": [{"chapter": 1, "v": 5}, {"chapter": 2, "v": 6}]}],
        [{"name": "刘备", "points": [{"chapter": 2, "v": 99}, {"chapter": 5, "v": 7}]},
         {"name": "曹操", "points": [{"chapter": 1, "v": 8}]}],
    ]
    out = ex.merge_keyed_points(outs, key_fn=lambda c: c["name"], point_fields=["points"])
    assert [c["name"] for c in out] == ["刘备", "曹操"]  # 按首见顺序
    liubei = out[0]
    assert [p["chapter"] for p in liubei["points"]] == [1, 2, 5]  # 并集 + 升序
    assert next(p for p in liubei["points"] if p["chapter"] == 2)["v"] == 6  # 章 2 保先出现


def test_merge_keyed_points_multiple_point_fields() -> None:
    outs = [
        [{"a": "刘备", "b": "曹操", "relation": "政敌",
          "points": [{"chapter": 1, "strength": 3}],
          "turning_points": [{"chapter": 1, "change": "初见"}]}],
        [{"a": "刘备", "b": "曹操", "relation": "ignored",
          "points": [{"chapter": 9, "strength": 8}],
          "turning_points": [{"chapter": 9, "change": "决裂"}]}],
    ]
    out = ex.merge_keyed_points(
        outs, key_fn=lambda r: frozenset((r["a"], r["b"])),
        point_fields=["points", "turning_points"],
    )
    assert len(out) == 1
    assert out[0]["relation"] == "政敌"  # 标量保先出现
    assert [p["chapter"] for p in out[0]["points"]] == [1, 9]
    assert [t["chapter"] for t in out[0]["turning_points"]] == [1, 9]
