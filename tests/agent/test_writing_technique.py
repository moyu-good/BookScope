"""writing_technique.generate_writing_technique 单测（写作手法分析）。

验 verify-filter（核验不过的手法丢）+ 成功留 / 空返 [] / 解析失败 None / 章号纠偏 /
截断抢救 / 重试 / technique 缺失丢。
"""

from __future__ import annotations

import json

from bookscope.agent import writing_technique as wt

_CHUNKS = [
    {"chunk_id": "c1", "chapter": 1, "text": "作者先抛出反常识的论点，再层层用史料夯实。"},
    {"chunk_id": "c2", "chapter": 5, "text": "他常用设问句把读者带进推理：真是这样吗？"},
]


class _FakeClient:
    def __init__(self, finals) -> None:  # noqa: ANN001
        self._texts = [finals] if isinstance(finals, str) else list(finals)
        self._i = 0

    def extract_final_text(self, resp):  # noqa: ANN001
        t = self._texts[min(self._i, len(self._texts) - 1)]
        self._i += 1
        return t


def _patch(monkeypatch, *, raises: Exception | None = None) -> None:
    def _fake(*_a, **_k):
        if raises is not None:
            raise raises
        return {"usage": {}}

    monkeypatch.setattr(wt, "_invoke_client", _fake)


def _gen(client):  # noqa: ANN001
    return wt.generate_writing_technique(
        full_text="x", chunks=_CHUNKS, llm_client=client, model="m"
    )


def _t(order, technique, how, chapter, snippet):  # noqa: ANN001
    return {
        "order": order, "technique": technique,
        "how": how, "chapter": chapter, "snippet": snippet,
    }


def test_success_returns_verified(monkeypatch):
    final = json.dumps(
        {"techniques": [
            _t(1, "反常识开篇", "先抛论点再夯实", 1,
               "作者先抛出反常识的论点，再层层用史料夯实"),
        ]},
        ensure_ascii=False,
    )
    _patch(monkeypatch)
    ts = _gen(_FakeClient(final))
    assert ts is not None and len(ts) == 1
    assert ts[0]["verified"] is True
    assert ts[0]["technique"] == "反常识开篇"


def test_unverified_dropped(monkeypatch):
    final = json.dumps(
        {"techniques": [_t(1, "编的手法", "x", 3, "书里根本没有的杜撰原文")]},
        ensure_ascii=False,
    )
    _patch(monkeypatch)
    assert _gen(_FakeClient(final)) == []


def test_techniqueless_dropped(monkeypatch):
    # 缺 technique 名 → 丢
    final = json.dumps(
        {"techniques": [
            {"order": 1, "chapter": 1,
             "snippet": "作者先抛出反常识的论点，再层层用史料夯实"},
        ]},
        ensure_ascii=False,
    )
    _patch(monkeypatch)
    assert _gen(_FakeClient(final)) == []


def test_chapter_corrected(monkeypatch):
    final = json.dumps(
        {"techniques": [
            _t(1, "设问引导", "设问带读者推理", 99,
               "他常用设问句把读者带进推理：真是这样吗？"),
        ]},
        ensure_ascii=False,
    )
    _patch(monkeypatch)
    ts = _gen(_FakeClient(final))
    assert ts[0]["chapter"] == 5
    assert ts[0]["verified"] is True


def test_empty_returns_empty(monkeypatch):
    _patch(monkeypatch)
    assert _gen(_FakeClient('{"techniques": []}')) == []


def test_parse_failure_returns_none(monkeypatch):
    _patch(monkeypatch)
    assert _gen(_FakeClient("不是 JSON")) is None


def test_retry_recovers(monkeypatch):
    good = json.dumps(
        {"techniques": [
            _t(1, "设问", "设问引导", 5,
               "他常用设问句把读者带进推理：真是这样吗？"),
        ]},
        ensure_ascii=False,
    )
    _patch(monkeypatch)
    ts = _gen(_FakeClient(["坏 JSON", good]))
    assert ts is not None and len(ts) == 1
