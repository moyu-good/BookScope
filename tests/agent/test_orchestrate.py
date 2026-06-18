"""orchestrate.orchestrate 单测（WP-agent-mode §10 编排器）。

全 mock，不跑真 LLM：
- 规划 / 综合两次 LLM 调用走 ``orch._invoke_client``——这里 patch 成一个按 system 文案
  分辨「规划」还是「综合」的假调用，配一个 ``extract_final_text`` 把假响应里的文本取出来；
- 各 ``generate_*`` 走 ``orch._GENERATORS[name]``（白名单表，可 monkeypatch 单项）。

覆盖契约：
- ① 规划只选菜单内功能；菜单外功能名被丢；缺参数的功能被丢；
- ② 按计划调对应 generate_*、只收 verified 发现；
- ③ 单个子功能抛错被跳过、不拖垮整次；
- ④ 综合结论引用收到的发现（citations 钉回发现原文，对不上的丢）；发现为空时不硬编；
- ⑤ callback / SSE 事件序列 plan → 各 step → synthesis；
- ⑥ 规划 / 综合 LLM 解析失败时重试一次。
"""

from __future__ import annotations

import json

from bookscope.agent import orchestrate as orch

# --------------------------------------------------------------------------- #
# 测试夹具：原文 chunk（章号纠偏的 ground truth，这里不真核验所以内容随意）。
# --------------------------------------------------------------------------- #

_CHUNKS = [
    {"chunk_id": "c1", "chapter": 2, "text": "第二章原文。墙角断剑落满灰尘。"},
    {"chunk_id": "c2", "chapter": 9, "text": "第九章原文。少年拔起断剑认主。"},
]


# --------------------------------------------------------------------------- #
# 假 LLM：_invoke_client 按 system 文案分辨规划 / 综合，回不同响应；
# extract_final_text 把响应里塞的文本取出来。两次 LLM 调用各自可指定文本（或文本序列，
# 支持「第一次返坏的、第二次返好的」来测重试）。
# --------------------------------------------------------------------------- #


class _FakeClient:
    """duck-typed LLM client：把 _invoke_client 塞进响应的文本原样吐回。"""

    def extract_final_text(self, resp):  # noqa: ANN001
        return resp["text"]

    def extract_usage_tokens(self, resp):  # noqa: ANN001
        return (0, 0)


def _is_plan_call(system: str) -> bool:
    return "分析编排器" in system


def _patch_llm(monkeypatch, *, plan_texts, synth_texts):
    """patch orch._invoke_client：规划吐 plan_texts 序列、综合吐 synth_texts 序列。

    序列里每个元素是「这次调用 extract_final_text 该返的文本」；按调用顺序逐个取，
    取空了沿用最后一个（重试场景：[坏, 好] 第一次坏第二次好）。
    """
    plan_iter = list(plan_texts)
    synth_iter = list(synth_texts)
    calls: dict[str, int] = {"plan": 0, "synth": 0}

    def _fake(_client, *, system, **_kw):
        if _is_plan_call(system):
            i = min(calls["plan"], len(plan_iter) - 1)
            calls["plan"] += 1
            return {"text": plan_iter[i]}
        i = min(calls["synth"], len(synth_iter) - 1)
        calls["synth"] += 1
        return {"text": synth_iter[i]}

    monkeypatch.setattr(orch, "_invoke_client", _fake)
    return calls


def _plan_json(steps):
    return json.dumps({"plan": steps}, ensure_ascii=False)


def _synth_json(answer, citations):
    return json.dumps(
        {"answer": answer, "citations": citations}, ensure_ascii=False
    )


def _run(monkeypatch, *, goal, plan_texts, synth_texts, on_event=None):
    _patch_llm(monkeypatch, plan_texts=plan_texts, synth_texts=synth_texts)
    return orch.orchestrate(
        goal=goal,
        full_text="（整本书……）",
        chunks=_CHUNKS,
        llm_client=_FakeClient(),
        model="deepseek-v4-flash",
        on_event=on_event,
    )


# --------------------------------------------------------------------------- #
# ① 规划：只选菜单内功能；菜单外被丢；缺参数被丢
# --------------------------------------------------------------------------- #


def test_plan_drops_unknown_feature(monkeypatch):
    """规划返回菜单外功能名 → 被 _validate_plan 丢掉，不进 plan / 不跑。"""
    # timeline 在菜单里、no_such_feature 不在
    monkeypatch.setitem(
        orch._GENERATORS, "generate_timeline",
        lambda **_: [
            {"event": "登基", "evidence": "第二章原文。墙角断剑落满灰尘。",
             "chapter": 2, "verified": True},
        ],
    )
    r = _run(
        monkeypatch,
        goal="梳理大事",
        plan_texts=[_plan_json([
            {"feature": "no_such_feature", "params": {}, "why": "瞎选"},
            {"feature": "timeline", "params": {}, "why": "梳理事件"},
        ])],
        synth_texts=[_synth_json(
            "全书事件如下。", [{"chapter": 2, "snippet": "第二章原文。墙角断剑落满灰尘。"}]
        )],
    )
    plan_features = [s["feature"] for s in r["plan"]]
    assert plan_features == ["timeline"]
    assert "no_such_feature" not in plan_features
    assert r["scanned"] == ["timeline"]


def test_plan_drops_feature_missing_required_param(monkeypatch):
    """要参数的功能（entity_recall 要 entity）模型没给 → 丢那条，不跑。"""
    called = {"entity_recall": False}

    def _spy_entity(**_):
        called["entity_recall"] = True
        return []

    monkeypatch.setitem(orch._GENERATORS, "generate_entity_recall", _spy_entity)
    r = _run(
        monkeypatch,
        goal="查某实体",
        plan_texts=[_plan_json([
            {"feature": "entity_recall", "params": {}, "why": "没给 entity"},
        ])],
        synth_texts=[_synth_json("无", [])],
    )
    assert r["plan"] == []
    assert called["entity_recall"] is False  # 缺参数根本不调


def test_plan_keeps_feature_with_required_param(monkeypatch):
    """要参数的功能给齐了 entity → 进 plan，并把参数透传给 generate_*。"""
    seen_kwargs = {}

    def _entity(**kw):
        seen_kwargs.update(kw)
        return [
            {"what": "登场", "snippet": "第二章原文。墙角断剑落满灰尘。",
             "chapter": 2, "verified": True},
        ]

    monkeypatch.setitem(orch._GENERATORS, "generate_entity_recall", _entity)
    r = _run(
        monkeypatch,
        goal="查断剑",
        plan_texts=[_plan_json([
            {"feature": "entity_recall", "params": {"entity": "断剑"}, "why": "追轨迹"},
        ])],
        synth_texts=[_synth_json(
            "断剑首现于第二章。",
            [{"chapter": 2, "snippet": "第二章原文。墙角断剑落满灰尘。"}],
        )],
    )
    assert [s["feature"] for s in r["plan"]] == ["entity_recall"]
    assert r["plan"][0]["params"] == {"entity": "断剑"}
    assert seen_kwargs.get("entity") == "断剑"  # 参数透传到了 generate_*


# --------------------------------------------------------------------------- #
# ② 跑：按计划调对应 generate_*、只收 verified 发现
# --------------------------------------------------------------------------- #


def test_runs_planned_generator_and_collects_only_verified(monkeypatch):
    """按计划调对应 generate_*，只收 verified 的行（未核验的丢）。"""
    monkeypatch.setitem(
        orch._GENERATORS, "generate_timeline",
        lambda **_: [
            {"event": "登基", "evidence": "第二章原文。墙角断剑落满灰尘。",
             "chapter": 2, "verified": True},
            {"event": "编的事件", "evidence": "查无此句", "chapter": 9,
             "verified": False},
        ],
    )
    r = _run(
        monkeypatch,
        goal="梳理大事",
        plan_texts=[_plan_json([
            {"feature": "timeline", "params": {}, "why": "梳理"},
        ])],
        synth_texts=[_synth_json(
            "登基发生在第二章。",
            [{"chapter": 2, "snippet": "第二章原文。墙角断剑落满灰尘。"}],
        )],
    )
    assert r["scanned"] == ["timeline"]
    # 只有 verified 那条进了 step.found
    assert len(r["steps"]) == 1
    assert r["steps"][0]["feature"] == "timeline"
    assert r["steps"][0]["found"] == 1
    # drill 让前端能点进完整视图
    assert r["steps"][0]["drill"] == {"feature": "timeline", "params": {}}


def test_multiple_features_run_in_plan_order(monkeypatch):
    """计划里多个功能依次跑，scanned / steps 顺序与 plan 一致。"""
    monkeypatch.setitem(
        orch._GENERATORS, "generate_timeline",
        lambda **_: [
            {"event": "事件", "evidence": "第二章原文。墙角断剑落满灰尘。",
             "chapter": 2, "verified": True},
        ],
    )
    monkeypatch.setitem(
        orch._GENERATORS, "generate_style_issues",
        lambda **_: [
            {"what": "重复用词", "snippet": "第九章原文。少年拔起断剑认主。",
             "chapter": 9, "verified": True},
        ],
    )
    r = _run(
        monkeypatch,
        goal="通盘看",
        plan_texts=[_plan_json([
            {"feature": "timeline", "params": {}, "why": "a"},
            {"feature": "style_issues", "params": {}, "why": "b"},
        ])],
        synth_texts=[_synth_json(
            "综合。",
            [{"chapter": 2, "snippet": "第二章原文。墙角断剑落满灰尘。"}],
        )],
    )
    assert r["scanned"] == ["timeline", "style_issues"]
    assert [s["feature"] for s in r["steps"]] == ["timeline", "style_issues"]


# --------------------------------------------------------------------------- #
# ③ 单个子功能抛错被跳过、不拖垮整次
# --------------------------------------------------------------------------- #


def test_failing_feature_skipped_does_not_kill_run(monkeypatch):
    """一个 generate_* 抛错 → 跳过那条、不在 scanned 里，其余照跑、整次不崩。"""
    def _boom(**_):
        raise RuntimeError("generator blew up")

    monkeypatch.setitem(orch._GENERATORS, "generate_timeline", _boom)
    monkeypatch.setitem(
        orch._GENERATORS, "generate_style_issues",
        lambda **_: [
            {"what": "毛病", "snippet": "第九章原文。少年拔起断剑认主。",
             "chapter": 9, "verified": True},
        ],
    )
    r = _run(
        monkeypatch,
        goal="通盘看",
        plan_texts=[_plan_json([
            {"feature": "timeline", "params": {}, "why": "a"},
            {"feature": "style_issues", "params": {}, "why": "b"},
        ])],
        synth_texts=[_synth_json(
            "综合。",
            [{"chapter": 9, "snippet": "第九章原文。少年拔起断剑认主。"}],
        )],
    )
    assert "timeline" not in r["scanned"]
    assert r["scanned"] == ["style_issues"]
    assert [s["feature"] for s in r["steps"]] == ["style_issues"]


# --------------------------------------------------------------------------- #
# ④ 综合：引用收到的发现（evidence-first）；发现为空时不硬编
# --------------------------------------------------------------------------- #


def test_synthesis_grounds_citations_to_findings(monkeypatch):
    """综合 citations 只留能钉回某条发现的；LLM 自造对不上的引用被丢。"""
    monkeypatch.setitem(
        orch._GENERATORS, "generate_timeline",
        lambda **_: [
            {"event": "登基", "evidence": "第二章原文。墙角断剑落满灰尘。",
             "chapter": 2, "verified": True},
        ],
    )
    r = _run(
        monkeypatch,
        goal="梳理大事",
        plan_texts=[_plan_json([
            {"feature": "timeline", "params": {}, "why": "梳理"},
        ])],
        synth_texts=[_synth_json(
            "登基在第二章。",
            [
                # 这条对得上发现（互为子串）
                {"chapter": 2, "snippet": "墙角断剑落满灰尘"},
                # 这条是 LLM 自造、对不上任何发现 → 应被丢
                {"chapter": 5, "snippet": "书外编的一句无证据原文"},
            ],
        )],
    )
    cits = r["synthesis"]["citations"]
    # 只留对得上的那条，且章号用发现的真章号（不信 LLM 自报）
    assert len(cits) == 1
    assert cits[0]["chapter"] == 2
    assert cits[0]["snippet"] == "第二章原文。墙角断剑落满灰尘。"


def test_synthesis_empty_findings_no_fabrication(monkeypatch):
    """所有功能都没查到 verified 发现 → 综合直说没证据，不调综合 LLM、不硬编。"""
    monkeypatch.setitem(
        orch._GENERATORS, "generate_timeline",
        lambda **_: [
            # 全未核验，收不到任何发现
            {"event": "编的", "evidence": "查无此句", "chapter": 2, "verified": False},
        ],
    )
    synth_called = {"n": 0}

    def _fake(_client, *, system, **_kw):
        if "综合分析助手" in system:
            synth_called["n"] += 1
            return {"text": _synth_json("不该被调到", [])}
        return {"text": _plan_json([
            {"feature": "timeline", "params": {}, "why": "梳理"},
        ])}

    monkeypatch.setattr(orch, "_invoke_client", _fake)
    r = orch.orchestrate(
        goal="梳理大事",
        full_text="（整本书……）",
        chunks=_CHUNKS,
        llm_client=_FakeClient(),
        model="deepseek-v4-flash",
    )
    assert r["synthesis"]["citations"] == []
    assert "没" in r["synthesis"]["text"] and "证据" in r["synthesis"]["text"]
    assert synth_called["n"] == 0  # 发现为空：短路，根本不调综合 LLM


# --------------------------------------------------------------------------- #
# ⑤ callback / SSE 事件序列正确：plan → 各 step → synthesis
# --------------------------------------------------------------------------- #


def test_event_sequence_plan_steps_synthesis(monkeypatch):
    """on_event 依次收到 plan、每个功能一个 step、最后 synthesis。"""
    monkeypatch.setitem(
        orch._GENERATORS, "generate_timeline",
        lambda **_: [
            {"event": "事件", "evidence": "第二章原文。墙角断剑落满灰尘。",
             "chapter": 2, "verified": True},
        ],
    )
    monkeypatch.setitem(
        orch._GENERATORS, "generate_style_issues",
        lambda **_: [
            {"what": "毛病", "snippet": "第九章原文。少年拔起断剑认主。",
             "chapter": 9, "verified": True},
        ],
    )
    events: list[dict] = []
    r = _run(
        monkeypatch,
        goal="通盘看",
        plan_texts=[_plan_json([
            {"feature": "timeline", "params": {}, "why": "a"},
            {"feature": "style_issues", "params": {}, "why": "b"},
        ])],
        synth_texts=[_synth_json(
            "综合。",
            [{"chapter": 2, "snippet": "第二章原文。墙角断剑落满灰尘。"}],
        )],
        on_event=events.append,
    )
    types = [e["type"] for e in events]
    assert types == ["plan", "step", "step", "synthesis"]
    # plan 帧带清洗后的 plan
    assert [s["feature"] for s in events[0]["plan"]] == ["timeline", "style_issues"]
    # step 帧顺序对应计划
    assert events[1]["feature"] == "timeline"
    assert events[2]["feature"] == "style_issues"
    # synthesis 帧带 text + citations
    assert events[3]["text"] == r["synthesis"]["text"]
    assert events[3]["citations"] == r["synthesis"]["citations"]


def test_callback_exception_does_not_break_orchestrate(monkeypatch):
    """on_event 抛错被包死，不拖垮编排（仍返完整结果）。"""
    monkeypatch.setitem(
        orch._GENERATORS, "generate_timeline",
        lambda **_: [
            {"event": "事件", "evidence": "第二章原文。墙角断剑落满灰尘。",
             "chapter": 2, "verified": True},
        ],
    )

    def _boom_cb(_event):
        raise RuntimeError("callback blew up")

    r = _run(
        monkeypatch,
        goal="梳理",
        plan_texts=[_plan_json([
            {"feature": "timeline", "params": {}, "why": "a"},
        ])],
        synth_texts=[_synth_json(
            "综合。",
            [{"chapter": 2, "snippet": "第二章原文。墙角断剑落满灰尘。"}],
        )],
        on_event=_boom_cb,
    )
    assert r["scanned"] == ["timeline"]
    assert r["synthesis"]["text"] == "综合。"


# --------------------------------------------------------------------------- #
# ⑥ 规划 / 综合 LLM 解析失败时重试一次
# --------------------------------------------------------------------------- #


def test_plan_parse_failure_retries_once(monkeypatch):
    """规划第一次返坏 JSON、第二次返好的 → 重试后拿到计划。"""
    monkeypatch.setitem(
        orch._GENERATORS, "generate_timeline",
        lambda **_: [
            {"event": "事件", "evidence": "第二章原文。墙角断剑落满灰尘。",
             "chapter": 2, "verified": True},
        ],
    )
    calls = _patch_llm(
        monkeypatch,
        plan_texts=[
            "这不是 JSON，模型瞎说了一通",  # 第一次解析失败
            _plan_json([{"feature": "timeline", "params": {}, "why": "梳理"}]),
        ],
        synth_texts=[_synth_json(
            "综合。",
            [{"chapter": 2, "snippet": "第二章原文。墙角断剑落满灰尘。"}],
        )],
    )
    r = orch.orchestrate(
        goal="梳理",
        full_text="（整本书……）",
        chunks=_CHUNKS,
        llm_client=_FakeClient(),
        model="deepseek-v4-flash",
    )
    assert calls["plan"] == 2  # 重试了一次
    assert [s["feature"] for s in r["plan"]] == ["timeline"]


def test_plan_both_attempts_fail_returns_empty(monkeypatch):
    """规划两次都坏 → 空计划，不跑任何功能，综合短路成「没证据」。"""
    calls = _patch_llm(
        monkeypatch,
        plan_texts=["坏 JSON 1", "坏 JSON 2"],
        synth_texts=[_synth_json("不该被调", [])],
    )
    r = orch.orchestrate(
        goal="梳理",
        full_text="（整本书……）",
        chunks=_CHUNKS,
        llm_client=_FakeClient(),
        model="deepseek-v4-flash",
    )
    assert calls["plan"] == 2
    assert r["plan"] == []
    assert r["scanned"] == []
    assert r["synthesis"]["citations"] == []


def test_synthesis_parse_failure_retries_once(monkeypatch):
    """综合第一次返坏 JSON、第二次返好的 → 重试后拿到综合。"""
    monkeypatch.setitem(
        orch._GENERATORS, "generate_timeline",
        lambda **_: [
            {"event": "事件", "evidence": "第二章原文。墙角断剑落满灰尘。",
             "chapter": 2, "verified": True},
        ],
    )
    calls = _patch_llm(
        monkeypatch,
        plan_texts=[_plan_json([
            {"feature": "timeline", "params": {}, "why": "梳理"},
        ])],
        synth_texts=[
            "综合这次不是 JSON",  # 第一次解析失败
            _synth_json(
                "登基在第二章。",
                [{"chapter": 2, "snippet": "第二章原文。墙角断剑落满灰尘。"}],
            ),
        ],
    )
    r = orch.orchestrate(
        goal="梳理",
        full_text="（整本书……）",
        chunks=_CHUNKS,
        llm_client=_FakeClient(),
        model="deepseek-v4-flash",
    )
    assert calls["synth"] == 2  # 重试了一次
    assert r["synthesis"]["text"] == "登基在第二章。"
    assert len(r["synthesis"]["citations"]) == 1


def test_synthesis_both_attempts_fail_falls_back_to_findings(monkeypatch):
    """综合两次都坏 → 不丢发现，退化成「列出已查到的证据」兜底。"""
    monkeypatch.setitem(
        orch._GENERATORS, "generate_timeline",
        lambda **_: [
            {"event": "事件", "evidence": "第二章原文。墙角断剑落满灰尘。",
             "chapter": 2, "verified": True},
        ],
    )
    calls = _patch_llm(
        monkeypatch,
        plan_texts=[_plan_json([
            {"feature": "timeline", "params": {}, "why": "梳理"},
        ])],
        synth_texts=["坏综合 1", "坏综合 2"],
    )
    r = orch.orchestrate(
        goal="梳理",
        full_text="（整本书……）",
        chunks=_CHUNKS,
        llm_client=_FakeClient(),
        model="deepseek-v4-flash",
    )
    assert calls["synth"] == 2
    # 兜底：发现没丢，作为 citations 直接给出
    assert len(r["synthesis"]["citations"]) == 1
    assert r["synthesis"]["citations"][0]["chapter"] == 2
    assert r["synthesis"]["citations"][0]["snippet"] == "第二章原文。墙角断剑落满灰尘。"
