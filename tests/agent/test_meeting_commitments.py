"""跨会议承诺—兑现 meeting_commitments 单测(1.7 会议垂直·杀手价值)。

合成两场会(6 月会承诺、7 月会兑现没)的 chunk + 整份原文 + mock LLM,不跑真 LLM,覆盖:

- 每场会出会脉(复用 action_ledger_from_meeting)→ 承诺=行动项;按会议时间排序。
- 一次全局推理跨会判兑现状态 + 锚回真实承诺(cid)。
- **状态死守 evidence-first**:兑现/未兑现/进行中必须更晚会议有原话坐实(过核验);
  锚不到证据 / 编的证据 → 降「未知」(绝不猜兑现,假阳性最坏)。
- **逾期由 BE 据 due 纯算**(due 真过 + 没兑现证据),不收模型的逾期标。
- 状态封闭集 + 别名归一 + 落不进退「未知」。
- 我的承诺(owner 筛);按人分组(owners);台账排序(逾期/未兑现置顶)。
- 不足 2 场 / 一条承诺都没 → None;LLM 失败 → 承诺还在全归未知;截断抢救。

mock 策略照 test_meeting_spine + test_cross_doc:patch 三处 invoke_client_cached
(meeting_spine 头要素 / _exhaustive 结论项 / meeting_commitments 跨会推理),靠 system
里的指令特征 + 当前在读哪场会的原文区分该返哪段 canned。
"""

from __future__ import annotations

import json

from bookscope.agent import meeting_commitments as mc
from bookscope.agent import meeting_spine as ms
from bookscope.agent._internal import exhaustive as _exhaustive

# ── 合成两场会 ───────────────────────────────────────────────────────────────
# 第 1 场(6 月):Eng-B 承诺下周交鉴权(有 owner 有 due=闭环真金白银)。
_M1_HEAD = "星图项目 第10次周会 2026年6月1日 参会:PM-A、Eng-B"
_M1_DECIDE = "PM-A:好,鉴权就这么定,用 token 方案。"
_M1_COMMIT = "Eng-B:鉴权接口我来写,下周一前给你们出初版。"
_M1_FULL = "\n".join([_M1_HEAD, _M1_DECIDE, _M1_COMMIT])
_M1_CHUNKS = [
    {"chunk_id": "m1h", "chapter": 0, "text": _M1_HEAD},
    {"chunk_id": "m1c", "chapter": 1, "text": _M1_DECIDE + _M1_COMMIT},
]

# 第 2 场(7 月):提到鉴权还没动(= 上一场承诺未兑现的原话信号)。
_M2_HEAD = "星图项目 第14次周会 2026年7月1日 参会:PM-A、Eng-B"
_M2_OPEN = "Eng-B:上次说的鉴权接口我还没开始弄,这周也排不上,得往后挪。"
_M2_FULL = "\n".join([_M2_HEAD, _M2_OPEN])
_M2_CHUNKS = [
    {"chunk_id": "m2h", "chapter": 0, "text": _M2_HEAD},
    {"chunk_id": "m2c", "chapter": 1, "text": _M2_OPEN},
]


class _FakeClient:
    def extract_final_text(self, resp):  # noqa: ANN001, ANN201
        return resp if isinstance(resp, str) else "{}"


# ── 每场会的 canned 会脉(头要素 + 结论项) ──────────────────────────────────
def _m1_head() -> str:
    return json.dumps({"form": "逐字稿", "elements": [
        {"field": "会议主题", "value": "星图项目第10次周会", "evidence": _M1_HEAD},
        {"field": "会议时间", "value": "2026年6月1日", "evidence": _M1_HEAD},
        {"field": "主持人", "value": "PM-A", "evidence": _M1_DECIDE},
        {"field": "参会人", "value": "PM-A、Eng-B", "evidence": _M1_HEAD},
        {"field": "缺席/列席", "value": "", "evidence": ""},
        {"field": "记录范围", "value": "", "evidence": ""},
    ]}, ensure_ascii=False)


def _m1_conclusions() -> str:
    return json.dumps({
        "decisions": [
            {"chapter": 1, "decision": "鉴权用 token 方案", "decided_by": "PM-A",
             "background": "", "substance": "真金白银", "substance_reason": "拍板",
             "evidence": _M1_DECIDE},
        ],
        "action_items": [
            {"chapter": 1, "task": "写鉴权接口初版", "owner": "Eng-B", "due": "下周一前",
             "from_decision": 1, "source": "Eng-B", "substance": "真金白银",
             "substance_reason": "有 owner 有 due", "evidence": _M1_COMMIT},
        ],
        "open_issues": [],
    }, ensure_ascii=False)


def _m2_head() -> str:
    return json.dumps({"form": "逐字稿", "elements": [
        {"field": "会议主题", "value": "星图项目第14次周会", "evidence": _M2_HEAD},
        {"field": "会议时间", "value": "2026年7月1日", "evidence": _M2_HEAD},
        {"field": "主持人", "value": "PM-A", "evidence": _M2_HEAD},
        {"field": "参会人", "value": "PM-A、Eng-B", "evidence": _M2_HEAD},
        {"field": "缺席/列席", "value": "", "evidence": ""},
        {"field": "记录范围", "value": "", "evidence": ""},
    ]}, ensure_ascii=False)


def _m2_conclusions() -> str:
    # 鉴权又被当未决重提 = 上一场承诺没兑现的原话信号。
    return json.dumps({
        "decisions": [],
        "action_items": [],
        "open_issues": [
            {"chapter": 1, "issue": "鉴权接口还没动,要往后挪", "raised_by": "Eng-B",
             "why_open": "未拍板", "background": "没排上", "evidence": _M2_OPEN},
        ],
    }, ensure_ascii=False)


# 默认跨会推理:cid=0(鉴权承诺)未兑现,证据来自第 2 场会(mid=1)的原话。
def _cross_payload(
    *, status="未兑现", evidence_mid=1, evidence=_M2_OPEN, cid=0
) -> str:
    return json.dumps({"commitments": [
        {"cid": cid, "status": status, "evidence_mid": evidence_mid,
         "evidence": evidence, "note": "下一场会说还没动"},
    ]}, ensure_ascii=False)


def _patch(monkeypatch, *, m1_head=None, m1_conc=None, m2_head=None, m2_conc=None,
           cross=None, cross_raises=None):
    """patch 三处 invoke_client_cached。

    - meeting_spine + _exhaustive:会脉两阶段(头要素 / 结论项),靠 system 指令特征 + 当前读哪场
      会的原文(full_text 拼进 system 的 book-first 前缀)区分该返哪场哪段。
    - meeting_commitments:跨会推理那一次(system 是 _INSTR,带「承诺清单」字样)。
    """
    m1h = m1_head if m1_head is not None else _m1_head()
    m1c = m1_conc if m1_conc is not None else _m1_conclusions()
    m2h = m2_head if m2_head is not None else _m2_head()
    m2c = m2_conc if m2_conc is not None else _m2_conclusions()

    def _spine_fake(_client, *, system="", **_kw):  # noqa: ANN001, ANN002, ANN003, ANN202
        # 哪场会:看 book-first 前缀里拼的原文(每场原文里有唯一标识串)。
        is_m1 = "第10次周会" in system or _M1_COMMIT in system
        if "会议头要素" in system:
            return m1h if is_m1 else m2h
        return m1c if is_m1 else m2c

    def _cross_fake(*_a, **_kw):  # noqa: ANN002, ANN003, ANN202
        if cross_raises is not None:
            raise cross_raises
        return cross if cross is not None else _cross_payload()

    monkeypatch.setattr(ms, "invoke_client_cached", _spine_fake)
    monkeypatch.setattr(_exhaustive, "invoke_client_cached", _spine_fake)
    monkeypatch.setattr(mc, "invoke_client_cached", _cross_fake)


def _run(monkeypatch, *, chunks=None, full_texts=None, owner=None, **patch_kw):
    _patch(monkeypatch, **patch_kw)
    return mc.commitments_across_meetings(
        meeting_chunks=chunks if chunks is not None else [_M1_CHUNKS, _M2_CHUNKS],
        llm_client=_FakeClient(),
        model="deepseek-v4-flash",
        meeting_full_texts=full_texts if full_texts is not None else [_M1_FULL, _M2_FULL],
        owner=owner,
        max_workers=1,  # 串行,测试可复现
    )


# ── 整体形状 ─────────────────────────────────────────────────────────────────
def test_overall_shape(monkeypatch):
    out = _run(monkeypatch)
    assert out is not None
    assert "commitments" in out and "meetings" in out and "owners" in out
    # 第 1 场 1 条承诺(鉴权);第 2 场没有行动项 → 共 1 条承诺。
    assert len(out["commitments"]) == 1
    assert len(out["meetings"]) == 2
    c = out["commitments"][0]
    for k in ("cid", "from_mid", "from_meeting", "from_date", "owner", "task", "due",
              "status", "status_note", "evidence_mid", "evidence_meeting", "evidence",
              "evidence_verified", "from_evidence", "from_verified"):
        assert k in c, f"承诺缺字段 {k}"


def test_commitment_anchored_to_real_meeting(monkeypatch):
    """承诺锚回真实会议:来自第 1 场(6 月),task/owner/due 照搬会脉。"""
    out = _run(monkeypatch)
    c = out["commitments"][0]
    assert c["from_mid"] == 0
    assert c["from_date"] == "2026年6月1日"
    assert c["owner"] == "Eng-B"
    assert "鉴权" in c["task"]
    assert c["due"] == "下周一前"


# ── 跨会判兑现(命门):evidence-first ────────────────────────────────────────
def test_unfulfilled_with_later_evidence(monkeypatch):
    """更晚的会有原话说没做 → 未兑现 + 证据锚到第 2 场会、过核验。"""
    out = _run(monkeypatch)
    c = out["commitments"][0]
    assert c["status"] == "未兑现"
    assert c["evidence_mid"] == 1
    assert c["evidence_meeting"] == "星图项目第14次周会"
    assert c["evidence_verified"] is True
    assert "鉴权" in c["evidence"]


def test_fulfilled_with_real_evidence(monkeypatch):
    """更晚的会真有「做完了」的原话(且逐字命中)→ 兑现成立。"""
    # 把第 2 场会脉改成「鉴权接好了」,跨会推理判兑现、证据引这句。
    done = "Eng-B:鉴权接口已经接好上线了,这块完事。"
    m2_full = "\n".join([_M2_HEAD, done])
    m2_conc = json.dumps({"decisions": [
        {"chapter": 1, "decision": "鉴权接口已接好上线", "decided_by": "Eng-B",
         "background": "", "substance": "真金白银", "substance_reason": "已落地",
         "evidence": done},
    ], "action_items": [], "open_issues": []}, ensure_ascii=False)
    out = _run(
        monkeypatch,
        chunks=[_M1_CHUNKS, [{"chunk_id": "m2h", "chapter": 0, "text": _M2_HEAD},
                             {"chunk_id": "m2c", "chapter": 1, "text": done}]],
        full_texts=[_M1_FULL, m2_full],
        m2_conc=m2_conc,
        cross=_cross_payload(status="兑现", evidence_mid=1, evidence=done),
    )
    c = out["commitments"][0]
    assert c["status"] == "兑现"
    assert c["evidence_verified"] is True


def test_fulfilled_without_evidence_downgraded(monkeypatch):
    """模型判「兑现」但没给证据 → 降「未知」(绝不猜兑现)。"""
    out = _run(monkeypatch, cross=_cross_payload(
        status="兑现", evidence_mid=None, evidence=""))
    c = out["commitments"][0]
    assert c["status"] == "未知"  # 没据 → 降级
    assert c["evidence"] == ""
    assert c["evidence_verified"] is False


def test_fulfilled_with_fabricated_evidence_downgraded(monkeypatch):
    """模型判「兑现」但证据原文里没有(编的)→ 降「未知」。"""
    out = _run(monkeypatch, cross=_cross_payload(
        status="兑现", evidence_mid=1, evidence="Eng-B 说鉴权早就上线了(原文根本没这句)"))
    c = out["commitments"][0]
    assert c["status"] == "未知"
    assert c["evidence_verified"] is False


def test_evidence_from_earlier_meeting_rejected(monkeypatch):
    """兑现证据指向的是承诺那场会(不是更晚的)→ 时序闸拦掉、降未知。

    cid=0 承诺来自 mid=0,证据若指 mid=0(同场或更早)不能算兑现——必须更晚的会。
    """
    out = _run(monkeypatch, cross=_cross_payload(
        status="兑现", evidence_mid=0, evidence=_M1_COMMIT))
    c = out["commitments"][0]
    assert c["status"] == "未知"  # 证据不在更晚的会 → 降级


def test_no_later_signal_is_unknown(monkeypatch):
    """模型判「未知」(更晚的会没再提)→ 保持未知、无证据。"""
    out = _run(monkeypatch, cross=_cross_payload(
        status="未知", evidence_mid=None, evidence=""))
    c = out["commitments"][0]
    assert c["status"] == "未知"
    assert c["evidence"] == ""


# ── 逾期由 BE 据 due 纯算 ────────────────────────────────────────────────────
def test_overdue_computed_by_be(monkeypatch):
    """due 真过了(承诺 due=6月10日,有一场 7 月会晚过)+ 没兑现证据 → BE 升「逾期」。"""
    # 承诺 due 给个能解析的绝对日期(默认「下周一前」解析不出、不会标逾期)。
    m1_conc = json.dumps({"decisions": [], "action_items": [
        {"chapter": 1, "task": "写鉴权接口初版", "owner": "Eng-B", "due": "2026年6月10日",
         "from_decision": None, "source": "", "substance": "真金白银",
         "substance_reason": "", "evidence": _M1_COMMIT},
    ], "open_issues": []}, ensure_ascii=False)
    # 跨会推理给未兑现但**不带有效证据**(evidence 编的),好让它先降未知再被逾期逻辑接管。
    # 这里直接让模型判未知,逾期完全靠 BE 据 due+会议日期算。
    out = _run(monkeypatch, m1_conc=m1_conc, cross=_cross_payload(
        status="未知", evidence_mid=None, evidence=""))
    c = out["commitments"][0]
    assert c["status"] == "逾期"  # 6/10 due,7/1 的会晚过 → 逾期


def test_no_overdue_without_due(monkeypatch):
    """没 due → 谈不上逾期(保持模型判的状态)。默认 due=「下周一前」解析不出 → 不标逾期。"""
    out = _run(monkeypatch, cross=_cross_payload(
        status="未知", evidence_mid=None, evidence=""))
    c = out["commitments"][0]
    assert c["status"] == "未知"  # due 解析不出,不强标逾期


def test_fulfilled_never_becomes_overdue(monkeypatch):
    """已兑现的(有有效证据)绝不被标逾期,哪怕 due 过了。"""
    done = "Eng-B:鉴权接口已经接好上线了,完事。"
    m1_conc = json.dumps({"decisions": [], "action_items": [
        {"chapter": 1, "task": "写鉴权接口初版", "owner": "Eng-B", "due": "2026年6月10日",
         "from_decision": None, "source": "", "substance": "真金白银",
         "substance_reason": "", "evidence": _M1_COMMIT},
    ], "open_issues": []}, ensure_ascii=False)
    m2_conc = json.dumps({"decisions": [
        {"chapter": 1, "decision": "鉴权已接好上线", "decided_by": "Eng-B",
         "background": "", "substance": "真金白银", "substance_reason": "",
         "evidence": done},
    ], "action_items": [], "open_issues": []}, ensure_ascii=False)
    out = _run(
        monkeypatch,
        chunks=[_M1_CHUNKS, [{"chunk_id": "m2h", "chapter": 0, "text": _M2_HEAD},
                             {"chunk_id": "m2c", "chapter": 1, "text": done}]],
        full_texts=[_M1_FULL, "\n".join([_M2_HEAD, done])],
        m1_conc=m1_conc, m2_conc=m2_conc,
        cross=_cross_payload(status="兑现", evidence_mid=1, evidence=done),
    )
    c = out["commitments"][0]
    assert c["status"] == "兑现"  # 不被逾期覆盖


# ── 状态封闭集 + 别名 ────────────────────────────────────────────────────────
def test_status_alias_normalized(monkeypatch):
    """模型吐「已完成」→ 归一到「兑现」(再走证据核验:有据才留兑现)。"""
    done = "Eng-B:鉴权接口已经接好上线了,完事。"
    out = _run(
        monkeypatch,
        chunks=[_M1_CHUNKS, [{"chunk_id": "m2h", "chapter": 0, "text": _M2_HEAD},
                             {"chunk_id": "m2c", "chapter": 1, "text": done}]],
        full_texts=[_M1_FULL, "\n".join([_M2_HEAD, done])],
        m2_conc=json.dumps({"decisions": [
            {"chapter": 1, "decision": "鉴权已接好", "decided_by": "Eng-B", "background": "",
             "substance": "真金白银", "substance_reason": "", "evidence": done},
        ], "action_items": [], "open_issues": []}, ensure_ascii=False),
        cross=_cross_payload(status="已完成", evidence_mid=1, evidence=done),
    )
    assert out["commitments"][0]["status"] == "兑现"


def test_status_unknown_falls_back(monkeypatch):
    """落不进封闭集 → 退「未知」。"""
    out = _run(monkeypatch, cross=_cross_payload(
        status="瞎填状态", evidence_mid=None, evidence=""))
    assert out["commitments"][0]["status"] == "未知"


def test_model_overdue_treated_as_unfulfilled(monkeypatch):
    """模型直接说「逾期」→ 先当未兑现收(要有据),逾期是 BE 的活。这里无有效证据 → 降未知。"""
    out = _run(monkeypatch, cross=_cross_payload(
        status="逾期", evidence_mid=None, evidence=""))
    # 模型的逾期当未兑现收,但无证据 → 降未知;且 due 解析不出不升逾期。
    assert out["commitments"][0]["status"] == "未知"


def test_coerce_status_pure():
    assert mc._coerce_status("兑现") == "兑现"
    assert mc._coerce_status("已完成") == "兑现"  # 别名
    assert mc._coerce_status("没做") == "未兑现"  # 别名
    assert mc._coerce_status("逾期") == "未兑现"  # 逾期当未兑现收
    assert mc._coerce_status("在做") == "进行中"  # 别名
    assert mc._coerce_status("瞎填") == "未知"
    assert mc._coerce_status(None) == "未知"
    assert mc._coerce_status("  进行中 ") == "进行中"  # 去空白


# ── 锚不到真实承诺 → 丢 ──────────────────────────────────────────────────────
def test_unknown_cid_dropped(monkeypatch):
    """模型给个不存在的 cid → 丢(不编不存在的承诺);真实承诺补「未知」兜底。"""
    out = _run(monkeypatch, cross=json.dumps({"commitments": [
        {"cid": 999, "status": "兑现", "evidence_mid": 1, "evidence": _M2_OPEN, "note": ""},
    ]}, ensure_ascii=False))
    # cid=999 丢;真实 cid=0 没被判到 → 补未知。
    assert len(out["commitments"]) == 1
    assert out["commitments"][0]["cid"] == 0
    assert out["commitments"][0]["status"] == "未知"


# ── 我的承诺(owner 筛) ──────────────────────────────────────────────────────
def test_my_commitments_filter_by_owner(monkeypatch):
    """传 owner=Eng-B 只返 Eng-B 的承诺。"""
    out = _run(monkeypatch, owner="Eng-B")
    assert all(c["owner"] == "Eng-B" or "Eng-B" in c["owner"] for c in out["commitments"])
    assert len(out["commitments"]) == 1


def test_my_commitments_no_match(monkeypatch):
    """传一个没承诺的 owner → 返空 commitments(但 scanned 仍 true)。"""
    out = _run(monkeypatch, owner="查无此人")
    assert out is not None
    assert out["commitments"] == []


# ── owners 列表 + 台账排序 ───────────────────────────────────────────────────
def test_owners_listed(monkeypatch):
    """owners 列出有承诺的人(Eng-B)。"""
    out = _run(monkeypatch)
    assert "Eng-B" in out["owners"]


def test_sort_overdue_first(monkeypatch):
    """台账排序:逾期 / 未兑现(要追的)排在兑现 / 未知前。

    造两条承诺:一条未兑现、一条兑现,断言未兑现排前。
    """
    # 第 1 场两条承诺。
    m1_conc = json.dumps({"decisions": [], "action_items": [
        {"chapter": 1, "task": "写鉴权接口初版", "owner": "Eng-B", "due": "",
         "from_decision": None, "source": "", "substance": "真金白银",
         "substance_reason": "", "evidence": _M1_COMMIT},
        {"chapter": 2, "task": "写文档", "owner": "PM-A", "due": "",
         "from_decision": None, "source": "", "substance": "有条件兑现",
         "substance_reason": "", "evidence": _M1_DECIDE},
    ], "open_issues": []}, ensure_ascii=False)
    done = "PM-A:文档我写好了,发群里了。"
    m2_full = "\n".join([_M2_HEAD, _M2_OPEN, done])
    m2_conc = json.dumps({"decisions": [
        {"chapter": 1, "decision": "文档已写好", "decided_by": "PM-A", "background": "",
         "substance": "真金白银", "substance_reason": "", "evidence": done},
    ], "action_items": [], "open_issues": [
        {"chapter": 1, "issue": "鉴权还没动", "raised_by": "Eng-B", "why_open": "未拍板",
         "background": "", "evidence": _M2_OPEN},
    ]}, ensure_ascii=False)
    cross = json.dumps({"commitments": [
        {"cid": 0, "status": "未兑现", "evidence_mid": 1, "evidence": _M2_OPEN, "note": ""},
        {"cid": 1, "status": "兑现", "evidence_mid": 1, "evidence": done, "note": ""},
    ]}, ensure_ascii=False)
    out = _run(
        monkeypatch,
        chunks=[_M1_CHUNKS, [{"chunk_id": "m2h", "chapter": 0, "text": _M2_HEAD},
                             {"chunk_id": "m2c", "chapter": 1, "text": _M2_OPEN + done}]],
        full_texts=[_M1_FULL, m2_full],
        m1_conc=m1_conc, m2_conc=m2_conc, cross=cross,
    )
    statuses = [c["status"] for c in out["commitments"]]
    assert statuses.index("未兑现") < statuses.index("兑现")


# ── 边界 / 兜底 ──────────────────────────────────────────────────────────────
def test_fewer_than_two_meetings_none(monkeypatch):
    """只有 1 场会 → None(跨会追要 ≥2 场)。"""
    _patch(monkeypatch)
    out = mc.commitments_across_meetings(
        meeting_chunks=[_M1_CHUNKS],
        llm_client=_FakeClient(), model="deepseek-v4-flash",
        meeting_full_texts=[_M1_FULL], max_workers=1,
    )
    assert out is None


def test_no_commitments_none(monkeypatch):
    """两场会但一条行动项都没抽到 → None(无承诺可追)。"""
    empty = json.dumps({"decisions": [], "action_items": [], "open_issues": []},
                       ensure_ascii=False)
    out = _run(monkeypatch, m1_conc=empty, m2_conc=empty)
    assert out is None


def test_llm_failure_keeps_commitments_as_unknown(monkeypatch):
    """跨会推理抛错 → 承诺还在(真实抽到的),状态全归未知,不崩。"""
    out = _run(monkeypatch, cross_raises=RuntimeError("provider 503"))
    assert out is not None
    assert len(out["commitments"]) == 1
    assert out["commitments"][0]["status"] == "未知"


def test_unparseable_cross_keeps_unknown(monkeypatch):
    """跨会推理返非 JSON → 承诺全归未知。"""
    out = _run(monkeypatch, cross="这根本不是 JSON")
    assert out["commitments"][0]["status"] == "未知"


def test_cross_salvaged_on_truncation(monkeypatch):
    """跨会推理被截断 → 截断抢救也能捞回状态。"""
    broken = (
        '{"commitments":[{"cid":0,"status":"未兑现","evidence_mid":1,'
        '"evidence":"' + _M2_OPEN + '","note":"还没动"}'
    )  # 缺结尾 ]} → 截断态
    out = _run(monkeypatch, cross=broken)
    c = out["commitments"][0]
    assert c["status"] == "未兑现"
    assert c["evidence_verified"] is True


def test_strips_code_fence(monkeypatch):
    fenced = "```json\n" + _cross_payload() + "\n```"
    out = _run(monkeypatch, cross=fenced)
    assert out["commitments"][0]["status"] == "未兑现"


# ── 排序按会议时间(更早的会承诺先排) ───────────────────────────────────────
def test_meetings_sorted_by_date(monkeypatch):
    """会议按日期排:6 月会(mid=0)在 7 月会(mid=1)前——哪怕传进来顺序反了。"""
    # 故意把 7 月会传在前、6 月会传在后,看排序后 mid 仍按日期。
    out = _run(
        monkeypatch,
        chunks=[_M2_CHUNKS, _M1_CHUNKS],
        full_texts=[_M2_FULL, _M1_FULL],
    )
    # 排序后 meetings[0] 应是 6 月那场。
    assert out["meetings"][0]["date"] == "2026年6月1日"
    assert out["meetings"][1]["date"] == "2026年7月1日"


# ── 纯件:日期归一 ───────────────────────────────────────────────────────────
def test_normalize_date_pure():
    assert mc._normalize_date("2026年3月10日") == "20260310"
    assert mc._normalize_date("2026-03-10") == "20260310"
    assert mc._normalize_date("2026/3/9") == "20260309"
    assert mc._normalize_date("下周一前") == ""  # 相对期解析不出
    assert mc._normalize_date("3月10日") == ""  # 没年不强判
    assert mc._normalize_date("") == ""
