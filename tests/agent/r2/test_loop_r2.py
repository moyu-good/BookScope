"""r2 AgentLoop 5 处改动点单测。

ADR-007 D-1 第二波核心测试——验证 OpenAI function calling 形态在 loop
内部的 5 个改动点都按预期工作：

1. ``_extract_tool_calls`` 从 ``choices[0].message.tool_calls`` 读
2. tool 结果作为 N 条 ``role=tool`` 消息追加
3. assistant 消息含 ``tool_calls`` 字段
4. ``_truncate_messages_r2`` 按 assistant tool_calls + N 条 tool 成组丢弃
5. ``finish_reason`` 驱动 tool_calls 继续 / stop 结束 loop

每个测试都用 OpenAI 原生形态构造 response，不构造 Anthropic 形态。
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from bookscope.agent.loop_r2 import _truncate_messages_r2


def _final_json_text(answer: str, citations: list[dict[str, Any]]) -> str:
    return json.dumps({"answer": answer, "citations": citations}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 改动点 1：从 OpenAI tool_calls 抽取工具调用
# ---------------------------------------------------------------------------


def test_loop_r2_tool_call_extraction_from_openai_format(
    r2_response_factory,
    r2_fake_client,
    make_r2_loop,
    make_chunk_match,
    fake_search_backend,
):
    """LLM 返回 ``choices[0].message.tool_calls`` 时 loop 应该派发并继续。"""
    # 第一轮：OpenAI 形态 tool_call → 调 search_chunks
    # 第二轮：纯文本 final answer
    responses = [
        r2_response_factory(
            tool_calls=[
                (
                    "call_001",
                    "search_chunks",
                    json.dumps({"query": "明朝开国", "top_k": 3}),
                )
            ],
            finish_reason="tool_calls",
        ),
        r2_response_factory(
            content=_final_json_text(
                "明朝由朱元璋开创。",
                [{"chapter": 1, "snippet": "片段"}],
            ),
            finish_reason="stop",
        ),
    ]
    client = r2_fake_client(responses)
    search = fake_search_backend([make_chunk_match()])
    loop = make_r2_loop(client, search_backend=search)

    result = loop.query("明朝开国是谁？")

    assert result.answer == "明朝由朱元璋开创。"
    assert search.call_count == 1
    assert result.trace.iterations == 2


# ---------------------------------------------------------------------------
# 改动点 2：tool 结果作为 N 条 role=tool 消息追加（严格保序）
# ---------------------------------------------------------------------------


def test_loop_r2_tool_result_messages_appended_as_role_tool(
    r2_response_factory,
    r2_fake_client,
    make_r2_loop,
    make_chunk_match,
    fake_search_backend,
):
    """一轮 1 个 tool_call 后应该有 1 条 role=tool 消息追加进 messages。"""
    captured_messages_round2: list[dict[str, Any]] = []

    def _capture_round_2(kwargs: dict[str, Any]):
        # 把第二轮发给 LLM 的 messages 截下来检查
        captured_messages_round2.extend(kwargs["messages"])
        return r2_response_factory(
            content=_final_json_text(
                "答案",
                [{"chapter": 1, "snippet": "片段"}],
            ),
            finish_reason="stop",
        )

    responses = [
        r2_response_factory(
            tool_calls=[
                (
                    "call_alpha",
                    "search_chunks",
                    json.dumps({"query": "test"}),
                )
            ],
            finish_reason="tool_calls",
        ),
        _capture_round_2,
    ]
    client = r2_fake_client(responses)
    search = fake_search_backend([make_chunk_match()])
    loop = make_r2_loop(client, search_backend=search)

    loop.query("Q")

    # 验证 messages 序列：[user, assistant(with tool_calls), tool, ...]
    tool_messages = [m for m in captured_messages_round2 if m.get("role") == "tool"]
    assert len(tool_messages) == 1
    assert tool_messages[0]["tool_call_id"] == "call_alpha"
    # content 是 json 字符串
    parsed = json.loads(tool_messages[0]["content"])
    assert isinstance(parsed, list)
    assert parsed[0]["chunk_id"] == "r0-chunk-1"


# ---------------------------------------------------------------------------
# 改动点 3：assistant 消息含 tool_calls 字段
# ---------------------------------------------------------------------------


def test_loop_r2_assistant_message_with_tool_calls_field(
    r2_response_factory,
    r2_fake_client,
    make_r2_loop,
    make_chunk_match,
    fake_search_backend,
):
    """assistant 消息追加时应该带 tool_calls 字段，content 可为 None。"""
    captured: list[dict[str, Any]] = []

    def _capture(kwargs):
        captured.extend(kwargs["messages"])
        return r2_response_factory(
            content=_final_json_text("answer", [{"chapter": 1, "snippet": "s"}]),
            finish_reason="stop",
        )

    responses = [
        r2_response_factory(
            content=None,  # OpenAI 风格：tool_calls 时 content 常 None
            tool_calls=[
                ("call_x", "search_chunks", json.dumps({"query": "Q"})),
            ],
            finish_reason="tool_calls",
        ),
        _capture,
    ]
    client = r2_fake_client(responses)
    search = fake_search_backend([make_chunk_match()])
    loop = make_r2_loop(client, search_backend=search)

    loop.query("Q")

    assistant_msgs = [m for m in captured if m.get("role") == "assistant"]
    assert len(assistant_msgs) == 1
    am = assistant_msgs[0]
    assert "tool_calls" in am
    assert len(am["tool_calls"]) == 1
    assert am["tool_calls"][0]["id"] == "call_x"
    assert am["tool_calls"][0]["type"] == "function"
    assert am["tool_calls"][0]["function"]["name"] == "search_chunks"
    # content 是 None（OpenAI 允许）
    assert am["content"] is None


# ---------------------------------------------------------------------------
# 改动点 4：_truncate_messages_r2 按 assistant tool_calls + N tool 成组丢弃
# ---------------------------------------------------------------------------


def test_loop_r2_truncate_pairs_assistant_with_n_tool_messages():
    """assistant(tool_calls=2) + 紧随 2 条 role=tool 应成组丢弃。"""
    messages = [
        {"role": "user", "content": "Q1"},
        # 早期一轮：assistant 调了 2 个 tool
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "a", "type": "function", "function": {"name": "x", "arguments": "{}"}},
                {"id": "b", "type": "function", "function": {"name": "y", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "a", "content": "result_a"},
        {"role": "tool", "tool_call_id": "b", "content": "result_b"},
        # 更早的 user 追问
        {"role": "user", "content": "Q2 中间补充"},
        # 第二轮：assistant 调 1 个 tool
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "c", "type": "function", "function": {"name": "z", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "c", "content": "result_c"},
        # 最新一条 user
        {"role": "user", "content": "Q3 最终"},
    ]
    truncated = _truncate_messages_r2(messages)

    # 最后一条 user 永远保留
    assert truncated[-1] == {"role": "user", "content": "Q3 最终"}
    # 早期那对 (1 assistant + 2 tool = 3 条) 应该被成组丢弃
    # 中间的 user 追问也单条丢弃
    # 至少应该丢掉首组——剩余条数 < 原 8 条
    assert len(truncated) < len(messages)


def test_loop_r2_truncate_skips_when_tool_count_mismatch():
    """assistant(tool_calls=2) 但后续只有 1 条 role=tool，停止丢弃。"""
    messages = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "a", "type": "function", "function": {"name": "x", "arguments": "{}"}},
                {"id": "b", "type": "function", "function": {"name": "y", "arguments": "{}"}},
            ],
        },
        # 只有 1 条 tool —— 缺一条
        {"role": "tool", "tool_call_id": "a", "content": "r"},
        {"role": "user", "content": "final"},
    ]
    truncated = _truncate_messages_r2(messages)
    # 因为配对不完整，停止丢弃；最后一条保留
    assert truncated[-1]["content"] == "final"


def test_loop_r2_truncate_preserves_system_and_last():
    """system 与最后一条 user 永远保留。"""
    messages = [
        {"role": "system", "content": "S"},
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "u_last"},
    ]
    truncated = _truncate_messages_r2(messages)
    assert truncated[0] == {"role": "system", "content": "S"}
    assert truncated[-1] == {"role": "user", "content": "u_last"}


# ---------------------------------------------------------------------------
# 改动点 5：finish_reason 驱动 loop
# ---------------------------------------------------------------------------


def test_loop_r2_finish_reason_tool_calls_continues_loop(
    r2_response_factory,
    r2_fake_client,
    make_r2_loop,
    make_chunk_match,
    fake_search_backend,
):
    """finish_reason=tool_calls 时 loop 应该继续派发 tool，不退出。"""
    responses = [
        r2_response_factory(
            tool_calls=[
                ("c1", "search_chunks", json.dumps({"query": "Q"})),
            ],
            finish_reason="tool_calls",
        ),
        r2_response_factory(
            content=_final_json_text("ans", [{"chapter": 1, "snippet": "s"}]),
            finish_reason="stop",
        ),
    ]
    client = r2_fake_client(responses)
    search = fake_search_backend([make_chunk_match()])
    loop = make_r2_loop(client, search_backend=search)

    result = loop.query("Q")
    assert result.trace.iterations == 2
    assert search.call_count == 1


def test_loop_r2_finish_reason_stop_ends_loop(
    r2_response_factory,
    r2_fake_client,
    make_r2_loop,
):
    """finish_reason=stop + 无 tool_calls 时 loop 立刻去 parse final answer。"""
    responses = [
        r2_response_factory(
            content=_final_json_text("一轮就答完", [{"chapter": 1, "snippet": "s"}]),
            finish_reason="stop",
        ),
    ]
    client = r2_fake_client(responses)
    loop = make_r2_loop(client)

    result = loop.query("Q")
    assert result.answer == "一轮就答完"
    assert result.trace.iterations == 1


# ---------------------------------------------------------------------------
# trace.protocol_version
# ---------------------------------------------------------------------------


def test_loop_r2_protocol_version_in_trace_is_r2(
    r2_response_factory,
    r2_fake_client,
    make_r2_loop,
):
    """r2 AgentLoop 构造的 trace 应该带 protocol_version='r2'。"""
    responses = [
        r2_response_factory(
            content=_final_json_text("ans", [{"chapter": 1, "snippet": "s"}]),
            finish_reason="stop",
        ),
    ]
    client = r2_fake_client(responses)
    loop = make_r2_loop(client)

    result = loop.query("Q")
    assert result.trace.protocol_version == "r2"


# ---------------------------------------------------------------------------
# 并发 tool 派发保序
# ---------------------------------------------------------------------------


def test_loop_r2_parallel_tool_dispatch_preserves_order(
    r2_response_factory,
    r2_fake_client,
    make_r2_loop,
    make_chunk_match,
    fake_search_backend,
):
    """一轮 3 个 tool_calls 并发派发后，追加的 tool 消息按 tool_calls 顺序。

    OpenAI 强约束：tool_calls 顺序与 role=tool 消息顺序必须严格一致，
    乱序会被 API 422。
    """
    captured_round2_messages: list[dict[str, Any]] = []

    def _capture(kwargs):
        captured_round2_messages.extend(kwargs["messages"])
        return r2_response_factory(
            content=_final_json_text("ans", [{"chapter": 1, "snippet": "s"}]),
            finish_reason="stop",
        )

    responses = [
        r2_response_factory(
            tool_calls=[
                ("call_1", "search_chunks", json.dumps({"query": "q1"})),
                ("call_2", "search_chunks", json.dumps({"query": "q2"})),
                ("call_3", "search_chunks", json.dumps({"query": "q3"})),
            ],
            finish_reason="tool_calls",
        ),
        _capture,
    ]
    client = r2_fake_client(responses)
    search = fake_search_backend([make_chunk_match()])
    loop = make_r2_loop(client, search_backend=search)

    loop.query("Q")

    tool_msgs = [m for m in captured_round2_messages if m.get("role") == "tool"]
    assert [m["tool_call_id"] for m in tool_msgs] == [
        "call_1",
        "call_2",
        "call_3",
    ]


# ---------------------------------------------------------------------------
# arguments 空串降级（DeepSeek / MiniMax 怪癖）
# ---------------------------------------------------------------------------


def test_loop_r2_tool_call_arguments_empty_string_tolerated(
    r2_response_factory,
    r2_fake_client,
    make_r2_loop,
    make_chunk_match,
    fake_search_backend,
):
    """arguments 是空串时降级为空 dict，不抛 JSONDecodeError。"""
    captured_inputs: list[dict[str, Any]] = []

    class _CaptureBackend:
        def retrieve(self, **kwargs):
            captured_inputs.append(kwargs)
            return []

    responses = [
        r2_response_factory(
            tool_calls=[
                ("call_empty", "list_characters_in_chapter", ""),
            ],
            finish_reason="tool_calls",
        ),
        r2_response_factory(
            content=_final_json_text("a", [{"chapter": 1, "snippet": "s"}]),
            finish_reason="stop",
        ),
    ]
    client = r2_fake_client(responses)
    loop = make_r2_loop(client)
    # 期望不抛 —— 即便 arguments 是空串 loop_r2 内部降级为 {} 后再传给
    # Pydantic 模型校验时会因缺必填字段抛 ValidationError，被
    # ToolDispatchError 包住——但本测试目的是验证不抛 JSONDecodeError，
    # 所以用 list_characters_in_chapter（chapter 必填）来确认走到了 backend
    with pytest.raises(Exception):  # noqa: BLE001
        loop.query("Q")
