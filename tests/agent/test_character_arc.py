"""character_arc.generate_character_arc 单测（WP-character-arc-curves）。

mock LLM（monkeypatch _invoke_client）+ 假 client，覆盖契约：
per 角色逐章戏份/处境 + evidence 校验 / 章号纠偏 / 编的 evidence unverified /
维度钳值 / 编造波动也只是 unverified（命根子：核不过不当确定结论画）/
parse 失败→None / LLM 抛错→None / 截断抢救 / 去代码围栏 / 重试 / 无点角色丢弃。
不跑真 LLM。
"""

from __future__ import annotations

import json

from bookscope.agent import character_arc as ca

_CHUNKS = [
    {"chunk_id": "c1", "chapter": 2,
     "text": "他初入军营，人微言轻，被老兵呼来喝去，夜里独自擦拭那柄祖传的旧刀。"},
    {"chunk_id": "c2", "chapter": 9,
     "text": "捷报传来，他立于城头受将士跪拜，当年那个被呼来喝去的少年，已是三军主帅。"},
    {"chunk_id": "c3", "chapter": 15,
     "text": "兵败如山倒，他负伤退入残破的祠堂，望着满地袍泽尸首，第一次落下泪来。"},
]


class _FakeClient:
    def __init__(self, final_text: str, usage=(150, 40)) -> None:
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
    monkeypatch.setattr(ca, "_invoke_client", _fake)


def test_success_builds_characters_and_verifies(monkeypatch):
    arc_json = json.dumps({
        "characters": [
            {"name": "主角", "points": [
                {"chapter": 2, "presence": 4, "fortune": -3,
                 "evidence": "他初入军营，人微言轻，被老兵呼来喝去"},
                {"chapter": 9, "presence": 10, "fortune": 5,
                 "evidence": "捷报传来，他立于城头受将士跪拜"},
                {"chapter": 15, "presence": 9, "fortune": -5,
                 "evidence": "兵败如山倒，他负伤退入残破的祠堂"},
            ]},
        ],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = ca.generate_character_arc(
        full_text="（整本书……）", chunks=_CHUNKS,
        llm_client=_FakeClient(arc_json), model="deepseek-v4-flash",
    )
    assert r is not None
    assert len(r) == 1
    char = r[0]
    assert char["name"] == "主角"
    pts = char["points"]
    assert [p["chapter"] for p in pts] == [2, 9, 15]  # 按章号排序
    assert pts[0]["presence"] == 4 and pts[0]["fortune"] == -3
    assert pts[0]["verified"] is True  # 命中 c1
    assert pts[0]["chapter"] == 2  # 真章号纠偏
    assert pts[1]["fortune"] == 5 and pts[1]["verified"] is True
    assert pts[2]["fortune"] == -5 and pts[2]["verified"] is True


def test_fabricated_arc_swing_unverified(monkeypatch):
    """命根子：诱导编出的弧线波动，evidence 核不过 → verified=False。

    一个全程平稳角色被编出"巅峰跌谷底"的过山车，但那些 evidence 原文里没有，
    全部 verified=False——前端据此标低置信/淡化，编的波动不当确定结论画。
    """
    arc_json = json.dumps({
        "characters": [
            {"name": "平稳配角", "points": [
                {"chapter": 2, "presence": 3, "fortune": 5,
                 "evidence": "他这章登上人生巅峰风光无两（书里根本没有的杜撰）"},
                {"chapter": 9, "presence": 3, "fortune": -5,
                 "evidence": "他这章跌入谷底众叛亲离（同样是编的）"},
            ]},
        ],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = ca.generate_character_arc(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(arc_json), model="m",
    )
    assert r is not None
    pts = r[0]["points"]
    assert all(p["verified"] is False for p in pts)  # 编的波动全核不过
    assert pts[0]["chapter"] == 2  # 未命中退回模型自报章号


def test_values_clamped(monkeypatch):
    """presence 越界钳到 0-10、fortune 钳到 -5..5；非数退默认 0。"""
    arc_json = json.dumps({
        "characters": [
            {"name": "甲", "points": [
                {"chapter": 1, "presence": 99, "fortune": -42, "evidence": "x"},
                {"chapter": 2, "presence": -3, "fortune": 11, "evidence": "y"},
                {"chapter": 3, "presence": "高", "fortune": None, "evidence": "z"},
            ]},
        ],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = ca.generate_character_arc(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(arc_json), model="m",
    )
    assert r is not None
    pts = r[0]["points"]
    assert pts[0]["presence"] == 10 and pts[0]["fortune"] == -5
    assert pts[1]["presence"] == 0 and pts[1]["fortune"] == 5
    assert pts[2]["presence"] == 0 and pts[2]["fortune"] == 0  # 非数退默认 0


def test_character_without_points_dropped(monkeypatch):
    """points 为空 / 全是坏点的角色丢弃；有有效点的保留。"""
    arc_json = json.dumps({
        "characters": [
            {"name": "无点角色", "points": []},  # 空 points → 丢
            # 无章号 → 点全丢光 → 角色被丢
            {"name": "坏点角色", "points": [{"presence": 5, "fortune": 0}]},
            {"name": "好角色", "points": [
                {"chapter": 2, "presence": 5, "fortune": 1, "evidence": "他初入军营"},
            ]},
        ],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = ca.generate_character_arc(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(arc_json), model="m",
    )
    assert r is not None
    assert [c["name"] for c in r] == ["好角色"]


def test_nameless_character_dropped(monkeypatch):
    """name 缺/空的角色丢弃。"""
    arc_json = json.dumps({
        "characters": [
            {"name": "", "points": [
                {"chapter": 1, "presence": 5, "fortune": 0, "evidence": "x"},
            ]},
            {"name": "乙", "points": [
                {"chapter": 2, "presence": 4, "fortune": 1, "evidence": "他初入军营"},
            ]},
        ],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = ca.generate_character_arc(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(arc_json), model="m",
    )
    assert r is not None
    assert [c["name"] for c in r] == ["乙"]


def test_dup_chapter_point_deduped(monkeypatch):
    """同角色同章号的点去重，保先出现的。"""
    arc_json = json.dumps({
        "characters": [
            {"name": "甲", "points": [
                {"chapter": 2, "presence": 5, "fortune": 1, "evidence": "他初入军营"},
                {"chapter": 2, "presence": 8, "fortune": -2, "evidence": "重复章号"},
            ]},
        ],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = ca.generate_character_arc(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(arc_json), model="m",
    )
    assert r is not None
    pts = r[0]["points"]
    assert len(pts) == 1
    assert pts[0]["presence"] == 5  # 保先出现的


def test_parse_failure_returns_none(monkeypatch):
    _patch_invoke(monkeypatch)
    r = ca.generate_character_arc(
        full_text="x", chunks=_CHUNKS,
        llm_client=_FakeClient("这不是 JSON，随便说点别的"), model="m",
    )
    assert r is None


def test_empty_characters_returns_none(monkeypatch):
    arc_json = json.dumps({"characters": []}, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = ca.generate_character_arc(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(arc_json), model="m",
    )
    assert r is None  # 没角色的弧线没意义


def test_llm_raises_returns_none(monkeypatch):
    _patch_invoke(monkeypatch, raises=RuntimeError("boom"))
    r = ca.generate_character_arc(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient("{}"), model="m",
    )
    assert r is None


def test_strips_code_fence(monkeypatch):
    inner = json.dumps({
        "characters": [
            {"name": "甲", "points": [
                {"chapter": 1, "presence": 5, "fortune": 0, "evidence": "y"},
            ]},
        ],
    }, ensure_ascii=False)
    arc_json = "```json\n" + inner + "\n```"
    _patch_invoke(monkeypatch)
    r = ca.generate_character_arc(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(arc_json), model="m",
    )
    assert r is not None
    assert len(r) == 1


def test_salvages_truncated_json(monkeypatch):
    """reasoning 吃 token 致 JSON 截断 → 抢救已闭合的角色，不整张图丢掉返 None。"""
    truncated = (
        '{"characters": ['
        '{"name": "甲", "points": ['
        '{"chapter": 1, "presence": 3, "fortune": 1, "evidence": "x"}]},'
        '{"name": "乙", "points": ['
        '{"chapter": 2, "presence": 7, "fortune": -2, "evidence": "y"}]},'
        '{"name": "丙", "points": [{"chapter": 3, "presence": 9, "for'  # 截断
    )
    _patch_invoke(monkeypatch)
    r = ca.generate_character_arc(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(truncated), model="m",
    )
    assert r is not None  # 没整张图丢掉
    assert [c["name"] for c in r] == ["甲", "乙"]  # 抢救到 2 个，截断的丙丢弃


def test_retry_on_first_parse_failure(monkeypatch):
    """第一次 parse 失败 → 重试一次，第二次成功。"""
    good = json.dumps({
        "characters": [
            {"name": "甲", "points": [
                {"chapter": 1, "presence": 5, "fortune": 0, "evidence": "y"},
            ]},
        ],
    }, ensure_ascii=False)
    seq = ["这不是 JSON", good]

    class _SeqClient:
        def extract_usage_tokens(self, resp):  # noqa: ANN001
            return (10, 5)

        def extract_final_text(self, resp):  # noqa: ANN001
            return seq.pop(0)

    _patch_invoke(monkeypatch)
    r = ca.generate_character_arc(
        full_text="x", chunks=_CHUNKS, llm_client=_SeqClient(), model="m",
    )
    assert r is not None
    assert len(r) == 1
