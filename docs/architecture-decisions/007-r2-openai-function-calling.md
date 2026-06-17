# ADR-007：r2 切换 OpenAI function calling 为 AgentLoop 内部主格式

## Status

**已批准 · 2026-05-15 作者第三次明示签字 · Sprint 7 删 r1 授权**

- 代际：r1-agent-loop → r2 演化
- 起草：副管理
- 创建日期：2026-05-13
- 第一次口头批准：2026-05-13（"签名没有问题，都可以继续"）—— Sprint 4 第一波骨架落地
- 第二次明示签字：2026-05-14（"按你的建议来，签字一下，我都同意"）—— Sprint 6 切默认 r2 + Sprint 7 删 r1 全条件就绪
- 第三次明示签字：2026-05-15（"按你的建议继续，通过我的签名"）—— Sprint 7 启动授权 · 真执行等 audit 报告回来后按推荐节奏分步推
- 决策摘要：把 AgentLoop 内部消息形态从 Anthropic tool_use 切到 OpenAI function calling；AnthropicAdapter 反向翻译；新 provider 0 翻译成本；feature flag 双轨过渡
- Sprint 5 r1 vs r2 实验数据（commit `c847169`）：anshi r1 15.80 / r2 13.79（Δ -2.01 / 容忍带 ±5.07 不退化）；mingchao r1 17.67 / r2 17.80（Δ +0.13 / 容忍带 ±2.47 不退化）。**撤回条件不命中**，前置条件全部满足

## Context / 背景

r1 启动时（ADR-002 v1）作者熟 Anthropic 协议，AgentLoop 主体直接用了 Anthropic Messages API 的形态：`content` 是 block 数组，`stop_reason="tool_use"` + `{"type": "tool_use", "id": ..., "name": ..., "input": {...}}` block 是工具调用约定。这套结构在 `bookscope/agent/loop.py` 主循环里到处都是——`_extract_content_blocks` / `_block_type` / `tool_use_blocks` / `tool_use_id`、`_truncate_messages` 配对丢弃的"`tool_use` block + `tool_result` block"语义、`_dispatch_tools_parallel` 写回的 `{"type": "tool_result", "tool_use_id": ..., "content": ...}` block——全都假设 Anthropic 形态。

ADR-002 v2 把默认 provider 切到 DeepSeek，是因为开源学习项目要让国内学生跑得起。但 DeepSeek 用 OpenAI 兼容协议（`choices[0].message.tool_calls` 数组 + `function.name` / `function.arguments` JSON 字符串），跟 AgentLoop 内部形态不一样。当时为了不动 loop 主体和 128 条测试，ADR-003 选择让 `DeepSeekAdapter` 做双向翻译——请求方向把 Anthropic 形态翻成 OpenAI 形态喂给 SDK，响应方向把 OpenAI 形态翻回 Anthropic 形态给 loop 用。`AnthropicAdapter` 反而几乎是 passthrough。

ADR-003 已经在"未来演化"节明确写过：r2 应该把内部形态切到 OpenAI function calling，DeepSeekAdapter 退化成 passthrough，AnthropicAdapter 反向翻译。本 ADR 把这条路径从"已知技术债"升级为"r2 主线工作"。

后续 MiniMax 用 DeepSeek 兼容协议接入，复用 `DeepSeekAdapter`；OpenAI 兼容端点（GLM / Qwen / Kimi）也都直接复用同一 adapter。**国内主流 provider 全部走 OpenAI 兼容协议**，Anthropic tool_use 是少数派。

## Problem / 问题

让多数派去翻译成少数派的格式，是个倒置的工程选择，引出三个具体问题。

### 问题 1：翻译层成所有 provider 怪癖的兜底场

`DeepSeekAdapter` 现在 428 行——一半是双向翻译，一半是 provider 怪癖兜底。最典型的几个：

- `_strip_thinking_tags`（L62–69）：minimax-m2.x / deepseek-r1 / qwen-qwq / glm-zero 等 reasoning model 在 `content` 里 inline 返回 `<think>...</think>` 段。loop 不知道这事，因为 loop 只认 Anthropic 形态——adapter 在响应翻译时把 think 段抹掉
- `_translate_error` 里的 `_looks_like_content_filter` + `_CONTENT_FILTER_HINTS`（L399–425）：MiniMax HTTP 422 内容审查的若干提示词（`new_sensitive` / `1027` / `content_filter` 等）要在 adapter 里识别后翻译成 `ContentFiltered`，loop 才能重试
- 一些 provider 给 `arguments` 是空串而不是 `"{}"`、`finish_reason` 缺省、`usage` 字段缺失——L342–346 / L327 / L356–358 都是这类宽容降级

更深的问题在 `bookscope/agent/loop.py`：

- `_autofix_unescaped_quotes_in_all_string_values`（L1162）：astron-code 类模型 JSON 输出裸 ASCII `"`，要在 loop 层做状态机扫描修复
- `_autofix_stray_apostrophe_string_closer`（L1297）：模型用 `'` 收束 string value
- `_autofix_control_chars_in_strings`（L1234）：字符串内裸控制字符
- `_autofix_unescaped_answer_quotes`（L1319）：定向修 `answer` 字段的转义

这四个 autofix 在 reviewer.py（L29–32 / L243–266）也复用一遍。本质上都是 provider 怪癖兜底——但因为 loop 内部是 Anthropic 形态，怪癖修复也只能在 loop 里写，无法在协议层就近处理。

### 问题 2：新 provider 接入成本高

每加一个新 provider（GLM / Qwen / Kimi 等），即使它原生支持 OpenAI function calling，仍然要走 `DeepSeekAdapter` 这一层翻译——意思是：

- 请求方向：把 Anthropic tool spec（`input_schema`）翻译成 OpenAI function spec（`parameters`）
- 请求方向：把 message role 翻译（Anthropic `tool_result` block 拆成独立 `role="tool"` 消息，见 `_append_user_message` L225–263）
- 响应方向：把 `tool_calls` 数组拆成多个 `tool_use` block，JSON arguments 字符串解析成 dict（`_from_openai_response` L317–367）
- 响应方向：`finish_reason` 字符串映射到 `stop_reason` 字符串（`_FINISH_REASON_MAP` L310–314）
- reasoning 块要在响应里 strip（`_strip_thinking_tags`）

新 provider 没有自己的协议特异性，但仍要继承所有这些翻译开销——更糟的是，新 provider 的特有怪癖必须挤进同一个 adapter 文件里，或者复制一份 adapter。

### 问题 3：工程直觉不对

"以多数协议为基础"是惯例。OpenAI function calling 是国内外行业事实标准；Anthropic tool_use 只有 Claude 一家用。让多数派给少数派让路是逆流。ADR-003 自己在 L67 已经承认这条路径，只是当时不愿意付迁移代价。

## Decision / 决策

### D-1：切换 AgentLoop 内部主格式

把 `bookscope/agent/loop.py` 主循环里的 Anthropic tool_use 形态全部改成 OpenAI function calling 形态。具体改动点：

- `_extract_content_blocks` / `tool_use_blocks` 逻辑改成读 `choices[0].message.tool_calls`
- `_dispatch_tools_parallel` 写回的形态从 `{"type": "tool_result", "tool_use_id": ..., "content": ...}` block 改成独立的 `{"role": "tool", "tool_call_id": ..., "content": ...}` 消息
- assistant message 追加从 `{"role": "assistant", "content": [...blocks]}` 改成 `{"role": "assistant", "content": str_or_null, "tool_calls": [...]}`
- `_truncate_messages` 的配对扫描语义改成"assistant 含 tool_calls + 后续 role=tool 消息（可能 N 条）" 的成组丢弃
- `stop_reason` 的判断改读 `finish_reason`

### D-2：AnthropicAdapter 反向翻译

`bookscope/agent/adapters/anthropic.py` 当前 181 行的近 passthrough 实现要改写：

- 请求方向：把 OpenAI 形态的 messages / tools 翻译成 Anthropic 形态再喂给 SDK
- 响应方向：把 SDK 返回的 Message 对象翻译成 OpenAI 形态返回给 loop

工程量：翻译表跟 `DeepSeekAdapter` 现在做的反过来，路径完全已知。

### D-3：DeepSeekAdapter / OpenAI 兼容 adapter 退化成 passthrough

- 请求方向：directly forward 给 `openai` SDK
- 响应方向：把 `ChatCompletion` 对象转成 plain dict（字段名保留 OpenAI 原样）
- reasoning 块 strip、错误翻译、内容审核识别 **继续在 adapter 层做**——这些是 provider 怪癖，本来就该在 adapter 层处理；切换主格式之后这些代码留下来，但不再夹在双向翻译之间

### D-4：feature flag 双轨

环境变量 `BOOKSCOPE_AGENT_PROTOCOL=r1|r2`，默认 `r1`：

- `r1`：走当前 AgentLoop（Anthropic 主格式）+ 当前 adapter（DeepSeek 翻译 / Anthropic passthrough）
- `r2`：走新 AgentLoop（OpenAI 主格式）+ 新 adapter（DeepSeek passthrough / Anthropic 翻译）

代码组织：`bookscope/agent/loop.py` 不动，新增 `bookscope/agent/loop_r2.py`；adapters 用 `bookscope/agent/adapters/deepseek_r2.py` / `anthropic_r2.py` 并列；`bookscope/agent/__init__.py` 按 env 分派构造。

理由：

- 双轨期间允许真实跑对比数据，r2 不退化才能切默认
- r1 现有所有 batch 数据 / case-study 数据都依赖 r1 trace 结构里的 `tool_use` / `tool_result` 字段名，case-study 章节里的引文也按 r1 结构截取
- 切换风险全压在 r2 路径上，r1 用户不受影响

### D-5：trace 结构 versioned

`LoopTrace.tool_calls` 字段当前是宽松 `list[dict]`，没绑死字段名。新增 `LoopTrace.protocol_version: Literal["r1", "r2"]`，默认 `r1`。`tool_calls` 里每条记录的字段名按版本走（r1 用 `tool_use_id`，r2 用 `tool_call_id`）。case-study 与 batch 归档要在元数据头标注 `protocol_version`。

旧数据全部隐式 `r1`；脚本读取时若缺字段按 `r1` 处理，不破坏向后兼容。

## Consequences / 后果

### 好

- 新增 OpenAI 兼容 provider 0 翻译成本——直接复制 DeepSeekAdapter 改 endpoint / 鉴权
- `DeepSeekAdapter` 不再做协议翻译，只保留 reasoning strip + 错误翻译 + 内容审核识别，文件大小预期能砍掉 200 行
- loop 层不再写 provider 怪癖 autofix——这些下沉到 adapter 层就近处理（autofix 仍然需要，但归位）
- 跟行业事实标准对齐，后续 maintainer / 贡献者上手成本降一档

### 弊

- **r1 trace 结构断**：r2 trace 字段名跟 r1 不一样，所有读 trace 的脚本（包括 `docs/internal/case-study/` 里若干分析）都要按 `protocol_version` 分支处理
- **Anthropic 用户成本上升**：现在 AnthropicAdapter 近 passthrough、稳定；切到反向翻译之后，AnthropicAdapter 成为新的翻译层，可能引入新 bug，BYOK Claude Sonnet 用户首当其冲
- **case-study 历史数据不能直接跟 r2 比**：第 26 轮的 ablation / 第 33 轮的 v3.3 实验都是 r1 数据，r2 出来后只能纵向跟 r2 比；横跨代际比较要明确标注"r1 vs r2 协议差"是潜在变量
- **测试改造工程量**：r1 测试集（120+ 条）大部分跟 Anthropic 形态绑定，r2 要写并行测试集；双轨期间两套都跑
- **双轨复杂度**：env flag 分派、两套 loop / 两套 adapter 并存一段时间，新 contributor 容易混淆

### 撤回条件

任一条命中重开本 ADR：

- r2 在 anshi / mingchao 两本书 baseline std 范围内退化超 2 分（CLAUDE.md memory `feedback_baseline_variance_first.md`：单次跟单次比要先求 baseline std）
- Anthropic 反向翻译引入持续不稳，BYOK Claude 用户大量退化
- Anthropic 官方在 r2 落地前推出 OpenAI 兼容 endpoint（见 Open Questions 第 1 条）——若推出则 r2 价值降一档，但仍值得做（行业标准对齐 + 翻译层简化仍成立）

## Alternatives / 备选方案

### A-1：保持现状（Anthropic 主格式 + DeepSeek 翻译）

- 利：0 改造成本，r1 数据连续
- 弊：上面三个问题继续累积；新 provider 接入仍要继承翻译层；adapter 越长越脏
- 评：技术债持续吃利息。不接受

### A-2：第三协议（纯 JSON-RPC / 自定义中间态）

- 利：跟两家 provider 都解耦，理论最干净
- 弊：要写两个翻译层（OpenAI ↔ 自定义、Anthropic ↔ 自定义），工程量翻倍；自定义中间态本身是又一份私有协议，新 contributor 多一份学习成本
- 评：理论优雅但落地差。不接受

### A-3：用第三方 router（LiteLLM / OpenRouter 等）

- 利：router 自己处理翻译，BookScope 不写
- 弊：ADR-003 已明确驳回——多一层依赖；部分 router 服务部署境外，国内用户访问差；BYOK 模式跟 router 不天然兼容
- 评：不接受

### A-4：等 Anthropic Messages API v2 推 OpenAI 兼容端点

- 利：如果 Anthropic 自己出 OpenAI 兼容端点，整个翻译问题自然消失
- 弊：没有公开 roadmap；等 6 个月还是 18 个月不知道；同时 BookScope 现在已经被翻译层拖累
- 评：可以观望但不能等。不接受作为唯一方案，但作为 Open Questions 第 1 条记录

## Migration Plan / 迁移方案

### 时间表

| Sprint | 工作 | Deliverable |
|--------|------|-------------|
| Sprint 4 | r2 loop / adapter 落地、单测对齐 | `loop_r2.py` + `deepseek_r2.py` + `anthropic_r2.py` + 单测 120 条 |
| Sprint 5 | r1 vs r2 对照实验 | anshi / mingchao 各 3 次跑、std 报告、本 ADR 撤回条件评估 |
| Sprint 6 | r2 切默认 + r1 deprecated | env 默认改 `r2`，r1 标 deprecated 但保留 |
| Sprint 7 | r1 代码删除 | 删 `loop.py` / 原 adapter（保留 reasoning strip 等公用工具）|

每个 sprint 结尾在 `docs/internal/STATE.md` 记录是否继续推进。Sprint 5 若退化超阈值，stop 在 Sprint 6 前停下，本 ADR 进入撤回流程。

### 数据兼容

- `LoopTrace.protocol_version: Literal["r1", "r2"]` 默认 `r1`
- case-study 历史数据全部隐式 `r1`，新章节标注 `protocol_version: r2`
- 跨代际比较表必须显式标 `r1 vs r2` 列头，不允许默认混算
- batch 归档目录约定：`data/batches/r1/...` / `data/batches/r2/...` 分目录存放

### 测试改造范围

- `tests/agent/` 下涉及 `tool_use` / `tool_result` block 形态的单测全部要复制一份到 `tests/agent/r2/`
- `_truncate_messages` 的配对丢弃逻辑要重写测试（r2 是 "assistant tool_calls + N 条 role=tool 消息"）
- adapter 双向翻译路径在 r2 下大部分消失，DeepSeek 测试要新写 passthrough 单测；Anthropic 测试要新写双向翻译单测
- 集成测试 mock HTTP 层在 r2 下要 mock OpenAI 原生形态（不是当前 mock Anthropic 形态）

### 回归阈值

r2 vs r1 在 anshi / mingchao 上各 3 次跑求 std，r2 平均分 ≥ r1 平均分 - max(1.0, r1 std × 1.0) 不算退化。若 r1 std 本身大（如 1.5+），阈值跟着放宽——避免拿单次跑当 ground truth（memory `feedback_baseline_variance_first.md`）。

## Open Questions / 待定

1. **Anthropic 是否未来切到 OpenAI 兼容**：若 Anthropic 推出 OpenAI 兼容 endpoint，AnthropicAdapter 也可走 passthrough，本 ADR 的"反向翻译"代价归零。但目前无公开信号，不能等
2. **MiniMax / GLM / Qwen 在 OpenAI 兼容上的小差异**：MiniMax 的 `<think>` 块 / 内容审查 422 是已知怪癖；GLM / Qwen 接入后会不会有新怪癖未知。adapter 层仍需保留怪癖兜底层
3. **streaming 协议是否同步切换**：当前 streaming 在 SSE event 形态上跟 Anthropic 协议解耦（见 `bookscope/agent/events.py`），但实际 chunk 解析可能仍假设 Anthropic 形态。r2 落地时要审查 streaming 路径
4. **r2 是否同时升级 reviewer.py**：reviewer 现在也复用 loop 里的 autofix 函数（reviewer.py L29–32），r2 下这些 autofix 是否下沉到 adapter 层需要再判
5. **r1 deprecated 后保留多久**：Sprint 7 删 r1 代码，但 case-study 章节里的引文截取脚本可能还在读 r1 trace。要不要保留 r1 trace 读取工具到 r2 稳定 6 个月之后
6. **D-2 `tool_choice` 翻译表**（Sprint 4 第三波 BE 自查补）：D-2 当时没列 OpenAI `tool_choice` 4 种值（`"none"` / `"auto"` / `"required"` / `{"type":"function","function":{"name":...}}`）到 Anthropic 端的翻译表。anthropic_r2 反向翻译已做覆盖（commit `d236a05`），但 ADR 文本未补——下次 ADR 修订一并写进 D-2
7. **tools 入参约定**（Sprint 4 第三波 BE 自查补）：r2 内部用 OpenAI 嵌套形态 `{"type":"function","function":{...}}`，anthropic_r2 翻译要把 `function` 字段扁平化到顶层。这点在 D-2 文本里没明示职责划分（loop_r2 / anthropic_r2 哪一方做嵌套→扁平）
8. **空 content + 空 tool_calls 边界 SDK 校验**（Sprint 4 第三波 BE 自查补）：r2 内部允许 assistant message 同时空 content 与空 tool_calls（loop_r2 兜底 None），但实际 SDK 校验可能拒收。anthropic_r2 翻译时已加守护，但 deepseek_r2 / openai_r2 没显式测——批量跑时若挂在 SDK 拒收需补 mock 测试
9. **完整 stop_reason 集合 + provider 差异**（Sprint 4 第三波 BE 自查补）：OpenAI `finish_reason` 还有 `"length"` / `"content_filter"` / `"function_call"`（旧）/ `"tool_calls"` / `"stop"` 5 类；Anthropic 还有 `"pause_turn"` / `"refusal"` 等较新值。loop_r2 当前控制流改用 `tool_calls` 列表存在与否信号——不依赖 stop_reason，理论上 provider 加新值不破。但 D-2 翻译表 (`stop_reason → finish_reason`) 应当列全集

## References

- ADR-002 v1：r1 启动时为何选 Anthropic 形态
- ADR-002 v2：默认 provider 切 DeepSeek
- ADR-003：provider adapter 层 Protocol 契约（本 ADR 直接演进自其 L67 "未来演化"节）
- ADR-006：本地 ML 模型 API 化（不直接相关，作 ADR 格式参考）
- `bookscope/agent/loop.py`：1384 行，主循环对 Anthropic 形态的依赖点
- `bookscope/agent/models.py`：127 行，`LoopTrace` 字段（要加 `protocol_version`）
- `bookscope/agent/adapters/deepseek.py`：428 行，当前双向翻译实现 + 怪癖兜底
- `bookscope/agent/adapters/anthropic.py`：181 行，当前近 passthrough 实现
- memory `feedback_provider_agnostic_first.md`：第 31 轮 "provider 行为差异要 BookScope 兜底"
- memory `reference_minimax_capabilities.md`：MiniMax 怪癖清单
- memory `feedback_baseline_variance_first.md`：比较前先求 baseline std

## 作者签字

**2026-05-13 作者第一次口头批准**："签名没有问题，都可以继续"。Sprint 4 第一波 r2 骨架于同日落地（commit `1c74806`）；后续按 Migration Plan 时间表跨 4 sprint 推进。

**2026-05-14 作者第二次明示签字**："按你的建议来，签字一下，我都同意"。Sprint 5 r1 vs r2 实验数据齐全 + 撤回条件不命中 + ADR Open Questions 6-9 补齐之后，作者正式批准 Sprint 6 启动——env 默认 r2 + r1 标 deprecated。本 ADR 状态从草案进"已批准"。

**2026-05-15 作者第三次明示签字**："按你的建议继续，通过我的签名"。Sprint 6 r2 mock 测试套补齐（32 测试 / 663 全绿）+ fast_path r2 形态修复（commit `0f36fb2` 通识题 8-15x 加速器复活）+ ROADMAP Backlog B-1 / B-2 立条目后，作者授权 Sprint 7 启动。**执行前置条件**：本次签字时 Sprint 7 删 r1 影响面 audit（`docs/internal/audit/sprint-7-r1-removal-impact.md`）尚在跑中，未阅。作者授权基于"按你的建议继续"的副管理信任——真删 r1 代码要等 audit 报告回来 + 按报告推荐节奏分步推进（B-2 autofix 下沉 → B-1 Adapter.extract_final_text → 删 loop.py + r1 adapter），每步独立 commit + 零回归。如 audit 命中撤回条件，本签字暂停 Sprint 7，回 STATE 等作者复审。
