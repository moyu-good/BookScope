"""公文逐条精读 redhead_close_reading 单测(1.6 公文整合·centerpiece,整合 1+2)。

合成一份红头文件的 chunk + 整份原文 + mock(假 client + monkeypatch 文脉 / 逐条改写 / 全文挑词),
覆盖逐条精读「从同一份文脉合成三件套」这段产品逻辑:

整合 2(三切面合一):
- 每条带齐:大白话(plain)+ 结构标签(structure:硬/软 + 主体 + 时限 + 依据)+ 内联术语
  (glossary)+ 对原文(evidence)+ 核验态。schema v1。
- 结构标签**直接取 doc_spine 条款骨架,不重抽**(instruction_type / actor / deadline / basis_ref
  原样带出)。
- 内联术语按「术语出现的原句」归到对应条款:原句是某条 evidence 的子串 → 归那条;退一步按
  chapter == 条款序号归。
- 大白话核原文不核白话:背后原文命中盖鉴印,改写失败退回原事项。
- 命中措辞刻度的条挂 nuance,没命中不挂。

evidence-first 死守:
- 内联术语**只挂核过的**(verified=True 且原句非空);核不过的术语(原句已被 glossary 退空)
  一条都不挂。
- 归不到任何条款的术语丢(逐条精读只内联锚得到某条的术语)。

退场:文脉没条款 → items 空(优雅退场)。

不跑真 LLM。
"""

from __future__ import annotations

from typing import Any

from bookscope.agent import redhead_close_reading as cr

# ── 合成红头文件:头 + 三条正文句,canned evidence 逐字引这几句来命中 ──────────────
_HEAD = "市市场监管局文件 X监发〔2024〕7号 关于优化营商环境的通知。"
# 硬约束句(无 marker,nuance 该为空)。含术语「证照分离」。
_HARD = "各区局应当于2024年9月30日前全面推行证照分离改革。"
# 自由裁量句(命中「结合实际」)。
_LOOPHOLE = "各地结合实际简化新设企业材料要求。"
# 搁置句(命中「逐步」)。含术语「放管服」。
_SHELVE = "鼓励各地逐步推广放管服改革。"

_FULL_TEXT = _HEAD + _HARD + _LOOPHOLE + _SHELVE

_CHUNKS = [
    {"chunk_id": "h0", "chapter": 0, "text": _HEAD},
    {"chunk_id": "c1", "chapter": 1, "text": _HARD},
    {"chunk_id": "c2", "chapter": 2, "text": _LOOPHOLE},
    {"chunk_id": "c3", "chapter": 3, "text": _SHELVE},
]


class _FakeClient:
    """duck-typed client;改写/挑词都被 mock 掉后不会真用到它,占位对齐签名。"""

    def extract_final_text(self, resp):  # noqa: ANN001, ANN201
        return resp if isinstance(resp, str) else "{}"


def _clause(
    chapter: int,
    *,
    matter: str = "",
    evidence: str = "",
    instruction_type: str = "信息告知",
    actor: str = "",
    deadline: str = "",
    basis_ref: str = "",
) -> dict[str, Any]:
    """造一条 doc_spine 条款骨架形态(带结构字段)。"""
    return {
        "chapter": chapter,
        "matter": matter,
        "evidence": evidence,
        "instruction_type": instruction_type,
        "actor": actor,
        "deadline": deadline,
        "basis_ref": basis_ref,
    }


def _term(
    term: str,
    *,
    explanation: str = "",
    context_meaning: str = "",
    policy_intent: str = "",
    evidence: str = "",
    verified: bool = True,
    chapter: int | None = None,
) -> dict[str, Any]:
    """造一条 glossary_from_spine 产物形态的术语(已过核验、带 chapter)。"""
    return {
        "term": term,
        "explanation": explanation,
        "context_meaning": context_meaning,
        "policy_intent": policy_intent,
        "evidence": evidence,
        "verified": verified,
        "match_score": 1.0 if verified else 0.0,
        "chapter": chapter,
    }


def _patch(monkeypatch, *, clauses, rewrites=None, terms=None):
    """patch 三个外部依赖:文脉(返 clauses)/ 逐条改写(_rewrite_one)/ 全文挑词(glossary)。

    - clauses: 文脉的条款列表。
    - rewrites: dict[chapter -> 白话] 或 None(None = 改写返空串,测退回原事项)。
    - terms: glossary_from_spine 返的 terms 列表(默认空)。
    """
    monkeypatch.setattr(
        cr, "get_or_build_doc_spine",
        lambda **_kw: {"head": [], "clauses": clauses},
    )

    def _fake_rewrite(clause, **_kw):  # noqa: ANN001, ANN003, ANN202
        if rewrites is None:
            return ""
        return rewrites.get(clause.get("chapter"), "")

    monkeypatch.setattr(cr, "_rewrite_one", _fake_rewrite)
    monkeypatch.setattr(
        cr, "glossary_from_spine",
        lambda **_kw: {"schema_version": "v3", "terms": terms or []},
    )


def _run(monkeypatch, *, clauses, rewrites=None, terms=None):
    _patch(monkeypatch, clauses=clauses, rewrites=rewrites, terms=terms)
    return cr.close_reading_from_spine(
        chunks=_CHUNKS,
        llm_client=_FakeClient(),
        model="deepseek-v4-flash",
        full_text=_FULL_TEXT,
    )


# ════════════════════════════════════════════════════════════════════════════
# 整体结构 + schema 版本
# ════════════════════════════════════════════════════════════════════════════
def test_schema_version_is_v1(monkeypatch):
    out = _run(
        monkeypatch,
        clauses=[_clause(1, matter="减免", evidence=_HARD)],
        rewrites={1: "得在9月30日前推行证照分离改革。"},
    )
    assert out["schema_version"] == cr.CLOSE_READING_SCHEMA_VERSION == "v1"


def test_item_has_all_fields(monkeypatch):
    """每条带齐:大白话 + 结构标签 + 内联术语 + 对原文 + 核验态。"""
    out = _run(
        monkeypatch,
        clauses=[
            _clause(
                1, matter="证照分离", evidence=_HARD,
                instruction_type="硬要求", actor="各区局",
                deadline="2024年9月30日", basis_ref="国发〔2021〕7号",
            )
        ],
        rewrites={1: "得在9月30日前全面推行证照分离改革。"},
    )
    assert len(out["items"]) == 1
    it = out["items"][0]
    for k in (
        "chapter", "matter", "plain", "structure", "glossary",
        "evidence", "verified", "match_score",
    ):
        assert k in it, f"逐条精读条缺字段 {k}"
    for k in ("instruction_type", "actor", "deadline", "basis_ref"):
        assert k in it["structure"], f"结构标签缺字段 {k}"


# ════════════════════════════════════════════════════════════════════════════
# 结构标签:直接取条款骨架,不重抽
# ════════════════════════════════════════════════════════════════════════════
def test_structure_label_taken_from_clause_skeleton(monkeypatch):
    """结构标签原样取 doc_spine 条款字段(硬/软 + 主体 + 时限 + 依据),不重抽、不改。"""
    out = _run(
        monkeypatch,
        clauses=[
            _clause(
                1, matter="x", evidence=_HARD,
                instruction_type="硬要求", actor="各区局",
                deadline="2024年9月30日", basis_ref="国发〔2021〕7号",
            )
        ],
        rewrites={1: "白话"},
    )
    st = out["items"][0]["structure"]
    assert st["instruction_type"] == "硬要求"
    assert st["actor"] == "各区局"
    assert st["deadline"] == "2024年9月30日"
    assert st["basis_ref"] == "国发〔2021〕7号"


def test_narrative_clause_label_carried(monkeypatch):
    """叙述体公文的要点(instruction_type=方针部署、主体/时限空)照样带出标签,不跳过。"""
    out = _run(
        monkeypatch,
        clauses=[_clause(1, matter="坚持改革", evidence=_SHELVE, instruction_type="方针部署")],
        rewrites={1: "要坚持推进放管服改革。"},
    )
    st = out["items"][0]["structure"]
    assert st["instruction_type"] == "方针部署"
    assert st["actor"] == ""  # 留空照带,不硬塞


# ════════════════════════════════════════════════════════════════════════════
# 大白话:核原文不核白话 + 改写失败退回原事项
# ════════════════════════════════════════════════════════════════════════════
def test_plain_verified_when_evidence_in_original(monkeypatch):
    """白话背后的原文 evidence 逐字命中合成原文 → verified=True 盖鉴印。"""
    out = _run(
        monkeypatch,
        clauses=[_clause(1, matter="减免", evidence=_HARD)],
        rewrites={1: "得在9月30日前推行证照分离改革。"},
    )
    it = out["items"][0]
    assert it["verified"] is True
    assert it["plain"] == "得在9月30日前推行证照分离改革。"


def test_plain_rewrite_failure_falls_back_to_matter(monkeypatch):
    """改写返空(LLM 给空串)→ plain 退回原事项,不假装翻好了。"""
    out = _run(
        monkeypatch,
        clauses=[_clause(1, matter="原事项摆着", evidence=_HARD)],
        rewrites=None,  # 改写全返空
    )
    assert out["items"][0]["plain"] == "原事项摆着"


def test_fabricated_evidence_not_verified(monkeypatch):
    """编的原文(原文里没有)→ 核不过,verified=False。"""
    out = _run(
        monkeypatch,
        clauses=[_clause(1, matter="x", evidence="本市发放十万元创业补贴(原文压根没有)。")],
        rewrites={1: "发钱"},
    )
    assert out["items"][0]["verified"] is False


# ════════════════════════════════════════════════════════════════════════════
# nuance:命中措辞刻度才挂
# ════════════════════════════════════════════════════════════════════════════
def test_nuance_attached_when_marker_in_evidence(monkeypatch):
    """条款原文命中「结合实际」→ 挂 nuance 点弦外之意。"""
    out = _run(
        monkeypatch,
        clauses=[_clause(1, matter="纸质材料", evidence=_LOOPHOLE)],
        rewrites={1: "各地按本地情况简化新设企业的材料要求。"},
    )
    it = out["items"][0]
    assert "nuance" in it
    assert any(n["marker"] == "结合实际" for n in it["nuance"])


def test_no_nuance_when_no_marker(monkeypatch):
    """硬约束句无 marker → 不挂 nuance(可选字段)。"""
    out = _run(
        monkeypatch,
        clauses=[_clause(1, matter="减免", evidence=_HARD)],
        rewrites={1: "得在9月30日前推行证照分离改革。"},
    )
    assert "nuance" not in out["items"][0]


# ════════════════════════════════════════════════════════════════════════════
# 内联术语:按原句归到对应条款 + evidence-first
# ════════════════════════════════════════════════════════════════════════════
def test_glossary_attached_to_clause_by_sentence(monkeypatch):
    """术语原句是某条 evidence 的子串 → 内联到那条;别条不挂。"""
    out = _run(
        monkeypatch,
        clauses=[
            _clause(1, matter="证照分离", evidence=_HARD),
            _clause(2, matter="纸质材料", evidence=_LOOPHOLE),
        ],
        rewrites={1: "推行证照分离", 2: "不用交纸质"},
        terms=[
            _term("证照分离", explanation="证照分开办", evidence=_HARD, chapter=1),
        ],
    )
    by_ch = {it["chapter"]: it for it in out["items"]}
    # 第 1 条原文含「证照分离」原句 → 挂上
    assert len(by_ch[1]["glossary"]) == 1
    assert by_ch[1]["glossary"][0]["term"] == "证照分离"
    assert by_ch[1]["glossary"][0]["explanation"] == "证照分开办"
    # 第 2 条不含该术语原句 → 不挂
    assert by_ch[2]["glossary"] == []


def test_glossary_attached_by_chapter_fallback(monkeypatch):
    """术语原句不是条款 evidence 的子串,但 chapter 对得上 → 退一步按 chapter 归。"""
    out = _run(
        monkeypatch,
        clauses=[_clause(3, matter="放管服", evidence=_SHELVE)],
        rewrites={3: "推进放管服"},
        terms=[
            # 原句给一句不在 _SHELVE 里的(子串匹配不上),但 chapter=3 对得上条款序号
            _term(
                "放管服", explanation="简政放权",
                evidence="深化放管服改革持续优化。", chapter=3,
            ),
        ],
    )
    it = out["items"][0]
    assert len(it["glossary"]) == 1
    assert it["glossary"][0]["term"] == "放管服"


def test_unverified_term_not_attached(monkeypatch):
    """核不过的术语(verified=False / 原句空)一条都不挂——不留核不到原文的假术语。"""
    out = _run(
        monkeypatch,
        clauses=[_clause(1, matter="x", evidence=_HARD)],
        rewrites={1: "白话"},
        terms=[
            _term("证照分离", explanation="x", evidence="", verified=False, chapter=1),
        ],
    )
    assert out["items"][0]["glossary"] == []


def test_term_matching_no_clause_dropped(monkeypatch):
    """术语归不到任何条款(原句不在任何 evidence、chapter 也对不上)→ 丢,不硬塞。"""
    out = _run(
        monkeypatch,
        clauses=[_clause(1, matter="x", evidence=_HARD)],
        rewrites={1: "白话"},
        terms=[
            _term(
                "负面清单", explanation="x",
                evidence="一句哪条都不沾的原文。", chapter=99, verified=True,
            ),
        ],
    )
    # 该术语原句不在第 1 条 evidence、chapter 99 也不是任何条款 → 不挂到任何条
    assert out["items"][0]["glossary"] == []


def test_term_inline_carries_context_and_intent(monkeypatch):
    """内联术语带出语境义 + 政策意图(逐条精读保留 glossary 的两层深度字段)。"""
    out = _run(
        monkeypatch,
        clauses=[_clause(3, matter="放管服", evidence=_SHELVE)],
        rewrites={3: "推进放管服"},
        terms=[
            _term(
                "放管服", explanation="简政放权放管结合优化服务",
                context_meaning="这份文件里指市场监管领域的简政放权",
                policy_intent="给市场松绑的改革方向",
                evidence=_SHELVE, chapter=3,
            ),
        ],
    )
    g = out["items"][0]["glossary"][0]
    assert g["context_meaning"] == "这份文件里指市场监管领域的简政放权"
    assert g["policy_intent"] == "给市场松绑的改革方向"


# ════════════════════════════════════════════════════════════════════════════
# 退场 + 顺序
# ════════════════════════════════════════════════════════════════════════════
def test_no_clauses_returns_empty(monkeypatch):
    """文脉没条款 → items 空(优雅退场),glossary 不该被调(调了就炸)。"""
    monkeypatch.setattr(
        cr, "get_or_build_doc_spine", lambda **_kw: {"head": [], "clauses": []}
    )

    def _boom(**_kw):  # noqa: ANN003, ANN202
        raise AssertionError("没条款不该跑 glossary")

    monkeypatch.setattr(cr, "glossary_from_spine", _boom)
    monkeypatch.setattr(cr, "_rewrite_one", lambda *_a, **_kw: "")
    out = cr.close_reading_from_spine(
        chunks=_CHUNKS, llm_client=_FakeClient(),
        model="deepseek-v4-flash", full_text=_FULL_TEXT,
    )
    assert out["schema_version"] == "v1"
    assert out["items"] == []


def test_items_ordered_by_clause(monkeypatch):
    """items 按条款顺序排(同 doc_spine clauses 的序)。"""
    out = _run(
        monkeypatch,
        clauses=[
            _clause(1, matter="一", evidence=_HARD),
            _clause(2, matter="二", evidence=_LOOPHOLE),
            _clause(3, matter="三", evidence=_SHELVE),
        ],
        rewrites={1: "a", 2: "b", 3: "c"},
    )
    assert [it["chapter"] for it in out["items"]] == [1, 2, 3]


def test_structure_label_helper_strips():
    """_structure_label 把字段 strip 干净(纯件)。"""
    st = cr._structure_label({
        "instruction_type": "  硬要求  ",
        "actor": "  各区局 ",
        "deadline": "",
        "basis_ref": " 国发〔2021〕7号 ",
    })
    assert st["instruction_type"] == "硬要求"
    assert st["actor"] == "各区局"
    assert st["deadline"] == ""
    assert st["basis_ref"] == "国发〔2021〕7号"
