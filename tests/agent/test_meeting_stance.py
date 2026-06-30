"""会议「立场与弦外」meeting_stance 单测(1.7 会议垂直·第四炮)。

合成一份会议逐字稿的 chunk + 整份原文 + mock LLM(假 client + patch invoke_client_cached 返
canned JSON),不跑真 LLM,覆盖:

- **evidence-first 命门**:basis 核不到的 stance/subtext 被丢整条(无据不输出)。
- **纪要退场(A 方案)**:form=纪要 → topics 空 + form_note 有提示(绝不硬编)。
- **封闭集兜底**:position 落不进退「摇摆」、kind 落不进不输出该条。
- **verdict 三态**:有立场张力 / 确证一致无弦外(stances 空但 verdict 本身是答案)/ 读不出。
- **schema 无 verified 字段**:stance/subtext 都不盖鉴印(评估层)。
- 整体形状 + 字段齐 + summary + 一个跑通的形态测试(逐字稿合成数据)。

mock 策略照 test_meeting_spine:patch meeting_stance 自己 import 的 invoke_client_cached
(一次扫全份不分段,不走 run_segments,所以只 patch 这一处)。
"""

from __future__ import annotations

import json

from bookscope.agent import meeting_stance as st

# ── 合成逐字稿:开头白 + 几句带说话人的发言,canned basis 逐字引来命中核验 ──────────
_HEAD = "星图项目 第14次周会 2026年3月3日 参会:PM-A、Eng-B、Eng-C"
# 软反对(嘴上不直接拒绝、强调风险、提替代):Eng-B 对 4月15 发版。
_EV_SOFT_NO = "Eng-B:4月15号太赶了吧,鉴权才刚合,我担心质量,要不往后挪两周更稳?"
# 口头答应没底(「争取」「尽量」留口子):Eng-C 社区运营。
_EV_HOLLOW = "Eng-C:行吧,那我尽量,争取下周挤点时间出个贡献指南初稿,但我手头也满。"
# 真一致同意(纯通报式拍板,无分歧):鉴权方案。
_EV_AGREE = "PM-A:那鉴权就定了,用 token 方案,大家都没意见哈。"

_FULL_TEXT = "\n".join([_HEAD, _EV_AGREE, _EV_SOFT_NO, _EV_HOLLOW])

_CHUNKS = [
    {"chunk_id": "h0", "chapter": 0, "text": _HEAD},
    {"chunk_id": "c1", "chapter": 1, "text": _EV_AGREE},
    {"chunk_id": "c2", "chapter": 2, "text": _EV_SOFT_NO},
    {"chunk_id": "c3", "chapter": 3, "text": _EV_HOLLOW},
]


class _FakeClient:
    def extract_final_text(self, resp):  # noqa: ANN001, ANN201
        return resp if isinstance(resp, str) else "{}"


def _stance_payload() -> str:
    """canned:三个议题——发版(软反对)、社区(口头答应没底)、鉴权(确证一致无弦外)。

    每条 basis 逐字引合成原文来命中核验;鉴权议题 verdict=确证一致无弦外、stances/subtexts 空。
    """
    return json.dumps({
        "topics": [
            {
                "topic": "v2.0 在 4 月 15 号发版",
                "verdict": "有立场张力",
                "stances": [
                    {"person": "Eng-B", "topic": "v2.0 在 4 月 15 号发版",
                     "position": "反对", "reading": "他其实软反对这个时间点,担心质量",
                     "substance": "有条件兑现",
                     "substance_reason": "提了替代方案(往后挪两周)但没硬拒",
                     "basis": [_EV_SOFT_NO], "confidence": "中"},
                ],
                "subtexts": [],
            },
            {
                "topic": "社区运营怎么推",
                "verdict": "有立场张力",
                "stances": [],
                "subtexts": [
                    {"kind": "口头答应没底", "person": "Eng-C", "topic": "社区运营怎么推",
                     "subtext": "嘴上应了但自己也没底,可能落空",
                     "basis": [_EV_HOLLOW], "confidence": "高"},
                ],
            },
            {
                "topic": "鉴权方案",
                "verdict": "确证一致无弦外",
                "stances": [],
                "subtexts": [],
            },
        ],
        "summary": "",
    }, ensure_ascii=False)


def _run(monkeypatch, *, form="逐字稿", canned=None, full_text=None):
    def _fake(_client, *, system="", **_kw):  # noqa: ANN001, ANN002, ANN003, ANN202
        return canned if canned is not None else _stance_payload()
    monkeypatch.setattr(st, "invoke_client_cached", _fake)
    return st.stances_from_meeting(
        chunks=_CHUNKS,
        llm_client=_FakeClient(),
        model="deepseek-v4-flash",
        full_text=full_text if full_text is not None else _FULL_TEXT,
        form=form,
    )


# ── 整体形状(逐字稿主路跑通)────────────────────────────────────────────────
def test_overall_shape(monkeypatch):
    out = _run(monkeypatch)
    assert out["schema_version"] == st.STANCE_SCHEMA_VERSION
    assert out["form"] == "逐字稿"
    assert out["form_note"] == ""  # 逐字稿 form_note 空串
    assert len(out["topics"]) == 3
    for t in out["topics"]:
        for k in ("topic", "verdict", "stances", "subtexts"):
            assert k in t, f"议题缺字段 {k}"
        assert t["verdict"] in st.VERDICTS


def test_stance_fields_complete(monkeypatch):
    out = _run(monkeypatch)
    topic = next(t for t in out["topics"] if t["topic"].startswith("v2.0"))
    s = topic["stances"][0]
    for k in ("person", "topic", "position", "reading", "substance",
              "substance_reason", "basis", "confidence"):
        assert k in s, f"立场缺字段 {k}"
    assert s["position"] in st.STANCE_POSITIONS
    assert s["substance"] in st.MEETING_SUBSTANCE_LEVELS
    assert s["confidence"] in st.CONFIDENCE_LEVELS


def test_subtext_fields_complete(monkeypatch):
    out = _run(monkeypatch)
    topic = next(t for t in out["topics"] if t["topic"].startswith("社区"))
    sub = topic["subtexts"][0]
    for k in ("kind", "person", "topic", "subtext", "basis", "confidence"):
        assert k in sub, f"弦外缺字段 {k}"
    assert sub["kind"] in st.SUBTEXT_KINDS


# ── evidence-first 命门:basis 核不到就丢整条 ────────────────────────────────
def test_stance_with_unverifiable_basis_dropped(monkeypatch):
    """basis 原文里没有 → 整条 stance 丢(无据的推断不输出)。"""
    canned = json.dumps({"topics": [
        {"topic": "发版", "verdict": "有立场张力",
         "stances": [
             {"person": "Eng-B", "topic": "发版", "position": "反对", "reading": "",
              "substance": "有条件兑现", "substance_reason": "",
              "basis": ["Eng-B 说他要辞职(原文根本没这句)"], "confidence": "中"},
         ],
         "subtexts": []},
    ], "summary": ""}, ensure_ascii=False)
    out = _run(monkeypatch, canned=canned)
    topic = out["topics"][0]
    assert topic["stances"] == []  # 核不过被丢
    # 内容全冲掉 + 原本「有立场张力」→ 逐字稿退「确证一致无弦外」
    assert topic["verdict"] == st.VERDICT_CONFIRMED_NONE


def test_subtext_with_unverifiable_basis_dropped(monkeypatch):
    """basis 核不到 → 整条 subtext 丢。"""
    canned = json.dumps({"topics": [
        {"topic": "社区", "verdict": "有立场张力", "stances": [],
         "subtexts": [
             {"kind": "拖延搁置", "person": "Eng-C", "topic": "社区", "subtext": "",
              "basis": ["这句原文里压根没有"], "confidence": "高"},
         ]},
    ], "summary": ""}, ensure_ascii=False)
    out = _run(monkeypatch, canned=canned)
    assert out["topics"][0]["subtexts"] == []


def test_basis_keeps_only_grounded_fragments(monkeypatch):
    """basis 有真有假:只留核得到的片段(剔掉编的),条目本身保留。"""
    canned = json.dumps({"topics": [
        {"topic": "发版", "verdict": "有立场张力",
         "stances": [
             {"person": "Eng-B", "topic": "发版", "position": "反对", "reading": "",
              "substance": "有条件兑现", "substance_reason": "",
              "basis": [_EV_SOFT_NO, "这条是编的原文里没有"], "confidence": "中"},
         ],
         "subtexts": []},
    ], "summary": ""}, ensure_ascii=False)
    out = _run(monkeypatch, canned=canned)
    s = out["topics"][0]["stances"][0]
    assert s["basis"] == [_EV_SOFT_NO]  # 编的那条被剔掉


# ── 纪要退场(A 方案)────────────────────────────────────────────────────────
def test_jiyao_form_退场(monkeypatch):
    """form=纪要 → topics 空 + form_note 有提示(绝不硬编)。"""
    out = _run(monkeypatch, form="纪要")
    assert out["form"] == "纪要"
    assert out["topics"] == []
    assert out["form_note"]  # 非空提示
    assert "逐字稿" in out["form_note"]
    assert out["summary"] == ""


def test_form_none_defaults_to_jiyao_退场(monkeypatch):
    """不传 form → 退「纪要」(更保守)→ 退场(不会误开只有逐字稿能跑的功能)。"""
    out = _run(monkeypatch, form=None)
    assert out["form"] == "纪要"
    assert out["topics"] == []
    assert out["form_note"]


def test_form_unknown_defaults_to_jiyao(monkeypatch):
    """非法 form → 退「纪要」→ 退场。"""
    out = _run(monkeypatch, form="胡说形态")
    assert out["form"] == "纪要"
    assert out["topics"] == []


# ── 封闭集兜底 ───────────────────────────────────────────────────────────────
def test_position_falls_back_to_摇摆(monkeypatch):
    """position 落不进五态 → 退「摇摆」(最中性,不替用户断成支持/反对)。"""
    canned = json.dumps({"topics": [
        {"topic": "发版", "verdict": "有立场张力",
         "stances": [
             {"person": "Eng-B", "topic": "发版", "position": "强烈拥护超级支持",
              "reading": "", "substance": "有条件兑现", "substance_reason": "",
              "basis": [_EV_SOFT_NO], "confidence": "中"},
         ],
         "subtexts": []},
    ], "summary": ""}, ensure_ascii=False)
    out = _run(monkeypatch, canned=canned)
    assert out["topics"][0]["stances"][0]["position"] == "摇摆"


def test_subtext_kind_unknown_dropped(monkeypatch):
    """kind 落不进六类 → 不输出该条(不设兜底类,弦外宁可漏)。"""
    canned = json.dumps({"topics": [
        {"topic": "社区", "verdict": "有立场张力", "stances": [],
         "subtexts": [
             {"kind": "某种说不清的言下之意", "person": "Eng-C", "topic": "社区",
              "subtext": "", "basis": [_EV_HOLLOW], "confidence": "高"},
         ]},
    ], "summary": ""}, ensure_ascii=False)
    out = _run(monkeypatch, canned=canned)
    assert out["topics"][0]["subtexts"] == []


def test_confidence_falls_back_to_low(monkeypatch):
    """confidence 落不进三档 → 退「低」(最保守)。"""
    canned = json.dumps({"topics": [
        {"topic": "发版", "verdict": "有立场张力",
         "stances": [
             {"person": "Eng-B", "topic": "发版", "position": "反对", "reading": "",
              "substance": "有条件兑现", "substance_reason": "",
              "basis": [_EV_SOFT_NO], "confidence": "非常确定"},
         ],
         "subtexts": []},
    ], "summary": ""}, ensure_ascii=False)
    out = _run(monkeypatch, canned=canned)
    assert out["topics"][0]["stances"][0]["confidence"] == "低"


def test_substance_alias_gongwen_to_meeting(monkeypatch):
    """模型吐公文版「空头倡导」→ 归一到会议版「空头表态」(复用 meeting_spine 别名)。"""
    canned = json.dumps({"topics": [
        {"topic": "发版", "verdict": "有立场张力",
         "stances": [
             {"person": "Eng-B", "topic": "发版", "position": "支持", "reading": "",
              "substance": "空头倡导", "substance_reason": "",
              "basis": [_EV_SOFT_NO], "confidence": "中"},
         ],
         "subtexts": []},
    ], "summary": ""}, ensure_ascii=False)
    out = _run(monkeypatch, canned=canned)
    assert out["topics"][0]["stances"][0]["substance"] == "空头表态"


# ── 封闭集纯函数 ─────────────────────────────────────────────────────────────
def test_coerce_position_pure():
    for p in st.STANCE_POSITIONS:
        assert st._coerce_position(p) == p
    assert st._coerce_position("瞎填") == "摇摆"
    assert st._coerce_position(None) == "摇摆"
    assert st._coerce_position("  支持 ") == "支持"


def test_coerce_kind_pure():
    for k in st.SUBTEXT_KINDS:
        assert st._coerce_kind(k) == k
    assert st._coerce_kind("瞎填") is None  # 落不进返 None(丢)
    assert st._coerce_kind(None) is None


def test_coerce_confidence_pure():
    for c in st.CONFIDENCE_LEVELS:
        assert st._coerce_confidence(c) == c
    assert st._coerce_confidence("瞎填") == "低"


# ── verdict 三态 ─────────────────────────────────────────────────────────────
def test_verdict_confirmed_none_kept_with_empty_items(monkeypatch):
    """确证一致无弦外:stances/subtexts 空,但议题保留、verdict 本身是答案。"""
    out = _run(monkeypatch)
    auth = next(t for t in out["topics"] if t["topic"] == "鉴权方案")
    assert auth["verdict"] == st.VERDICT_CONFIRMED_NONE
    assert auth["stances"] == []
    assert auth["subtexts"] == []


def test_verdict_has_tension_when_items_present(monkeypatch):
    """读出了立场/弦外的议题 verdict=有立场张力。"""
    out = _run(monkeypatch)
    ship = next(t for t in out["topics"] if t["topic"].startswith("v2.0"))
    assert ship["verdict"] == st.VERDICT_HAS_TENSION
    assert ship["stances"]


# ── schema 无 verified 字段(评估层、不盖鉴印)──────────────────────────────
def test_no_verified_field_on_stance_or_subtext(monkeypatch):
    """立场/弦外都没有 verified 字段(评估层、绝不盖鉴印,前端标研判)。"""
    out = _run(monkeypatch)
    for t in out["topics"]:
        for s in t["stances"]:
            assert "verified" not in s, "立场不该有 verified(评估层)"
            assert "match_score" not in s
        for sub in t["subtexts"]:
            assert "verified" not in sub, "弦外不该有 verified(评估层)"


# ── summary ──────────────────────────────────────────────────────────────────
def test_summary_built_from_verified_items(monkeypatch):
    """summary 从已核验的立场/弦外拼(带立场),有料就非空。"""
    out = _run(monkeypatch)
    assert out["summary"]  # 高置信度口头答应没底 → 该被点出来
    assert "Eng-C" in out["summary"]


def test_summary_empty_when_no_items(monkeypatch):
    """全是确证一致无弦外(没立场没弦外)→ summary 空串。"""
    canned = json.dumps({"topics": [
        {"topic": "鉴权", "verdict": "确证一致无弦外", "stances": [], "subtexts": []},
        {"topic": "文档", "verdict": "确证一致无弦外", "stances": [], "subtexts": []},
    ], "summary": ""}, ensure_ascii=False)
    out = _run(monkeypatch, canned=canned)
    assert out["summary"] == ""


# ── 异常 / 解析兜底 ──────────────────────────────────────────────────────────
def test_llm_failure_returns_empty(monkeypatch):
    """LLM 调用抛 → 返空结构(不抛、前端优雅退场)。"""
    def _boom(_client, **_kw):  # noqa: ANN001, ANN002, ANN003, ANN202
        raise RuntimeError("provider 挂了")
    monkeypatch.setattr(st, "invoke_client_cached", _boom)
    out = st.stances_from_meeting(
        chunks=_CHUNKS, llm_client=_FakeClient(), model="m",
        full_text=_FULL_TEXT, form="逐字稿",
    )
    assert out["topics"] == []
    assert out["form"] == "逐字稿"


def test_unparseable_returns_empty(monkeypatch):
    """解析不出 JSON → 返空结构。"""
    out = _run(monkeypatch, canned="这不是 JSON 啊随便说点啥")
    assert out["topics"] == []


def test_strips_code_fence(monkeypatch):
    """带 markdown 围栏的 JSON 也解析得出。"""
    fenced = "```json\n" + _stance_payload() + "\n```"
    out = _run(monkeypatch, canned=fenced)
    assert len(out["topics"]) == 3


def test_salvage_on_truncation(monkeypatch):
    """截断的 JSON(少收尾)→ 从 topics 抢救已闭合议题。"""
    full = _stance_payload()
    # 砍掉结尾的 ],"summary":""} 制造截断,但前面议题对象闭合。
    truncated = full[: full.rindex("]")]  # 去掉 topics 收尾及之后
    out = _run(monkeypatch, canned=truncated)
    assert len(out["topics"]) >= 1  # 抢救到至少一个议题


# ── 无原文兜底 ───────────────────────────────────────────────────────────────
def test_empty_text_returns_empty(monkeypatch):
    """没原文(full_text 空 + chunks 也空文本)→ 空结构,不跑 LLM 也不崩。"""
    def _fake(_client, **_kw):  # noqa: ANN001, ANN002, ANN003, ANN202
        raise AssertionError("没原文不该调 LLM")
    monkeypatch.setattr(st, "invoke_client_cached", _fake)
    out = st.stances_from_meeting(
        chunks=[{"chunk_id": "x", "chapter": 0, "text": ""}],
        llm_client=_FakeClient(), model="m", full_text="", form="逐字稿",
    )
    assert out["topics"] == []
    assert out["form"] == "逐字稿"
