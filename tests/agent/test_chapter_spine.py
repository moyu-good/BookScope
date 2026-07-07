"""章脉(ADR-010)单测 —— 分维解析 / 归一 / 章号纠偏 / 跨维 union / build 装配。

纯件直接喂数据;build_chapter_spine 把 mapreduce_per_chapter 桩掉,不调真 LLM。
"""

from __future__ import annotations

import json

import bookscope.agent.chapter_spine as cs


# ── 解析 ───────────────────────────────────────────────────────────────────
def test_parse_plot_valid() -> None:
    parse = cs._make_parser("plot")
    text = json.dumps({"chapters": [
        {"chapter": 1, "events": ["打架"], "tension": 8, "sentiment": -2,
         "pov": "甲", "mainline": True, "foreshadow": [], "evidence": "甲打了乙"},
    ]})
    out = parse(text)
    assert out is not None
    assert out[0]["chapter"] == 1
    assert out[0]["tension"] == 8
    assert out[0]["pov"] == "甲"


def test_parse_char_valid() -> None:
    parse = cs._make_parser("char")
    text = json.dumps({"chapters": [
        {"chapter": 2, "present": ["甲", "乙"],
         "relations": [{"pair": ["甲", "乙"], "note": "结义"}],
         "char_states": [], "evidence": "甲乙结义"},
    ]})
    out = parse(text)
    assert out and out[0]["present"] == ["甲", "乙"]
    assert out[0]["relations"][0]["note"] == "结义"


def test_parse_salvages_truncated() -> None:
    # 截断:第二个对象没闭合 + 数组/外层没收尾 → 主 parse 必败,从已闭合的抢救
    parse = cs._make_parser("plot")
    truncated = (
        '{"chapters": [{"chapter": 1, "events": [], "tension": 5, "sentiment": 0, '
        '"pov": "甲", "mainline": true, "foreshadow": [], "evidence": "x"}, '
        '{"chapter": 2, "events": ["未闭合'
    )
    out = parse(truncated)
    assert out is not None
    assert [c["chapter"] for c in out] == [1]  # 抢救到第一章


def test_coerce_drops_non_int_chapter_and_clamps() -> None:
    parse = cs._make_parser("plot")
    text = json.dumps({"chapters": [
        {"chapter": "一", "tension": 5, "evidence": "x"},          # 章号非整数 → 丢
        {"chapter": 3, "tension": 99, "sentiment": -99, "evidence": "y"},  # 钳到 10 / -5
    ]})
    out = parse(text)
    assert [c["chapter"] for c in out] == [3]
    assert out[0]["tension"] == 10
    assert out[0]["sentiment"] == -5
    assert out[0]["pov"] == "群像"          # 缺省
    assert out[0]["mainline"] is True       # 缺省


# ── 章号纠偏 ─────────────────────────────────────────────────────────────────
def test_correct_by_evidence_overrides_chapter() -> None:
    chunks = [
        {"chunk_id": "c1", "chapter": 1, "text": "桃园结义,刘关张同心。"},
        {"chunk_id": "c2", "chapter": 86, "text": "诸葛亮舌战群儒。"},
    ]
    # 模型自报章号 11(多卷书撞号),evidence 命中真第 86 章 → 应纠偏成 86
    records = [{"chapter": 11, "evidence": "诸葛亮舌战群儒"}]
    cs._correct_by_evidence(records, chunks)
    assert records[0]["chapter"] == 86
    assert records[0]["verified"] is True


def test_correct_by_evidence_miss_keeps_self_reported() -> None:
    chunks = [{"chunk_id": "c1", "chapter": 1, "text": "桃园结义。"}]
    records = [{"chapter": 5, "evidence": "查无此句"}]
    cs._correct_by_evidence(records, chunks)
    assert records[0]["chapter"] == 5          # 没命中退回自报
    assert records[0]["verified"] is False


# ── 跨维 union ───────────────────────────────────────────────────────────────
def test_merge_dimensions_unions_fields_by_chapter() -> None:
    char = [{"chapter": 1, "present": ["甲"], "relations": [], "char_states": [],
             "evidence": "e_char", "verified": True, "match_score": 1.0}]
    plot = [{"chapter": 1, "events": ["打"], "tension": 8, "sentiment": -2, "pov": "甲",
             "mainline": True, "foreshadow": [], "evidence": "e_plot",
             "verified": False, "match_score": 0.5}]
    merged = cs._merge_dimensions([char, plot])
    assert len(merged) == 1
    rec = merged[0]
    assert rec["present"] == ["甲"]            # 人物维字段
    assert rec["tension"] == 8                  # 情节维字段
    assert rec["verified"] is True             # 任一维命中即 True
    assert rec["match_score"] == 1.0           # 取最大
    assert rec["evidence"] == "e_char"         # 第一条非空


def test_merge_dimensions_sorts_and_handles_disjoint_chapters() -> None:
    char = [{"chapter": 3, "present": ["甲"], "evidence": "a"},
            {"chapter": 1, "present": ["乙"], "evidence": "b"}]
    plot = [{"chapter": 2, "tension": 5, "evidence": "c"}]
    merged = cs._merge_dimensions([char, plot])
    assert [r["chapter"] for r in merged] == [1, 2, 3]   # 升序


# ── build 装配 ───────────────────────────────────────────────────────────────
class _FakeClient:
    def extract_final_text(self, resp):  # noqa: ANN001, ANN201
        return "{}"


def test_build_chapter_spine_fiction_runs_two_dims(monkeypatch) -> None:  # noqa: ANN001
    calls = []

    def _fake_mapreduce(**kwargs):  # noqa: ANN003, ANN202
        calls.append(kwargs["instruction"])
        # 据指令判断是哪一维,返该维的一条章 1 记录
        if kwargs["instruction"] is cs._INSTR_CHAR:
            return [{"chapter": 1, "present": ["甲"], "evidence": "e",
                     "verified": True, "match_score": 1.0}]
        return [{"chapter": 1, "tension": 7, "evidence": "e2",
                 "verified": True, "match_score": 1.0}]

    monkeypatch.setattr(cs, "mapreduce_per_chapter", _fake_mapreduce)
    spine = cs.build_chapter_spine(chunks=[], llm_client=_FakeClient(), model="m")
    assert len(calls) == 2                       # 小说跑两维,不跑概念维
    assert cs._INSTR_CONCEPT not in calls
    assert len(spine) == 1
    assert spine[0]["present"] == ["甲"]         # 两维 union 到一条
    assert spine[0]["tension"] == 7


def test_build_chapter_spine_theory_adds_concept_dim(monkeypatch) -> None:  # noqa: ANN001
    calls = []

    def _fake_mapreduce(**kwargs):  # noqa: ANN003, ANN202
        calls.append(kwargs["instruction"])
        return []

    monkeypatch.setattr(cs, "mapreduce_per_chapter", _fake_mapreduce)
    cs.build_chapter_spine(chunks=[], llm_client=_FakeClient(), model="m", genre="theory")
    assert len(calls) == 3                       # 理论书加概念维
    assert cs._INSTR_CONCEPT in calls


# ── 1.5.2 方案 B：char/plot 重维收窄章闸,concept 轻维走全局,全局默认不动 ──────
def test_build_chapter_spine_per_dim_chapter_cap(monkeypatch) -> None:  # noqa: ANN001
    by_dim: dict[str, int] = {}
    has_continue: dict[str, bool] = {}

    def _fake_mapreduce(**kwargs):  # noqa: ANN003, ANN202
        instr = kwargs["instruction"]
        dim = {cs._INSTR_CHAR: "char", cs._INSTR_PLOT: "plot",
               cs._INSTR_CONCEPT: "concept"}[instr]
        by_dim[dim] = kwargs["max_chapters"]
        has_continue[dim] = kwargs.get("continue_fn") is not None
        return []

    monkeypatch.setattr(cs, "mapreduce_per_chapter", _fake_mapreduce)
    cs.build_chapter_spine(chunks=[], llm_client=_FakeClient(), model="m", genre="theory")
    # 重维收窄到专用小章闸,轻维走全局 12
    assert by_dim["char"] == cs._SPINE_HEAVY_DIM_MAX_CHAPTERS
    assert by_dim["plot"] == cs._SPINE_HEAVY_DIM_MAX_CHAPTERS
    assert by_dim["concept"] == cs.DEFAULT_MAX_CHAPTERS == 12
    # 续抽只挂重维
    assert has_continue["char"] is True
    assert has_continue["plot"] is True
    assert has_continue["concept"] is False


def test_spine_scale_params_match_probe_sweet_spot() -> None:
    # probe_spine_scale(三国 732k 字冷启动、4 组对照)定案的超长文 sweet spot:段放大到
    # 12 章 / 12 万字 + max_tokens 抬到 16000 → 冷启动快 3.3 倍、0 截断、完整度 1.0。
    # 设计从"重维收窄章闸防截断"改成"大段配够 token 一次抽完"——这三个值是配套的,别单改一个。
    assert cs._SPINE_HEAVY_DIM_MAX_CHAPTERS == 12
    assert cs._SPINE_CHAR_BUDGET == 120000
    assert cs.DEFAULT_SPINE_MAX_TOKENS == 16000


# ── 1.5.2 方案 C：续抽把段截断丢的章补回来,章数对齐 ──────────────────────────
class _SegFakeClient:
    """按调用次数返不同 content;extract_final_text 读回上次塞的 content。"""

    def __init__(self, texts: list[str]) -> None:
        self._texts = list(texts)
        self.i = 0

    def extract_final_text(self, resp):  # noqa: ANN001, ANN201
        return resp["choices"][0]["message"]["content"]


def test_continue_fn_refills_dropped_chapters(monkeypatch) -> None:  # noqa: ANN001
    # 段覆盖 6 章,首次截断只抢救回 3 章(传给 continue_fn 当 partial),续抽补回剩下 3 章。
    seg = [{"chunk_id": f"c{i}", "chapter": i, "text": "正文"} for i in range(1, 7)]
    partial = [{"chapter": i} for i in (1, 2, 3)]  # 自报章号(还没纠偏),数量=3

    cont_calls = {"n": 0}

    def _fake_invoke(*_a, **_k):  # noqa: ANN002, ANN003, ANN202
        cont_calls["n"] += 1
        # 第一轮续抽补回 4、5、6 三章,凑齐 6 章
        return {"choices": [{"message": {"content": json.dumps(
            {"chapters": [{"chapter": 4, "tension": 5, "evidence": "e"},
                          {"chapter": 5, "tension": 5, "evidence": "e"},
                          {"chapter": 6, "tension": 5, "evidence": "e"}]})},
            "finish_reason": "stop"}]}

    monkeypatch.setattr(cs, "invoke_client_cached", _fake_invoke)
    cont = cs._make_continue_fn(
        "plot", cs._INSTR_PLOT,
        llm_client=_SegFakeClient([]), model="m", max_tokens=8000, cache_enabled=True,
    )
    extra = cont(seg, partial)
    assert cont_calls["n"] == 1                       # 一轮就补齐,不多打
    assert [c["chapter"] for c in extra] == [4, 5, 6]  # 补回差掉的三章
    # partial(3) + extra(3) = 6,对齐段覆盖章数
    assert len(partial) + len(extra) == cs._segment_chapter_count(seg) == 6


def test_continue_fn_stops_at_max_rounds(monkeypatch) -> None:  # noqa: ANN001
    # 续抽每轮只补 1 章、永远补不齐 → 最多打 _SPINE_CONTINUE_MAX_ROUNDS 轮就停,不无限补。
    seg = [{"chunk_id": f"c{i}", "chapter": i, "text": "正文"} for i in range(1, 11)]
    partial = [{"chapter": 1}]
    n = {"i": 0}

    def _fake_invoke(*_a, **_k):  # noqa: ANN002, ANN003, ANN202
        n["i"] += 1
        return {"choices": [{"message": {"content": json.dumps(
            {"chapters": [{"chapter": 100 + n["i"], "tension": 5, "evidence": "e"}]})},
            "finish_reason": "length"}]}  # 每轮补 1 章还截断

    monkeypatch.setattr(cs, "invoke_client_cached", _fake_invoke)
    cont = cs._make_continue_fn(
        "plot", cs._INSTR_PLOT,
        llm_client=_SegFakeClient([]), model="m", max_tokens=8000, cache_enabled=True,
    )
    extra = cont(seg, partial)
    assert n["i"] == cs._SPINE_CONTINUE_MAX_ROUNDS    # 补满上限轮就停
    assert len(extra) == cs._SPINE_CONTINUE_MAX_ROUNDS


def test_continue_fn_no_chapter_field_skips(monkeypatch) -> None:  # noqa: ANN001
    # 段不带 chapter(向后兼容路)→ 判不出差几章,不续抽,不打调用。
    called = {"n": 0}
    monkeypatch.setattr(
        cs, "invoke_client_cached",
        lambda *_a, **_k: called.__setitem__("n", called["n"] + 1) or {},
    )
    cont = cs._make_continue_fn(
        "char", cs._INSTR_CHAR,
        llm_client=_SegFakeClient([]), model="m", max_tokens=8000, cache_enabled=True,
    )
    extra = cont([{"chunk_id": "c0", "text": "无章号"}], [{"chapter": 1}])
    assert extra == []
    assert called["n"] == 0
