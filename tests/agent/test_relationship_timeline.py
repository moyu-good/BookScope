"""relationship_timeline.generate_relationship_timeline 单测（WP-relationship-over-time）。

mock LLM（monkeypatch _invoke_client）+ 假 client，覆盖契约：
逐对关系 + 逐章强度 + 转折 evidence 校验 / 章号纠偏 / 编的 evidence unverified /
强度钳值 / 同对去重 / 空内容关系丢 / parse 失败→None / LLM 抛错→None /
截断抢救 / 去代码围栏 / 重试。不跑真 LLM。
"""

from __future__ import annotations

import json

from bookscope.agent import relationship_timeline as rt

_CHUNKS = [
    {"chunk_id": "c1", "chapter": 3,
     "text": "刘备三顾茅庐，终于在草庐中见到诸葛亮，二人促膝长谈，相见恨晚。"},
    {"chunk_id": "c2", "chapter": 9,
     "text": "白帝城中，刘备病重，托孤于诸葛亮，泣曰：君才十倍曹丕，必能安国。"},
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
    monkeypatch.setattr(rt, "_invoke_client", _fake)


def test_success_builds_relations_and_verifies(monkeypatch):
    payload = json.dumps({
        "relations": [
            {
                "a": "刘备", "b": "诸葛亮", "relation": "君臣",
                "points": [
                    {"chapter": 3, "strength": 6},
                    {"chapter": 9, "strength": 10},
                ],
                "turning_points": [
                    {"chapter": 3, "change": "三顾茅庐初识",
                     "evidence": "刘备三顾茅庐，终于在草庐中见到诸葛亮，二人促膝长谈，相见恨晚"},
                    {"chapter": 9, "change": "白帝城托孤，信任到顶",
                     "evidence": "白帝城中，刘备病重，托孤于诸葛亮"},
                ],
            },
        ],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = rt.generate_relationship_timeline(
        full_text="（整本书……）", chunks=_CHUNKS,
        llm_client=_FakeClient(payload), model="deepseek-v4-flash",
    )
    assert r is not None
    assert len(r) == 1
    rel = r[0]
    assert rel["a"] == "刘备" and rel["b"] == "诸葛亮"
    assert rel["relation"] == "君臣"
    assert [p["chapter"] for p in rel["points"]] == [3, 9]
    assert rel["points"][1]["strength"] == 10
    tps = rel["turning_points"]
    assert len(tps) == 2
    assert tps[0]["verified"] is True  # 命中 c1
    assert tps[0]["chapter"] == 3  # 真章号纠偏
    assert tps[1]["verified"] is True  # 命中 c2
    assert tps[1]["chapter"] == 9


def test_fabricated_turning_point_unverified(monkeypatch):
    """编的转折 evidence（原文里没有）→ verified=False，章号退回模型自报。"""
    payload = json.dumps({
        "relations": [
            {
                "a": "甲", "b": "乙", "relation": "政敌",
                "points": [{"chapter": 5, "strength": 4}],
                "turning_points": [
                    {"chapter": 5, "change": "诱导编出的决裂",
                     "evidence": "书里根本没有的杜撰句子拿来测假阳性"},
                ],
            },
        ],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = rt.generate_relationship_timeline(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(payload), model="m",
    )
    assert r is not None
    tp = r[0]["turning_points"][0]
    assert tp["verified"] is False  # 没命中
    assert tp["chapter"] == 5  # 未命中退回模型自报章号


def test_strength_clamped(monkeypatch):
    """strength 越界钳到 0-10；非数退默认 0。"""
    payload = json.dumps({
        "relations": [
            {
                "a": "甲", "b": "乙", "relation": "同盟",
                "points": [
                    {"chapter": 1, "strength": 99},
                    {"chapter": 2, "strength": -3},
                    {"chapter": 3, "strength": "强"},
                ],
                "turning_points": [],
            },
        ],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = rt.generate_relationship_timeline(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(payload), model="m",
    )
    assert r is not None
    pts = r[0]["points"]
    assert pts[0]["strength"] == 10
    assert pts[1]["strength"] == 0
    assert pts[2]["strength"] == 0  # 非数退默认


def test_stable_relation_keeps_empty_turning_points(monkeypatch):
    """关系全程平稳（turning_points 空）但有 points → 保留，转折空列表（命根子：不编转折）。"""
    payload = json.dumps({
        "relations": [
            {
                "a": "甲", "b": "乙", "relation": "邻里",
                "points": [{"chapter": 1, "strength": 3}, {"chapter": 5, "strength": 3}],
                "turning_points": [],
            },
        ],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = rt.generate_relationship_timeline(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(payload), model="m",
    )
    assert r is not None
    assert r[0]["turning_points"] == []
    assert len(r[0]["points"]) == 2


def test_empty_relation_dropped(monkeypatch):
    """points 和 turning_points 全空的关系 → 丢（画不出东西、没核验锚点）。"""
    payload = json.dumps({
        "relations": [
            {"a": "甲", "b": "乙", "relation": "x", "points": [], "turning_points": []},
            {"a": "丙", "b": "丁", "relation": "y",
             "points": [{"chapter": 2, "strength": 5}], "turning_points": []},
        ],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = rt.generate_relationship_timeline(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(payload), model="m",
    )
    assert r is not None
    assert len(r) == 1
    assert {r[0]["a"], r[0]["b"]} == {"丙", "丁"}


def test_same_pair_deduped(monkeypatch):
    """同一对关系（无向）重复出现 → 去重，只留第一条。"""
    payload = json.dumps({
        "relations": [
            {"a": "甲", "b": "乙", "relation": "君臣",
             "points": [{"chapter": 1, "strength": 5}], "turning_points": []},
            {"a": "乙", "b": "甲", "relation": "重复",
             "points": [{"chapter": 2, "strength": 8}], "turning_points": []},
        ],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = rt.generate_relationship_timeline(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(payload), model="m",
    )
    assert r is not None
    assert len(r) == 1
    assert r[0]["relation"] == "君臣"  # 留第一条


def test_self_pair_dropped(monkeypatch):
    """a == b 的"关系" → 丢。"""
    payload = json.dumps({
        "relations": [
            {"a": "甲", "b": "甲", "relation": "x",
             "points": [{"chapter": 1, "strength": 5}], "turning_points": []},
        ],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = rt.generate_relationship_timeline(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(payload), model="m",
    )
    assert r is None  # 唯一的关系被丢 → 空 relations → None


def test_points_sorted_and_deduped(monkeypatch):
    """points 同章号去重、乱序排回升序。"""
    payload = json.dumps({
        "relations": [
            {
                "a": "甲", "b": "乙", "relation": "x",
                "points": [
                    {"chapter": 5, "strength": 7},
                    {"chapter": 2, "strength": 3},
                    {"chapter": 5, "strength": 9},  # 同章号 → 丢
                ],
                "turning_points": [],
            },
        ],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = rt.generate_relationship_timeline(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(payload), model="m",
    )
    assert r is not None
    assert [p["chapter"] for p in r[0]["points"]] == [2, 5]
    assert r[0]["points"][1]["strength"] == 7  # 留第一个章号 5


def test_parse_failure_returns_none(monkeypatch):
    _patch_invoke(monkeypatch)
    r = rt.generate_relationship_timeline(
        full_text="x", chunks=_CHUNKS,
        llm_client=_FakeClient("这不是 JSON，随便说点别的"), model="m",
    )
    assert r is None


def test_empty_relations_returns_none(monkeypatch):
    payload = json.dumps({"relations": []}, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = rt.generate_relationship_timeline(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(payload), model="m",
    )
    assert r is None  # 没关系的时间轴没意义


def test_llm_raises_returns_none(monkeypatch):
    _patch_invoke(monkeypatch, raises=RuntimeError("boom"))
    r = rt.generate_relationship_timeline(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient("{}"), model="m",
    )
    assert r is None


def test_strips_code_fence(monkeypatch):
    inner = json.dumps({
        "relations": [
            {"a": "甲", "b": "乙", "relation": "x",
             "points": [{"chapter": 1, "strength": 5}], "turning_points": []},
        ],
    }, ensure_ascii=False)
    payload = "```json\n" + inner + "\n```"
    _patch_invoke(monkeypatch)
    r = rt.generate_relationship_timeline(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(payload), model="m",
    )
    assert r is not None
    assert len(r) == 1


def test_salvages_truncated_json(monkeypatch):
    """reasoning 吃 token 致 JSON 截断 → 抢救已闭合的关系，不整张时间轴丢掉返 None。"""
    truncated = (
        '{"relations": ['
        '{"a": "甲", "b": "乙", "relation": "x", '
        '"points": [{"chapter": 1, "strength": 5}], "turning_points": []},'
        '{"a": "丙", "b": "丁", "relation": "y", '
        '"points": [{"chapter": 2, "strength": 8}], "turning_points": []},'
        '{"a": "戊", "b": "己", "relation": "z", "poi'  # 截断
    )
    _patch_invoke(monkeypatch)
    r = rt.generate_relationship_timeline(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(truncated), model="m",
    )
    assert r is not None  # 没整张时间轴丢掉
    pairs = [{rel["a"], rel["b"]} for rel in r]
    assert {"甲", "乙"} in pairs
    assert {"丙", "丁"} in pairs
    assert {"戊", "己"} not in pairs  # 截断的丢弃


def test_retry_on_first_parse_failure(monkeypatch):
    """第一次 parse 失败 → 重试一次，第二次成功。"""
    good = json.dumps({
        "relations": [
            {"a": "甲", "b": "乙", "relation": "x",
             "points": [{"chapter": 1, "strength": 5}], "turning_points": []},
        ],
    }, ensure_ascii=False)
    seq = ["这不是 JSON", good]

    class _SeqClient:
        def extract_usage_tokens(self, resp):  # noqa: ANN001
            return (10, 5)

        def extract_final_text(self, resp):  # noqa: ANN001
            return seq.pop(0)

    _patch_invoke(monkeypatch)
    r = rt.generate_relationship_timeline(
        full_text="x", chunks=_CHUNKS, llm_client=_SeqClient(), model="m",
    )
    assert r is not None
    assert len(r) == 1
