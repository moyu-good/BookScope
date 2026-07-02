"""公文大白话翻译 redhead_plain 单测(1.6 二炮 + #22 全文逐句 + 弦外之意注解)。

合成一份红头文件的 chunk + 整份原文 + mock(假 client + monkeypatch 文脉 / invoke_client_cached),
覆盖:

clauses 模式(默认,向后兼容):
- 逐条款摘译,白话锚原文核验(命中盖鉴印),改写失败退回原事项。
- 命中措辞刻度的条挂 nuance,没命中不挂。
- mode 默认就是 clauses;响应带 mode 字段。

fulltext 模式(#22):
- 整份原文按句切段并发顺译,每句一对(seq/original/plain/evidence),按原文顺序连续编号。
- 每句原文过核验;命中 marker 的句挂 nuance、没命中不挂。
- 截断抢救(salvage)、解析不出返空、空全文优雅退场。

分段:_segment_fulltext 不在句中切、按字符预算攒整句成段。

不跑真 LLM。
"""

from __future__ import annotations

import json

from bookscope.agent import redhead_plain as rp
from bookscope.agent.redhead_codebook import clause_is_pure_statement

# ── 合成红头文件 ──────────────────────────────────────────────────────────────
_HEAD = "市市场监管局文件 X监发〔2024〕7号 关于优化营商环境的通知。"
# 硬约束句(无 marker,nuance 该为空)。
_HARD = "各区局应当于2024年9月30日前为新登记个体户减免登记费每户200元。"
# 留口子句(命中「结合实际」)。
_LOOPHOLE = "各地结合实际简化新设企业材料要求。"
# 搁置句(命中「逐步」)。
_SHELVE = "鼓励各地逐步推广电子证照应用。"

_FULL_TEXT = _HEAD + _HARD + _LOOPHOLE + _SHELVE

_CHUNKS = [
    {"chunk_id": "h0", "chapter": 0, "text": _HEAD},
    {"chunk_id": "c1", "chapter": 1, "text": _HARD},
    {"chunk_id": "c2", "chapter": 2, "text": _LOOPHOLE},
    {"chunk_id": "c3", "chapter": 3, "text": _SHELVE},
]


class _FakeClient:
    def extract_final_text(self, resp):  # noqa: ANN001, ANN201
        return resp if isinstance(resp, str) else "{}"


def _patch_invoke(monkeypatch, canned):
    """把 invoke_client_cached patch 成返 canned(字符串 = 所有调用同一段;list = 按调用序逐段返)。"""
    if isinstance(canned, list):
        seq = iter(canned)

        def _fake(*_a, **_kw):  # noqa: ANN002, ANN003, ANN202
            return next(seq)
    else:
        def _fake(*_a, **_kw):  # noqa: ANN002, ANN003, ANN202
            return canned
    monkeypatch.setattr(rp, "invoke_client_cached", _fake)


def _patch_spine(monkeypatch, clauses):
    """把 get_or_build_doc_spine patch 成返带 clauses 的文脉(不跑真精读)。"""
    def _fake(**_kw):  # noqa: ANN003, ANN202
        return {"head": [], "clauses": clauses}
    monkeypatch.setattr(rp, "get_or_build_doc_spine", _fake)


# ── #5 复读根因:纯表态条款不复读、不调 LLM(WP-redhead-substance-vs-slogan) ──────

def _clause(**kw):
    """一条默认「纯表态」条款(方针部署 + 空头 + 三空);传 kw 覆盖某字段成实质。"""
    base = {
        "instruction_type": "方针部署",
        "substance": "空头倡导",
        "actor": "",
        "deadline": "",
        "penalty": "",
        "matter": "以重度残疾人及其家庭需求为导向",
        "evidence": "坚持以重度残疾人及其家庭需求为导向。",
    }
    base.update(kw)
    return base


class TestPureStatementJudge:
    """clause_is_pure_statement 组合判据:五条全命中才纯表态,任一不满足即实质(偏保守)。"""

    def test_all_five_met_is_pure_statement(self):
        assert clause_is_pure_statement(_clause()) is True

    def test_has_actor_is_substantive(self):
        assert clause_is_pure_statement(_clause(actor="民政部")) is False

    def test_has_deadline_is_substantive(self):
        assert clause_is_pure_statement(_clause(deadline="2025年底前")) is False

    def test_has_penalty_is_substantive(self):
        assert clause_is_pure_statement(_clause(penalty="予以通报")) is False

    def test_substance_not_hollow_is_substantive(self):
        assert clause_is_pure_statement(_clause(substance="真金白银")) is False

    def test_not_directive_type_is_substantive(self):
        assert clause_is_pure_statement(_clause(instruction_type="硬要求")) is False


class TestRewriteOnePureStatementBranch:
    """_rewrite_one:纯表态直接给固定说明句、不调 LLM;实质条款才走改写。"""

    def test_pure_statement_returns_template_without_llm(self, monkeypatch):
        # invoke_client_cached 一被调用就炸——证纯表态分支根本没走 LLM。
        def _boom(*_a, **_kw):  # noqa: ANN002, ANN003, ANN202
            raise AssertionError("纯表态条款不该调 LLM")

        monkeypatch.setattr(rp, "invoke_client_cached", _boom)
        out = rp._rewrite_one(
            _clause(),
            llm_client=_FakeClient(),
            model="x",
            max_tokens=1200,
            cache_enabled=False,
        )
        assert out == rp.PURE_STATEMENT_PLAIN

    def test_substantive_clause_calls_llm(self, monkeypatch):
        _patch_invoke(monkeypatch, "得在2025年底前把这事办成。")
        out = rp._rewrite_one(
            _clause(
                instruction_type="硬要求",
                substance="真金白银",
                deadline="2025年底前",
            ),
            llm_client=_FakeClient(),
            model="x",
            max_tokens=1200,
            cache_enabled=False,
        )
        assert out == "得在2025年底前把这事办成。"


def _patch_finish_reason(monkeypatch, reason):
    """把 read_openai_finish_reason patch 成固定返回(测截断分支)。"""
    monkeypatch.setattr(rp, "read_openai_finish_reason", lambda _r: reason)


# ════════════════════════════════════════════════════════════════════════════
# clauses 模式(默认)
# ════════════════════════════════════════════════════════════════════════════

def test_clauses_default_mode_and_schema(monkeypatch):
    """不传 mode = clauses;响应带 mode + schema v2。"""
    _patch_spine(monkeypatch, [
        {"chapter": 1, "matter": "登记费减免", "evidence": _HARD},
    ])
    _patch_invoke(monkeypatch, "得在2024年9月30日前给新登记个体户每户减免200元登记费。")
    out = rp.plain_language_from_spine(
        chunks=_CHUNKS, llm_client=_FakeClient(), model="deepseek-v4-flash",
        full_text=_FULL_TEXT,
    )
    assert out["schema_version"] == rp.PLAIN_SCHEMA_VERSION == "v2"
    assert out["mode"] == "clauses"
    assert len(out["items"]) == 1
    it = out["items"][0]
    for k in ("chapter", "matter", "plain", "evidence", "verified", "match_score"):
        assert k in it, f"clauses 条缺字段 {k}"


def test_clauses_verified_when_in_original(monkeypatch):
    """白话背后的原文 evidence 命中合成原文 → verified=True 盖鉴印。"""
    _patch_spine(monkeypatch, [{"chapter": 1, "matter": "减免", "evidence": _HARD}])
    _patch_invoke(monkeypatch, "得在9月30日前减免每户200元。")
    out = rp.plain_language_from_spine(
        chunks=_CHUNKS, llm_client=_FakeClient(), model="m", full_text=_FULL_TEXT,
    )
    assert out["items"][0]["verified"] is True
    assert out["items"][0]["plain"] == "得在9月30日前减免每户200元。"


def test_clauses_rewrite_failure_falls_back_to_matter(monkeypatch):
    """改写返空(LLM 给空串)→ plain 退回原事项,不假装翻好了。"""
    _patch_spine(monkeypatch, [{"chapter": 1, "matter": "原事项摆这", "evidence": _HARD}])
    _patch_invoke(monkeypatch, "")  # 改写失败
    out = rp.plain_language_from_spine(
        chunks=_CHUNKS, llm_client=_FakeClient(), model="m", full_text=_FULL_TEXT,
    )
    assert out["items"][0]["plain"] == "原事项摆这"


def test_clauses_nuance_attached_on_marker_hit(monkeypatch):
    """条款原文命中「结合实际」→ 挂 nuance;命中「逐步」的另一条也挂;硬约束句不挂。"""
    _patch_spine(monkeypatch, [
        {"chapter": 1, "matter": "硬约束", "evidence": _HARD},        # 无 marker
        {"chapter": 2, "matter": "材料", "evidence": _LOOPHOLE},      # 结合实际
        {"chapter": 3, "matter": "证照", "evidence": _SHELVE},        # 逐步
    ])
    _patch_invoke(monkeypatch, "白话")
    out = rp.plain_language_from_spine(
        chunks=_CHUNKS, llm_client=_FakeClient(), model="m", full_text=_FULL_TEXT,
    )
    items = out["items"]
    # 第一条无 marker → 不挂 nuance 字段
    assert "nuance" not in items[0]
    # 第二条命中结合实际
    assert items[1]["nuance"][0]["marker"] == "结合实际"
    # 第三条命中逐步
    assert items[2]["nuance"][0]["marker"] == "逐步"


def test_clauses_empty_when_no_clauses(monkeypatch):
    """文脉没拆出条款 → items 空,优雅退场。"""
    _patch_spine(monkeypatch, [])
    out = rp.plain_language_from_spine(
        chunks=_CHUNKS, llm_client=_FakeClient(), model="m", full_text=_FULL_TEXT,
    )
    assert out["mode"] == "clauses"
    assert out["items"] == []


# ════════════════════════════════════════════════════════════════════════════
# fulltext 模式(#22)
# ════════════════════════════════════════════════════════════════════════════

def _fulltext_pairs_payload() -> str:
    """一段顺译:四句原文各一对(原文逐字引合成原文里的句子,核得到)。"""
    return json.dumps({
        "pairs": [
            {"original": "市市场监管局文件 X监发〔2024〕7号 关于优化营商环境的通知。",
             "plain": "这是市市场监管局发的关于优化营商环境的通知。"},
            {"original": "各区局应当于2024年9月30日前为新登记个体户减免登记费每户200元。",
             "plain": "各区局得在2024年9月30日前给新登记个体户每户减免200元登记费。"},
            {"original": "各地结合实际简化新设企业材料要求。",
             "plain": "新设企业一般不用再交纸质材料了。"},
            {"original": "鼓励各地逐步推广电子证照应用。",
             "plain": "鼓励各地慢慢推开电子证照。"},
        ],
    }, ensure_ascii=False)


def test_fulltext_basic_structure_and_order(monkeypatch):
    """全文模式:逐句对照,seq 从 1 连续编号,字段齐全,schema/mode 对。"""
    _patch_spine(monkeypatch, [])  # 文脉只为触发缓存,fulltext 不拆它
    _patch_invoke(monkeypatch, _fulltext_pairs_payload())
    out = rp.plain_language_from_spine(
        chunks=_CHUNKS, llm_client=_FakeClient(), model="m",
        full_text=_FULL_TEXT, mode="fulltext",
    )
    assert out["schema_version"] == "v2"
    assert out["mode"] == "fulltext"
    items = out["items"]
    assert len(items) == 4
    assert [it["seq"] for it in items] == [1, 2, 3, 4]  # 连续编号
    for it in items:
        for k in ("seq", "original", "plain", "evidence", "verified", "match_score"):
            assert k in it, f"fulltext 句缺字段 {k}"
        # evidence 就是这句逐字原文
        assert it["evidence"] == it["original"]


def test_fulltext_verified_and_nuance(monkeypatch):
    """全文模式:每句原文命中合成原文 → verified;命中 marker 的句挂 nuance、没命中不挂。"""
    _patch_spine(monkeypatch, [])
    _patch_invoke(monkeypatch, _fulltext_pairs_payload())
    out = rp.plain_language_from_spine(
        chunks=_CHUNKS, llm_client=_FakeClient(), model="m",
        full_text=_FULL_TEXT, mode="fulltext",
    )
    items = out["items"]
    assert all(it["verified"] for it in items)  # 四句都逐字命中
    # 第1、2句无 marker → 不挂
    assert "nuance" not in items[0]
    assert "nuance" not in items[1]
    # 第3句命中「结合实际」
    assert items[2]["nuance"][0]["marker"] == "结合实际"
    # 第4句命中「逐步」
    assert items[3]["nuance"][0]["marker"] == "逐步"


def test_fulltext_plain_fallback_to_original(monkeypatch):
    """某句 plain 空 → 退回原文摆着,不假装翻好了。"""
    _patch_spine(monkeypatch, [])
    canned = json.dumps({
        "pairs": [{"original": _HARD, "plain": ""}],  # plain 空
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch, canned)
    out = rp.plain_language_from_spine(
        chunks=_CHUNKS, llm_client=_FakeClient(), model="m",
        full_text=_FULL_TEXT, mode="fulltext",
    )
    assert out["items"][0]["plain"] == _HARD


def test_fulltext_concurrent_segments_keep_order(monkeypatch):
    """全文按字符预算切成多段并发,concat 后句序仍是原文序、seq 连续。

    char_budget 设小,逼出多段;两段各返自己的句对,验顺序拼接。
    """
    _patch_spine(monkeypatch, [])
    # 段1(前两句)、段2(后两句)——按调用序逐段返
    seg1 = json.dumps({"pairs": [
        {"original": _HEAD, "plain": "通知抬头。"},
        {"original": _HARD, "plain": "减免200元。"},
    ]}, ensure_ascii=False)
    seg2 = json.dumps({"pairs": [
        {"original": _LOOPHOLE, "plain": "不用交纸质材料。"},
        {"original": _SHELVE, "plain": "慢慢推电子证照。"},
    ]}, ensure_ascii=False)
    _patch_invoke(monkeypatch, [seg1, seg2])
    # char_budget 设到只能装一两句 → 切多段;workers=1 保串行可预测调用序
    out = rp.plain_language_from_spine(
        chunks=_CHUNKS, llm_client=_FakeClient(), model="m",
        full_text=_FULL_TEXT, mode="fulltext", char_budget=40, max_workers=1,
    )
    items = out["items"]
    assert [it["seq"] for it in items] == [1, 2, 3, 4]
    # 原文顺序:抬头 → 减免 → 留口子 → 逐步
    assert items[0]["original"] == _HEAD
    assert items[3]["original"] == _SHELVE


def test_fulltext_truncation_salvage(monkeypatch):
    """截断(finish_reason=length)+ 半截 JSON → salvage 抢回已闭合的句对。"""
    _patch_spine(monkeypatch, [])
    _patch_finish_reason(monkeypatch, "length")
    # 两个完整对象 + 第三个被截断(没闭合)→ salvage 抢前两个
    truncated = (
        '{"pairs":[{"original":"' + _HEAD + '","plain":"抬头。"},'
        '{"original":"' + _HARD + '","plain":"减免。"},'
        '{"original":"' + _LOOPHOLE + '","plain":"不用交材'  # 截断
    )
    _patch_invoke(monkeypatch, truncated)
    out = rp.plain_language_from_spine(
        chunks=_CHUNKS, llm_client=_FakeClient(), model="m",
        full_text=_FULL_TEXT, mode="fulltext",
    )
    # 抢回前两句(第三句被截断丢)
    assert len(out["items"]) == 2
    assert out["items"][0]["original"] == _HEAD
    assert out["items"][1]["original"] == _HARD


def test_fulltext_unparseable_returns_empty(monkeypatch):
    """完全解析不出 → items 空,不报错。"""
    _patch_spine(monkeypatch, [])
    _patch_invoke(monkeypatch, "这根本不是 JSON")
    out = rp.plain_language_from_spine(
        chunks=_CHUNKS, llm_client=_FakeClient(), model="m",
        full_text=_FULL_TEXT, mode="fulltext",
    )
    assert out["mode"] == "fulltext"
    assert out["items"] == []


def test_fulltext_empty_source_returns_empty(monkeypatch):
    """全文空(无 full_text 且 chunks 文本空)→ 优雅退场,不跑顺译。"""
    def _boom(*_a, **_kw):  # noqa: ANN002, ANN003, ANN202
        raise AssertionError("空全文不该调顺译")
    _patch_spine(monkeypatch, [])
    monkeypatch.setattr(rp, "invoke_client_cached", _boom)
    empty_chunks = [{"chunk_id": "x", "chapter": 0, "text": "   "}]
    out = rp.plain_language_from_spine(
        chunks=empty_chunks, llm_client=_FakeClient(), model="m", mode="fulltext",
    )
    assert out["items"] == []


def test_fulltext_strips_code_fence(monkeypatch):
    """带 markdown 围栏照样解析。"""
    _patch_spine(monkeypatch, [])
    fenced = "```json\n" + _fulltext_pairs_payload() + "\n```"
    _patch_invoke(monkeypatch, fenced)
    out = rp.plain_language_from_spine(
        chunks=_CHUNKS, llm_client=_FakeClient(), model="m",
        full_text=_FULL_TEXT, mode="fulltext",
    )
    assert len(out["items"]) == 4


def test_fulltext_drops_pair_without_original(monkeypatch):
    """句对缺 original(没核验锚)→ 丢这对;有 original 的留。"""
    _patch_spine(monkeypatch, [])
    canned = json.dumps({"pairs": [
        {"original": "", "plain": "没原文的句"},   # 丢
        {"original": _HARD, "plain": "有原文的句"},  # 留
    ]}, ensure_ascii=False)
    _patch_invoke(monkeypatch, canned)
    out = rp.plain_language_from_spine(
        chunks=_CHUNKS, llm_client=_FakeClient(), model="m",
        full_text=_FULL_TEXT, mode="fulltext",
    )
    assert len(out["items"]) == 1
    assert out["items"][0]["original"] == _HARD


# ════════════════════════════════════════════════════════════════════════════
# 纯件:分段 + 切句
# ════════════════════════════════════════════════════════════════════════════

def test_split_into_sentences():
    sents = rp._split_into_sentences(_FULL_TEXT)
    assert len(sents) == 4  # 四句(各以。收尾)
    assert sents[0] == _HEAD
    assert sents[3] == _SHELVE
    # 空白只返空
    assert rp._split_into_sentences("   ") == []


def test_segment_fulltext_does_not_cut_mid_sentence():
    """按字符预算攒整句成段,不在句中切。"""
    segs = rp._segment_fulltext(_FULL_TEXT, char_budget=40)
    # 预算小 → 切成多段
    assert len(segs) >= 2
    # 拼回去 == 原文(没丢字、没在句中切)
    assert "".join(segs) == _HEAD + _HARD + _LOOPHOLE + _SHELVE
    # 每段都由完整句构成(段尾必是句末标点之一)
    for seg in segs:
        assert seg[-1] in "。!?；…」』】）" or seg.endswith("\n")


def test_segment_fulltext_single_segment_when_under_budget():
    """全文不超预算 → 单段(整份一块)。"""
    segs = rp._segment_fulltext(_FULL_TEXT, char_budget=100000)
    assert len(segs) == 1


def test_segment_fulltext_empty():
    assert rp._segment_fulltext("", 1000) == []
    assert rp._segment_fulltext("   ", 1000) == []


# ════════════════════════════════════════════════════════════════════════════
# _parse_pairs 纯件
# ════════════════════════════════════════════════════════════════════════════

def test_parse_pairs_basic():
    pairs = rp._parse_pairs(_fulltext_pairs_payload())
    assert len(pairs) == 4
    assert pairs[0]["original"] == _HEAD


def test_parse_pairs_empty_on_garbage():
    assert rp._parse_pairs("not json") == []
    assert rp._parse_pairs("") == []
