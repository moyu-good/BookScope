"""motif_tracking.generate_motif_tracking 单测（主题母题追踪）。

验 verify-filter（核验不过的复现丢）+ 成功留 / 母题不在书返 [] / 解析失败 None /
章号纠偏 / 截断抢救 / 重试。
"""

from __future__ import annotations

import json

from bookscope.agent import motif_tracking as mt

_CHUNKS = [
    {"chunk_id": "c1", "chapter": 2, "text": "正统之争贯穿始终，谁掌天命谁就是正主。"},
    {"chunk_id": "c2", "chapter": 9, "text": "后期宣传把这场叛乱重新讲成了一段神话。"},
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

    monkeypatch.setattr(mt, "_invoke_client", _fake)


def _gen(client, motif="正统"):  # noqa: ANN001
    return mt.generate_motif_tracking(
        motif=motif, full_text="x", chunks=_CHUNKS, llm_client=client, model="m"
    )


def _oc(order, chapter, manifestation, snippet):  # noqa: ANN001
    return {
        "order": order, "chapter": chapter,
        "manifestation": manifestation, "snippet": snippet,
    }


def test_success_returns_verified(monkeypatch):
    final = json.dumps(
        {"occurrences": [_oc(1, 2, "正统之争开场", "正统之争贯穿始终，谁掌天命谁就是正主")]},
        ensure_ascii=False,
    )
    _patch(monkeypatch)
    occ = _gen(_FakeClient(final))
    assert occ is not None and len(occ) == 1
    assert occ[0]["verified"] is True
    assert occ[0]["manifestation"] == "正统之争开场"


def test_unverified_dropped(monkeypatch):
    final = json.dumps(
        {"occurrences": [_oc(1, 3, "编的复现", "书里根本没有的杜撰原文")]},
        ensure_ascii=False,
    )
    _patch(monkeypatch)
    assert _gen(_FakeClient(final)) == []


def test_chapter_corrected(monkeypatch):
    final = json.dumps(
        {"occurrences": [_oc(1, 99, "宣传成神话", "后期宣传把这场叛乱重新讲成了一段神话")]},
        ensure_ascii=False,
    )
    _patch(monkeypatch)
    occ = _gen(_FakeClient(final))
    assert occ[0]["chapter"] == 9
    assert occ[0]["verified"] is True


def test_empty_returns_empty(monkeypatch):
    _patch(monkeypatch)
    assert _gen(_FakeClient('{"occurrences": []}'), motif="赛博朋克") == []


def test_parse_failure_returns_none(monkeypatch):
    _patch(monkeypatch)
    assert _gen(_FakeClient("不是 JSON")) is None


def test_salvage_truncated(monkeypatch):
    truncated = (
        '{"occurrences": [{"order": 1, "chapter": 2, "manifestation": "开场", '
        '"snippet": "正统之争贯穿始终，谁掌天命谁就是正主"}, {"order": 2, "manifestation": "未闭合'
    )
    _patch(monkeypatch)
    occ = _gen(_FakeClient(truncated))
    assert occ is not None and len(occ) == 1
    assert occ[0]["verified"] is True


def test_retry_recovers(monkeypatch):
    good = json.dumps(
        {"occurrences": [_oc(1, 2, "开场", "正统之争贯穿始终，谁掌天命谁就是正主")]},
        ensure_ascii=False,
    )
    _patch(monkeypatch)
    occ = _gen(_FakeClient(["坏 JSON", good]))
    assert occ is not None and len(occ) == 1
