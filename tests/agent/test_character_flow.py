"""character_flow.generate_character_flow 单测（WP-character-narrative-flow）。

mock LLM（monkeypatch _invoke_client）+ 假 client，覆盖契约：
逐章拼图 + 同场对证据校验 / 章号纠偏 / 编的同场对 unverified / parse 失败→None /
LLM 抛错→None / 截断抢救 / present 端点补全 / 去代码围栏 / 重试。
不跑真 LLM。
"""

from __future__ import annotations

import json

from bookscope.agent import character_flow as cf

_CHUNKS = [
    {"chunk_id": "c1", "chapter": 3,
     "text": "玄德同关羽、张飞来到庄前。玄德下马，亲叩柴门。孔明昼寝未起，玄德拱立阶下。"},
    {"chunk_id": "c2", "chapter": 7,
     "text": "操执玄德手，同入小亭，已设樽俎。二人对坐，开怀畅饮。"},
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
    monkeypatch.setattr(cf, "_invoke_client", _fake)


def test_success_builds_chapters_and_verifies_pairs(monkeypatch):
    flow_json = json.dumps({
        "chapters": [
            {
                "chapter": 3,
                "present": ["刘备", "关羽", "张飞", "诸葛亮"],
                "pairs": [
                    {"a": "刘备", "b": "诸葛亮",
                     "evidence": "孔明昼寝未起，玄德拱立阶下"},
                ],
            },
            {
                "chapter": 7,
                "present": ["曹操", "刘备"],
                "pairs": [
                    {"a": "曹操", "b": "刘备",
                     "evidence": "操执玄德手，同入小亭"},
                ],
            },
        ],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = cf.generate_character_flow(
        full_text="（整本书……）", chunks=_CHUNKS,
        llm_client=_FakeClient(flow_json), model="deepseek-v4-flash",
    )
    assert r is not None
    assert [c["chapter"] for c in r] == [3, 7]  # 按章号排序
    # 第 3 章同场对命中 c1 → verified + 真章号 3
    pair0 = r[0]["pairs"][0]
    assert pair0["verified"] is True
    assert pair0["chapter"] == 3
    # 第 7 章同场对命中 c2 → verified + 真章号 7
    pair1 = r[1]["pairs"][0]
    assert pair1["verified"] is True
    assert pair1["chapter"] == 7


def test_fabricated_pair_evidence_unverified(monkeypatch):
    """编的同场对（原文里没有）→ verified=False，章号退回模型自报。"""
    flow_json = json.dumps({
        "chapters": [
            {
                "chapter": 5,
                "present": ["甲", "乙"],
                "pairs": [
                    {"a": "甲", "b": "乙",
                     "evidence": "书里根本没有的杜撰句子拿来测假阳性同场对"},
                ],
            },
        ],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = cf.generate_character_flow(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(flow_json), model="m",
    )
    assert r is not None
    pair = r[0]["pairs"][0]
    assert pair["verified"] is False  # 没命中
    assert pair["chapter"] == 5  # 未命中退回模型自报章号


def test_parse_failure_returns_none(monkeypatch):
    _patch_invoke(monkeypatch)
    r = cf.generate_character_flow(
        full_text="x", chunks=_CHUNKS,
        llm_client=_FakeClient("这不是 JSON，随便说点别的"), model="m",
    )
    assert r is None


def test_empty_chapters_returns_none(monkeypatch):
    flow_json = json.dumps({"chapters": []}, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = cf.generate_character_flow(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(flow_json), model="m",
    )
    assert r is None  # 没章节的流图没意义


def test_llm_raises_returns_none(monkeypatch):
    _patch_invoke(monkeypatch, raises=RuntimeError("boom"))
    r = cf.generate_character_flow(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient("{}"), model="m",
    )
    assert r is None


def test_pair_endpoint_added_to_present(monkeypatch):
    """同场对引用了 present 没列的人物 → 补进 present（模型偶尔漏列）。"""
    flow_json = json.dumps({
        "chapters": [
            {
                "chapter": 1,
                "present": ["甲"],
                "pairs": [{"a": "甲", "b": "丙", "evidence": "x"}],
            },
        ],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = cf.generate_character_flow(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(flow_json), model="m",
    )
    assert r is not None
    assert "丙" in r[0]["present"]


def test_self_pair_dropped(monkeypatch):
    """a == b 的自配对丢弃；正常对保留。"""
    flow_json = json.dumps({
        "chapters": [
            {
                "chapter": 2,
                "present": ["甲", "乙"],
                "pairs": [
                    {"a": "甲", "b": "甲", "evidence": "x"},  # 自配对 → 丢
                    {"a": "甲", "b": "乙", "evidence": "y"},
                ],
            },
        ],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = cf.generate_character_flow(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(flow_json), model="m",
    )
    assert r is not None
    assert len(r[0]["pairs"]) == 1
    assert r[0]["pairs"][0]["b"] == "乙"


def test_chapter_without_pairs_kept(monkeypatch):
    """章节只有 present、无同场对（独角戏章）也保留。"""
    flow_json = json.dumps({
        "chapters": [
            {"chapter": 4, "present": ["甲"], "pairs": []},
        ],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = cf.generate_character_flow(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(flow_json), model="m",
    )
    assert r is not None
    assert len(r) == 1
    assert r[0]["pairs"] == []
    assert r[0]["present"] == ["甲"]


def test_strips_code_fence(monkeypatch):
    inner = json.dumps({
        "chapters": [
            {"chapter": 1, "present": ["甲", "乙"],
             "pairs": [{"a": "甲", "b": "乙", "evidence": "y"}]},
        ],
    }, ensure_ascii=False)
    flow_json = "```json\n" + inner + "\n```"
    _patch_invoke(monkeypatch)
    r = cf.generate_character_flow(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(flow_json), model="m",
    )
    assert r is not None
    assert len(r) == 1


def test_salvages_truncated_json(monkeypatch):
    """reasoning 吃 token 致 JSON 截断 → 抢救已闭合的章节，不整张图丢掉返 None。"""
    truncated = (
        '{"chapters": ['
        '{"chapter": 1, "present": ["甲", "乙"], '
        '"pairs": [{"a": "甲", "b": "乙", "evidence": "x"}]},'
        '{"chapter": 2, "present": ["丙", "丁"], '
        '"pairs": [{"a": "丙", "b": "丁", "evidence": "y"}]},'
        '{"chapter": 3, "present": ["戊"], "pai'  # 这章被截断
    )
    _patch_invoke(monkeypatch)
    r = cf.generate_character_flow(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(truncated), model="m",
    )
    assert r is not None  # 没整张图丢掉
    assert [c["chapter"] for c in r] == [1, 2]  # 抢救到 2 章，截断的第 3 章丢弃


def test_non_integer_chapter_dropped(monkeypatch):
    """chapter 非整数的条目丢弃；整数的保留。"""
    flow_json = json.dumps({
        "chapters": [
            {"chapter": "三", "present": ["甲"], "pairs": []},  # 章号非整数 → 丢
            {"chapter": 2, "present": ["乙", "丙"],
             "pairs": [{"a": "乙", "b": "丙", "evidence": "z"}]},
        ],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = cf.generate_character_flow(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(flow_json), model="m",
    )
    assert r is not None
    assert [c["chapter"] for c in r] == [2]


def test_retry_on_first_parse_failure(monkeypatch):
    """第一次 parse 失败 → 重试一次，第二次成功。"""
    good = json.dumps({
        "chapters": [
            {"chapter": 1, "present": ["甲", "乙"],
             "pairs": [{"a": "甲", "b": "乙", "evidence": "y"}]},
        ],
    }, ensure_ascii=False)
    seq = ["这不是 JSON", good]

    class _SeqClient:
        def extract_usage_tokens(self, resp):  # noqa: ANN001
            return (10, 5)

        def extract_final_text(self, resp):  # noqa: ANN001
            return seq.pop(0)

    _patch_invoke(monkeypatch)
    r = cf.generate_character_flow(
        full_text="x", chunks=_CHUNKS, llm_client=_SeqClient(), model="m",
    )
    assert r is not None
    assert len(r) == 1
