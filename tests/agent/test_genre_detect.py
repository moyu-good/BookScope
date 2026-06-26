"""genre_detect.detect_genre 单测（题材检测）。

mock _invoke_client + 假 client，覆盖：命中封闭集 / 多嘴带标点也能抠出 / 不在集退其他 /
解析失败退其他 / LLM 抛异常退其他 / 重试 / theory 轴映射 / is_theory_genre 判定。
"""

from __future__ import annotations

from bookscope.agent import genre_detect as gd


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

    monkeypatch.setattr(gd, "_invoke_client", _fake)


def _detect(client):  # noqa: ANN001
    return gd.detect_genre(
        title="制内市场",
        toc_titles=["第一章 导论", "第二章 机制"],
        sample_text="制内市场是国家主导型政治经济的核心机制。",
        llm_client=client,
        model="m",
    )


def test_clean_genre_word(monkeypatch):
    _patch(monkeypatch)
    assert _detect(_FakeClient("理论")) == "理论"


def test_genre_with_punctuation_and_quotes(monkeypatch):
    # 模型多嘴带标点 / 引号，仍能抠出封闭集词。
    _patch(monkeypatch)
    assert _detect(_FakeClient("“小说”。")) == "小说"


def test_genre_embedded_in_sentence(monkeypatch):
    # 模型解释了一通，文本里含封闭集词也能命中第一个。
    _patch(monkeypatch)
    assert _detect(_FakeClient("我认为这是一本历史类的书")) == "历史"


def test_out_of_set_falls_back_to_other(monkeypatch):
    # 模型回了个不在封闭集的词 → 退其他（两次都不在集就认）。
    _patch(monkeypatch)
    assert _detect(_FakeClient("散文")) == gd.FALLBACK_GENRE


def test_empty_reply_falls_back(monkeypatch):
    _patch(monkeypatch)
    assert _detect(_FakeClient("")) == gd.FALLBACK_GENRE


def test_llm_raises_falls_back(monkeypatch):
    _patch(monkeypatch, raises=RuntimeError("boom"))
    assert _detect(_FakeClient("理论")) == gd.FALLBACK_GENRE


def test_retry_recovers_on_second_attempt(monkeypatch):
    # 首次解析退兜底（不在集），第二次给好词 → 返好词。
    _patch(monkeypatch)
    assert _detect(_FakeClient(["散文", "诗歌"])) == "诗歌"


def test_all_closed_set_words_pass_through(monkeypatch):
    _patch(monkeypatch)
    for g in gd.GENRES:
        assert _detect(_FakeClient(g)) == g


def test_genre_to_argument_axis():
    assert gd.genre_to_argument_axis("理论") == "theory"
    assert gd.genre_to_argument_axis("论文") == "theory"
    assert gd.genre_to_argument_axis("小说") == "fiction"
    assert gd.genre_to_argument_axis("历史") == "fiction"
    assert gd.genre_to_argument_axis("公文") == "fiction"
    assert gd.genre_to_argument_axis("其他") == "fiction"
    assert gd.genre_to_argument_axis(None) is None


def test_is_theory_genre():
    assert gd.is_theory_genre("理论") is True
    assert gd.is_theory_genre("论文") is True
    assert gd.is_theory_genre("小说") is False
    assert gd.is_theory_genre(None) is True


def test_no_toc_no_sample_still_runs(monkeypatch):
    # 目录 / 原文都空时只靠书名也得能跑出结果（不抛）。
    _patch(monkeypatch)
    out = gd.detect_genre(
        title="某本书", toc_titles=[], sample_text="",
        llm_client=_FakeClient("其他"), model="m",
    )
    assert out == "其他"
