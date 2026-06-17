"""consistency_scan.generate_consistency_scan 单测（设定一致性，exp-011）。

mock LLM + 假 client，覆盖：真矛盾两处都核验→保留 / 自洽空数组→[] 非 None /
命根子：编的矛盾(snippet 不命中)→丢 / 一处不命中→丢 / parse 失败→None / 重试 / 去重。
"""

from __future__ import annotations

import json

from bookscope.agent import consistency_scan as cs

_CHUNKS = [
    {"chunk_id": "c1", "chapter": 5, "text": "安禄山是个左撇子，平日惯用左手持物。"},
    {"chunk_id": "c2", "chapter": 23, "text": "安禄山曾用右手狠狠挥动马鞭督战。"},
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
    monkeypatch.setattr(cs, "_invoke_client", _fake)


def _scan(payload):
    return cs.generate_consistency_scan(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(payload), model="m",
    )


def test_real_contradiction_both_verified_kept(monkeypatch):
    _patch(monkeypatch)
    payload = json.dumps({"contradictions": [{
        "topic": "安禄山惯用手", "conflict": "前说左撇子后用右手",
        "a": {"snippet": "安禄山是个左撇子，平日惯用左手持物。", "chapter": 9},
        "b": {"snippet": "安禄山曾用右手狠狠挥动马鞭督战。", "chapter": 9},
    }]}, ensure_ascii=False)
    out = _scan(payload)
    assert out is not None
    assert len(out) == 1
    assert out[0]["a"]["verified"] is True
    assert out[0]["b"]["verified"] is True
    assert out[0]["a"]["chapter"] == 5  # 章号纠偏到命中 chunk 真章号
    assert out[0]["b"]["chapter"] == 23


def test_clean_book_empty_not_none(monkeypatch):
    """自洽书返空数组 → [] 而非 None（区分'没矛盾'和'扫失败'）。"""
    _patch(monkeypatch)
    out = _scan('{"contradictions": []}')
    assert out == []  # 空但成功，不是 None


def test_fabricated_contradiction_dropped(monkeypatch):
    """命根子：编的矛盾 snippet 不命中原文 → 两处都 unverified → 丢。"""
    _patch(monkeypatch)
    payload = json.dumps({"contradictions": [{
        "topic": "编的", "conflict": "瞎编的矛盾",
        "a": {"snippet": "书里根本没有的杜撰句子甲拿来测命根子", "chapter": 1},
        "b": {"snippet": "书里根本没有的杜撰句子乙拿来测命根子", "chapter": 2},
    }]}, ensure_ascii=False)
    out = _scan(payload)
    assert out == []  # 编的矛盾被命根子守卫丢掉


def test_one_side_unverified_dropped(monkeypatch):
    """一处证据不命中 → 整条丢（真矛盾要两处都真）。"""
    _patch(monkeypatch)
    payload = json.dumps({"contradictions": [{
        "topic": "半真", "conflict": "一处真一处假",
        "a": {"snippet": "安禄山是个左撇子，平日惯用左手持物。", "chapter": 5},
        "b": {"snippet": "完全杜撰对不上原文的另一处证据", "chapter": 9},
    }]}, ensure_ascii=False)
    out = _scan(payload)
    assert out == []


def test_parse_failure_returns_none(monkeypatch):
    _patch(monkeypatch)
    out = _scan("这不是 JSON")
    assert out is None


def test_malformed_missing_side_dropped(monkeypatch):
    _patch(monkeypatch)
    payload = json.dumps({"contradictions": [
        {"topic": "缺 b", "a": {"snippet": "安禄山是个左撇子，平日惯用左手持物。"}},
    ]}, ensure_ascii=False)
    out = _scan(payload)
    assert out == []  # 缺一处 → coerce 丢


def test_retries_on_parse_failure(monkeypatch):
    _patch(monkeypatch)

    class _Flaky:
        def __init__(self) -> None:
            self.calls = 0

        def extract_final_text(self, resp):  # noqa: ANN001
            self.calls += 1
            if self.calls == 1:
                return "坏的"
            return '{"contradictions": []}'

    client = _Flaky()
    out = cs.generate_consistency_scan(
        full_text="x", chunks=_CHUNKS, llm_client=client, model="m",
    )
    assert out == []
    assert client.calls == 2
