# ADR-003：LLM provider adapter 层 —— Protocol 契约与 adapter 清单

## Status

**已批准**（作者口头，2026-04-20，方案 B 衍生）

- 代际：r1-agent-loop
- 作者：moyu-good
- 创建日期：2026-04-20
- 最后更新：2026-04-20

## Context / 背景

NORTH_STAR 明确了两条与本 ADR 直接相关的不变量："LLM provider 国内优先"与"所有 LLM 调用必须 provider-agnostic"。ADR-002 v2 在选型层面决定首选 DeepSeek、备选 Anthropic，但把"怎么抽象"留给本 ADR 统一规定，避免 AgentLoop 与 provider 绑死。

adapter 层的职责可归结为一句话：**把各 provider 特定的 API / 请求格式 / 响应形态，转换成 AgentLoop 内部统一的形态，让 loop 本体对 provider 完全无感**。

当前 AgentLoop 内部形态是 Anthropic tool_use block 风格（v1 遗留自 ADR-002 v1，直接使用了 Anthropic Messages API 的 `content blocks + stop_reason + tool_use/tool_result` 结构）。本 ADR 不重写内部形态——该项作为技术债显式记录，留给 r2 或下一次架构扫描处理；本版 adapter 在此形态之上收敛。

adapter 层还承担另一职责：把 provider 侧的错误（认证失败、rate limit、context 溢出等）翻译为 loop 层可识别的语义错误分层，避免每加一家 provider 就要动 loop 的错误处理分支。

## Decision

### LLMClient Protocol

定义一个最小 Protocol，AgentLoop 仅依赖该 Protocol，不依赖任何具体 SDK。

```python
from typing import Any, Protocol


class LLMClient(Protocol):
    """Provider-agnostic LLM client。

    AgentLoop 只依赖此 Protocol，不依赖任何具体 SDK。
    所有具体 provider 通过 adapter 实现本接口。
    """

    def messages_create(
        self,
        *,
        model: str,
        system: str,
        tools: list[dict],
        messages: list[dict],
        max_tokens: int,
    ) -> dict:
        """同步调用。返回 Anthropic 风格的 response dict（当前内部形态）。

        返回形态：
        {
          "stop_reason": "tool_use" | "end_turn" | "max_tokens",
          "content": [
            {"type": "text", "text": "..."} 或
            {"type": "tool_use", "id": "...", "name": "...", "input": {...}}
          ],
          "usage": {"input_tokens": N, "output_tokens": M}
        }

        不同 provider 的响应在 adapter 内部转换为上述统一形态。
        """
        ...
```

**为什么当前选 Anthropic 风格作为内部形态**：ADR-002 v1 基于 Anthropic Messages API 实现了 AgentLoop，`content blocks` 结构在表达"多个 tool_use 并行返回 + 每个 block 独立携带 id 与 input"时简洁且已被 128 条测试覆盖。若此刻切换到 OpenAI function calling 作为内部形态，要改 loop.py 与整套测试，属于在没有真实收益的情况下的高风险 churn。

**未来演化**：建议 r2 或下一次架构扫描时，把内部形态切换为 OpenAI function calling —— 它已是业界事实标准，多数国内 provider（DeepSeek、Kimi、Qwen-OpenAI 兼容端点、GLM-OpenAI 兼容端点）都原生支持。切换后 `AnthropicAdapter` 做反向转换，`DeepSeekAdapter` 变为 passthrough。本 ADR 把该演化路径作为已知技术债显式记录。

### Adapter 清单

首发两个 adapter，列为三类候选状态以明确接下来的增量路径。

| Adapter | 状态 | 默认模型 | SDK 依赖 | 用途 |
| --- | --- | --- | --- | --- |
| `DeepSeekAdapter` | v0.1 首发 | `deepseek-chat` | `openai`（DeepSeek OpenAI 兼容接口） | **默认 provider** |
| `AnthropicAdapter` | v0.1 首发 | `claude-sonnet-4-6` | `anthropic` | BYOK 下用户可显式切换 |
| `GLMAdapter` | 未实现 | `glm-4.5` | 智谱 SDK 或 OpenAI 兼容端点 | v0.2+ 候选 |
| `QwenAdapter` | 未实现 | `qwen3-235b-a22b` | DashScope SDK 或 OpenAI 兼容端点 | v0.2+ 候选 |
| `KimiAdapter` | 未实现 | `moonshot-v1-auto` | Kimi OpenAI 兼容接口 | v0.2+ 候选 |

**各 adapter 实现要点：**

- **DeepSeekAdapter**：内部用 `openai` SDK 连 DeepSeek endpoint `https://api.deepseek.com/v1`；function calling 遵循 OpenAI 标准；**关键**：adapter 负责把内部 Anthropic tool_use 形态双向转换为 OpenAI function calling 形态（请求方向：tools schema 转换 + tool_result 消息重写；响应方向：`choices[0].message.tool_calls` 转 `content` blocks）。
- **AnthropicAdapter**：内部用 `anthropic` SDK；几乎 passthrough（内部形态本身就是 Anthropic 风格）；仅做极少字段对齐（例如统一 `usage` 字段命名、错误类型翻译）。
- **GLMAdapter / QwenAdapter / KimiAdapter**（后续补齐）：三家均提供 OpenAI 兼容端点，可复用 `DeepSeekAdapter` 的大部分转换逻辑。建议把 `DeepSeekAdapter` 的 format 转换抽象为 `OpenAICompatibleAdapter` 基类，后续三家继承该基类仅覆写 endpoint、模型名、鉴权细节。

### 错误类型分层

在 `bookscope/agent/errors.py`（已存在，由 ADR-002 v1 建立）追加 provider 层错误，与 loop 层 `AgentError` 子类并列：

```python
class ProviderError(AgentError):
    """Provider 层通用错误基类。

    adapter 内部捕获 provider 侧原生异常（openai.APIError、
    anthropic.APIError 等）后，翻译为本基类或其子类抛出。
    loop 层只需识别 ProviderError 家族即可做通用重试 / 降级决策。
    """


class ProviderUnavailable(ProviderError):
    """Provider API 不可达或认证失败（5xx、401、403、DNS 失败等）。"""


class RateLimited(ProviderError):
    """Provider 返回 429 rate limit。adapter 可附带 retry_after。"""


class ContextLimitExceeded(ProviderError):
    """请求 token 数超过 provider 的 context limit。

    提示上层调用者收缩 messages / tools schema / max_tokens。
    """
```

loop 层对 `ProviderError` 家族的处理：`ProviderUnavailable` 与 `RateLimited` 按指数退避重试（复用现有的 tool retry 机制），`ContextLimitExceeded` 直接向上冒泡，由调用方（FastAPI router）决定是否给用户返回"问题过长，请收缩范围"的提示。

### Format 转换规范（Anthropic ↔ OpenAI）

该规范是 `DeepSeekAdapter` 实现的核心，也是后续任何 OpenAI 兼容 adapter 的共享资产。

**OpenAI → Anthropic（响应方向，adapter 接收 provider 响应后转内部形态）：**

- `choices[0].message.tool_calls[*]` → Anthropic `content` 里的 `{"type": "tool_use", "id": <tool_call_id>, "name": <function.name>, "input": <json.loads(function.arguments)>}` blocks。
- `choices[0].message.content`（非空时）→ Anthropic `content` 里的 `{"type": "text", "text": <content>}` block。若同时存在 text 与 tool_calls，保留两种 block（Anthropic 允许一次响应里 text + tool_use 共存）。
- `choices[0].finish_reason == "tool_calls"` → Anthropic `stop_reason == "tool_use"`。
- `choices[0].finish_reason == "stop"` → Anthropic `stop_reason == "end_turn"`。
- `choices[0].finish_reason == "length"` → Anthropic `stop_reason == "max_tokens"`。
- `usage.prompt_tokens` → Anthropic `usage.input_tokens`；`usage.completion_tokens` → `usage.output_tokens`。

**Anthropic → OpenAI（请求方向，adapter 把内部形态转为 provider 请求）：**

- Anthropic `tools: [{"name", "description", "input_schema"}]` → OpenAI `tools: [{"type": "function", "function": {"name", "description", "parameters": <input_schema>}}]`。
- Anthropic `messages[*].content` 含 `{"type": "tool_result", "tool_use_id": <id>, "content": <str>}` block → OpenAI 需要把该条转为独立的 `{"role": "tool", "tool_call_id": <id>, "content": <str>}` 消息；若原 message 还含其它 block，则拆成多条 OpenAI message。
- Anthropic `messages[*].content` 含 `{"type": "tool_use", ...}` block（出现在上一轮 assistant message 里）→ OpenAI `{"role": "assistant", "tool_calls": [{"id": <id>, "type": "function", "function": {"name": <name>, "arguments": <json.dumps(input)>}}]}`。
- Anthropic `system: <str>` → OpenAI `messages[0]` 追加 `{"role": "system", "content": <str>}`（注意位置：OpenAI 是把 system 作为 messages 的第一条）。
- Anthropic `max_tokens` → OpenAI `max_tokens`（语义一致，直接传）。

两张转换表是 `DeepSeekAdapter` 必须实现并测试覆盖的全部转换路径；新增 OpenAI 兼容 adapter 可直接复用。

## Consequences / 后果

**变好的一面：**

- AgentLoop 对 provider 完全无感，未来替换 provider 零主循环改动。
- adapter 层作为单一抽象点，让各 provider 的演化节奏彼此解耦。
- 新增 provider 只写一个 adapter 文件，不改 loop 核心代码，也不改已有 adapter。
- 错误分类清晰：loop 层识别 `ProviderError` 家族做通用策略，adapter 层对 provider 原生异常做语义翻译，职责边界干净。
- 对 BYOK 场景友好：session 注入不同 adapter 即可在国内 / 境外 provider 之间切换。

**要付出的代价：**

- 内部形态当前绑定 Anthropic 风格是 v1 遗留技术债；`DeepSeekAdapter` 作为默认 provider 反而要做更多格式转换。中期需要一次有计划的重构。
- 两套首发 adapter = 两套单元测试 + 至少一套组合集成测试。维护面比"只写一个 adapter"稍大。
- Format 转换逻辑中 tool_result 的拆分（一条 Anthropic message 里多个 tool_result block 需要拆成多条 OpenAI message）是已知的易错点，单元测试必须覆盖。

## Alternatives Considered / 替代方案

- **不做 adapter，在 AgentLoop 里直接 if-else 处理各 provider**。耦合差、loop 代码随 provider 数量膨胀、每加一家都触动核心测试集。驳回。
- **内部形态直接切 OpenAI function calling**。长期方向合理，但当前切换意味着重写 loop.py 与全部 128 条测试，属于无真实收益的高风险 churn。本 ADR 把该路径作为未来演化路径记录，当前不执行。
- **引入第三方 provider router（OpenRouter、LiteLLM、LangChain LLMProvider 等）**。多一层依赖；部分 router 服务本身部署在境外，国内用户访问不便；且封装粒度与 BookScope 的需求错配。违背"依赖体量要小"与"国内优先"精神。驳回。
- **用 Pydantic 强约束 Protocol 的 `messages` / `tools` 结构**。Protocol 层过度约束会让 adapter 内部做更多冗余验证。当前选择 `list[dict]` 宽松签名，让结构约束由 Pydantic schema（tool input）与 loop 层解析逻辑承担。保留未来收紧的可能。

## 落地路径

与 ADR-002 v2 的落地路径对齐、互为补充。

1. 新建目录 `bookscope/agent/adapters/`，内含 `__init__.py`、`base.py`（Protocol 与错误类型）、`deepseek.py`、`anthropic.py`。
2. 在 `bookscope/agent/errors.py` 追加 `ProviderError` / `ProviderUnavailable` / `RateLimited` / `ContextLimitExceeded`。
3. 实现 `DeepSeekAdapter`：OpenAI 兼容端点 + 完整双向 format 转换 + provider 错误翻译。
4. 实现 `AnthropicAdapter`：near-passthrough + provider 错误翻译。
5. 为两个 adapter 分别写单元测试（使用固定响应夹具，不调真 API）；每家 adapter 的双向 format 转换路径必须全覆盖。
6. 更新 `AgentLoop` 的 client 类型标注从 `_MessagesClientLike` 改为 `LLMClient`，默认模型常量由 `"claude-sonnet-4-6"` 改为 `"deepseek-chat"`。
7. 组合集成测试：用 `DeepSeekAdapter` + mock HTTP 层驱动完整 AgentLoop.query 流程；`AnthropicAdapter` 同理。
8. FastAPI 集成：session 存储里记录用户选择的 provider + API key，在 router 层根据 session 配置实例化对应 adapter，注入 AgentLoop。

---

**批准记录**：

- **已批准**（作者口头，2026-04-20，方案 B 衍生）
- 进入实施阶段
