"""公文「利害与风向」研判 redhead_stakes 单测(1.6.1)。

合成一份红头文件的 chunk + 整份原文 + mock LLM(假 client + monkeypatch invoke_client_cached
返 canned JSON),覆盖:

- 三段结构(机会/风险/信号)+ 字段齐全;含金量/时效/置信度落封闭集,落不进有兜底。
- 机会/风险 evidence 核验:命中原文 verified=True;编的(原文没有)被丢。
- 机会/风险按 substance 排序(真金白银在前)。
- 信号不过 verified(评估层);无 basis / basis 编的(核不到原文)被丢。
- recommendation 非空(给了带立场的建议)。
- 空 role 退场返空,不跑 LLM。

不跑真 LLM。
"""

from __future__ import annotations

import json

from bookscope.agent import redhead_stakes as rs

# 合成红头文件:三句原文,后面 canned evidence 逐字引这几句来命中(避免长行重复内联也读得清)。
_HEAD = "市市场监管局文件 X监发〔2024〕7号 关于优化个体工商户营商环境的通知。"
# 真金白银句:硬约束词 + 数字 + 时限 + 主体。
_HARD = "各区市场监管局应当于2024年9月30日前为新登记个体工商户减免登记费每户200元。"
# 空头句:鼓励/探索/条件成熟时逐步,无数字无时限无主体。
_HOLLOW = "鼓励各地探索更便利的个体工商户登记方式,条件成熟时逐步推广。"
# 罚则句:有问责 + 责任主体。
_PENALTY = "对未按期完成减免的区局,由市局予以通报问责。"

_FULL_TEXT = _HEAD + _HARD + _HOLLOW + _PENALTY

# 条款序号当单元(chunk 的 chapter 字段=条款序号)。
_CHUNKS = [
    {"chunk_id": "h0", "chapter": 0, "text": _HEAD},
    {"chunk_id": "c1", "chapter": 1, "text": _HARD},
    {"chunk_id": "c2", "chapter": 2, "text": _HOLLOW},
    {"chunk_id": "c3", "chapter": 3, "text": _PENALTY},
]


class _FakeClient:
    def extract_final_text(self, resp):  # noqa: ANN001, ANN201
        return resp if isinstance(resp, str) else "{}"


def _patch(monkeypatch, canned: str):
    """单次调用:把 invoke_client_cached patch 成返同一段 canned JSON(不跑真 LLM)。"""
    def _fake(*_a, **_kw):  # noqa: ANN002, ANN003, ANN202
        return canned
    monkeypatch.setattr(rs, "invoke_client_cached", _fake)


def _run(monkeypatch, canned: str, *, role: str = "个体工商户"):
    _patch(monkeypatch, canned)
    return rs.stakes_from_doc(
        chunks=_CHUNKS,
        role=role,
        llm_client=_FakeClient(),
        model="deepseek-v4-flash",
        full_text=_FULL_TEXT,
    )


def _full_payload() -> str:
    """一份齐全的四段研判:相关条款两条、机会两条(一真金白银一空头)、风险一条、信号一条。

    机会顺序故意把空头放前面、真金白银放后面——用来验排序确实把真金白银提前。
    相关条款故意把相关度「中」放前、「高」放后——用来验排序把「高」提前。
    """
    return json.dumps({
        "related_clauses": [
            {
                "chapter": 2, "matter": "便利登记", "relevance": "中",
                "bearing": "利好", "note": "你将来办登记可能更方便", "evidence": _HOLLOW,
            },
            {
                "chapter": 1, "matter": "登记费减免", "relevance": "高",
                "bearing": "利好", "note": "你新登记能省200元", "evidence": _HARD,
            },
        ],
        "opportunities": [
            {
                "what": "探索更便利登记方式",
                "why": "你将来办登记可能更省事",
                "action": "关注本地试点动态",
                "substance": "空头倡导",
                "substance_reason": "原文用「鼓励…探索…条件成熟时逐步」,无数字无时限无主体",
                "horizon": "无期",
                "evidence": _HOLLOW,
            },
            {
                "what": "登记费减免每户200元",
                "why": "你新登记能省200元",
                "action": "9月30日前去办新登记享减免",
                "substance": "真金白银",
                "substance_reason": "原文「应当…9月30日前…减免每户200元」有硬约束+数字+时限+主体",
                "horizon": "近",
                "evidence": _HARD,
            },
        ],
        "risks": [
            {
                "what": "区局未按期减免会被问责",
                "cost": "若你所在区局拖办,你的减免可能延误",
                "substance": "真金白银",
                "substance_reason": "原文「未按期…由市局予以通报问责」有罚则+责任主体",
                "horizon": "近",
                "evidence": _PENALTY,
            },
        ],
        "signals": [
            {
                "direction": "对个体工商户的营商环境在持续放松、给实惠",
                "basis": [_HARD, _HOLLOW],
                "confidence": "中",
            },
        ],
    }, ensure_ascii=False)


# ── 整体结构 + 字段齐全 ───────────────────────────────────────────────────────
def test_three_sections_and_fields(monkeypatch):
    out = _run(monkeypatch, _full_payload())
    assert out["schema_version"] == rs.STAKES_SCHEMA_VERSION
    assert out["role"] == "个体工商户"
    assert len(out["related_clauses"]) == 2
    assert len(out["opportunities"]) == 2
    assert len(out["risks"]) == 1
    assert len(out["signals"]) == 1
    # 相关条款字段齐全(证据层,有 verified)
    rc = out["related_clauses"][0]
    for k in ("chapter", "matter", "relevance", "bearing", "note",
              "evidence", "verified", "match_score"):
        assert k in rc, f"相关条款缺字段 {k}"
    # 机会字段齐全
    opp = out["opportunities"][0]
    for k in ("what", "why", "action", "substance", "substance_reason",
              "horizon", "evidence", "verified", "match_score"):
        assert k in opp, f"机会缺字段 {k}"
    # 风险字段齐全(用 cost 不是 why)
    risk = out["risks"][0]
    for k in ("what", "cost", "substance", "substance_reason",
              "horizon", "evidence", "verified", "match_score"):
        assert k in risk, f"风险缺字段 {k}"
    assert "why" not in risk  # 风险没有 why
    # 信号字段齐全(评估层,无 verified)
    sig = out["signals"][0]
    for k in ("direction", "basis", "confidence"):
        assert k in sig, f"信号缺字段 {k}"
    assert "verified" not in sig  # 信号不盖鉴印


# ── 含金量 / 时效 / 置信度落封闭集 ────────────────────────────────────────────
def test_substance_horizon_confidence_in_closed_set(monkeypatch):
    out = _run(monkeypatch, _full_payload())
    for it in out["opportunities"] + out["risks"]:
        assert it["substance"] in rs.SUBSTANCE_LEVELS
        assert it["horizon"] in rs.HORIZONS
    for sig in out["signals"]:
        assert sig["confidence"] in rs.CONFIDENCE_LEVELS


def test_unknown_substance_falls_back(monkeypatch):
    """模型给个不在三档里的含金量 → 退「有条件兑现」(中性兜底)。"""
    canned = json.dumps({
        "opportunities": [{
            "what": "x", "why": "", "action": "",
            "substance": "9分超硬核",  # 不在封闭集
            "substance_reason": "", "horizon": "什么时候",  # horizon 也乱填
            "evidence": _HARD,
        }],
        "risks": [], "signals": [],
    }, ensure_ascii=False)
    out = _run(monkeypatch, canned)
    assert out["opportunities"][0]["substance"] == "有条件兑现"
    assert out["opportunities"][0]["horizon"] == "无期"  # 兜底


def test_unknown_confidence_falls_back(monkeypatch):
    """信号置信度落不进三档 → 退「低」(最保守)。"""
    canned = json.dumps({
        "opportunities": [], "risks": [],
        "signals": [{
            "direction": "在放松",
            "basis": ["鼓励各地探索更便利的个体工商户登记方式,条件成熟时逐步推广。"],
            "confidence": "非常高",  # 不在封闭集
        }],
    }, ensure_ascii=False)
    out = _run(monkeypatch, canned)
    assert out["signals"][0]["confidence"] == "低"


# ── 机会/风险 evidence 核验:命中原文 verified=True ────────────────────────────
def test_opportunities_risks_verified_when_in_original(monkeypatch):
    out = _run(monkeypatch, _full_payload())
    for it in out["opportunities"] + out["risks"]:
        assert it["verified"] is True  # canned evidence 都逐字命中合成原文
        assert it["evidence"]


def test_fabricated_evidence_dropped(monkeypatch):
    """编的 evidence(原文里根本没有)→ 核不过被丢,绝不留编的。"""
    canned = json.dumps({
        "opportunities": [
            {
                "what": "真有的减免", "why": "", "action": "",
                "substance": "真金白银", "substance_reason": "", "horizon": "近",
                "evidence": _HARD,
            },
            {
                "what": "编的大红包", "why": "", "action": "",
                "substance": "真金白银", "substance_reason": "", "horizon": "近",
                "evidence": "市局将给每户个体户发放一万元创业补贴(这句原文压根没有)。",
            },
        ],
        "risks": [
            {
                "what": "编的处罚", "cost": "", "substance": "真金白银",
                "substance_reason": "", "horizon": "近",
                "evidence": "违规者将被吊销营业执照并罚款五十万(原文没有这句)。",
            },
        ],
        "signals": [],
    }, ensure_ascii=False)
    out = _run(monkeypatch, canned)
    # 编的机会被丢,只剩真有的一条
    assert len(out["opportunities"]) == 1
    assert out["opportunities"][0]["what"] == "真有的减免"
    # 编的风险被丢,一条不剩
    assert out["risks"] == []


# ── 机会/风险按 substance 排序(真金白银在前)─────────────────────────────────
def test_sorted_by_substance(monkeypatch):
    """canned 里机会故意空头在前、真金白银在后;输出应把真金白银排到最前。"""
    out = _run(monkeypatch, _full_payload())
    subs = [it["substance"] for it in out["opportunities"]]
    assert subs[0] == "真金白银"  # 真金白银提到最前
    # 排序权重单调不降:真金白银 < 有条件兑现 < 空头倡导 的 rank
    ranks = [rs.SUBSTANCE_LEVELS.index(s) for s in subs]
    assert ranks == sorted(ranks)


# ── 信号:评估层不过 verified;无 basis / basis 编的被丢 ──────────────────────
def test_signal_no_basis_dropped(monkeypatch):
    """信号 basis 空 → 无据的推断,丢。"""
    canned = json.dumps({
        "opportunities": [], "risks": [],
        "signals": [
            {"direction": "瞎猜的方向", "basis": [], "confidence": "高"},
            {
                "direction": "有据的方向",
                "basis": ["鼓励各地探索更便利的个体工商户登记方式,条件成熟时逐步推广。"],
                "confidence": "中",
            },
        ],
    }, ensure_ascii=False)
    out = _run(monkeypatch, canned)
    assert len(out["signals"]) == 1
    assert out["signals"][0]["direction"] == "有据的方向"


def test_signal_fabricated_basis_dropped(monkeypatch):
    """信号 basis 全是编的(原文核不到)→ 无原文基础,整条丢。"""
    canned = json.dumps({
        "opportunities": [], "risks": [],
        "signals": [{
            "direction": "看起来要大放水",
            "basis": ["国家将取消所有个体户税收(这句原文没有)。"],
            "confidence": "高",
        }],
    }, ensure_ascii=False)
    out = _run(monkeypatch, canned)
    assert out["signals"] == []  # basis 核不到原文,整条丢


def test_signal_basis_keeps_only_grounded(monkeypatch):
    """信号 basis 一真一假 → 保留留下有原文基础的那条,剔掉编的;信号本身不盖 verified。"""
    real = "各区市场监管局应当于2024年9月30日前为新登记个体工商户减免登记费每户200元。"
    canned = json.dumps({
        "opportunities": [], "risks": [],
        "signals": [{
            "direction": "在给个体户实惠",
            "basis": [real, "还会发万元红包(编的)。"],
            "confidence": "中",
        }],
    }, ensure_ascii=False)
    out = _run(monkeypatch, canned)
    assert len(out["signals"]) == 1
    assert out["signals"][0]["basis"] == [real]  # 只留核得到的


# ── recommendation 非空(给了带立场的建议)──────────────────────────────────
def test_recommendation_non_empty(monkeypatch):
    out = _run(monkeypatch, _full_payload())
    assert out["recommendation"]  # 非空
    # 带立场:真金白银的点名值得动,空头的点名别当真
    assert "真金白银" in out["recommendation"] or "值得马上动" in out["recommendation"]
    assert "空头" in out["recommendation"] or "别太当真" in out["recommendation"]


def test_recommendation_empty_when_nothing(monkeypatch):
    """三段都空(机会/风险都没核过)→ recommendation 也空,前端优雅退场。"""
    canned = json.dumps({"opportunities": [], "risks": [], "signals": []}, ensure_ascii=False)
    out = _run(monkeypatch, canned)
    assert out["recommendation"] == ""


# ── 相关条款(吸收自跟我相关,整合 3)──────────────────────────────────────────
def test_related_clauses_verified_and_sorted(monkeypatch):
    """相关条款逐条核验(canned evidence 命中=verified)+ 按相关度排(高在前)。"""
    out = _run(monkeypatch, _full_payload())
    rcs = out["related_clauses"]
    assert len(rcs) == 2
    # canned 故意「中」在前「高」在后,排序应把「高」提前
    assert rcs[0]["relevance"] == "高"
    assert rcs[0]["chapter"] == 1
    # 都命中原文 → verified
    assert all(rc["verified"] is True for rc in rcs)


def test_related_clause_unverified_kept_not_dropped(monkeypatch):
    """相关条款核不过的**不丢、只标待核**(对齐原 relevance 契约,跟机会/风险丢掉不一样)。"""
    canned = json.dumps({
        "related_clauses": [{
            "chapter": 1, "matter": "编的条款", "relevance": "高", "bearing": "义务",
            "note": "x", "evidence": "原文压根没有这句话的条款。",
        }],
        "opportunities": [], "risks": [], "signals": [],
    }, ensure_ascii=False)
    out = _run(monkeypatch, canned)
    # 核不过但仍保留(标 verified=False),不像机会/风险那样丢
    assert len(out["related_clauses"]) == 1
    assert out["related_clauses"][0]["verified"] is False


def test_related_bearing_relevance_closed_set(monkeypatch):
    """相关条款的 relevance / bearing 落不进封闭集 → 退兜底(中 / 条件)。"""
    canned = json.dumps({
        "related_clauses": [{
            "chapter": 1, "matter": "x", "relevance": "超高", "bearing": "随便",
            "note": "", "evidence": _HARD,
        }],
        "opportunities": [], "risks": [], "signals": [],
    }, ensure_ascii=False)
    out = _run(monkeypatch, canned)
    assert out["related_clauses"][0]["relevance"] == "中"
    assert out["related_clauses"][0]["bearing"] == "条件"


# ── 空 role 跑通用版(整合 3,作者拍板点 3:不强制要身份)──────────────────────
def test_empty_role_runs_generic_not_empty(monkeypatch):
    """role 空 → 跑通用版(仍调 LLM 研判机会/风险/信号),不再直接返空。相关条款恒空。"""
    canned = json.dumps({
        "related_clauses": [{
            # 通用版就算模型给了相关条款也该被丢(没身份谈不上个性化相关)
            "chapter": 1, "matter": "不该出现", "relevance": "高", "bearing": "义务",
            "note": "", "evidence": _HARD,
        }],
        "opportunities": [{
            "what": "登记费减免每户200元", "why": "新登记能省钱", "action": "去办登记",
            "substance": "真金白银", "substance_reason": "有数字+时限+主体", "horizon": "近",
            "evidence": _HARD,
        }],
        "risks": [], "signals": [],
    }, ensure_ascii=False)
    out = _run(monkeypatch, canned, role="   ")  # 全空白身份
    assert out["role"] == ""
    # 通用版仍研判出机会(不再返空)
    assert len(out["opportunities"]) == 1
    # 相关条款个性化,通用版恒空
    assert out["related_clauses"] == []


def test_empty_role_uses_generic_instruction(monkeypatch):
    """role 空时拼的是通用版指令(不含「用户身份」尾段),不喂荒谬身份判定那套。"""
    captured = {}

    def _capture(*_a, **kw):  # noqa: ANN002, ANN003, ANN202
        captured["system"] = kw.get("system", "")
        return json.dumps(
            {"related_clauses": [], "opportunities": [], "risks": [], "signals": []},
            ensure_ascii=False,
        )

    monkeypatch.setattr(rs, "invoke_client_cached", _capture)
    rs.stakes_from_doc(
        chunks=_CHUNKS, role="", llm_client=_FakeClient(),
        model="deepseek-v4-flash", full_text=_FULL_TEXT,
    )
    assert "用户身份:" not in captured["system"]  # 通用版不拼身份尾段
    assert "面向**一般读者**" in captured["system"]  # 用的是通用指令


# ── parse 兜底:去 markdown 围栏 ──────────────────────────────────────────────
def test_strips_code_fence(monkeypatch):
    fenced = "```json\n" + _full_payload() + "\n```"
    out = _run(monkeypatch, fenced)
    assert len(out["opportunities"]) == 2
    assert len(out["risks"]) == 1


def test_unparseable_returns_empty(monkeypatch):
    """完全解析不出 → 三段空 + recommendation 空,不报错。"""
    out = _run(monkeypatch, "这根本不是 JSON")
    assert out["opportunities"] == []
    assert out["risks"] == []
    assert out["signals"] == []
    assert out["recommendation"] == ""


def test_llm_exception_returns_empty(monkeypatch):
    """LLM 调用抛异常 → 吞掉返空结构(前端优雅退场),不往上抛。"""
    def _boom(*_a, **_kw):  # noqa: ANN002, ANN003, ANN202
        raise RuntimeError("provider 503")
    monkeypatch.setattr(rs, "invoke_client_cached", _boom)
    out = rs.stakes_from_doc(
        chunks=_CHUNKS, role="个体工商户", llm_client=_FakeClient(),
        model="deepseek-v4-flash", full_text=_FULL_TEXT,
    )
    assert out["role"] == "个体工商户"
    assert out["opportunities"] == []
    assert out["signals"] == []


# ── 纯件:封闭集归一 ──────────────────────────────────────────────────────────
def test_coerce_substance_pure():
    # 归一件已统一到 redhead_codebook(单一真相源),stakes 经 import 暴露同一公开件。
    for lv in rs.SUBSTANCE_LEVELS:
        assert rs.coerce_substance(lv) == lv
    assert rs.coerce_substance("空头支票") == "有条件兑现"  # 落不进退兜底
    assert rs.coerce_substance(123) == "有条件兑现"
    assert rs.coerce_substance("  真金白银  ") == "真金白银"  # 去空白


def test_coerce_confidence_pure():
    for lv in rs.CONFIDENCE_LEVELS:
        assert rs._coerce_confidence(lv) == lv
    assert rs._coerce_confidence("爆表") == "低"
    assert rs._coerce_confidence(None) == "低"


def test_coerce_opportunity_drops_blank():
    # what 空 → 丢
    assert rs._coerce_opportunity({"what": "", "evidence": "有原文"}) is None
    # evidence 空 → 丢(证据层没原文撑不进)
    assert rs._coerce_opportunity({"what": "有说法", "evidence": ""}) is None
    ok = rs._coerce_opportunity({"what": "x", "evidence": "y"})
    assert ok is not None
    assert ok["substance"] == "有条件兑现"  # 缺 substance 退兜底


def test_coerce_signal_drops_no_basis():
    # basis 空 → 丢
    assert rs._coerce_signal({"direction": "方向", "basis": []}) is None
    # direction 空 → 丢
    assert rs._coerce_signal({"direction": "", "basis": ["原文"]}) is None
    ok = rs._coerce_signal({"direction": "方向", "basis": ["原文片段"]})
    assert ok is not None
    assert ok["confidence"] == "低"  # 缺 confidence 退兜底
    # basis 写成单字符串也宽松收
    ok2 = rs._coerce_signal({"direction": "d", "basis": "单条原文"})
    assert ok2 is not None
    assert ok2["basis"] == ["单条原文"]


def test_coerce_related_pure():
    # matter 和 evidence 都空 → 丢(没说法也没原文)
    assert rs._coerce_related({"matter": "", "evidence": ""}) is None
    # 只要有 matter 或 evidence 之一就保留(evidence 进核验那步)
    ok = rs._coerce_related({"matter": "x", "evidence": ""})
    assert ok is not None
    assert ok["relevance"] == "中"  # 缺 relevance 退兜底
    assert ok["bearing"] == "条件"  # 缺 bearing 退兜底
    # chapter 非整数 → None(锚不回具体条次)
    assert rs._coerce_related({"matter": "x", "chapter": "一"})["chapter"] is None
    assert rs._coerce_related({"matter": "x", "chapter": 3})["chapter"] == 3
