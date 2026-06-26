"""argument_structure.generate_argument_structure 单测（论点结构梳理）。

mock _invoke_client + 假 client，覆盖：成功返论点 + 核验 / 解析失败 None / 空 None /
截断抢救 / 章号纠偏 / 重试。
"""

from __future__ import annotations

import json

from bookscope.agent import argument_structure as ar

_CHUNKS = [
    {"chunk_id": "c1", "chapter": 1, "text": "制内市场是国家主导型政治经济的核心机制。"},
    {"chunk_id": "c2", "chapter": 4, "text": "政府通过制度安排把市场嵌入国家治理框架。"},
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

    monkeypatch.setattr(ar, "_invoke_client", _fake)


def _gen(client):  # noqa: ANN001
    return ar.generate_argument_structure(
        full_text="x", chunks=_CHUNKS, llm_client=client, model="m"
    )


def _cl(order, claim, chapter, evidence):  # noqa: ANN001
    return {"order": order, "claim": claim, "chapter": chapter, "evidence": evidence}


def test_success_returns_verified_claims(monkeypatch):
    final = json.dumps(
        {"claims": [_cl(1, "制内市场是核心机制", 1, "制内市场是国家主导型政治经济的核心机制")]},
        ensure_ascii=False,
    )
    _patch(monkeypatch)
    cls = _gen(_FakeClient(final))
    assert cls is not None and len(cls) == 1
    assert cls[0]["verified"] is True
    assert cls[0]["claim"] == "制内市场是核心机制"


def test_parse_failure_returns_none(monkeypatch):
    _patch(monkeypatch)
    assert _gen(_FakeClient("不是 JSON")) is None


def test_empty_claims_returns_none(monkeypatch):
    _patch(monkeypatch)
    assert _gen(_FakeClient('{"claims": []}')) is None


def test_fiction_genre_gates_out_without_calling_llm(monkeypatch):
    # 叙事题材：直接返 [] 优雅退场，绝不调 LLM（_invoke_client 被调到就炸）。
    def _boom(*_a, **_k):
        raise AssertionError("LLM 不该被调用——叙事题材应在门控处退场")

    monkeypatch.setattr(ar, "_invoke_client", _boom)
    out = ar.generate_argument_structure(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient("x"), model="m",
        genre="fiction",
    )
    assert out == []  # [] 区别于失败的 None


def test_theory_genre_runs_normally(monkeypatch):
    final = json.dumps(
        {"claims": [_cl(1, "制内市场是核心机制", 1, "制内市场是国家主导型政治经济的核心机制")]},
        ensure_ascii=False,
    )
    _patch(monkeypatch)
    out = ar.generate_argument_structure(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(final), model="m",
        genre="theory",
    )
    assert out is not None and len(out) == 1


def test_genre_none_runs_as_before(monkeypatch):
    # 向后兼容：端点没传 genre（None）时照旧跑，不被门控挡掉。
    final = json.dumps(
        {"claims": [_cl(1, "制内市场是核心机制", 1, "制内市场是国家主导型政治经济的核心机制")]},
        ensure_ascii=False,
    )
    _patch(monkeypatch)
    assert _gen(_FakeClient(final)) is not None


def test_is_argument_genre_predicate():
    assert ar.is_argument_genre("theory") is True
    assert ar.is_argument_genre(None) is True
    assert ar.is_argument_genre("fiction") is False
    assert ar.is_argument_genre("") is False


def test_llm_raises_returns_none(monkeypatch):
    _patch(monkeypatch, raises=RuntimeError("boom"))
    assert _gen(_FakeClient("{}")) is None


def test_chapter_corrected_from_chunk(monkeypatch):
    final = json.dumps(
        {"claims": [_cl(1, "市场嵌入治理", 99, "政府通过制度安排把市场嵌入国家治理框架")]},
        ensure_ascii=False,
    )
    _patch(monkeypatch)
    cls = _gen(_FakeClient(final))
    assert cls[0]["chapter"] == 4  # 命中 c2 真章号覆盖 99
    assert cls[0]["verified"] is True


def test_salvage_truncated(monkeypatch):
    truncated = (
        '{"claims": [{"order": 1, "claim": "制内市场是核心机制", "chapter": 1, '
        '"evidence": "制内市场是国家主导型政治经济的核心机制"}, {"order": 2, "claim": "未闭合'
    )
    _patch(monkeypatch)
    cls = _gen(_FakeClient(truncated))
    assert cls is not None and len(cls) == 1
    assert cls[0]["verified"] is True


def test_retry_recovers_on_second_attempt(monkeypatch):
    good = json.dumps(
        {"claims": [_cl(1, "核心机制", 1, "制内市场是国家主导型政治经济的核心机制")]},
        ensure_ascii=False,
    )
    _patch(monkeypatch)
    cls = _gen(_FakeClient(["坏 JSON", good]))
    assert cls is not None and len(cls) == 1
