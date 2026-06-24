"""style_issues.generate_style_issues 单测（文体级毛病检测）。

重点验命根子守卫：核验不过的毛病（编的）被丢。+ 成功留 / 空返 [] / 解析失败 None /
type 兜底 / 截断抢救 / 重试。
"""

from __future__ import annotations

import json

from bookscope.agent import style_issues as si

_CHUNKS = [
    {"chunk_id": "c1", "chapter": 1, "text": "他笑了笑，他笑了笑，他又笑了笑，重复的笑充斥全章。"},
    {"chunk_id": "c2", "chapter": 7, "text": "这条支线提到的神秘信使，此后再无交代。"},
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

    monkeypatch.setattr(si, "_invoke_client", _fake)


def _gen(client):  # noqa: ANN001
    return si.generate_style_issues(
        full_text="x", chunks=_CHUNKS, llm_client=client, model="m"
    )


def test_verified_issue_kept(monkeypatch):
    final = json.dumps(
        {"issues": [
            {"type": "repetition", "what": "笑了笑重复", "chapter": 1,
             "snippet": "他笑了笑，他笑了笑，他又笑了笑"},
        ]},
        ensure_ascii=False,
    )
    _patch(monkeypatch)
    issues = _gen(_FakeClient(final))
    assert issues is not None and len(issues) == 1
    assert issues[0]["verified"] is True
    assert issues[0]["type"] == "repetition"


def test_unverified_issue_dropped(monkeypatch):
    # 命根子守卫：snippet 不在原文（编的毛病）→ 丢
    final = json.dumps(
        {"issues": [
            {"type": "pov", "what": "编的视角越界", "chapter": 3,
             "snippet": "这句书里根本没有的杜撰原文"},
        ]},
        ensure_ascii=False,
    )
    _patch(monkeypatch)
    issues = _gen(_FakeClient(final))
    assert issues == []  # 编的被丢光，返空（合法）


def test_mixed_keeps_only_verified(monkeypatch):
    final = json.dumps(
        {"issues": [
            {"type": "repetition", "what": "真", "chapter": 1,
             "snippet": "他笑了笑，他笑了笑，他又笑了笑"},
            {"type": "pov", "what": "编的", "chapter": 3, "snippet": "杜撰不存在的原文"},
        ]},
        ensure_ascii=False,
    )
    _patch(monkeypatch)
    issues = _gen(_FakeClient(final))
    assert len(issues) == 1
    assert issues[0]["what"] == "真"


def test_invalid_type_defaults_repetition(monkeypatch):
    final = json.dumps(
        {"issues": [
            {"type": "乱填的type", "what": "x", "chapter": 1,
             "snippet": "他笑了笑，他笑了笑，他又笑了笑"},
        ]},
        ensure_ascii=False,
    )
    _patch(monkeypatch)
    issues = _gen(_FakeClient(final))
    assert issues[0]["type"] == "repetition"


def test_empty_returns_empty_not_none(monkeypatch):
    _patch(monkeypatch)
    assert _gen(_FakeClient('{"issues": []}')) == []


def test_parse_failure_returns_none(monkeypatch):
    _patch(monkeypatch)
    assert _gen(_FakeClient("不是 JSON")) is None


def test_retry_recovers(monkeypatch):
    good = json.dumps(
        {"issues": [
            {"type": "repetition", "what": "笑了笑重复", "chapter": 1,
             "snippet": "他笑了笑，他笑了笑，他又笑了笑"},
        ]},
        ensure_ascii=False,
    )
    _patch(monkeypatch)
    issues = _gen(_FakeClient(["坏 JSON", good]))
    assert issues is not None and len(issues) == 1
    assert issues[0]["type"] == "repetition"
