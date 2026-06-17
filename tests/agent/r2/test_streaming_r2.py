"""r2 streaming 兼容性断言测试（ADR-007 Open Q-3）。

落地依据：``docs/internal/audit/streaming-r2-compatibility.md``——审查结论为 r2
streaming 与 r1 形态完全兼容，无需任何代码改造。本测试给出**回归护栏**：
将来任何人改 r2 emit 或 events.py 字段时，本测试会捕捉到与 r1 形态的
意外漂移。

覆盖断言：

1. r2 loop 跑一次 tool_use → final_answer 流程，emit 的事件 type 全部
   落在 8 类字面量内（与 r1 同集合）
2. ``ToolUseEvent.tool_use_id`` 是 string——r2 实际填的是 OpenAI 的
   ``tool_call_id``，类型与 r1 一致让 FE 透明
3. 所有 emit 的事件都能用 ``asdict`` 成功序列化（SSE 端点编码前提）
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from bookscope.agent.events import (
    FinalAnswerEvent,
    IterationStartEvent,
    LoopEvent,
    ToolResultEvent,
    ToolUseEvent,
)

_R1_COMPATIBLE_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "route_decision",
        "iteration_start",
        "tool_use",
        "tool_result",
        "format_retry",
        "content_filter_retry",
        "final_answer",
        "review",
        "error",
    }
)


def _final_json_text(answer: str, citations: list[dict[str, Any]]) -> str:
    return json.dumps({"answer": answer, "citations": citations}, ensure_ascii=False)


def test_loop_r2_emits_events_with_r1_compatible_type_literals(
    r2_response_factory,
    r2_fake_client,
    make_r2_loop,
    make_chunk_match,
    fake_search_backend,
) -> None:
    """r2 emit 的事件 type 必须全部在 r1 已有 8 类字面量内。

    回归护栏：避免有人改 r2 时给 events.py 加新字段或改字面量，导致
    FE / SSE 序列化出现未识别 event 名。
    """
    captured: list[LoopEvent] = []

    def _on_event(event: LoopEvent) -> None:
        captured.append(event)

    responses = [
        r2_response_factory(
            tool_calls=[
                (
                    "call_zzz_001",
                    "search_chunks",
                    json.dumps({"query": "开国", "top_k": 3}),
                )
            ],
            finish_reason="tool_calls",
        ),
        r2_response_factory(
            content=_final_json_text(
                "明朝由朱元璋开国。",
                [{"chapter": 1, "snippet": "片段"}],
            ),
            finish_reason="stop",
        ),
    ]
    client = r2_fake_client(responses)
    search = fake_search_backend([make_chunk_match()])
    loop = make_r2_loop(client, search_backend=search)
    loop._on_event = _on_event  # type: ignore[attr-defined]

    result = loop.query("明朝开国是谁？")

    assert result.answer == "明朝由朱元璋开国。"
    assert captured, "r2 loop 应当 emit 至少一个事件"
    for event in captured:
        assert event.type in _R1_COMPATIBLE_EVENT_TYPES, (
            f"r2 emit 出现未知 event type={event.type!r}，"
            f"与 r1 字面量集合 {_R1_COMPATIBLE_EVENT_TYPES} 偏离"
        )


def test_loop_r2_tool_use_event_carries_string_tool_use_id(
    r2_response_factory,
    r2_fake_client,
    make_r2_loop,
    make_chunk_match,
    fake_search_backend,
) -> None:
    """``ToolUseEvent.tool_use_id`` 字段必须是 string。

    r2 实际填的是 OpenAI ``tool_call_id``（如 ``call_xxx``），但走的是
    r1 同名字段——FE / SSE 形态完全一致。本断言保证 r2 emit 不漏掉 id
    或填成 None / int。
    """
    captured: list[LoopEvent] = []
    expected_tool_call_id = "call_streaming_compat_001"

    def _on_event(event: LoopEvent) -> None:
        captured.append(event)

    responses = [
        r2_response_factory(
            tool_calls=[
                (
                    expected_tool_call_id,
                    "search_chunks",
                    json.dumps({"query": "明朝", "top_k": 3}),
                )
            ],
            finish_reason="tool_calls",
        ),
        r2_response_factory(
            content=_final_json_text(
                "答。",
                [{"chapter": 1, "snippet": "片段"}],
            ),
            finish_reason="stop",
        ),
    ]
    client = r2_fake_client(responses)
    search = fake_search_backend([make_chunk_match()])
    loop = make_r2_loop(client, search_backend=search)
    loop._on_event = _on_event  # type: ignore[attr-defined]

    loop.query("?")

    tool_use_events = [e for e in captured if isinstance(e, ToolUseEvent)]
    assert len(tool_use_events) == 1, "应当 emit 唯一一个 ToolUseEvent"
    tu_event = tool_use_events[0]
    assert isinstance(tu_event.tool_use_id, str), (
        f"ToolUseEvent.tool_use_id 应当是 string；实际 {type(tu_event.tool_use_id)}"
    )
    assert tu_event.tool_use_id == expected_tool_call_id, (
        "r2 应该把 OpenAI tool_call.id 透传进 ToolUseEvent.tool_use_id"
    )


def test_loop_r2_all_emitted_events_are_asdict_serializable(
    r2_response_factory,
    r2_fake_client,
    make_r2_loop,
    make_chunk_match,
    fake_search_backend,
) -> None:
    """SSE 端点用 ``asdict(event)`` 序列化每帧；r2 emit 的事件必须全部能过。

    这是 SSE 编码（``routes/agent.py::_format_sse``）的前提条件。
    """
    captured: list[LoopEvent] = []

    def _on_event(event: LoopEvent) -> None:
        captured.append(event)

    responses = [
        r2_response_factory(
            tool_calls=[
                ("call_a", "search_chunks", json.dumps({"query": "Q", "top_k": 3}))
            ],
            finish_reason="tool_calls",
        ),
        r2_response_factory(
            content=_final_json_text(
                "答。",
                [{"chapter": 1, "snippet": "片段"}],
            ),
            finish_reason="stop",
        ),
    ]
    client = r2_fake_client(responses)
    search = fake_search_backend([make_chunk_match()])
    loop = make_r2_loop(client, search_backend=search)
    loop._on_event = _on_event  # type: ignore[attr-defined]

    loop.query("?")

    # 至少应当含 IterationStart / ToolUse / ToolResult / FinalAnswer
    type_classes_seen = {type(e) for e in captured}
    for required_cls in (
        IterationStartEvent,
        ToolUseEvent,
        ToolResultEvent,
        FinalAnswerEvent,
    ):
        assert required_cls in type_classes_seen, (
            f"r2 streaming 缺失关键事件类型：{required_cls.__name__}"
        )

    # 每个事件都应当能被 asdict 转 dict，能 JSON 序列化（SSE 编码必经路径）
    for event in captured:
        payload = asdict(event)
        assert isinstance(payload, dict)
        # 不要求 ensure_ascii；与 _format_sse 一致让中文通过
        json.dumps(payload, ensure_ascii=False)
