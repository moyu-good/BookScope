"""claim_support.check_claim_support 单测（claim precision，exp-015）。

mock judge（monkeypatch _invoke_client）+ 假 client，覆盖：
supported / weak / 逐字跳过 / judge 抛错→unchecked / 空 snippet→unchecked /
关键词兜底解析 / 混合（逐字 + 转述）。
"""

from __future__ import annotations

from bookscope.agent import claim_support as cs


class _FakeClient:
    def __init__(self, final_text: str) -> None:
        self._final = final_text

    def extract_final_text(self, resp):  # noqa: ANN001
        return self._final


def _patch(monkeypatch, *, raises: Exception | None = None):
    def _fake(*_a, **_k):
        if raises is not None:
            raise raises
        return {}  # dummy resp；extract_final_text 返 _FakeClient._final
    monkeypatch.setattr(cs, "_invoke_client", _fake)


def test_supported_verdict(monkeypatch):
    _patch(monkeypatch)
    cits = [{"snippet": "原文片段", "match_type": "paraphrase"}]
    out = cs.check_claim_support(
        "某论断", cits, llm_client=_FakeClient('{"verdict": "supported"}'), model="m",
    )
    assert out[0]["claim_support"] == "supported"


def test_weak_verdict(monkeypatch):
    _patch(monkeypatch)
    cits = [{"snippet": "原文片段", "match_type": "paraphrase"}]
    out = cs.check_claim_support(
        "某论断", cits, llm_client=_FakeClient('{"verdict": "weak"}'), model="m",
    )
    assert out[0]["claim_support"] == "weak"


def test_quote_skipped_marked_supported(monkeypatch):
    """逐字引用天然 supported——不调 judge（client.extract_final_text 抛错也不影响）。"""
    _patch(monkeypatch)

    class _RaisingClient:
        def extract_final_text(self, resp):  # noqa: ANN001
            raise AssertionError("judge 不该对逐字引用调用")

    cits = [{"snippet": "逐字原文", "match_type": "quote"}]
    out = cs.check_claim_support(
        "某论断", cits, llm_client=_RaisingClient(), model="m",
    )
    assert out[0]["claim_support"] == "supported"


def test_judge_error_marked_unchecked(monkeypatch):
    _patch(monkeypatch, raises=RuntimeError("boom"))
    cits = [{"snippet": "原文片段", "match_type": "paraphrase"}]
    out = cs.check_claim_support(
        "某论断", cits, llm_client=_FakeClient("x"), model="m",
    )
    assert out[0]["claim_support"] == "unchecked"


def test_empty_snippet_unchecked(monkeypatch):
    _patch(monkeypatch)
    cits = [{"snippet": "", "match_type": "paraphrase"}]
    out = cs.check_claim_support(
        "某论断", cits, llm_client=_FakeClient('{"verdict": "supported"}'), model="m",
    )
    assert out[0]["claim_support"] == "unchecked"


def test_keyword_fallback_parse(monkeypatch):
    """judge 没吐干净 JSON 时关键词兜底。"""
    _patch(monkeypatch)
    cits = [{"snippet": "原文片段", "match_type": "none"}]
    out = cs.check_claim_support(
        "某论断", cits, llm_client=_FakeClient("我判断这条是 weak，因为没建立因果"), model="m",
    )
    assert out[0]["claim_support"] == "weak"


def test_mixed_quote_and_paraphrase(monkeypatch):
    _patch(monkeypatch)
    cits = [
        {"snippet": "逐字", "match_type": "quote"},
        {"snippet": "转述", "match_type": "paraphrase"},
    ]
    out = cs.check_claim_support(
        "某论断", cits, llm_client=_FakeClient('{"verdict": "weak"}'), model="m",
    )
    assert out[0]["claim_support"] == "supported"  # 逐字跳过
    assert out[1]["claim_support"] == "weak"  # 转述被核
