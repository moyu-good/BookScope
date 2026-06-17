"""timeline.generate_timeline 单测（时间线/事件梳理）。

mock LLM + 假 client，覆盖：成功解析+按 order 排序+evidence 核验 / parse 失败→None /
空→None / 重试 / 缺 event 丢。
"""

from __future__ import annotations

import json

from bookscope.agent import timeline as tl

_CHUNKS = [
    {"chunk_id": "c1", "chapter": 4, "text": "天宝十四载十一月，安禄山在范阳起兵反唐。"},
    {"chunk_id": "c2", "chapter": 9, "text": "灵宝之战唐军大败，潼关失守。"},
]


class _FakeClient:
    def __init__(self, final_text: str) -> None:
        self._final = final_text

    def extract_final_text(self, resp):  # noqa: ANN001
        return self._final


def _patch(monkeypatch, *, raises: Exception | None = None):
    def _fake(*_a, **_k):
        if raises is not None:
            raise raises
        return {}
    monkeypatch.setattr(tl, "_invoke_client", _fake)


def _gen(payload):
    return tl.generate_timeline(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(payload), model="m",
    )


def test_success_sorted_and_verified(monkeypatch):
    _patch(monkeypatch)
    payload = json.dumps({"events": [
        {"order": 2, "time": "天宝十五载六月", "event": "灵宝之战大败",
         "chapter": 8, "evidence": "灵宝之战唐军大败，潼关失守。"},
        {"order": 1, "time": "天宝十四载十一月", "event": "安禄山起兵",
         "chapter": 8, "evidence": "天宝十四载十一月，安禄山在范阳起兵反唐。"},
    ]}, ensure_ascii=False)
    out = _gen(payload)
    assert out is not None
    assert [e["order"] for e in out] == [1, 2]  # 按 order 排
    assert out[0]["event"] == "安禄山起兵"
    assert out[0]["verified"] is True
    assert out[0]["chapter"] == 4  # 章号纠偏到命中 chunk
    assert out[1]["chapter"] == 9


def test_unverified_event_kept_marked(monkeypatch):
    """evidence 不命中的事件保留但标 verified=False（时间线重完整性）。"""
    _patch(monkeypatch)
    payload = json.dumps({"events": [
        {"order": 1, "event": "书里没有的杜撰事件", "chapter": 1,
         "evidence": "完全对不上原文的杜撰证据句子"},
    ]}, ensure_ascii=False)
    out = _gen(payload)
    assert out is not None
    assert len(out) == 1
    assert out[0]["verified"] is False


def test_salvages_truncated_json(monkeypatch):
    """长输出截断 → 抢救已闭合的事件，不整张丢。"""
    _patch(monkeypatch)
    truncated = (
        '{"events": ['
        '{"order": 1, "event": "起兵", "evidence": "安禄山在范阳起兵反唐"},'
        '{"order": 2, "event": "灵宝之战", "evidence": "灵宝之战唐军大败"},'
        '{"order": 3, "event": "截断", "evid'  # 被截断
    )
    out = _gen(truncated)
    assert out is not None
    assert len(out) == 2  # 抢救到 2 个完整事件
    assert out[0]["verified"] is True  # 抢救出的事件也过证据核验


def test_parse_failure_returns_none(monkeypatch):
    _patch(monkeypatch)
    assert _gen("这不是 JSON") is None


def test_empty_returns_none(monkeypatch):
    _patch(monkeypatch)
    assert _gen('{"events": []}') is None


def test_missing_event_field_dropped(monkeypatch):
    _patch(monkeypatch)
    payload = json.dumps({"events": [
        {"order": 1, "evidence": "天宝十四载十一月，安禄山在范阳起兵反唐。"},  # 缺 event → 丢
        {"order": 2, "event": "灵宝之战", "evidence": "灵宝之战唐军大败，潼关失守。"},
    ]}, ensure_ascii=False)
    out = _gen(payload)
    assert out is not None
    assert len(out) == 1
    assert out[0]["event"] == "灵宝之战"


def test_retries_on_parse_failure(monkeypatch):
    _patch(monkeypatch)

    class _Flaky:
        def __init__(self) -> None:
            self.calls = 0

        def extract_final_text(self, resp):  # noqa: ANN001
            self.calls += 1
            if self.calls == 1:
                return "坏的"
            return '{"events": [{"order": 1, "event": "起兵", "evidence": "x"}]}'

    client = _Flaky()
    out = tl.generate_timeline(
        full_text="x", chunks=_CHUNKS, llm_client=client, model="m",
    )
    assert out is not None
    assert client.calls == 2
