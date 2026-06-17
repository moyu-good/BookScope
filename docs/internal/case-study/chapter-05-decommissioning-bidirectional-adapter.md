# 第 5 章 · 消除双向 adapter 那一周：r1 → r2 协议主格式切换

> **状态**：草稿 starter · 等 Sprint 4-7 实施期间持续补完 · 作者未定稿
> **时段起**：2026-05-13（ADR-007 作者签字 + Sprint 4 第一波启动）
> **时段终**：（待 Sprint 7 删 r1 代码后填）
> **覆盖 commit**：（待 Sprint 4-7 实施期间补全）
> **与前后章关系**：第 4 章讲 anshi 五题的 4 个 autofix 工具栈如何堆进 loop.py；第 6 章讲 Sprint 5 性能优化那一日；第 5 章夹在中间——跨 4 个 sprint 的代际级协议切换，把这两章共同暴露的"adapter 越长越脏"问题从源头切掉

---

## 序：藏在 adapter 里的 5 个月

r1 启动那天作者熟的是 Anthropic 协议。第 16 轮真 API 跑通的 trace 里，agent loop 主循环到处都是 Anthropic Messages API 的 tool_use 形态——`content` 是 block 数组，`stop_reason="tool_use"` 配 `{"type": "tool_use", "id": ..., "name": ..., "input": {...}}` block 是工具调用约定，tool 执行完写回也是 `{"type": "tool_result", "tool_use_id": ..., "content": ...}` block 拼回 messages 数组。这套结构在 `bookscope/agent/loop.py` 1384 行主循环里到处都是——`_extract_content_blocks` / `_block_type` / `tool_use_blocks` / `tool_use_id` / `_truncate_messages` 配对丢弃的 "tool_use block + tool_result block" 语义全都假设 Anthropic 形态。

写的时候没多想——那是作者唯一熟的协议，128 条测试也按这个形态绑好。链路通，trace 干净，第 16 轮 6 小时内活检掉 reranker 之后就再没人回头看主循环的协议形态。

然后 ADR-002 v2 把默认 provider 切到 DeepSeek。理由很朴素——这是个开源学习项目，要让国内学生跑得起，token 成本和中文友好两条都得占。但 DeepSeek 走 OpenAI 兼容协议：`choices[0].message.tool_calls` 数组里每条是 `{"id": ..., "type": "function", "function": {"name": ..., "arguments": "<JSON 字符串>"}}`，tool 执行完写回是独立的 `{"role": "tool", "tool_call_id": ..., "content": ...}` 消息，不是嵌进 user message 的 block。

跟 AgentLoop 内部形态对不上。

当时 ADR-003 选了最小工作量的路径——让 `DeepSeekAdapter` 做双向翻译。请求方向把 Anthropic 形态翻成 OpenAI 形态喂给 SDK，响应方向把 OpenAI 形态翻回 Anthropic 形态给 loop 用。loop 主体一行不改，128 条测试零回归，DeepSeek 当晚就接通了。`AnthropicAdapter` 反而几乎是 passthrough——只 181 行，大部分是 SDK 调用的薄包装。

这个选择埋了 5 个月的账。

5 个月里 BookScope 接了 MiniMax（走 DeepSeek 兼容协议复用 adapter）、astron 退役、试探过 GLM / Qwen / Kimi 都走 OpenAI 兼容。每次新 provider 来都不用改 loop——只动 DeepSeekAdapter。听起来很赞，实际是 adapter 一刀一刀越切越脏。

举几个具体的：

- `_strip_thinking_tags`（adapter L62-69）：minimax-m2.x / deepseek-r1 / qwen-qwq / glm-zero 这些 reasoning model 在 content 里 inline 返回 `<think>...</think>` 段。loop 不知道这事，因为 loop 只认 Anthropic 形态——adapter 在响应翻译时把 think 段抹掉
- `_translate_error` 里的 `_looks_like_content_filter` + `_CONTENT_FILTER_HINTS`（L399-425）：MiniMax HTTP 422 内容审查的若干提示词（`new_sensitive` / `1027` / `content_filter` 等）要在 adapter 里识别后翻译成 `ContentFiltered`，loop 才能重试
- 一些 provider 给 `arguments` 是空串而不是 `"{}"`、`finish_reason` 缺省、`usage` 字段缺失——L342-346 / L327 / L356-358 都是这类宽容降级

DeepSeekAdapter 现在 428 行。一半是双向翻译，一半是怪癖兜底。AnthropicAdapter 还是 181 行近 passthrough，没怎么动过。

更糟的是 chapter-04 写的 anshi 五题——那一章踩出来的 4 个 autofix 工具（unescaped quotes / stray apostrophe / control chars / unescaped answer quotes）全堆在 loop.py 第 1162-1340 行。本来应该是 adapter 层的协议怪癖，但 loop 内部形态是 Anthropic、adapter 接收时已经翻译完了，怪癖兜底只能在 loop 里写。reviewer.py L29-32 又复用了一遍——同一套 autofix 代码两个入口都得维护。

5 个月之后这条路撑不下去了。chapter-04 那 4 个 autofix 工具落地时已经能感觉到 loop.py 在膨胀——再来一个 provider，再加一类怪癖，loop 会变成"主循环 + 协议解释器 + 兜底大杂烩"三合一。这不是干净代码该长出来的样子。

---

## 一、问题真相：让多数派给少数派让路

切换 ADR 的决定不是"代码不好看"四个字推动的——是数据。

把 BookScope 接过和试探过的 provider 列一遍：

| Provider | 协议 | 接入 adapter | 备注 |
|---|---|---|---|
| Anthropic Claude | Anthropic tool_use | AnthropicAdapter（181 行 passthrough） | r1 启动协议 |
| DeepSeek | OpenAI 兼容 | DeepSeekAdapter（428 行双向翻译） | 默认 provider |
| MiniMax-M2.7 | DeepSeek 兼容 | 复用 DeepSeekAdapter | 当前主力 |
| GLM-4-plus | OpenAI 兼容 | 复用 DeepSeekAdapter | 已试探 |
| Qwen-max | OpenAI 兼容 | 复用 DeepSeekAdapter | 已试探 |
| Kimi-k1.5 | OpenAI 兼容 | 复用 DeepSeekAdapter | 已试探 |
| astron-code | OpenAI 兼容 | 复用 DeepSeekAdapter | 已下线 |

7 个 provider，6 个走 OpenAI 兼容协议，只有 Anthropic 自己用 tool_use。比例是 6:1。

更直白点：**国内所有主流 LLM provider 都走 OpenAI 兼容**——DeepSeek / MiniMax / GLM / Qwen / Kimi 一个不漏。Anthropic tool_use 是只 Claude 一家用的协议。BookScope 把少数派当主格式，让多数派每次都经过一层翻译——这是个倒置的工程选择。

后果是三条具体的债：

**第一条：翻译层成所有 provider 怪癖的兜底场。** DeepSeekAdapter 428 行里一半翻译一半兜底；新怪癖来了只能往这一个文件里加。哪天要给 GLM 单独处理某个字段，要么改 DeepSeekAdapter 加分支判断（不干净），要么复制一份 GLMAdapter（重复代码 + 翻译层翻倍）。

**第二条：新 provider 接入要继承所有翻译开销。** 新 provider 即使原生支持 OpenAI function calling，也要走 DeepSeekAdapter 这一层翻译——把 Anthropic tool spec 的 `input_schema` 翻成 OpenAI `parameters`、把 Anthropic message 的 tool_result block 拆成独立 `role="tool"` 消息、把 `tool_calls` 数组拆成 `tool_use` block、JSON arguments 字符串解析成 dict、reasoning 块 strip。这些事情新 provider 本来不需要做——但因为 loop 内部是 Anthropic 形态，它必须经过。

**第三条：工程直觉不对。** "以多数协议为基础"是行业惯例。OpenAI function calling 是国内外事实标准；Anthropic tool_use 只有 Claude 一家用。让多数派给少数派让路是逆流——ADR-003 自己在第 67 行就已经承认过这条路径该反过来，只是当时不愿意付迁移代价。

5 个月的债积累到 chapter-04 那 4 个 autofix 把 loop.py 推到 1384 行那天——付迁移代价的时刻到了。

---

## 二、ADR-007 决策框架

ADR-007 作者今天签字（2026-05-13）。

完整内容在 `docs/architecture-decisions/007-r2-openai-function-calling.md`，这里把五条决策摘下来：

**D-1：切换 AgentLoop 内部主格式。** `bookscope/agent/loop.py` 主循环里的 Anthropic tool_use 形态全部改成 OpenAI function calling 形态。`_extract_content_blocks` / `tool_use_blocks` 改读 `choices[0].message.tool_calls`；tool 执行完写回从 user message 里的 tool_result block 改成独立的 `{"role": "tool", "tool_call_id": ..., "content": ...}` 消息；assistant message 追加从 block 数组改成 `{"content": str_or_null, "tool_calls": [...]}`；`_truncate_messages` 的配对扫描语义改成"assistant 含 tool_calls + 后续 N 条 role=tool 消息"成组丢弃；`stop_reason` 判断改读 `finish_reason`。

**D-2：AnthropicAdapter 反向翻译。** 当前 181 行近 passthrough 的 AnthropicAdapter 要改写——请求方向把 OpenAI 形态翻译成 Anthropic 形态再喂给 SDK，响应方向把 SDK 返回的 Message 对象翻译成 OpenAI 形态返回给 loop。工程量已知——翻译表跟 DeepSeekAdapter 现在做的方向相反，路径完全镜像。

**D-3：DeepSeekAdapter 退化成 passthrough。** 请求方向直接 forward 给 openai SDK；响应方向把 ChatCompletion 对象转成 plain dict，字段名保留 OpenAI 原样。reasoning 块 strip、错误翻译、内容审核识别这些**继续在 adapter 层做**——它们本来就是 provider 怪癖，本来就该在 adapter 层处理；切换主格式之后这些代码留下来，但不再夹在双向翻译之间，干净。

**D-4：feature flag 双轨。** 环境变量 `BOOKSCOPE_AGENT_PROTOCOL=r1|r2`，默认 `r1`。r1 完全不动——走当前 loop.py + 当前 adapter。r2 走新增的 `bookscope/agent/loop_r2.py` + `deepseek_r2.py` + `anthropic_r2.py` 并列存在。`bookscope/agent/__init__.py` 按 env 分派构造。

理由是把切换风险全压在 r2 路径上。r1 现有所有 batch 数据、case-study 数据都依赖 r1 trace 结构里的 `tool_use` / `tool_result` 字段名，case-study 章节里的引文也按 r1 结构截取——双轨期间 r1 用户完全不受影响。

**D-5：trace 结构 versioned。** `LoopTrace.tool_calls` 字段当前是宽松 `list[dict]`，没绑死字段名。新增 `LoopTrace.protocol_version: Literal["r1", "r2"]`，默认 `r1`。tool_calls 里每条记录的字段名按版本走（r1 用 `tool_use_id`，r2 用 `tool_call_id`）。case-study 和 batch 归档要在元数据头标注 `protocol_version`。

旧数据全部隐式 r1；脚本读取时若缺字段按 r1 处理，向后兼容不破坏。

### 4 sprint 时间表

| Sprint | 工作 | Deliverable |
|---|---|---|
| Sprint 4 | r2 loop / adapter 落地、单测对齐 | `loop_r2.py` + `deepseek_r2.py` + `anthropic_r2.py` + 单测 120 条 |
| Sprint 5 | r1 vs r2 对照实验 | anshi / mingchao 各 3 次跑、std 报告、本 ADR 撤回条件评估 |
| Sprint 6 | r2 切默认 + r1 deprecated | env 默认改 r2，r1 标 deprecated 但保留 |
| Sprint 7 | r1 代码删除 | 删 loop.py / 原 adapter（保留 reasoning strip 等公用工具） |

每个 sprint 结尾在 `docs/internal/STATE.md` 记录是否继续推进。

### 撤回条件

ADR 在 Sprint 5 末评估三条撤回条件，任一命中重开 ADR：

- r2 在 anshi / mingchao 两本书 baseline std 范围内退化超 2 分（memory `feedback_baseline_variance_first.md` 的纪律——单次跟单次比要先求 baseline std，r1 std 已经在 1.06 量级，阈值跟着放宽）
- Anthropic 反向翻译引入持续不稳，BYOK Claude 用户大量退化
- Anthropic 官方在 r2 落地前推出 OpenAI 兼容 endpoint——若推出则 r2 价值降一档，但仍值得做（行业标准对齐 + 翻译层简化仍成立）

撤回不是"r2 不能慢"——是"r2 不能在 noise 之外退化"。这条纪律来自第 33 轮的教训：单次 baseline 当 ground truth 比新版本会得错误结论。

---

## 三、Sprint 4 第一波：骨架先落

commit `1c74806`——5 月 13 日当天 ADR 签字后 4 小时落下来。`feat(sprint-4): BE · r2 骨架第一波 · LoopTrace.protocol_version + env flag 路由 + 3 个 r2 文件占位`，6 个文件 +234 行，0 删除。

六个文件按角色分两组——挂载点 2 个、占位 3 个、测试 1 个：

| 文件 | 行数 | 角色 | ADR 决策 |
|---|---|---|---|
| `bookscope/agent/models.py` | +9 | `LoopTrace.protocol_version: Literal["r1", "r2"] = "r1"` | D-5 trace versioned |
| `bookscope/agent/__init__.py` | +25 | `_select_agent_loop_class()` 读 env 路由 | D-4 双轨 env flag |
| `bookscope/agent/loop_r2.py` | 新 55 | r2 主循环骨架，TODO 5 条 | D-1 切主格式（占位） |
| `bookscope/agent/adapters/deepseek_r2.py` | 新 41 | DeepSeek r2 骨架 | D-3 退 passthrough（占位） |
| `bookscope/agent/adapters/anthropic_r2.py` | 新 43 | Anthropic r2 骨架 | D-2 反向翻译（占位） |
| `tests/agent/test_r2_skeleton.py` | 新 57 | 5 个 pytest 用例 | 验证骨架接通 |

测试 526 → 531 全绿——r1 路径 0 改动 0 回归，r2 路径 5 条新断言全过。`BOOKSCOPE_AGENT_PROTOCOL=r2 python -c "from bookscope.agent import _select_agent_loop_class; print(_select_agent_loop_class())"` 的 env 烟测输出 `<class 'bookscope.agent.loop_r2.AgentLoop'>`，分派路径接通。ruff 改动文件全绿。

第一波四个工程选择是有判断的，不是堆代码：

**第一，骨架不动核心。** 5 agent 天的工作量在第一波只挂载点不切真行为——r1 路径一行不改，r2 默认不开。零运行时风险。"先把 env flag 接通"和"先把主循环切完"是两条路线，后者一旦中途出问题会回滚 1384 行 loop.py 的 5 处改动点；前者只要 env 默认 r1，所有现网 batch 跑的都还是 r1 路径，第二波出问题最多丢的是新加的几十行 r2 文件。

**第二，r2 子类继承 r1 一行写完。** 三个 r2 文件骨架阶段都是 `class AgentLoop(_R1AgentLoop): pass` 这种一行子类——env 切到 r2 立刻能跑，行为等价 r1。这让 ADR-007 D-4 的双轨 env flag 可以**先接通再充实**，不用等第二波 5 处改动点全部落完才能验证路由。先接通后充实是 big-bang 切换的反面。

**第三，TODO 清单作 contract。** 三个 r2 文件末尾都写明第二波要改的具体方法名——`loop_r2.py` 标注 5 处改动点（`_extract_content_blocks` / 写回 tool_result / append assistant message / `_truncate_messages` 配对扫描 / `stop_reason` 判断），`deepseek_r2.py` 标注退翻译时哪些怪癖兜底要留下（`_strip_thinking_tags` 等公用工具），`anthropic_r2.py` 标注反向翻译的字段映射方向。第二波接手的 BE agent 不用回头读完整 ADR-007，看文件末尾 TODO 就知道改哪。

**第四，测试身份不只跑通。** 5 条断言里第 5 条是 `assert issubclass(R2AgentLoop, R1AgentLoop)`——验证骨架阶段 r2 是 r1 子类。这条断言会在第二波 `loop_r2.AgentLoop` 不再继承 r1 时**自然失败**，作为"骨架阶段 → 核心切换阶段"的明显信号。一条测试同时是合约（骨架期 r2 等价 r1）和切换闸门（第二波删继承时这条必须改），不是装饰。

第一波不验证 r2 真实跑通——那是第二波的事。骨架落完之后再动 1384 行 loop.py 主循环的 5 处改动点。

---

## 四、Sprint 4 第二波：loop_r2 真切——主循环 5 处改动点

commit `46bae86`——5 月 13 日第一波之后几个小时落下来。`feat(sprint-4): BE · r2 核心切第二波 · loop_r2 5 处改动真切 + deepseek_r2 退翻译留怪癖 + anthropic_r2 守护 + 23 r2 测试`，10 个文件 +2338/-102。

骨架阶段 `loop_r2.py` 是 55 行子类 `class AgentLoop(_R1AgentLoop): pass`；第二波之后 740 行独立 class。删继承这一步本身是个判断——继承会把 r1 那批 Anthropic 形态的 `_extract_content_blocks` / `_block_type` / `_truncate_messages` 方法定义全带进 r2 namespace，混着新写的 r2 方法看起来"两套都在"，后续维护极易翻车。独立 class + 共用工具函数从 `bookscope.agent.loop` 显式 import（`_elapsed_ms` / `_invoke_client` / `_resp_field` / 各种常量），消息形态相关的方法全 r2 自己写。

下面按改动点串。

### 改动点 1：`_extract_tool_calls` 读 `choices[0].message.tool_calls`

r1 形态是从 Anthropic content blocks 数组里筛 `type=tool_use` 的 block。r2 形态完全换轨——读 `choices[0].message.tool_calls`，每条是 `{id, type: "function", function: {name, arguments}}` 嵌套结构。

实现拆三层 helper（`loop_r2.py` L107-140）：

```python
def _msg_field(msg, field):
    if isinstance(msg, dict): return msg.get(field)
    return getattr(msg, field, None)

def _tc_field(tc, field): ...
def _tc_function_field(tc, field):
    fn = _tc_field(tc, "function")
    if isinstance(fn, dict): return fn.get(field)
    return getattr(fn, field, None)
```

理由是 OpenAI SDK 真跑起来返回 `ChatCompletionMessage` 对象，访问要走 `getattr`；但测试 mock / adapter passthrough 转 plain dict 后又得走 `.get`。两种形态混着进 loop——helper 把这条岔路收在一处，主流程不分支。

`_extract_tool_calls` 本身 8 行（L411-418）：拿到 `tool_calls` 字段，`None` 归 `[]`，单个非 list 包装成 list，避免下游 `for tc in tool_calls` 在某些 provider 给单值时炸。

### 改动点 2：N 条 `role=tool` 消息追加 + 严格保序

r1 形态是单条 user message 里塞 N 个 `tool_result` block。r2 形态完全拆开——N 个 tool_call 对应 N 条独立 `{"role": "tool", "tool_call_id": ..., "content": ...}` 消息，按调用顺序紧跟 assistant 消息。

OpenAI 这条约束比 Anthropic 严——**tool_call_id 顺序必须严格对应 assistant 里 tool_calls 的顺序**。直觉用 `concurrent.futures.as_completed` 按完成顺序填 outputs 会让 tool_call_id 顺序错位，API 直接 422。这条坑 chapter-06 第二节"tool 调用并行：第一刀切下去"在 r1 已经踩过一次（74bddd5 那次 CI 上 422 才发现）——r2 这次直接复用同一保序模式，不再当新坑。

`_dispatch_tools_parallel`（L483-568）的实现：

```python
outputs = [None] * n
with ThreadPoolExecutor(max_workers=max_workers) as executor:
    future_to_idx = {
        executor.submit(self._dispatch_tool_with_retry, ...): idx
        for idx, meta in enumerate(tool_metas)
    }
    for future, idx in future_to_idx.items():
        outputs[idx] = future.result()

for i in range(n):
    messages.append({
        "role": "tool",
        "tool_call_id": tool_metas[i][1],
        "content": json.dumps(outputs[i], ensure_ascii=False),
    })
```

`dict[future, idx]` 映射 + 按 idx 写回 outputs，慢的 tool 会让快的 tool 等，但顺序保住。N == 1 时跳过 ThreadPoolExecutor 同步调用——保留 r1 的单 tool 优化。

`test_loop_r2_parallel_tool_dispatch_preserves_order`（`tests/agent/r2/test_loop_r2.py` L339-382）专门验证这条：3 个 tool_calls `call_1` / `call_2` / `call_3` 并发派发后追加的 role=tool 消息 `tool_call_id` 必须严格按这个顺序排列。

`arguments` 还有个 OpenAI 独有的坑——它是 **JSON 字符串**不是 dict。DeepSeek / MiniMax 某些 reasoning model 给空串 `""` 而不是 `"{}"`，`json.loads("")` 会抛 `JSONDecodeError`。L514-519 降级处理——空串 / 解析失败 / 解析后非 dict 都归空 dict，让下游 Pydantic 模型自己报缺字段的具体错误，而不是被 JSON 解析中途打断。

### 改动点 3：assistant 消息形态——`content` + `tool_calls` 字段

r1 的 assistant 消息 `content` 是 block 数组。r2 切到 `{"role": "assistant", "content": str_or_null, "tool_calls": [...]}`——`content` 是字符串或 None，`tool_calls` 是另一个并列字段。

两个坑写在 `_append_assistant_message_r2`（L441-477）：

第一，`content == ""` 跟 `content == None` 含义不同。OpenAI 某些 provider 对空字符串 content 强校验直接 422，None 则放过。L454-456 统一归一——`isinstance(content, str) and content == ""` 改成 `None`。

第二，**不带 tool_calls 时不要加空 list 字段**。某些 provider（具体是 GLM 在试探期踩过）会校验 `tool_calls` list 必须非空，传空 list 直接报错。这条 r2 实现里走的是另一条岔路——只有 tool_calls 非空时才走 `_append_assistant_message_r2`，纯文本回复走 `_parse_final_answer` 路径不追加 assistant 消息（让 final answer 作为最后一轮 LLM 输出直接返回，不写回 messages）。两条路径分干净，避免一个方法里写"按条件加字段还是不加字段"的分支。

`test_loop_r2_assistant_message_with_tool_calls_field`（L134-176）覆盖这条——构造 `content=None` 的 OpenAI 风格响应，验证追加的 assistant 消息 `content` 确实是 None，`tool_calls` 字段包含完整 `{id, type: "function", function: {name, arguments}}` 嵌套。

### 改动点 4：`_truncate_messages_r2` 配对扫描

r1 配对是 1+1——assistant 含 tool_use block 配 user 含 tool_result block，永远 2 条一组。r2 配对是 1+N——assistant 含 tool_calls 配后续 N 条 role=tool 消息，N 由该 assistant 的 `len(tool_calls)` 决定。

算法在 `_truncate_messages_r2`（L872-943），关键判断：

```python
if n > 0:
    if len(middle) >= 1 + n and all(
        _is_role_tool(middle[i]) for i in range(1, 1 + n)
    ):
        middle = middle[1 + n:]
        progressed = True
        continue
    break  # 连续性不满足停止丢弃
```

N 配对比 1 配对的容错空间小——r1 错位最多伤一对，r2 错位会伤 N+1 条消息或把无关历史误删。所以选 break 而不是 skip——只要后续 N 条不严格都是 role=tool，整个截断循环就停下来。宁可这次 truncate 没截到位下次再来，也不要把无关 user / assistant 误删。

`progressed` flag 是从 r1 抄来的——防"输入正好 ≤ KEEP_LAST 不动 → retry 死循环"。第一次进 truncate 必须真丢一条才进入"剩余总长度 ≤ KEEP_LAST 即停"的判断；否则进来就停，外层 `_invoke_with_context_truncate_retry` 看 context 还超限继续重试，又进 truncate 又啥都不丢，死循环到把 `_context_truncate_retry_limit` 烧光。

测试两条互为反例（L184-240）：

- `test_loop_r2_truncate_pairs_assistant_with_n_tool_messages`：assistant(tool_calls=2) + 2 条 role=tool 成组丢弃
- `test_loop_r2_truncate_skips_when_tool_count_mismatch`：assistant(tool_calls=2) 但只有 1 条 role=tool，停止丢弃保留最后一条

### 改动点 5：`finish_reason` 替 `stop_reason`

r1 的 `stop_reason` 三种状态——`tool_use` / `end_turn` / `max_tokens`。r2 的 `finish_reason` 三种状态——`tool_calls` / `stop` / `length`。字面映射很干净。

但 loop 控制流**没有完全依赖 finish_reason**——L265-273 注释说清楚：

> 注：tool_calls 非空 == finish_reason="tool_calls"（OpenAI 规约），用 tool_calls 列表存在与否驱动 loop 比读 finish_reason 字符串更强（某些 provider 在工具调用时不准确写 finish_reason）。

实际控制流是看 `tool_calls = self._extract_tool_calls(message)` 这条 list 空不空——非空走 tool 派发分支，空走 final answer 解析分支。`_extract_finish_reason` helper（L420-428）留着但只在 max_iterations / error 诊断 hook 里用得到。

理由是 chapter-04 那段时间 MiniMax 偶尔出现"`finish_reason="stop"` 但 `tool_calls` 字段非空"的怪状——读字符串作为 loop 信号会让 r2 在 tool 调用轮直接走去 parse final answer，拿到 None content 立刻 LLMFormatError。改读 `tool_calls` 字段存在性后这条 race 自然消解——字段是结构信号，比字符串强。

### 测试身份兼合约——预言兑现

第三节末尾写过："5 条断言里第 5 条是 `assert issubclass(R2AgentLoop, R1AgentLoop)`——验证骨架阶段 r2 是 r1 子类。这条断言会在第二波 `loop_r2.AgentLoop` 不再继承 r1 时自然失败"。

第二波 BE 真把 loop_r2 改成独立 class，骨架那条断言自然挂。BE 顺手改了名（`tests/agent/test_r2_skeleton.py`）：

```diff
- def test_r2_agent_loop_is_subclass_of_r1():
-     assert issubclass(R2AgentLoop, R1AgentLoop)
+ def test_r2_agent_loop_is_independent_class():
+     assert not issubclass(R2AgentLoop, R1AgentLoop)
+     assert R2AgentLoop is not R1AgentLoop
```

语义从"断言子类身份"翻转成"断言独立类身份"。骨架那条挂掉的测试不是 bug——是"骨架阶段 → 核心切换阶段"的明显信号。**失败的测试当合约**这个工程姿态值得点出：第一波留这条测试不是为它"跑通"，是为它"在第二波必然失败"。failed 是合约约定的事件，名字改完后两条断言一起放着继续守独立类身份不被回滚。

新加的 23 条 r2 测试（`tests/agent/r2/` 5 个文件）覆盖率分布：10 条 `test_loop_r2.py` 5 处改动点 + 配对保序 + arguments 空串降级；9 条 `test_deepseek_r2.py` passthrough 路径 + reasoning strip + 内容审查识别；3 条 `test_anthropic_r2.py` 验 `NotImplementedError` 守护 + workaround 文案；1 条 smoke 跨文件验证 r2 模块整体可 import。531 → 554 全绿——r1 路径 0 改动 0 回归。

第二波之后 r2 真能跑起来了。下面要处理的是 Anthropic 反向翻译——那是第五节的事。

---

## 五、AnthropicAdapter 反向翻译的工程量与坑

commit `d236a05`——5 月 13 日第二波几小时后落下来。`feat(sprint-4): BE · anthropic_r2 反向翻译实施 · ADR-007 D-2 工程量最大一块兑现`，2 个文件 +921/-59：`anthropic_r2.py` 60 → 456 行（+396），`tests/agent/r2/test_anthropic_r2.py` 54 → 520 行（删 3 旧守护测试 + 加 28 新翻译测试）。

第二波留的 `NotImplementedError` 守护占位被替换成真双向翻译——loop_r2 内部 OpenAI 形态进来翻成 Anthropic 形态喂 SDK、SDK 返回的 `Message` 对象翻回 OpenAI `ChatCompletion` plain dict 给 loop。路径跟 r1 的 DeepSeekAdapter 完全镜像——后者是 Anthropic → OpenAI 双向翻译给 OpenAI 兼容 provider，前者是 OpenAI → Anthropic 双向翻译给 Anthropic SDK。**5 个月之前付不起的迁移代价这次反过来由 Anthropic 这一家承担**——一个 provider 写一份翻译，比 6 个 provider 共用一份翻译干净多了。

### 请求方向 5 处翻译

**第 1 处：system 抽到顶级字段。** OpenAI 把 system 当 messages 列表里 role=system 的一项，Anthropic 是独立的顶级字段。`_translate_messages_to_anthropic`（L157-217）扫一遍 messages 把所有 role=system 条目抽出来，跟函数参数 `system_arg` 用 `\n\n` 合并成单字符串放到顶级 `system` kwarg。多条 system 合并保结构——某些 prompt 模式（reviewer / loop 都会塞 system）会同时传顶级 system + 列表里 system，不能丢任何一条。

**第 2 处：role=tool 连续 N 条消息合并回 user tool_result block 数组——保序又是关键。** OpenAI 是 N 条独立 role=tool 消息，Anthropic 要求合并成 1 条 user message 含 N 个 `tool_result` block。`_translate_messages_to_anthropic` L186-200 用 inner while 循环扫连续 role=tool 一段、`tool_call_id` ↔ `tool_use_id` 严格对位拷过去，遇到非 tool 消息立刻停下封一个 user message 进 anth list。这条对位错了 Anthropic SDK 直接 400——chapter-06 第二节 r1 时代踩过相同形态的坑，r2 这边直接复用保序模式不再当新坑。

**第 3 处：assistant `tool_calls` 字段拆成 `content` blocks——arguments JSON 解析失败要容错。** OpenAI 形态 `{role: assistant, content: "...", tool_calls: [...]}` 翻成 Anthropic `{role: assistant, content: [{type: text, ...}, {type: tool_use, id, name, input: {...}}]}`。`_translate_assistant_message`（L220-259）三个工程选择都点出来：

- `arguments` 在 OpenAI 是 JSON 字符串、`input` 在 Anthropic 是 dict——`_parse_arguments_string`（L262-275）做转换
- **JSON parse 失败退化 `{"_raw": original}` 不 raise**（L271-272 except 块）——chapter-04 写过 minimax 给残缺 JSON 的常态，这里 adapter 层不该让翻译过程因为下游 LLM 拼错括号就崩，让 Anthropic 拿着 `_raw` 去做它该做的事（schema 校验失败下游会清晰报错）
- Anthropic 要求 content 至少一个 block——空 content + 空 tool_calls 时退化加一个空 text block（L256-257）。这条 ADR-007 D-2 没提，SDK 试出来的边界

**第 4 处：tools 嵌套 → 扁平 + 双形态兼容。** `_translate_tools_to_anthropic`（L278-314）做 `{type: function, function: {name, description, parameters}}` → `{name, description, input_schema}` 的扁平化（parameters → input_schema 字段改名，结构内 JSON Schema 不变）。但 loop_r2 当前 `_build_tool_schemas` 内部 docstring 选了"tools 仍传 Anthropic 扁平、由 adapter 兜底翻译"——这是 ADR-003 留下的既定路径，但 ADR-007 D-1 又说"loop 主格式 OpenAI"，两边没显式对齐。`_translate_tools_to_anthropic` L296-313 双形态都接——OpenAI 嵌套照翻译，Anthropic 扁平原样过——保持向前兼容。

**第 5 处：tool_choice 4 种值翻译表。** ADR-007 D-2 完全没提 tool_choice（这条本轮 BE agent 自查标了 ADR 修订建议）。`_translate_tool_choice_to_anthropic`（L317-341）兜底全部 4 种：

- `"auto"` → `{"type": "auto"}`
- `"none"` → 返回 `None`，调用方不传 tool_choice 字段（Anthropic 较新版本支持 `{"type": "none"}` 但兼容性差——干脆不传更稳）
- `"required"` → `{"type": "any"}`
- `{"type": "function", "function": {"name": X}}` → `{"type": "tool", "name": X}`

### 响应方向 4 处翻译

**第 1 处：content blocks 拆分——空与非空状态语义不同。** `_translate_response_to_openai`（L349-413）扫 Anthropic content blocks 一遍——`text` block 合并成单字符串 `content_str`，`tool_use` block 转 OpenAI `tool_calls` 数组。两个 None 表达坑写得很明确（L378-382）：

```python
content_str: str | None = "".join(text_parts) if text_parts else None
tool_calls_field: list[dict[str, Any]] | None = (
    tool_calls_out if tool_calls_out else None
)
```

只 tool_use 没 text → `content=None` 不写空串；只 text 没 tool_use → `tool_calls=None` 不写空 list。chapter-05 第四节改动点 3 已经提过——某些 OpenAI 兼容 provider 对空 list / 空串校验严，r2 选 None 表达"无"。

**第 2 处：function.arguments 必须 JSON 字符串。** Anthropic input 是 dict（结构化的、解析过的）→ OpenAI arguments 是 JSON 字符串（要 loop_r2 那边 `_extract_tool_calls` 之后再 `json.loads` 回 dict）。L373 一行：`"arguments": json.dumps(input_val, ensure_ascii=False)`——`ensure_ascii=False` 关键，中文小说内容里全是非 ASCII，转 `\uXXXX` 会让下游 schema validator 误读字段长度。

**第 3 处：stop_reason → finish_reason 映射。** L50-55 常量表写死 4 种：`tool_use→tool_calls / end_turn→stop / max_tokens→length / stop_sequence→stop`。Anthropic 后续可能加 `pause_turn / refusal` 等新值，本轮 BE agent 自查标了 ADR 修订建议——Open Q 应该加一条。L385 fallback 默认 `"stop"`——未知 stop_reason 也给 OpenAI 一个合法 finish_reason，不让 loop_r2 控制流卡住。

**第 4 处：usage 字段改名 + 加 total_tokens。** Anthropic 的 `input_tokens` / `output_tokens` → OpenAI 的 `prompt_tokens` / `completion_tokens`，加 `total_tokens = input + output`（OpenAI 有这个字段 Anthropic 没有）。L408-412 直白翻译。

### 测试 28 条对应 9 处翻译点

`tests/agent/r2/test_anthropic_r2.py` 520 行 28 测试——请求方向 13 + 响应方向 9 + 端到端 2 + 边界 4。挑 4 条有代表性的：

- `test_request_system_message_extraction_to_top_level`（L94）——抽出语义对位
- `test_request_tool_messages_merged_to_user_tool_result_block`（L120）——保序 + 对位
- `test_request_tool_call_arguments_invalid_json_fallback`（L220）——容错退化 `{"_raw": ...}`
- `test_response_only_tool_use_content_none`（L334）——None vs 空串语义
- `test_anthropic_r2_complete_roundtrip_with_tool_call`（L438）——端到端 OpenAI 形态进 → 翻成 Anthropic 喂 SDK → SDK 返回 → 翻回 OpenAI 形态出

测试 554 → 579 全绿（+25 净新增——删 3 旧守护测试 + 加 28 新翻译测试）。r1 路径 0 改动 0 回归。

### ADR-007 修订建议 4 条

本轮 BE agent 自查发现 ADR-007 D-2 没覆盖到的边界，列 4 条该补：

1. **D-2 没提 tool_choice 翻译表**——实际 4 种值都必要，光说"反向翻译"不够。建议 D-2 加一段 tool_choice 字典映射
2. **tools 入参约定 D-1 与 ADR-003 隐含约定打架**——D-1 说 loop 主格式 OpenAI 应该传嵌套 tools，但 `_build_tool_schemas` docstring 选了 Anthropic 扁平+ adapter 兜底翻译。两条不矛盾但没对齐——建议 ADR-007 补一句"tools 入参职责划分：loop 直传 Anthropic 扁平，由 adapter 内部兼容两形态"
3. **assistant 空 content + 空 tool_calls 边界**——SDK 要求 Anthropic assistant content 至少一个 block，加了空 text block 兜底，ADR 没提。建议 D-2 加一行"翻译时若 OpenAI assistant 既无 content 又无 tool_calls，退化加一个空 text block 保 SDK 合法性"
4. **Open Q 加 stop_reason 集合 + provider 差异**——Anthropic 后续可能加 `pause_turn` / `refusal` 等新值。建议加一条 Open Question："Anthropic stop_reason 完整集合及未来新增值的兜底策略"

ADR-007 D-2 工程量本轮兑现完毕。下一节是 Sprint 5 r1 vs r2 对照实验——r2 路径完整三 adapter 都接通后才有跑 batch 的资格。

---

## 六、Sprint 5 r1 vs r2 对照实验数据

commit `c847169` + `aa8d8d0`——5 月 13 日第五节翻译落完几小时后跑下来。`data(sprint-5): r1 vs r2 协议对照 12 batch · 两本书都不退化 · ADR-007 撤回条件不命中` + `docs(exp-005): 补跨书 mismatch 说明 + batch-03 q1 失败诊断`。完整实验报告在 `docs/internal/experiments/005-r1-vs-r2-protocol-comparison.md`。

ADR 第二节末写过撤回条件——r2 vs r1 差 > r1 std × 1.0 算退化。这一节就是去把这条阈值压在真数据上看会不会响。

### 实验设计

变量锁死到只剩协议层一条岔路：

- provider：minimax `MiniMax-M2.7`
- prompt：`loop_system_prompt_v3.4.md`（第 33 轮收敛的当前最优版本）
- reviewer：minimax + `reviewer_rubric_v1`（5 维 25 分制）
- 题集：`v2-batch-01.json` 5 题作家诊断题
- 路由：env flag `BOOKSCOPE_AGENT_PROTOCOL` 切 r1 / r2
- `BOOKSCOPE_QUESTION_PROCESSING_ENABLED=0`——关 question_processor 避免新功能（chapter-08 那一日落地的长题拆题）混进协议层对照

两本书 × r1 / r2 × **3 次跑** = 12 batch / 60 题。3 次不是堆数据——memory `feedback_baseline_variance_first.md` 第 33 轮被作者锤过一次："单次 baseline 当 ground truth 比新版本会得错误结论"。r1 std 不知道前提下任何"r2 跌 2 分"都没法判断是退化还是 noise。这次先把 r1 自己跟自己跑 3 次求 std，再让 r2 的浮动落进这个容忍带里看。

并发组织：3 波 × 4 batch（每波两本书 r1+r2 各一遍），总耗 25 分钟。token 估算 60 题 × 30k input + 4k output ≈ 1.8M input / 240k output。

### 数据对照

12 batch 拆开看：

| Batch | n | 各题 total | avg |
|---|---|---|---|
| anshi r1 #1 | 5 | 25 / 15 / 17 / 10 / 19 | 17.20 |
| anshi r1 #2 | 5 | 19 / 18 / 17 / 10 / 12 | 15.20 |
| anshi r1 #3 | 5 | 10 / 7 / 21 / 21 / 16 | 15.00 |
| **anshi r1 合计** | **15** | — | **15.80** |
| anshi r2 #1 | 5 | 19 / 17 / 19 / 10 / 20 | 17.00 |
| anshi r2 #2 | 5 | 6 / 11 / 7 / 14 / 15 | 10.60 |
| anshi r2 #3 | 4 | 14 / 5 / 18 / 18 | 13.75 |
| **anshi r2 合计** | **14** | — | **13.79** |
| mingchao r1 #1 | 5 | 15 / 17 / 20 / 15 / 18 | 17.00 |
| mingchao r1 #2 | 5 | 18 / 21 / 18 / 16 / 12 | 17.00 |
| mingchao r1 #3 | 5 | 21 / 18 / 20 / 19 / 17 | 19.00 |
| **mingchao r1 合计** | **15** | — | **17.67** |
| mingchao r2 #1 | 5 | 18 / 14 / 19 / 15 / 14 | 16.00 |
| mingchao r2 #2 | 5 | 15 / 23 / 18 / 19 / 19 | 18.80 |
| mingchao r2 #3 | 5 | 19 / 21 / 19 / 17 / 17 | 18.60 |
| **mingchao r2 合计** | **15** | — | **17.80** |

压成对照表：

| 书 | r1 avg | r1 std | r2 avg | r2 std | Δ (r2 − r1) | r1 容忍带 | 退化？ |
|---|---|---|---|---|---|---|---|
| anshi | 15.80 | 5.07 | 13.79 | 5.16 | -2.01 | ±5.07 | **否** |
| mingchao | 17.67 | 2.47 | 17.80 | 2.54 | +0.13 | ±2.47 | **否** |

anshi 一节 r2 比 r1 跌 2.01 分——单看数字会以为"r2 不行"，但 r1 自己的 std 就有 5.07，2.01 远在这条容忍带里。mingchao 一节 r2 涨 0.13 分，r2 std 2.54 几乎等于 r1 std 2.47，**协议变化在 baseline noise 内不可分辨**。两本书都没踩 ADR 撤回阈值。**Sprint 6 切默认 r2 的前置数据条件满足**。

### anshi 一节跨书 mismatch 的反向揭示

12 batch 跑完归档之后逐 batch 抽 reviewer 评语，anshi r2 batch-02 q4 top_issue 第一条直接砸进来：

> 系统加载了完全错误的书籍（安史之乱 vs 朱元璋），检索环节没有做语义相关性过滤，导致后面所有工作都是无效的

回去查 `v2-batch-01.json` 题面——题里直接提朱元璋、李善长、张士诚、陈友谅、第 14 章审问。这是为 mingchao 设计的 5 题作家诊断题。但 anshi r1 / r2 都用了同一题集跑在 anshi（安史之乱）书上——**题书不匹配**。

reviewer 其他几题评语对位上同一件事：

> 两段引文和答案之间没有逻辑关系——第1章讲为何需要安史之乱专著，第3章讲起兵经过，两者无法支撑'陈友谅不存在'这一核心判断，引文是装饰

> BookScope 直接拒绝回答，而不是先处理「书里没有这个人物」这个事实本身——铺垫薄不薄的前提是铺垫存在，这条线根本不在书里

这意味着 anshi 数据真正测的是"跨书 mismatch 下协议稳定性"——不是"题书匹配下协议对照"。**mingchao 一节才是真正的协议层对照**（题书匹配 + r2 微涨 0.13 + std 2.54 ≈ 2.47）；anshi 一节是次要验证。

但反过来想——两种实验条件下 r2 都没退化，这是 ADR-007 D-1 设计可行性的**双重证据**：题书匹配下站得住，跨书错配下也站得住。

补充实验排期写进 STATE：用真正为 anshi 设计的题集（伏笔 / 节奏 / 历史人物建构 / 立场一致性等针对安史之乱的题）重跑 anshi r1 / r2 各 3 次。等 Sprint 3 跨题材测试基线就位（作者新书 epub + 作家诊断题）才能跑——CLAUDE.md 第五节硬规则 AI 不代选题。

### batch-03 q1 失败诊断

anshi r2 batch-03 n=4 不是 5——q1 ERROR，error 类型是 `reviewer_format_error: reviewer output has no valid JSON object`。minimax reviewer 输出非合法 JSON 且 autofix 救不回。

这是 memory `reference_minimax_capabilities.md` 第 2 条 "reviewer JSON 输出非标" 的已知坑——跟 r2 协议无关。chapter-08 那一日 BE-B 在 question_processor 那边加了 JSON parse 兜底，reviewer 这边没扩到。Follow-up task #21 把 question_processor 的兜底扩到 reviewer 入口。

挂这一题不影响整体对照结论——anshi r2 14 题的均值跟 r1 15 题的均值都在同一容忍带里。

### 元层观察

**第一，`feedback_baseline_variance_first.md` 第二次兑现。** anshi r1 std 5.07 / mingchao r1 std 2.47，两本书的 std 差 2 倍。如果照第 33 轮之前的旧习惯单次 r1 跟单次 r2 比，会得出"anshi r2 跌 2 分明显退化"的结论；但 3 次跑求出 r1 自己的 std 之后，5.07 容忍带把 2.01 的 Δ 完全吞掉。3 次跑求 std 不是 nice-to-have——是看清"退化"与"noise"分界的唯一手段。

**第二，r2 12 batch 零协议层崩溃。** loop_r2 5 处改动 + deepseek_r2 passthrough + anthropic_r2 反向翻译 + API 层 `_select_agent_loop_class` 动态路由 + streaming SSE 透传——整个代际切换 60 题跑完没暴露任何 runtime 级问题。挂的那一题是 reviewer JSON 已知坑，不是协议层。这本身就是 ADR-007 设计可行性最硬的一种证据——比分数好看更说明问题。

**第三，mingchao 上 r2 微涨 0.13 分的猜测。** trace 层细分留给 Sprint 6 之后做，本轮先记两个候选解释。一个是 anthropic_r2 反向翻译对 reasoning model 的 `<think>` 块处理更稳——DeepSeekAdapter strip 一次 + anthropic_r2 在反向翻译时如果走 Anthropic SDK 还会再过一次清洗，双层兜底冗余但稳健。另一个是 loop_r2 的 `dict[future, idx]` 保序模式比 r1 的 user message 内 block 顺序约定更严格——某些 provider 在 r1 路径下 block 顺序不严会让 tool_calls 错位，r2 路径直接按 idx 写回 outputs 排掉这条 race。两个猜测都需要 trace 抽样验证才能下结论，本节先挂存疑。

**第四，实验设计缺陷被反向揭示——AI-as-judge 的二次价值。** 跨书 mismatch 这件事不是预实验时发现的，是事后单题深析时被 reviewer 评语揭出来的。"系统加载了完全错误的书籍"这条 top_issue 不是评 agent 的答案——是在评作者副管理设的实验题目。reviewer 工具本来定位是"给作家看答案质量的检测器"，但它被反过来用作"给副管理看实验设计是否严谨的检测器"。这条二次价值跟 chapter-07 写的 AI-as-judge 主线方向反过来——chapter-07 是把 AI-as-judge 走出实验室面向作家用户，本章是 AI-as-judge 反过来照副管理自己的实验设计。一个工具的两条价值方向，本章只点出来下章再展开。

---

## 七、切默认那一天 · Sprint 6 启动

commit `88ab2d9`——2026-05-14 17:59。`feat(r2): Sprint 6 启动 · ADR-007 已批准 · 默认协议 r1 → r2 · r1 deprecated`，9 个文件 +115/-30。看 diff 第一眼会以为是个小 commit——`bookscope/agent/__init__.py:76` env 默认值从字符串 `"r1"` 改成字符串 `"r2"`，加上 `if protocol == "r1"` 一行控制流翻面，主代码改动一共 5 行。**这 5 行底下是 5 个月双向 adapter 账的清盘。**

### 看完实验数据再签——两次签字间隔 1 天

ADR-007 第一次签字在 2026-05-13——作者那天看完 ADR 草案就说"签名没有问题，都可以继续"，Sprint 4 的 r2 三个模块 + 反向翻译那天全部落完。第二次签字隔了 1 天，5 月 14 日才动笔——这 1 天里跑完 Sprint 5 的 r1 vs r2 对照实验 12 batch（commit `c847169`）。

这条节奏值得放慢讲。

第一次签字签的是"方向"——ADR-007 五条决策在白板上推得过、loop_r2 五处改动点列得清、anthropic_r2 反向翻译镜像 deepseek 已落工程量已知。签了就允许花 5 agent 天落代码。

第二次签字签的是"切换"——env 默认翻面会让所有 user-facing 流量直接走 r2。这一签下去 r1 进 deprecated 段，下一个 sprint 直接走 git rm。要签这条得**先看到数据**。

数据是这样的（第六节已经摊开过，这里点要害）：

| 书 | r1 avg | r1 std | r2 avg | Δ | 容忍带 | 退化？ |
|---|---|---|---|---|---|---|
| anshi | 15.80 | 5.07 | 13.79 | -2.01 | ±5.07 | 否 |
| mingchao | 17.67 | 2.47 | 17.80 | +0.13 | ±2.47 | 否 |

anshi 单看 Δ -2.01 像跌，但 r1 std 5.07 是它两倍，2.01 完全落在 baseline noise 里——这就是 memory `feedback_baseline_variance_first.md` 第二次兑现的价值。第 33 轮作者亲自锤过一次"单次 baseline 当 ground truth 比新版本会得错误结论"——3 次跑求 std 不是 nice-to-have，是看清"退化"与"noise"分界的唯一手段。如果 Sprint 5 只跑了一次 r1 + 一次 r2，看到 -2.01 这条 Δ 作者第二次签字大概率不会下笔。

作者 5 月 14 日下午回话：

> 按你的建议来，签字一下，我都同意

8 个字。背后的判断已经在数据里说完了。

### `_select_agent_loop_class` 控制流翻面那一行

`bookscope/agent/__init__.py:76` 改动只有一处——`os.environ.get("BOOKSCOPE_AGENT_PROTOCOL", "r2")` 默认值从 `"r1"` 改 `"r2"`，配合 L77 `if protocol == "r1": return AgentLoop` 把控制流翻成"只有显式传 r1 才走旧路，其他一切包括默认 / r2 / 拼错的值 / 空字符串全走 r2"。

为什么"拼错的值也走 r2"——这是 Sprint 6 切默认的**关键工程选择**。

之前 r1 是默认的时候，env 写 `"r1"` / `"R1"` / `"r0"` / 啥都不写都进 r1，r2 必须显式拼对 `"r2"` 才进。环境变量打错字这种小事过去半年没人遇到，因为 r2 是"研究模式"用户少。Sprint 6 切完默认之后角色反转——r2 是 1.0 路径，r1 退到 deprecated 段位作回滚兜底。这时候控制流必须保证"主路径默认走、回滚路径显式开"，所以判断条件只接 `"r1"` 一个准确字符串作回滚信号，其他全归 r2。

docstring（`__init__.py` L60-72）把这条说得很直：

> `"r2"`（默认）/ 空 / 其他值：返回 `loop_r2.AgentLoop` ——r2 代际 OpenAI function calling 主格式
>
> `"r1"`：返回 `loop.AgentLoop` ——r1 代际 Anthropic tool_use 主格式，**已 deprecated**，Sprint 7 删除

加注末尾留了一行：

> 明确传 `BOOKSCOPE_AGENT_PROTOCOL=r1` 仍可回滚 r1，作 Sprint 7 删除前的最后兜底窗口

回滚窗口的"窗口期"=Sprint 6 启动到 Sprint 7 git rm 之间的全部时间。这段时间任何用户在线上撞 r2 协议异常，作者可以 `export BOOKSCOPE_AGENT_PROTOCOL=r1` 拉回旧路径，不需要回滚 commit。

### 22 个 API mock 测试 autouse 锁 r1——为什么不直接重写

切默认翻面下来跑 pytest，22 个 `tests/api/` 下的 mock 测试集体挂红——这些测试当初按 r1 形态写的桩响应，喂给 LLM mock 的是 `content=[{"type": "tool_use", ...}]` 数组 + `stop_reason="tool_use"` 这套 Anthropic 形态。r2 loop 进来读 `choices[0].message.tool_calls` 直接拿到 None，全套 22 条立刻爆。

这里有两条岔路：

**第一条**：现在花 1 天把 22 条 mock 全部重写成 OpenAI 形态。彻底干净，但 1 天工作量阻塞 Sprint 6 切默认这条主线。

**第二条**：autouse fixture 把 env 默认锁回 r1，让旧 22 条按原协议跑——r1 模块还在文件没删，跑得起。新 r2 mock 测试套另起子目录 `tests/api/r2/` 用 autouse 反向锁 r2 写。

选了第二条。理由不只是省 1 天工作量——更重要的是"主切换 commit 不混重写"这条工程姿态。`88ab2d9` 的 scope 是 env 默认翻面 + ADR 签字 + r1 deprecated 标记，这是个**协议层 1.0 / r1 0.x** 的里程碑 commit；如果同时塞 22 条测试重写进来，code review 时谁也分不清"测试重写有没有偷偷改业务断言"。Sprint 6 主切换先落、r2 mock 重写作为独立 sprint 工作面后排，回头看 diff 史每个 commit 就是一件事。

落地是新建 `tests/api/conftest.py`（31 行）：

```python
@pytest.fixture(autouse=True)
def _lock_r1_protocol_for_api_mocks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOOKSCOPE_AGENT_PROTOCOL", "r1")
```

3 行 fixture 救 22 条测试。autouse 让 `tests/api/` 下任何用例进来之前都先 setenv r1，旧 mock 桩响应跟 r1 loop 对得上继续过。明确测 r2 路径的用例（`test_ask_response_includes_protocol_version_r2`）在用例内部 `monkeypatch.setenv(..., "r2")` 显式覆盖即可——pytest fixture 解析按调用栈就近原则，用例内 setenv 后于 fixture 跑，最终生效。

`test_protocol_routing.py` 同步翻 4 条守护测试名（`test_default_protocol_is_r1` → `..._r2` / 加 `test_protocol_r1_env_routes_to_legacy_loop` 守护回滚路径 / `..._fall_back_to_r1` → `..._fall_back_to_r2`）。骨架阶段 `test_r2_skeleton.py` 那条 `test_select_agent_loop_class_default_r1` 也跟着翻面成 `..._default_r2` + 新加 `..._r1_env` 守护回滚——chapter-05 第三节末尾点过"失败的测试当合约"，这里又一次兑现：默认翻面的事实写进测试名当合约，下次有人不小心改回默认 r1 立刻挂。

pytest **631 通过**（baseline 629 + 翻面后新增 2 条回滚守护断言）。零回归。

### r1 三模块 docstring 加 `.. deprecated:: Sprint 6`

`loop.py` / `adapters/deepseek.py` / `adapters/anthropic.py` 三个 r1 模块顶部 docstring 各加一段：

```
.. deprecated:: Sprint 6
   r1 协议层进入退役段位。Sprint 7 删除。
   主路径走 r2：``loop_r2`` / ``deepseek_r2`` / ``anthropic_r2``。
   回滚机制：``BOOKSCOPE_AGENT_PROTOCOL=r1``。
```

deprecated 标记不阻断 import 也不出运行时 warning——Sphinx 文档渲染会显示退役状态，IDE 跳过去会提示，但代码继续跑。这是 Sprint 6 → Sprint 7 之间过渡段的姿态：r1 还活着但不接新功能，新 provider 接入不走 r1 adapter 直接进 r2 路径。

### r2 mock 测试套范式脚手架——commit `2d96e90`

切默认 commit 落完几小时，本轮接着搭 `tests/api/r2/` 范式脚手架。`test(api): tests/api/r2 范式脚手架 · happy path + ContentFiltered 错误链`，4 文件 +460 行测试 + docstring。

为什么不一次性把 22 条 r1 mock 全重写——回到上一小段的逻辑：本 commit scope 是**搭范式不是补全套**。后续 sprint 按这套 pattern 复制即可。

四文件：

| 文件 | 角色 |
|---|---|
| `tests/api/r2/__init__.py` | 目录定位（范式 / 脚手架） |
| `tests/api/r2/conftest.py` | autouse 反向锁 r2（覆盖父级 r1 锁） |
| `tests/api/r2/test_agent_ask_r2.py` | happy path：从 r1 拷过来翻成 OpenAI 形态桩 |
| `tests/api/r2/test_error_handling_e2e_r2.py` | error path：ContentFiltered 重试 1+2=3 次调用链 |

两个坑值得点出来。

**第一个坑：pytest 子目录 autouse 在父目录 autouse 之后跑。** 父级 `tests/api/conftest.py` autouse 锁 r1，子级 `tests/api/r2/conftest.py` autouse 锁 r2——两条 fixture 都对 `tests/api/r2/` 下的用例生效。直觉上担心冲突——到底以谁为准？

pytest fixture 解析按目录层级，从根目录向叶子目录解析，越靠近测试文件的 fixture 越晚跑、越后生效。所以**子级 monkeypatch.setenv("r2") 在父级 monkeypatch.setenv("r1") 之后执行，最终 env=r2**。这是设计上的 cascade 顺序，不是 race condition——pytest 文档讲过但代码里看到两条同名 setenv 第一眼还是会愣。

conftest docstring 把这条写死了：

> pytest fixture 解析按目录就近原则——子目录 autouse 在父目录 autouse 之后跑，所以子目录的 `monkeypatch.setenv` 是最终生效值

未来 BE agent 进来加测试时不用回去翻 pytest 文档，看 conftest 注释就知道为什么父级锁 r1 也能让子级跑 r2。

**第二个坑：`time.sleep` patch 路径 r1 vs r2 不同。** ContentFiltered 重试链测试要把 `time.sleep` patch 成 no-op，否则两次重试中间各 sleep 一次会让测试跑 5+ 秒。r1 路径走 `monkeypatch.setattr("bookscope.agent.loop.time.sleep", _no_sleep)`，r2 路径走 `bookscope.agent.loop_r2.time.sleep`——两个模块各自 `import time` 是独立的模块级别引用，patch r1 那条对 r2 不生效。

`tests/api/r2/test_error_handling_e2e_r2.py:158` 直接走 r2 路径：

```python
monkeypatch.setattr("bookscope.agent.loop_r2.time.sleep", _no_sleep)
```

对照 `tests/api/test_error_handling_e2e.py:219` 的 r1 版本只差模块名一字。这条坑写进 r2 测试模板 docstring 后，后续补 22 条 mock 等价版本时不会有人复制粘贴忘改路径。`pytest tests/api/r2/ -v` 2 passed in 9.01s；全套 633 passed in 86s 零回归。

### 未来工作面回顾

本节落笔时挂了三条 follow-up——r2 mock 测试套补全、Sprint 7 删 r1 代码、本章第八节等 Sprint 7 真做完再写。这三条全部在 Sprint 7 落地：r2 mock 测试套在 Sprint 6 第四 / 五 / 六波 BE-QA 联动期间补到位（commit `e4768ba` / `a454f36`），Sprint 7 步骤 ② 直接 git rm 11 个 r1 mock 测试文件（commit `b29d626`）；r1 runtime 三个模块在 Sprint 7 步骤 ③b 真删（commit `440bcad`）；本章第八节就是下面这一节，详见第八节。

切默认这一天的 9 文件 +115/-30 看完了。5 行业务代码 + 31 行新 conftest + 4 个翻面测试名 + 3 个 deprecated 段——加起来不到 100 行真实改动。但每一行底下都有一个工程判断：env 默认翻面只接受 `"r1"` 字符串做回滚信号；22 条旧测试不重写靠 autouse 锁 r1 兜底；r1 不删只标 deprecated 留回滚窗口；r2 mock 测试套只搭范式不补全套。这些判断的共同特征是——**主切换 commit 只做协议层翻面这一件事**。重写 / 补全套 / 删旧码全部排到后续独立 sprint。

5 个月之前 ADR-003 选最小工作量的双向 adapter 路径，把账往后压。5 个月之后 ADR-007 一次性还了，但还的姿态是"分 4 个 sprint 还"——不是一个大 commit 把所有事做完，是把切换拆成"骨架 → 5 处改动点 → 反向翻译 → 实验 → 切默认 → 删旧码"6 个工作面，每个工作面独立 commit 独立验收。这个工程姿态比"切到 OpenAI 兼容协议"这个技术决策本身更值得记。

---

## 八、删 r1 那一天 · Sprint 7 git rm 落地

5 月 15 日下午把 1693 行代码真删了。

这件事得倒着讲——签字在前，audit 在后，删码在最后。中间还插了一次撤回判断。这套节奏跟 Sprint 4 / 5 / 6 那种"想清楚就直接落"不一样，Sprint 7 是把"签字 ≠ 立刻 rm -rf"这件事真摆出来过了一遍。

### 三次签字间隔两天

第一次签字在 2026-05-13 ADR-007 草案通过——那天授权的是 Sprint 4 五条决策落代码。第二次签字隔了一天到 5 月 14 日，授权的是 Sprint 6 env 默认 r1 翻 r2；这一签前面 Sprint 5 跑完 12 batch r1 vs r2 对照实验，撤回阈值压在数据上不响。第三次签字 5 月 15 日，作者那句话：

> 按你的建议继续，通过我的签名

8 个字，授权的是 Sprint 7 git rm 1693 行 r1 runtime。

5 月 15 日凌晨副管理派 BE agent 做的第一件事不是 git rm，是写 audit 报告。`docs/internal/audit/sprint-7-r1-removal-impact.md`（commit `f355593`）3500 中文字 9 节——r1 代码总量盘点、引用面 grep、测试套去留判定、reviewer.py r2 兼容性 audit、fast_path 后续 r2 化空间、chapter-05 第八节素材清单、4 步执行节奏、撤回条件诚实判断、给作者签字的关键判断点。7 项候选撤回条件逐项过完全部不命中。

但作者第三次签字的时候这份 audit 还没回。

签字写的字面意思是"通过我的签名"——副管理把这条解读成"作者基于副管理一贯把握节奏的信任先签了，真执行等 audit 回来分步推"。ADR-007 第三次签字同步写明了这个意思——这条签字不是"立刻 rm -rf"的指令，是预先授权 + 信任副管理把节奏控住。签字下来允许的是"在 audit 不命中撤回条件的前提下，副管理自己决定步骤 ② ③ ④ 的具体节奏"。如果 audit 回来发现命中撤回条件，本签字暂停回 STATE 等复审，不强推。

把"签字"跟"立刻执行"分开这件事，是 ADR-007 第三次签字这一行字里**最有重量的工程姿态**。代际级决策从作者手里下来不是一道直接驱动键盘的电信号，是一个授权令牌，副管理拿着这个令牌按 audit 报告分步执行，每一步可撤回。

### audit 漏审被守住的那一刻

audit 报告 5/15 早上落完，撤回条件不命中，副管理推荐的方案 A 是"先抽 autofix 到 utils 解耦 reviewer、再删 r1 mock 测试、再 git rm r1 runtime、再同步文档"4 步。

第一步 5 月 15 日 11 点落（commit `1050367`）——把 autofix 函数 + `parse_final_answer` 从 loop.py 抽到 `bookscope/agent/utils/json_parsing.py`，reviewer.py 改成从 utils import，r1 loop.py 自己保留私有别名 `_unescaped_quotes_in_text_field = unescaped_quotes_in_text_field` 转调让现有调用零变化。这一步的 precedent 是 commit `b33e985` 把 `extract_first_json_object` 抽到 utils 公共包——同样的"先抽到中性位置、原位置保留私有别名转调"姿态。第二步 13 点落（commit `b29d626`）——git rm 11 个 r1-only mock 测试文件 + 删父级 `tests/api/conftest.py` 整文件 + 部分翻面测试，baseline 663 → 500 净减 163 case。

第三步原计划一条命令——`git rm bookscope/agent/loop.py bookscope/agent/adapters/anthropic.py bookscope/agent/adapters/deepseek.py`。

BE agent 没强删。

read-only grep 跑了一遍 `from bookscope.agent.loop import` / `from bookscope.agent.adapters.deepseek import` / `from bookscope.agent.adapters.anthropic import` 三条搜索——揭出 audit 第 5 节"step ③ 主要风险面"漏掉了一整片硬依赖链。r2 runtime 四个模块（`loop_r2.py` / `fast_path.py` / `anthropic_r2.py` / `deepseek_r2.py`）对 r1 internal symbol 还有物理 import：

- `loop_r2.py:72-94` 从 r1 `loop.py` import **13 个常量 + 5 个私有 helper**——`CONTEXT_TRUNCATE_KEEP_LAST` / `DEFAULT_*_RETRY_LIMIT` / `TOOL_NAME_*` / `_elapsed_ms` / `_invoke_client` / `_resp_field` / `_summarise_output` / `_question_processing_enabled`
- `loop_r2.py:95` 还有一条 `from bookscope.agent.loop import AgentLoop as _R1AgentLoop`——构造期复用 `_R1AgentLoop._load_system_prompt(self)` 当 mixin 用，让 r2 借 r1 prompt 加载逻辑
- `fast_path.py:38-42` 引 r1 的 `TOOL_NAME_SEARCH` / `_elapsed_ms` / `_invoke_client`
- `anthropic_r2.py:44` 引 r1 adapter 的 `_translate_error`
- `deepseek_r2.py:33-38` 引 r1 adapter 的 `DEEPSEEK_DEFAULT_BASE_URL` / `_looks_like_content_filter` / `_strip_thinking_tags` / `_translate_error`

audit 第 5 节做了 grep，但 grep 结果只用在了测试侧——runtime 侧没 grep。一条 grep 一次就能看见的链，audit 阶段把它漏过去了。

这是 ADR-007 第三次签字写的硬规则真兑现一次。

ADR-007 第三次签字下面那段话原文是这样写的：

> 真执行等 audit 回来分步推。如 audit 命中撤回条件，本签字暂停回 STATE 等复审。

这段话不是装饰，是给副管理的硬约束。"作者签字"在工程师语境里一般理解成"主管批了，可以做"——一次性授权。但 BookScope 的副管理模式把这个理解翻面——签字是**条件授权**，条件就是 audit 不命中撤回条件。BE agent 在第三步真要下 git rm 前先跑 read-only grep，本质上是把签字条款最后一次核对。grep 揭出 import 链漏审，等价"audit 命中撤回条件"——签字条款触发暂停，BE agent 没下命令。

BE agent 没下 git rm 命令。**事前阻断 = 事后阻断的 superset**——硬执行下去预计 r2 测试套 500 个挂大约 480 个，任何 import r2 路径的测试都会炸；连夜逐个修雪崩点 commit history 会留一段红屎山。撤回判断写进 STATE 头注（第十一波），列三个 take：A 拆 ③ 成 ③a 抽共享 symbol + ③b git rm；B r2 复制定义不引 r1；C 强删接住雪崩。副管理推荐 A，等作者明示。

作者批的就是"按你的建议继续"。take A 上路。

这一刻值得放慢讲一遍——签字不是放弃监督。代际级删除从作者手里下来到 git rm 命令真敲到键盘，中间至少要走两道关：audit 报告的撤回条件诚实判断、真执行前 BE agent 的 grep 核对。任何一道关响铃，副管理停下回 STATE 写撤回判断等作者复审，不强推。这套节奏跟"作者拍板 / 工程师执行"的传统线性流程不一样——是**作者授权一个工程节奏 + 副管理代行节奏控制 + 子 agent 在每一步前真做事前核对**的三层结构。任何一层失效都会让代际删除出事，三层都在位的时候代际删除是安全的。

### audit 预测 2150 vs 实测 1693 的 457 行差额

take A 落地分两步。

第十二波（commit `0d4d210`）做的是 ③a——新建 `bookscope/agent/_internal/` 包按 loop 内部 helper / Anthropic adapter 怪癖 / DeepSeek 系 adapter 怪癖三层切，避免 `loop_shared.py` 膨胀。25 个真定义搬出：loop_shared 收 16 个常量 + 5 个模块级 helper + 2 个 prompt 加载（`load_system_prompt(instance)` / `load_citation_format_hint(instance)`，原 r1 instance method 改成模块级接 self 形式参数）；anthropic_shared 1 helper；deepseek_shared 1 常量 + 3 helper。r2 四模块的 import 路径全部改指 `_internal/*`，构造期不再走 `_R1AgentLoop._load_*(self)` 这条诡异 classmethod mixin 路径，直接调模块级函数。r1 三模块保留私有别名转调，零行为变化。

这一步的工程姿态有个 precedent——commit `b33e985` 把 `extract_first_json_object` 抽到 `bookscope/agent/utils/json_parsing.py`，commit `1050367` 把 autofix 函数继续抽。`_internal` 包是同一姿态的扩展：**先把共享 symbol 搬到中性位置、再删原位置**。500 测试零回归。

第十三波（commit `440bcad`）做的是 ③b——git rm 真删。

数字摆出来：

- `bookscope/agent/loop.py`：1168 行
- `bookscope/agent/adapters/anthropic.py`：161 行
- `bookscope/agent/adapters/deepseek.py`：364 行
- 合计：**1693 行**

audit 第 1 节当初估的是 2150 行净删。

实测比预估**少 457 行**。差额来源很明确——第十二波 ③a 把 25 个 symbol（16 常量 + 9 helper）从原位搬到了 `_internal/`。audit 估算时按"含共享 symbol"的原始 r1 物理体积估，没把"③a 会先把这部分搬走"算进去。

这一对数字本身就是分步推方案的最好证据。

audit 阶段看到 2150 行净删的体量，作者拍板"按你的建议继续"的那一刻面对的也是 2150 行这个心理预期；如果真按那条路一刀切下去——硬删 r1 + 接住 r2 雪崩——commit history 会留一段非常难看的修复段，r2 测试套挂掉 480 个再连夜逐个修，副管理对作者也没法清楚解释"为什么 r1 删完 r2 也跟着崩了"。分两步走下来 1693 行删得干净——loop_r2 / fast_path / anthropic_r2 / deepseek_r2 任何一个文件没碰 r1 internal symbol，500 测试零回归。

audit 数字看着唬人，分步走下来其实没那么险。

这条经验值得记下来——**代际级删除的真实工程难度不在 git rm 那一刻，在 git rm 之前的解耦准备**。Sprint 7 真正难的是 ③a 那一步把 25 个 symbol 搬到 `_internal/` 让 r2 不再依赖 r1 物理文件；③b 的 git rm 反而是机械动作。

### `__init__.py` 路由翻面 · r1 显式报错带迁移引导

git rm 三个文件还顺手改了两处路由：

`bookscope/agent/__init__.py` 的 `_select_agent_loop_class()` 简化成 r2 直返——之前 Sprint 6 留的"`r1` 字符串作回滚信号"那条岔路这次彻底删。但删的姿态不是静默——env 显式传 `BOOKSCOPE_AGENT_PROTOCOL=r1` 改成抛 `RuntimeError` 含完整迁移引导：

```
r1 protocol decommissioned at Sprint 7 (2026-05-15).
Default is r2 (OpenAI function calling). To restore r1,
revert to commit before 440bcad. See ADR-007 for migration path.
```

不静默忽略很关键。Sprint 6 切默认时留过一段回滚窗口期——任何用户在线上撞 r2 协议异常可以 `export BOOKSCOPE_AGENT_PROTOCOL=r1` 拉回旧路径。这条窗口期到 Sprint 7 关上。如果保留"r1 默认走 r2 不报错"的兜底，任何还在 `BOOKSCOPE_AGENT_PROTOCOL=r1` 部署的用户会**静默走 r2 路径不自知**——主路径改变用户不感知是非常坏的产品姿态。改抛 RuntimeError 含迁移引导让任何还在这条 env 上的部署立刻显式撞红，比静默切路径友好一万倍。

`bookscope/agent/adapters/__init__.py` 同步翻面——`AnthropicAdapter` / `DeepSeekAdapter` 改 re-export from `anthropic_r2` / `deepseek_r2`。用户面 API 名稳定不带 `_r2` 后缀——下游代码 `from bookscope.agent.adapters import AnthropicAdapter` 这条路径不需要改，实际指向的是 `anthropic_r2.py` 里的 `AnthropicAdapter` 类。

这条命名约定值得记一下——**`r2` 后缀只活在模块文件名层，不上升到用户面 API**。Sprint 7 之后再有 r3 切换的话，r3 模块叫 `*_r3.py`、`adapters/__init__.py` 翻面到 r3 re-export、用户面 `AnthropicAdapter` 这个名字永远稳定。模块文件名是工程实现细节版本化的承载体，类名是对外契约——两层分开。

### 测试 500 → 496：audit 第 3.3 节漏判的那 4 条

git rm 之后跑 pytest，4 条挂——audit 第 3.3 节漏判的一处。

`tests/agent/test_question_processor.py::TestAgentLoopIntegration` 一组 4 条 integration 测试：`long_question_triggers` / `short_question_skips` / `env_flag_disables` / `processor_failure_does_not_block`。这组测试 audit 写"保留全部 question_processor 测试"——但实际上 `TestAgentLoopIntegration` 这个 class 用 Anthropic `content_blocks` 形态 stub 驱动 `bookscope.agent.AgentLoop`，r2 切换后 stub 形态不匹配。同文件的 `TestProcessedQuestionDataclass` / `TestProcessQuestionHappyPath` / `TestProcessQuestionFallback` / `TestQuestionProcessedEvent` / `TestBuildSystemAddendum` / `TestParseProcessorJsonFallbacks` 6 类 unit 覆盖 `process_question` 自身全部行为，不用 stub，不挂。

audit 把 `test_question_processor.py` 当通用层，没识别其内部一组 `TestAgentLoopIntegration` class 是 r1 integration——这是 audit 第二处局部漏判（第一处是 ③ 的 import 链漏审）。

修法跟 Sprint 7 删 r1 测试主旋律一致——整组 4 条删 + 配套 `_FakeSearchBackend` / `_FakeChapterBackend` / `_FakeCharactersBackend` / `_final_json_block` / `_collect_callback` 5 个 fixture 一起删。r2 形态 integration 测试进 follow-up 单独补，不强塞进 Sprint 7。

修完测试 500 → 496/496 全绿。

净减 4 不是"r2 不行多挂 4 条"——是 audit 漏判被发现 + 范围孤立 + 同 root cause + 修复路径明确，按副管理常规工程决策原地修不雪崩。撤回条件未命中：r2 套零 ImportError / 零 NameError；唯一 4 条失败定位为 audit §3.3 漏判。

Sprint 7 实质工作收官——r1 runtime 物理消失、r1 protocol 用户面切断、import 链零残留。代际切换 ADR-007 从 5 月 13 日草案签字到 5 月 15 日 git rm 落地，整整 3 天。

回头看这 3 天的关键节点不是 git rm 本身，是中间那两次"签字 ≠ 立刻执行"的工程姿态——第三次签字写明"audit 回来分步推"作约束，audit 漏审 import 链被守住后写撤回判断回 STATE，作者批 take A 拆 ③a / ③b，③a 把 25 个 symbol 搬到 `_internal/` 让 ③b 干净 git rm。

5 个月之前 ADR-003 选最小工作量的双向 adapter 路径埋的账，5 个月之后 ADR-007 这套姿态彻底还清。比"删掉 1693 行代码"更值得记的是——**代际级删除是分步可撤回的工程操作，不是一次性 rm -rf**。下次 BookScope 再有 r2 → r3 这种代际级切换，这套"草案签字 → 实施 → 数据验证 → 默认翻面 → 解耦准备 → 真删"6 步节奏可以原样复制。

---

*本章 starter 到此为止。第八节落完之后整章草稿在第 35 轮第十四波收尾。定稿等 r2 在线上稳定运行一段时间之后的里程碑点，作者亲笔润色。*
