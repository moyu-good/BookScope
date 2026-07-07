"""卷/幕层(WP-hierarchical-spine)单测 —— 卷切分 / 三守卫 / 结构校验 / 归一。

纯件直接喂数据;build_arc_layer 用 fake client(不调真 LLM)。覆盖 probe 定的三守卫:
①正常切分保留 ②不合规切分→退固定窗口 ③evidence 裁剪到 span ④短书→返 None ⑤结构校验。
"""

from __future__ import annotations

import json

import bookscope.agent.chapter_arcs as ca


# ── 造测试数据 ────────────────────────────────────────────────────────────────
def _spine(n: int) -> list[dict]:
    """造 n 章的紧凑章脉(只需 chapter 字段,build_arc_layer 只看真章数 + 骨架)。"""
    return [
        {"chapter": i, "present": ["甲"], "events": [f"第{i}章事件"], "tension": 5,
         "mainline": True, "foreshadow": []}
        for i in range(1, n + 1)
    ]


class _FakeClient:
    """按预置文本返;extract_final_text 读回上次塞的 content。"""

    def __init__(self, text: str) -> None:
        self._text = text

    def extract_final_text(self, resp):  # noqa: ANN001, ANN201
        return resp["choices"][0]["message"]["content"]


def _volumes_json(volumes: list[dict]) -> str:
    return json.dumps({"volumes": volumes})


def _patch_invoke(monkeypatch, content: str) -> None:
    """把 invoke_client_cached 桩成返固定 content(不调真 LLM)。"""
    monkeypatch.setattr(
        ca, "invoke_client_cached",
        lambda *_a, **_k: {"choices": [{"message": {"content": content}}]},
    )


# ── 守卫 c:短书跳过 → 返 None ─────────────────────────────────────────────────
def test_short_book_returns_none(monkeypatch) -> None:  # noqa: ANN001
    called = {"n": 0}
    monkeypatch.setattr(
        ca, "invoke_client_cached",
        lambda *_a, **_k: called.__setitem__("n", called["n"] + 1) or {},
    )
    # 39 章 < 阈值 40 → 短书,直接返 None,连 LLM 都不调
    out = ca.build_arc_layer(spine=_spine(39), llm_client=_FakeClient(""), model="m")
    assert out is None
    assert called["n"] == 0


def test_short_book_threshold_boundary(monkeypatch) -> None:  # noqa: ANN001
    # 恰好 40 章(= 阈值)→ 不算短书,会去切分(这里 LLM 返合规 4 卷覆盖 40 章)
    vols = [
        {"chapter_span": [1, 10], "title": "一", "evidence_chapters": [3]},
        {"chapter_span": [11, 20], "title": "二", "evidence_chapters": [15]},
        {"chapter_span": [21, 30], "title": "三", "evidence_chapters": [25]},
        {"chapter_span": [31, 40], "title": "四", "evidence_chapters": [38]},
    ]
    _patch_invoke(monkeypatch, _volumes_json(vols))
    out = ca.build_arc_layer(spine=_spine(40), llm_client=_FakeClient(""), model="m")
    assert out is not None
    assert len(out) == 4


# ── 守卫 a(正例):合规切分原样保留 ──────────────────────────────────────────────
def test_valid_split_kept(monkeypatch) -> None:  # noqa: ANN001
    vols = [
        {"chapter_span": [1, 25], "title": "群雄逐鹿", "theme": "开局",
         "key_events": ["e1"], "central_characters": ["甲"], "evidence_chapters": [5, 20]},
        {"chapter_span": [26, 50], "title": "三分天下", "theme": "鼎立",
         "key_events": ["e2"], "central_characters": ["乙"], "evidence_chapters": [40]},
    ]
    _patch_invoke(monkeypatch, _volumes_json(vols))
    out = ca.build_arc_layer(spine=_spine(50), llm_client=_FakeClient(""), model="m")
    assert out is not None
    assert len(out) == 2
    assert out[0]["title"] == "群雄逐鹿"
    assert out[0]["chapter_span"] == [1, 25]
    assert out[0]["central_characters"] == ["甲"]
    # 合规切分不带 approximate 标记(那是兜底才有)
    assert "approximate" not in out[0]


# ── 守卫 a(反例):不合规切分 → 退固定窗口兜底 ────────────────────────────────────
def test_gap_falls_back_to_fixed_window(monkeypatch) -> None:  # noqa: ANN001
    # 26→30 有 gap(第一卷止 25,第二卷起 31)→ 结构不合规 → 退固定窗口
    vols = [
        {"chapter_span": [1, 25], "title": "一", "evidence_chapters": [5]},
        {"chapter_span": [31, 50], "title": "二", "evidence_chapters": [40]},
    ]
    _patch_invoke(monkeypatch, _volumes_json(vols))
    out = ca.build_arc_layer(spine=_spine(50), llm_client=_FakeClient(""), model="m")
    assert out is not None
    # 固定窗口:50 章 / 每 10 章一卷 = 5 卷,全带 approximate 标记
    assert len(out) == 5
    assert all(v["approximate"] is True for v in out)
    assert out[0]["chapter_span"] == [1, 10]
    assert out[-1]["chapter_span"] == [41, 50]


def test_overlap_falls_back_to_fixed_window(monkeypatch) -> None:  # noqa: ANN001
    # 两卷重叠(第一卷止 30,第二卷起 20)→ 不合规 → 退固定窗口
    vols = [
        {"chapter_span": [1, 30], "title": "一", "evidence_chapters": [5]},
        {"chapter_span": [20, 45], "title": "二", "evidence_chapters": [40]},
    ]
    _patch_invoke(monkeypatch, _volumes_json(vols))
    out = ca.build_arc_layer(spine=_spine(45), llm_client=_FakeClient(""), model="m")
    assert out is not None
    assert all(v.get("approximate") is True for v in out)


def test_llm_failure_falls_back_to_fixed_window(monkeypatch) -> None:  # noqa: ANN001
    # LLM 调用抛异常 → graceful 退固定窗口,不崩
    def _boom(*_a, **_k):  # noqa: ANN002, ANN003, ANN202
        raise RuntimeError("api down")

    monkeypatch.setattr(ca, "invoke_client_cached", _boom)
    out = ca.build_arc_layer(spine=_spine(45), llm_client=_FakeClient(""), model="m")
    assert out is not None
    assert all(v.get("approximate") is True for v in out)


def test_empty_llm_output_falls_back(monkeypatch) -> None:  # noqa: ANN001
    # LLM 返空/解析不出 volumes → 退固定窗口
    _patch_invoke(monkeypatch, "抱歉我无法完成")
    out = ca.build_arc_layer(spine=_spine(45), llm_client=_FakeClient(""), model="m")
    assert out is not None
    assert all(v.get("approximate") is True for v in out)


# ── 守卫 b:evidence_chapters 裁到本卷跨度内 ──────────────────────────────────────
def test_evidence_clipped_to_span(monkeypatch) -> None:  # noqa: ANN001
    # 第一卷 [1,25],evidence 点到 30(邻卷)+ 5(本卷)→ 裁掉 30,只留 5
    vols = [
        {"chapter_span": [1, 25], "title": "一", "evidence_chapters": [5, 30, 20]},
        {"chapter_span": [26, 50], "title": "二", "evidence_chapters": [40]},
    ]
    _patch_invoke(monkeypatch, _volumes_json(vols))
    out = ca.build_arc_layer(spine=_spine(50), llm_client=_FakeClient(""), model="m")
    assert out is not None
    assert out[0]["evidence_chapters"] == [5, 20]     # 30 裁掉、去重升序
    assert out[1]["evidence_chapters"] == [40]


# ── 结构校验器 _validate_spans 直测(连续 / 不重叠 / 覆盖)──────────────────────────
def test_validate_spans_continuous_covering() -> None:
    chapters = list(range(1, 31))
    vols = [{"chapter_span": [1, 15]}, {"chapter_span": [16, 30]}]
    assert ca._validate_spans(vols, chapters) is True


def test_validate_spans_rejects_gap() -> None:
    chapters = list(range(1, 31))
    vols = [{"chapter_span": [1, 15]}, {"chapter_span": [17, 30]}]  # 16 漏了
    assert ca._validate_spans(vols, chapters) is False


def test_validate_spans_rejects_overlap() -> None:
    chapters = list(range(1, 31))
    vols = [{"chapter_span": [1, 16]}, {"chapter_span": [15, 30]}]  # 15/16 重叠
    assert ca._validate_spans(vols, chapters) is False


def test_validate_spans_rejects_uncovered_start() -> None:
    chapters = list(range(1, 31))
    vols = [{"chapter_span": [3, 15]}, {"chapter_span": [16, 30]}]  # 1、2 没覆盖
    assert ca._validate_spans(vols, chapters) is False


def test_validate_spans_rejects_uncovered_end() -> None:
    chapters = list(range(1, 31))
    vols = [{"chapter_span": [1, 15]}, {"chapter_span": [16, 28]}]  # 29、30 没覆盖
    assert ca._validate_spans(vols, chapters) is False


def test_validate_spans_rejects_bad_span_shape() -> None:
    chapters = list(range(1, 31))
    assert ca._validate_spans([{"chapter_span": [1]}], chapters) is False       # 缺一个端点
    assert ca._validate_spans([{"chapter_span": [15, 1]}], chapters) is False   # 起 > 止
    assert ca._validate_spans([{"chapter_span": ["a", "b"]}], chapters) is False  # 非整数


def test_validate_spans_covers_book_with_chapter_gaps() -> None:
    # 章脉本身不连号(缺 5-8 章,脏书常见):卷跨度并集必须恰好等于章脉章集,不多算不漏
    chapters = [1, 2, 3, 4, 9, 10, 11, 12]
    vols_ok = [{"chapter_span": [1, 4]}, {"chapter_span": [9, 12]}]
    # 首尾相接要求 prev_hi+1 == cur_lo,这里 4+1=5 ≠ 9 → 按严格规则会判不合规,退兜底
    # (章脉有洞时 LLM 很难切出严格首尾相接的卷,兜底更稳)
    assert ca._validate_spans(vols_ok, chapters) is False


# ── 固定窗口兜底 _fixed_window_arcs 直测 ─────────────────────────────────────────
def test_fixed_window_covers_all_chapters() -> None:
    arcs = ca._fixed_window_arcs(list(range(1, 46)))
    # 45 章 / 每 10 章一卷 = 5 卷([1,10][11,20][21,30][31,40][41,45])
    assert [v["chapter_span"] for v in arcs] == [
        [1, 10], [11, 20], [21, 30], [31, 40], [41, 45],
    ]
    assert all(v["approximate"] is True for v in arcs)
    assert all(v["title"] == "" and v["key_events"] == [] for v in arcs)  # 不硬编内容
    # evidence_chapters = 本窗口全部章
    assert arcs[0]["evidence_chapters"] == list(range(1, 11))


def test_fixed_window_empty_chapters() -> None:
    assert ca._fixed_window_arcs([]) == []


# ── 归一 _normalize_volume 直测 ──────────────────────────────────────────────────
def test_normalize_volume_fills_defaults() -> None:
    out = ca._normalize_volume({"chapter_span": [1, 10]})
    assert out["title"] == "" and out["theme"] == ""
    assert out["key_events"] == [] and out["central_characters"] == []
    assert out["evidence_chapters"] == []


def test_normalize_volume_bad_span_becomes_empty() -> None:
    out = ca._normalize_volume({"chapter_span": "乱", "title": "x"})
    assert out["chapter_span"] == []
    assert out["evidence_chapters"] == []           # span 非法 → evidence 裁成空


# ── 卷切分输出解析 _parse_volumes 直测 ───────────────────────────────────────────
def test_parse_volumes_strips_code_fence() -> None:
    text = "```json\n" + _volumes_json([{"chapter_span": [1, 5]}]) + "\n```"
    out = ca._parse_volumes(text)
    assert out is not None and out[0]["chapter_span"] == [1, 5]


def test_parse_volumes_extracts_from_prose() -> None:
    text = "好的,结果如下:" + _volumes_json([{"chapter_span": [1, 5]}]) + " 以上。"
    out = ca._parse_volumes(text)
    assert out is not None and len(out) == 1


def test_parse_volumes_empty_returns_none() -> None:
    assert ca._parse_volumes("") is None
    assert ca._parse_volumes("完全不是 JSON") is None
    assert ca._parse_volumes('{"other": 1}') is None   # 有 JSON 但没 volumes 键


def test_arc_schema_version_defined() -> None:
    # 卷层结构版本常量在(接 ADR-008,将来升级失效缓存)
    assert ca.ARC_SCHEMA_VERSION == "v1"
    assert ca._ARC_MIN_CHAPTERS == 40
