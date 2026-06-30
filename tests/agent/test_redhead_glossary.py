"""公文名词解释 redhead_glossary 单测(1.6 三炮 + v2 深度升级:语境含义 + 政策意图)。

合成一份红头文件的 chunk + 整份原文 + mock(假 client + monkeypatch 文脉 / run_segments),
覆盖:

v1 老行为(向后兼容,一字没动):
- 词条结构(term/explanation/evidence/chapter/verified/match_score)齐全;schema 升 v2。
- 难词原句 evidence 核验:命中原文 verified=True 盖鉴印;编的(原文没有)核不过 → evidence 退空。
- 跨段按归一化词面去重(同词只留先出现一条)。
- 文脉读不出东西(头要素全空 + 没条款)→ 直接返空、不跑识别。

v2 新增两层深度字段(本次):
- context_meaning(本文件语境特指义,证据层、可选):模型给了就带出;跟着原句核验态走,
  核不过原句时值仍带出(由 verified=False 标未核验、不盖鉴印),不被清空。
- policy_intent(政策意图,评估层·研判,可选):模型给了就带出;**不进核验、不盖鉴印**——
  哪怕原句核不过,政策意图照样原样带出(它本就是研判、不靠原句撑)。
- 无意图 / 无语境义时不硬编:模型留空 → 输出就是空串(前端据此不渲染),后端绝不替它造。

不跑真 LLM。
"""

from __future__ import annotations

from typing import Any

from bookscope.agent import redhead_glossary as rg

# ── 合成红头文件:三句原文,canned 词条的 evidence 逐字引这几句来命中 ──────────────
_HEAD = "市市场监管局文件 X监发〔2024〕7号 关于深化证照分离改革的通知。"
# 含「证照分离」「负面清单」两个难词的句子。
_C1 = "全面推行证照分离改革,对市场准入实行负面清单管理。"
# 含「放管服」的句子。
_C2 = "深化放管服改革,持续优化营商环境。"

_FULL_TEXT = _HEAD + _C1 + _C2

# 条款序号当单元(chunk 的 chapter 字段=条款序号)。
_CHUNKS = [
    {"chunk_id": "h0", "chapter": 0, "text": _HEAD},
    {"chunk_id": "c1", "chapter": 1, "text": _C1},
    {"chunk_id": "c2", "chapter": 2, "text": _C2},
]


class _FakeClient:
    """duck-typed client;run_segments 被 mock 掉后其实不会真用到它,占位对齐签名。"""

    def extract_final_text(self, resp):  # noqa: ANN001, ANN201
        return resp if isinstance(resp, str) else "{}"


def _patch_spine(monkeypatch, *, head=None, clauses=None):
    """把 get_or_build_doc_spine patch 成返指定文脉(不跑真精读)。

    默认给一条非空条款,让 glossary_from_spine 的"这份读得通"闸放行;测空文脉时传 head=[]、
    clauses=[]。
    """
    spine = {
        "head": head if head is not None else [],
        "clauses": clauses if clauses is not None else [{"chapter": 1, "matter": "x"}],
    }

    def _fake(**_kw):  # noqa: ANN003, ANN202
        return spine

    monkeypatch.setattr(rg, "get_or_build_doc_spine", _fake)


def _patch_segments(monkeypatch, seg_outs: list[list[dict[str, Any]]]):
    """把 run_segments patch 成直接返"每段已解析的词条列表"(绕开真 LLM + 真分段)。

    glossary 走 run_segments 出每段词条,再 _merge_terms 跨段去重、再逐条核验。这里直接喂
    已解析的段结果,聚焦验"合并 + 核验 + 字段组装"这段产品逻辑。
    """

    def _fake(**_kw):  # noqa: ANN003, ANN202
        return seg_outs

    monkeypatch.setattr(rg, "run_segments", _fake)


def _term(
    term: str,
    *,
    explanation: str = "",
    context_meaning: str = "",
    policy_intent: str = "",
    evidence: str = "",
) -> dict[str, Any]:
    """造一条"已过 parse_fn 归一"的词条(run_segments 的产物形态:含 v2 全字段)。"""
    return {
        "term": term,
        "explanation": explanation,
        "context_meaning": context_meaning,
        "policy_intent": policy_intent,
        "evidence": evidence,
    }


def _run(monkeypatch, seg_outs, *, head=None, clauses=None):
    _patch_spine(monkeypatch, head=head, clauses=clauses)
    _patch_segments(monkeypatch, seg_outs)
    return rg.glossary_from_spine(
        chunks=_CHUNKS,
        llm_client=_FakeClient(),
        model="deepseek-v4-flash",
        full_text=_FULL_TEXT,
    )


# ════════════════════════════════════════════════════════════════════════════
# 整体结构 + 字段齐全 + schema 版本
# ════════════════════════════════════════════════════════════════════════════
def test_schema_version_is_v3(monkeypatch):
    out = _run(monkeypatch, [[_term("证照分离", explanation="x", evidence=_C1)]])
    assert out["schema_version"] == rg.GLOSSARY_SCHEMA_VERSION == "v3"


def test_glossary_prompt_catches_policy_jargon():
    """识别 prompt 明确教模型抓政策黑话(五年规划简称/新概念/数字缩略语),
    同时仍守住别挑大白话(通知/会议/单位)。"""
    instr = rg._INSTR_GLOSSARY
    # 抓政策黑话:核心原则 + 三类举例
    assert "政策黑话" in instr
    assert "普通人懂不懂" in instr  # 判据是普通人懂不懂,不是政界用得多不多
    assert "十五五" in instr or "十四五" in instr  # 五年规划简称
    assert "新质生产力" in instr  # 治理经济新概念
    assert "五位一体" in instr or "四个全面" in instr  # 数字缩略语
    # 仍守住别挑大白话
    assert "通知" in instr and "会议" in instr and "单位" in instr
    assert "别挑大白话" in instr or "大白话" in instr


def test_term_has_all_v2_fields(monkeypatch):
    """每条词条带齐 v1 老字段 + v2 新字段(context_meaning / policy_intent)。"""
    seg = [[
        _term(
            "放管服",
            explanation="简政放权、放管结合、优化服务的合称",
            context_meaning="这份文件里指市场监管领域的简政放权措施",
            policy_intent="简政放权的改革方向,政府要退、市场要进",
            evidence=_C2,
        )
    ]]
    out = _run(monkeypatch, seg)
    assert len(out["terms"]) == 1
    t = out["terms"][0]
    for k in (
        "term", "explanation", "context_meaning", "policy_intent",
        "chapter", "evidence", "verified", "match_score",
    ):
        assert k in t, f"词条缺字段 {k}"


# ════════════════════════════════════════════════════════════════════════════
# v1 老行为:原句 evidence 核验(命中盖鉴印 / 编的核不过退空)
# ════════════════════════════════════════════════════════════════════════════
def test_evidence_verified_when_in_original(monkeypatch):
    """canned evidence 逐字命中合成原文 → verified=True、evidence 保留、chapter 落到命中条款。"""
    out = _run(monkeypatch, [[_term("证照分离", explanation="x", evidence=_C1)]])
    t = out["terms"][0]
    assert t["verified"] is True
    assert t["evidence"] == _C1
    assert t["chapter"] == 1  # _C1 在第 1 条款


def test_fabricated_evidence_dropped_to_empty(monkeypatch):
    """编的原句(原文里根本没有)→ 核不过,verified=False、evidence 退空(不留假原句撑场)。"""
    seg = [[
        _term(
            "证照分离",
            explanation="x",
            evidence="本市将向每户企业发放十万元创业补贴(这句原文压根没有)。",
        )
    ]]
    out = _run(monkeypatch, seg)
    t = out["terms"][0]
    assert t["verified"] is False
    assert t["evidence"] == ""  # 核不过退空


# ════════════════════════════════════════════════════════════════════════════
# v2:语境含义(证据层,跟着原句核验态走,但读出的所指不被清空)
# ════════════════════════════════════════════════════════════════════════════
def test_context_meaning_carried_when_verified(monkeypatch):
    """原句核得过 → 语境含义带出。"""
    seg = [[
        _term(
            "负面清单",
            explanation="清单之外都放开的管理方式",
            context_meaning="这份文件里指市场准入的负面清单",
            evidence=_C1,
        )
    ]]
    out = _run(monkeypatch, seg)
    t = out["terms"][0]
    assert t["verified"] is True
    assert t["context_meaning"] == "这份文件里指市场准入的负面清单"


def test_context_meaning_kept_even_when_evidence_unverified(monkeypatch):
    """原句核不过 → evidence 退空、verified=False,但语境含义(读出的所指、非逐字引文)仍带出。

    语境含义是从原文用法读出来的"这词在本文指什么",不是要拿去逐字比对的引文;它跟着原句的
    核验态由前端按未核验呈现(verified=False),值本身不清空——清空它=丢掉这层解读。
    """
    seg = [[
        _term(
            "证照分离",
            explanation="x",
            context_meaning="这份文件里特指企业开办环节的证照分离",
            evidence="原文没有的句子(核不过)。",
        )
    ]]
    out = _run(monkeypatch, seg)
    t = out["terms"][0]
    assert t["verified"] is False
    assert t["evidence"] == ""  # 逐字引文核不过退空
    assert t["context_meaning"] == "这份文件里特指企业开办环节的证照分离"  # 解读仍在


def test_context_meaning_empty_not_fabricated(monkeypatch):
    """模型没给语境含义(读不出更具体所指)→ 输出空串,后端不替它造。"""
    out = _run(monkeypatch, [[_term("证照分离", explanation="x", evidence=_C1)]])
    assert out["terms"][0]["context_meaning"] == ""


# ════════════════════════════════════════════════════════════════════════════
# v2:政策意图(评估层·研判,不进核验、不盖鉴印)
# ════════════════════════════════════════════════════════════════════════════
def test_policy_intent_carried_when_present(monkeypatch):
    """模型给了政策意图 → 原样带出。"""
    seg = [[
        _term(
            "放管服",
            explanation="x",
            policy_intent="简政放权的改革方向,先放开再监管",
            evidence=_C2,
        )
    ]]
    out = _run(monkeypatch, seg)
    assert out["terms"][0]["policy_intent"] == "简政放权的改革方向,先放开再监管"


def test_policy_intent_survives_unverified_evidence(monkeypatch):
    """原句核不过 → evidence 退空,但政策意图(研判、不靠原句撑)照样原样带出、不被清空。"""
    seg = [[
        _term(
            "放管服",
            explanation="x",
            policy_intent="透出继续简政放权、给市场松绑的方向",
            evidence="原文没有的句子(核不过)。",
        )
    ]]
    out = _run(monkeypatch, seg)
    t = out["terms"][0]
    assert t["verified"] is False
    assert t["evidence"] == ""
    # 政策意图是评估层,不盖鉴印、不进核验——原句核不过它照样在
    assert t["policy_intent"] == "透出继续简政放权、给市场松绑的方向"


def test_policy_intent_empty_not_fabricated(monkeypatch):
    """模型没给政策意图(中性名词没政策指向)→ 输出空串,后端不替它编一个方向。"""
    seg = [[
        _term("负面清单", explanation="清单之外都放开", evidence=_C1)
    ]]
    out = _run(monkeypatch, seg)
    assert out["terms"][0]["policy_intent"] == ""


def test_mixed_some_with_intent_some_without(monkeypatch):
    """一份里有的词有政策意图、有的没有 → 各自如实:有的带出、没的留空,不互相污染。"""
    seg = [[
        _term(
            "放管服", explanation="x",
            policy_intent="简政放权方向", evidence=_C2,
        ),
        _term(
            "通知", explanation="一种公文文种",  # 中性词,无政策意图
            evidence=_HEAD,
        ),
    ]]
    out = _run(monkeypatch, seg)
    by_term = {t["term"]: t for t in out["terms"]}
    assert by_term["放管服"]["policy_intent"] == "简政放权方向"
    assert by_term["通知"]["policy_intent"] == ""


# ════════════════════════════════════════════════════════════════════════════
# 跨段去重 + 空文脉退场
# ════════════════════════════════════════════════════════════════════════════
def test_cross_segment_dedup_keeps_first(monkeypatch):
    """同一个词跨段重复 → 只留先出现那条(它的字段)。"""
    seg_outs = [
        [_term("证照分离", explanation="先出现的释义", evidence=_C1)],
        [_term("证照分离", explanation="后出现的释义(该被丢)", evidence=_C1)],
    ]
    out = _run(monkeypatch, seg_outs)
    terms = [t for t in out["terms"] if t["term"] == "证照分离"]
    assert len(terms) == 1
    assert terms[0]["explanation"] == "先出现的释义"


def test_empty_spine_returns_empty_without_segments(monkeypatch):
    """文脉头要素全空 + 没条款 → 直接返空、不跑识别(run_segments 被调就炸,证明没调)。"""
    def _boom(**_kw):  # noqa: ANN003, ANN202
        raise AssertionError("空文脉不该跑 run_segments")

    _patch_spine(monkeypatch, head=[], clauses=[])
    monkeypatch.setattr(rg, "run_segments", _boom)
    out = rg.glossary_from_spine(
        chunks=_CHUNKS, llm_client=_FakeClient(),
        model="deepseek-v4-flash", full_text=_FULL_TEXT,
    )
    assert out["schema_version"] == "v3"
    assert out["terms"] == []


def test_no_terms_found_returns_empty(monkeypatch):
    """文脉读得通但每段都没挑到难词 → terms 空。"""
    out = _run(monkeypatch, [[], []])
    assert out["terms"] == []


# ════════════════════════════════════════════════════════════════════════════
# 纯件:_coerce_term v2 字段
# ════════════════════════════════════════════════════════════════════════════
def test_coerce_term_carries_v2_fields():
    t = rg._coerce_term({
        "term": "放管服",
        "explanation": "  释义  ",
        "context_meaning": "  本文件指…  ",
        "policy_intent": "  改革方向  ",
        "evidence": "  原句  ",
    })
    assert t is not None
    assert t["explanation"] == "释义"  # strip
    assert t["context_meaning"] == "本文件指…"
    assert t["policy_intent"] == "改革方向"


def test_coerce_term_v2_fields_default_empty():
    """缺 context_meaning / policy_intent(v1 老数据形态)→ 退空串,向后兼容。"""
    t = rg._coerce_term({"term": "证照分离", "explanation": "x", "evidence": "y"})
    assert t is not None
    assert t["context_meaning"] == ""
    assert t["policy_intent"] == ""


def test_coerce_term_drops_blank_term():
    """term 空 → 丢(没词面没法当词条)。"""
    assert rg._coerce_term({"term": "  ", "explanation": "x"}) is None
    assert rg._coerce_term("不是 dict") is None
