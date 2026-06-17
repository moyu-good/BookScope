# r2 streaming SSE 兼容性审查

**审查日期**：2026-05-13
**审查范围**：ADR-007 Open Q-3 —— r2 落地时 streaming 路径是否假设 Anthropic 形态
**结论**：r2 streaming 与 r1 完全兼容，**无需改造** BE / FE 代码
**审查人**：BE（副管理）

---

## 审查的文件

| 文件 | 角色 | 关键行 |
|------|------|--------|
| `bookscope/agent/events.py` | LoopEvent dataclass 定义（8 类事件）| L18-117 |
| `bookscope/agent/loop.py` | r1 AgentLoop emit 点 | L55-56 / L486-617（`_dispatch_tools_parallel`）|
| `bookscope/agent/loop_r2.py` | r2 AgentLoop emit 点 | L58-67 / L490-629（`_dispatch_tools_parallel`）|
| `bookscope/api/routes/agent.py` | SSE 端点 `/api/agent/ask/stream` | L165-302 / `_format_sse` L305-313 |
| `web/src/App.tsx` | FE SSE 消费 | L43-86（LoopEventFE 类型）/ L286-330（事件处理 switch）|

---

## 字段 / 结构假设清单

### 1. `LoopEvent` dataclass 字段命名

| 字段 | 出现在 | 假设 | 评估 |
|------|--------|------|------|
| `ToolUseEvent.tool_use_id` | `events.py` L42, FE L50 | 命名来自 Anthropic 协议（`tool_use_id`），但实际类型是 `str \| None`，**对值不挑** | **r2-compatible**：r2 在 `loop_r2.py` L525 把 OpenAI 的 `tool_call_id` 透传进这同一个字段；FE 也只读不解析格式 |
| `ToolUseEvent.tool_input` | `events.py` L40, FE L49 | `dict[str, Any]`——r1 来自 Anthropic block.input，r2 来自 OpenAI function.arguments JSON 解析 | **r2-compatible**：r2 在 L514-519 已经 `json.loads` 并降级，给同一字段同一形态 |
| `ToolResultEvent.*` | `events.py` L48-55 | 字段全是协议无关（`tool_name` / `output_summary` / `status` / `attempt`）| **r2-compatible** |
| 其他 6 类事件 | `events.py` 全文 | `iteration_start` / `format_retry` / `content_filter_retry` / `final_answer` / `error` / `review` 字段全部协议无关 | **r2-compatible** |

### 2. SSE 端点

| 假设 | 评估 |
|------|------|
| `routes/agent.py` L300-302 用 `asdict(event)` 直接序列化任意 LoopEvent | **r2-compatible**：dataclass 序列化与协议无关 |
| `_format_sse` 用 `event.type` 字面量当 SSE event 名 | **r2-compatible**：r1/r2 都 emit 同一套 type literal |
| 端点 L242-249（fallback AgentLoop）现在已经过任务 1 改造，用 `_select_agent_loop_class()` | **r2-compatible**：r2 AgentLoop 构造签名跟 r1 一致 |

### 3. r1 / r2 AgentLoop emit 行为对比

| 事件 | r1 emit 点 | r2 emit 点 | 差异 |
|------|------------|------------|------|
| `IterationStartEvent` | `loop.py` 主循环开头 | `loop_r2.py` L249 | 无 |
| `ToolUseEvent` | `loop.py` L510，`tool_use_id` 填 Anthropic block.id | `loop_r2.py` L522，`tool_use_id` 填 OpenAI tool_call.id | 字段命名同名，**值的语义都是"本次工具调用的 provider 侧 id"**——FE 不解析格式 |
| `ToolResultEvent` | `loop.py` L593 / L617 | `loop_r2.py` L597 / L621 | 无 |
| `FormatRetryEvent` / `ContentFilterRetryEvent` / `FinalAnswerEvent` / `ErrorEvent` | r1 多处 | r2 多处 | 无 |

### 4. FE 消费假设（`App.tsx` L43-86 / L286-330）

| 假设 | 评估 |
|------|------|
| `LoopEventFE.tool_use.tool_use_id: string \| null` | **r2-compatible**：r2 透传的 `tool_call_id` 是 string，能直接放进 string 槽 |
| FE 不会解析 `tool_use_id` 的格式（不区分 `toolu_xxx` 还是 `call_xxx`），只用来在 UI 上做 idempotent 匹配 | **r2-compatible**——L300-330 的 switch 逻辑确认 |
| FE 的 `tool_result` 找最近一条同名 + running 状态来匹配，**不靠 tool_use_id 关联**（见 L287 注释）| **r2-compatible**：FE 关联策略本身就跟 id 解耦，r2 切换毫无影响 |

---

## 改造决策

**结论**：r2 streaming 路径无需任何代码改造。三大原因：

1. **events.py 的 dataclass 字段早就协议无关**——字段命名虽然带 Anthropic 色彩（`tool_use_id`），但类型签名只要求 string，r2 直接透传 OpenAI `tool_call_id` 进去就行
2. **r2 loop 已经在 emit 时做了字段填充对齐**（`loop_r2.py` L522-529 把 `tool_call_id` 装进 `tool_use_id` 槽）——这是 Sprint 4 第二波 commit `46bae86` 写代码时已经预留的接口兼容性
3. **FE 不解析 id 的内容格式**，匹配逻辑用"最近一条同名 + running"做关联（`App.tsx` L287 显式说明）——切换协议对 FE 透明

唯一名义上的"非对称"：events.py 字段叫 `tool_use_id` 而 r2 协议侧叫 `tool_call_id`。命名上略有违和，但**改字段名会破坏向后兼容**（trace 序列化 / FE 类型 / 测试快照都依赖此名），代价远大于收益。

### 选择不做的改造

| 改造选项 | 利 | 弊 | 决策 |
|----------|-----|-----|------|
| 把 `ToolUseEvent.tool_use_id` 字段加 alias 叫 `tool_call_id` | 命名对齐 r2 | dataclass 不支持 alias；用 property 会破坏 `asdict` 序列化；增加 FE 双字段处理 | 推迟 |
| 在 r2 emit 时同时填 `tool_use_id` 和某个新字段 | 命名澄清 | 字段重复无新信息；trace 体积 +1 字段 × N 调用 | 推迟 |
| events.py 引入 v2 dataclass | 长期清晰 | r1 deprecated 后再统一改名风险更小（与 ADR-007 Migration Plan Sprint 7 节奏匹配）| 推迟到 Sprint 7 |

---

## 测试覆盖建议

新增 1 个断言测试（任务 2 落地），证明 r2 路径事件流跟 r1 形态一致：

- 文件：`tests/agent/r2/test_streaming_r2.py`
- 用例：`test_loop_r2_emit_event_types_match_r1_schema`
- 断言：r2 loop 跑一次 mock query 后，`on_event` 收到的事件全部能用 `asdict` 序列化、`type` 字段值落在 8 类字面量内、`ToolUseEvent.tool_use_id` 是 string（即便 r2 实际填的是 OpenAI tool_call.id）

不需要更深的端到端 SSE 测试——`tests/api/test_agent_ask.py::test_agent_ask_stream_*` 系列已经覆盖 SSE 端点编码 / 分帧；任务 1 又新加了 `test_protocol_routing.py` 覆盖 r2 路由。

---

## References

- ADR-007 D-1 / D-5（r2 主格式 + trace versioned）
- `docs/internal/sprint-1-streaming-callback-design.md`（callback hook 三原则）
- commit `46bae86`（loop_r2.py 落地，emit 已对齐）
- commit `1c74806`（`_select_agent_loop_class()` 骨架）
