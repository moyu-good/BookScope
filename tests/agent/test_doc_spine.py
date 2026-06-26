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


# ── 头要素新增:密级 / 紧急程度(GB/T 9704 版头要素,研究笔记 004 §3.1)─────────────
def test_classification_and_urgency_in_head_fields():
    """密级 / 紧急程度 进了头要素清单(产品级安全信号 + 紧急信号)。"""
    assert "密级" in ds._HEAD_FIELDS
    assert "紧急程度" in ds._HEAD_FIELDS


def test_classification_urgency_blank_pending_when_absent(monkeypatch):
    """绝大多数公文不标密级/紧急程度——抽不到留空待核,绝不硬凑。"""
    spine = _run(monkeypatch, head_text=_full_head(), clause_text=_full_clauses())
    by_field = {el["field"]: el for el in spine["head"]}
    for f in ("密级", "紧急程度"):
        assert by_field[f]["value"] == ""  # 没标就留空
        assert by_field[f]["verified"] is False  # 标待核


# ── 法规本体 N/A 区分:条例没有的"发文"要素标"本文种无此项"不标待核 ───────────────────
def test_regulation_marks_na_not_pending(monkeypatch):
    """法规本体(条例)结构上没有发文字号/密级/紧急程度/主送/抄送/签发人 → 标 not_applicable,
    区别于待核(该有却没抽到)。文种/发文机关/标题事由/成文日期这些法规该有的不标 N/A。
    回应作者:一份条例显"头要素 3/10、全待核"会让人以为抽坏了,其实是文件本就没那 6 项。"""
    head = _head_payload([
        {"field": "文种", "value": "条例", "evidence": "制定本条例"},
        {"field": "发文机关", "value": "广州市人民代表大会常务委员会",
         "evidence": "广州市第十五届人民代表大会常务委员会第四十二次会议通过"},
        {"field": "标题事由", "value": "广州市优化营商环境条例",
         "evidence": "广州市优化营商环境条例"},
        {"field": "成文日期", "value": "2020年10月28日",
         "evidence": "2020年10月28日广州市第十五届人民代表大会常务委员会第四十二次会议通过"},
    ])
    chunks = [
        {"chunk_id": "h0", "chapter": 0,
         "text": "广州市优化营商环境条例 2020年10月28日广州市第十五届人民代表大会常务委员会"
                 "第四十二次会议通过 第一条 为优化营商环境，制定本条例。"},
    ]
    spine = _run(
        monkeypatch, head_text=head,
        clause_text=_clause_payload([
            {"chapter": 1, "matter": "立法目的", "instruction_type": "依据陈述",
             "actor": "", "deadline": "", "basis_ref": "",
             "evidence": "第一条 为优化营商环境，制定本条例。"},
        ]),
        chunks=chunks,
    )
    by_field = {el["field"]: el for el in spine["head"]}
    # 法规没有的 6 个"发文"要素 → not_applicable=True(空值,但不是待核)
    for f in ("发文字号", "密级", "紧急程度", "主送机关", "抄送机关", "签发人"):
        assert by_field[f].get("not_applicable") is True, f"{f} 该标本文种无此项"
        assert by_field[f]["value"] == ""
    # 法规该有的 4 项不标 N/A
    for f in ("文种", "发文机关", "标题事由", "成文日期"):
        assert by_field[f].get("not_applicable") is not True, f"{f} 不该标 N/A"


def test_notice_head_no_na(monkeypatch):
    """普通公文(通知)不标 N/A——空要素仍是待核(该有可能没抽到,不是文种没有)。"""
    spine = _run(monkeypatch, head_text=_full_head(), clause_text=_full_clauses())
    for el in spine["head"]:
        assert el.get("not_applicable") is not True


def test_classification_extracted_and_verified(monkeypatch):
    """涉密+特急件:密级/紧急程度抽到且 evidence 命中原文 → 收下并核过。"""
    chunks = [
        {"chunk_id": "h0", "chapter": 0,
         "text": "机密★1年 特急 市发展改革委文件 X发〔2024〕5号 "
                 "关于做好新能源补贴申报的通知。"},
        {"chunk_id": "c1", "chapter": 1,
         "text": "各县区发展改革局应当于2024年6月30日前完成材料汇总上报。"},
    ]
    head = _head_payload([
        {"field": "密级", "value": "机密", "evidence": "机密★1年 特急 市发展改革委文件"},
        {"field": "紧急程度", "value": "特急", "evidence": "机密★1年 特急 市发展改革委文件"},
    ])
    spine = _run(monkeypatch, head_text=head, clause_text=_full_clauses(), chunks=chunks)
    by_field = {el["field"]: el for el in spine["head"]}
    assert by_field["密级"]["value"] == "机密"
    assert by_field["密级"]["verified"] is True
    assert by_field["紧急程度"]["value"] == "特急"
    assert by_field["紧急程度"]["verified"] is True


# ── instruction_type 接行文方向先验(研究笔记 004 §3.2)──────────────────────────
def test_clause_prompt_carries_direction_prior():
    """条款维 prompt 把上行/下行/平行的行文方向先验喂进去了,文种名出现在 prompt 里。"""
    instr = ds._INSTR_CLAUSE
    assert "上行文" in instr and "下行文" in instr and "平行文" in instr
    # 文种名嵌进先验(请示=上行、命令=下行、函=平行)
    assert "请示" in instr and "命令" in instr and "函" in instr
    # 点明上行文的措辞别误判成对下级硬要求
    assert "别判成对下级" in instr or "别判成对下级的硬要求" in instr


# ── 1.6.1 办事清单含金量层:substance / penalty / substance_reason ────────────────
def _clauses_with_substance() -> str:
    """三条条款带含金量:第1条真金白银(有罚则)、第2条空头(纯倡导无罚则)、第3条依据陈述。"""
    return _clause_payload([
        {"chapter": 1, "matter": "县区局汇总上报补贴申报材料", "instruction_type": "硬要求",
         "actor": "各县区发展改革局", "deadline": "2024年6月30日前", "basis_ref": "",
         "substance": "真金白银", "substance_reason": "「应当…6月30日前…」有硬约束+时限+主体",
         "penalty": "逾期未报予以通报",
         "evidence": "各县区发展改革局应当于2024年6月30日前完成本辖区补贴申报材料的汇总上报。"},
        {"chapter": 2, "matter": "鼓励探索更高效申报方式", "instruction_type": "软倡导",
         "actor": "", "deadline": "", "basis_ref": "",
         "substance": "空头倡导",
         "substance_reason": "「鼓励…可以先行先试」纯倡导无数字无时限无罚则",
         "penalty": "",
         "evidence": "鼓励各地结合实际探索更高效的申报方式，可以先行先试。"},
        {"chapter": 3, "matter": "陈述行文依据", "instruction_type": "依据陈述",
         "actor": "", "deadline": "", "basis_ref": "省发〔2023〕12号",
         "substance": "有条件兑现", "substance_reason": "", "penalty": "",
         "evidence": "根据《省新能源发展意见》（省发〔2023〕12号），现就有关事项通知如下。"},
    ])


def test_clause_substance_fields_present_and_closed_set(monkeypatch):
    """每条条款带 substance(落三档封闭集)+ substance_reason + penalty。"""
    spine = _run(monkeypatch, head_text=_full_head(), clause_text=_clauses_with_substance())
    by_ch = {c["chapter"]: c for c in spine["clauses"]}
    for c in spine["clauses"]:
        for k in ("substance", "substance_reason", "penalty"):
            assert k in c, f"条款缺字段 {k}"
        assert c["substance"] in ds.SUBSTANCE_LEVELS
    assert by_ch[1]["substance"] == "真金白银"
    assert by_ch[2]["substance"] == "空头倡导"
    assert by_ch[3]["substance"] == "有条件兑现"


def test_clause_penalty_kept_when_present_blank_when_absent(monkeypatch):
    """有罚则的条款留住代价;纯倡导的 penalty 空——绝不替它编代价(空正好印证是空头)。"""
    spine = _run(monkeypatch, head_text=_full_head(), clause_text=_clauses_with_substance())
    by_ch = {c["chapter"]: c for c in spine["clauses"]}
    assert by_ch[1]["penalty"] == "逾期未报予以通报"  # 真金白银条留住罚则
    assert by_ch[2]["penalty"] == ""  # 空头条没罚则,留空不编


def test_clause_unknown_substance_falls_back(monkeypatch):
    """模型给个不在三档里的含金量 → 退「有条件兑现」(中性兜底)。"""
    clause = _clause_payload([
        {"chapter": 1, "matter": "x", "instruction_type": "硬要求",
         "substance": "9分超硬核", "substance_reason": "", "penalty": "",
         "actor": "", "deadline": "", "basis_ref": "",
         "evidence": "各县区发展改革局应当于2024年6月30日前完成本辖区补贴申报材料的汇总上报。"},
    ])
    spine = _run(monkeypatch, head_text=_full_head(), clause_text=clause)
    assert spine["clauses"][0]["substance"] == "有条件兑现"


def test_clause_substance_defaults_when_absent_backward_compat(monkeypatch):
    """老格式条款(没 substance 字段,如旧缓存重抽)→ substance 退中性档、penalty 空,向后兼容。"""
    # _full_clauses() 是不带 substance 的老格式
    spine = _run(monkeypatch, head_text=_full_head(), clause_text=_full_clauses())
    for c in spine["clauses"]:
        assert c["substance"] == "有条件兑现"  # 缺字段退中性兜底
        assert c["penalty"] == ""
        assert c["substance_reason"] == ""


def test_clause_prompt_carries_codebook_and_substance():
    """条款维 prompt 拼进了 codebook(开环/闭环判据)+ 问含金量 + 不办的代价。"""
    instr = ds._INSTR_CLAUSE
    assert "含金量" in instr and "真金白银" in instr and "空头倡导" in instr
    assert "不办的代价" in instr or "不办会怎样" in instr
    # codebook 的约束力阶梯 marker 进来了
    assert "约束力阶梯" in instr


def test_coerce_clause_substance_layer_defaults():
    """_coerce_clause 纯件:缺 substance/penalty → substance 退中性、penalty/reason 空。"""
    ok = ds._coerce_clause({"chapter": 1, "matter": "x"})
    assert ok is not None
    assert ok["substance"] == "有条件兑现"
    assert ok["penalty"] == ""
    assert ok["substance_reason"] == ""
    # 给了合法 substance 就留住
    ok2 = ds._coerce_clause({"chapter": 2, "matter": "y", "substance": "真金白银",
                             "penalty": "罚款", "substance_reason": "有罚则"})
    assert ok2["substance"] == "真金白银"
    assert ok2["penalty"] == "罚款"


# ── 看结构(结构即信号)层:doc 级 structure_read ─────────────────────────────────
# WP §二「看结构」落到产品的判断层。权威刻度(据已抽文种+机关判效力层级+研判)+ 结构信号
# (缺身份要素=存疑/排序=牵头/篇幅构成=性质)。评估层标研判、绝不盖鉴印,但锚已核要素。
# 死守:法规 N/A 标过的要素**不报缺席信号**(不误报)。


def test_structure_read_present_for_notice(monkeypatch):
    """通知出 structure_read:权威刻度判「一般公文」+ 引到已抽文种/机关。"""
    spine = _run(monkeypatch, head_text=_full_head(), clause_text=_full_clauses())
    sr = spine["structure_read"]
    auth = sr["authority"]
    assert auth["level"] == "一般公文"  # 通知=中性兜底
    assert auth["rank"] == ds._AUTHORITY_RANK["一般公文"]
    # 引到已抽的文种 + 发文机关(不是空说)
    assert auth["doc_type"] == "通知"
    assert auth["issuer"] == "市发展改革委"
    assert auth["doc_type_evidence"]  # 带文种原文撑
    # 文种 + 机关都核过 → verified_basis True
    assert auth["verified_basis"] is True
    # 有一句研判(分量/能管到谁)
    assert auth["appraisal"]


def test_structure_read_authority_levels(monkeypatch):
    """不同文种判不同效力层级:令>地方性法规>指令性公文>一般公文>商洽函(纯件直测)。"""
    # 令 = 公布令/法规(最高)
    assert ds._classify_authority("令", "国务院") == "公布令/法规"
    # 条例 + 人大常委会 = 地方性法规
    assert ds._classify_authority(
        "条例", "广州市人民代表大会常务委员会"
    ) == "地方性法规"
    # 命令/决定/批复 = 指令性公文
    assert ds._classify_authority("命令", "某部") == "指令性公文"
    assert ds._classify_authority("批复", "某委") == "指令性公文"
    # 函 = 商洽函(最弱)
    assert ds._classify_authority("函", "某局") == "商洽函"
    # 通知/意见 = 一般公文(中性兜底)
    assert ds._classify_authority("通知", "某委") == "一般公文"
    assert ds._classify_authority("意见", "某府") == "一般公文"
    # rank 排序:令 < 地方性法规 < 指令性 < 一般 < 函
    assert (
        ds._AUTHORITY_RANK["公布令/法规"]
        < ds._AUTHORITY_RANK["地方性法规"]
        < ds._AUTHORITY_RANK["指令性公文"]
        < ds._AUTHORITY_RANK["一般公文"]
        < ds._AUTHORITY_RANK["商洽函"]
    )


def test_structure_read_missing_identity_element_signal(monkeypatch):
    """普通公文缺发文字号 → 报缺席信号(存疑/非正式),引到具体缺的要素。"""
    # 头要素只给文种 + 机关,发文字号/成文日期都没抽到(空、非 N/A)
    head = _head_payload([
        {"field": "文种", "value": "通知", "evidence": "关于做好新能源补贴申报的通知"},
        {"field": "发文机关", "value": "市发展改革委", "evidence": "市发展改革委文件"},
    ])
    spine = _run(monkeypatch, head_text=head, clause_text=_full_clauses())
    missing = [s for s in spine["structure_read"]["signals"] if s["kind"] == "missing"]
    elements = {s["element"] for s in missing}
    assert "发文字号" in elements  # 普通公文缺身份要素 → 报存疑
    assert "成文日期" in elements
    for s in missing:
        assert s["note"]  # 每条说清缺这项意味着什么


def test_structure_read_regulation_na_not_reported_as_missing(monkeypatch):
    """死守:法规本体 N/A 的发文字号/成文日期**绝不报缺席信号**(它本就没有,报=误报)。"""
    head = _head_payload([
        {"field": "文种", "value": "条例", "evidence": "制定本条例"},
        {"field": "发文机关", "value": "广州市人民代表大会常务委员会",
         "evidence": "广州市第十五届人民代表大会常务委员会第四十二次会议通过"},
        {"field": "标题事由", "value": "广州市优化营商环境条例",
         "evidence": "广州市优化营商环境条例"},
        {"field": "成文日期", "value": "2020年10月28日",
         "evidence": "2020年10月28日广州市第十五届人民代表大会常务委员会第四十二次会议通过"},
    ])
    chunks = [
        {"chunk_id": "h0", "chapter": 0,
         "text": "广州市优化营商环境条例 2020年10月28日广州市第十五届人民代表大会常务委员会"
                 "第四十二次会议通过 第一条 为优化营商环境，制定本条例。"},
    ]
    spine = _run(
        monkeypatch, head_text=head,
        clause_text=_clause_payload([
            {"chapter": 1, "matter": "立法目的", "instruction_type": "依据陈述",
             "actor": "", "deadline": "", "basis_ref": "",
             "evidence": "第一条 为优化营商环境，制定本条例。"},
        ]),
        chunks=chunks,
    )
    sr = spine["structure_read"]
    # 层级判对:人大常委会通过的条例 = 地方性法规
    assert sr["authority"]["level"] == "地方性法规"
    # 发文字号是 N/A(法规本体无此项)→ 绝不出现在缺席信号里
    missing = [s for s in sr["signals"] if s["kind"] == "missing"]
    elements = {s["element"] for s in missing}
    assert "发文字号" not in elements, "法规 N/A 的发文字号不该报缺席(误报)"


def test_structure_read_ordering_signal_points_to_first_actor(monkeypatch):
    """排序信号:第一个带责任主体的条款 = 牵头,引到具体条款 + 主体。"""
    spine = _run(monkeypatch, head_text=_full_head(), clause_text=_full_clauses())
    ordering = [s for s in spine["structure_read"]["signals"] if s["kind"] == "ordering"]
    # _full_clauses 第 1 条 actor=各县区发展改革局,第 2/3 条无 actor → 仅 1 条有 actor,
    # 不足 2 条不报排序(避免单主体也喊"牵头")
    assert ordering == []


def test_structure_read_ordering_signal_when_multiple_actors(monkeypatch):
    """两条以上带主体 → 报排序信号,点名排第一的为牵头。"""
    clause = _clause_payload([
        {"chapter": 1, "matter": "甲办", "instruction_type": "硬要求",
         "actor": "市发改委", "deadline": "", "basis_ref": "",
         "evidence": "各县区发展改革局应当于2024年6月30日前完成本辖区补贴申报材料的汇总上报。"},
        {"chapter": 2, "matter": "乙配合", "instruction_type": "硬要求",
         "actor": "市财政局", "deadline": "", "basis_ref": "",
         "evidence": "鼓励各地结合实际探索更高效的申报方式，可以先行先试。"},
    ])
    spine = _run(monkeypatch, head_text=_full_head(), clause_text=clause)
    ordering = [s for s in spine["structure_read"]["signals"] if s["kind"] == "ordering"]
    assert len(ordering) == 1
    assert "市发改委" in ordering[0]["note"]  # 排第一的主体被点名牵头
    assert "第 1 条" in ordering[0]["element"]


def test_structure_read_weight_signal_all_soft(monkeypatch):
    """篇幅/构成信号:全软倡导、0 硬要求 → 倡导性文件(约束力弱)。"""
    clause = _clause_payload([
        {"chapter": 1, "matter": "鼓励一", "instruction_type": "软倡导",
         "actor": "", "deadline": "", "basis_ref": "",
         "evidence": "鼓励各地结合实际探索更高效的申报方式，可以先行先试。"},
        {"chapter": 2, "matter": "鼓励二", "instruction_type": "软倡导",
         "actor": "", "deadline": "", "basis_ref": "",
         "evidence": "根据《省新能源发展意见》（省发〔2023〕12号），现就有关事项通知如下。"},
    ])
    spine = _run(monkeypatch, head_text=_full_head(), clause_text=clause)
    weight = [s for s in spine["structure_read"]["signals"] if s["kind"] == "weight"]
    assert len(weight) == 1
    assert "倡导性" in weight[0]["note"]  # 全软倡导=倡导性文件


def test_structure_read_weight_signal_mostly_hard(monkeypatch):
    """硬要求占多数 → 动真格的指令件。

    _full_clauses 是 1 硬要求 / 1 软倡导 / 1 依据陈述(硬要求不过半 → 不报 weight),所以这里
    专门造一份全硬要求的来验"硬要求占多数"分支。
    """
    clause = _clause_payload([
        {"chapter": 1, "matter": "甲", "instruction_type": "硬要求",
         "actor": "", "deadline": "", "basis_ref": "",
         "evidence": "各县区发展改革局应当于2024年6月30日前完成本辖区补贴申报材料的汇总上报。"},
        {"chapter": 2, "matter": "乙", "instruction_type": "硬要求",
         "actor": "", "deadline": "", "basis_ref": "",
         "evidence": "鼓励各地结合实际探索更高效的申报方式，可以先行先试。"},
    ])
    spine2 = _run(monkeypatch, head_text=_full_head(), clause_text=clause)
    weight = [s for s in spine2["structure_read"]["signals"] if s["kind"] == "weight"]
    assert len(weight) == 1
    assert "动真格" in weight[0]["note"]


def test_structure_read_absent_when_no_doc_type(monkeypatch):
    """文种都没抽到(判不了层级)→ 不挂 structure_read(向后兼容,不硬造)。"""
    head = _head_payload([
        {"field": "发文机关", "value": "某委", "evidence": "某委文件"},
    ])
    spine = _run(monkeypatch, head_text=head, clause_text=_full_clauses())
    # 文种空 → structure_read 不出现(可选字段)
    assert "structure_read" not in spine


def test_structure_read_verified_basis_false_when_unverified(monkeypatch):
    """权威刻度依据(文种/机关)没核过 → verified_basis=False(研判依据更薄,前端可据此弱化)。"""
    # 文种 evidence 原文里没有 → 核不过
    head = _head_payload([
        {"field": "文种", "value": "通知", "evidence": "这句原文里压根没有这文种出处。"},
        {"field": "发文机关", "value": "市发展改革委", "evidence": "市发展改革委文件"},
    ])
    spine = _run(monkeypatch, head_text=head, clause_text=_full_clauses())
    assert spine["structure_read"]["authority"]["verified_basis"] is False


def test_classify_authority_pure():
    """_classify_authority 纯件:封闭集 + 兜底。"""
    assert ds._classify_authority("令", "") == "公布令/法规"
    assert ds._classify_authority("办法", "某部") == "部门规章/规范性文件"
    assert ds._classify_authority("条例", "某省人民代表大会常务委员会") == "地方性法规"
    assert ds._classify_authority("条例", "国务院") == "公布令/法规"  # 中央本级条例
    assert ds._classify_authority("通知", "") == ds._DEFAULT_AUTHORITY_LEVEL
    assert ds._classify_authority("", "") == ds._DEFAULT_AUTHORITY_LEVEL  # 空退兜底
