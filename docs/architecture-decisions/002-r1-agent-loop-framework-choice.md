# ADR-002：r1 agent loop 的技术实现选型

## Status

**已批准**（作者口头批准，2026-04-20）。本版为第 2 版，因作者补充"LLM 国内优先"硬偏好重写。

- 代际：r1-agent-loop
- 作者：moyu-good
- 创建日期：2026-04-20
- 最后更新：2026-04-20

## Revision History

- **v1（2026-04-20 上午）**：决策 Claude Sonnet 4.6 原生 tool use + 自建轻量 loop；默认模型锁定为 `claude-sonnet-4-6`。
- **v2（2026-04-20 下午，当前版本）**：作者补充不变量"LLM provider 国内优先"，原 v1 的"锁定 Anthropic"决策与 NORTH_STAR 直接冲突，驳回作废。本版把 Decision 改写为"DeepSeek function calling 首选 + Anthropic 备选 + provider-agnostic adapter 层"。AgentLoop 主循环算法（message loop、tool dispatch、citation 强制、重试、trace）**保持不动**，变化只发生在 client 注入层与默认模型名。详细的 adapter 层设计由 ADR-003 承接。

## Context / 背景

r1 代际的核心体验是"和书对话"：用户提问后，系统通过 agent loop 动态决定调用哪些 tool（来自 ADR-001 定义的 `search_chunks` / `get_chapter_range` / `list_characters_in_chapter`），汇总证据，再由 LLM 综合成带原文引用的答案。典型一次提问触发 2-3 次 tool 调用，少量跨章节综合题会扩展到 4-5 次。loop 实现必须处理中间状态管理、tool 调用错误回滚、超时中断、citation 追踪等一整套工程问题，不是"一次 LLM 调用"就能完事的轻量工作。

BookScope 在 NORTH_STAR 里已明确的 provider 相关不变量：

- **LLM provider 国内优先**：首选 DeepSeek、GLM、Qwen、Kimi 等国内公开 LLM；Anthropic / OpenAI / Google 为备选。
- **所有 LLM 调用必须 provider-agnostic**：用 duck-typed client 或 Protocol 抽象，禁止硬编码任一家 SDK；默认实现必须先接国内 adapter。
- **BYOK 原则**：用户自带 API key，禁止在产品里嵌入任何 hosted LLM 密钥。
- **禁止 GPU 依赖**：Web 产品必须 CPU 可跑，所有推理走 provider API。

此外，中文长篇叙事（《明朝那些事儿》、网络小说）在国内模型上的中文理解与长上下文表现通常至少追平境外模型，在古汉语 / 文言 / 称谓体系上往往更优；叠加地缘稳定性与国内用户拿本地 API key 的便利，国内优先是务实选择而非政治姿态。

选型的主要关切按优先级排序为：**稳定性 > 开发速度 > 依赖体量 > 地缘风险**。BookScope 的硬性边界：Python 3.11+ 与 FastAPI 后端，成本不设红线（允许在需要时上 DeepSeek-R1 / Claude Opus 这类顶配），所有推理路径必须可被结构化日志完整捕获，任何框架的"黑盒魔法"都会放大 24/7 自主迭代场景下的排障成本。

本 ADR 定死 agent loop 的 provider 选型与抽象路径；Protocol 契约与 adapter 具体形态由配套的 ADR-003 详细规定。

## Decision / 决策

**选择（方案 B，默认国内 + 境外备选）：**

- **默认 provider**：DeepSeek function calling（`deepseek-chat` 为日常默认，`deepseek-r1` 作为需要深度推理时的可选升级）。
- **备选 provider**：Anthropic Claude Sonnet 4.6 / Opus 4.7，在 BYOK 场景下供用户显式切换。
- **抽象层**：定义 `LLMClient` Protocol 由 ADR-003 详细规定；AgentLoop 只依赖 Protocol，不依赖任何具体 SDK。至少两个 adapter 首发：`DeepSeekAdapter`、`AnthropicAdapter`。
- **AgentLoop 主循环代码保持不动**：已实现的 message loop、tool dispatch、citation 强制、失败重试、LoopTrace 结构全部复用；provider 差异完全吸收在 adapter 层，loop 本体零 churn。

### 论证

**其一，DeepSeek 在 2026 年已具备作为 BookScope 默认 provider 的全部条件。** function calling 自 2024 年以来经过几轮迭代已稳定，兼容 OpenAI function calling 语义；`deepseek-chat` 与 `deepseek-r1` 都支持多轮 tool use 与结构化输出；API 稳定性与中文长文本理解能力适合书籍问答这种每轮 2-5 次 tool call、总 token 不过分庞大的场景；`deepseek-r1` 开放权重，未来若作者想本地复现实验结果不存在封闭授权阻力。对 BookScope 这种"基于原文证据给出带 citation 的答复"的任务，DeepSeek 的能力边界完全够用。

**其二，保留 Anthropic 备选是务实而非妥协。** 一部分早期 BYOK 用户手里只有 Claude API key；另一些极长上下文诉求（例如一次把超过百万字的多卷本塞进单轮 prompt）在 Claude 1M context 的可用性上短期仍有边际优势。保留 `AnthropicAdapter` 作为并列首发 adapter，让 BYOK 用户真实有选择空间，也让对比评估（本月要做的 r0/r1/微信读书/ChatGPT/Claude 直通的横评）能直接在同一套 loop 代码里跑。

**其三，为什么不维持 v1 的"锁定 Anthropic"。** 直接违反 NORTH_STAR 不变量"LLM provider 国内优先"与"provider-agnostic 抽象"；使 BookScope 在地缘层面强依赖单家境外供应商；与 BYOK 原则在用户体感层冲突（国内用户拿 Claude key 远不如拿 DeepSeek key 顺手）；在中文书籍场景上也没有证据表明 Claude 能力超出 DeepSeek 足够多以值得承担上述成本。v1 决策作废。

**其四，为什么不用锁定 DeepSeek 的方案 A。** 作者在方案选择时明确选了 B 而非 A。方案 B 通过 adapter 层花很小的额外维护量换到了评估自由度与 BYOK 用户的真实选项，避免把 BookScope 从"锁定境外一家"翻转到"锁定国内一家"——后者同样违背 provider-agnostic 精神。

**其五，为什么 AgentLoop 主循环不重写。** 现有 loop 已实现 message loop、tool dispatch、tool 失败重试、format 重试、超时、LoopTrace 结构；对 client 的依赖从一开始就是 duck-typed（`_MessagesClientLike` Protocol，只要求 `.messages.create(...)`），这正是 provider-agnostic 抽象的雏形。128 条测试全绿。把已经 provider-agnostic 的内核再写一遍，既没收益又放大回归风险。

**其六，为什么走 adapter 层而不是 switch-case 嵌入 loop。** adapter 层让各家 provider 的演化节奏相互解耦：DeepSeek 明天若调整 function calling 语义，只需改 `DeepSeekAdapter`，AgentLoop 本体零变动。新增 GLM / Qwen / Kimi 时也只需新增一个 adapter，不打开 loop 核心代码。这是最低 churn、最易回归保护的扩展点设计。

**其七，为什么首选 DeepSeek 而不是 GLM / Qwen / Kimi。** 四家均为国内首选候选，但综合评估 DeepSeek 胜出：function calling 成熟度最高、API 稳定性与 OpenAI 兼容层最干净、`deepseek-r1` 权重开放给未来本地验证留余地、价格档位适中。其余三家未被排除——ADR-003 已把它们列为后续 adapter 候选，按需补全即可。

## Decision 实现要点

以下 14 条是 loop 与 provider 集成层必须满足的硬约束，替代 v1 对应章节（删除 Anthropic 独家字样，新增 adapter 层相关条款）。

1. **模块位置**：AgentLoop 保持在 `bookscope/agent/loop.py`。adapter 新建在 `bookscope/agent/adapters/`（目录由 ADR-003 规定）。loop 本体不再持有任何 provider 特定代码路径。
2. **核心类签名**：`AgentLoop(client, tools, max_iterations=8, ...)`。`client` 参数类型为 `LLMClient` Protocol（ADR-003 定义），不标注任何具体 SDK 类型；构造参数注入 client、tool 清单、上限轮次等，便于测试替换 mock。
3. **每轮迭代数据流**：把当前 `messages` 交给 `client.messages_create(...)` → 解析返回的 `tool_use` blocks → 通过 tool dispatcher 分发到具体 tool backend → 把 tool 结果包装为 `tool_result` block 追加到下一轮 `messages`，直至 LLM 返回 `stop_reason == "end_turn"` 或达上限。流程不受 provider 切换影响。
4. **Citation 字段强制要求**：最终答案必须输出结构化字段 `citations: list[ChunkRef]`（每条至少含 `chapter: int` + `snippet: str`）。缺失或格式错误时拒绝该答案并重试一次；再次失败直接抛 `LLMFormatError`。该约束在 loop 层实现，与 provider 无关。
5. **失败重试策略**：单 tool 调用失败最多重试 2 次（含原调用共 3 次），采用指数退避；LLM 返回格式错误重试 1 次；超 `max_iterations` 立刻返回 `MaxIterationsExceeded` 并附已有中间结果，不做隐式延长。
6. **状态可观察**：每轮迭代产生结构化 `LoopTrace` 记录（tool 名、输入摘要、输出摘要、token 用量、耗时、stop_reason），写入 `docs/internal/experiments/<实验 id>/trace-<timestamp>.jsonl`。Trace 文件只追加、可 diff，便于 24/7 自主实验时做回溯分析。
7. **并发边界**：v1 loop 为单用户单 session 单实例，不做 agent 级并发；后续若需多用户扩展再引入队列与隔离。
8. **超时控制**：单次 loop 总时长硬上限 90 秒（含所有 tool 调用与 LLM 往返）。超过直接终止，抛 `LoopTimeout`。
9. **错误类型分层**：沿用 v1 已定义的 `ToolDispatchError` / `LLMFormatError` / `MaxIterationsExceeded` / `LoopTimeout`；ADR-003 在此之上追加 `ProviderError` / `ProviderUnavailable` / `RateLimited` / `ContextLimitExceeded` 供 adapter 层抛出，loop 在遇到这些类型时按 `ToolDispatchError` 的语义做重试决策。
10. **模型选择**：**默认模型改为 `deepseek-chat`**，通过 `AgentLoop(model=...)` 参数覆盖。可在 session 级切换到 `deepseek-r1`（深度推理）或 `claude-sonnet-4-6` / `claude-opus-4-7`（境外备选）。**明确禁用 Haiku / 小尺寸 DeepSeek / GLM-Flash 等弱推理档位**——深度问答收敛质量不达标。
11. **AgentLoop 依赖 LLMClient Protocol 而非具体 SDK**：类型标注统一使用 ADR-003 定义的 `LLMClient` Protocol；禁止在 loop.py 里 import 任何 provider SDK（`anthropic` / `openai` / `zhipuai` / `dashscope` 等都不得出现）。
12. **adapter 层职责**：把 provider 特定 API / 格式转换为 AgentLoop 内部统一形态。当前内部形态为 Anthropic tool_use block 风格（v1 遗留），`DeepSeekAdapter` 负责 OpenAI function calling ↔ Anthropic tool_use 的双向转换；`AnthropicAdapter` 接近 passthrough。详细转换规范见 ADR-003。
13. **Prompt 版本化**：所有系统提示词与格式模板保存在 `bookscope/agent/prompts/` 下（例如 `loop_system_prompt_v1.md`、`citation_format_v1.md`）。严禁在代码里硬编码长 prompt，版本号与 ADR / 实验结果关联。
14. **技术债显式标注**：当前 AgentLoop 内部仍用 Anthropic tool_use block 形态（v1 遗留），`DeepSeekAdapter` 做 OpenAI function calling ↔ Anthropic tool_use 的双向转换。中期（r2 或下一次架构扫描）应把内部形态重构为 OpenAI function calling（业界事实标准），让 Anthropic adapter 做反向转换。该项作为代码内 TODO 与 ADR-003 里"未来演化路径"共同记录，避免遗忘。

## Consequences / 后果

**变好的一面：**

- 符合 NORTH_STAR 不变量"LLM 国内优先"与"provider-agnostic 抽象"，决策与北极星对齐。
- BYOK 用户真实拥有国内 / 境外双路可选，不被任一家 provider 绑架。
- 地缘稳定性显著改善：国内优先让主链路不依赖单家境外供应商。
- adapter 层天然为未来加 GLM / Qwen / Kimi 铺路；新增一家仅新增一个 adapter，不触 loop 核心。
- 同一份 AgentLoop 代码即可跑"r1-DeepSeek vs r1-Claude"对比实验，横评成本接近零。

**要付出的代价：**

- 需要维护 adapter 层。虽然每个 adapter 代码量小，但两套 adapter 代表两套单元测试与集成测试需要常备。
- `DeepSeekAdapter` 内部做 OpenAI function calling ↔ Anthropic tool_use 格式双向转换，是 v1 遗留的短期技术债；未来重构内部形态时需要一次性迁移。
- DeepSeek SDK 生态相较 Anthropic Python SDK 略年轻，早期开发若踩到 provider 侧 bug，调试成本可能略高。项目接受该代价作为国内优先的合理对价。

## Alternatives Considered / 替代方案

- **v1 原方案：锁定 Anthropic Sonnet 4.6 + 自建 loop**。能力强、SDK 成熟，但直接违反 NORTH_STAR 不变量"LLM 国内优先"；地缘风险与 BYOK 易用性问题明显。驳回，v1 作废。
- **方案 A：锁定 DeepSeek，不保留境外 adapter**。更简单，但作者选了方案 B；且锁定单家国内 provider 与 provider-agnostic 抽象的精神仍有冲突，会丢失横评能力。驳回。
- **锁定 GLM-4.5 为默认**。中文能力与 DeepSeek 各有所长，但 function calling 成熟度与 OpenAI 兼容层略逊 DeepSeek，做默认不如后者。未来作为 ADR-003 里 `GLMAdapter` 并入，仍是一等公民候选。
- **锁定 Qwen3-235B-A22B 为默认**。开源权重强，长上下文档位丰富，但 API 稳定性历史上相对波动；作为 ADR-003 中 `QwenAdapter` 的后续补齐候选更合适。
- **LangGraph**。state machine 抽象对"一问→若干 tool→一答"是过度设计；引入 langchain 生态大量非必要依赖，违背"依赖体量要小"。v1 已驳回，维持驳回。
- **LlamaIndex Agent Runner**。RAG 流水线友好，但 agent 部分是附属能力，tool 错误可观测性差。v1 已驳回，维持驳回。
- **CrewAI**。多 agent 协作导向与 BookScope 当前单 agent 场景错位，框架成熟度与原生 API 不在同一层级。v1 已驳回，维持驳回。
- **Anthropic Agent SDK**。官方出品但仍在快速迭代，API 稳定性与可调试性弱于 Messages API 直连；且只覆盖一家 provider，不解决 adapter 层需求。v1 已驳回，维持驳回。
- **Microsoft Autogen**。多 agent 对话范式与当前场景错位，依赖体量偏大。v1 已驳回，维持驳回。

## 落地路径

配合 ADR-001（tool 定义）与 ADR-003（adapter 层）一起推进，三份 ADR 互为配套。

1. 按 ADR-003 新建 `bookscope/agent/adapters/` 目录与 `LLMClient` Protocol 文件，统一 client 契约。
2. 实现 `DeepSeekAdapter`（首选）：走 OpenAI 兼容接口连 `https://api.deepseek.com/v1`，做 OpenAI function calling ↔ Anthropic tool_use 双向转换。
3. 实现 `AnthropicAdapter`（备选）：基于 anthropic SDK，内部形态接近 passthrough。
4. 更新 `bookscope/agent/loop.py`：默认模型常量由 `"claude-sonnet-4-6"` 改为 `"deepseek-chat"`；`_MessagesClientLike` 替换为 ADR-003 的 `LLMClient` Protocol；docstring 中"provider-agnostic"表述显式化。
5. 为两个 adapter 分别补单元测试（不调真 API，用响应夹具驱动 format 转换）；为 loop 与 adapter 组合补集成测试。
6. FastAPI 集成：新建 router（如 `bookscope/api/routers/agent.py`），暴露 `POST /api/agent/{session_id}/ask`；默认注入 `DeepSeekAdapter`，支持 session 级切换到 `AnthropicAdapter`。
7. 首个里程碑：对 "test 明朝那些事儿.epub" 提出 3 个典型问题（事实查询 / 角色关系 / 跨章节综合），同时用 DeepSeek 与 Claude 各跑一遍，对比引用精度与回答深度。
8. 后续扩展：按需补 `GLMAdapter` / `QwenAdapter` / `KimiAdapter`，每家仅新增文件，不触 loop 核心。
9. 中期技术债消除：当 r2 或下一次架构扫描启动时，把 AgentLoop 内部形态从 Anthropic tool_use 切换为 OpenAI function calling，让 `AnthropicAdapter` 做反向转换，`DeepSeekAdapter` 变为 passthrough，去除 v1 遗留的双向转换负担。

---

**批准记录**：

- **已批准**（作者口头，2026-04-20，方案 B）
- 口头记录：作者确认"b"（选项 B：默认国内 + 境外备选）
- 上一版 v1 决策已作废，本 v2 替代
- 进入实施阶段
