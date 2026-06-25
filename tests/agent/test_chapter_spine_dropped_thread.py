"""chapter_spine_dropped_thread.dropped_threads_from_spine 单测（病二·证据张冠李戴的修复）。

dropped 内部串两次 LLM：先调 subplot_weave_from_spine（走 chapter_spine_subplot 的
invoke_client_cached）出支线，再调复核（走本模块的 invoke_client_cached）判收束/悬着。
两个模块各 patch 一次。

覆盖：传 chunks → snippet 按失踪线名在末活跃章原文现捞、真讲那条线、不是章代表句；
chunks=None → snippet 退回章代表句（向后兼容）；复核判正常收束 → 滤掉。
不跑真 LLM。
"""

from __future__ import annotations

import json

from bookscope.agent import chapter_spine_dropped_thread as cdt
from bookscope.agent import chapter_spine_subplot as csub

# 末活跃章=第3章；第3章原文里既有"祭天大典"的真句，也有别的最显眼的事（章代表句来源）。
_CHUNKS = [
    {"chunk_id": "c2", "chapter": 2,
     "text": "国主筹备祭天大典，昭告天下。百官奔走相告。"},
    {"chunk_id": "c3", "chapter": 3,
     "text": "祭天大典如期举行，礼成而散。另有一场宫廷宴饮喧闹至深夜，乃本章最热闹处。"},
    {"chunk_id": "c10", "chapter": 10,
     "text": "全书终章，主线诸事各有交代，唯祭天一线再无下文。"},
]

# spine：events 给现捞拼 query；evidence 是章代表句（chunks=None 时的旧 snippet 来源）。
# 末章=10（_book_last_chapter 取最大章号）。
_SPINE = [
    {"chapter": 2, "evidence": "第2章章代表句。", "events": [{"event": "筹备祭天"}]},
    {"chapter": 3, "evidence": "第3章章代表句：宫廷宴饮喧闹至深夜。",
     "events": [{"event": "祭天大典举行"}]},
    {"chapter": 10, "evidence": "第10章章代表句。", "events": [{"event": "主线收束"}]},
]

# subplot LLM 吐出的支线：祭天大典线活跃到第3章后消失（末章10，沉默尾巴7≥5）。
_WEAVE = json.dumps({
    "subplots": [{"name": "祭天大典线", "active_chapters": [2, 3]}],
    "intersections": [],
}, ensure_ascii=False)

# 复核 LLM：判这条线是"真悬着"（dropped=true），不滤掉。
_VERDICTS = json.dumps({
    "verdicts": [{"thread": "祭天大典线", "dropped": True, "why": "起了头后文无交代"}],
}, ensure_ascii=False)


class _FakeClient:
    def extract_final_text(self, resp):  # noqa: ANN001
        return resp if isinstance(resp, str) else ""


def _patch_both(monkeypatch, *, weave=_WEAVE, verdicts=_VERDICTS):
    """subplot 模块的 invoke_client_cached 返支线、dropped 模块的返复核裁决。"""
    monkeypatch.setattr(csub, "invoke_client_cached", lambda *a, **k: weave)
    monkeypatch.setattr(cdt, "invoke_client_cached", lambda *a, **k: verdicts)


def _run(*, chunks=None, spine=None):
    return cdt.dropped_threads_from_spine(
        spine=spine if spine is not None else _SPINE,
        llm_client=_FakeClient(),
        model="deepseek-v4-flash",
        chunks=chunks,
        min_silent_tail=5,
    )


def test_with_chunks_snippet_fresh_caught(monkeypatch):
    """传 chunks → snippet 按失踪线名在末活跃章原文现捞，真讲这条线，不是章代表句。"""
    _patch_both(monkeypatch)
    out = _run(chunks=_CHUNKS)
    assert len(out) == 1
    d = out[0]
    assert d["thread"] == "祭天大典线"
    assert d["last_active_chapter"] == 3
    # 现捞到第3章里真讲祭天的那句，不是"宫廷宴饮"那条章代表句。
    assert "祭天大典" in d["snippet"]
    assert "宫廷宴饮" not in d["snippet"]
    assert d["verified"] is True


def test_with_chunks_no_support_unverified(monkeypatch):
    """末活跃章原文里捞不到讲这条线的句子 → snippet 空、verified=False。"""
    chunks = [
        # 第3章原文里线名("祭天大典线")半个字都不沾，只讲边关战事 → 现捞不到。
        {"chunk_id": "c3", "chapter": 3, "text": "这一章只写边关战事，将士枕戈待旦。"},
    ]
    _patch_both(monkeypatch)
    out = _run(chunks=chunks)
    assert len(out) == 1
    assert out[0]["snippet"] == ""
    assert out[0]["verified"] is False


def test_without_chunks_backward_compatible(monkeypatch):
    """chunks=None → snippet 退回末活跃章的章代表句（向后兼容旧行为）。"""
    _patch_both(monkeypatch)
    out = _run(chunks=None)
    assert len(out) == 1
    assert out[0]["snippet"] == "第3章章代表句：宫廷宴饮喧闹至深夜。"
    assert out[0]["verified"] is True


def test_review_says_resolved_filtered(monkeypatch):
    """复核判正常收束（dropped=false）→ 这条滤掉，不报（不 cry wolf）。"""
    resolved = json.dumps({
        "verdicts": [{"thread": "祭天大典线", "dropped": False, "why": "已正常收束"}],
    }, ensure_ascii=False)
    _patch_both(monkeypatch, verdicts=resolved)
    out = _run(chunks=_CHUNKS)
    assert out == []


def test_no_subplots_returns_empty(monkeypatch):
    """支线编织抽不出支线 → []（合法，不是失败）。"""
    empty = json.dumps({"subplots": [], "intersections": []}, ensure_ascii=False)
    _patch_both(monkeypatch, weave=empty)
    out = _run(chunks=_CHUNKS)
    assert out == []
