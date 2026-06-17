"""r2 端到端最小冒烟。

env ``BOOKSCOPE_AGENT_PROTOCOL=r2`` + mock deepseek client + 三 backend
跑完整 1-question agent loop，断言：

- ``_select_agent_loop_class`` 返回 r2 ``AgentLoop``
- trace.protocol_version == "r2"
- 1 个 tool_call → 1 个 tool_result → final answer 走通
- answer + citations 字段正确
"""

from __future__ import annotations

import json

import pytest

from bookscope.agent import _select_agent_loop_class
from bookscope.agent.loop_r2 import AgentLoop as R2AgentLoop


def test_r2_loop_smoke_with_mock_deepseek(
    monkeypatch: pytest.MonkeyPatch,
    r2_response_factory,
    r2_fake_client,
    make_r2_loop,
    make_chunk_match,
    fake_search_backend,
):
    """env=r2 时整条路径用 r2 AgentLoop 跑出 success result。"""
    monkeypatch.setenv("BOOKSCOPE_AGENT_PROTOCOL", "r2")

    # 1. env 路由正确
    assert _select_agent_loop_class() is R2AgentLoop

    # 2. 构造 r2 loop + mock 响应序列
    responses = [
        # 第 1 轮：tool_call 一个 search_chunks
        r2_response_factory(
            tool_calls=[
                (
                    "call_smoke",
                    "search_chunks",
                    json.dumps({"query": "smoke test", "top_k": 3}),
                )
            ],
            finish_reason="tool_calls",
        ),
        # 第 2 轮：final answer
        r2_response_factory(
            content=json.dumps(
                {
                    "answer": "明朝由朱元璋于 1368 年开创",
                    "citations": [{"chapter": 1, "snippet": "朱元璋立国"}],
                },
                ensure_ascii=False,
            ),
            finish_reason="stop",
        ),
    ]
    client = r2_fake_client(responses)
    search = fake_search_backend([make_chunk_match(chapter=1, snippet="朱元璋立国")])
    loop = make_r2_loop(client, search_backend=search)

    # 3. 跑 query
    result = loop.query("明朝是谁建立的？")

    # 4. 全部断言
    assert "朱元璋" in result.answer
    assert len(result.citations) == 1
    assert result.citations[0]["chapter"] == 1
    assert result.trace.protocol_version == "r2"
    assert result.trace.iterations == 2
    assert search.call_count == 1
    # tool_calls 留 trace
    assert len(result.trace.tool_calls) == 1
    assert result.trace.tool_calls[0]["tool_name"] == "search_chunks"
    assert result.trace.tool_calls[0]["status"] == "ok"
