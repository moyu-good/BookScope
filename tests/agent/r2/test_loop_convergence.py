"""WP5 loop 收敛测试（2026-06-10）：空转检测 + 剩时强制综合.

守护两条自救机制——循环不再只能傻跑到 timeout：

1. 空转检测：连续 2 轮 search_chunks 查同一处 → 注入"停止检索、立即
   综合"提示，每 query 至多一次（`trace.spin_nudges`）
2. 剩时强制综合：剩余时间 < FORCED_SYNTHESIS_REMAINING_SECONDS → 注入
   "立即给 final answer"提示，而非等超时硬切（`trace.forced_synthesis`）

设计稿：`docs/internal/design/WP5-loop-convergence.md`
"""

from __future__ import annotations

import json
from typing import Any

from bookscope.agent import loop_r2


def _final_json_text(answer: str, citations: list[dict[str, Any]]) -> str:
    return json.dumps({"answer": answer, "citations": citations}, ensure_ascii=False)


def _search_call(call_id: str, query: str) -> tuple[str, str, str]:
    return (call_id, "search_chunks", json.dumps({"query": query}))


_FINAL = _final_json_text("综合答案", [{"chapter": 1, "snippet": "原文片段"}])


# ---------------------------------------------------------------------------
# 空转检测
# ---------------------------------------------------------------------------


class TestSpinDetection:
    def test_two_rounds_same_query_injects_nudge(
        self, r2_response_factory, r2_fake_client, make_r2_loop
    ):
        """连续两轮查同一 query → 第二轮后注入空转提示，spin_nudges=1。"""
        client = r2_fake_client(
            [
                r2_response_factory(tool_calls=[_search_call("c1", "朱元璋的性格")]),
                r2_response_factory(tool_calls=[_search_call("c2", "朱元璋的性格")]),
                r2_response_factory(content=_FINAL),
            ]
        )
        loop = make_r2_loop(client)
        result = loop.query("朱元璋这个人物写得立体吗？")

        assert result.trace.spin_nudges == 1
        # nudge 文本进了最后一轮发给模型的消息流
        assert any(
            m.get("content") == loop_r2.SPIN_NUDGE_MESSAGE
            for m in client.last_kwargs["messages"]
        )

    def test_distinct_queries_no_nudge(
        self, r2_response_factory, r2_fake_client, make_r2_loop
    ):
        """每轮查不同 query（正常推进）→ 不注入空转提示。"""
        client = r2_fake_client(
            [
                r2_response_factory(tool_calls=[_search_call("c1", "朱元璋的性格")]),
                r2_response_factory(tool_calls=[_search_call("c2", "李善长的结局")]),
                r2_response_factory(content=_FINAL),
            ]
        )
        loop = make_r2_loop(client)
        result = loop.query("这本书的人物塑造如何？")

        assert result.trace.spin_nudges == 0

    def test_nudge_injected_at_most_once(
        self, r2_response_factory, r2_fake_client, make_r2_loop
    ):
        """三轮以上查同一 query → 只注入一次，不累加。"""
        client = r2_fake_client(
            [
                r2_response_factory(tool_calls=[_search_call("c1", "同一个问题")]),
                r2_response_factory(tool_calls=[_search_call("c2", "同一个问题")]),
                r2_response_factory(tool_calls=[_search_call("c3", "同一个问题")]),
                r2_response_factory(content=_FINAL),
            ]
        )
        loop = make_r2_loop(client)
        result = loop.query("反复查同一处会怎样？")

        assert result.trace.spin_nudges == 1


# ---------------------------------------------------------------------------
# 剩时强制综合
# ---------------------------------------------------------------------------


class TestForcedSynthesis:
    def test_low_remaining_time_injects_synthesis(
        self, r2_response_factory, r2_fake_client, make_r2_loop
    ):
        """timeout 预算低于强制综合阈值 → 第一轮即注入综合提示。"""
        client = r2_fake_client([r2_response_factory(content=_FINAL)])
        # timeout 20s < FORCED_SYNTHESIS_REMAINING_SECONDS(30)，从第一轮起剩时不足
        loop = make_r2_loop(
            client,
            timeout_seconds=loop_r2.FORCED_SYNTHESIS_REMAINING_SECONDS - 10,
        )
        result = loop.query("时间快用完时还能答吗？")

        assert result.trace.forced_synthesis is True
        assert any(
            m.get("content") == loop_r2.FORCED_SYNTHESIS_MESSAGE
            for m in client.last_kwargs["messages"]
        )

    def test_ample_time_no_forced_synthesis(
        self, r2_response_factory, r2_fake_client, make_r2_loop
    ):
        """时间预算充裕 → 不注入强制综合提示。"""
        client = r2_fake_client([r2_response_factory(content=_FINAL)])
        loop = make_r2_loop(client, timeout_seconds=600.0)
        result = loop.query("时间够用时正常作答")

        assert result.trace.forced_synthesis is False
