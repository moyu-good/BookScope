"""long_context.run_long_context 单测（WP-retrieval-routing）。

mock 掉 LLM 调用（monkeypatch _invoke_client）+ 假 client，覆盖契约：
成功拼 AgentQueryResult + 引用核验 / parse 失败 → None / LLM 抛错 → None /
未核验引用保留不删 / 缓存 token 累计 / on_event emit。
"""

from __future__ import annotations

import json

from bookscope.agent import long_context as lc
from bookscope.agent.models import AgentQueryResult

_CHUNKS = [
    {"chunk_id": "c1", "chapter": 1, "text": "安禄山身兼范阳平卢河东三镇节度使，势力极大。"},
    {"chunk_id": "c2", "chapter": 3, "text": "他以奉唐玄宗密诏讨伐杨国忠为借口在范阳起兵。"},
]


class _FakeClient:
    def __init__(self, final_text: str, usage=(100, 20)) -> None:
        self._final = final_text
        self._usage = usage

    def extract_usage_tokens(self, resp):  # noqa: ANN001
        return self._usage

    def extract_final_text(self, resp):  # noqa: ANN001
        return self._final


def _patch_invoke(monkeypatch, *, raises: Exception | None = None, usage_dict=None):
    def _fake(*_a, **_k):
        if raises is not None:
            raise raises
        return {"usage": usage_dict or {
            "prompt_cache_hit_tokens": 50, "prompt_cache_miss_tokens": 10,
        }}
    monkeypatch.setattr(lc, "_invoke_client", _fake)


def _verified(cit):
    return cit.get("verified") if isinstance(cit, dict) else getattr(cit, "verified", None)


def _chapter(cit):
    return cit.get("chapter") if isinstance(cit, dict) else getattr(cit, "chapter", None)


def test_success_returns_result_with_verified_citation(monkeypatch):
    final = json.dumps({
        "answer": "安禄山起兵前身兼范阳、平卢、河东三镇节度使。",
        "citations": [{"chapter": 1, "snippet": "安禄山身兼范阳平卢河东三镇节度使"}],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = lc.run_long_context(
        "安禄山兼哪几镇节度使？", full_text="（整本书原文……）",
        chunks=_CHUNKS, llm_client=_FakeClient(final), model="deepseek-v4-flash",
    )
    assert isinstance(r, AgentQueryResult)
    assert "三镇" in r.answer
    assert r.trace.outcome == "long_context_success"
    assert r.trace.iterations == 1
    assert r.trace.total_input_tokens == 100
    assert r.trace.cache_hit_tokens == 50
    assert r.citations and _verified(r.citations[0]) is True


def test_parse_failure_returns_none(monkeypatch):
    _patch_invoke(monkeypatch)
    r = lc.run_long_context(
        "q", full_text="x", chunks=_CHUNKS,
        llm_client=_FakeClient("这不是 JSON，随便说点别的"), model="m",
    )
    assert r is None


def test_llm_call_raises_returns_none(monkeypatch):
    _patch_invoke(monkeypatch, raises=RuntimeError("boom"))
    r = lc.run_long_context(
        "q", full_text="x", chunks=_CHUNKS, llm_client=_FakeClient("{}"), model="m",
    )
    assert r is None


def test_unverified_citation_kept_not_deleted(monkeypatch):
    final = json.dumps({
        "answer": "某个结论。",
        "citations": [{"chapter": 9, "snippet": "书里根本没有的杜撰片段拿来测假阳性"}],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = lc.run_long_context(
        "q", full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(final), model="m",
    )
    assert isinstance(r, AgentQueryResult)
    assert len(r.citations) == 1  # 保留不删
    assert _verified(r.citations[0]) is False  # 但标 unverified
    assert _chapter(r.citations[0]) == 9  # 未命中 → 不纠偏，保留模型自报章号


def test_verified_citation_chapter_corrected_from_chunk(monkeypatch):
    """模型自报章号漂了（99），但 snippet 逐字命中 c2（真章号 3）→ 用真章号覆盖。"""
    final = json.dumps({
        "answer": "安禄山以讨伐杨国忠为借口起兵。",
        "citations": [
            {"chapter": 99, "snippet": "他以奉唐玄宗密诏讨伐杨国忠为借口在范阳起兵"},
        ],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = lc.run_long_context(
        "安禄山起兵借口？", full_text="x", chunks=_CHUNKS,
        llm_client=_FakeClient(final), model="m",
    )
    assert isinstance(r, AgentQueryResult)
    assert _verified(r.citations[0]) is True
    assert _chapter(r.citations[0]) == 3  # 模型自报 99 被命中 chunk c2 的真章号 3 覆盖


class _SeqClient:
    """每次 extract_final_text 回下一条 final（测重试：坏→好）。"""

    def __init__(self, finals: list[str], usage=(100, 20)) -> None:
        self._finals = finals
        self._i = 0
        self._usage = usage

    def extract_usage_tokens(self, resp):  # noqa: ANN001
        return self._usage

    def extract_final_text(self, resp):  # noqa: ANN001
        t = self._finals[min(self._i, len(self._finals) - 1)]
        self._i += 1
        return t


def test_retry_recovers_on_second_attempt(monkeypatch):
    """第 1 次答案 JSON 不合格、第 2 次合格 → 成功，且两次 token 都累计。"""
    bad = "这不是 JSON，随便说点别的"
    good = json.dumps({
        "answer": "好答案。",
        "citations": [{"chapter": 1, "snippet": "安禄山身兼范阳平卢河东三镇节度使"}],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = lc.run_long_context(
        "q", full_text="x", chunks=_CHUNKS,
        llm_client=_SeqClient([bad, good]), model="m",
    )
    assert isinstance(r, AgentQueryResult)
    assert r.answer == "好答案。"
    assert r.trace.total_input_tokens == 200  # 100 × 2 次尝试都计入


def test_retry_exhausted_returns_none(monkeypatch):
    """两次都不合格 → 回退 RAG（None）。"""
    _patch_invoke(monkeypatch)
    r = lc.run_long_context(
        "q", full_text="x", chunks=_CHUNKS,
        llm_client=_SeqClient(["坏一", "坏二"]), model="m",
    )
    assert r is None


def test_lenient_string_chapter_flows_through(monkeypatch):
    """章号写成字符串 "第99章"：lenient 强转 + snippet 命中 c1 → verified + 真章号 1。"""
    final = json.dumps({
        "answer": "a",
        "citations": [{"chapter": "第99章", "snippet": "安禄山身兼范阳平卢河东三镇节度使"}],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = lc.run_long_context(
        "q", full_text="x", chunks=_CHUNKS,
        llm_client=_FakeClient(final), model="m",
    )
    assert isinstance(r, AgentQueryResult)
    assert _verified(r.citations[0]) is True
    assert _chapter(r.citations[0]) == 1  # 命中 c1 真章号覆盖


def test_on_event_emits_iteration_and_final(monkeypatch):
    final = json.dumps({
        "answer": "a", "citations": [{"chapter": 1, "snippet": "安禄山身兼范阳平卢河东三镇节度使"}],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    events: list = []
    lc.run_long_context(
        "q", full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(final),
        model="m", on_event=events.append,
    )
    names = [type(e).__name__ for e in events]
    assert "IterationStartEvent" in names
    assert "FinalAnswerEvent" in names


# --- 路由 helper（agent.py 接入逻辑）---------------------------------------

class _StubBook:
    def __init__(self, text: str) -> None:
        self.raw_text = text


class _StubChunk:
    def __init__(self, index: int, text: str) -> None:
        self.index = index
        self.text = text


class _StubAssembler:
    def __init__(self, text: str, chunks: list, chunk_to_chapter: dict | None = None) -> None:
        self._book_text = _StubBook(text)
        self._chunks = chunks
        self._chunk_to_chapter = chunk_to_chapter or {}

    def _compute_chunk_to_chapter_map(self) -> dict:
        return self._chunk_to_chapter


def test_should_use_long_context_default_on_when_unset(monkeypatch):
    # 2026-06-16 转默认：未设环境变量 + 书塞得下 → 默认走长上下文
    monkeypatch.delenv("BOOKSCOPE_LONGCTX", raising=False)
    monkeypatch.setenv("BOOKSCOPE_LONGCTX_MAX_TOKENS", "600000")
    from bookscope.api.routes.agent import _should_use_long_context
    assert _should_use_long_context(_StubAssembler("字" * 1000, [])) is True


def test_should_use_long_context_explicit_off(monkeypatch):
    # 逃生口：显式设 off 关回 RAG
    monkeypatch.setenv("BOOKSCOPE_LONGCTX", "off")
    from bookscope.api.routes.agent import _should_use_long_context
    assert _should_use_long_context(_StubAssembler("字" * 1000, [])) is False


def test_should_use_long_context_fits(monkeypatch):
    monkeypatch.setenv("BOOKSCOPE_LONGCTX", "on")
    monkeypatch.setenv("BOOKSCOPE_LONGCTX_MAX_TOKENS", "600000")
    from bookscope.api.routes.agent import _should_use_long_context
    # 10 万字 × 0.68 = 6.8 万 ≤ 60 万 → 走长上下文
    assert _should_use_long_context(_StubAssembler("字" * 100000, [])) is True


def test_should_use_long_context_too_big(monkeypatch):
    monkeypatch.setenv("BOOKSCOPE_LONGCTX", "on")
    monkeypatch.setenv("BOOKSCOPE_LONGCTX_MAX_TOKENS", "600000")
    from bookscope.api.routes.agent import _should_use_long_context
    # 200 万字 × 0.68 = 136 万 > 60 万 → 退回 RAG
    assert _should_use_long_context(_StubAssembler("字" * 2000000, [])) is False


def test_long_context_inputs_builds_evidence():
    from bookscope.api.routes.agent import _long_context_inputs
    # 映射给 chunk0→章2、chunk1→章5；chunk2 不在映射 → 退 0
    asm = _StubAssembler(
        "全书原文",
        [_StubChunk(0, "片段甲"), _StubChunk(1, "片段乙"), _StubChunk(2, "片段丙")],
        chunk_to_chapter={0: 2, 1: 5},
    )
    full, chunks = _long_context_inputs(asm)
    assert full == "全书原文"
    assert chunks[0]["chunk_id"] == "r0-chunk-0"
    assert chunks[0]["text"] == "片段甲"
    assert chunks[0]["chapter"] == 2  # 真章号填进来了
    assert chunks[1]["chapter"] == 5
    assert chunks[2]["chapter"] == 0  # 映射拿不到 → 退 0
    assert len(chunks) == 3
