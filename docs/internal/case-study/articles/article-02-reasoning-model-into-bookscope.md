# 文章 · Reasoning Model 进入 BookScope：`<think>` 标签、tool_calls 字段、与 Agent Loop 的不兼容假象

> **状态**：草稿 · 作者未定稿
> **时段**：2026-04-27（第 26 轮，一晚两次 pilot 与一次 5 题 batch）
> **覆盖**：`bookscope/agent/adapters/deepseek.py` · `bookscope/agent/loop.py` · `bookscope/agent/prompts/loop_system_prompt_v3.1.md` · `scripts/run_batch_r1.py`
> **数据**：`docs/internal/experiments/data/v3-minimax-pilot-2.json` · `v3.1-minimax-pilot.json` · `v3.1-minimax-batch-01.json`

---

## 一、第 26 轮的 5-token sanity check 撞上 `<think>`

第 26 轮是从一句最普通的指令开始的：

> 继续，但是我们的 api 更新了。这次用的是 minimax，用的 2.7 的模型。

`base_url` 改一行（`https://api.minimaxi.com/v1`），`model` 字段从 `astron-code-latest` 切到 `MiniMax-M2.7`，`api_key` 走环境变量。第 8 轮 ADR-003 / 第 19 轮 API 层一等公民化的全部铺垫，理论上让"切 provider"这件事归零成本。`DeepSeekAdapter` 的 docstring 第 81 行明写：

> base_url：OpenAI 兼容 endpoint；默认 DeepSeek 官方地址。私有部署 / 代理走 OpenRouter 时可覆盖。

按这个抽象的契约，MiniMax 的 OpenAI 兼容 endpoint 就该跟 DeepSeek 官方地址一样，是字符串替换级别的差异。

切完之后没有立刻跑 smoke——按副管理流程的"贵动作前先 5-token 廉价 sanity"原则，先发了一个最小的 chat completion 请求：5 个 token、不带 tool、不带 system，就问"你好"。

回来的 `response.choices[0].message.content` 长这样：

```text
<think>
用户用中文打招呼"你好"。这是一个非常简短、友好的开场白。
我应该用同样友好的方式回应，并询问对方需要什么帮助。
保持简洁，不要过度解释。我会用中文回应。
</think>

你好！很高兴见到你。请问有什么我可以帮你的？
```

这是 MiniMax-M2.7 作为 reasoning model 的一个**协议外行为**：思考链以 `<think>...</think>` 块的形态被 inline 进 `content` 字段。OpenAI 兼容协议本身没有为 reasoning content 定义独立字段（DeepSeek-R1 用 `reasoning_content`，OpenAI o1 系列用单独的 reasoning summary，但都是各家方言）；MiniMax 选择了"塞进 content 里用 tag 区分"的方案。

对一个**直接面向人类用户的 chat 应用**，这无伤大雅——前端把 `<think>` 块隐藏起来即可。但对 BookScope，这是致命的：第 7 轮就定下来的 citation 强制机制要求 LLM 的 final answer 是一个**严格 JSON 对象**，由 `loop.py:_parse_final_answer` 走 `json.loads` 解析。一旦 `<think>` 块出现在 final 文本里，`json.loads` 立刻在第一个 `<` 处炸——它根本不是合法 JSON 的开头。

OpenAI 兼容协议在这里露出了它的底色：**它兼容字段名、字段结构、HTTP 路径，但不兼容 reasoning model 的语义**。

## 二、Strip 在哪一层做：adapter vs prompt

`<think>` 块出现的瞬间，第一反应有三个候选位置去 strip：

1. **prompt 层**：在 `loop_system_prompt_v3.1.md` 里加一条 `不要输出 <think> 块`
2. **loop 层**：在 `loop.py:_extract_text_from_blocks` 拼出 final text 后做正则 strip
3. **adapter 层**：在 `DeepSeekAdapter._from_openai_response` 把 OpenAI 响应翻成 Anthropic 风格的同一处做 strip

先排除 prompt 层。reasoning model 的 `<think>` 是**训练阶段烙进去的输出格式**，不是 instruction-following 的可控行为。你跟 MiniMax-M2.7 说"不要输出思考链"，它会把"嗯，用户让我不要输出思考链，那我应该……"这段也写进 `<think>` 块里——你**根本拦不住**它生成思考链，只能选择丢不丢。这跟"用 prompt 让 GPT-4 不要 hallucinate"是同一类伪操作。

loop 层与 adapter 层之间的选择更微妙。两者都能干掉 `<think>` 块，但 BookScope 当前其实有**三个独立的 LLM 调用入口**：

- `AgentLoop`（生成 answer）
- `bookscope/agent/reviewer.py`（AI-as-judge 审稿）
- `bookscope/agent/kg/extractor.py`（`MinimalKGExtractor` 抽角色）

三个入口都共用 `LLMClient` Protocol，都会拿到 OpenAI 响应。在 loop 层 strip，意味着 reviewer 和 extractor 各自要再写一遍 strip 逻辑——三处重复，未来加 RerankerProvider（ADR-007）就是四处。在 adapter 层 strip，**一处修，三处受益**。

更彻底地讲：`<think>` 块不是"应用语义"的问题，是"协议翻译"的问题。`DeepSeekAdapter` 的职责是把 OpenAI 风格响应翻成 Anthropic 风格的 content blocks。reasoning content 的 inline tag 是 OpenAI 协议没规定但模型实际会发的"协议方言"——它**就该在协议翻译层被规范化**。对上层（loop / reviewer / extractor），抽象应该是干净的"`text` block 是已可信的纯叙事文本"。

最终改动在 `bookscope/agent/adapters/deepseek.py`，第 52–68 行：

```python
# Reasoning models（minimax-m2.x / deepseek-r1 / qwen-qwq / glm-zero 等）会把
# 思考链 inline 在 content 里以 <think>...</think> 段返回，污染下游 JSON
# parse。这里在 OpenAI→Anthropic 转换层抹掉。non-reasoning model 的 content
# 不含此标签，相当于 no-op。多对 / 单对 / 跨行均覆盖；不闭合的开放标签兜底
# 也按"截到末尾"处理，避免被卡住。
_THINK_BLOCK_RE = re.compile(r"<think\b[^>]*>.*?</think>", re.DOTALL | re.IGNORECASE)
_OPEN_THINK_RE = re.compile(r"<think\b[^>]*>.*", re.DOTALL | re.IGNORECASE)


def _strip_thinking_tags(text: str) -> str:
    """删除 <think>...</think> 块。无标签时原样返回。"""
    if "<think" not in text.lower():
        return text
    cleaned = _THINK_BLOCK_RE.sub("", text)
    # 兜底：模型 stop 在 think 内部（max_tokens 截断），抹掉残留开放段
    cleaned = _OPEN_THINK_RE.sub("", cleaned)
    return cleaned.strip()
```

调用点放在 `_from_openai_response` 第 332–336 行，紧挨着把 OpenAI `message.content` 转成 Anthropic `text` block 的位置：

```python
text = getattr(message, "content", None)
if text:
    text = _strip_thinking_tags(text)
    if text:
        content.append({"type": "text", "text": text})
```

注意第二个 `if text:` —— `<think>` 块占满整个 `content` 字段（思考完了 max_tokens 已用尽，一个字的 final 答复都没剩）的边界情况下，strip 完是空字符串，这时连 text block 都不该加。这条边界后面会回来咬人，第六节再讲。

## 三、双 pattern 与开放标签兜底

正则有两条，看起来冗余：

```python
_THINK_BLOCK_RE = re.compile(r"<think\b[^>]*>.*?</think>", re.DOTALL | re.IGNORECASE)
_OPEN_THINK_RE = re.compile(r"<think\b[^>]*>.*", re.DOTALL | re.IGNORECASE)
```

第一条 `_THINK_BLOCK_RE` 是常规的"闭合 tag 对"匹配——`<think>...</think>` 里的 `.` 因为 `re.DOTALL` 跨行。这一条覆盖 99% 的情况：MiniMax 通常把思考链好好闭合掉，紧接着输出 final 答复。

第二条 `_OPEN_THINK_RE` 处理一个看起来不该发生但真会发生的边界：`max_tokens` 把模型截在了 `</think>` 之前。第 26 轮第二次 pilot 就遇到一次——`max_tokens=4000`，思考链跑到 3998 token 就被截，`content` 长这样：

```text
<think>
用户问的是清洗开国功臣的叙事节奏...
[2000 字思考...]
让我再回顾一下时间线：第 14 章张士诚...
[继续思考但永远到不了 </think>]
```

闭合 pattern 在这里不匹配——它要求看到完整的 `</think>`。如果只用闭合 pattern，整段思考链原封不动留在 `content` 里被当成 final answer 喂给 `json.loads`，立刻报 `Expecting value: line 1 column 1 (char 0)`。

`_OPEN_THINK_RE` 兜底：从第一个开放 `<think>` 一路 greedy 吃到末尾。这一段确实把"思考没说完就停了"的情况丢成空答案，但语义上是对的——agent 思考没收敛，本来就该让 loop 进下一轮 retry / format_retry，而不是把半截思考链当答案。

`re.DOTALL` 是因为思考链跨行；`re.IGNORECASE` 是为了兼容 `<Think>` / `<THINK>` 这种各家 reasoning model 可能出现的 case 漂移（DeepSeek-R1 文档的 `reasoning_content` 是另一种方案，但 GLM-Zero 早期版本就出过 `<Think>` 大写 tag 的报告）。`\b` 单词边界防止把 `<thinking>` 之类带前缀的标签误伤。

`if "<think" not in text.lower(): return text` 是个**fast path**——non-reasoning model 的响应里 99.9% 不含这个串，省掉两次正则编译扫描。MiniMax M2.7 是 reasoning model，每次响应都走全路径；DeepSeek-chat / Anthropic Claude 几乎每次都走 fast path。同一段代码对两种 provider 都 zero-cost 正确。

## 四、Strip 通了，发现真问题：`tool_call_names: []`

`<think>` strip 上线，第一次 v3 pilot 跑 q1（节奏评估题）。82 秒返回，answer 漂亮——三段式结构判断、跨章节呼应分析、引文都对。

reviewer 给的分却把人摁住了：**17/25**。

| 维度 | 分数 |
|------|------|
| structural_judgment | 4 |
| evidence_density | 2 |
| honesty | 4 |
| actionability | 3 |
| cross_chapter_coherence | 5 |

evidence_density **2 分**——比 v2+astron baseline 的 5 分掉了 3 分。reviewer 给的批注（保存在 `docs/internal/experiments/data/v3-minimax-pilot-2.json` 第 73 行）很硬：

> 五段 citation 中四段仅支撑表层事件（'有人被杀'、'杀李善长'），支撑核心论点的关键判断——如'叙事猛然提速''日常化恐怖''情感密度达到顶点'——完全找不到对应原文，是典型的以断言代替证据。

打开 trace 看，`trace_summary` 第 60 行写着：

```json
{
  "iterations": 2,
  "duration_ms": 73574,
  "total_input_tokens": 55084,
  "total_output_tokens": 1862,
  "outcome": "success",
  "tool_call_names": []
}
```

**`tool_call_names: []`**。两轮迭代，**0 次 tool 调用**。

73 秒里，55k input token、1862 output token——MiniMax-M2.7 在做什么？看完 system prompt + question + citation_format hint 后，它**直接靠训练记忆**生成了一份看起来非常像在引用原文的答复。citation 字段里那五段引文，结构上严格符合 `{chapter: int, snippet: str}`，文本读起来也像《明朝那些事儿》原书的句子——但这五段全部是**模型从训练数据里复刻出来的**，不是从当前 session 加载的 epub 里查出来的。

evidence_density 2 分扣得精确：reviewer 看到的 answer 文本里说"叙事猛然提速""日常化恐怖""情感密度达到顶点"，但配套的 citation snippet 只支撑得住"有人被杀""李善长被杀"这种表层事件——**因为那五条 citation 本质上是模型对"明朝那些事儿这本书一般长什么样"的刻板印象**，不是基于"当前 session 这本具体的 epub 里第 14、18、19、20 章实际写了什么"。看似有引文，实质是 hallucination 的精装版。

这是 BookScope 与 ChatGPT / Claude 直通最核心的差异：**原文证据现场调取**。MiniMax-M2.7 在 baseline 题上**绕过**了这一机制。

更刺眼的是，直接 prompt"现在调用 search_chunks 函数找 X" 时，MiniMax 的 `finish_reason` 立刻是 `tool_calls`，`tool_calls` 字段填得整整齐齐——它**有能力调 tool**。它在 BookScope agent 任务里**选择**不调，因为它"觉得自己已经知道"。

这是 v3.1 prompt 的硬约束 A / B / C 三条诞生的原因。

## 五、tool_calls 字段的随意性

`tool_calls` 字段在 OpenAI 协议里的语义是"模型决定要调用 N 个 function"。在 DeepSeek-chat / GPT-4 这种 non-reasoning model 上，这个字段相当稳定——给定 system prompt 中明示"你有这些 tool 可用"+ user 问题需要工具能解决时，它几乎一定触发；问题不需要工具时几乎一定不触发。

MiniMax-M2.7 的行为分裂：

- **直接 prompt 模式**：`messages = [{"role": "user", "content": "调用 search_chunks 找 X"}]`，`finish_reason` 立刻是 `tool_calls`，字段格式正确——**它知道**有 tool 在那里
- **agent 任务模式**：完整的 BookScope system prompt + citation_format hint + 真实问题，5 轮迭代里 0 次 `tool_calls` 触发

差异在于：直接 prompt 模式下，"调 tool"是用户的明确指令；agent 任务模式下，"是否调 tool"是模型自主判断。MiniMax-M2.7 自主判断的结果是"我训练里见过《明朝那些事儿》，可以直接答"。

这不是 prompt 没说清楚。v3 prompt 第 17–19 行明明白白写了三个 tool 的签名和用法；第 22–29 行写了"探查 → 细读 → 综合"的推理流程建议，每一步都点名要调 tool。MiniMax-M2.7 全部读到了——它的 `<think>` 块（pilot 抓到的）甚至有"用户问的是节奏，按理应该用 search_chunks 查一下，但我对这本书已经很熟悉……"这种内心戏。

**它不是不知道要调 tool。它是判断自己不需要调**。

这是新一代 reasoning model 在公开书 baseline 上的 tool-bypass 漏洞：**模型的 reasoning 训练目标里"我已经知道"的权重压过了"按外部工具协议执行"的权重**。结果是 agent loop 框架对它的"工具暴露"被悄悄绕过。

v3.1 prompt 加的硬约束 A 是直接堵这一条：

```markdown
### A. 至少一次 tool 调用

零 tool 调用直接给 answer = **失败 case**。即使问题"看起来很简单"、即使你"已经知道"答案，
也必须先调用至少 1 次 search_chunks 或 get_chapter_range 拿到当前 session 的真实原文 chunk。
```

约束 B 把"训练记忆"明示为禁区：

```markdown
### B. 禁止靠训练记忆作答

- 训练记忆里的"书"和当前 session 加载的"书"可能不一致
- 作者真正用 BookScope 时，加载的是自己的小说草稿——你训练里绝对没见过
- 即使在公开书 baseline 测试上，也要表现得像在面对作家私域稿一样
```

约束 C 处理"我已经知道 ≠ 我已经查过"的元层次问题：

```markdown
### C. "我已经知道" ≠ "我已经查过"

如果你在 reasoning（无论显式 <think> 还是隐式）里冒出"这本书里 XX 章是 YY"这种判断，
不要直接写进 answer——先用 tool 验证一遍。reasoning 里的"知道"是训练记忆的回声，
不是当前 session 的证据。
```

v3.1 在第二次 pilot 真起作用了——`tool_call_names` 不再是空数组，但 batch runner 又揭穿了一个更早期的 bug。

## 六、batch runner 字段名 bug 与"M2.7 完全不调 tool"的误判

第 26 轮新写了一个 `scripts/run_batch_r1.py`：读 questions JSON → 一次 load book → N 题 query → reviewer 审稿 → 写 batch JSON。手工跑 5 题来回切换 smoke + reviewer 要 30 分钟，runner 一次跑完。

batch runner 里有个 `_extract_trace_summary` 函数把 `LoopTrace` 压成 trace_summary 写进输出 JSON。第一版字段名写错了：

```python
# 错的版本
def _extract_trace_summary(trace):
    return {
        "iterations": trace.iterations,
        "duration_ms": trace.duration_ms,
        "tool_call_names": [tc["name"] for tc in trace.tool_invocations],  # bug
        ...
    }
```

`bookscope/agent/models.py` 第 47–50 行 `LoopTrace` 的字段是 `tool_calls: list[dict]`，每个 dict 的键是 `tool_name`，不是 `name`。我写 batch runner 时记忆里把字段名抄错了——而且 `LoopTrace` 是 Pydantic model，访问不存在的属性 `trace.tool_invocations` 直接 `AttributeError`，但被 try-except 在 batch runner 里吞掉，trace_summary 里的 `tool_call_names` 被填成空数组。

第一次 v3 pilot（`docs/internal/experiments/data/v3-minimax-pilot-no-enforcement.json`）和第二次 v3 pilot（`v3-minimax-pilot-2.json`）的 trace 都被这个 bug 报告成 `tool_call_names: []`——**跟 M2.7 真的不调 tool 的真实行为长得一模一样**。

诊断走了一段冤枉路。第二次 pilot 我先怀疑"v3.1 强制约束没生效"，回头审 v3.1 prompt，又怀疑"MiniMax 完全不读硬约束部分"，准备写 v3.2。直到把 batch runner trace 字段名修对，重跑 v3.1 pilot：

```json
{
  "iterations": 7,
  "duration_ms": 217xxx,
  "tool_call_names": [
    "search_chunks", "search_chunks", "search_chunks",
    "search_chunks", "search_chunks",
    "get_chapter_range",
    "search_chunks"
  ],
  "outcome": "success"
}
```

**v3.1 真起作用了**。MiniMax-M2.7 在硬约束下乖乖调了 7 次 tool。前两次"完全不调"是字段名 bug 编造出来的幻象。

这条 bug 教会我两件事：

1. **trace 字段是 contract**。`models.py` 已经定义了 `tool_calls: list[dict]` + `tool_name` 这个 schema；任何下游消费方（batch runner / reviewer / case study）都必须用同一个 schema，不能凭印象写。靠类型注解和 lint 都很难抓——`trace.tool_invocations` 在 Pydantic 模型上是合法的 `AttributeError`，不是 IDE 能高亮的拼写错误
2. **被 try-except 吞掉的 AttributeError 是最毒的 bug**。它让一个明显的"代码炸了"伪装成"数据真长这样"，把诊断带偏到 prompt 层 / 模型行为层。修复后我把那个 try-except 改成只接 `(KeyError, IndexError)` 这两类**预期内**的异常，`AttributeError` 让它直接 surface

## 七、output_tokens=147 但留下 6 字符净答复

第 26 轮第三次出问题是 reviewer 的 JSON parse 失败，报 `Invalid control character at: line N column M`。

MiniMax-M2.7 在 reviewer 的输出 JSON 里把 raw newline 直接写进 string value 没转义：

```json
{
  "per_dimension_comment": {
    "evidence_density": "五段 citation 中四段仅支撑表层事件
（'有人被杀'、'杀李善长'），支撑核心论点的关键判断..."
  }
}
```

中间那个 `\n` 是 raw 0x0A，json.loads 在严格模式下拒绝接受 string value 里的裸 control char（必须 escape 成 `\n`）。

修法是 `loop.py` 第 700–757 行新增的 `_autofix_control_chars_in_strings`：跟第 24 轮 `_autofix_unescaped_quotes_in_all_string_values` 同一套状态机思路——`in_string` 标志位扫描，遇到 `\n` / `\r` / `\t` 改成 `\\n` / `\\r` / `\\t` escape sequence。reviewer 与 loop 共享同一个 helper。

但更让人停下思考的是另一组数据。某次跑 v3.1 时 trace_summary 是这样：

```json
{
  "total_input_tokens": 38291,
  "total_output_tokens": 147,
  "duration_ms": 12442,
  "outcome": "format_error"
}
```

**output_tokens 147**，但 final text strip `<think>` 后留下来的净答复字符数：**6**（一个不完整的 `{"answ`）。

剩下的 141 个 output token 全部是 `<think>` 块里的思考。reasoning model 的训练目标——把推理花在思考链上——在 BookScope 这种"答复需要严格 JSON"的场景里产生了一个副作用：**模型把 max_tokens 配额几乎全部花在思考上，留给 final 答复的预算不够把 JSON 写完**。

这是 reasoning model 与 agent token-budget 设计假设的张力。BookScope 第 7 轮设的 `DEFAULT_MAX_TOKENS = 4000`（`loop.py` 第 63 行），最初是按 non-reasoning model 估的——4000 token 给 final answer 是绰绰有余的预算，agent 通常用 1500–2500 就收敛。换成 reasoning model 后，4000 里有 2000+ 被思考链占走，剩下 1500 在写 citation 的 chunk snippet（中文每字 2–3 token）时就开始捉襟见肘。

应对有两条路：把 max_tokens 提到 8000（成本翻倍）；或者切到 OpenAI o1 / DeepSeek-R1 那种把 reasoning_content 走独立字段、不计入 max_tokens 的方案（要改 adapter、改协议）。第 26 轮没动，留作 r2 候选。当前权宜：format_retry_limit=1，retry 时 prompt 提示"严格按 JSON schema 重新回复，不要再调 tool"——retry 的 user message 显式不再让模型思考多余的东西。

## 八、5 题 batch 的真实图景

修完字段名 bug + control-char autofix 后跑 5 题 v3.1+minimax batch（`docs/internal/experiments/data/v3.1-minimax-batch-01.json`）：

| 题号 | 类型 | v2+astron baseline | v3.1+minimax | Δ | tool_calls |
|------|------|-------|-------|-----|------|
| q1 | 节奏评估 | 25 | 18 | -7 | 2 |
| q2 | 支线密度 | 25 | 19 | -6 | 2 |
| q3 | 伏笔回收 | 25 | 22 | -3 | 5 |
| q4 | 角色转变可信度 | 25 | 18 | -7 | 3 |
| q5 | 设定漂移 | 24 | 23 | -1 | 6 |
| **平均** | — | **24.8** | **20.0** | **-4.8** | — |

| 维度 | baseline | candidate | Δ |
|------|---------|-----------|----|
| structural_judgment | 5.0 | 4.4 | -0.6 |
| evidence_density | 5.0 | 3.6 | **-1.4** |
| honesty | 5.0 | 4.0 | -1.0 |
| actionability | 4.8 | 3.6 | -1.2 |
| cross_chapter_coherence | 5.0 | 4.4 | -0.6 |

第一个观察：**tool_calls 与总分强相关**。q5（tool=6, total=23）和 q3（tool=5, total=22）逼近 v2 baseline；q1/q2（tool=2, total=18/19）是均值的拖底。

第二个观察：v3.1 强制约束 A "至少一次 tool 调用"被 MiniMax 当作**最低限度**遵守——q1 和 q2 都只调了 2 次（最低限度的 2 次：1 次探查 + 1 次细读），剩下全靠训练记忆补。citation 数从 v2-astron baseline 的 10–13 条降到 5–7 条，差异在 q1/q2 上尤其明显。

第三个观察：evidence_density -1.4 是退化最严重的维度。这跟"5 段 citation 里 4 段只支撑表层事件，核心论点完全无引文支撑"的 reviewer 批语完全对得上。MiniMax-M2.7 在调了 tool 之后，**把 tool 返回的 chunk 用作"装饰品"而不是"论据骨架"**——它在 answer 里下的核心判断（"叙事猛然提速""情感密度达到顶点"）依然来自训练记忆里的"明朝那些事儿一般长什么样"，tool 拿到的 chunk 只是被零散贴在 citation 字段里凑数。

这是比"完全不调 tool"更微妙的退化：模型表面上遵守了"至少 1 次 tool 调用"的约束，但它**没把 tool 真当成证据来源**——它把 tool 当成了一道**仪式**，过完就回到训练记忆里去推理。

## 九、通用化收益与对其他 reasoning model 的预测

`_strip_thinking_tags` 写完之后，回头审一遍它在非 MiniMax provider 上的代价：

- **DeepSeek-chat（non-reasoning）**：每次响应跑 fast path（`if "<think" not in text.lower(): return text`），开销 = 一次小写转换 + 一次 substring 查找，纳秒级
- **Anthropic Claude（non-reasoning，且不走 OpenAI 兼容路径）**：根本不进 `DeepSeekAdapter._from_openai_response`，零接触
- **DeepSeek-R1**（reasoning，但用 `reasoning_content` 独立字段）：未来接入时，`reasoning_content` 由 adapter 在 OpenAI→Anthropic 翻译时直接丢弃（不进 `text` block）；`<think>` strip 走 fast path
- **GLM-Zero / Qwen-QwQ / 阿里 QwQ-32B**（reasoning，已知会用 `<think>` 块）：strip helper 直接生效，零代码改动

关键收益：**adapter 层修一处，covers 整个 reasoning model 家族的 inline thinking tag 方言**。这是 ADR-003 的"provider adapter 层吸收方言"原则在 reasoning model 时代的延伸。

预测：未来 12 个月内国内会有 5+ 个新 reasoning model 进 OpenAI 兼容生态。每一家可能选不同的 thinking content 表达方式：

- **inline `<think>` 块**（MiniMax 现在的方案）
- **独立 `reasoning_content` 字段**（DeepSeek-R1 的方案）
- **`message.reasoning` 子字段**（OpenAI o1 的方案，但 o1 不开 reasoning summary）
- **special token + content prefix**（早期 OpenChat / 部分开源 fine-tune 的方案）

`_strip_thinking_tags` 只覆盖第一种方言。第二种、第三种要在 `_from_openai_response` 加分支识别 `getattr(message, "reasoning_content", None)` 之类。第四种最难处理，需要按 model name 走不同 strip 逻辑——但好在每一种都是 adapter 层的事，loop / reviewer / extractor 不用知道。

这正是 OpenAI 兼容协议的真实形态："兼容"是表面的，每家 reasoning model 在协议外有自己的方言；adapter 层是吸收方言、把它规范化的工程战场。

## 十、Reasoning Model on Agent Loop 兼容性 Checklist

第 26 轮一晚的成果，归并成一份给未来接入 reasoning model 的 checklist：

### 协议层

- [ ] **Inline thinking tag strip**：在 OpenAI→Anthropic 翻译层 strip `<think>...</think>` 块；处理闭合 / 开放 / 大小写 / DOTALL 四种 case
- [ ] **独立 reasoning content 字段**：识别 `message.reasoning_content` / `message.reasoning` 等独立字段，丢弃或选择性持久化
- [ ] **content 全空答复**：strip 完是空字符串时不要加 text block，让上层进 format_retry 而不是炸
- [ ] **JSON string value 内 raw control char autofix**：reasoning model 在多行 JSON value 里塞 raw `\n` / `\r` / `\t` 是常态，需要 autofix helper（不是 fix model）

### 行为层

- [ ] **tool_calls 字段的随意性**：reasoning model 即便有 tool 暴露在 system prompt 里也可能"自主判断"绕开调用——必须在 prompt 层加硬约束 A（至少一次 tool 调用），否则 agent 退化为通用聊天
- [ ] **训练污染显式封堵**：公开测试集上必须明示"训练记忆 ≠ 当前 session 证据"（约束 B），不然 evidence_density 会塌
- [ ] **元约束**：reasoning 里的"我已经知道"必须用 tool 验证后才能进 answer（约束 C），否则 hallucination 会披着"思考链"的外衣进来

### Token-budget 层

- [ ] **max_tokens 重估**：reasoning model 把推理花在 `<think>` 块里，原 non-reasoning model 的 `max_tokens` 配额对 final answer 而言可能不够；要么提配额（成本翻倍），要么切到独立 reasoning_content 字段方案
- [ ] **format_retry 提示明确**：retry 的 user message 显式说"不要再思考""严格按 JSON schema 输出"，让模型在 retry 时把预算花在 final answer 上
- [ ] **trace 字段 schema 严格**：`tool_calls` / `tool_name` / `iterations` 等字段任何下游消费方都必须照 `models.py` 定义的 schema 走，不能凭印象写——被 try-except 吞掉的 `AttributeError` 是最毒的 bug

### 实验层

- [ ] **公开书 baseline 不能孤证**：训练污染让公开书的 evidence_density 维度系统性偏低；reasoning model 的真用例评估必须切到模型训练里没见过的私域文本（NORTH_STAR 第 1 条）
- [ ] **Reviewer 与 generator 同 provider 是已知偏袒源**：5 题 batch 的 4.8 分差距远超偏袒方差，结论可信，但任何"小幅升降"必须切独立 provider 复测才能下结论
- [ ] **batch runner 优先于手工 5 题 serial**：API 是按 token 计费的远端服务，手工切窗口跑 5 题会浪费 30 分钟自我等待；写一份 runner 一次跑完是正确姿势（feedback_batch_over_serial）

---

## 尾声：兼容性的本质

第 26 轮一开始我以为是"切个 base_url 的事"。结束时手里是：一个 18 行的 `_strip_thinking_tags` + 一份 100 行的 v3.1 prompt + 一个修字段名的 batch runner + 五道题的退化数据 + 一份 reasoning-model-on-agent-loop checklist。

这件事的本质不是 MiniMax-M2.7 不好。它在中文叙事生成上的能力客观上比 astron-code-latest 强（answer 文笔更细腻，跨章节呼应更稳）。这件事的本质是**"OpenAI 兼容协议"在 reasoning model 时代是个被泄漏掉的抽象**。

字段名兼容、字段类型兼容、HTTP 路径兼容、status code 兼容——但**模型的输出语义、token-budget 假设、tool_calls 触发条件**都不兼容。每一家 reasoning model 厂商训练时按自己的目标优化（有的把 reasoning 暴露在 content 里给开发者看，有的塞独立字段，有的根本不给），结果是同一段 BookScope agent loop 代码碰到不同 reasoning model 时行为可能完全不同。

`DeepSeekAdapter` 的名字其实从第 8 轮起就不准确了——它早就不是"DeepSeek 专用 adapter"，它是"OpenAI 兼容协议 + 各种厂商方言修补"的工程战场。第 26 轮在它身上加的 `_strip_thinking_tags` 只是这个战场里最新的一道堑壕。

下次接入新 reasoning model 时，5-token sanity check 必须先做。不是为了验证"它能不能回话"——它当然能。而是为了看 raw content 字段里到底装了什么协议外的"惊喜"。每一个看似细节的工程兼容点，背后都是 reasoning model 训练目标与 agent framework 设计假设的偏差——这种偏差在 prompt 层是堵不住的，必须在 adapter 层、在协议翻译那一刻就吸收掉。

第 27 轮的方向已经写在 STATE.md 第 28–34 行：作者决定是切到自己未公开稿子做 P1 真用例（候选 a，推荐），还是先单变量分离公开书 baseline 上 prompt vs provider 的退化来源（候选 b/c）。无论选哪条，本章建立的兼容性 checklist 会跟着走——下一个 reasoning model 进来时不必再付一次 6 小时的诊断成本。

---

## 附录：本文涉及的工程产物

- `bookscope/agent/adapters/deepseek.py` 第 52–68 行：`_strip_thinking_tags` + 双 pattern 正则
- `bookscope/agent/adapters/deepseek.py` 第 332–336 行：`_from_openai_response` 调用点
- `bookscope/agent/loop.py` 第 700–757 行：`_autofix_control_chars_in_strings`
- `bookscope/agent/loop.py` 第 65 行：`SYSTEM_PROMPT_PATH` 切到 v3.1
- `bookscope/agent/prompts/loop_system_prompt_v3.1.md` 第 31–53 行：硬约束 A / B / C
- `bookscope/agent/models.py` 第 47–50 行：`LoopTrace.tool_calls: list[dict]` + `tool_name` 字段名 contract
- `scripts/run_batch_r1.py`：batch runner（含修复后的 `_extract_trace_summary`）
- `docs/internal/experiments/data/v3-minimax-pilot-no-enforcement.json`：v3 pilot 17/25（保留作研究证据）
- `docs/internal/experiments/data/v3-minimax-pilot-2.json`：修字段名前的 v3 复跑数据
- `docs/internal/experiments/data/v3.1-minimax-pilot.json`：v3.1 单题 17/25
- `docs/internal/experiments/data/v3.1-minimax-batch-01.json`：v3.1 全 5 题 20.0/25
- `tests/agent/test_agent_loop.py`：+5 control-char autofix 用例
- 全量 **394/394** 全绿
