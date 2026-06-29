"""会议会脉 + 行动项台账 meeting_spine 单测(1.7 会议垂直首炮)。

合成一份会议记录的 chunk + 整份原文 + mock LLM(假 client + monkeypatch invoke_client_cached
返 canned JSON),不跑真 LLM,覆盖:

- 头要素抽取 + form 门控判形态 + N/A 区分(纪要的「缺席/列席」、逐字稿的「记录范围」)。
- 结论项一次抽两类(decisions + action_items)+ 字段齐全 + coerce。
- **loose_end 由 BE 纯计算**(owner 空 or due 空),不收模型的值。
- **含金量判档**(会议三档,公文「空头倡导」别名归一到会议「空头表态」,落不进退兜底)。
- evidence 锚原文过核验(逐字命中=verified,编的=待核)。
- from_decision 段内序号 → 全局序号映射;台账排序(loose_end 置顶 → 含金量 → 序号)。
- 我的行动项:传 owner 只返该身份的;parse 兜底 / 异常退空。
- **议而未决(第二炮)**:抽出来 + 字段齐 + why_open 四档判 + 别名归一 + raised_by 空不编人 +
  evidence 核验 + 按为何悬着排序 + 截断抢救。
"""

from __future__ import annotations

import json

from bookscope.agent import meeting_spine as ms
from bookscope.agent._internal import exhaustive as _exhaustive

# 合成逐字稿:开头白(主题/时间/参会)+ 几句带说话人的发言,canned evidence 逐字引来命中核验。
_HEAD_LINE = "星图项目 第14次周会 2026年3月3日 参会:PM-A、Eng-B、Eng-C"
# 闭环行动项(有 owner + due):该判真金白银、loose_end=false。
_EV_AUTH = "Eng-B:接口我来写,下周一前给你们出个初版,你们先接着调。"
# 开环行动项(owner 空):该 loose_end=true、含金量空头表态。
_EV_PERF = "PM-A:性能这个先记着,回头安排个人专门看看。"
# 决议拍板句。
_EV_DECIDE = "PM-A:好,那鉴权就定了,用 token + 刷新方案。"
# 议而未决:讨论了没拍板的议题(数据库选型),raised_by 抽得到、why_open=未拍板。
_EV_OPEN = "Eng-C:数据库到底用 PG 还是 Mongo,我俩没聊拢,这个再研究研究下次定吧。"

_FULL_TEXT = "\n".join([_HEAD_LINE, _EV_DECIDE, _EV_AUTH, _EV_PERF, _EV_OPEN])

_CHUNKS = [
    {"chunk_id": "h0", "chapter": 0, "text": _HEAD_LINE},
    {"chunk_id": "c1", "chapter": 1, "text": _EV_DECIDE + _EV_AUTH + _EV_PERF + _EV_OPEN},
]


class _FakeClient:
    def extract_final_text(self, resp):  # noqa: ANN001, ANN201
        return resp if isinstance(resp, str) else "{}"


def _head_payload(form: str = "逐字稿") -> str:
    """头要素一次抽取的 canned:主题/时间/主持人/参会抽到,缺席/记录范围留空。"""
    return json.dumps({"form": form, "elements": [
        {"field": "会议主题", "value": "星图项目第14次周会", "evidence": _HEAD_LINE},
        {"field": "会议时间", "value": "2026年3月3日", "evidence": _HEAD_LINE},
        {"field": "主持人", "value": "PM-A", "evidence": _EV_DECIDE},
        {"field": "参会人", "value": "PM-A、Eng-B、Eng-C", "evidence": _HEAD_LINE},
        {"field": "缺席/列席", "value": "", "evidence": ""},
        {"field": "记录范围", "value": "", "evidence": ""},
    ]}, ensure_ascii=False)


def _conclusions_payload() -> str:
    """结论项一次抽三类:1 条决议 + 2 条行动项(1 闭环 1 开环)+ 1 条议而未决。

    行动项 1(鉴权)挂 from_decision=1(本段决议序号);行动项 2(性能)owner 空、from_decision=null。
    议而未决(数据库选型)why_open=未拍板、raised_by 抽到。
    """
    return json.dumps({
        "decisions": [
            {"chapter": 1, "decision": "鉴权用 token + 刷新方案", "decided_by": "PM-A",
             "background": "Eng-B 调研后对比三方案", "substance": "真金白银",
             "substance_reason": "明确拍板「就定了」+ 有人接带时限", "evidence": _EV_DECIDE},
        ],
        "action_items": [
            {"chapter": 1, "task": "写鉴权接口初版", "owner": "Eng-B", "due": "下周一前",
             "from_decision": 1, "source": "Eng-B", "substance": "真金白银",
             "substance_reason": "有 owner 有 due", "evidence": _EV_AUTH},
            {"chapter": 2, "task": "看性能优化", "owner": "", "due": "",
             "from_decision": None, "source": "PM-A", "substance": "空头表态",
             "substance_reason": "「回头安排个人」无 owner 无 due", "evidence": _EV_PERF},
        ],
        "open_issues": [
            {"chapter": 1, "issue": "数据库选 PG 还是 Mongo 没定", "raised_by": "Eng-C",
             "why_open": "未拍板", "background": "两人没聊拢,留到下次", "evidence": _EV_OPEN},
        ],
    }, ensure_ascii=False)


def _patch_two_phase(monkeypatch, head_canned: str, conclusions_canned: str):
    """patch invoke_client_cached:头要素抽取返 head_canned,结论项抽取返 conclusions_canned。

    两阶段靠 system 里的指令特征区分(头要素 prompt 带「会议头要素」,结论项带「结论项精读」)。
    run_segments 内部也走 invoke_client_cached,所以这一个 patch 同时管头要素维和结论项维。
    """
    def _fake(_client, *, system="", **_kw):  # noqa: ANN001, ANN002, ANN003, ANN202
        if "会议头要素" in system:
            return head_canned
        return conclusions_canned
    # 头要素维 + 续抽走 meeting_spine 自己 import 的;结论项维走 run_segments,而
    # run_segments 在 _internal.exhaustive 命名空间里 import invoke_client_cached——
    # 两处都要 patch 才管得到整条链。
    monkeypatch.setattr(ms, "invoke_client_cached", _fake)
    monkeypatch.setattr(_exhaustive, "invoke_client_cached", _fake)


def _run(monkeypatch, *, form=None, owner=None,
         head_canned=None, conclusions_canned=None):
    _patch_two_phase(
        monkeypatch,
        head_canned if head_canned is not None else _head_payload(),
        conclusions_canned if conclusions_canned is not None else _conclusions_payload(),
    )
    return ms.action_ledger_from_meeting(
        chunks=_CHUNKS,
        llm_client=_FakeClient(),
        model="deepseek-v4-flash",
        full_text=_FULL_TEXT,
        form=form,
        owner=owner,
        max_workers=1,  # 串行,测试可复现
    )


# ── 整体形状 ─────────────────────────────────────────────────────────────────
def test_ledger_overall_shape(monkeypatch):
    out = _run(monkeypatch)
    assert out["schema_version"] == ms.MEETING_SPINE_SCHEMA_VERSION
    assert out["form"] in ms.MEETING_FORMS
    assert len(out["decisions"]) == 1
    assert len(out["action_items"]) == 2
    assert len(out["open_issues"]) == 1  # 第二炮:议而未决抽出来了
    # head 固定 6 条骨架,没抽到的也出一条
    assert len(out["head"]) == 6


def test_action_item_fields_complete(monkeypatch):
    out = _run(monkeypatch)
    for a in out["action_items"]:
        for k in ("chapter", "task", "owner", "due", "from_decision", "source",
                  "substance", "substance_reason", "loose_end", "evidence",
                  "verified", "match_score"):
            assert k in a, f"行动项缺字段 {k}"
        assert a["substance"] in ms.MEETING_SUBSTANCE_LEVELS


def test_decision_fields_complete(monkeypatch):
    out = _run(monkeypatch)
    for d in out["decisions"]:
        for k in ("chapter", "decision", "decided_by", "background", "substance",
                  "substance_reason", "evidence", "verified", "match_score"):
            assert k in d, f"决议缺字段 {k}"
        assert d["substance"] in ms.MEETING_SUBSTANCE_LEVELS


# ── loose_end 纯计算(命门)──────────────────────────────────────────────────
def test_loose_end_computed_by_be_not_model(monkeypatch):
    """owner 空或 due 空 = loose_end true,由 BE 算;闭环的 false。"""
    out = _run(monkeypatch)
    by_task = {a["task"]: a for a in out["action_items"]}
    assert by_task["写鉴权接口初版"]["loose_end"] is False  # 有 owner 有 due
    assert by_task["看性能优化"]["loose_end"] is True        # owner 空


def test_loose_end_ignores_model_value(monkeypatch):
    """模型就算瞎填 loose_end,BE 也按 owner/due 真实情况重算(不信模型)。"""
    canned = json.dumps({"decisions": [], "action_items": [
        # owner 齐 due 齐,但模型瞎填 loose_end=true → BE 应改回 false
        {"chapter": 1, "task": "A", "owner": "Eng-B", "due": "周一", "from_decision": None,
         "source": "", "substance": "真金白银", "substance_reason": "", "evidence": _EV_AUTH,
         "loose_end": True},
        # owner 空,模型瞎填 loose_end=false → BE 应改回 true
        {"chapter": 2, "task": "B", "owner": "", "due": "周二", "from_decision": None,
         "source": "", "substance": "有条件兑现", "substance_reason": "", "evidence": _EV_PERF,
         "loose_end": False},
    ]}, ensure_ascii=False)
    out = _run(monkeypatch, conclusions_canned=canned)
    by_task = {a["task"]: a for a in out["action_items"]}
    assert by_task["A"]["loose_end"] is False
    assert by_task["B"]["loose_end"] is True


# ── 含金量判档 + 会议版叶子档名 ──────────────────────────────────────────────
def test_substance_meeting_leaf_name(monkeypatch):
    """含金量用会议三档,开环行动项判「空头表态」(不是公文「空头倡导」)。"""
    out = _run(monkeypatch)
    by_task = {a["task"]: a for a in out["action_items"]}
    assert by_task["写鉴权接口初版"]["substance"] == "真金白银"
    assert by_task["看性能优化"]["substance"] == "空头表态"


def test_substance_alias_gongwen_to_meeting(monkeypatch):
    """模型吐公文版「空头倡导」→ 归一到会议版「空头表态」(别名映射)。"""
    canned = json.dumps({"decisions": [], "action_items": [
        {"chapter": 1, "task": "X", "owner": "", "due": "", "from_decision": None,
         "source": "", "substance": "空头倡导", "substance_reason": "", "evidence": _EV_PERF},
    ]}, ensure_ascii=False)
    out = _run(monkeypatch, conclusions_canned=canned)
    assert out["action_items"][0]["substance"] == "空头表态"


def test_substance_unknown_falls_back(monkeypatch):
    """落不进三档 → 退「有条件兑现」(中性兜底)。"""
    canned = json.dumps({"decisions": [], "action_items": [
        {"chapter": 1, "task": "X", "owner": "Eng-B", "due": "周一", "from_decision": None,
         "source": "", "substance": "超级真", "substance_reason": "", "evidence": _EV_AUTH},
    ]}, ensure_ascii=False)
    out = _run(monkeypatch, conclusions_canned=canned)
    assert out["action_items"][0]["substance"] == "有条件兑现"


def test_coerce_meeting_substance_pure():
    for s in ms.MEETING_SUBSTANCE_LEVELS:
        assert ms._coerce_meeting_substance(s) == s
    assert ms._coerce_meeting_substance("空头倡导") == "空头表态"  # 公文别名
    assert ms._coerce_meeting_substance("瞎填") == "有条件兑现"
    assert ms._coerce_meeting_substance(None) == "有条件兑现"
    assert ms._coerce_meeting_substance("  真金白银 ") == "真金白银"  # 去空白


# ── owner/due 抽不到留空、绝不编 ─────────────────────────────────────────────
def test_empty_owner_due_kept_blank(monkeypatch):
    """owner/due 空就是空,不编一个人/时间(信号不是缺陷)。"""
    out = _run(monkeypatch)
    perf = next(a for a in out["action_items"] if a["task"] == "看性能优化")
    assert perf["owner"] == ""
    assert perf["due"] == ""


# ── form 门控 + N/A 区分 ────────────────────────────────────────────────────
def test_form_override_used(monkeypatch):
    """传了 form=纪要 就用它,不管模型在 head 里判的是逐字稿。"""
    out = _run(monkeypatch, form="纪要", head_canned=_head_payload("逐字稿"))
    assert out["form"] == "纪要"


def test_form_from_model_when_not_overridden(monkeypatch):
    """没传 form 用模型判的。"""
    out = _run(monkeypatch, head_canned=_head_payload("逐字稿"))
    assert out["form"] == "逐字稿"


def test_form_unknown_defaults_to_jiyao(monkeypatch):
    """模型给个非法 form → 退「纪要」(更保守)。"""
    out = _run(monkeypatch, head_canned=_head_payload("胡说形态"))
    assert out["form"] == "纪要"


def test_na_jiyao_absence_field(monkeypatch):
    """纪要:空着的「缺席/列席」标 not_applicable(本形态无此项),不当待核。"""
    out = _run(monkeypatch, form="纪要")
    absence = next(el for el in out["head"] if el["field"] == "缺席/列席")
    assert absence.get("not_applicable") is True


def test_na_zhuzi_scope_field(monkeypatch):
    """逐字稿:空着的「记录范围」标 not_applicable(逐字稿是流水没议题概述)。"""
    out = _run(monkeypatch, form="逐字稿")
    scope = next(el for el in out["head"] if el["field"] == "记录范围")
    assert scope.get("not_applicable") is True


def test_na_only_when_empty(monkeypatch):
    """该形态天生有的字段抽到了值,绝不标 N/A(主题/时间是两形态都该有的)。"""
    out = _run(monkeypatch, form="纪要")
    topic = next(el for el in out["head"] if el["field"] == "会议主题")
    assert "not_applicable" not in topic or topic["not_applicable"] is False


# ── from_decision 段内→全局映射 ─────────────────────────────────────────────
def test_from_decision_mapped_to_global(monkeypatch):
    """行动项 from_decision 指本段决议序号,全局重排后指向全局决议序号。"""
    out = _run(monkeypatch)
    auth = next(a for a in out["action_items"] if a["task"] == "写鉴权接口初版")
    # 只有 1 条决议,全局序号也是 1
    assert auth["from_decision"] == 1
    perf = next(a for a in out["action_items"] if a["task"] == "看性能优化")
    assert perf["from_decision"] is None  # 原本 null,保持


def test_from_decision_non_int_becomes_none(monkeypatch):
    """from_decision 给个非整数 → None(不瞎指)。"""
    canned = json.dumps({"decisions": [], "action_items": [
        {"chapter": 1, "task": "X", "owner": "Eng-B", "due": "周一",
         "from_decision": "第一条", "source": "", "substance": "真金白银",
         "substance_reason": "", "evidence": _EV_AUTH},
    ]}, ensure_ascii=False)
    out = _run(monkeypatch, conclusions_canned=canned)
    assert out["action_items"][0]["from_decision"] is None


# ── 台账排序 ─────────────────────────────────────────────────────────────────
def test_ledger_sort_loose_end_first(monkeypatch):
    """台账排序:loose_end(没人接/没时限的黑洞)置顶。"""
    out = _run(monkeypatch)
    # 性能(loose_end)应排在鉴权(闭环)前
    tasks = [a["task"] for a in out["action_items"]]
    assert tasks.index("看性能优化") < tasks.index("写鉴权接口初版")


# ── 我的行动项(owner 筛)──────────────────────────────────────────────────
def test_my_action_items_filter_by_owner(monkeypatch):
    """传 owner=Eng-B 只返 owner 命中 Eng-B 的(鉴权);性能 owner 空不返。"""
    out = _run(monkeypatch, owner="Eng-B")
    assert out["owner"] == "Eng-B"
    tasks = [a["task"] for a in out["action_items"]]
    assert tasks == ["写鉴权接口初版"]


def test_no_owner_returns_all(monkeypatch):
    """不传 owner 返全部(台账模式)。"""
    out = _run(monkeypatch)
    assert out["owner"] is None
    assert len(out["action_items"]) == 2


# ── evidence 核验 ────────────────────────────────────────────────────────────
def test_evidence_verified_when_in_original(monkeypatch):
    """canned evidence 都逐字命中合成原文 → verified=True。"""
    out = _run(monkeypatch)
    for a in out["action_items"]:
        assert a["verified"] is True
    for d in out["decisions"]:
        assert d["verified"] is True


def test_fabricated_evidence_marked_pending(monkeypatch):
    """evidence 原文里没有 → verified=False 标待核(绝不假装核过)。"""
    canned = json.dumps({"decisions": [], "action_items": [
        {"chapter": 1, "task": "X", "owner": "Eng-B", "due": "周一", "from_decision": None,
         "source": "", "substance": "真金白银", "substance_reason": "",
         "evidence": "Eng-B 说他要辞职了(原文根本没这句)。"},
    ]}, ensure_ascii=False)
    out = _run(monkeypatch, conclusions_canned=canned)
    assert out["action_items"][0]["verified"] is False


# ── 议而未决(第二炮)──────────────────────────────────────────────────────
def test_open_issue_fields_complete(monkeypatch):
    """议而未决每条字段齐全(含 BE 附的 verified/match_score)。"""
    out = _run(monkeypatch)
    assert len(out["open_issues"]) == 1
    for o in out["open_issues"]:
        for k in ("chapter", "issue", "raised_by", "why_open", "background",
                  "evidence", "verified", "match_score"):
            assert k in o, f"议而未决缺字段 {k}"
        assert o["why_open"] in ms.MEETING_OPEN_ISSUE_REASONS


def test_open_issue_extracted_content(monkeypatch):
    """议而未决抽到的内容对:议题/谁提的/为何悬着。"""
    out = _run(monkeypatch)
    oi = out["open_issues"][0]
    assert oi["chapter"] == 1  # 全局重排 1 起
    assert "数据库" in oi["issue"]
    assert oi["raised_by"] == "Eng-C"
    assert oi["why_open"] == "未拍板"


def test_open_issue_evidence_verified(monkeypatch):
    """议而未决的 evidence 逐字命中原文 → verified=True(同决议/行动项一套核验)。"""
    out = _run(monkeypatch)
    assert out["open_issues"][0]["verified"] is True


def test_open_issue_fabricated_evidence_pending(monkeypatch):
    """编的 evidence 原文里没有 → verified=False 标待核(绝不假装核过)。"""
    canned = json.dumps({"decisions": [], "action_items": [], "open_issues": [
        {"chapter": 1, "issue": "X", "raised_by": "", "why_open": "未拍板",
         "background": "", "evidence": "原文根本没有这句话编的。"},
    ]}, ensure_ascii=False)
    out = _run(monkeypatch, conclusions_canned=canned)
    assert out["open_issues"][0]["verified"] is False


def test_open_issue_raised_by_kept_blank(monkeypatch):
    """没点明谁提的就留空,绝不替它编一个人(同 owner 空逻辑)。"""
    canned = json.dumps({"decisions": [], "action_items": [], "open_issues": [
        {"chapter": 1, "issue": "预算谁出没说清", "raised_by": "", "why_open": "未拍板",
         "background": "", "evidence": _EV_OPEN},
    ]}, ensure_ascii=False)
    out = _run(monkeypatch, conclusions_canned=canned)
    assert out["open_issues"][0]["raised_by"] == ""


def test_open_issue_reason_alias_normalized(monkeypatch):
    """模型吐近义说法(如「下次会上定」)→ 归一到四档正名(待下次)。"""
    canned = json.dumps({"decisions": [], "action_items": [], "open_issues": [
        {"chapter": 1, "issue": "X", "raised_by": "", "why_open": "下次会上定",
         "background": "", "evidence": _EV_OPEN},
    ]}, ensure_ascii=False)
    out = _run(monkeypatch, conclusions_canned=canned)
    assert out["open_issues"][0]["why_open"] == "待下次"


def test_open_issue_reason_unknown_falls_back(monkeypatch):
    """落不进四档 → 退「未拍板」(最常见、最该追)。"""
    canned = json.dumps({"decisions": [], "action_items": [], "open_issues": [
        {"chapter": 1, "issue": "X", "raised_by": "", "why_open": "瞎填的原因",
         "background": "", "evidence": _EV_OPEN},
    ]}, ensure_ascii=False)
    out = _run(monkeypatch, conclusions_canned=canned)
    assert out["open_issues"][0]["why_open"] == "未拍板"


def test_open_issue_sorted_by_reason(monkeypatch):
    """议而未决排序:未拍板/没人接(会场内能追的黑洞)排前,待外部/待下次排后。"""
    canned = json.dumps({"decisions": [], "action_items": [], "open_issues": [
        {"chapter": 1, "issue": "待下次的", "raised_by": "", "why_open": "待下次",
         "background": "", "evidence": _EV_DECIDE},
        {"chapter": 2, "issue": "未拍板的", "raised_by": "", "why_open": "未拍板",
         "background": "", "evidence": _EV_PERF},
    ]}, ensure_ascii=False)
    out = _run(monkeypatch, conclusions_canned=canned)
    issues = [o["issue"] for o in out["open_issues"]]
    assert issues.index("未拍板的") < issues.index("待下次的")


def test_coerce_open_issue_reason_pure():
    for r in ms.MEETING_OPEN_ISSUE_REASONS:
        assert ms._coerce_open_issue_reason(r) == r
    assert ms._coerce_open_issue_reason("下次会上定") == "待下次"  # 别名
    assert ms._coerce_open_issue_reason("没人认领") == "没人接"  # 别名
    assert ms._coerce_open_issue_reason("瞎填") == "未拍板"
    assert ms._coerce_open_issue_reason(None) == "未拍板"
    assert ms._coerce_open_issue_reason("  待外部 ") == "待外部"  # 去空白


def test_coerce_open_issue_drops_no_chapter():
    """没序号 → 丢(摆不进会脉)。"""
    assert ms._coerce_open_issue({"issue": "X", "raised_by": "Y"}) is None
    assert ms._coerce_open_issue({"chapter": "一", "issue": "X"}) is None


def test_open_issue_salvaged_on_truncation(monkeypatch):
    """主解析失败时,从截断抢救也能捞回议而未决(同决议/行动项的截断兜底)。"""
    # 故意造个被截断的 JSON:open_issues 数组开着、最后一条对象闭合,主 loads 会失败。
    broken = (
        '{"decisions":[],"action_items":[],"open_issues":['
        '{"chapter":1,"issue":"数据库选型没定","raised_by":"Eng-C",'
        '"why_open":"未拍板","background":"","evidence":"' + _EV_OPEN + '"}'
    )  # 缺结尾的 ]} → 截断态
    out = _run(monkeypatch, conclusions_canned=broken)
    assert len(out["open_issues"]) == 1
    assert out["open_issues"][0]["raised_by"] == "Eng-C"


# ── prompt 接 codebook + 会议叶子档名 ───────────────────────────────────────
def test_prompt_carries_meeting_codebook():
    instr = ms._INSTR_CONCLUSIONS
    assert "空头表态" in instr  # 会议版叶子档名
    assert "空头倡导" not in instr  # 不漏公文档名进 prompt
    assert "拍板语" in instr  # 会议措辞刻度进来了
    assert "证据要摘长" in instr  # 锚错防护强调


def test_prompt_carries_open_issue_codebook():
    """prompt 把议而未决该抽什么 + 四档「为何悬着」都交代了。"""
    instr = ms._INSTR_CONCLUSIONS
    assert "open_issue" in instr  # 第三类抽取键
    assert "议而未决" in instr
    for reason in ms.MEETING_OPEN_ISSUE_REASONS:
        assert reason in instr, f"prompt 漏了为何悬着档:{reason}"


# ── parse / 异常兜底 ─────────────────────────────────────────────────────────
def test_strips_code_fence(monkeypatch):
    fenced = "```json\n" + _conclusions_payload() + "\n```"
    out = _run(monkeypatch, conclusions_canned=fenced)
    assert len(out["action_items"]) == 2


def test_unparseable_conclusions_empty(monkeypatch):
    """结论项解析不出 → 决议/行动项/议而未决全空,但 head 仍在(读过这份)。"""
    out = _run(monkeypatch, conclusions_canned="这根本不是 JSON")
    assert out["action_items"] == []
    assert out["decisions"] == []
    assert out["open_issues"] == []


def test_llm_exception_returns_skeleton(monkeypatch):
    """抽取全抛 → 头要素全留空待核骨架、结论项空,不崩。"""
    def _boom(*_a, **_kw):  # noqa: ANN002, ANN003, ANN202
        raise RuntimeError("provider 503")
    monkeypatch.setattr(ms, "invoke_client_cached", _boom)
    monkeypatch.setattr(_exhaustive, "invoke_client_cached", _boom)
    out = ms.action_ledger_from_meeting(
        chunks=_CHUNKS, llm_client=_FakeClient(),
        model="deepseek-v4-flash", full_text=_FULL_TEXT, max_workers=1,
    )
    assert out["action_items"] == []
    assert out["decisions"] == []
    assert out["open_issues"] == []
    assert len(out["head"]) == 6  # 骨架还在
    assert all(el["verified"] is False for el in out["head"])


# ── 纯件:coerce 决议/行动项 ────────────────────────────────────────────────
def test_coerce_action_drops_no_chapter():
    """没序号 → 丢(摆不进会脉)。"""
    assert ms._coerce_action({"task": "X", "owner": "Y"}) is None
    assert ms._coerce_action({"chapter": "一", "task": "X"}) is None


def test_coerce_action_does_not_set_loose_end():
    """_coerce_action 不收 loose_end(它在重排时纯计算,不在 coerce 层)。"""
    a = ms._coerce_action({"chapter": 1, "task": "X", "owner": "", "due": ""})
    assert a is not None
    assert "loose_end" not in a  # coerce 不管,_renumber 才算


def test_coerce_decision_drops_no_chapter():
    assert ms._coerce_decision({"decision": "X"}) is None
