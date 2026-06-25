"""chapter_spine_foreshadow.foreshadow_from_spine 单测(病二·证据张冠李戴修复)。

mock invoke_client_cached + 假 client,覆盖新契约:
传 chunks → 两端 evidence 按 description 在埋点/回收章原文现捞(不挂章代表句)+
verify_citations 标 verified;埋点章捞不到 → 空 + setup_verified=False;
回收章捞不到 → 空 + payoff_verified=False(弧仍 resolved,由章号配对定);
chunks=None → 退回老行为(章代表句、不带 verified 字段);
无埋点 → None;LLM 抛错 → None。不跑真 LLM。
"""

from __future__ import annotations

import json

from bookscope.agent import chapter_spine_foreshadow as csf

# 章脉:逐章「埋」标 + 章代表句 evidence(章脉每章只留一条,是"这章最显眼那件事")。
# 注意第 2 章的章代表句是"老仆打翻了油灯"——跟断剑伏笔无关,正是病二会误挂的那种章代表句。
_SPINE = [
    {
        "chapter": 2,
        "evidence": "深夜里老仆打翻了油灯,惊起满院的狗吠。",  # 这章最显眼但与伏笔无关的代表句
        "foreshadow": [{"type": "埋", "hook": "墙角断剑认主"}],
        "events": [{"event": "少年初到老宅"}],
    },
    {
        "chapter": 9,
        "evidence": "城破之夜火光冲天,百姓四散奔逃。",  # 同样无关的章代表句
        "foreshadow": [],
        "events": [{"event": "少年拔断剑认主,挑落贼首"}, {"event": "城破"}],
    },
]

# 原文:每章既有"无关的显眼事"(对应章代表句)、又有真讲断剑伏笔的句子。
# 现捞要挑出真讲伏笔的那句,不是章代表句对应的无关句。
_CHUNKS = [
    {
        "chunk_id": "c2a", "chapter": 2,
        "text": "深夜里老仆打翻了油灯,惊起满院的狗吠。",
    },
    {
        "chunk_id": "c2b", "chapter": 2,
        "text": "墙角那柄断剑落满灰尘,老仆叮嘱少年莫要去碰,说它认主、伤过人。",
    },
    {
        "chunk_id": "c9a", "chapter": 9,
        "text": "城破之夜火光冲天,百姓四散奔逃。",
    },
    {
        "chunk_id": "c9b", "chapter": 9,
        "text": "少年拔起墙角那柄断剑,剑身嗡鸣认主,一剑挑落贼首。",
    },
]


class _FakeClient:
    """假 LLM client:只需提供 extract_final_text 返回预置 JSON。"""

    def __init__(self, final_text: str) -> None:
        self._final = final_text

    def extract_final_text(self, resp):  # noqa: ANN001
        return resp if isinstance(resp, str) else self._final


def _patch(monkeypatch, text: str, *, raises: Exception | None = None):
    """monkeypatch invoke_client_cached → 直接吐预置文本(或抛错),不碰真 LLM / 缓存。"""

    def _fake(*_a, **_k):
        if raises is not None:
            raise raises
        return text

    monkeypatch.setattr(csf, "invoke_client_cached", _fake)


def _run(payload: str, *, spine=None, chunks=None, **kw):
    return csf.foreshadow_from_spine(
        spine=spine if spine is not None else _SPINE,
        chunks=chunks,
        llm_client=_FakeClient(""),
        model="deepseek-v4-flash",
        **kw,
    )


def test_evidence_picks_real_foreshadow_sentence_not_chapter_rep(monkeypatch):
    """传 chunks:两端 evidence 现捞真讲这条伏笔的句子,不是章代表句的无关显眼事。"""
    payload = json.dumps(
        {
            "arcs": [
                {
                    "description": "墙角断剑认主,后来成了少年挑落贼首的兵器",
                    "setup_chapter": 2,
                    "payoff_chapter": 9,
                }
            ]
        },
        ensure_ascii=False,
    )
    _patch(monkeypatch, payload)
    r = _run(payload, chunks=_CHUNKS)
    assert r is not None and len(r) == 1
    arc = r[0]
    assert arc["status"] == "resolved"
    # 埋点 evidence 必须是真讲断剑伏笔那句,不是"老仆打翻油灯"那条章代表句
    assert "断剑" in arc["setup_evidence"] and "认主" in arc["setup_evidence"]
    assert "油灯" not in arc["setup_evidence"]  # 没挂章代表句的无关显眼事
    # 回收 evidence 必须是真讲回收那句,不是"城破之夜火光冲天"那条章代表句
    assert "断剑" in arc["payoff_evidence"] and "挑落贼首" in arc["payoff_evidence"]
    assert "火光冲天" not in arc["payoff_evidence"]
    assert arc["setup_verified"] is True
    assert arc["payoff_verified"] is True


def test_setup_not_in_chapter_text_unverified(monkeypatch):
    """埋点章原文里捞不到讲这条伏笔的句子 → setup_evidence 空 + setup_verified=False(不硬塞)。"""
    spine = [
        {
            "chapter": 2,
            "evidence": "深夜里老仆打翻了油灯,惊起满院的狗吠。",
            "foreshadow": [{"type": "埋", "hook": "一枚刻字玉佩"}],
            "events": [{"event": "少年初到老宅"}],
        },
        {
            "chapter": 9,
            "evidence": "城破之夜火光冲天。",
            "foreshadow": [],
            "events": [{"event": "玉佩认出少年身世"}],
        },
    ]
    # 第 2 章原文里压根没提玉佩——这条伏笔的 description 在埋点章捞不到支撑句。
    chunks = [
        {"chunk_id": "x2", "chapter": 2, "text": "深夜里老仆打翻了油灯,惊起满院的狗吠。"},
        {"chunk_id": "x9", "chapter": 9, "text": "城破之夜,那枚刻字玉佩认出了少年的身世。"},
    ]
    payload = json.dumps(
        {
            "arcs": [
                {
                    "description": "一枚刻字玉佩道破少年身世",
                    "setup_chapter": 2,
                    "payoff_chapter": 9,
                }
            ]
        },
        ensure_ascii=False,
    )
    _patch(monkeypatch, payload)
    arc = _run(payload, spine=spine, chunks=chunks)[0]
    assert arc["setup_evidence"] == ""  # 埋点章没这条伏笔的支撑句,空着不硬塞
    assert arc["setup_verified"] is False
    # 回收章原文里有玉佩,这端捞得到、核得过
    assert "玉佩" in arc["payoff_evidence"]
    assert arc["payoff_verified"] is True


def test_payoff_not_in_chapter_text_unverified(monkeypatch):
    """回收章原文里捞不到回收支撑句 → payoff_evidence 空 + payoff_verified=False。

    弧仍 resolved(resolved 由 LLM 章号配对定,evidence 现捞是另一层守卫)。
    """
    spine = [
        {
            "chapter": 2,
            "evidence": "墙角断剑落灰。",
            "foreshadow": [{"type": "埋", "hook": "墙角断剑认主"}],
            "events": [{"event": "少年初到老宅"}],
        },
        {
            "chapter": 9,
            "evidence": "城破。",
            "foreshadow": [],
            "events": [{"event": "断剑认主挑贼首"}],
        },
    ]
    # 第 9 章原文里完全没讲断剑回收(只讲了别的)——回收端捞不到。
    chunks = [
        {"chunk_id": "x2", "chapter": 2, "text": "墙角那柄断剑落满灰尘,老仆说它认主。"},
        {"chunk_id": "x9", "chapter": 9, "text": "城破之夜,百姓扶老携幼四散奔逃出城。"},
    ]
    payload = json.dumps(
        {
            "arcs": [
                {
                    "description": "墙角断剑认主成兵器",
                    "setup_chapter": 2,
                    "payoff_chapter": 9,
                }
            ]
        },
        ensure_ascii=False,
    )
    _patch(monkeypatch, payload)
    arc = _run(payload, spine=spine, chunks=chunks)[0]
    assert arc["status"] == "resolved"  # 章号配对仍判 resolved
    assert "断剑" in arc["setup_evidence"]  # 埋点端捞得到
    assert arc["setup_verified"] is True
    assert arc["payoff_evidence"] == ""  # 回收端原文没支撑句,空
    assert arc["payoff_verified"] is False


def test_dangling_arc_payoff_empty(monkeypatch):
    """断弧(payoff_chapter=null):payoff 端不现捞、留空、payoff_verified=False。"""
    payload = json.dumps(
        {
            "arcs": [
                {
                    "description": "墙角断剑认主,挖了坑没填",
                    "setup_chapter": 2,
                    "payoff_chapter": None,
                }
            ]
        },
        ensure_ascii=False,
    )
    _patch(monkeypatch, payload)
    arc = _run(payload, chunks=_CHUNKS)[0]
    assert arc["status"] == "dangling"
    assert arc["payoff_chapter"] is None
    assert "断剑" in arc["setup_evidence"]  # 埋点端仍现捞
    assert arc["setup_verified"] is True
    assert arc["payoff_evidence"] == ""
    assert arc["payoff_verified"] is False


def test_chunks_none_keeps_old_chapter_rep_behavior(monkeypatch):
    """chunks=None(端点接线前):退回老行为——两端取章代表句,且不带 verified 字段。"""
    payload = json.dumps(
        {
            "arcs": [
                {
                    "description": "墙角断剑认主成兵器",
                    "setup_chapter": 2,
                    "payoff_chapter": 9,
                }
            ]
        },
        ensure_ascii=False,
    )
    _patch(monkeypatch, payload)
    arc = _run(payload, chunks=None)[0]  # 不传 chunks
    # 老行为:setup/payoff evidence 是章脉那章的章代表句
    assert arc["setup_evidence"] == "深夜里老仆打翻了油灯,惊起满院的狗吠。"
    assert arc["payoff_evidence"] == "城破之夜火光冲天,百姓四散奔逃。"
    # 老行为不产出 verified 字段(向后兼容,端点接线前不崩)
    assert "setup_verified" not in arc
    assert "payoff_verified" not in arc


def test_no_setup_returns_none(monkeypatch):
    """章脉里没有任何「埋」标 → None(非叙事书/纯论述)。"""
    spine = [{"chapter": 1, "evidence": "纯论述,无伏笔。", "foreshadow": [], "events": []}]
    _patch(monkeypatch, "{}")
    assert _run("{}", spine=spine, chunks=_CHUNKS) is None


def test_llm_raises_returns_none(monkeypatch):
    """配对调用抛错 → None(端点照走不 break)。"""
    _patch(monkeypatch, "{}", raises=RuntimeError("boom"))
    assert _run("{}", chunks=_CHUNKS) is None


def test_parse_failure_returns_none(monkeypatch):
    """LLM 吐的不是 JSON → 解析不出弧 → None。"""
    _patch(monkeypatch, "这不是 JSON,随便说点别的")
    assert _run("x", chunks=_CHUNKS) is None
