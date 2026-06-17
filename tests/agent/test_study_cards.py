"""study_cards.generate_study_cards 单测（知识点卡片）。

验 verify-filter（核验不过的卡丢）+ 成功留 / 空返 [] / 解析失败 None / 章号纠偏 /
concept 缺失丢 / 重试。
"""

from __future__ import annotations

import json

from bookscope.agent import study_cards as sc

_CHUNKS = [
    {"chunk_id": "c1", "chapter": 2, "text": "制内市场的核心是国家用制度把市场关进笼子里。"},
    {"chunk_id": "c2", "chapter": 6, "text": "国家能力指国家把意图转成有效治理结果的本事。"},
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

    monkeypatch.setattr(sc, "_invoke_client", _fake)


def _gen(client):  # noqa: ANN001
    return sc.generate_study_cards(
        full_text="x", chunks=_CHUNKS, llm_client=client, model="m"
    )


def _card(order, concept, point, question, chapter, snippet):  # noqa: ANN001
    return {
        "order": order, "concept": concept, "point": point,
        "question": question, "chapter": chapter, "snippet": snippet,
    }


def test_success_returns_verified(monkeypatch):
    final = json.dumps(
        {"cards": [
            _card(1, "制内市场", "国家用制度框住市场", "市场为何受制于国家？", 2,
                  "制内市场的核心是国家用制度把市场关进笼子里"),
        ]},
        ensure_ascii=False,
    )
    _patch(monkeypatch)
    cs = _gen(_FakeClient(final))
    assert cs is not None and len(cs) == 1
    assert cs[0]["verified"] is True
    assert cs[0]["concept"] == "制内市场"
    assert cs[0]["question"]


def test_unverified_dropped(monkeypatch):
    final = json.dumps(
        {"cards": [_card(1, "编的", "x", "q", 3, "书里根本没有的杜撰原文")]},
        ensure_ascii=False,
    )
    _patch(monkeypatch)
    assert _gen(_FakeClient(final)) == []


def test_conceptless_dropped(monkeypatch):
    final = json.dumps(
        {"cards": [{"order": 1, "point": "x", "chapter": 2,
                    "snippet": "制内市场的核心是国家用制度把市场关进笼子里"}]},
        ensure_ascii=False,
    )
    _patch(monkeypatch)
    assert _gen(_FakeClient(final)) == []


def test_chapter_corrected(monkeypatch):
    final = json.dumps(
        {"cards": [
            _card(1, "国家能力", "把意图转成治理结果", "什么是国家能力？", 99,
                  "国家能力指国家把意图转成有效治理结果的本事"),
        ]},
        ensure_ascii=False,
    )
    _patch(monkeypatch)
    cs = _gen(_FakeClient(final))
    assert cs[0]["chapter"] == 6
    assert cs[0]["verified"] is True


def test_empty_returns_empty(monkeypatch):
    _patch(monkeypatch)
    assert _gen(_FakeClient('{"cards": []}')) == []


def test_parse_failure_returns_none(monkeypatch):
    _patch(monkeypatch)
    assert _gen(_FakeClient("不是 JSON")) is None


def test_retry_recovers(monkeypatch):
    good = json.dumps(
        {"cards": [
            _card(1, "制内市场", "国家框住市场", "市场为何受制？", 2,
                  "制内市场的核心是国家用制度把市场关进笼子里"),
        ]},
        ensure_ascii=False,
    )
    _patch(monkeypatch)
    cs = _gen(_FakeClient(["坏 JSON", good]))
    assert cs is not None and len(cs) == 1
