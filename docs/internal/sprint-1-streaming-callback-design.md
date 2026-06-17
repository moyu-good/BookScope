# Sprint 1 设计文档 · AgentLoop Streaming Callback Hook

**Sprint 1 BE deliverable** · 给 BookScope agent loop 加 callback 通知机制，让 SSE 端点能在 < 5 秒推首字到用户屏幕。

**作者**：planner agent（第 33 轮第七部分 Sprint 1 启动）
**实施者**：主 Claude（BE 角色）后续按本设计落地
**状态**：设计已批，未实施

---

## 1. LoopEvent 数据结构

新增文件 `bookscope/agent/events.py`。用 `dataclass(frozen=True)` + `Literal` 字面量做 discriminated union（保持纯标准库，不引入新依赖）。

```python
# bookscope/agent/events.py（实施时新建）
from dataclasses import dataclass
from typing import Any, Callable, Literal, Union

EventType = Literal[
    "iteration_start",
    "tool_use",
    "tool_result",
    "format_retry",
    "content_filter_retry",
    "final_answer",
    "error",
]

@dataclass(frozen=True)
class IterationStartEvent:
    type: Literal["iteration_start"] = "iteration_start"
    iteration: int = 0                 # 第几轮（1-based）
    elapsed_ms: int = 0

@dataclass(frozen=True)
class ToolUseEvent:
    tool_name: str
    tool_input: dict[str, Any]
    tool_use_id: str | None = None
    iteration: int = 0
    elapsed_ms: int = 0
    type: Literal["tool_use"] = "tool_use"

@dataclass(frozen=True)
class ToolResultEvent:
    tool_name: str
    output_summary: str                # _summarise_output() 已有，复用，避免泄全文
    status: Literal["ok", "error"] = "ok"
    attempt: int = 1                   # 第几次尝试（含原次）
    elapsed_ms: int = 0
    error_message: str | None = None
    type: Literal["tool_result"] = "tool_result"

@dataclass(frozen=True)
class FormatRetryEvent:
    retries_used: int                  # 触发后已用的重试次数
    reason: str                        # exc 的字符串（短）
    type: Literal["format_retry"] = "format_retry"

@dataclass(frozen=True)
class ContentFilterRetryEvent:
    retries_used: int
    type: Literal["content_filter_retry"] = "content_filter_retry"

@dataclass(frozen=True)
class FinalAnswerEvent:
    answer: str
    citations: list[dict]
    iterations: int
    duration_ms: int
    type: Literal["final_answer"] = "final_answer"

@dataclass(frozen=True)
class ErrorEvent:
    error_type: str                    # "MaxIterationsExceeded" / "LoopTimeout" / ...
    message: str
    duration_ms: int
    type: Literal["error"] = "error"

LoopEvent = Union[
    IterationStartEvent, ToolUseEvent, ToolResultEvent,
    FormatRetryEvent, ContentFilterRetryEvent,
    FinalAnswerEvent, ErrorEvent,
]

LoopCallback = Callable[[LoopEvent], None]
```

判别字段：`event.type` 是字面量字符串，调用方可 `match event.type` 或 `isinstance` 双向用。

## 2. AgentLoop `__init__` 接收 callback

`loop.py` 的 `__init__` 末尾 keyword-only 加一参，默认 `None`：

```python
on_event: LoopCallback | None = None,
```

存为 `self._on_event = on_event`。**默认行为零回归**——`on_event=None` 时全部跳过 emit。

新增私有方法 `_emit(event: LoopEvent) -> None`：

```python
def _emit(self, event: LoopEvent) -> None:
    if self._on_event is None:
        return
    try:
        self._on_event(event)
    except Exception:
        # 用户 callback 崩溃绝不污染 agent 主流程
        import logging
        logging.getLogger(__name__).exception(
            "on_event callback raised; suppressed to protect loop"
        )
```

## 3. 触发点（具体函数 / 时机）

| 事件 | 位置 | 触发时机 |
|------|------|---------|
| `IterationStartEvent` | `query()` 主 for 循环头 | 进入新一轮前（`_check_timeout` 之后、`_invoke_with_content_filter_retry` 之前） |
| `ContentFilterRetryEvent` | `_invoke_with_content_filter_retry()` | 每次 `ContentFiltered` 命中且未超上限时（`trace.content_filter_retries = attempts` 那行后） |
| `ToolUseEvent` | `query()` 内 `_dispatch_tool_with_retry` 调用之前 | 每个 `tool_use_block` 开始 dispatch 前。emit 时带 `iteration` |
| `ToolResultEvent` | `_dispatch_tool_with_retry()` 成功 / 失败两路 | 每次尝试结束（不只是最终结果）。复用现有 `trace.tool_calls.append` 字段 |
| `FormatRetryEvent` | `query()` `format_retries_used += 1` 后 | 每次格式重试触发时 |
| `FinalAnswerEvent` | `query()` 的 `return AgentQueryResult(...)` 之前 | 拿到合规 final answer，return 之前 |
| `ErrorEvent` | `query()` 三个 `except` 块 + `LLMFormatError` / `ContentFiltered` 重试耗尽 | 任何 outcome 非 success 时 |

**实现守则**：emit 在 trace 字段更新**之后**（保证 callback 看到的状态与 trace 一致）。`final_answer` emit 在 `trace.duration_ms` 写入后、return 前。

## 4. callback 异常处理

见第 2 节 `_emit`：try/except 包死，用 `logging.exception` 记录后吞掉。

理由：用户 callback 任何崩溃（SSE 连接断了、queue 满了、序列化炸了）都不能让 agent 主流程退出。SSE 端点的"客户端断连"是常态，agent 应继续把 query 跑完（结果至少能进 trace）。

不需要熔断 / 限流——一次 query 最多 20-30 个 event，量级小。

## 5. 单元测试设计

新增 `tests/agent/test_loop_callback.py`。复用现有 `tests/agent/test_loop.py` 的 fake client 装置。

| 测试 | 验证点 |
|------|--------|
| `test_no_callback_zero_regression` | 不传 `on_event`，跑现有 happy path，断言结果与 baseline 完全一致 |
| `test_iteration_start_emitted` | 传 callback 收集 events，断言 `iteration_start` 数量等于 `trace.iterations` |
| `test_tool_use_and_result_pair` | 每个 `tool_use` 必有对应 `tool_result`（按顺序）；`output_summary` 字段非空 |
| `test_final_answer_carries_citations` | happy path 跑完，最后一个事件是 `FinalAnswerEvent`，`citations` 与返回的 `AgentQueryResult.citations` 相等 |
| `test_callback_exception_suppressed` | callback 抛 `RuntimeError`，loop 仍正常 return；assert 用 `caplog` 检 "suppressed" 日志 |
| `test_format_retry_emitted` | fake client 第一次返回坏 JSON，第二次返回好的；断言出现 1 个 `FormatRetryEvent` |
| `test_content_filter_retry_emitted` | fake client 第一次抛 `ContentFiltered`，第二次正常；断言出现 1 个 `ContentFilterRetryEvent` |
| `test_max_iterations_emits_error` | 让 fake client 永远 return tool_use；断言收尾事件是 `ErrorEvent(error_type="MaxIterationsExceeded")` |
| `test_tool_dispatch_error_emits_error` | backend 永远抛异常；断言 `ToolResultEvent` status=error 出现 N 次 + 最后一个事件 `ErrorEvent(error_type="ToolDispatchError")` |

覆盖率目标：`events.py` 100% / `loop.py` 新增分支 100%。

## 6. 跟 LoopTrace 的关系

互补不重复。trace 是终态全量快照（query 跑完后才完整），event 是过程增量流（实时可读）。

落地约束：
- 每个 `_emit` 调用的 event payload **从 trace 已写入的字段读**（顺序：先 trace 写、再 emit），保证两者一致
- `ToolResultEvent` 字段（`tool_name` / `output_summary` / `status` / `elapsed_ms` / `attempt`）与 `trace.tool_calls[-1]` 一一对应
- 不在 trace 里加新字段。trace 保持现有契约不破

## 7. SSE 端点上层调用形态（Sprint 1 BE 第三 deliverable 实施时参考）

```python
# bookscope/api/routes_query.py（未来文件）
import asyncio, json
from dataclasses import asdict
from fastapi.responses import StreamingResponse

async def stream_query(question: str):
    queue: asyncio.Queue = asyncio.Queue(maxsize=200)
    loop_ref = asyncio.get_running_loop()

    def on_event(event):
        # AgentLoop 跑在 worker thread，要 thread-safe 入队
        loop_ref.call_soon_threadsafe(queue.put_nowait, event)

    agent = AgentLoop(..., on_event=on_event)
    task = asyncio.create_task(asyncio.to_thread(agent.query, question))

    async def gen():
        while True:
            done, _ = await asyncio.wait(
                {task, asyncio.create_task(queue.get())},
                return_when=asyncio.FIRST_COMPLETED,
            )
            # 把 event dataclass 转 SSE：
            #   event: <type>\n
            #   data: <json>\n\n

    return StreamingResponse(gen(), media_type="text/event-stream")
```

**关键设计点**：

1. AgentLoop 是同步（`time.monotonic()` + 阻塞 LLM 调用），FastAPI handler 必须 `asyncio.to_thread` 把它丢 worker thread；callback 要用 `call_soon_threadsafe` 跨线程入队
2. SSE 事件 `event:` 字段直接用 `event.type`（discriminated union 字面量）；`data:` 字段用 `json.dumps(asdict(event), ensure_ascii=False)`
3. 客户端断连时 `queue.put_nowait` 可能堆积——给 queue 设 `maxsize=200`，满了就丢老的
4. **首字延迟来源**：`iteration_start` 事件在第一次 LLM 调用之前就 emit 了——用户看到 "正在思考..." 几乎是 0 延迟；真正首个 `tool_use` 大约在 1-3 秒后到达（LLM 决策时间）

---

## 实施顺序

1. 先建 `bookscope/agent/events.py`（数据类，无依赖）
2. 改 `loop.py` 加 `on_event` 参数 + `_emit` 方法（不加触发点，确保零回归）
3. 跑现有 412 测试 → 必须全绿
4. 按表逐个加触发点，每加一个就跑相关测试
5. 写新测试文件 `tests/agent/test_loop_callback.py`
6. 整体 pytest + ruff 收尾

**反向兼容**：所有变化对 `on_event=None` 的旧 caller 透明；`AgentQueryResult` / `LoopTrace` schema 不动；现有异常类型不动。
