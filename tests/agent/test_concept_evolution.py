"""concept_evolution.generate_concept_evolution 单测（跨章概念演进对照）。

重点验设计调整：核验不过的阶段（抽象概念易给的非逐字 snippet）被丢。+ 成功留 /
概念不在书返 [] / 解析失败 None / 章号纠偏 / 截断抢救 / 重试。
"""

from __future__ import annotations

import json

from bookscope.agent import concept_evolution as ce

_CHUNKS = [
    {"chunk_id": "c1", "chapter": 1, "text": "制内市场是国家主导型政治经济的核心机制。"},
    {"chunk_id": "c2", "chapter": 6, "text": "到后期，制内市场深化为国家与市场的制度性嵌套。"},
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

    monkeypatch.setattr(ce, "_invoke_client", _fake)


def _gen(client, concept="制内市场"):  # noqa: ANN001
    return ce.generate_concept_evolution(
        concept=concept, full_text="x", chunks=_CHUNKS, llm_client=client, model="m"
    )


def _st(order, chapter, development, snippet):  # noqa: ANN001
    return {
        "order": order, "chapter": chapter,
        "development": development, "snippet": snippet,
    }


def test_success_returns_verified_stages(monkeypatch):
    final = json.dumps(
        {"stages": [_st(1, 1, "提出核心机制", "制内市场是国家主导型政治经济的核心机制")]},
        ensure_ascii=False,
    )
    _patch(monkeypatch)
    sts = _gen(_FakeClient(final))
    assert sts is not None and len(sts) == 1
    assert sts[0]["verified"] is True
    assert sts[0]["development"] == "提出核心机制"


def test_unverified_stage_dropped(monkeypatch):
    # 设计调整：核验不过的阶段（非逐字 snippet）丢
    final = json.dumps(
        {"stages": [_st(1, 3, "编的演进", "这句书里根本没有的杜撰原文")]},
        ensure_ascii=False,
    )
    _patch(monkeypatch)
    assert _gen(_FakeClient(final)) == []  # 编的丢光，返空（合法）


def test_mixed_keeps_only_verified(monkeypatch):
    final = json.dumps(
        {"stages": [
            _st(1, 1, "真", "制内市场是国家主导型政治经济的核心机制"),
            _st(2, 3, "编的", "杜撰不存在的原文"),
        ]},
        ensure_ascii=False,
    )
    _patch(monkeypatch)
    sts = _gen(_FakeClient(final))
    assert len(sts) == 1
    assert sts[0]["development"] == "真"


def test_chapter_corrected_from_chunk(monkeypatch):
    final = json.dumps(
        {"stages": [_st(1, 99, "深化", "到后期，制内市场深化为国家与市场的制度性嵌套")]},
        ensure_ascii=False,
    )
    _patch(monkeypatch)
    sts = _gen(_FakeClient(final))
    assert sts[0]["chapter"] == 6  # 命中 c2 真章号覆盖 99
    assert sts[0]["verified"] is True


def test_empty_returns_empty_not_none(monkeypatch):
    _patch(monkeypatch)
    assert _gen(_FakeClient('{"stages": []}'), concept="量子纠缠") == []


def test_parse_failure_returns_none(monkeypatch):
    _patch(monkeypatch)
    assert _gen(_FakeClient("不是 JSON")) is None


def test_salvage_truncated(monkeypatch):
    truncated = (
        '{"stages": [{"order": 1, "chapter": 1, "development": "提出", '
        '"snippet": "制内市场是国家主导型政治经济的核心机制"}, {"order": 2, "development": "未闭合'
    )
    _patch(monkeypatch)
    sts = _gen(_FakeClient(truncated))
    assert sts is not None and len(sts) == 1
    assert sts[0]["verified"] is True


def test_retry_recovers(monkeypatch):
    good = json.dumps(
        {"stages": [_st(1, 1, "提出", "制内市场是国家主导型政治经济的核心机制")]},
        ensure_ascii=False,
    )
    _patch(monkeypatch)
    sts = _gen(_FakeClient(["坏 JSON", good]))
    assert sts is not None and len(sts) == 1
