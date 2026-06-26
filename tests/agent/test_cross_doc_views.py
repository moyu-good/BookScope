"""cross_doc_views 三个跨文件视图单测(1.6 红头文件 Phase 1)。

mock invoke_client_cached + 假 client,合成 2-3 份文脉 / cross_doc 结果(同 test_cross_doc /
test_chapter_spine_consistency 模式)。三视图各覆盖:
- 依据链网络 ``dependency_graph_from_cross_doc``:正路出节点 + 有向边 / 纯聚合不调 LLM /
  空·无边·None 返 None / (from,to,kind) 去重 / 机关枢纽节点。
- 政策演变 ``policy_evolution_from_spines``:正路按成文日期排 + 锚真实文件 / 锚不到真字号丢 /
  该文件没已核证据丢(锚不到原文) / 同文件去重 / 空数组返 [] / 空·解析失败·抛错返 None / 截断抢救。
- 上下级一致性 ``level_consistency_from_spines``:正路标走样 + 两侧锚原文 / 走样类型封闭集 /
  锚不到真字号丢 / 平级当上下级丢 / 任一侧证据空丢(双向守卫) / 全平级返 None(题材自适应) /
  都一致返 [] / 抛错返 None / 去代码围栏。
不跑真 LLM。
"""

from __future__ import annotations

import json

from bookscope.agent import cross_doc_views as cdv

# 关系边的 kind 来自 cross_doc 的封闭集(依据 / 落实 / 废止 / 修改 / 上下级)。
_REL_KINDS = {"依据", "落实", "废止", "修改", "上下级"}


# ── 合成文脉 / cross_doc 结果 ────────────────────────────────────────────────


def _head(num="", doc_type="", org="", date="", title=""):
    """造一份文脉的 head(只填测试关心的要素,其余按 doc_spine 形态补空待核)。"""
    fields = {
        "发文字号": num, "文种": doc_type, "发文机关": org, "主送机关": "",
        "抄送机关": "", "标题事由": title, "成文日期": date, "签发人": "",
    }
    return [
        {"field": k, "value": v, "evidence": "", "verified": bool(v), "match_score": 0.0}
        for k, v in fields.items()
    ]


def _clause(ch, matter="", evidence="", instr="信息告知", basis=""):
    return {
        "chapter": ch, "matter": matter, "instruction_type": instr,
        "actor": "", "deadline": "", "basis_ref": basis, "evidence": evidence,
        "verified": bool(evidence), "match_score": 1.0 if evidence else 0.0,
    }


# 三层一摞:省意见(上)→ 市方案(中)→ 县通知(下)。条款带已核 evidence(现取 snippet 用)。
_SPINES = [
    {
        "schema_version": "v1",
        "head": _head(num="省发〔2024〕1号", doc_type="意见", org="某省政府",
                      date="2024年1月1日", title="关于稳岗补贴的意见"),
        "clauses": [
            _clause(1, "稳岗补贴标准每人500元", evidence="对参保企业按每人500元发放稳岗补贴。"),
            _clause(2, "各市制定实施细则", evidence="各市可结合实际制定具体实施细则。"),
        ],
    },
    {
        "schema_version": "v1",
        "head": _head(num="市发〔2024〕5号", doc_type="通知", org="某省某市政府",
                      date="2024年3月1日", title="关于落实稳岗补贴的通知"),
        "clauses": [
            _clause(1, "稳岗补贴标准每人300元", evidence="本市稳岗补贴按每人300元发放。",
                    basis="省发〔2024〕1号"),
            _clause(2, "申报截止6月底", evidence="补贴申报截止2024年6月30日。"),
        ],
    },
    {
        "schema_version": "v1",
        "head": _head(num="县发〔2024〕9号", doc_type="通知", org="某省某县政府",
                      date="2024年5月1日", title="关于稳岗补贴申报的通知"),
        "clauses": [
            _clause(1, "据市通知组织申报", evidence="按市通知组织本县企业申报稳岗补贴。",
                    basis="市发〔2024〕5号"),
        ],
    },
]


class _FakeClient:
    def __init__(self, final_text=""):
        self._final = final_text

    def extract_final_text(self, resp):  # noqa: ANN001
        return resp if isinstance(resp, str) else self._final


def _patch(monkeypatch, text, *, raises=None):
    """patch cross_doc_views.invoke_client_cached 顺序返 text(可 list),或 raises 抛错。"""
    seq = text if isinstance(text, list) else [text]

    def _fake(*_a, **_k):
        if raises is not None:
            raise raises
        return seq.pop(0)

    monkeypatch.setattr(cdv, "invoke_client_cached", _fake)


# ════════════════════════════════════════════════════════════════════════════
# 视图一:依据链关联网(纯聚合,0 次 LLM)
# ════════════════════════════════════════════════════════════════════════════

_CROSS_DOC = {
    "relations": [
        {"from_doc": "市发〔2024〕5号", "to_doc": "省发〔2024〕1号", "kind": "依据",
         "chapter_anchor": 1, "note": "市方案依据省意见"},
        {"from_doc": "县发〔2024〕9号", "to_doc": "市发〔2024〕5号", "kind": "落实",
         "chapter_anchor": 1, "note": "县通知落实市方案"},
    ],
    "docs": [
        {"字号": "省发〔2024〕1号", "文种": "意见", "机关": "某省政府", "成文日期": "2024年1月1日"},
        {"字号": "市发〔2024〕5号", "文种": "通知", "机关": "某市政府", "成文日期": "2024年3月1日"},
        {"字号": "县发〔2024〕9号", "文种": "通知", "机关": "某县政府", "成文日期": "2024年5月1日"},
    ],
}


def test_dep_graph_no_llm_call(monkeypatch):
    """依据链网络纯聚合:就算 patch 了 LLM 也绝不调它(调了就抛,验 0 次 LLM)。"""

    def _boom(*_a, **_k):
        raise AssertionError("依据链网络不该调 LLM")

    monkeypatch.setattr(cdv, "invoke_client_cached", _boom)
    g = cdv.dependency_graph_from_cross_doc(_CROSS_DOC)
    assert g is not None  # 没抛 = 没调 LLM


def test_dep_graph_builds_nodes_and_directed_edges():
    """正路:文件节点带画像 + 有向边带 kind/anchor + 机关枢纽节点 + 发文隶属边。"""
    g = cdv.dependency_graph_from_cross_doc(_CROSS_DOC)
    nodes = {n["id"]: n for n in g["nodes"]}
    # 三个文件节点
    for num in ("省发〔2024〕1号", "市发〔2024〕5号", "县发〔2024〕9号"):
        assert nodes[num]["kind"] == "文件"
    assert nodes["省发〔2024〕1号"]["文种"] == "意见"
    assert nodes["省发〔2024〕1号"]["成文日期"] == "2024年1月1日"
    # 三个机关枢纽节点(每个机关辖一份文件)
    org_ids = {n["id"] for n in g["nodes"] if n["kind"] == "机关"}
    assert org_ids == {"机关:某省政府", "机关:某市政府", "机关:某县政府"}
    # 关系边有向、带 kind / chapter_anchor / note
    rel_edges = [e for e in g["edges"] if e["kind"] in _REL_KINDS]
    by_src = {e["source"]: e for e in rel_edges}
    assert by_src["市发〔2024〕5号"]["target"] == "省发〔2024〕1号"
    assert by_src["市发〔2024〕5号"]["kind"] == "依据"
    assert by_src["市发〔2024〕5号"]["chapter_anchor"] == 1
    assert by_src["县发〔2024〕9号"]["kind"] == "落实"
    # 发文隶属边:机关 → 文件
    fa = [e for e in g["edges"] if e["kind"] == "发文"]
    assert len(fa) == 3
    assert all(e["source"].startswith("机关:") for e in fa)


def test_dep_graph_dedup_from_to_kind():
    """(from,to,kind) 三元组重复 → 只留首条。"""
    cd = {
        "relations": [
            {"from_doc": "市发〔2024〕5号", "to_doc": "省发〔2024〕1号", "kind": "依据",
             "chapter_anchor": 1, "note": "首条"},
            {"from_doc": "市发〔2024〕5号", "to_doc": "省发〔2024〕1号", "kind": "依据",
             "chapter_anchor": 2, "note": "重复,丢"},
        ],
        "docs": _CROSS_DOC["docs"],
    }
    g = cdv.dependency_graph_from_cross_doc(cd)
    rel_edges = [e for e in g["edges"] if e["kind"] == "依据"]
    assert len(rel_edges) == 1
    assert rel_edges[0]["note"] == "首条"


def test_dep_graph_self_edge_dropped():
    """from == to 的自指边丢;若丢光所有边 → None。"""
    cd = {"relations": [{"from_doc": "市发〔2024〕5号", "to_doc": "市发〔2024〕5号",
                         "kind": "依据", "chapter_anchor": 1, "note": "自指"}],
          "docs": _CROSS_DOC["docs"]}
    assert cdv.dependency_graph_from_cross_doc(cd) is None


def test_dep_graph_none_and_empty_return_none():
    assert cdv.dependency_graph_from_cross_doc(None) is None
    assert cdv.dependency_graph_from_cross_doc({"relations": [], "docs": []}) is None
    assert cdv.dependency_graph_from_cross_doc({"docs": []}) is None


# ════════════════════════════════════════════════════════════════════════════
# 视图二:政策演变时间线
# ════════════════════════════════════════════════════════════════════════════


def _evolve(payload, *, spines=None, topic=None, **kw):
    return cdv.policy_evolution_from_spines(
        doc_spines=spines if spines is not None else _SPINES,
        llm_client=_FakeClient(),
        model="deepseek-v4-flash",
        topic=topic,
        **kw,
    )


def test_policy_success(monkeypatch):
    """正路:按成文日期升序排阶段、每阶段锚真实文件 + 取该文件已核证据当 snippet。"""
    payload = json.dumps({"stages": [
        {"order": 1, "doc": "省发〔2024〕1号", "change": "确立稳岗补贴每人500元"},
        {"order": 2, "doc": "市发〔2024〕5号", "change": "补贴降到每人300元"},
        {"order": 3, "doc": "县发〔2024〕9号", "change": "落实到县级申报"},
    ]}, ensure_ascii=False)
    _patch(monkeypatch, payload)
    out = _evolve(payload, topic="稳岗补贴")
    assert out is not None
    assert [s["order"] for s in out] == [1, 2, 3]
    assert [s["doc"] for s in out] == ["省发〔2024〕1号", "市发〔2024〕5号", "县发〔2024〕9号"]
    assert all(s["snippet"] for s in out)  # 每阶段都锚到了该文件已核证据
    assert all(s["verified"] is True for s in out)
    assert "500元" in out[0]["snippet"]  # 省份的已核证据


def test_policy_reorders_by_date(monkeypatch):
    """LLM 给乱序 → 按成文日期重排、重编 order。"""
    payload = json.dumps({"stages": [
        {"order": 1, "doc": "县发〔2024〕9号", "change": "晚"},
        {"order": 2, "doc": "省发〔2024〕1号", "change": "最早"},
        {"order": 3, "doc": "市发〔2024〕5号", "change": "中"},
    ]}, ensure_ascii=False)
    _patch(monkeypatch, payload)
    out = _evolve(payload)
    assert [s["doc"] for s in out] == ["省发〔2024〕1号", "市发〔2024〕5号", "县发〔2024〕9号"]
    assert [s["order"] for s in out] == [1, 2, 3]


def test_policy_fabricated_doc_dropped(monkeypatch):
    """doc 不是这摞文件真实字号(LLM 编的)→ 丢这阶段。"""
    payload = json.dumps({"stages": [
        {"order": 1, "doc": "省发〔2024〕1号", "change": "真"},
        {"order": 2, "doc": "国发〔2099〕99号", "change": "编的字号"},
    ]}, ensure_ascii=False)
    _patch(monkeypatch, payload)
    out = _evolve(payload)
    assert len(out) == 1
    assert out[0]["doc"] == "省发〔2024〕1号"


def test_policy_doc_without_evidence_dropped(monkeypatch):
    """该文件文脉里没有任何已核 evidence → 锚不到原文,丢这阶段(立身之本)。"""
    spines = [
        {"head": _head(num="甲发〔2024〕1号", org="某省", date="2024年1月1日"),
         "clauses": [_clause(1, "有证据", evidence="这是甲的已核原文。")]},
        {"head": _head(num="乙发〔2024〕2号", org="某市", date="2024年2月1日"),
         "clauses": [_clause(1, "没证据", evidence="")]},  # 全留空待核
    ]
    payload = json.dumps({"stages": [
        {"order": 1, "doc": "甲发〔2024〕1号", "change": "x"},
        {"order": 2, "doc": "乙发〔2024〕2号", "change": "y"},
    ]}, ensure_ascii=False)
    _patch(monkeypatch, payload)
    out = _evolve(payload, spines=spines)
    assert len(out) == 1
    assert out[0]["doc"] == "甲发〔2024〕1号"


def test_policy_dedup_same_doc(monkeypatch):
    """同一文件出现两次 → 只留首条。"""
    payload = json.dumps({"stages": [
        {"order": 1, "doc": "省发〔2024〕1号", "change": "首条"},
        {"order": 2, "doc": "省发〔2024〕1号", "change": "重复"},
    ]}, ensure_ascii=False)
    _patch(monkeypatch, payload)
    out = _evolve(payload)
    assert len(out) == 1
    assert out[0]["change"] == "首条"


def test_policy_empty_array_returns_empty(monkeypatch):
    """主题不在这摞文件(LLM 返空数组)→ [](区分'没演变'和'失败')。"""
    _patch(monkeypatch, json.dumps({"stages": []}))
    assert _evolve('{"stages": []}', topic="不存在的主题") == []


def test_policy_parse_failure_returns_none(monkeypatch):
    _patch(monkeypatch, "这不是 JSON")
    assert _evolve("x") is None


def test_policy_llm_raises_returns_none(monkeypatch):
    _patch(monkeypatch, "{}", raises=RuntimeError("boom"))
    assert _evolve("x") is None


def test_policy_no_numbered_doc_returns_none(monkeypatch):
    """一份有字号的文件都没有 → None,不调 LLM。"""
    spines = [{"head": _head(num="", org="某省"), "clauses": [_clause(1, "x")]}]
    # 不 patch:走到 LLM 就抛 AttributeError,说明没在前面返 None
    assert cdv.policy_evolution_from_spines(
        doc_spines=spines, llm_client=_FakeClient(), model="m",
    ) is None


def test_policy_salvages_truncated(monkeypatch):
    """reasoning 吃 token 致 JSON 截断 → 抢救已闭合的阶段。"""
    truncated = (
        '{"stages": ['
        '{"order": 1, "doc": "省发〔2024〕1号", "change": "完整"},'
        '{"order": 2, "doc": "市发〔2024〕5号", "chan'  # 截断
    )
    _patch(monkeypatch, truncated)
    out = _evolve(truncated)
    assert out is not None
    docs = {s["doc"] for s in out}
    assert "省发〔2024〕1号" in docs
    assert "市发〔2024〕5号" not in docs  # 截断的丢


def test_policy_strips_code_fence(monkeypatch):
    inner = json.dumps({"stages": [
        {"order": 1, "doc": "省发〔2024〕1号", "change": "x"},
    ]}, ensure_ascii=False)
    _patch(monkeypatch, "```json\n" + inner + "\n```")
    out = _evolve(inner)
    assert out is not None
    assert len(out) == 1


# ════════════════════════════════════════════════════════════════════════════
# 视图二·加一层:政策措辞 diff(逐字比)
# ════════════════════════════════════════════════════════════════════════════
#
# diff 的 before/after 必须逐字命中各自文件已核 evidence 池。_SPINES 里可用逐字原文:
#   省发〔2024〕1号 / 条款1:对参保企业按每人500元发放稳岗补贴。
#   省发〔2024〕1号 / 条款2:各市可结合实际制定具体实施细则。
#   市发〔2024〕5号 / 条款1:本市稳岗补贴按每人300元发放。
#   市发〔2024〕5号 / 条款2:补贴申报截止2024年6月30日。


def _diff(payload, *, spines=None, topic=None, **kw):
    return cdv.policy_wording_diff_from_spines(
        doc_spines=spines if spines is not None else _SPINES,
        llm_client=_FakeClient(),
        model="deepseek-v4-flash",
        topic=topic,
        **kw,
    )


def test_diff_success_verbatim(monkeypatch):
    """正路:before/after 都逐字命中各自文件已核证据 → 留;direction/来源都对。"""
    payload = json.dumps({"diffs": [{
        "topic_point": "补贴标准的约束力",
        "before": "对参保企业按每人500元发放稳岗补贴。",
        "before_doc": "省发〔2024〕1号",
        "after": "本市稳岗补贴按每人300元发放。",
        "after_doc": "市发〔2024〕5号",
        "direction": "收紧",
        "basis": "补贴从每人500元降到300元,标准收窄",
    }]}, ensure_ascii=False)
    _patch(monkeypatch, payload)
    out = _diff(payload, topic="补贴标准")
    assert out is not None
    assert len(out) == 1
    d = out[0]
    assert d["direction"] == "收紧"
    assert d["before_doc"] == "省发〔2024〕1号"
    assert d["after_doc"] == "市发〔2024〕5号"
    assert "500元" in d["before"]
    assert "300元" in d["after"]
    assert d["verified"] is True


def test_diff_升格_direction(monkeypatch):
    """升格(约束力升):before/after 逐字命中 → 留,direction=升格。"""
    payload = json.dumps({"diffs": [{
        "topic_point": "细则制定的约束力",
        "before": "各市可结合实际制定具体实施细则。",   # 省·条款2(倡导「可」)
        "before_doc": "省发〔2024〕1号",
        "after": "本市稳岗补贴按每人300元发放。",        # 市·条款1(确定执行)
        "after_doc": "市发〔2024〕5号",
        "direction": "升格",
        "basis": "从『可制定』变成明确执行,约束力上升",
    }]}, ensure_ascii=False)
    _patch(monkeypatch, payload)
    out = _diff(payload)
    assert len(out) == 1
    assert out[0]["direction"] == "升格"


def test_diff_松绑_direction(monkeypatch):
    """松绑(约束力降):逐字命中 → 留,direction=松绑。"""
    payload = json.dumps({"diffs": [{
        "topic_point": "申报口径",
        "before": "本市稳岗补贴按每人300元发放。",
        "before_doc": "市发〔2024〕5号",
        "after": "各市可结合实际制定具体实施细则。",
        "after_doc": "省发〔2024〕1号",
        "direction": "松绑",
        "basis": "从硬标准变成『可结合实际』,放宽了",
    }]}, ensure_ascii=False)
    # 注意:松绑这条 after 的成文日期(省1月)早于 before(市3月),只验 direction 落进封闭集 +
    # 逐字命中即可——日期序排序不影响留存。
    _patch(monkeypatch, payload)
    out = _diff(payload)
    assert len(out) == 1
    assert out[0]["direction"] == "松绑"


def test_diff_wording_mismatch_dropped(monkeypatch):
    """before/after 措辞对不上原文(LLM 改写/编的)→ 整条丢(立身之本)。"""
    payload = json.dumps({"diffs": [
        {  # before 是编的(原文里没有「鼓励企业稳岗」这句)
            "topic_point": "瞎编的提法",
            "before": "鼓励企业积极稳岗就业。",
            "before_doc": "省发〔2024〕1号",
            "after": "本市稳岗补贴按每人300元发放。",
            "after_doc": "市发〔2024〕5号",
            "direction": "升格",
            "basis": "编的",
        },
        {  # after 改写了原文(「每人300元」→「人均300元」,逐字对不上)
            "topic_point": "改写的措辞",
            "before": "对参保企业按每人500元发放稳岗补贴。",
            "before_doc": "省发〔2024〕1号",
            "after": "本市稳岗补贴按人均300元发放。",   # 改了字
            "after_doc": "市发〔2024〕5号",
            "direction": "收紧",
            "basis": "改写的",
        },
    ]}, ensure_ascii=False)
    _patch(monkeypatch, payload)
    assert _diff(payload) == []  # 两条措辞都对不上原文,全丢


def test_diff_paraphrase_not_enough(monkeypatch):
    """转述命中(n-gram 过阈值但非逐字)对 diff 不够——措辞变没变靠逐字,转述说明被改写,丢。"""
    payload = json.dumps({"diffs": [{
        "topic_point": "补贴标准",
        # 把原文「对参保企业按每人500元发放稳岗补贴。」删几个字 + 调序,n-gram 还高但非逐字子串
        "before": "参保企业每人500元发放稳岗补贴",
        "before_doc": "省发〔2024〕1号",
        "after": "本市稳岗补贴按每人300元发放。",
        "after_doc": "市发〔2024〕5号",
        "direction": "收紧",
        "basis": "降标准",
    }]}, ensure_ascii=False)
    _patch(monkeypatch, payload)
    assert _diff(payload) == []  # before 是转述非逐字,丢


def test_diff_新增_only_after(monkeypatch):
    """新增:旧版无此提法,只核 after 逐字命中(before 允许空)。"""
    payload = json.dumps({"diffs": [{
        "topic_point": "申报截止时间",
        "before": "",
        "before_doc": "",
        "after": "补贴申报截止2024年6月30日。",   # 市·条款2,逐字
        "after_doc": "市发〔2024〕5号",
        "direction": "新增",
        "basis": "旧版没有申报截止,新版加上了",
    }]}, ensure_ascii=False)
    _patch(monkeypatch, payload)
    out = _diff(payload)
    assert len(out) == 1
    assert out[0]["direction"] == "新增"
    assert "6月30日" in out[0]["after"]
    assert out[0]["before"] == ""


def test_diff_删除_only_before(monkeypatch):
    """删除:新版删掉此提法,只核 before 逐字命中(after 允许空)。"""
    payload = json.dumps({"diffs": [{
        "topic_point": "细则授权",
        "before": "各市可结合实际制定具体实施细则。",   # 省·条款2,逐字
        "before_doc": "省发〔2024〕1号",
        "after": "",
        "after_doc": "",
        "direction": "删除",
        "basis": "下一版删去了授权各市自定细则的提法",
    }]}, ensure_ascii=False)
    _patch(monkeypatch, payload)
    out = _diff(payload)
    assert len(out) == 1
    assert out[0]["direction"] == "删除"
    assert "实施细则" in out[0]["before"]
    assert out[0]["after"] == ""


def test_diff_新增_missing_after_dropped(monkeypatch):
    """新增但 after 措辞也对不上原文 → 丢(唯一该核的那侧坐实不了)。"""
    payload = json.dumps({"diffs": [{
        "topic_point": "编的新增",
        "before": "",
        "before_doc": "",
        "after": "新增了一项原文里没有的提法。",   # 编的
        "after_doc": "市发〔2024〕5号",
        "direction": "新增",
        "basis": "编的",
    }]}, ensure_ascii=False)
    _patch(monkeypatch, payload)
    assert _diff(payload) == []


def test_diff_direction_closed_set(monkeypatch):
    """direction 落不进封闭集 → 丢(不自造方向)。"""
    payload = json.dumps({"diffs": [
        {"topic_point": "a", "before": "对参保企业按每人500元发放稳岗补贴。",
         "before_doc": "省发〔2024〕1号", "after": "本市稳岗补贴按每人300元发放。",
         "after_doc": "市发〔2024〕5号", "direction": "收紧", "basis": "x"},
        {"topic_point": "b", "before": "各市可结合实际制定具体实施细则。",
         "before_doc": "省发〔2024〕1号", "after": "本市稳岗补贴按每人300元发放。",
         "after_doc": "市发〔2024〕5号", "direction": "微调了一下", "basis": "自造"},
    ]}, ensure_ascii=False)
    _patch(monkeypatch, payload)
    out = _diff(payload)
    assert len(out) == 1
    assert all(x["direction"] in cdv.POLICY_DIFF_DIRECTIONS for x in out)


def test_diff_fabricated_doc_dropped(monkeypatch):
    """before_doc / after_doc 不是真实 anchor(LLM 编的字号)→ 丢。"""
    payload = json.dumps({"diffs": [{
        "topic_point": "编字号",
        "before": "对参保企业按每人500元发放稳岗补贴。",
        "before_doc": "国发〔2099〕99号",   # 编的
        "after": "本市稳岗补贴按每人300元发放。",
        "after_doc": "市发〔2024〕5号",
        "direction": "收紧",
        "basis": "x",
    }]}, ensure_ascii=False)
    _patch(monkeypatch, payload)
    assert _diff(payload) == []


def test_diff_same_doc_change_dropped(monkeypatch):
    """改了措辞类(非新增/删除)before/after 来自同一文件 → 不算跨文件演变,丢。"""
    payload = json.dumps({"diffs": [{
        "topic_point": "同文件内",
        "before": "对参保企业按每人500元发放稳岗补贴。",
        "before_doc": "省发〔2024〕1号",
        "after": "各市可结合实际制定具体实施细则。",
        "after_doc": "省发〔2024〕1号",   # 同一份
        "direction": "转向",
        "basis": "x",
    }]}, ensure_ascii=False)
    _patch(monkeypatch, payload)
    assert _diff(payload) == []


def test_diff_dedup(monkeypatch):
    """同 (topic_point, before, after) 重复 → 只留一条。"""
    one = {
        "topic_point": "补贴标准",
        "before": "对参保企业按每人500元发放稳岗补贴。",
        "before_doc": "省发〔2024〕1号",
        "after": "本市稳岗补贴按每人300元发放。",
        "after_doc": "市发〔2024〕5号",
        "direction": "收紧",
        "basis": "x",
    }
    payload = json.dumps({"diffs": [one, dict(one, basis="重复")]}, ensure_ascii=False)
    _patch(monkeypatch, payload)
    out = _diff(payload)
    assert len(out) == 1


def test_diff_empty_array_returns_empty(monkeypatch):
    """这摞文件没措辞变化(LLM 返空数组)→ [](区分'没变化'和'失败')。"""
    _patch(monkeypatch, json.dumps({"diffs": []}))
    assert _diff('{"diffs": []}') == []


def test_diff_parse_failure_returns_none(monkeypatch):
    _patch(monkeypatch, "这不是 JSON")
    assert _diff("x") is None


def test_diff_llm_raises_returns_none(monkeypatch):
    _patch(monkeypatch, "{}", raises=RuntimeError("boom"))
    assert _diff("x") is None


def test_diff_fewer_than_two_docs_returns_none(monkeypatch):
    """少于两份有 anchor 的文件 → 跨文件比无从谈起 → None,不调 LLM。"""
    spines = [{"head": _head(num="省发〔2024〕1号", org="某省", date="2024年1月1日"),
               "clauses": [_clause(1, "x", evidence="原文一句。")]}]
    # 不 patch:走到 LLM 就抛 AttributeError,说明在前面返了 None
    assert cdv.policy_wording_diff_from_spines(
        doc_spines=spines, llm_client=_FakeClient(), model="m",
    ) is None


def test_diff_salvages_truncated(monkeypatch):
    """reasoning 吃 token 致 JSON 截断 → 抢救已闭合的 diff。"""
    truncated = (
        '{"diffs": ['
        '{"topic_point": "补贴标准", '
        '"before": "对参保企业按每人500元发放稳岗补贴。", "before_doc": "省发〔2024〕1号", '
        '"after": "本市稳岗补贴按每人300元发放。", "after_doc": "市发〔2024〕5号", '
        '"direction": "收紧", "basis": "降标准"},'
        '{"topic_point": "截", "before": "补贴申报截'  # 截断
    )
    _patch(monkeypatch, truncated)
    out = _diff(truncated)
    assert out is not None
    assert len(out) == 1  # 完整那条留,截断那条丢
    assert out[0]["topic_point"] == "补贴标准"


def test_diff_strips_code_fence(monkeypatch):
    inner = json.dumps({"diffs": [{
        "topic_point": "补贴标准",
        "before": "对参保企业按每人500元发放稳岗补贴。",
        "before_doc": "省发〔2024〕1号",
        "after": "本市稳岗补贴按每人300元发放。",
        "after_doc": "市发〔2024〕5号",
        "direction": "收紧", "basis": "x",
    }]}, ensure_ascii=False)
    _patch(monkeypatch, "```json\n" + inner + "\n```")
    out = _diff(inner)
    assert out is not None
    assert len(out) == 1


# ════════════════════════════════════════════════════════════════════════════
# 视图三:上下级一致性核查
# ════════════════════════════════════════════════════════════════════════════


def _level(payload, *, spines=None, **kw):
    return cdv.level_consistency_from_spines(
        doc_spines=spines if spines is not None else _SPINES,
        llm_client=_FakeClient(),
        model="deepseek-v4-flash",
        **kw,
    )


# 真走样:省定每人500元,市落成每人300元(走样)。
_DEVIATION = json.dumps({"deviations": [{
    "topic": "稳岗补贴标准", "detail": "省定500元市落成300元", "deviation": "走样",
    "upper": "省发〔2024〕1号", "lower": "市发〔2024〕5号",
    "upper_clause": 1, "lower_clause": 1,
}]}, ensure_ascii=False)


def test_level_success(monkeypatch):
    """正路:标出走样、两侧锚到各自文件已核原文 + 条款。"""
    _patch(monkeypatch, _DEVIATION)
    out = _level(_DEVIATION)
    assert out is not None
    assert len(out) == 1
    d = out[0]
    assert d["deviation"] == "走样"
    assert d["upper"]["doc"] == "省发〔2024〕1号"
    assert d["lower"]["doc"] == "市发〔2024〕5号"
    assert "500元" in d["upper"]["snippet"]  # 省的已核证据
    assert "300元" in d["lower"]["snippet"]  # 市的已核证据
    assert d["upper"]["clause"] == 1
    assert d["lower"]["clause"] == 1
    assert d["upper"]["verified"] is True and d["lower"]["verified"] is True


def test_level_deviation_type_closed_set(monkeypatch):
    """deviation 落不进封闭集 → 丢这条(不自造走样类型)。"""
    payload = json.dumps({"deviations": [
        {"topic": "a", "detail": "x", "deviation": "走样",
         "upper": "省发〔2024〕1号", "lower": "市发〔2024〕5号",
         "upper_clause": 1, "lower_clause": 1},
        {"topic": "b", "detail": "y", "deviation": "稍微不太一样",  # 自造
         "upper": "省发〔2024〕1号", "lower": "县发〔2024〕9号",
         "upper_clause": 1, "lower_clause": 1},
    ]}, ensure_ascii=False)
    _patch(monkeypatch, payload)
    out = _level(payload)
    assert len(out) == 1
    assert all(x["deviation"] in cdv.DEVIATION_TYPES for x in out)


def test_level_fabricated_doc_dropped(monkeypatch):
    """upper / lower 不是真实字号 → 丢。"""
    payload = json.dumps({"deviations": [{
        "topic": "编的", "detail": "x", "deviation": "走样",
        "upper": "国发〔2099〕99号", "lower": "市发〔2024〕5号",
        "upper_clause": 1, "lower_clause": 1,
    }]}, ensure_ascii=False)
    _patch(monkeypatch, payload)
    assert _level(payload) == []


def test_level_must_be_upper_over_lower(monkeypatch):
    """upper 层级必须严格高于 lower:把下位当上位(方向反了)→ 丢。"""
    payload = json.dumps({"deviations": [{
        "topic": "方向反了", "detail": "x", "deviation": "走样",
        "upper": "市发〔2024〕5号", "lower": "省发〔2024〕1号",  # 市当 upper、省当 lower
        "upper_clause": 1, "lower_clause": 1,
    }]}, ensure_ascii=False)
    _patch(monkeypatch, payload)
    assert _level(payload) == []  # 市(3)不比省(2)靠上,丢


def test_level_either_side_no_evidence_drops(monkeypatch):
    """双向守卫:任一侧锚不到已核原文 → 整条丢(不 cry wolf)。"""
    spines = [
        {"head": _head(num="省发〔2024〕1号", org="某省政府", date="2024年1月1日"),
         "clauses": [_clause(1, "省有证据", evidence="省定每人500元。")]},
        {"head": _head(num="市发〔2024〕5号", org="某省某市政府", date="2024年3月1日"),
         "clauses": [_clause(1, "市没证据", evidence="")]},  # 留空待核
    ]
    payload = json.dumps({"deviations": [{
        "topic": "补贴标准", "detail": "x", "deviation": "走样",
        "upper": "省发〔2024〕1号", "lower": "市发〔2024〕5号",
        "upper_clause": 1, "lower_clause": 1,
    }]}, ensure_ascii=False)
    _patch(monkeypatch, payload)
    assert _level(payload, spines=spines) == []  # 市侧坐实不了,整条丢


def test_level_all_same_level_returns_none(monkeypatch):
    """题材自适应:一摞全平级(都是省级)→ 没上下级落差 → None,不硬造。"""
    spines = [
        {"head": _head(num="甲省发〔2024〕1号", org="甲省政府", date="2024年1月1日"),
         "clauses": [_clause(1, "x", evidence="甲省原文。")]},
        {"head": _head(num="乙省发〔2024〕2号", org="乙省政府", date="2024年2月1日"),
         "clauses": [_clause(1, "y", evidence="乙省原文。")]},
    ]
    # 不 patch:走到 LLM 就抛,说明没在 _has_hierarchy 闸前返 None
    assert cdv.level_consistency_from_spines(
        doc_spines=spines, llm_client=_FakeClient(), model="m",
    ) is None


def test_level_single_doc_returns_none():
    """单文件 → 没上下级可查 → None。"""
    spines = [{"head": _head(num="省发〔2024〕1号", org="某省政府"),
               "clauses": [_clause(1, "x", evidence="原文。")]}]
    assert cdv.level_consistency_from_spines(
        doc_spines=spines, llm_client=_FakeClient(), model="m",
    ) is None


def test_level_anchors_doc_without_number_by_title(monkeypatch):
    """没字号的地方法规(广东条例)靠标题进上下级一致性,层级落差照样判得出。

    营商环境链真实形态:722 条例(国务院,层级 1,有字号);广东条例(省人大常委会,层级 2,没
    字号、只有标题)。早先只认字号 → 广东条例整个进不来 → 凑不出 1/2 落差 → 视图返 None。
    """
    spines = [
        {"head": _head(num="国务院令第722号", doc_type="条例", org="国务院",
                       date="2019年10月22日", title="优化营商环境条例"),
         "clauses": [_clause(1, "全国通用规则", evidence="政府应当依法保护市场主体。")]},
        {"head": _head(num="", doc_type="条例", org="广东省人民代表大会常务委员会",
                       date="2020年7月1日", title="广东省优化营商环境条例"),
         "clauses": [_clause(1, "地方细化", evidence="本省加设备案前置审批一项。")]},
    ]
    # 模型用每份的 id 当 upper/lower:722 有字号 → id 是字号;广东没字号 → id 是标题。
    payload = json.dumps({"deviations": [{
        "topic": "备案审批", "detail": "省条例加设了上位没有的前置审批", "deviation": "加码",
        "upper": "国务院令第722号", "lower": "广东省优化营商环境条例",
        "upper_clause": 1, "lower_clause": 1,
    }]}, ensure_ascii=False)
    _patch(monkeypatch, payload)
    out = cdv.level_consistency_from_spines(
        doc_spines=spines, llm_client=_FakeClient(), model="m",
    )
    assert out is not None  # 层级落差判出来了(没因广东条例缺字号而塌)
    assert len(out) == 1
    assert out[0]["upper"]["doc"] == "国务院令第722号"            # 722 靠字号 anchor
    assert out[0]["lower"]["doc"] == "广东省优化营商环境条例"     # 广东靠标题 anchor
    assert out[0]["deviation"] == "加码"


def test_level_deviation_types_include_dichu():
    """封闭集补了立法法本名「抵触」(真正的违法标签)。"""
    assert "抵触" in cdv.DEVIATION_TYPES
    for t in ("抵触", "走样", "加码", "漏落实"):
        assert t in cdv.DEVIATION_TYPES


def test_level_accepts_dichu_deviation(monkeypatch):
    """模型用立法法术语「抵触」标走样 → 落进封闭集、不被滤掉。"""
    payload = json.dumps({"deviations": [{
        "topic": "补贴标准", "detail": "下位违反上位强制规定", "deviation": "抵触",
        "upper": "省发〔2024〕1号", "lower": "市发〔2024〕5号",
        "upper_clause": 1, "lower_clause": 1,
    }]}, ensure_ascii=False)
    _patch(monkeypatch, payload)
    out = _level(payload)
    assert len(out) == 1
    assert out[0]["deviation"] == "抵触"


def test_org_variation_authority_subjects():
    """变通权主体认得出:民族自治地方 / 经济特区 → True;一般省市政府 → False。"""
    assert cdv._has_variation_authority("内蒙古自治区人民代表大会常务委员会") is True
    assert cdv._has_variation_authority("延边朝鲜族自治州人民政府") is True
    assert cdv._has_variation_authority("某某自治县人民政府") is True
    assert cdv._has_variation_authority("某民族乡人民政府") is True
    assert cdv._has_variation_authority("深圳经济特区") is True
    assert cdv._has_variation_authority("某省政府") is False
    assert cdv._has_variation_authority("某省某市政府") is False
    assert cdv._has_variation_authority("") is False


def test_org_level_autonomous_subjects_keep_level():
    """变通权主体的层级照样判得出(自治州→3 / 自治县→4 / 自治区→2)。"""
    assert cdv._org_level("内蒙古自治区人大常委会") == 2
    assert cdv._org_level("延边朝鲜族自治州政府") == 3
    assert cdv._org_level("某自治县政府") == 4
    assert cdv._org_level("某省政府") == 2


def test_level_digest_carries_variation_flag():
    """收清单时把「变通权」标进 digest(喂给 LLM 做抵触/变通区分用)。"""
    spines = [
        {"head": _head(num="国发〔2024〕1号", doc_type="决定", org="国务院",
                       date="2024年1月1日", title="全国统一规则"),
         "clauses": [_clause(1, "x", evidence="国务院定的全国规则。")]},
        {"head": _head(num="", doc_type="单行条例", org="某某自治县人民代表大会",
                       date="2024年3月1日", title="某自治县变通规定"),
         "clauses": [_clause(1, "y", evidence="本自治县据自治权变通如下。")]},
    ]
    digest, _nums, _lv, _ev = cdv._collect_level_inventory(spines)
    by_org = {d["发文机关"]: d for d in digest}
    assert by_org["国务院"]["变通权"] is False
    assert by_org["某某自治县人民代表大会"]["变通权"] is True


def test_level_consistent_returns_empty(monkeypatch):
    """都一致(LLM 返空数组)→ [] 而非 None(区分'都对得上'和'失败')。"""
    _patch(monkeypatch, json.dumps({"deviations": []}))
    assert _level('{"deviations": []}') == []


def test_level_dedup_by_topic(monkeypatch):
    """同 topic 重复 → 只留一条。"""
    payload = json.dumps({"deviations": [
        {"topic": "补贴标准", "detail": "x", "deviation": "走样",
         "upper": "省发〔2024〕1号", "lower": "市发〔2024〕5号",
         "upper_clause": 1, "lower_clause": 1},
        {"topic": "补贴标准", "detail": "重复", "deviation": "加码",
         "upper": "省发〔2024〕1号", "lower": "县发〔2024〕9号",
         "upper_clause": 1, "lower_clause": 1},
    ]}, ensure_ascii=False)
    _patch(monkeypatch, payload)
    out = _level(payload)
    assert len(out) == 1


def test_level_parse_failure_returns_none(monkeypatch):
    _patch(monkeypatch, "这不是 JSON")
    assert _level("x") is None


def test_level_llm_raises_returns_none(monkeypatch):
    _patch(monkeypatch, "{}", raises=RuntimeError("boom"))
    assert _level("x") is None


def test_level_strips_code_fence(monkeypatch):
    _patch(monkeypatch, "```json\n" + _DEVIATION + "\n```")
    out = _level(_DEVIATION)
    assert out is not None
    assert len(out) == 1


# ── 上下级一致性·博弈姿态(posture)维 ───────────────────────────────────────


def test_level_carries_posture_when_in_set(monkeypatch):
    """冲突带 posture 且落进封闭集 → 挂上 posture(研判维),冲突结构其余照旧。"""
    payload = json.dumps({"deviations": [{
        "topic": "稳岗补贴标准", "detail": "省定500元市落成300元", "deviation": "走样",
        "upper": "省发〔2024〕1号", "lower": "市发〔2024〕5号",
        "upper_clause": 1, "lower_clause": 1, "posture": "打折扣",
    }]}, ensure_ascii=False)
    _patch(monkeypatch, payload)
    out = _level(payload)
    assert len(out) == 1
    assert out[0]["posture"] == "打折扣"
    # 现有结构一个不动(向后兼容)
    assert out[0]["deviation"] == "走样"
    assert "500元" in out[0]["upper"]["snippet"]


def test_level_posture_加码(monkeypatch):
    """加码姿态:落进封闭集 → 挂上。"""
    payload = json.dumps({"deviations": [{
        "topic": "补贴标准", "detail": "下位标准高于上位", "deviation": "加码",
        "upper": "省发〔2024〕1号", "lower": "市发〔2024〕5号",
        "upper_clause": 1, "lower_clause": 1, "posture": "层层加码",
    }]}, ensure_ascii=False)
    _patch(monkeypatch, payload)
    out = _level(payload)
    assert len(out) == 1
    assert out[0]["posture"] == "层层加码"


def test_level_invalid_posture_dropped_conflict_kept(monkeypatch):
    """posture 落不进封闭集 → 不挂 posture,但冲突本身照常保留(posture 是可选维,不当 gate)。"""
    payload = json.dumps({"deviations": [{
        "topic": "补贴标准", "detail": "省定500元市落成300元", "deviation": "走样",
        "upper": "省发〔2024〕1号", "lower": "市发〔2024〕5号",
        "upper_clause": 1, "lower_clause": 1, "posture": "随便编个姿态",
    }]}, ensure_ascii=False)
    _patch(monkeypatch, payload)
    out = _level(payload)
    assert len(out) == 1               # 冲突没被 posture 拖掉
    assert "posture" not in out[0]     # 编的姿态不挂


def test_level_no_posture_field_backward_compat(monkeypatch):
    """模型没给 posture(老形态)→ 冲突照常,没有 posture 键(向后兼容)。"""
    _patch(monkeypatch, _DEVIATION)    # _DEVIATION 不带 posture
    out = _level(_DEVIATION)
    assert len(out) == 1
    assert "posture" not in out[0]


# ════════════════════════════════════════════════════════════════════════════
# 视图一·加一层:依据链博弈姿态(posture)
# ════════════════════════════════════════════════════════════════════════════
#
# posture 的 from/to 是「下位→上位」(依据 / 落实边方向)。_CROSS_DOC 里的依据 / 落实边:
#   市发〔2024〕5号 --依据--> 省发〔2024〕1号
#   县发〔2024〕9号 --落实--> 市发〔2024〕5号
# 两端文件在 _SPINES 里都有已核 evidence(现取 from/to snippet 用)。


def _posture(payload, *, cross=None, spines=None, **kw):
    return cdv.dependency_postures_from_spines(
        cross_doc_result=cross if cross is not None else _CROSS_DOC,
        doc_spines=spines if spines is not None else _SPINES,
        llm_client=_FakeClient(),
        model="deepseek-v4-flash",
        **kw,
    )


def test_posture_success_落实(monkeypatch):
    """正路:忠实落实——对回真实依据边、两侧锚到各自已核原文、posture 落封闭集。"""
    payload = json.dumps({"postures": [{
        "from_doc": "市发〔2024〕5号", "to_doc": "省发〔2024〕1号",
        "posture": "忠实落实", "from_clause": 1, "to_clause": 1,
        "basis": "市照省的稳岗补贴口径落实",
    }]}, ensure_ascii=False)
    _patch(monkeypatch, payload)
    out = _posture(payload)
    assert out is not None
    assert len(out) == 1
    p = out[0]
    assert p["posture"] == "忠实落实"
    assert p["from_doc"] == "市发〔2024〕5号"
    assert p["to_doc"] == "省发〔2024〕1号"
    assert "300元" in p["from_snippet"]   # 下位(市)已核原文
    assert "500元" in p["to_snippet"]     # 上位(省)已核原文
    assert p["verified"] is True


def test_posture_加码(monkeypatch):
    """层层加码:落进封闭集、对回真实落实边 → 留。"""
    payload = json.dumps({"postures": [{
        "from_doc": "县发〔2024〕9号", "to_doc": "市发〔2024〕5号",
        "posture": "层层加码", "from_clause": 1, "to_clause": 1,
        "basis": "县把市的要求加严",
    }]}, ensure_ascii=False)
    _patch(monkeypatch, payload)
    out = _posture(payload)
    assert len(out) == 1
    assert out[0]["posture"] == "层层加码"


def test_posture_打折扣(monkeypatch):
    """打折扣:落进封闭集 → 留。"""
    payload = json.dumps({"postures": [{
        "from_doc": "市发〔2024〕5号", "to_doc": "省发〔2024〕1号",
        "posture": "打折扣", "from_clause": 1, "to_clause": 1,
        "basis": "省定500元,市落成300元——打了折",
    }]}, ensure_ascii=False)
    _patch(monkeypatch, payload)
    out = _posture(payload)
    assert len(out) == 1
    assert out[0]["posture"] == "打折扣"
    assert all(x["posture"] in cdv.POSTURE_TYPES for x in out)


def test_posture_invalid_dropped(monkeypatch):
    """posture 落不进封闭集 → 丢这条(不替用户硬断姿态)。"""
    payload = json.dumps({"postures": [
        {"from_doc": "市发〔2024〕5号", "to_doc": "省发〔2024〕1号",
         "posture": "忠实落实", "from_clause": 1, "to_clause": 1, "basis": "真"},
        {"from_doc": "县发〔2024〕9号", "to_doc": "市发〔2024〕5号",
         "posture": "瞎编的姿态", "from_clause": 1, "to_clause": 1, "basis": "编"},
    ]}, ensure_ascii=False)
    _patch(monkeypatch, payload)
    out = _posture(payload)
    assert len(out) == 1
    assert out[0]["posture"] == "忠实落实"


def test_posture_no_evidence_dropped(monkeypatch):
    """引发姿态的原文对照锚不到(某侧文件没已核证据)→ 丢这条(双向守卫,无据不出)。"""
    spines = [
        {"head": _head(num="甲发〔2024〕1号", org="某省政府", date="2024年1月1日"),
         "clauses": [_clause(1, "上位有证据", evidence="省定每人500元。")]},
        {"head": _head(num="乙发〔2024〕2号", org="某省某市政府", date="2024年3月1日"),
         "clauses": [_clause(1, "下位没证据", evidence="")]},  # 留空待核
    ]
    cross = {
        "relations": [{"from_doc": "乙发〔2024〕2号", "to_doc": "甲发〔2024〕1号",
                       "kind": "依据", "chapter_anchor": 1, "note": "乙依据甲"}],
        "docs": [{"字号": "甲发〔2024〕1号", "文种": "意见", "机关": "某省政府",
                  "成文日期": "2024年1月1日"},
                 {"字号": "乙发〔2024〕2号", "文种": "通知", "机关": "某省某市政府",
                  "成文日期": "2024年3月1日"}],
    }
    payload = json.dumps({"postures": [{
        "from_doc": "乙发〔2024〕2号", "to_doc": "甲发〔2024〕1号",
        "posture": "打折扣", "from_clause": 1, "to_clause": 1, "basis": "x",
    }]}, ensure_ascii=False)
    _patch(monkeypatch, payload)
    assert _posture(payload, cross=cross, spines=spines) == []  # 下位锚不到原文,丢


def test_posture_fabricated_edge_dropped(monkeypatch):
    """posture 对不回真实的依据 / 落实边(LLM 编的边)→ 丢。"""
    payload = json.dumps({"postures": [{
        # 省→县 并不存在这条依据 / 落实边(_CROSS_DOC 里没有)
        "from_doc": "省发〔2024〕1号", "to_doc": "县发〔2024〕9号",
        "posture": "忠实落实", "from_clause": 1, "to_clause": 1, "basis": "编的边",
    }]}, ensure_ascii=False)
    _patch(monkeypatch, payload)
    assert _posture(payload) == []


def test_posture_no_dep_edges_returns_none(monkeypatch):
    """没有任何依据 / 落实边(只有废止 / 发文等)→ None,不调 LLM。"""
    cross = {
        "relations": [{"from_doc": "市发〔2024〕5号", "to_doc": "省发〔2024〕1号",
                       "kind": "废止", "chapter_anchor": 1, "note": "市废省"}],
        "docs": _CROSS_DOC["docs"],
    }
    # 不 patch:走到 LLM 就抛,说明在前面返了 None
    assert cdv.dependency_postures_from_spines(
        cross_doc_result=cross, doc_spines=_SPINES,
        llm_client=_FakeClient(), model="m",
    ) is None


def test_posture_dedup_one_per_edge(monkeypatch):
    """同一条边给了两个姿态 → 只留首个。"""
    payload = json.dumps({"postures": [
        {"from_doc": "市发〔2024〕5号", "to_doc": "省发〔2024〕1号",
         "posture": "忠实落实", "from_clause": 1, "to_clause": 1, "basis": "首个"},
        {"from_doc": "市发〔2024〕5号", "to_doc": "省发〔2024〕1号",
         "posture": "打折扣", "from_clause": 1, "to_clause": 1, "basis": "重复"},
    ]}, ensure_ascii=False)
    _patch(monkeypatch, payload)
    out = _posture(payload)
    assert len(out) == 1
    assert out[0]["posture"] == "忠实落实"


def test_posture_empty_array_returns_empty(monkeypatch):
    """有依据 / 落实边但 LLM 一个姿态没判出 → [](区分'没判出'和'失败')。"""
    _patch(monkeypatch, json.dumps({"postures": []}))
    assert _posture('{"postures": []}') == []


def test_posture_parse_failure_returns_none(monkeypatch):
    _patch(monkeypatch, "这不是 JSON")
    assert _posture("x") is None


def test_posture_llm_raises_returns_none(monkeypatch):
    _patch(monkeypatch, "{}", raises=RuntimeError("boom"))
    assert _posture("x") is None


def test_posture_salvages_truncated(monkeypatch):
    """reasoning 吃 token 致 JSON 截断 → 抢救已闭合的姿态。"""
    truncated = (
        '{"postures": ['
        '{"from_doc": "市发〔2024〕5号", "to_doc": "省发〔2024〕1号", '
        '"posture": "忠实落实", "from_clause": 1, "to_clause": 1, "basis": "完整"},'
        '{"from_doc": "县发〔2024〕9号", "to_doc": "市发〔2024〕5号", "post'  # 截断
    )
    _patch(monkeypatch, truncated)
    out = _posture(truncated)
    assert out is not None
    assert len(out) == 1  # 完整那条留,截断那条丢
    assert out[0]["from_doc"] == "市发〔2024〕5号"


def test_posture_strips_code_fence(monkeypatch):
    inner = json.dumps({"postures": [{
        "from_doc": "市发〔2024〕5号", "to_doc": "省发〔2024〕1号",
        "posture": "忠实落实", "from_clause": 1, "to_clause": 1, "basis": "x",
    }]}, ensure_ascii=False)
    _patch(monkeypatch, "```json\n" + inner + "\n```")
    out = _posture(inner)
    assert out is not None
    assert len(out) == 1


# ── attach_postures_to_edges(纯合并,把姿态贴回星图边) ──────────────────────


def test_attach_postures_to_matching_edge():
    """姿态按 (source,target) 贴到匹配的星图边上;没匹配的边不挂。"""
    graph = cdv.dependency_graph_from_cross_doc(_CROSS_DOC)
    postures = [{
        "from_doc": "市发〔2024〕5号", "to_doc": "省发〔2024〕1号",
        "posture": "打折扣", "from_clause": 1, "to_clause": 1,
        "from_snippet": "本市稳岗补贴按每人300元发放。",
        "to_snippet": "对参保企业按每人500元发放稳岗补贴。",
        "basis": "省500市300打了折",
    }]
    out = cdv.attach_postures_to_edges(graph, postures)
    # 找那条被贴的依据边
    hit = [e for e in out["edges"]
           if e["source"] == "市发〔2024〕5号" and e["target"] == "省发〔2024〕1号"]
    assert len(hit) == 1
    assert hit[0]["posture"]["label"] == "打折扣"
    assert "500元" in hit[0]["posture"]["to_snippet"]
    # 其它边没有 posture 键(只贴匹配的)
    others = [e for e in out["edges"]
              if not (e["source"] == "市发〔2024〕5号" and e["target"] == "省发〔2024〕1号")]
    assert all("posture" not in e for e in others)


def test_attach_postures_none_graph_or_empty():
    """graph 为 None / postures 空 → 原样返(没姿态可贴,不炸)。"""
    assert cdv.attach_postures_to_edges(None, []) is None
    g = cdv.dependency_graph_from_cross_doc(_CROSS_DOC)
    same = cdv.attach_postures_to_edges(g, [])
    assert same is g
    assert all("posture" not in e for e in same["edges"])


def test_posture_types_closed_set():
    """封闭集就是这四类(忠实落实 / 层层加码 / 打折扣 / 创新先行)。"""
    assert set(cdv.POSTURE_TYPES) == {"忠实落实", "层层加码", "打折扣", "创新先行"}
    assert cdv.coerce_posture("打折扣") == "打折扣"
    assert cdv.coerce_posture("瞎编") is None
    assert cdv.coerce_posture("") is None
    assert cdv.coerce_posture(None) is None
