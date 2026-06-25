"""_internal/exhaustive.py —— 按章 map-reduce 可复用件单测(分段 + 按章 concat 去重)。

mock LLM(monkeypatch invoke_client_cached 给每段递增标记)+ 假 client(按段返不同章 JSON)。
不调真 LLM。
"""

from __future__ import annotations

import json

import bookscope.agent._internal.exhaustive as ex


def test_segment_chunks_splits_by_budget() -> None:
    chunks = [{"chunk_id": f"c{i}", "text": "一二三四五"} for i in range(5)]  # 每个 5 字
    assert len(ex.segment_chunks(chunks, char_budget=8)) == 5  # 每段 1 个
    assert len(ex.segment_chunks(chunks, char_budget=12)) == 3  # [c0c1][c2c3][c4]
    assert len(ex.segment_chunks([], 40)) == 0


def test_segment_chunks_caps_by_max_chapters() -> None:
    # ADR-010 D-7 章闸:20 个 chunk 各属不同章、每个很短(字数闸不触发),max_chapters=5 → 按章切
    chunks = [{"chunk_id": f"c{i}", "chapter": i, "text": "短"} for i in range(20)]
    segs = ex.segment_chunks(chunks, char_budget=100000, max_chapters=5)
    assert len(segs) == 4  # 20 章 / 每段至多 5 章
    assert all(len({c["chapter"] for c in s}) <= 5 for s in segs)


def test_segment_chunks_same_chapter_not_counted_twice() -> None:
    # 同章多 chunk 不算多章:10 个 chunk 都属 chapter 1,max_chapters=2 不该切(字数也不超)
    chunks = [{"chunk_id": f"c{i}", "chapter": 1, "text": "短"} for i in range(10)]
    assert len(ex.segment_chunks(chunks, char_budget=100000, max_chapters=2)) == 1


def test_segment_chunks_no_chapter_field_ignores_cap() -> None:
    # 不带 chapter 时章闸不触发,退回纯字符预算(向后兼容)
    chunks = [{"chunk_id": f"c{i}", "text": "一二三四五"} for i in range(5)]
    assert len(ex.segment_chunks(chunks, char_budget=12, max_chapters=1)) == 3


def test_segment_chunks_char_budget_still_wins_when_tighter() -> None:
    # 长章场景:每章一个 4 万字 chunk,字数闸先到,章闸(12)咬不到 → 每段 1 章
    chunks = [{"chunk_id": f"c{i}", "chapter": i, "text": "字" * 39000} for i in range(3)]
    segs = ex.segment_chunks(chunks, char_budget=40000, max_chapters=12)
    assert len(segs) == 3  # 字数先到,每段 1 章


def test_resolve_workers() -> None:
    assert ex.resolve_workers(3) == 3
    assert ex.resolve_workers(0) == 1  # < 1 兜底 1
    assert ex.resolve_workers(None, default=6) == 6


class _FakeMulti:
    def __init__(self, texts: list[str]) -> None:
        self._texts = list(texts)

    def extract_usage_tokens(self, resp):  # noqa: ANN001
        return (10, 5)

    def extract_final_text(self, resp):  # noqa: ANN001
        i = resp.get("_seg", 0)
        return self._texts[i] if i < len(self._texts) else '{"chapters": []}'


def _seq_patch(monkeypatch) -> None:  # noqa: ANN001
    state = {"i": 0}

    def _fake(*_a, **_k):  # noqa: ANN002, ANN003
        i = state["i"]
        state["i"] += 1
        return {"_seg": i}

    monkeypatch.setattr(ex, "invoke_client_cached", _fake)


def _parse(text: str):  # noqa: ANN202
    try:
        return json.loads(text).get("chapters", [])
    except Exception:
        return []


def test_mapreduce_concats_and_dedups_by_chapter(monkeypatch) -> None:  # noqa: ANN001
    _seq_patch(monkeypatch)
    chunks = [{"chunk_id": "c0", "text": "甲"}, {"chunk_id": "c1", "text": "乙"}]
    texts = [
        json.dumps({"chapters": [{"chapter": 2, "v": "a"}, {"chapter": 1, "v": "a"}]}),
        json.dumps({"chapters": [{"chapter": 3, "v": "b"}, {"chapter": 2, "v": "dup"}]}),
    ]
    out = ex.mapreduce_per_chapter(
        chunks=chunks, instruction="x", user_msg="y", parse_fn=_parse,
        llm_client=_FakeMulti(texts), model="m", max_tokens=100,
        char_budget=1, max_workers=1,  # char_budget=1 → 每 chunk 一段
    )
    # 1,2,3 各一条;章 2 跨段重复 → 只留首见(第一段的 "a")
    assert [c["chapter"] for c in out] == [1, 2, 3]
    assert next(c for c in out if c["chapter"] == 2)["v"] == "a"


def test_mapreduce_correct_fn_runs_before_merge(monkeypatch) -> None:  # noqa: ANN001
    """多卷书 bug 的最小复现 + 修复证明:模型两段都自报小章号 1、2(撞号),靠 evidence 里的
    真章号纠偏。``correct_fn`` 在合并前逐段跑 → 后段纠成 3、4,四章全留;不跑 → 后段跟前段
    撞章被 ``merge_by_chapter`` 去重吞掉,只剩 2 章(明朝 158→30 就是这么丢的)。
    """
    _seq_patch(monkeypatch)
    chunks = [{"chunk_id": "c0", "text": "甲"}, {"chunk_id": "c1", "text": "乙"}]
    texts = [
        json.dumps({"chapters": [{"chapter": 1, "true": 1}, {"chapter": 2, "true": 2}]}),
        json.dumps({"chapters": [{"chapter": 1, "true": 3}, {"chapter": 2, "true": 4}]}),
    ]

    def _correct(seg, _chunks):  # noqa: ANN001, ANN202 — 模拟章号纠偏:把自报章号改成 evidence 真章号
        for item in seg:
            item["chapter"] = item["true"]

    out_fixed = ex.mapreduce_per_chapter(
        chunks=chunks, instruction="x", user_msg="y", parse_fn=_parse,
        llm_client=_FakeMulti(texts), model="m", max_tokens=100,
        char_budget=1, max_workers=1, correct_fn=_correct,
    )
    assert [c["chapter"] for c in out_fixed] == [1, 2, 3, 4]  # 合并前纠偏 → 四章全留

    _seq_patch(monkeypatch)  # 重置段计数器
    out_buggy = ex.mapreduce_per_chapter(
        chunks=chunks, instruction="x", user_msg="y", parse_fn=_parse,
        llm_client=_FakeMulti(texts), model="m", max_tokens=100,
        char_budget=1, max_workers=1,  # correct_fn=None → 按自报章号先去重
    )
    assert [c["chapter"] for c in out_buggy] == [1, 2]  # 后段撞号被吞,正是要修的 bug


def test_mapreduce_skips_unparseable_segment(monkeypatch) -> None:  # noqa: ANN001
    _seq_patch(monkeypatch)
    chunks = [{"chunk_id": "c0", "text": "甲"}, {"chunk_id": "c1", "text": "乙"}]
    out = ex.mapreduce_per_chapter(
        chunks=chunks, instruction="x", user_msg="y", parse_fn=_parse,
        llm_client=_FakeMulti(["不是JSON", json.dumps({"chapters": [{"chapter": 5}]})]),
        model="m", max_tokens=100, char_budget=1, max_workers=1,
    )
    assert [c["chapter"] for c in out] == [5]  # 坏段跳过,好段保留


# ── reduce 合并件（纯函数，直接喂 outs，不过 LLM）─────────────────────────────


def test_merge_by_chapter_dedups_and_sorts() -> None:
    outs = [
        [{"chapter": 2, "v": "a"}, {"chapter": 1, "v": "a"}],
        [{"chapter": 3, "v": "b"}, {"chapter": 2, "v": "dup"}],
    ]
    out = ex.merge_by_chapter(outs)
    assert [c["chapter"] for c in out] == [1, 2, 3]
    assert next(c for c in out if c["chapter"] == 2)["v"] == "a"  # 保先出现


def test_merge_by_key_dedups_keeps_first() -> None:
    outs = [
        [{"event": "赤壁", "x": 1}, {"event": "官渡", "x": 1}],
        [{"event": "赤壁", "x": 2}, {"event": "夷陵", "x": 3}],  # 赤壁跨段重复
    ]
    out = ex.merge_by_key(outs, key_fn=lambda e: e["event"])
    assert [e["event"] for e in out] == ["赤壁", "官渡", "夷陵"]
    assert out[0]["x"] == 1  # 保先出现段的值


def test_merge_by_key_drops_none_key() -> None:
    outs = [[{"event": "赤壁"}, {"noevent": True}]]
    out = ex.merge_by_key(outs, key_fn=lambda e: e.get("event"))
    assert [e.get("event") for e in out] == ["赤壁"]  # key=None 丢


def test_merge_keyed_points_unions_subpoints_by_chapter() -> None:
    # 同一角色「刘备」跨两段，各带不同章的 points；标量 name 保先出现
    outs = [
        [{"name": "刘备", "points": [{"chapter": 1, "v": 5}, {"chapter": 2, "v": 6}]}],
        [{"name": "刘备", "points": [{"chapter": 2, "v": 99}, {"chapter": 5, "v": 7}]},
         {"name": "曹操", "points": [{"chapter": 1, "v": 8}]}],
    ]
    out = ex.merge_keyed_points(outs, key_fn=lambda c: c["name"], point_fields=["points"])
    assert [c["name"] for c in out] == ["刘备", "曹操"]  # 按首见顺序
    liubei = out[0]
    assert [p["chapter"] for p in liubei["points"]] == [1, 2, 5]  # 并集 + 升序
    assert next(p for p in liubei["points"] if p["chapter"] == 2)["v"] == 6  # 章 2 保先出现


def test_merge_keyed_points_multiple_point_fields() -> None:
    outs = [
        [{"a": "刘备", "b": "曹操", "relation": "政敌",
          "points": [{"chapter": 1, "strength": 3}],
          "turning_points": [{"chapter": 1, "change": "初见"}]}],
        [{"a": "刘备", "b": "曹操", "relation": "ignored",
          "points": [{"chapter": 9, "strength": 8}],
          "turning_points": [{"chapter": 9, "change": "决裂"}]}],
    ]
    out = ex.merge_keyed_points(
        outs, key_fn=lambda r: frozenset((r["a"], r["b"])),
        point_fields=["points", "turning_points"],
    )
    assert len(out) == 1
    assert out[0]["relation"] == "政敌"  # 标量保先出现
    assert [p["chapter"] for p in out[0]["points"]] == [1, 9]
    assert [t["chapter"] for t in out[0]["turning_points"]] == [1, 9]


def test_merge_keyed_points_multi_per_key_keeps_same_chapter() -> None:
    # 同一章 2 个不同转折:按章去重会吞掉第二个;multi_per_key_fields 改按整条去重 → 都留
    outs = [
        [
            {
                "a": "刘备",
                "b": "曹操",
                "turning_points": [
                    {"chapter": 5, "change": "初见"},
                    {"chapter": 5, "change": "决裂"},
                ],
            }
        ],
    ]
    out = ex.merge_keyed_points(
        outs,
        key_fn=lambda r: frozenset((r["a"], r["b"])),
        point_fields=["turning_points"],
        multi_per_key_fields=frozenset({"turning_points"}),
    )
    assert [t["change"] for t in out[0]["turning_points"]] == ["初见", "决裂"]


def test_merge_keyed_points_default_dedups_same_chapter() -> None:
    # 默认(不在 multi_per_key_fields):同章按章去重只留首条
    outs = [[{"name": "刘备", "points": [{"chapter": 5, "v": 1}, {"chapter": 5, "v": 2}]}]]
    out = ex.merge_keyed_points(
        outs, key_fn=lambda c: c["name"], point_fields=["points"]
    )
    assert [p["v"] for p in out[0]["points"]] == [1]


# ── 1.5.2 方案 A/B/C：finish_reason 可观测 + 章闸透传 + 截断续抽 ───────────────


def _resp(text: str, finish_reason: str = "stop") -> dict:
    """造一个带 finish_reason 的 OpenAI 形态 response（run_segment 读其 finish_reason）。"""
    return {
        "choices": [{"message": {"content": text}, "finish_reason": finish_reason}],
    }


class _FakeFinish:
    """每段按 finish_reason 区分返回；extract_final_text 读回 content。"""

    def extract_final_text(self, resp):  # noqa: ANN001, ANN201
        return resp["choices"][0]["message"]["content"]


def test_run_segments_passes_max_chapters_down(monkeypatch) -> None:  # noqa: ANN001
    # 方案 B：run_segments 把 max_chapters 透传给 segment_chunks（不再写死全局 12）。
    seen = {}

    def _spy_segment(  # noqa: ANN202
        chunks,  # noqa: ANN001
        char_budget=ex.DEFAULT_CHAR_BUDGET,  # noqa: ANN001
        max_chapters=ex.DEFAULT_MAX_CHAPTERS,  # noqa: ANN001
    ):
        seen["max_chapters"] = max_chapters
        return [chunks]  # 一段省事

    monkeypatch.setattr(ex, "segment_chunks", _spy_segment)
    monkeypatch.setattr(ex, "invoke_client_cached", lambda *_a, **_k: _resp('{"chapters": []}'))
    ex.run_segments(
        chunks=[{"chunk_id": "c0", "chapter": 1, "text": "甲"}],
        instruction="x", user_msg="y", parse_fn=_parse,
        llm_client=_FakeFinish(), model="m", max_tokens=100,
        max_chapters=6, max_workers=1,
    )
    assert seen["max_chapters"] == 6


def test_run_segments_default_max_chapters_unchanged(monkeypatch) -> None:  # noqa: ANN001
    # 不传 max_chapters → 沿用全局 DEFAULT_MAX_CHAPTERS（别的穷尽化功能行为不变）。
    seen = {}

    def _spy_segment(  # noqa: ANN202
        chunks,  # noqa: ANN001
        char_budget=ex.DEFAULT_CHAR_BUDGET,  # noqa: ANN001
        max_chapters=ex.DEFAULT_MAX_CHAPTERS,  # noqa: ANN001
    ):
        seen["max_chapters"] = max_chapters
        return [chunks]

    monkeypatch.setattr(ex, "segment_chunks", _spy_segment)
    monkeypatch.setattr(ex, "invoke_client_cached", lambda *_a, **_k: _resp('{"chapters": []}'))
    ex.run_segments(
        chunks=[{"chunk_id": "c0", "chapter": 1, "text": "甲"}],
        instruction="x", user_msg="y", parse_fn=_parse,
        llm_client=_FakeFinish(), model="m", max_tokens=100, max_workers=1,
    )
    assert seen["max_chapters"] == ex.DEFAULT_MAX_CHAPTERS == 12


def test_run_segment_no_finish_reason_is_not_truncated(monkeypatch) -> None:  # noqa: ANN001
    # finish_reason 缺失（老 Fake / 缓存形态）→ 当"不知道是否截断"，不触发续抽，行为不变。
    called = {"continue": False}

    def _continue(_seg, _partial):  # noqa: ANN001, ANN202
        called["continue"] = True
        return [{"chapter": 99}]

    monkeypatch.setattr(
        ex, "invoke_client_cached",
        lambda *_a, **_k: {"_seg": 0},  # 无 choices → finish_reason None
    )

    class _C:
        def extract_final_text(self, _resp):  # noqa: ANN001, ANN201
            return json.dumps({"chapters": [{"chapter": 1}]})

    outs = ex.run_segments(
        chunks=[{"chunk_id": "c0", "chapter": 1, "text": "甲"}],
        instruction="x", user_msg="y", parse_fn=_parse,
        llm_client=_C(), model="m", max_tokens=100, max_workers=1,
        continue_fn=_continue,
    )
    assert called["continue"] is False
    assert [c["chapter"] for c in outs[0]] == [1]


def test_run_segment_truncated_calls_continue_and_appends(monkeypatch) -> None:  # noqa: ANN001
    # 方案 A + C：finish_reason=length 且抢救到部分 → 调 continue_fn 把差掉的章补回来 append。
    monkeypatch.setattr(
        ex, "invoke_client_cached",
        lambda *_a, **_k: _resp(json.dumps({"chapters": [{"chapter": 1}]}), "length"),
    )

    def _continue(seg, partial):  # noqa: ANN001, ANN202
        assert [c["chapter"] for c in partial] == [1]  # 拿到已抢救的
        return [{"chapter": 2}, {"chapter": 3}]  # 补回差掉的两章

    outs = ex.run_segments(
        chunks=[{"chunk_id": f"c{i}", "chapter": i, "text": "甲"} for i in (1, 2, 3)],
        instruction="x", user_msg="y", parse_fn=_parse,
        llm_client=_FakeFinish(), model="m", max_tokens=100,
        char_budget=100000, max_chapters=12, max_workers=1,
        continue_fn=_continue,
    )
    # 一段（章闸 12、字数够）→ 截断抢救 1 章 + 续抽补 2 章 = 三章齐
    assert [c["chapter"] for c in outs[0]] == [1, 2, 3]


def test_run_segment_truncated_without_continue_keeps_partial(monkeypatch) -> None:  # noqa: ANN001
    # 截断但没配 continue_fn → 保留抢救到的部分（不补、不丢光），行为跟旧版一致。
    monkeypatch.setattr(
        ex, "invoke_client_cached",
        lambda *_a, **_k: _resp(json.dumps({"chapters": [{"chapter": 1}]}), "length"),
    )
    outs = ex.run_segments(
        chunks=[{"chunk_id": "c0", "chapter": 1, "text": "甲"}],
        instruction="x", user_msg="y", parse_fn=_parse,
        llm_client=_FakeFinish(), model="m", max_tokens=100, max_workers=1,
    )
    assert [c["chapter"] for c in outs[0]] == [1]


def test_run_segment_truncated_empty_single_chapter_gives_up(monkeypatch) -> None:  # noqa: ANN001
    # 截断且一条都没抢救到、且段只剩单章 → 拆不动（单章是下限）→ 放弃返空。不续抽。
    called = {"continue": False}

    def _continue(_seg, _partial):  # noqa: ANN001, ANN202
        called["continue"] = True
        return [{"chapter": 1}]

    monkeypatch.setattr(
        ex, "invoke_client_cached",
        lambda *_a, **_k: _resp("不是JSON半截", "length"),
    )
    outs = ex.run_segments(
        chunks=[{"chunk_id": "c0", "chapter": 1, "text": "甲"}],
        instruction="x", user_msg="y", parse_fn=_parse,
        llm_client=_FakeFinish(), model="m", max_tokens=100, max_workers=1,
        continue_fn=_continue,
    )
    assert called["continue"] is False
    assert outs[0] == []  # 单章拆不动,放弃


# ── 1.5.2 丢章修复：截断且抢救为 0 → 按章拆小重抽，不跳过整段 ──────────────────


def test_split_segment_by_chapter_halves() -> None:
    seg = [{"chunk_id": f"c{i}", "chapter": i, "text": "x"} for i in range(1, 7)]  # 6 章
    subs = ex._split_segment_by_chapter(seg)
    assert subs is not None
    assert [c["chapter"] for c in subs[0]] == [1, 2, 3]  # 前一半章
    assert [c["chapter"] for c in subs[1]] == [4, 5, 6]  # 后一半章


def test_split_segment_keeps_same_chapter_chunks_together() -> None:
    # 同章多 chunk 不拆散:章 1 两个 chunk + 章 2 两个 chunk → 拆成 [章1] / [章2]
    seg = [
        {"chunk_id": "a", "chapter": 1, "text": "x"},
        {"chunk_id": "b", "chapter": 1, "text": "y"},
        {"chunk_id": "c", "chapter": 2, "text": "z"},
        {"chunk_id": "d", "chapter": 2, "text": "w"},
    ]
    subs = ex._split_segment_by_chapter(seg)
    assert subs is not None
    assert {c["chunk_id"] for c in subs[0]} == {"a", "b"}
    assert {c["chunk_id"] for c in subs[1]} == {"c", "d"}


def test_split_segment_single_chapter_returns_none() -> None:
    seg = [{"chunk_id": f"c{i}", "chapter": 1, "text": "x"} for i in range(3)]  # 都是单章
    assert ex._split_segment_by_chapter(seg) is None


def test_split_segment_no_chapter_returns_none() -> None:
    seg = [{"chunk_id": f"c{i}", "text": "x"} for i in range(3)]  # 不带 chapter
    assert ex._split_segment_by_chapter(seg) is None


def test_run_segment_truncated_empty_splits_and_covers_all_chapters(monkeypatch) -> None:  # noqa: ANN001
    # 核心修复路径:一段 6 章,整段抽时**总被截断且抢救为 0**(旧逻辑会丢掉全部 6 章);
    # 拆小后单章能抽出 → 断言拆到每章都被覆盖、零丢。
    # 桩:段含 >1 章(即"还没拆到单章")时返截断空响应,逼它继续拆;拆到单章时正常返该章。
    def _fake_invoke(*_a, **kwargs):  # noqa: ANN002, ANN003, ANN202
        # build_longctx_system 把段原文塞进 system;从 system 数出现了几个章标记判断段大小。
        system = kwargs.get("system", "")
        marks = [n for n in range(1, 7) if f"〔章{n}〕" in system]
        if len(marks) > 1:
            return _resp("截断半截没法解析", "length")  # 多章段:截断且抢救为 0
        # 单章段:正常返该章一条
        ch = marks[0]
        return _resp(json.dumps({"chapters": [{"chapter": ch}]}), "stop")

    monkeypatch.setattr(ex, "invoke_client_cached", _fake_invoke)
    chunks = [
        {"chunk_id": f"c{i}", "chapter": i, "text": f"〔章{i}〕正文"} for i in range(1, 7)
    ]
    outs = ex.run_segments(
        chunks=chunks, instruction="x", user_msg="y", parse_fn=_parse,
        llm_client=_FakeFinish(), model="m", max_tokens=100,
        char_budget=100000, max_chapters=12, max_workers=1,  # 一段含全 6 章
    )
    got = sorted(c["chapter"] for seg_out in outs for c in seg_out)
    assert got == [1, 2, 3, 4, 5, 6]  # 拆小后每章都覆盖,零丢


def test_run_segment_split_respects_depth_limit(monkeypatch) -> None:  # noqa: ANN001
    # 每段(含单章)永远返截断且抢救为 0 → 递归靠 _SPLIT_MAX_DEPTH + 单章拆不动双重收敛,
    # 不无限递归;最终覆盖为空(谁也抽不出),但不挂死。
    calls = {"n": 0}

    def _fake_invoke(*_a, **_k):  # noqa: ANN002, ANN003, ANN202
        calls["n"] += 1
        return _resp("永远截断", "length")

    monkeypatch.setattr(ex, "invoke_client_cached", _fake_invoke)
    chunks = [{"chunk_id": f"c{i}", "chapter": i, "text": "x"} for i in range(1, 9)]  # 8 章
    outs = ex.run_segments(
        chunks=chunks, instruction="x", user_msg="y", parse_fn=_parse,
        llm_client=_FakeFinish(), model="m", max_tokens=100,
        char_budget=100000, max_chapters=12, max_workers=1,
    )
    assert [c for seg_out in outs for c in seg_out] == []  # 谁也抽不出
    assert calls["n"] < 100  # 收敛,不爆炸(8 章拆树调用数有限)


# ── 1.5.2 兜底不变量：合并后缺章 → 单章重抽补齐 ────────────────────────────────


def _sweep_invoke(*_a, **kwargs):  # noqa: ANN002, ANN003, ANN202
    # 多章段:漏掉章 3(没截断、模型就是漏了);单章段(兜底重抽):正常返该章。
    system = kwargs.get("system", "")
    marks = [n for n in range(1, 4) if f"〔章{n}〕" in system]
    if len(marks) > 1:
        return _resp(json.dumps({"chapters": [{"chapter": 1}, {"chapter": 2}]}))
    return _resp(json.dumps({"chapters": [{"chapter": marks[0]}]}))


def test_mapreduce_sweep_recovers_missing_chapter(monkeypatch) -> None:  # noqa: ANN001
    # 第一遍整段漏掉章 3 → 兜底按"每个喂入章都得出现"单章重抽,把章 3 救回。
    monkeypatch.setattr(ex, "invoke_client_cached", _sweep_invoke)
    chunks = [{"chunk_id": f"c{i}", "chapter": i, "text": f"〔章{i}〕正文"} for i in range(1, 4)]
    out = ex.mapreduce_per_chapter(
        chunks=chunks, instruction="x", user_msg="y", parse_fn=_parse,
        llm_client=_FakeFinish(), model="m", max_tokens=100,
        char_budget=100000, max_chapters=12, max_workers=1,
        correct_fn=lambda _seg, _c: None, sweep_missing_chapters=True,
    )
    assert [c["chapter"] for c in out] == [1, 2, 3]  # 漏的章 3 被兜底救回


def test_mapreduce_sweep_off_keeps_missing(monkeypatch) -> None:  # noqa: ANN001
    # 不开 sweep(默认)→ 漏的章不补,别的穷尽化功能行为不变。
    monkeypatch.setattr(ex, "invoke_client_cached", _sweep_invoke)
    chunks = [{"chunk_id": f"c{i}", "chapter": i, "text": f"〔章{i}〕正文"} for i in range(1, 4)]
    out = ex.mapreduce_per_chapter(
        chunks=chunks, instruction="x", user_msg="y", parse_fn=_parse,
        llm_client=_FakeFinish(), model="m", max_tokens=100,
        char_budget=100000, max_chapters=12, max_workers=1,
        correct_fn=lambda _seg, _c: None,  # sweep_missing_chapters 默认 False
    )
    assert [c["chapter"] for c in out] == [1, 2]  # 漏的章 3 不补


def test_mapreduce_sweep_needs_correct_fn(monkeypatch) -> None:  # noqa: ANN001
    # 兜底只在有 correct_fn(章号可信)时生效——无 correct_fn 时不扫,免得拿自报章号瞎补。
    monkeypatch.setattr(ex, "invoke_client_cached", _sweep_invoke)
    chunks = [{"chunk_id": f"c{i}", "chapter": i, "text": f"〔章{i}〕正文"} for i in range(1, 4)]
    out = ex.mapreduce_per_chapter(
        chunks=chunks, instruction="x", user_msg="y", parse_fn=_parse,
        llm_client=_FakeFinish(), model="m", max_tokens=100,
        char_budget=100000, max_chapters=12, max_workers=1,
        sweep_missing_chapters=True,  # 但没 correct_fn → 不扫
    )
    assert [c["chapter"] for c in out] == [1, 2]  # 没补
