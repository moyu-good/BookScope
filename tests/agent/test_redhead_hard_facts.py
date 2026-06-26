"""公文硬信息提取 redhead_hard_facts 单测(含 1.6.1 约束力层)。

合成一份红头文件的 chunk + 整份原文 + mock LLM(假 client + monkeypatch
invoke_client_cached 返 canned JSON;get_or_build_doc_spine patch 成 no-op,这功能
只借它触发缓存、不拆字段),覆盖:

- 五类硬信息抽取 + kind 落封闭集(落不进丢)、value 锚 evidence 过核验。
- 1.6.1 约束力层:每条带 binding(硬指标/参考值,落封闭集、落不进退「参考值」)+ binding_reason。
- 约束力字段缺失向后兼容:老格式(没 binding)→ 退「参考值」、reason 空。
- prompt 拼进 codebook + 问约束力。
- parse 兜底 / 异常退空表。

不跑真 LLM。
"""

from __future__ import annotations

import json

from bookscope.agent import redhead_hard_facts as hf

# 合成红头文件:几句原文,canned evidence 逐字引来命中核验。
_HEAD = "市市场监管局文件 X监发〔2024〕7号 关于优化营商环境的通知。"
# 硬指标句:硬约束词 + 数字 + 罚则兜底。
_HARD = "各区市场监管局应当于2024年9月30日前将企业开办时间压缩至1个工作日内,逾期予以通报问责。"
# 软目标句:力争性、无罚则。
_SOFT = "力争到2025年底全市政务服务网上可办率达到90%。"
# 适用范围句。
_SCOPE = "本通知适用于本市各区市场监管局及市政务服务中心。"

_FULL_TEXT = _HEAD + _HARD + _SOFT + _SCOPE

_CHUNKS = [
    {"chunk_id": "h0", "chapter": 0, "text": _HEAD},
    {"chunk_id": "c1", "chapter": 1, "text": _HARD},
    {"chunk_id": "c2", "chapter": 2, "text": _SOFT},
    {"chunk_id": "c3", "chapter": 3, "text": _SCOPE},
]


class _FakeClient:
    def extract_final_text(self, resp):  # noqa: ANN001, ANN201
        return resp if isinstance(resp, str) else "{}"


def _patch(monkeypatch, canned: str):
    """patch 抽取调用返 canned;spine 入口 no-op(这功能只借它触发缓存,不拆字段)。"""
    def _fake(*_a, **_kw):  # noqa: ANN002, ANN003, ANN202
        return canned
    monkeypatch.setattr(hf, "invoke_client_cached", _fake)
    monkeypatch.setattr(hf, "get_or_build_doc_spine", lambda *_a, **_kw: {})


def _run(monkeypatch, canned: str):
    _patch(monkeypatch, canned)
    return hf.hard_facts_from_spine(
        chunks=_CHUNKS,
        llm_client=_FakeClient(),
        model="deepseek-v4-flash",
        full_text=_FULL_TEXT,
    )


def _full_payload() -> str:
    """四条硬信息:时限(硬指标)、数字指标(硬指标)、数字指标(参考值/软目标)、适用范围。"""
    return json.dumps({"facts": [
        {"kind": "时限", "value": "2024年9月30日前", "context": "企业开办时间压缩时限",
         "binding": "硬指标", "binding_reason": "「应当…逾期予以通报问责」有硬约束+罚则",
         "evidence": _HARD},
        {"kind": "数字指标", "value": "1个工作日内", "context": "企业开办时间目标",
         "binding": "硬指标", "binding_reason": "「应当…逾期问责」绑硬约束有罚则",
         "evidence": _HARD},
        {"kind": "数字指标", "value": "90%", "context": "政务服务网上可办率目标",
         "binding": "参考值", "binding_reason": "「力争…达到」是力争性软目标,无罚则",
         "evidence": _SOFT},
        {"kind": "适用范围", "value": "本市各区市场监管局及市政务服务中心",
         "context": "本通知适用对象",
         "binding": "参考值", "binding_reason": "范围陈述,非指标",
         "evidence": _SCOPE},
    ]}, ensure_ascii=False)


# ── 整体抽取 + 字段齐全 ──────────────────────────────────────────────────────
def test_facts_extracted_with_binding_fields(monkeypatch):
    out = _run(monkeypatch, _full_payload())
    assert out["schema_version"] == hf.HARD_FACTS_SCHEMA_VERSION
    assert len(out["facts"]) == 4
    for f in out["facts"]:
        for k in ("kind", "value", "context", "evidence", "verified", "match_score",
                  "binding", "binding_reason"):
            assert k in f, f"硬信息缺字段 {k}"
        assert f["binding"] in hf.BINDINGS


def test_binding_hard_vs_reference(monkeypatch):
    """硬约束+罚则的判硬指标;力争性的判参考值。"""
    out = _run(monkeypatch, _full_payload())
    by_val = {f["value"]: f for f in out["facts"]}
    assert by_val["2024年9月30日前"]["binding"] == "硬指标"
    assert by_val["1个工作日内"]["binding"] == "硬指标"
    assert by_val["90%"]["binding"] == "参考值"  # 力争性软目标


def test_unknown_binding_falls_back_to_reference(monkeypatch):
    """模型给个不在两档里的约束力 → 退「参考值」(最保守,不替数拔高成硬指标)。"""
    canned = json.dumps({"facts": [
        {"kind": "数字指标", "value": "90%", "context": "x",
         "binding": "超级硬", "binding_reason": "", "evidence": _SOFT},
    ]}, ensure_ascii=False)
    out = _run(monkeypatch, canned)
    assert out["facts"][0]["binding"] == "参考值"


def test_binding_defaults_when_absent_backward_compat(monkeypatch):
    """老格式硬信息(没 binding 字段)→ 退「参考值」、reason 空,向后兼容。"""
    canned = json.dumps({"facts": [
        {"kind": "时限", "value": "2024年9月30日前", "context": "x", "evidence": _HARD},
    ]}, ensure_ascii=False)
    out = _run(monkeypatch, canned)
    assert out["facts"][0]["binding"] == "参考值"
    assert out["facts"][0]["binding_reason"] == ""


# ── kind 封闭集 + 核验(沿用原有契约,确认约束力层没破)────────────────────────
def test_kind_closed_set_drops_invalid(monkeypatch):
    """kind 落不进五类 → 丢(不自造一类硬信息)。"""
    canned = json.dumps({"facts": [
        {"kind": "时限", "value": "2024年9月30日前", "context": "", "evidence": _HARD},
        {"kind": "玄学指标", "value": "宇宙真理", "context": "", "evidence": _HARD},
    ]}, ensure_ascii=False)
    out = _run(monkeypatch, canned)
    kinds = [f["kind"] for f in out["facts"]]
    assert "时限" in kinds
    assert "玄学指标" not in kinds


def test_fabricated_value_marked_pending(monkeypatch):
    """evidence 原文里没有 → verified=False 标待核(沿用契约,绝不假装核过)。"""
    canned = json.dumps({"facts": [
        {"kind": "数字指标", "value": "每户发1万元", "context": "",
         "binding": "硬指标", "binding_reason": "",
         "evidence": "市局将给每户发放一万元补贴(原文没这句)。"},
    ]}, ensure_ascii=False)
    out = _run(monkeypatch, canned)
    assert out["facts"][0]["verified"] is False


def test_verified_when_in_original(monkeypatch):
    out = _run(monkeypatch, _full_payload())
    for f in out["facts"]:
        assert f["verified"] is True  # canned evidence 都逐字命中合成原文


# ── prompt 接 codebook + 问约束力 ────────────────────────────────────────────
def test_prompt_carries_codebook_and_binding():
    instr = hf._INSTR_HARD_FACTS
    assert "约束力" in instr and "硬指标" in instr and "参考值" in instr
    assert "约束力阶梯" in instr  # codebook 进来了


# ── parse / 异常兜底 ─────────────────────────────────────────────────────────
def test_strips_code_fence(monkeypatch):
    fenced = "```json\n" + _full_payload() + "\n```"
    out = _run(monkeypatch, fenced)
    assert len(out["facts"]) == 4


def test_unparseable_returns_empty(monkeypatch):
    out = _run(monkeypatch, "这根本不是 JSON")
    assert out["facts"] == []


def test_llm_exception_returns_empty(monkeypatch):
    def _boom(*_a, **_kw):  # noqa: ANN002, ANN003, ANN202
        raise RuntimeError("provider 503")
    monkeypatch.setattr(hf, "invoke_client_cached", _boom)
    monkeypatch.setattr(hf, "get_or_build_doc_spine", lambda *_a, **_kw: {})
    out = hf.hard_facts_from_spine(
        chunks=_CHUNKS, llm_client=_FakeClient(),
        model="deepseek-v4-flash", full_text=_FULL_TEXT,
    )
    assert out["facts"] == []


# ── 纯件:约束力归一 ─────────────────────────────────────────────────────────
def test_coerce_binding_pure():
    for b in hf.BINDINGS:
        assert hf._coerce_binding(b) == b
    assert hf._coerce_binding("软软的") == "参考值"  # 落不进退兜底
    assert hf._coerce_binding(None) == "参考值"
    assert hf._coerce_binding("  硬指标  ") == "硬指标"  # 去空白


def test_coerce_fact_binding_default():
    """_coerce_fact 缺 binding → 退「参考值」、reason 空。"""
    f = hf._coerce_fact({"kind": "时限", "value": "30日内", "evidence": "x"})
    assert f is not None
    assert f["binding"] == "参考值"
    assert f["binding_reason"] == ""
