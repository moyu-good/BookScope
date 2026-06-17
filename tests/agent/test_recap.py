"""recap.generate_recap 单测（无剧透情节回顾）。

模块层（≤X 章截断在端点做）：成功返要点 + 核验 / 解析失败 None / 空 None / 截断抢救 /
章号纠偏 / 重试。无剧透的零后文泄漏由 probe 端到端验（构造性：后文不喂）。
"""

from __future__ import annotations

import json

from bookscope.agent import recap as rc

_CHUNKS = [
    {"chunk_id": "c1", "chapter": 1, "text": "安禄山身兼范阳平卢河东三镇节度使，势力极大。"},
    {"chunk_id": "c2", "chapter": 3, "text": "他以奉唐玄宗密诏讨伐杨国忠为借口在范阳起兵。"},
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

    monkeypatch.setattr(rc, "_invoke_client", _fake)


def _gen(client):  # noqa: ANN001
    return rc.generate_recap(
        up_to_chapter=5, full_text="x", chunks=_CHUNKS, llm_client=client, model="m"
    )


def _pt(order, point, chapter, snippet):  # noqa: ANN001
    return {"order": order, "point": point, "chapter": chapter, "snippet": snippet}


def test_success_returns_verified_points(monkeypatch):
    final = json.dumps(
        {"points": [_pt(1, "安禄山掌三镇", 1, "安禄山身兼范阳平卢河东三镇节度使")]},
        ensure_ascii=False,
    )
    _patch(monkeypatch)
    pts = _gen(_FakeClient(final))
    assert pts is not None and len(pts) == 1
    assert pts[0]["verified"] is True
    assert pts[0]["point"] == "安禄山掌三镇"


def test_chapter_corrected_from_chunk(monkeypatch):
    final = json.dumps(
        {"points": [_pt(1, "起兵", 99, "他以奉唐玄宗密诏讨伐杨国忠为借口在范阳起兵")]},
        ensure_ascii=False,
    )
    _patch(monkeypatch)
    pts = _gen(_FakeClient(final))
    assert pts[0]["chapter"] == 3
    assert pts[0]["verified"] is True


def test_parse_failure_returns_none(monkeypatch):
    _patch(monkeypatch)
    assert _gen(_FakeClient("不是 JSON")) is None


def test_empty_returns_none(monkeypatch):
    _patch(monkeypatch)
    assert _gen(_FakeClient('{"points": []}')) is None


def test_llm_raises_returns_none(monkeypatch):
    _patch(monkeypatch, raises=RuntimeError("boom"))
    assert _gen(_FakeClient("{}")) is None


def test_salvage_truncated(monkeypatch):
    truncated = (
        '{"points": [{"order": 1, "point": "安禄山掌三镇", "chapter": 1, '
        '"snippet": "安禄山身兼范阳平卢河东三镇节度使"}, {"order": 2, "point": "未闭合'
    )
    _patch(monkeypatch)
    pts = _gen(_FakeClient(truncated))
    assert pts is not None and len(pts) == 1
    assert pts[0]["verified"] is True


def test_retry_recovers(monkeypatch):
    good = json.dumps(
        {"points": [_pt(1, "掌三镇", 1, "安禄山身兼范阳平卢河东三镇节度使")]},
        ensure_ascii=False,
    )
    _patch(monkeypatch)
    pts = _gen(_FakeClient(["坏 JSON", good]))
    assert pts is not None and len(pts) == 1
