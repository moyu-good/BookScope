"""suggested_questions.generate_book_questions 单测（每书自动出题）。

mock LLM（monkeypatch _invoke_client）+ 假 client，覆盖：
成功解析 / type 归一 / parse 失败→None / LLM 抛错→None / 空→None / 去重。
"""

from __future__ import annotations

import json

from bookscope.agent import suggested_questions as sq


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
    monkeypatch.setattr(sq, "_invoke_client", _fake)


def test_success_parses_questions(monkeypatch):
    payload = json.dumps({"questions": [
        {"type": "伏笔回收", "question": "安禄山起兵的伏笔前几章埋够了吗？"},
        {"type": "人物弧线", "question": "李隆基从明君到失当是渐变还是硬扳？"},
    ]}, ensure_ascii=False)
    _patch(monkeypatch)
    out = sq.generate_book_questions(
        full_text="全书原文", llm_client=_FakeClient(payload), model="m",
    )
    assert out is not None
    assert len(out) == 2
    assert out[0]["type"] == "伏笔回收"
    assert "安禄山" in out[0]["question"]


def test_type_normalized(monkeypatch):
    """模型给的同义 type 归一到五类。"""
    payload = json.dumps({"questions": [
        {"type": "人物动机漂移", "question": "Q1"},
        {"type": "前后矛盾", "question": "Q2"},
        {"type": "莫名其妙的类", "question": "Q3"},
    ]}, ensure_ascii=False)
    _patch(monkeypatch)
    out = sq.generate_book_questions(
        full_text="x", llm_client=_FakeClient(payload), model="m",
    )
    assert out is not None
    assert out[0]["type"] == "人物弧线"
    assert out[1]["type"] == "设定一致性"
    assert out[2]["type"] == "其它"  # 不在表里 → 其它


def test_dedup_questions(monkeypatch):
    payload = json.dumps({"questions": [
        {"type": "伏笔回收", "question": "重复的问题"},
        {"type": "节奏张力", "question": "重复的问题"},
        {"type": "人物关系", "question": "不同的问题"},
    ]}, ensure_ascii=False)
    _patch(monkeypatch)
    out = sq.generate_book_questions(
        full_text="x", llm_client=_FakeClient(payload), model="m",
    )
    assert out is not None
    assert len(out) == 2  # 去重


def test_parse_failure_returns_none(monkeypatch):
    _patch(monkeypatch)
    out = sq.generate_book_questions(
        full_text="x", llm_client=_FakeClient("这不是 JSON"), model="m",
    )
    assert out is None


def test_empty_questions_returns_none(monkeypatch):
    _patch(monkeypatch)
    out = sq.generate_book_questions(
        full_text="x", llm_client=_FakeClient('{"questions": []}'), model="m",
    )
    assert out is None


def test_llm_raise_returns_none(monkeypatch):
    _patch(monkeypatch, raises=RuntimeError("boom"))
    out = sq.generate_book_questions(
        full_text="x", llm_client=_FakeClient("{}"), model="m",
    )
    assert out is None


def test_retries_on_parse_failure(monkeypatch):
    """第一次吐坏 JSON、第二次吐好的 → 重试拿到结果（模型偶发不按 JSON）。"""
    _patch(monkeypatch)  # _invoke_client 返 dummy；extract_final_text 决定内容

    class _FlakyClient:
        def __init__(self) -> None:
            self.calls = 0

        def extract_final_text(self, resp):  # noqa: ANN001
            self.calls += 1
            if self.calls == 1:
                return "这不是 JSON"  # 第一次坏
            return '{"questions": [{"type": "伏笔回收", "question": "Q"}]}'

    client = _FlakyClient()
    out = sq.generate_book_questions(full_text="x", llm_client=client, model="m")
    assert out is not None
    assert client.calls == 2  # 确实重试了
    assert out[0]["question"] == "Q"
