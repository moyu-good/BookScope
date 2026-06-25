"""公文文脉 doc_spine 单测(1.6 红头文件垂直地基)。

合成一份红头文件的 chunk(条款序号当单元) + mock LLM(假 client + monkeypatch
invoke_client_cached),覆盖:

- 文脉结构:head(头要素维)+ clauses(条款维)+ schema_version。
- 指令类型是**封闭集标签**(硬要求/软倡导/信息告知/依据陈述),带原文撑,不是分数;
  落不进四类退「信息告知」。
- 文种落进 15 文种封闭集,落不进留空(绝不自造)。
- 头要素 evidence 过 verify_citations:核得过 verified=True、核不过(含空)标待核 verified=False。
- 头要素**抽不到留空待核**:模型只给部分要素,其余出空记录、绝不编。
- 条款 evidence 核验 + 章号(条款序号)纠偏。
- 时限/责任主体抽不到留空不编。
- parse 三层兜底:去代码围栏 / 截断抢救条款。

不跑真 LLM。
"""

from __future__ import annotations

import json

from bookscope.agent import doc_spine as ds

# 合成红头文件:条款序号当单元(chunk 的 chapter 字段=条款序号)。
_CHUNKS = [
    {"chunk_id": "h0", "chapter": 0,
     "text": "市发展改革委文件 X发〔2024〕5号 关于做好新能源补贴申报的通知 "
             "成文日期：2024年5月8日 签发人：张某。"},
    {"chunk_id": "c1", "chapter": 1,
     "text": "各县区发展改革局应当于2024年6月30日前完成本辖区补贴申报材料的汇总上报。"},
    {"chunk_id": "c2", "chapter": 2,
     "text": "鼓励各地结合实际探索更高效的申报方式，可以先行先试。"},
    {"chunk_id": "c3", "chapter": 3,
     "text": "根据《省新能源发展意见》（省发〔2023〕12号），现就有关事项通知如下。"},
]


class _FakeClient:
    def extract_final_text(self, resp):  # noqa: ANN001, ANN201
        return resp if isinstance(resp, str) else "{}"


def _patch(monkeypatch, *, head_text: str, clause_text: str):
    """头要素维一次调用、条款维分段调用——按 system 里的指令分支返不同 canned JSON。

    invoke_client_cached 被 doc_spine 与 exhaustive 两处用;两处都 patch 到同一分支函数。
    """
    def _fake(*_a, **kwargs):  # noqa: ANN002, ANN003, ANN202
        system = kwargs.get("system", "")
        # 头要素维指令含「文件头要素」,条款维指令含「逐条款精读」。
        return head_text if "文件头要素" in system else clause_text

    monkeypatch.setattr(ds, "invoke_client_cached", _fake)
    # exhaustive.run_segments 走它自己 import 的 invoke_client_cached;条款维分段经过它。
    import bookscope.agent._internal.exhaustive as exh
    monkeypatch.setattr(exh, "invoke_client_cached", _fake)


def _head_payload(elements: list[dict]) -> str:
    return json.dumps({"elements": elements}, ensure_ascii=False)


def _clause_payload(clauses: list[dict]) -> str:
    return json.dumps({"clauses": clauses}, ensure_ascii=False)


def _run(monkeypatch, *, head_text: str, clause_text: str, chunks=None):
    _patch(monkeypatch, head_text=head_text, clause_text=clause_text)
    return ds.build_doc_spine(
        chunks=chunks if chunks is not None else _CHUNKS,
        llm_client=_FakeClient(),
        model="deepseek-v4-flash",
        max_workers=1,  # 串行,断言确定
    )


def _full_head() -> str:
    return _head_payload([
        {"field": "发文字号", "value": "X发〔2024〕5号",
         "evidence": "市发展改革委文件 X发〔2024〕5号"},
        {"field": "文种", "value": "通知",
         "evidence": "关于做好新能源补贴申报的通知"},
        {"field": "发文机关", "value": "市发展改革委",
         "evidence": "市发展改革委文件"},
        {"field": "成文日期", "value": "2024年5月8日",
         "evidence": "成文日期：2024年5月8日"},
        {"field": "签发人", "value": "张某", "evidence": "签发人：张某"},
    ])


def _full_clauses() -> str:
    return _clause_payload([
        {"chapter": 1, "matter": "县区局汇总上报补贴申报材料", "instruction_type": "硬要求",
         "actor": "各县区发展改革局", "deadline": "2024年6月30日前", "basis_ref": "",
         "evidence": "各县区发展改革局应当于2024年6月30日前完成本辖区补贴申报材料的汇总上报。"},
        {"chapter": 2, "matter": "鼓励探索更高效申报方式", "instruction_type": "软倡导",
         "actor": "", "deadline": "", "basis_ref": "",
         "evidence": "鼓励各地结合实际探索更高效的申报方式，可以先行先试。"},
        {"chapter": 3, "matter": "陈述行文依据", "instruction_type": "依据陈述",
         "actor": "", "deadline": "", "basis_ref": "省发〔2023〕12号",
         "evidence": "根据《省新能源发展意见》（省发〔2023〕12号），现就有关事项通知如下。"},
    ])


# ── 整体结构 ─────────────────────────────────────────────────────────────────
def test_builds_head_and_clauses(monkeypatch):
    spine = _run(monkeypatch, head_text=_full_head(), clause_text=_full_clauses())
    assert spine["schema_version"] == ds.DOC_SPINE_SCHEMA_VERSION
    # 头要素维固定产出全部 8 个要素(没抽到的也出空待核)
    assert len(spine["head"]) == len(ds._HEAD_FIELDS)
    fields = {el["field"] for el in spine["head"]}
    assert fields == set(ds._HEAD_FIELDS)
    # 条款维三条
    clauses = spine["clauses"]
    assert [c["chapter"] for c in clauses] == [1, 2, 3]


# ── 指令类型是带原文撑的封闭集标签,不是分数 ──────────────────────────────────
def test_instruction_type_is_label_with_evidence(monkeypatch):
    spine = _run(monkeypatch, head_text=_full_head(), clause_text=_full_clauses())
    by_ch = {c["chapter"]: c for c in spine["clauses"]}
    assert by_ch[1]["instruction_type"] == "硬要求"
    assert by_ch[2]["instruction_type"] == "软倡导"
    assert by_ch[3]["instruction_type"] == "依据陈述"
    # 每条都带原文撑且核得过(命中合成原文)
    for c in spine["clauses"]:
        assert c["evidence"]
        assert c["verified"] is True
        # 指令类型是字符串标签,绝不是数字分数
        assert isinstance(c["instruction_type"], str)
        assert c["instruction_type"] in ds.INSTRUCTION_TYPES


def test_unknown_instruction_type_falls_back_to_info(monkeypatch):
    """模型给个不在四类里的标签 → 退「信息告知」(最弱兜底,不误导用户当硬要求)。"""
    clause = _clause_payload([
        {"chapter": 1, "matter": "x", "instruction_type": "9分超强硬",
         "actor": "", "deadline": "", "basis_ref": "",
         "evidence": "各县区发展改革局应当于2024年6月30日前完成本辖区补贴申报材料的汇总上报。"},
    ])
    spine = _run(monkeypatch, head_text=_full_head(), clause_text=clause)
    assert spine["clauses"][0]["instruction_type"] == "信息告知"


# ── 文种落进封闭集,落不进留空 ───────────────────────────────────────────────
def test_doc_type_must_be_in_closed_set(monkeypatch):
    """模型自造一个不在 15 文种里的「文种」→ 留空,绝不收。"""
    head = _head_payload([
        {"field": "文种", "value": "红头大令", "evidence": "关于……的通知"},
    ])
    spine = _run(monkeypatch, head_text=head, clause_text=_full_clauses())
    wenzhong = next(el for el in spine["head"] if el["field"] == "文种")
    assert wenzhong["value"] == ""  # 自造文种被丢


def test_valid_doc_type_kept(monkeypatch):
    spine = _run(monkeypatch, head_text=_full_head(), clause_text=_full_clauses())
    wenzhong = next(el for el in spine["head"] if el["field"] == "文种")
    assert wenzhong["value"] == "通知"
    assert wenzhong["verified"] is True  # evidence 命中标题原文


# ── 头要素 evidence 核验:核不过标待核 ────────────────────────────────────────
def test_head_evidence_not_in_original_marked_pending(monkeypatch):
    """模型给的发文字号 evidence 原文里根本没有 → verified=False 标待核(没核过不当真)。"""
    head = _head_payload([
        {"field": "发文字号", "value": "假发〔9999〕1号",
         "evidence": "这句原文里压根没有，是模型编的字号出处。"},
    ])
    spine = _run(monkeypatch, head_text=head, clause_text=_full_clauses())
    fawenzihao = next(el for el in spine["head"] if el["field"] == "发文字号")
    assert fawenzihao["verified"] is False  # 核不过,标待核


def test_head_verified_when_evidence_in_original(monkeypatch):
    spine = _run(monkeypatch, head_text=_full_head(), clause_text=_full_clauses())
    fawenzihao = next(el for el in spine["head"] if el["field"] == "发文字号")
    assert fawenzihao["value"] == "X发〔2024〕5号"
    assert fawenzihao["verified"] is True  # evidence 命中原文


# ── 头要素抽不到留空待核,绝不编 ──────────────────────────────────────────────
def test_missing_head_elements_left_blank_pending(monkeypatch):
    """模型只给了发文字号,其余 7 个要素全没给 → 各出一条空记录、verified=False,绝不编。"""
    head = _head_payload([
        {"field": "发文字号", "value": "X发〔2024〕5号",
         "evidence": "市发展改革委文件 X发〔2024〕5号"},
    ])
    spine = _run(monkeypatch, head_text=head, clause_text=_full_clauses())
    by_field = {el["field"] for el in spine["head"]}
    assert by_field == set(ds._HEAD_FIELDS)  # 仍产出全部要素
    for el in spine["head"]:
        if el["field"] == "发文字号":
            continue
        assert el["value"] == ""  # 没抽到的留空
        assert el["verified"] is False  # 标待核


def test_head_extraction_failure_all_blank(monkeypatch):
    """头要素维 LLM 返回不可解析 → 全要素留空待核,不报错、不编。"""
    spine = _run(monkeypatch, head_text="这不是 JSON", clause_text=_full_clauses())
    assert len(spine["head"]) == len(ds._HEAD_FIELDS)
    assert all(el["value"] == "" and el["verified"] is False for el in spine["head"])
    # 条款维不受影响照常出
    assert len(spine["clauses"]) == 3


# ── 时限/责任主体抽不到留空不编 ──────────────────────────────────────────────
def test_clause_deadline_actor_blank_when_absent(monkeypatch):
    spine = _run(monkeypatch, head_text=_full_head(), clause_text=_full_clauses())
    by_ch = {c["chapter"]: c for c in spine["clauses"]}
    # 第 1 条有时限+责任主体
    assert by_ch[1]["deadline"] == "2024年6月30日前"
    assert by_ch[1]["actor"] == "各县区发展改革局"
    # 第 2 条软倡导,无时限无主体 → 留空
    assert by_ch[2]["deadline"] == ""
    assert by_ch[2]["actor"] == ""
    # 第 3 条依据陈述,带 basis_ref
    assert by_ch[3]["basis_ref"] == "省发〔2023〕12号"


# ── 条款序号(chapter)纠偏 ───────────────────────────────────────────────────
def test_clause_chapter_corrected_by_evidence(monkeypatch):
    """模型自报条款序号 99,但 evidence 命中真序号 1 的 chunk → 纠偏成 1。"""
    clause = _clause_payload([
        {"chapter": 99, "matter": "x", "instruction_type": "硬要求",
         "actor": "各县区发展改革局", "deadline": "2024年6月30日前", "basis_ref": "",
         "evidence": "各县区发展改革局应当于2024年6月30日前完成本辖区补贴申报材料的汇总上报。"},
    ])
    spine = _run(monkeypatch, head_text=_full_head(), clause_text=clause)
    assert spine["clauses"][0]["chapter"] == 1  # 纠偏到真序号
    assert spine["clauses"][0]["verified"] is True


# ── parse 兜底 ───────────────────────────────────────────────────────────────
def test_clause_strips_code_fence(monkeypatch):
    inner = _full_clauses()
    fenced = "```json\n" + inner + "\n```"
    spine = _run(monkeypatch, head_text=_full_head(), clause_text=fenced)
    assert [c["chapter"] for c in spine["clauses"]] == [1, 2, 3]


def test_clause_salvages_truncated(monkeypatch):
    """条款维 JSON 截断 → 抢救已闭合的条款,不整段丢。"""
    truncated = (
        '{"clauses": [{"chapter": 1, "matter": "完整一条", "instruction_type": "硬要求", '
        '"actor": "各县区发展改革局", "deadline": "2024年6月30日前", "basis_ref": "", '
        '"evidence": "各县区发展改革局应当于2024年6月30日前完成本辖区补贴申报材料的汇总上报。"}, '
        '{"chapter": 2, "matter": "未闭合'  # 截断
    )
    spine = _run(monkeypatch, head_text=_full_head(), clause_text=truncated)
    chs = [c["chapter"] for c in spine["clauses"]]
    assert 1 in chs and 2 not in chs  # 抢救到第一条,截断的第二条丢


def test_empty_clauses_when_unparseable(monkeypatch):
    """条款维完全解析不出 → clauses 空,文脉仍带 head 正常返。"""
    spine = _run(monkeypatch, head_text=_full_head(), clause_text="什么都不是")
    assert spine["clauses"] == []
    assert len(spine["head"]) == len(ds._HEAD_FIELDS)


# ── 封闭集纯件 ───────────────────────────────────────────────────────────────
def test_coerce_doc_type_pure():
    assert ds._coerce_doc_type("通知") == "通知"
    assert ds._coerce_doc_type("红头大令") == ""  # 不在 15 文种
    assert ds._coerce_doc_type(123) == ""  # 非字符串
    assert ds._coerce_doc_type("  通知  ") == "通知"  # 去空白


def test_coerce_instruction_type_pure():
    for t in ds.INSTRUCTION_TYPES:
        assert ds._coerce_instruction_type(t) == t
    assert ds._coerce_instruction_type("8分") == "信息告知"  # 落不进退兜底
    assert ds._coerce_instruction_type(None) == "信息告知"


def test_coerce_clause_drops_non_int_chapter():
    assert ds._coerce_clause({"chapter": "一", "matter": "x"}) is None
    assert ds._coerce_clause({"matter": "无序号"}) is None
    ok = ds._coerce_clause({"chapter": 2, "matter": "有事项"})
    assert ok is not None
    assert ok["chapter"] == 2
    assert ok["instruction_type"] == "信息告知"  # 缺指令类型退兜底
    assert ok["deadline"] == ""  # 缺时限留空
