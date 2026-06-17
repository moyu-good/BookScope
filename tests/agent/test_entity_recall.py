"""entity_recall.generate_entity_recall 单测（实体回溯快查）。

mock _invoke_client + 假 client，覆盖契约：成功返出现 + 原文核验 / 实体不在书里返
``[]``（命根子，不是 None）/ 解析失败返 None / 截断抢救 / 章号纠偏 / 无 snippet 丢 / 重试。
"""

from __future__ import annotations

import json

from bookscope.agent import entity_recall as er

_CHUNKS = [
    {"chunk_id": "c1", "chapter": 1, "text": "安禄山身兼范阳平卢河东三镇节度使，势力极大。"},
    {"chunk_id": "c2", "chapter": 3, "text": "他以奉唐玄宗密诏讨伐杨国忠为借口在范阳起兵。"},
]


class _FakeClient:
    """extract_final_text 按次回下一条（单条 str 或多条 list 测重试）。"""

    def __init__(self, finals) -> None:  # noqa: ANN001
        self._texts = [finals] if isinstance(finals, str) else list(finals)
        self._i = 0

    def extract_final_text(self, resp):  # noqa: ANN001
        t = self._texts[min(self._i, len(self._texts) - 1)]
        self._i += 1
        return t


def _patch_invoke(monkeypatch, *, raises: Exception | None = None) -> None:
    def _fake(*_a, **_k):
        if raises is not None:
            raise raises
        return {"usage": {}}

    monkeypatch.setattr(er, "_invoke_client", _fake)


def _gen(client, entity="安禄山"):  # noqa: ANN001
    return er.generate_entity_recall(
        entity=entity, full_text="x", chunks=_CHUNKS, llm_client=client, model="m"
    )


def _ap(order, chapter, what, snippet):  # noqa: ANN001
    return {"order": order, "chapter": chapter, "what": what, "snippet": snippet}


def test_success_returns_verified_appearances(monkeypatch):
    final = json.dumps(
        {"appearances": [_ap(1, 1, "登场", "安禄山身兼范阳平卢河东三镇节度使")]},
        ensure_ascii=False,
    )
    _patch_invoke(monkeypatch)
    aps = _gen(_FakeClient(final))
    assert aps is not None and len(aps) == 1
    assert aps[0]["verified"] is True
    assert aps[0]["what"] == "登场"


def test_entity_not_in_book_returns_empty_not_none(monkeypatch):
    # 命根子：不存在的实体 → 模型返回 appearances:[] → 返 [] (合法)，不是 None
    _patch_invoke(monkeypatch)
    aps = _gen(_FakeClient('{"appearances": []}'), entity="朱元璋")
    assert aps == []


def test_parse_failure_returns_none(monkeypatch):
    _patch_invoke(monkeypatch)
    assert _gen(_FakeClient("这不是 JSON，随便说点别的")) is None


def test_llm_raises_returns_none(monkeypatch):
    _patch_invoke(monkeypatch, raises=RuntimeError("boom"))
    assert _gen(_FakeClient("{}")) is None


def test_chapter_corrected_from_chunk(monkeypatch):
    # 模型自报章号 99，snippet 逐字命中 c2（真章号 3）→ 用真章号覆盖
    final = json.dumps(
        {"appearances": [
            _ap(1, 99, "起兵", "他以奉唐玄宗密诏讨伐杨国忠为借口在范阳起兵"),
        ]},
        ensure_ascii=False,
    )
    _patch_invoke(monkeypatch)
    aps = _gen(_FakeClient(final))
    assert aps[0]["chapter"] == 3
    assert aps[0]["verified"] is True


def test_drops_snippetless_appearance(monkeypatch):
    final = json.dumps(
        {"appearances": [
            {"order": 1, "chapter": 1, "what": "无证据"},  # 缺 snippet → 丢
            _ap(2, 1, "有证据", "安禄山身兼范阳平卢河东三镇节度使"),
        ]},
        ensure_ascii=False,
    )
    _patch_invoke(monkeypatch)
    aps = _gen(_FakeClient(final))
    assert len(aps) == 1
    assert aps[0]["what"] == "有证据"


def test_salvage_truncated(monkeypatch):
    # 截断 JSON（数组没收尾）→ 抢救出已闭合的完整对象
    truncated = (
        '{"appearances": [{"order": 1, "chapter": 1, "what": "登场", '
        '"snippet": "安禄山身兼范阳平卢河东三镇节度使"}, {"order": 2, "what": "未闭合'
    )
    _patch_invoke(monkeypatch)
    aps = _gen(_FakeClient(truncated))
    assert aps is not None and len(aps) == 1
    assert aps[0]["verified"] is True


def test_retry_recovers_on_second_attempt(monkeypatch):
    good = json.dumps(
        {"appearances": [_ap(1, 1, "登场", "安禄山身兼范阳平卢河东三镇节度使")]},
        ensure_ascii=False,
    )
    _patch_invoke(monkeypatch)
    aps = _gen(_FakeClient(["坏 JSON", good]))  # 第一次坏、第二次好
    assert aps is not None and len(aps) == 1
