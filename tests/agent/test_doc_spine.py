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


# ── 骨架鸟瞰:build_doc_head_only 只建 head，跳条款 map-reduce（#43 公文结构秒出）──
def test_head_only_skips_clause_mapreduce(monkeypatch):
    """公文结构骨架:只建 head + structure_read，绝不跑条款维 run_segments(那两分钟的活)。"""
    _patch(monkeypatch, head_text=_full_head(), clause_text=_full_clauses())

    # 条款维走 run_segments;head-only 绝不该碰它——patch 成一炸,碰到即 fail。
    def _boom(*_a, **_k):  # noqa: ANN002, ANN003, ANN202
        raise AssertionError("build_doc_head_only 不该调 run_segments(条款 map-reduce)")

    monkeypatch.setattr(ds, "run_segments", _boom)
    spine = ds.build_doc_head_only(
        chunks=_CHUNKS, llm_client=_FakeClient(), model="deepseek-v4-flash"
    )
    assert spine["clauses"] == []  # 没建任何条款
    assert spine["head_only"] is True
    # head 骨架齐(8 要素全出,同 build_doc_spine)
    assert len(spine["head"]) == len(ds._HEAD_FIELDS)
    # structure_read 从 head 推:authority 的 doc_type = 文种「通知」(不依赖条款)
    assert spine.get("structure_read") is not None
    assert spine["structure_read"]["authority"]["doc_type"] == "通知"


def test_head_only_no_wenzhong_no_structure_read(monkeypatch):
    """文种没抽到 → 没判层级的根基 → 无 structure_read（同 build_doc_spine，不硬造）。"""
    head_no_wenzhong = _head_payload([
        {"field": "发文机关", "value": "某局", "evidence": "某局文件"},
    ])
    _patch(monkeypatch, head_text=head_no_wenzhong, clause_text=_full_clauses())
    monkeypatch.setattr(ds, "run_segments", lambda *_a, **_k: (_ for _ in ()).throw(
        AssertionError("head-only 不该跑条款")))
    spine = ds.build_doc_head_only(
        chunks=_CHUNKS, llm_client=_FakeClient(), model="deepseek-v4-flash"
    )
    assert spine["clauses"] == []
    assert "structure_read" not in spine  # 文种空,不硬造


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


# ── 叙述体公文支持(v3):公报/意见把每个原则/部署抽一条,不压成一条 ──────────────────
def test_fangzhen_bushu_is_a_valid_instruction_type():
    """新增「方针部署」进了指令类型封闭集(收叙述体公文的原则/方向/部署点)。"""
    assert "方针部署" in ds.INSTRUCTION_TYPES
    assert ds._coerce_instruction_type("方针部署") == "方针部署"


def test_clause_prompt_handles_narrative_bulletin():
    """条款维 prompt 明确教模型:叙述体公文(公报/意见)按原则/部署逐条抽,别压成一条。"""
    instr = ds._INSTR_CLAUSE
    # 认两类写法 + 叙述体专门教法
    assert "分条式" in instr and "叙述体" in instr
    # 六项原则要抽成六条、绝不压成一条空泛的「遵循以下原则」
    assert "遵循以下原则" in instr
    assert "压成一条" in instr or "绝不压成" in instr
    # 没有责任主体/时限也照抽(叙述体常缺)
    assert "没有责任主体" in instr or "缺主体缺时限" in instr
    # 新指令类型在 prompt 里
    assert "方针部署" in instr


def test_narrative_six_principles_extracted_as_six_clauses(monkeypatch):
    """模拟公报「六项原则」:模型把六个「坚持X」各抽一条 → 六条都保住、各带原文撑,
    绝不退化成一条。每条 instruction_type=方针部署、无主体无时限留空、不编代价。"""
    chunks = [
        {"chunk_id": "h0", "chapter": 0,
         "text": "中国共产党第二十届中央委员会第四次全体会议公报"},
        {"chunk_id": "c1", "chapter": 0,
         "text": "全会指出，必须遵循以下原则，坚持党的全面领导，坚持人民至上，"
                 "坚持高质量发展，坚持全面深化改革，坚持有效市场和有为政府相结合，"
                 "坚持统筹发展和安全。"},
    ]
    principles = [
        ("坚持党的全面领导", "坚持党的全面领导"),
        ("坚持人民至上", "坚持人民至上"),
        ("坚持高质量发展", "坚持高质量发展"),
        ("坚持全面深化改革", "坚持全面深化改革"),
        ("坚持有效市场和有为政府相结合", "坚持有效市场和有为政府相结合"),
        ("坚持统筹发展和安全", "坚持统筹发展和安全"),
    ]
    clauses = _clause_payload([
        {"chapter": i, "matter": matter, "instruction_type": "方针部署",
         "actor": "", "deadline": "", "basis_ref": "",
         "substance": "空头倡导", "substance_reason": "纯原则无数字无时限无主体无罚则",
         "penalty": "",
         "evidence": ev}
        for i, (matter, ev) in enumerate(principles, start=1)
    ])
    spine = _run(monkeypatch, head_text=_head_payload([
        {"field": "文种", "value": "公报", "evidence": "全体会议公报"},
    ]), clause_text=clauses, chunks=chunks)
    # 六条原则全保住,没压成一条
    assert len(spine["clauses"]) == 6
    for c in spine["clauses"]:
        assert c["instruction_type"] == "方针部署"
        assert c["actor"] == ""  # 叙述体原则无责任主体,留空不编
        assert c["deadline"] == ""  # 无时限,留空不编
        assert c["penalty"] == ""  # 无罚则,留空不编
        assert c["evidence"]  # 每条钉到对应那半句原文
        assert c["verified"] is True  # evidence 命中合成原文


def test_narrative_clause_substance_not_forced_real_money(monkeypatch):
    """死守:叙述体方针部署口气坚定(坚持/必须)但无配套兑现 → 不该判真金白银。
    模型若误判真金白银,coerce 不拦(它是合法档),但 prompt 已明示别只看语气;这里验
    模型按 prompt 给空头/有条件兑现时如实保留。"""
    clauses = _clause_payload([
        {"chapter": 1, "matter": "坚持高质量发展", "instruction_type": "方针部署",
         "actor": "", "deadline": "", "basis_ref": "",
         "substance": "空头倡导", "substance_reason": "方向性号召,无数字时限主体罚则",
         "penalty": "",
         "evidence": "坚持高质量发展"},
    ])
    chunks = [
        {"chunk_id": "h0", "chapter": 0, "text": "公报。坚持高质量发展。"},
    ]
    spine = _run(monkeypatch, head_text=_head_payload([
        {"field": "文种", "value": "公报", "evidence": "公报"},
    ]), clause_text=clauses, chunks=chunks)
    assert spine["clauses"][0]["substance"] == "空头倡导"


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


def test_notice_head_status_three_states(monkeypatch):
    """普通公文(通知)的空值三态(task #29 根一):
    密级/紧急程度空=确证为无(公开件/平件,absent_confirmed),不是待核;
    主送机关/抄送机关空=真没抽到(unverified,前端显待核);
    抽到的(发文字号/文种/发文机关/成文日期/签发人)=present。
    """
    spine = _run(monkeypatch, head_text=_full_head(), clause_text=_full_clauses())
    by_field = {el["field"]: el for el in spine["head"]}
    # 密级/紧急程度:公文格式规则下确证为无 → absent_confirmed + reason,不是待核
    assert by_field["密级"]["status"] == "absent_confirmed"
    assert by_field["密级"]["reason"] == "公开件无密级"
    assert by_field["密级"].get("not_applicable") is True  # 旧字段对齐:不计分母
    assert by_field["紧急程度"]["status"] == "absent_confirmed"
    assert by_field["紧急程度"]["reason"] == "平件(未标紧急)"
    # 主送/抄送机关:通知该有却没抽到 → unverified(真待核)
    assert by_field["主送机关"]["status"] == "unverified"
    assert by_field["主送机关"].get("not_applicable") is not True
    assert by_field["抄送机关"]["status"] == "unverified"
    # 抽到的要素 = present
    for f in ("发文字号", "文种", "发文机关", "成文日期", "签发人"):
        assert by_field[f]["status"] == "present", f"{f} 抽到了该 present"


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


# ═══════════════════════════════════════════════════════════════════════════════
# task #29 根一:头要素空值三态(present / absent_confirmed / unverified)
# 设计稿 docs/design/WP-evidence-empty-semantics.md §根一。"空"不再一律落"待核":
# 据公文格式规则把"确证为无"标 absent_confirmed + reason,真没抽到才退 unverified。
# ═══════════════════════════════════════════════════════════════════════════════


def test_head_status_field_exists_for_all_elements(monkeypatch):
    """每个头要素都带 status(三态之一)+ reason 字段(纯增,向后兼容)。"""
    spine = _run(monkeypatch, head_text=_full_head(), clause_text=_full_clauses())
    for el in spine["head"]:
        assert "status" in el and "reason" in el
        assert el["status"] in ds.HEAD_STATUSES


def test_head_status_present_when_extracted(monkeypatch):
    """抽到了的要素 = present(reason 空)。"""
    spine = _run(monkeypatch, head_text=_full_head(), clause_text=_full_clauses())
    by_field = {el["field"]: el for el in spine["head"]}
    assert by_field["发文字号"]["status"] == "present"
    assert by_field["发文字号"]["reason"] == ""


def test_head_status_classification_absent_confirmed(monkeypatch):
    """密级/紧急程度空 = 确证为无(公开件/平件),带站得住的 reason,前端显笃定不是待核。"""
    spine = _run(monkeypatch, head_text=_full_head(), clause_text=_full_clauses())
    by_field = {el["field"]: el for el in spine["head"]}
    assert by_field["密级"]["status"] == "absent_confirmed"
    assert by_field["密级"]["reason"] == "公开件无密级"
    assert by_field["紧急程度"]["status"] == "absent_confirmed"
    assert by_field["紧急程度"]["reason"] == "平件(未标紧急)"


def test_head_status_signoff_absent_confirmed_for_downward(monkeypatch):
    """下行文(通知)无签发人栏 = absent_confirmed(GB/T 只上行文要签发人)。
    _full_head 里签发人抽到了,这里专造一份签发人空的通知验确证为无分支。"""
    head = _head_payload([
        {"field": "文种", "value": "通知", "evidence": "关于做好新能源补贴申报的通知"},
        {"field": "发文机关", "value": "市发展改革委", "evidence": "市发展改革委文件"},
        # 签发人不给 → 通知是下行文,本就没签发人栏
    ])
    spine = _run(monkeypatch, head_text=head, clause_text=_full_clauses())
    by_field = {el["field"]: el for el in spine["head"]}
    assert by_field["签发人"]["status"] == "absent_confirmed"
    assert by_field["签发人"]["reason"] == "此文种无签发人栏"


def test_head_status_signoff_unverified_for_upward(monkeypatch):
    """上行文(请示)该有签发人却空 = unverified(真没抽到,退待核,绝不硬判'确证无')。
    这是 evidence-first 死守:拿不准是不是该有,就退 unverified。"""
    head = _head_payload([
        {"field": "文种", "value": "请示", "evidence": "关于xx的请示"},
        {"field": "发文机关", "value": "某县政府", "evidence": "某县政府文件"},
        # 签发人空 → 上行文该有签发人,空着是真没抽到
    ])
    spine = _run(
        monkeypatch, head_text=head,
        clause_text=_clause_payload([
            {"chapter": 1, "matter": "请求批准", "instruction_type": "依据陈述",
             "actor": "", "deadline": "", "basis_ref": "",
             "evidence": "各县区发展改革局应当于2024年6月30日前完成本辖区补贴申报材料的汇总上报。"},
        ]),
    )
    by_field = {el["field"]: el for el in spine["head"]}
    assert by_field["签发人"]["status"] == "unverified", "上行文缺签发人=真待核,不准判确证无"
    assert by_field["签发人"].get("not_applicable") is not True


def test_head_status_unverified_for_real_miss(monkeypatch):
    """主送机关(没有公文格式规则说它本就没有)空 = unverified(真没抽到 → 待核)。"""
    spine = _run(monkeypatch, head_text=_full_head(), clause_text=_full_clauses())
    by_field = {el["field"]: el for el in spine["head"]}
    assert by_field["主送机关"]["status"] == "unverified"
    assert by_field["主送机关"]["reason"] == ""


def test_head_status_regulation_na_is_absent_confirmed(monkeypatch):
    """法规本体(条例)的发文要素空 = absent_confirmed(法规本体无此发文要素),不是待核。"""
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
    # 法规本体的发文字号/密级/签发人等 → 确证为无(法规本体无此发文要素),不待核
    for f in ("发文字号", "密级", "签发人"):
        assert by_field[f]["status"] == "absent_confirmed", f"{f} 该确证为无"
        assert by_field[f]["reason"] == "法规本体无此发文要素"
        assert by_field[f].get("not_applicable") is True


def test_confirmed_absent_reason_pure():
    """_confirmed_absent_reason 纯件:确证为无给依据,拿不准返 None(退待核)。"""
    # 密级/紧急程度:任何文种空着都是确证为无
    assert ds._confirmed_absent_reason("密级", "通知") == "公开件无密级"
    assert ds._confirmed_absent_reason("紧急程度", "通知") == "平件(未标紧急)"
    # 签发人:下行/平行文确证无,上行文返 None(该有却没抽到 → 待核)
    assert ds._confirmed_absent_reason("签发人", "通知") == "此文种无签发人栏"
    assert ds._confirmed_absent_reason("签发人", "函") == "此文种无签发人栏"
    assert ds._confirmed_absent_reason("签发人", "请示") is None  # 上行文该有
    assert ds._confirmed_absent_reason("签发人", "报告") is None
    # 法规本体:发文要素都确证无(优先级最高,密级也走法规这条)
    assert ds._confirmed_absent_reason("发文字号", "条例") == "法规本体无此发文要素"
    assert ds._confirmed_absent_reason("密级", "条例") == "法规本体无此发文要素"
    # 没有格式规则兜底的字段 → None(退待核)
    assert ds._confirmed_absent_reason("主送机关", "通知") is None
    assert ds._confirmed_absent_reason("发文字号", "通知") is None


def test_classify_head_status_pure():
    """_classify_head_status 纯件:有值=present、确证无=absent_confirmed、其余=unverified。"""
    assert ds._classify_head_status("发文字号", "X发〔2024〕5号", "通知") == (
        "present", "")
    assert ds._classify_head_status("密级", "", "通知") == (
        "absent_confirmed", "公开件无密级")
    assert ds._classify_head_status("主送机关", "", "通知") == ("unverified", "")


# ═══════════════════════════════════════════════════════════════════════════════
# task #29 根二:效力研判吃发文机关行政层级
# 设计稿 §根二。光按文种一刀切会把国办《意见》判成"一般公文、容易被覆盖"——错。
# 高层级(国务院/国办/部委/省级)文件要点出权威范围,绝不说"容易被上位覆盖"。
# ═══════════════════════════════════════════════════════════════════════════════


def test_classify_agency_level_pure():
    """_classify_agency_level 纯件:最高/高/中低/空。"""
    # 最高:国务院/国办/中共中央/全国人大
    assert ds._classify_agency_level("国务院") == "最高"
    assert ds._classify_agency_level("国务院办公厅") == "最高"
    assert ds._classify_agency_level("中共中央办公厅") == "最高"
    assert ds._classify_agency_level("全国人民代表大会常务委员会") == "最高"
    # 高:部委(国家级)、省级
    assert ds._classify_agency_level("教育部") == "高"
    assert ds._classify_agency_level("国家发展和改革委员会") == "高"
    assert ds._classify_agency_level("广东省人民政府") == "高"
    # 中低:市/县
    assert ds._classify_agency_level("广州市人民政府") == "中低"
    assert ds._classify_agency_level("某县发展改革局") == "中低"
    # 市优先于省:"广东省广州市..."以更低的市为准
    assert ds._classify_agency_level("广东省广州市人民政府") == "中低"
    # 判不出 → 空串
    assert ds._classify_agency_level("") == ""
    assert ds._classify_agency_level("xx办公室") == ""


def test_structure_read_carries_agency_level(monkeypatch):
    """structure_read.authority 带 agency_level(据已抽发文机关判)。"""
    spine = _run(monkeypatch, head_text=_full_head(), clause_text=_full_clauses())
    # _full_head 发文机关=市发展改革委 → 中低
    assert spine["structure_read"]["authority"]["agency_level"] == "中低"


def test_top_agency_yi_jian_not_called_general_doc(monkeypatch):
    """触发实例:国务院办公厅《意见》——文种维度归'一般公文',但发文机关是最高层级 →
    appraisal 必须点出全国约束力、绝不说'容易被上位覆盖/一般公文'。这是根二的命门。"""
    head = _head_payload([
        {"field": "文种", "value": "意见", "evidence": "国务院办公厅关于xx的意见"},
        {"field": "发文机关", "value": "国务院办公厅",
         "evidence": "国务院办公厅关于xx的意见"},
    ])
    chunks = [
        {"chunk_id": "h0", "chapter": 0,
         "text": "国务院办公厅关于xx的意见 各省、自治区、直辖市人民政府……"},
        {"chunk_id": "c1", "chapter": 1,
         "text": "各县区发展改革局应当于2024年6月30日前完成本辖区补贴申报材料的汇总上报。"},
    ]
    spine = _run(monkeypatch, head_text=head, clause_text=_full_clauses(), chunks=chunks)
    auth = spine["structure_read"]["authority"]
    # 文种维度的层级标签仍是"一般公文"(意见 by 文种就是),但 agency_level=最高
    assert auth["agency_level"] == "最高"
    # appraisal 被高层级覆盖:点出全国约束,绝不出现"容易被覆盖/可有可无"那套
    assert "全国" in auth["appraisal"]
    assert "容易被" not in auth["appraisal"]
    assert "最高层级" in auth["appraisal"]


def test_high_agency_appraisal_override(monkeypatch):
    """部委/省级(高层级)的通知/意见 → appraisal 点出本系统权威,不说'容易被覆盖'。"""
    head = _head_payload([
        {"field": "文种", "value": "通知", "evidence": "教育部关于xx的通知"},
        {"field": "发文机关", "value": "教育部", "evidence": "教育部关于xx的通知"},
    ])
    chunks = [
        {"chunk_id": "h0", "chapter": 0, "text": "教育部关于xx的通知 各省教育厅……"},
        {"chunk_id": "c1", "chapter": 1,
         "text": "各县区发展改革局应当于2024年6月30日前完成本辖区补贴申报材料的汇总上报。"},
    ]
    spine = _run(monkeypatch, head_text=head, clause_text=_full_clauses(), chunks=chunks)
    auth = spine["structure_read"]["authority"]
    assert auth["agency_level"] == "高"
    assert "容易被" not in auth["appraisal"]
    assert "高层级" in auth["appraisal"]


def test_mid_agency_keeps_doctype_appraisal(monkeypatch):
    """中低层级(市/县)通知 → 不覆盖,仍用文种维度的'一般公文'研判(包含'容易被覆盖')。
    根二只给高层级翻案,不动中低层级的诚实研判。"""
    spine = _run(monkeypatch, head_text=_full_head(), clause_text=_full_clauses())
    auth = spine["structure_read"]["authority"]
    # _full_head 发文机关=市发展改革委(中低)
    assert auth["agency_level"] == "中低"
    assert auth["level"] == "一般公文"
    # 中低层级保留文种维度的研判(一般公文 = 能管到主送机关但容易被覆盖)
    assert auth["appraisal"] == ds._AUTHORITY_APPRAISAL["一般公文"]


def test_high_authority_appraisal_pure():
    """_high_authority_appraisal 纯件:最高/高给覆盖句,中低/空返 None。"""
    top = ds._high_authority_appraisal("最高", "国务院办公厅")
    assert top is not None and "全国" in top and "容易被" not in top
    high = ds._high_authority_appraisal("高", "教育部")
    assert high is not None and "容易被" not in high
    assert ds._high_authority_appraisal("中低", "广州市人民政府") is None
    assert ds._high_authority_appraisal("", "") is None
