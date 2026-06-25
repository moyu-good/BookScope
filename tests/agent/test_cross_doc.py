"""cross_doc.cross_doc_relations_from_spines 单测(1.6 文件间层)。

mock invoke_client_cached + 假 client,覆盖契约:
关系 parse/coerce / from·to 锚到真字号 / kind 封闭集 / 锚不到丢 / chapter_anchor 锚真实条款 /
(from,to,kind) 去重 / 机关名归一 / docs 节点 / <2 份返 None / 没字号丢 / 字号重复去重 /
空·解析失败·抛错返 None / 截断抢救 / 去代码围栏。不跑真 LLM。
"""

from __future__ import annotations

import json

from bookscope.agent import cross_doc


def _head(num="", doc_type="", org="", date="", title=""):
    """造一份文脉的 head(只填测试关心的几个要素,其余按 doc_spine 形态补空待核)。"""
    fields = {
        "发文字号": num, "文种": doc_type, "发文机关": org, "主送机关": "",
        "抄送机关": "", "标题事由": title, "成文日期": date, "签发人": "",
    }
    return [
        {"field": k, "value": v, "evidence": "", "verified": bool(v), "match_score": 0.0}
        for k, v in fields.items()
    ]


def _clause(ch, matter="", basis=""):
    return {
        "chapter": ch, "matter": matter, "instruction_type": "信息告知",
        "actor": "", "deadline": "", "basis_ref": basis, "evidence": "",
        "verified": False, "match_score": 0.0,
    }


# 三层一摞:省意见 / 市方案 / 县通知。字号是身份证。
# 注意:这里 clause 的 basis 全留空,好让下面这批用例**只测 LLM 推理那一路**——本地 basis_ref
# 兜底那一路另有 ``test_local_basis_*`` 专测(否则 fixture 自带的 basis 会额外冒出依据关系,
# 把"只测 LLM 这一条"的断言搅乱)。
_SPINES = [
    {
        "schema_version": "v1",
        "head": _head(num="省发〔2024〕1号", doc_type="意见", org="某省政府", date="2024年1月1日"),
        "clauses": [_clause(1, "总体要求"), _clause(2, "保障措施")],
    },
    {
        "schema_version": "v1",
        "head": _head(num="市发〔2024〕5号", doc_type="通知", org="某市政府", date="2024年3月1日"),
        "clauses": [_clause(1, "落实省里部署"), _clause(2, "细化任务")],
    },
    {
        "schema_version": "v1",
        "head": _head(num="县发〔2024〕9号", doc_type="通知", org="某县政府", date="2024年5月1日"),
        "clauses": [_clause(1, "据市通知办理")],
    },
]


class _FakeClient:
    def __init__(self, final_text=""):
        self._final = final_text

    def extract_final_text(self, resp):  # noqa: ANN001
        return resp if isinstance(resp, str) else self._final


def _patch(monkeypatch, text, *, raises=None):
    """patch cross_doc.invoke_client_cached 顺序返 text(可 list),或 raises 抛错。

    机关归一(``build_spine_name_map``)走的是它自己模块里 import 的 ``invoke_client_cached``,
    跟这里 patch 的 ``cross_doc.invoke_client_cached`` 不是同一引用——所以默认把
    ``cross_doc.build_spine_name_map`` 直接 stub 成恒等表(不合并),关系推理那次调用才是序列里
    的 text。机关归一本身有专门的 ``test_org_name_normalized`` 验。
    """
    monkeypatch.setattr(cross_doc, "build_spine_name_map", lambda **_k: {})

    seq = text if isinstance(text, list) else [text]

    def _fake(*_a, **_k):
        if raises is not None:
            raise raises
        return seq.pop(0)

    monkeypatch.setattr(cross_doc, "invoke_client_cached", _fake)


def _run(spines=None, **kw):
    return cross_doc.cross_doc_relations_from_spines(
        doc_spines=spines if spines is not None else _SPINES,
        llm_client=_FakeClient(),
        model="deepseek-v4-flash",
        **kw,
    )


def test_success_builds_relations_and_docs(monkeypatch):
    payload = json.dumps({
        "relations": [
            {"from_doc": "市发〔2024〕5号", "to_doc": "省发〔2024〕1号", "kind": "依据",
             "chapter_anchor": 1, "note": "市方案依据省意见"},
            {"from_doc": "县发〔2024〕9号", "to_doc": "市发〔2024〕5号", "kind": "落实",
             "chapter_anchor": 1, "note": "县通知落实市方案"},
        ],
    }, ensure_ascii=False)
    _patch(monkeypatch, payload)
    r = _run()
    assert r is not None
    rels = r["relations"]
    assert len(rels) == 2
    by_from = {x["from_doc"]: x for x in rels}
    assert by_from["市发〔2024〕5号"]["to_doc"] == "省发〔2024〕1号"
    assert by_from["市发〔2024〕5号"]["kind"] == "依据"
    assert by_from["市发〔2024〕5号"]["chapter_anchor"] == 1
    assert by_from["县发〔2024〕9号"]["kind"] == "落实"
    # docs 节点:每份一节点,带 字号/文种/机关/成文日期
    docs = r["docs"]
    assert len(docs) == 3
    nums = {d["字号"] for d in docs}
    assert nums == {"省发〔2024〕1号", "市发〔2024〕5号", "县发〔2024〕9号"}
    省 = next(d for d in docs if d["字号"] == "省发〔2024〕1号")
    assert 省["文种"] == "意见"
    assert 省["机关"] == "某省政府"
    assert 省["成文日期"] == "2024年1月1日"


def test_from_to_must_anchor_real_doc_number(monkeypatch):
    """from / to 不是这摞文件里真实字号 → 丢。"""
    payload = json.dumps({
        "relations": [
            {"from_doc": "市发〔2024〕5号", "to_doc": "省发〔2024〕1号", "kind": "依据",
             "chapter_anchor": 1, "note": "真"},
            {"from_doc": "市发〔2024〕5号", "to_doc": "国发〔2099〕99号", "kind": "依据",
             "chapter_anchor": 1, "note": "to 是清单外编的字号"},
            {"from_doc": "假发〔2024〕0号", "to_doc": "省发〔2024〕1号", "kind": "依据",
             "chapter_anchor": 1, "note": "from 编的字号"},
        ],
    }, ensure_ascii=False)
    _patch(monkeypatch, payload)
    rels = _run()["relations"]
    assert len(rels) == 1
    assert rels[0]["note"] == "真"


def test_kind_must_be_in_closed_set(monkeypatch):
    """kind 落不进封闭集 → 丢这条(不自造关系类型)。"""
    payload = json.dumps({
        "relations": [
            {"from_doc": "市发〔2024〕5号", "to_doc": "省发〔2024〕1号", "kind": "依据",
             "chapter_anchor": 1, "note": "好"},
            {"from_doc": "县发〔2024〕9号", "to_doc": "市发〔2024〕5号", "kind": "参考一下",
             "chapter_anchor": 1, "note": "自造的 kind"},
        ],
    }, ensure_ascii=False)
    _patch(monkeypatch, payload)
    rels = _run()["relations"]
    assert len(rels) == 1
    assert rels[0]["kind"] == "依据"
    assert all(x["kind"] in cross_doc.RELATION_KINDS for x in rels)


def test_self_relation_dropped(monkeypatch):
    """from == to(文件跟自己有关系)→ 丢。"""
    payload = json.dumps({
        "relations": [
            {"from_doc": "市发〔2024〕5号", "to_doc": "市发〔2024〕5号", "kind": "依据",
             "chapter_anchor": 1, "note": "自指"},
        ],
    }, ensure_ascii=False)
    _patch(monkeypatch, payload)
    assert _run() is None  # 唯一一条被丢 → 无真实关系 → None


def test_chapter_anchor_anchored_to_real_clause(monkeypatch):
    """chapter_anchor 锚到 from_doc 真实条款序号;越界 / 非整数 → 退 None(关系仍立)。"""
    payload = json.dumps({
        "relations": [
            {"from_doc": "市发〔2024〕5号", "to_doc": "省发〔2024〕1号", "kind": "依据",
             "chapter_anchor": 1, "note": "锚到真条款 1"},
            {"from_doc": "县发〔2024〕9号", "to_doc": "市发〔2024〕5号", "kind": "落实",
             "chapter_anchor": 99, "note": "县只有条款 1，99 越界"},
        ],
    }, ensure_ascii=False)
    _patch(monkeypatch, payload)
    rels = _run()["relations"]
    by_from = {x["from_doc"]: x for x in rels}
    assert by_from["市发〔2024〕5号"]["chapter_anchor"] == 1
    assert by_from["县发〔2024〕9号"]["chapter_anchor"] is None  # 越界退 None，关系仍在


def test_chapter_anchor_missing_or_non_int(monkeypatch):
    """chapter_anchor 缺 / 字符串 / 布尔 → None，关系仍立。"""
    payload = json.dumps({
        "relations": [
            {"from_doc": "市发〔2024〕5号", "to_doc": "省发〔2024〕1号", "kind": "依据",
             "note": "没给 anchor"},
            {"from_doc": "县发〔2024〕9号", "to_doc": "市发〔2024〕5号", "kind": "落实",
             "chapter_anchor": "第一条", "note": "anchor 是字符串"},
        ],
    }, ensure_ascii=False)
    _patch(monkeypatch, payload)
    rels = _run()["relations"]
    assert len(rels) == 2
    assert all(x["chapter_anchor"] is None for x in rels)


def test_dedup_from_to_kind(monkeypatch):
    """(from, to, kind) 三元组重复 → 只留首条。"""
    payload = json.dumps({
        "relations": [
            {"from_doc": "市发〔2024〕5号", "to_doc": "省发〔2024〕1号", "kind": "依据",
             "chapter_anchor": 1, "note": "首条"},
            {"from_doc": "市发〔2024〕5号", "to_doc": "省发〔2024〕1号", "kind": "依据",
             "chapter_anchor": 2, "note": "重复，丢"},
        ],
    }, ensure_ascii=False)
    _patch(monkeypatch, payload)
    rels = _run()["relations"]
    assert len(rels) == 1
    assert rels[0]["note"] == "首条"


def test_org_name_normalized(monkeypatch):
    """机关名归一:同一机关多种叫法 → docs 节点统一成 canonical(只动节点标签)。"""
    spines = [
        {"head": _head(num="财发〔2024〕1号", doc_type="意见", org="财政部", date="2024年1月1日"),
         "clauses": [_clause(1, "x")]},
        {"head": _head(num="财发〔2024〕2号", doc_type="通知", org="财", date="2024年2月1日"),
         "clauses": [_clause(1, "y")]},  # basis 留空,只测机关归一不掺 basis 兜底关系
    ]
    # 机关归一把「财」归到「财政部」(stub build_spine_name_map 出别名→canonical 表)。
    monkeypatch.setattr(cross_doc, "build_spine_name_map", lambda **_k: {"财": "财政部"})
    rel_payload = json.dumps({
        "relations": [
            {"from_doc": "财发〔2024〕2号", "to_doc": "财发〔2024〕1号", "kind": "依据",
             "chapter_anchor": 1, "note": "归一测试"},
        ],
    }, ensure_ascii=False)
    monkeypatch.setattr(cross_doc, "invoke_client_cached", lambda *_a, **_k: rel_payload)
    r = cross_doc.cross_doc_relations_from_spines(
        doc_spines=spines, llm_client=_FakeClient(), model="m",
    )
    assert r is not None
    orgs = {d["机关"] for d in r["docs"]}
    assert orgs == {"财政部"}  # 「财」被归一到「财政部」


def test_less_than_two_docs_returns_none(monkeypatch):
    """只有 1 份有字号的文件:凑不成「文件之间」→ None。"""
    spines = [{"head": _head(num="省发〔2024〕1号", org="某省"), "clauses": [_clause(1, "x")]}]
    _patch(monkeypatch, "{}")
    assert _run(spines=spines) is None


def test_doc_without_number_excluded(monkeypatch):
    """没抽到发文字号的文脉不进网络:够不到 2 份 → None。"""
    spines = [
        {"head": _head(num="省发〔2024〕1号", org="某省"), "clauses": [_clause(1, "x")]},
        {"head": _head(num="", org="某市"), "clauses": [_clause(1, "y")]},  # 没字号
    ]
    _patch(monkeypatch, "{}")
    assert _run(spines=spines) is None  # 只剩 1 份有字号


def test_duplicate_number_deduped(monkeypatch):
    """同一字号重复出现:只留第一份(字号是唯一身份),够不到 2 份 → None。"""
    spines = [
        {"head": _head(num="省发〔2024〕1号", org="某省"), "clauses": [_clause(1, "x")]},
        {"head": _head(num="省发〔2024〕1号", org="某省抄本"), "clauses": [_clause(1, "y")]},
    ]
    _patch(monkeypatch, "{}")
    assert _run(spines=spines) is None  # 去重后只 1 份


def test_empty_relations_returns_none(monkeypatch):
    """这摞文件之间没关系(LLM 返空数组)→ None(端点返空态)。"""
    _patch(monkeypatch, json.dumps({"relations": []}))
    assert _run() is None


def test_parse_failure_returns_none(monkeypatch):
    _patch(monkeypatch, "这不是 JSON，随便说点别的")
    assert _run() is None


def test_llm_raises_returns_none(monkeypatch):
    _patch(monkeypatch, "{}", raises=RuntimeError("boom"))
    assert _run() is None


def test_empty_doc_spines_returns_none():
    """空输入直接 None,不调 LLM。"""
    assert cross_doc.cross_doc_relations_from_spines(
        doc_spines=[], llm_client=_FakeClient(), model="m",
    ) is None


def test_salvages_truncated_relations(monkeypatch):
    """reasoning 吃 token 致 JSON 截断 → 抢救已闭合的关系,不整摞丢。"""
    truncated = (
        '{"relations": ['
        '{"from_doc": "市发〔2024〕5号", "to_doc": "省发〔2024〕1号", "kind": "依据",'
        ' "chapter_anchor": 1, "note": "完整"},'
        '{"from_doc": "县发〔2024〕9号", "to_doc": "市发〔2024〕5号", "kind": "落实",'  # 截断
    )
    _patch(monkeypatch, truncated)
    r = _run()
    assert r is not None
    froms = {x["from_doc"] for x in r["relations"]}
    assert "市发〔2024〕5号" in froms  # 闭合的那条救回
    assert "县发〔2024〕9号" not in froms  # 截断的丢


def test_strips_code_fence(monkeypatch):
    inner = json.dumps({
        "relations": [
            {"from_doc": "市发〔2024〕5号", "to_doc": "省发〔2024〕1号", "kind": "依据",
             "chapter_anchor": 1, "note": "x"},
        ],
    }, ensure_ascii=False)
    _patch(monkeypatch, "```json\n" + inner + "\n```")
    r = _run()
    assert r is not None
    assert len(r["relations"]) == 1


# ── 没字号的文件靠标题进网络(地方法规场景) ─────────────────────────────────────
def test_doc_without_number_anchors_by_title(monkeypatch):
    """没发文字号的地方法规(广东 / 广州条例)用标题当 anchor,照样进网络、能被引到。

    营商环境链的真实形态:722 条例有字号;广东条例没字号,只有标题《广东省优化营商环境条例》,
    正文「根据《优化营商环境条例》制定本条例」按标题引 722。
    """
    spines = [
        # 722:有字号
        {"head": _head(num="国务院令第722号", doc_type="条例", org="国务院",
                       title="优化营商环境条例", date="2019年10月22日"),
         "clauses": [_clause(1, "总则")]},
        # 广东条例:没字号,靠标题进网络;正文按标题引 722
        {"head": _head(num="", doc_type="条例", org="广东省人民代表大会常务委员会",
                       title="广东省优化营商环境条例", date="2020年7月1日"),
         "clauses": [_clause(1, "据上位条例制定", basis="《优化营商环境条例》")]},
    ]
    # LLM 这次什么都不推(返空),全靠本地 basis_ref 兜底——验"按标题引"那条捞得出来。
    _patch(monkeypatch, json.dumps({"relations": []}))
    r = _run(spines=spines)
    assert r is not None
    # 广东条例靠标题当 anchor 进了 docs(没字号也在)
    anchors = {d["字号"] for d in r["docs"]}
    assert "广东省优化营商环境条例" in anchors
    # 本地兜底捞出"广东条例 依据 722"(按标题引解析回 722 的字号 anchor)
    rels = r["relations"]
    assert any(
        x["from_doc"] == "广东省优化营商环境条例"
        and x["to_doc"] == "国务院令第722号"
        and x["kind"] == "依据"
        for x in rels
    )


# ── 本地 basis_ref 兜底:LLM 漏了,正文引用照样坐实依据 ──────────────────────────
def test_local_basis_ref_caught_even_when_llm_misses(monkeypatch):
    """LLM 一条关系都没推出来,但条款 basis_ref 正文引到另一份 → 本地兜底坐实"依据"。"""
    spines = [
        {"head": _head(num="省发〔2024〕1号", doc_type="意见", org="某省政府"),
         "clauses": [_clause(1, "总体要求")]},
        {"head": _head(num="市发〔2024〕5号", doc_type="通知", org="某市政府"),
         "clauses": [_clause(1, "落实", basis="省发〔2024〕1号")]},
    ]
    _patch(monkeypatch, json.dumps({"relations": []}))  # LLM 啥也没推
    r = _run(spines=spines)
    assert r is not None
    rels = r["relations"]
    assert len(rels) == 1
    assert rels[0]["from_doc"] == "市发〔2024〕5号"
    assert rels[0]["to_doc"] == "省发〔2024〕1号"
    assert rels[0]["kind"] == "依据"
    assert rels[0]["chapter_anchor"] == 1  # basis 来自第 1 条款,锚得准


def test_local_basis_ref_to_outside_doc_dropped(monkeypatch):
    """basis_ref 引的是这摞之外的文件 → 解析不到 anchor,本地不坐实(不编)。"""
    spines = [
        {"head": _head(num="省发〔2024〕1号", doc_type="意见", org="某省政府"),
         "clauses": [_clause(1, "据国家文件", basis="国发〔2099〕99号")]},  # 引清单外
        {"head": _head(num="市发〔2024〕5号", doc_type="通知", org="某市政府"),
         "clauses": [_clause(1, "细化")]},
    ]
    _patch(monkeypatch, json.dumps({"relations": []}))
    assert _run(spines=spines) is None  # 引的不在这摞里,锚不到 → 无关系 → None


def test_llm_failure_keeps_local_relations(monkeypatch):
    """LLM 调用抛错,但本地 basis_ref 已捞到关系 → 不返 None,链不全塌。"""
    spines = [
        {"head": _head(num="省发〔2024〕1号", doc_type="意见", org="某省政府"),
         "clauses": [_clause(1, "总体要求")]},
        {"head": _head(num="市发〔2024〕5号", doc_type="通知", org="某市政府"),
         "clauses": [_clause(1, "落实", basis="省发〔2024〕1号")]},
    ]
    _patch(monkeypatch, "{}", raises=RuntimeError("LLM boom"))
    r = _run(spines=spines)
    assert r is not None  # 本地那路兜住了
    assert len(r["relations"]) == 1
    assert r["relations"][0]["kind"] == "依据"
