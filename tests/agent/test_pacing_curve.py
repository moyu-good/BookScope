"""pacing_curve.generate_pacing_curve 单测（节奏曲线，exp-012）。

mock LLM + 假 client，覆盖：成功解析+排序 / tension 夹到 1-5 / 丢残点 /
parse 失败→None / 空→None / 重试。
"""

from __future__ import annotations

import json

from bookscope.agent import pacing_curve as pc


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
    monkeypatch.setattr(pc, "_invoke_client", _fake)


def test_success_sorted(monkeypatch):
    payload = json.dumps({"chapters": [
        {"chapter": 3, "tension": 5, "note": "灵宝之战高潮"},
        {"chapter": 1, "tension": 2, "note": "背景铺垫"},
        {"chapter": 2, "tension": 1, "note": "制度分析"},
    ]}, ensure_ascii=False)
    _patch(monkeypatch)
    out = pc.generate_pacing_curve(
        full_text="x", llm_client=_FakeClient(payload), model="m",
    )
    assert out is not None
    assert [p["chapter"] for p in out] == [1, 2, 3]  # 按章号排序
    assert out[2]["tension"] == 5


def test_tension_clamped(monkeypatch):
    payload = json.dumps({"chapters": [
        {"chapter": 1, "tension": 9, "note": "x"},
        {"chapter": 2, "tension": 0, "note": "y"},
    ]}, ensure_ascii=False)
    _patch(monkeypatch)
    out = pc.generate_pacing_curve(
        full_text="x", llm_client=_FakeClient(payload), model="m",
    )
    assert out is not None
    assert out[0]["tension"] == 5  # 9 夹到 5
    assert out[1]["tension"] == 1  # 0 夹到 1


def test_malformed_point_dropped(monkeypatch):
    payload = json.dumps({"chapters": [
        {"chapter": 1, "note": "缺 tension"},  # 丢
        {"chapter": "二", "tension": 3},  # chapter 非 int → 丢
        {"chapter": 3, "tension": 4, "note": "ok"},
    ]}, ensure_ascii=False)
    _patch(monkeypatch)
    out = pc.generate_pacing_curve(
        full_text="x", llm_client=_FakeClient(payload), model="m",
    )
    assert out is not None
    assert len(out) == 1
    assert out[0]["chapter"] == 3


def test_parse_failure_returns_none(monkeypatch):
    _patch(monkeypatch)
    out = pc.generate_pacing_curve(
        full_text="x", llm_client=_FakeClient("这不是 JSON"), model="m",
    )
    assert out is None


def test_empty_returns_none(monkeypatch):
    _patch(monkeypatch)
    out = pc.generate_pacing_curve(
        full_text="x", llm_client=_FakeClient('{"chapters": []}'), model="m",
    )
    assert out is None


def test_retries_on_parse_failure(monkeypatch):
    _patch(monkeypatch)

    class _FlakyClient:
        def __init__(self) -> None:
            self.calls = 0

        def extract_final_text(self, resp):  # noqa: ANN001
            self.calls += 1
            if self.calls == 1:
                return "坏的"
            return '{"chapters": [{"chapter": 1, "tension": 3, "note": "ok"}]}'

    client = _FlakyClient()
    out = pc.generate_pacing_curve(full_text="x", llm_client=client, model="m")
    assert out is not None
    assert client.calls == 2
    assert out[0]["tension"] == 3
