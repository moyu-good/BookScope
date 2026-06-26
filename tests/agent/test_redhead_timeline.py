"""公文关键时间轴 redhead_timeline 单测(含 1.6.1 约束力层)。

合成一份红头文件的 chunk + 假文脉(带 penalty 的 clauses) + mock LLM,覆盖:

- 时间节点抽取 + evidence 锚原文过核验(命中 verified=True、编的标待核)。
- 1.6.1 约束力层:每个节点带 deadline_type(真deadline/软目标,落封闭集、落不进退「软目标」)
  + deadline_reason。
- 约束力字段缺失向后兼容:老格式(没 deadline_type)→ 退「软目标」、reason 空。
- 紧凑清单把 clause 的 penalty 摆进去(判真死线最直接的 marker)。
- prompt 拼进 codebook + 问真死线 vs 软目标。
- 空条款 / parse 兜底 / 异常退空轴。

不跑真 LLM。
"""

from __future__ import annotations

import json

from bookscope.agent import redhead_timeline as tl

# 合成红头文件:几句原文,canned evidence 逐字引来命中核验。
_HARD = "各区市场监管局应当于2024年9月30日前完成存量登记,逾期不予受理。"
_SOFT = "力争到2025年底实现政务服务事项全程网办。"

_CHUNKS = [
    {"chunk_id": "c1", "chapter": 1, "text": _HARD},
    {"chunk_id": "c2", "chapter": 2, "text": _SOFT},
]

# 假文脉的 clauses——带 1.6.1 的 penalty 字段(第1条有罚则,第2条无)。
_FAKE_CLAUSES = [
    {"chapter": 1, "matter": "完成存量登记", "instruction_type": "硬要求",
     "actor": "各区市场监管局", "deadline": "2024年9月30日前",
     "substance": "真金白银", "substance_reason": "", "penalty": "逾期不予受理",
     "evidence": _HARD},
    {"chapter": 2, "matter": "实现全程网办", "instruction_type": "软倡导",
     "actor": "", "deadline": "2025年底",
     "substance": "空头倡导", "substance_reason": "", "penalty": "",
     "evidence": _SOFT},
]


class _FakeClient:
    def extract_final_text(self, resp):  # noqa: ANN001, ANN201
        return resp if isinstance(resp, str) else "{}"


def _patch(monkeypatch, canned: str, *, clauses=None):
    """patch 抽取调用返 canned;文脉入口返带 clauses 的假 spine。"""
    def _fake(*_a, **_kw):  # noqa: ANN002, ANN003, ANN202
        return canned
    monkeypatch.setattr(tl, "invoke_client_cached", _fake)
    spine = {"clauses": clauses if clauses is not None else _FAKE_CLAUSES}
    monkeypatch.setattr(tl, "get_or_build_doc_spine", lambda *_a, **_kw: spine)


def _run(monkeypatch, canned: str, *, clauses=None):
    _patch(monkeypatch, canned, clauses=clauses)
    return tl.timeline_from_spine(
        chunks=_CHUNKS,
        llm_client=_FakeClient(),
        model="deepseek-v4-flash",
        full_text=_HARD + _SOFT,
    )


def _full_payload() -> str:
    """两个时间节点:真死线(有逾期罚则)+ 软目标(力争性)。"""
    return json.dumps({"nodes": [
        {"when": "2024年9月30日前", "what": "完成存量登记", "chapter": 1,
         "deadline_type": "真deadline", "deadline_reason": "「应当…逾期不予受理」有罚则兜底",
         "evidence": _HARD},
        {"when": "2025年底", "what": "实现全程网办", "chapter": 2,
         "deadline_type": "软目标", "deadline_reason": "「力争…」是力争性,无罚则",
         "evidence": _SOFT},
    ]}, ensure_ascii=False)


# ── 整体抽取 + 字段齐全 ──────────────────────────────────────────────────────
def test_nodes_extracted_with_deadline_type(monkeypatch):
    out = _run(monkeypatch, _full_payload())
    assert out["schema_version"] == tl.TIMELINE_SCHEMA_VERSION
    assert len(out["nodes"]) == 2
    for n in out["nodes"]:
        for k in ("when", "what", "chapter", "evidence", "verified", "match_score",
                  "deadline_type", "deadline_reason"):
            assert k in n, f"节点缺字段 {k}"
        assert n["deadline_type"] in tl.DEADLINE_TYPES


def test_real_deadline_vs_soft_target(monkeypatch):
    """有逾期罚则的判真死线;力争性的判软目标。"""
    out = _run(monkeypatch, _full_payload())
    by_when = {n["when"]: n for n in out["nodes"]}
    assert by_when["2024年9月30日前"]["deadline_type"] == "真deadline"
    assert by_when["2025年底"]["deadline_type"] == "软目标"


def test_unknown_deadline_type_falls_back_to_soft(monkeypatch):
    """模型给个不在两档里的性质 → 退「软目标」(最保守,不替时点拔高成真死线吓人)。"""
    canned = json.dumps({"nodes": [
        {"when": "2024年9月30日前", "what": "x", "chapter": 1,
         "deadline_type": "天王老子死线", "deadline_reason": "", "evidence": _HARD},
    ]}, ensure_ascii=False)
    out = _run(monkeypatch, canned)
    assert out["nodes"][0]["deadline_type"] == "软目标"


def test_deadline_type_defaults_when_absent_backward_compat(monkeypatch):
    """老格式节点(没 deadline_type 字段)→ 退「软目标」、reason 空,向后兼容。"""
    canned = json.dumps({"nodes": [
        {"when": "2024年9月30日前", "what": "完成存量登记", "chapter": 1, "evidence": _HARD},
    ]}, ensure_ascii=False)
    out = _run(monkeypatch, canned)
    assert out["nodes"][0]["deadline_type"] == "软目标"
    assert out["nodes"][0]["deadline_reason"] == ""


# ── 核验(沿用契约,确认约束力层没破)───────────────────────────────────────────
def test_verified_when_in_original(monkeypatch):
    out = _run(monkeypatch, _full_payload())
    for n in out["nodes"]:
        assert n["verified"] is True  # canned evidence 都命中合成原文


def test_fabricated_evidence_marked_pending(monkeypatch):
    """evidence 原文没有 → verified=False 标待核(绝不假装日期有原文撑)。"""
    canned = json.dumps({"nodes": [
        {"when": "2099年", "what": "编的", "chapter": 1,
         "deadline_type": "真deadline", "deadline_reason": "",
         "evidence": "全市将于2099年实现共产主义(原文没这句)。"},
    ]}, ensure_ascii=False)
    out = _run(monkeypatch, canned)
    assert out["nodes"][0]["verified"] is False


# ── 紧凑清单把 penalty 摆进去(判真死线的 marker)──────────────────────────────
def test_compact_clauses_includes_penalty():
    compact = tl._compact_clauses(_FAKE_CLAUSES)
    assert "不办的代价" in compact
    assert "逾期不予受理" in compact  # 第1条的罚则被摆进清单


# ── prompt 接 codebook + 问真死线 vs 软目标 ──────────────────────────────────
def test_prompt_carries_codebook_and_deadline_type():
    instr = tl._INSTR_TIMELINE
    assert "真deadline" in instr and "软目标" in instr
    assert "约束力阶梯" in instr  # codebook 进来了


# ── 空条款 / parse / 异常兜底 ────────────────────────────────────────────────
def test_empty_clauses_returns_empty(monkeypatch):
    """文脉没拆出条款 → 空时间轴。"""
    out = _run(monkeypatch, _full_payload(), clauses=[])
    assert out["nodes"] == []


def test_strips_code_fence(monkeypatch):
    fenced = "```json\n" + _full_payload() + "\n```"
    out = _run(monkeypatch, fenced)
    assert len(out["nodes"]) == 2


def test_unparseable_returns_empty(monkeypatch):
    out = _run(monkeypatch, "这根本不是 JSON")
    assert out["nodes"] == []


def test_llm_exception_returns_empty(monkeypatch):
    def _boom(*_a, **_kw):  # noqa: ANN002, ANN003, ANN202
        raise RuntimeError("provider 503")
    monkeypatch.setattr(tl, "invoke_client_cached", _boom)
    monkeypatch.setattr(tl, "get_or_build_doc_spine", lambda *_a, **_kw: {"clauses": _FAKE_CLAUSES})
    out = tl.timeline_from_spine(
        chunks=_CHUNKS, llm_client=_FakeClient(),
        model="deepseek-v4-flash", full_text=_HARD + _SOFT,
    )
    assert out["nodes"] == []


# ── 纯件:性质归一 ───────────────────────────────────────────────────────────
def test_coerce_deadline_type_pure():
    for d in tl.DEADLINE_TYPES:
        assert tl._coerce_deadline_type(d) == d
    assert tl._coerce_deadline_type("超级死线") == "软目标"  # 落不进退兜底
    assert tl._coerce_deadline_type(None) == "软目标"
    assert tl._coerce_deadline_type("  真deadline  ") == "真deadline"  # 去空白


def test_coerce_node_deadline_type_default():
    """_coerce_node 缺 deadline_type → 退「软目标」、reason 空。"""
    n = tl._coerce_node({"when": "2024年", "what": "x", "evidence": "y"})
    assert n is not None
    assert n["deadline_type"] == "软目标"
    assert n["deadline_reason"] == ""
