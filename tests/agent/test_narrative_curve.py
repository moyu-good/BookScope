"""narrative_curve.generate_narrative_curve 单测（WP-multidim-narrative-curve）。

mock LLM（monkeypatch _invoke_client）+ 假 client，覆盖契约：
逐章多维 + evidence 校验 / 章号纠偏 / 编的 evidence unverified / 维度钳值 /
parse 失败→None / LLM 抛错→None / 截断抢救 / 去代码围栏 / 重试。
不跑真 LLM。
"""

from __future__ import annotations

import json

from bookscope.agent import narrative_curve as nc

_CHUNKS = [
    {"chunk_id": "c1", "chapter": 3,
     "text": "捷报传来，城头欢声雷动。守将登楼，见敌军溃退、旌旗倒卷，不禁仰天大笑。"},
    {"chunk_id": "c2", "chapter": 7,
     "text": "孤城终于陷落。老兵拄着断枪立在残垣上，望着满地袍泽的尸首，泪流满面。"},
]


class _FakeClient:
    def __init__(self, final_text: str, usage=(120, 30)) -> None:
        self._final = final_text
        self._usage = usage

    def extract_usage_tokens(self, resp):  # noqa: ANN001
        return self._usage

    def extract_final_text(self, resp):  # noqa: ANN001
        return self._final


def _patch_invoke(monkeypatch, *, raises: Exception | None = None):
    def _fake(*_a, **_k):
        if raises is not None:
            raise raises
        return {"usage": {}}
    monkeypatch.setattr(nc, "_invoke_client", _fake)


def test_success_builds_chapters_and_verifies(monkeypatch):
    curve_json = json.dumps({
        "chapters": [
            {"chapter": 3, "tension": 9, "sentiment": 4, "pov": "守将",
             "mainline": True, "evidence": "守将登楼，见敌军溃退、旌旗倒卷，不禁仰天大笑"},
            {"chapter": 7, "tension": 8, "sentiment": -5, "pov": "老兵",
             "mainline": True, "evidence": "老兵拄着断枪立在残垣上，望着满地袍泽的尸首，泪流满面"},
        ],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = nc.generate_narrative_curve(
        full_text="（整本书……）", chunks=_CHUNKS,
        llm_client=_FakeClient(curve_json), model="deepseek-v4-flash",
    )
    assert r is not None
    assert [c["chapter"] for c in r] == [3, 7]  # 按章号排序
    c0 = r[0]
    assert c0["tension"] == 9
    assert c0["sentiment"] == 4
    assert c0["pov"] == "守将"
    assert c0["mainline"] is True
    assert c0["verified"] is True  # 命中 c1
    assert c0["chapter"] == 3  # 真章号纠偏
    c1 = r[1]
    assert c1["sentiment"] == -5
    assert c1["verified"] is True
    assert c1["chapter"] == 7


def test_fabricated_evidence_unverified(monkeypatch):
    """编的 evidence（原文里没有）→ verified=False，章号退回模型自报。"""
    curve_json = json.dumps({
        "chapters": [
            {"chapter": 5, "tension": 6, "sentiment": 0, "pov": "甲",
             "mainline": False, "evidence": "书里根本没有的杜撰句子拿来测假阳性"},
        ],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = nc.generate_narrative_curve(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(curve_json), model="m",
    )
    assert r is not None
    assert r[0]["verified"] is False  # 没命中
    assert r[0]["chapter"] == 5  # 未命中退回模型自报章号


def test_dimension_values_clamped(monkeypatch):
    """tension 越界钳到 0-10、sentiment 钳到 -5..5；非数退默认。"""
    curve_json = json.dumps({
        "chapters": [
            {"chapter": 1, "tension": 99, "sentiment": -42, "pov": "甲",
             "mainline": True, "evidence": "x"},
            {"chapter": 2, "tension": -3, "sentiment": 11, "pov": "乙",
             "mainline": True, "evidence": "y"},
            {"chapter": 3, "tension": "高", "sentiment": None, "pov": "丙",
             "mainline": True, "evidence": "z"},
        ],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = nc.generate_narrative_curve(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(curve_json), model="m",
    )
    assert r is not None
    assert r[0]["tension"] == 10 and r[0]["sentiment"] == -5
    assert r[1]["tension"] == 0 and r[1]["sentiment"] == 5
    assert r[2]["tension"] == 0 and r[2]["sentiment"] == 0  # 非数退默认 0


def test_missing_pov_defaults_to_qunxiang(monkeypatch):
    """pov 缺/空 → 退"群像"；mainline 非 bool → 退 True。"""
    curve_json = json.dumps({
        "chapters": [
            {"chapter": 1, "tension": 3, "sentiment": 0, "pov": "",
             "mainline": "是", "evidence": "x"},
        ],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = nc.generate_narrative_curve(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(curve_json), model="m",
    )
    assert r is not None
    assert r[0]["pov"] == "群像"
    assert r[0]["mainline"] is True


def test_parse_failure_returns_none(monkeypatch):
    _patch_invoke(monkeypatch)
    r = nc.generate_narrative_curve(
        full_text="x", chunks=_CHUNKS,
        llm_client=_FakeClient("这不是 JSON，随便说点别的"), model="m",
    )
    assert r is None


def test_empty_chapters_returns_none(monkeypatch):
    curve_json = json.dumps({"chapters": []}, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = nc.generate_narrative_curve(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(curve_json), model="m",
    )
    assert r is None  # 没章节的曲线没意义


def test_llm_raises_returns_none(monkeypatch):
    _patch_invoke(monkeypatch, raises=RuntimeError("boom"))
    r = nc.generate_narrative_curve(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient("{}"), model="m",
    )
    assert r is None


def test_non_integer_chapter_dropped(monkeypatch):
    """chapter 非整数的条目丢弃；整数的保留。"""
    curve_json = json.dumps({
        "chapters": [
            {"chapter": "三", "tension": 5, "sentiment": 0, "pov": "甲",
             "mainline": True, "evidence": "x"},  # 章号非整数 → 丢
            {"chapter": 2, "tension": 4, "sentiment": 1, "pov": "乙",
             "mainline": True, "evidence": "z"},
        ],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = nc.generate_narrative_curve(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(curve_json), model="m",
    )
    assert r is not None
    assert [c["chapter"] for c in r] == [2]


def test_strips_code_fence(monkeypatch):
    inner = json.dumps({
        "chapters": [
            {"chapter": 1, "tension": 5, "sentiment": 0, "pov": "甲",
             "mainline": True, "evidence": "y"},
        ],
    }, ensure_ascii=False)
    curve_json = "```json\n" + inner + "\n```"
    _patch_invoke(monkeypatch)
    r = nc.generate_narrative_curve(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(curve_json), model="m",
    )
    assert r is not None
    assert len(r) == 1


def test_salvages_truncated_json(monkeypatch):
    """reasoning 吃 token 致 JSON 截断 → 抢救已闭合的章节，不整张曲线丢掉返 None。"""
    truncated = (
        '{"chapters": ['
        '{"chapter": 1, "tension": 3, "sentiment": 1, "pov": "甲", '
        '"mainline": true, "evidence": "x"},'
        '{"chapter": 2, "tension": 7, "sentiment": -2, "pov": "乙", '
        '"mainline": false, "evidence": "y"},'
        '{"chapter": 3, "tension": 9, "sentiment": 4, "pov": "丙", "evi'  # 截断
    )
    _patch_invoke(monkeypatch)
    r = nc.generate_narrative_curve(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(truncated), model="m",
    )
    assert r is not None  # 没整张曲线丢掉
    assert [c["chapter"] for c in r] == [1, 2]  # 抢救到 2 章，截断的第 3 章丢弃


def test_retry_on_first_parse_failure(monkeypatch):
    """第一次 parse 失败 → 重试一次，第二次成功。"""
    good = json.dumps({
        "chapters": [
            {"chapter": 1, "tension": 5, "sentiment": 0, "pov": "甲",
             "mainline": True, "evidence": "y"},
        ],
    }, ensure_ascii=False)
    seq = ["这不是 JSON", good]

    class _SeqClient:
        def extract_usage_tokens(self, resp):  # noqa: ANN001
            return (10, 5)

        def extract_final_text(self, resp):  # noqa: ANN001
            return seq.pop(0)

    _patch_invoke(monkeypatch)
    r = nc.generate_narrative_curve(
        full_text="x", chunks=_CHUNKS, llm_client=_SeqClient(), model="m",
    )
    assert r is not None
    assert len(r) == 1
