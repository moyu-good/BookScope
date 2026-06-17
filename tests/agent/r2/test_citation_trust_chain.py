"""WP1 citation 可信链 + WP5a partial_evidence 的 r2 loop 集成测试。

设计稿：``docs/internal/design/WP1-citation-trust-chain.md``。覆盖成功标准：

1. 答题 snippet 与工具返回一致 → ``verified=True`` 且 ``chunk_id`` 填充
2. 编造 snippet → ``verified=False``，答案不被拒绝（只观测不执法）
4. LoopTimeout / MaxIterationsExceeded → ``ErrorEvent.partial_evidence``
   非空且 ≤ 5 条，异常对象同样携带
"""

from __future__ import annotations

import json
import time
from typing import Any

import pytest

from bookscope.agent.errors import LoopTimeout, MaxIterationsExceeded
from bookscope.agent.tools.schemas import ChunkMatch


def _final_json_text(answer: str, citations: list[dict[str, Any]]) -> str:
    return json.dumps({"answer": answer, "citations": citations}, ensure_ascii=False)


_CHUNK_TEXT = "朱元璋出身贫寒，幼年做过放牛娃，后来入皇觉寺为僧。"


def _search_then_answer_responses(
    r2_response_factory, snippet: str
) -> list[Any]:
    """构造两轮响应：第一轮 search tool_call，第二轮带指定 snippet 的 final。"""
    return [
        r2_response_factory(
            tool_calls=[
                ("call_1", "search_chunks", json.dumps({"query": "朱元璋出身"})),
            ],
            finish_reason="tool_calls",
        ),
        r2_response_factory(
            content=_final_json_text(
                "朱元璋出身贫寒。",
                [{"chapter": 1, "snippet": snippet}],
            ),
            finish_reason="stop",
        ),
    ]


# ---------------------------------------------------------------------------
# 成功标准 1：真实 snippet → verified=True + chunk_id 填充
# ---------------------------------------------------------------------------


def test_loop_r2_citation_from_tool_output_is_verified(
    r2_response_factory,
    r2_fake_client,
    make_r2_loop,
    fake_search_backend,
):
    """snippet 取自 search 返回的原文 → 系统标 verified=True 并填 chunk_id。"""
    match = ChunkMatch(
        chunk_id="r0-chunk-1",
        chapter=1,
        text=_CHUNK_TEXT,
        relevance_score=1.0,
        contains_characters=[],
        source_version="r0",
    )
    client = r2_fake_client(
        _search_then_answer_responses(
            r2_response_factory, "幼年做过放牛娃，后来入皇觉寺为僧。"
        )
    )
    loop = make_r2_loop(client, search_backend=fake_search_backend([match]))

    result = loop.query("朱元璋出身如何？")

    assert len(result.citations) == 1
    cit = result.citations[0]
    assert cit["verified"] is True
    assert cit["chunk_id"] == "r0-chunk-1"
    assert cit["match_score"] == 1.0
    # 原有字段不动
    assert cit["chapter"] == 1


# ---------------------------------------------------------------------------
# 成功标准 2：编造 snippet → verified=False，答案不被拒绝
# ---------------------------------------------------------------------------


def test_loop_r2_fabricated_citation_marked_unverified_but_not_rejected(
    r2_response_factory,
    r2_fake_client,
    make_r2_loop,
    fake_search_backend,
):
    """编造的 snippet → verified=False / chunk_id=None；query 仍正常返回。"""
    match = ChunkMatch(
        chunk_id="r0-chunk-1",
        chapter=1,
        text=_CHUNK_TEXT,
        relevance_score=1.0,
        contains_characters=[],
        source_version="r0",
    )
    client = r2_fake_client(
        _search_then_answer_responses(
            r2_response_factory, "刘伯温夜观天象，断言金陵有王气，劝主公早定大计。"
        )
    )
    loop = make_r2_loop(client, search_backend=fake_search_backend([match]))

    result = loop.query("朱元璋出身如何？")

    # 首版只观测不执法：答案照常返回
    assert result.answer == "朱元璋出身贫寒。"
    assert result.trace.outcome == "success"
    cit = result.citations[0]
    assert cit["verified"] is False
    assert cit["chunk_id"] is None
    assert cit["match_score"] < 0.6


# ---------------------------------------------------------------------------
# get_chapter_range 的章节文本同样可作证据
# ---------------------------------------------------------------------------


def test_loop_r2_chapter_range_output_registered_as_evidence(
    r2_response_factory,
    r2_fake_client,
    make_r2_loop,
):
    """citation 引自 get_chapter_range 拉的章节原文 → 按 chapter-{N} 伪 id 命中。"""
    from bookscope.agent.tools.schemas import ChapterText
    from tests.agent.r2.conftest import _R2FakeChapterBackend

    chapter = ChapterText(
        chapter=3,
        title="鄱阳湖",
        full_text="陈友谅率六十万大军顺江而下，鄱阳湖一战定天下归属。",
        word_count=24,
        source_version="r0",
    )
    responses = [
        r2_response_factory(
            tool_calls=[
                (
                    "call_1",
                    "get_chapter_range",
                    json.dumps({"start_chapter": 3, "end_chapter": 3}),
                ),
            ],
            finish_reason="tool_calls",
        ),
        r2_response_factory(
            content=_final_json_text(
                "鄱阳湖之战是决定性战役。",
                [{"chapter": 3, "snippet": "鄱阳湖一战定天下归属"}],
            ),
            finish_reason="stop",
        ),
    ]
    client = r2_fake_client(responses)
    loop = make_r2_loop(client, chapter_backend=_R2FakeChapterBackend([chapter]))

    result = loop.query("鄱阳湖之战的意义？")

    cit = result.citations[0]
    assert cit["verified"] is True
    assert cit["chunk_id"] == "chapter-3"


# ---------------------------------------------------------------------------
# 成功标准 4：max_iterations / timeout → partial_evidence 非空 ≤ 5 条
# ---------------------------------------------------------------------------


def _many_chunks(n: int) -> list[ChunkMatch]:
    return [
        ChunkMatch(
            chunk_id=f"r0-chunk-{i}",
            chapter=i,
            text=f"第{i}章原文片段，内容足够长以供截断验证。" * 20,
            relevance_score=1.0,
            contains_characters=[],
            source_version="r0",
        )
        for i in range(1, n + 1)
    ]


def test_loop_r2_max_iterations_carries_partial_evidence(
    r2_response_factory,
    r2_fake_client,
    make_r2_loop,
    fake_search_backend,
):
    """max_iterations 中止时 ErrorEvent 与异常都带 ≤ 5 条 partial_evidence。"""
    events: list[Any] = []
    # 一轮 search 命中 7 条 chunk；max_iterations=1 → 派发完就中止
    responses = [
        r2_response_factory(
            tool_calls=[
                ("call_1", "search_chunks", json.dumps({"query": "Q"})),
            ],
            finish_reason="tool_calls",
        ),
    ]
    client = r2_fake_client(responses)
    loop = make_r2_loop(
        client,
        search_backend=fake_search_backend(_many_chunks(7)),
        max_iterations=1,
        on_event=events.append,
    )

    with pytest.raises(MaxIterationsExceeded) as exc_info:
        loop.query("Q")

    # 异常对象携带（API 层 504 响应用）
    pe = exc_info.value.partial_evidence
    assert 0 < len(pe) <= 5
    for item in pe:
        assert set(item) == {"chunk_id", "chapter", "snippet"}
        assert len(item["snippet"]) <= 200

    # ErrorEvent 同样携带（SSE 流用）
    error_events = [e for e in events if e.type == "error"]
    assert len(error_events) == 1
    assert error_events[0].error_type == "MaxIterationsExceeded"
    assert error_events[0].partial_evidence == pe


def test_loop_r2_timeout_carries_partial_evidence(
    r2_response_factory,
    r2_fake_client,
    make_r2_loop,
):
    """timeout 中止时已登记的 search 命中随 ErrorEvent / 异常带回。

    构造方式：search backend 故意 sleep 超过 timeout_seconds——第 1 轮
    tool 调用本身能跑完并登记证据，第 2 轮入口的超时检查触发 LoopTimeout。
    """
    events: list[Any] = []

    class _SlowSearchBackend:
        def retrieve(self, **kwargs: Any) -> list[ChunkMatch]:
            time.sleep(0.1)
            return _many_chunks(3)

    responses = [
        r2_response_factory(
            tool_calls=[
                ("call_1", "search_chunks", json.dumps({"query": "Q"})),
            ],
            finish_reason="tool_calls",
        ),
    ]
    client = r2_fake_client(responses)
    loop = make_r2_loop(
        client,
        search_backend=_SlowSearchBackend(),
        timeout_seconds=0.05,
        on_event=events.append,
    )

    with pytest.raises(LoopTimeout) as exc_info:
        loop.query("Q")

    pe = exc_info.value.partial_evidence
    assert 0 < len(pe) <= 5
    assert pe[0]["chunk_id"] == "r0-chunk-1"

    error_events = [e for e in events if e.type == "error"]
    assert len(error_events) == 1
    assert error_events[0].error_type == "LoopTimeout"
    assert error_events[0].partial_evidence == pe


def test_loop_r2_timeout_with_no_evidence_yields_empty_partial(
    r2_fake_client,
    make_r2_loop,
):
    """还没跑出任何工具结果就超时 → partial_evidence 为空列表（不炸）。"""
    client = r2_fake_client([])  # 不会被调用
    loop = make_r2_loop(client, timeout_seconds=-1.0)

    with pytest.raises(LoopTimeout) as exc_info:
        loop.query("Q")

    assert exc_info.value.partial_evidence == []
