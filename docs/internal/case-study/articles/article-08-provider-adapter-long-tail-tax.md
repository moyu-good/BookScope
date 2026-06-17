# Provider Adapter 的长尾税收：OpenAI 兼容假象底下的真实碎片

> **状态**：草稿 · 作者未定稿
>
> slug：`article-08-provider-adapter-long-tail-tax`
> 视角：架构反思
> 关联代际：r1-agent-loop
> 关联 ADR：ADR-002 v2、ADR-003

---

## 一、引子：为什么我会盯着这层四百行的 adapter 写一万字

BookScope 的 `bookscope/agent/adapters/` 目录非常小。三个文件加起来不到 600 行：`base.py` 一个 Protocol，`deepseek.py` 一个 adapter，`anthropic.py` 一个 adapter。AgentLoop 主循环（`bookscope/agent/loop.py`）有 800 行左右，但 adapter 层显著比它瘦，看起来像那种"画一次架构图就再也不用改的稳定基础设施"。

事实正好相反。

这一层是我整个 r1 代际改动最频繁的代码区域之一。从 ADR-002 v1 到 v2 是一次方向级翻修；DeepSeek 接入只是开始；第 16 轮接入讯飞星辰 astron-code-latest 时我在 loop 里加了一道 `_autofix_unescaped_answer_quotes`；第 19 轮把 astron 一等公民化又加了 13 个新单测；第 26 轮接 MiniMax M2.7 时又往 DeepSeekAdapter 里塞了一个 `_strip_thinking_tags`，并在 loop 里再加一道 `_autofix_control_chars_in_strings`。每一次都不是因为 Protocol 设计不行，而是因为某家 provider 在"OpenAI 兼容"招牌底下露出了一处自己的脾气。

这不是个例事故，是结构性现象。我把这种现象命名为 **provider adapter 的长尾税收**：你以为接入是一次性付清的 SDK 集成成本，实际上是按 provider 数 × 实战暴露面持续征收的零碎税。每一处税额不大，单独看都像"小 patch"；累积起来已经形成一个 4 道 autofix + 1 个 strip helper 的技术债资产负债表，而且仍在增长。

这篇文章想做三件事。

第一，把决策史摆清楚——为什么 ADR-002 v1 锁了 Anthropic、v2 又改成 adapter 层，这个翻转里我最早误判了什么。

第二，把每家 provider 的 patch 清单拉出来——astron 的裸引号、minimax 的 `<think>` 块和 control char，分别以什么形态出现、对应代码长什么样、单测怎么覆盖。

第三，反思——adapter 层抽象的真实价值到底是不是"统一所有 provider"？我现在的答案是不是。它的真实价值是"为每家碎片提供一个可定位的命名空间"。基于这个重新理解，我会在末尾给出一个 onboarding 标准化方案：未来再加一家 provider，先跑 `scripts/adapter_smoke_check.py` 走完 5-token sanity check + batch 跑 + reviewer 跑三个观察点，把碎片在第一天就抓出来，而不是等用户问到一道罕见题才暴露。

---

## 二、ADR-002 v1：当我以为锁住一家 provider 是务实选择

r1 的第一版决策是"锁定 Anthropic Sonnet 4.6 + 自建轻量 loop"。当时的判断很简单：tool use 我已经熟，Messages API 的 `content blocks + stop_reason + tool_use/tool_result` 结构刚好匹配我想要的 agent 内部状态机；从动手成本看，用 anthropic SDK 直接写 loop，三天就能跑出第一版 trace。

ADR-002 v1 的论证里我列了七条理由，每条都站得住——稳定性、tool use 成熟度、SDK 质量、可调试性、依赖体量、与 BookScope 长上下文需求的契合度、对开发节奏的友好度。当时我没把"国内优先"列进 NORTH_STAR 不变量。或者说，我当时还没意识到那是一条不变量，只是把它当一个偏好。

v1 写完那天下午，我重读 NORTH_STAR，发现自己已经在文档里写过：

> LLM provider 国内优先：首选 DeepSeek、GLM、Qwen、Kimi 等国内公开 LLM；Anthropic / OpenAI / Google 为备选。
>
> 所有 LLM 调用必须 provider-agnostic：用 duck-typed client 或 Protocol 抽象，禁止硬编码任一家 SDK；默认实现必须先接国内 adapter。

v1 的"锁定 Anthropic"和这两条不变量是直接冲突的。冲突不在于 Anthropic 本身有多差——它的 tool use 实战表现确实很稳——而在于"锁定"两个字本身就违反了"provider-agnostic"。BookScope 的定位是开源学习项目 + GitHub Star 收集，默认 provider 必须对国内学生友好，能让他们在不翻墙、不付国际信用卡、不用代理的情况下跑起来。锁 Anthropic 等于自动把目标用户群切掉一大半。

v1 作废，v2 重写。这里有一处我要承认的判断失误：**我在 v1 写 ADR 的时候，正处于"loop 已经跑通、第一批 trace 已经出来"的高兴劲里，把 Messages API 的实战顺手当成"这就是该选的 provider"**。这是典型的"动手成本驱动决策"——已经写出来的代码会反过来扭曲对架构的判断。第二天冷下来读 NORTH_STAR 才捡回来。

后来我把这件事写进了内部经验：**ADR 的第一稿，最少要在写完之后过 24 小时再读 NORTH_STAR 检查一遍**。架构决策不能在动手当下做。

---

## 三、ADR-002 v2 + ADR-003：从锁一家到 adapter 层抽象

v2 的核心改动是把"锁定 Anthropic"改成"DeepSeek 默认 + Anthropic 备选 + provider-agnostic adapter 层"。AgentLoop 主循环算法（message loop、tool dispatch、citation 强制、重试、trace）保持不动，变化只发生在 client 注入层与默认模型名。

ADR-002 v2 的实现要点 11、12 是我特别想引一下原文的：

> 11. AgentLoop 依赖 LLMClient Protocol 而非具体 SDK：类型标注统一使用 ADR-003 定义的 `LLMClient` Protocol；禁止在 loop.py 里 import 任何 provider SDK（`anthropic` / `openai` / `zhipuai` / `dashscope` 等都不得出现）。
>
> 12. adapter 层职责：把 provider 特定 API / 格式转换为 AgentLoop 内部统一形态。当前内部形态为 Anthropic tool_use block 风格（v1 遗留），`DeepSeekAdapter` 负责 OpenAI function calling ↔ Anthropic tool_use 的双向转换；`AnthropicAdapter` 接近 passthrough。

ADR-003 把抽象的具体形状定下来。Protocol 长这样：

```python
@runtime_checkable
class LLMClient(Protocol):
    def messages_create(
        self,
        *,
        model: str,
        system: str,
        tools: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        max_tokens: int,
    ) -> dict[str, Any]:
        ...
```

我想强调几个刻意的设计选择。

第一，**只一个方法**。我没有在 Protocol 上挂 `stream_messages_create`、`count_tokens`、`embed`、`moderation` 之类的副线方法。AgentLoop 当前只用同步一轮调用，所以 Protocol 也只暴露同步一轮调用。Protocol 不是"把 provider 能做的所有事都列出来"，是"把 loop 真的需要 provider 做的事最小化列出来"。任何 provider 上多余的能力都不该爬进 Protocol。

第二，**关键字参数**。`model` / `system` / `tools` / `messages` / `max_tokens` 全部是 keyword-only。没有位置参数歧义，新加 adapter 时不会因为参数顺序错了而隐式 bug。

第三，**返回 plain dict 而不是 Pydantic 模型**。理由很俗：loop 还要做 content-block 类型枚举，dict 访问最灵活；Pydantic 模型一旦定死字段，反而限制了 adapter 层在遇到 provider 形态变化时的应变空间。这个 trade-off 我接受类型安全弱一点，换 adapter 层韧性强一点。

第四，**返回 Anthropic 风格而不是 OpenAI 风格**。这是 v1 遗留的技术债——AgentLoop 内部形态本来就是 Anthropic 风格，切 DeepSeek 时我选择在 adapter 层做翻译，而不是重写 loop。后果是 `DeepSeekAdapter`（默认 provider）反而做更多格式转换，`AnthropicAdapter`（备选）几乎是 passthrough。这件事我在 ADR-003 里显式记成 "tech debt 声明"：

> 当 r2 或下一次架构扫描启动时，把 AgentLoop 内部形态从 Anthropic tool_use 切换为 OpenAI function calling，让 AnthropicAdapter 做反向转换，DeepSeekAdapter 变为 passthrough，去除 v1 遗留的双向转换负担。

写成 ADR 比放在 TODO 注释里更难被遗忘。这是我在 BookScope 学到的另一条经验：**短期技术债要进 ADR，不要进注释**。注释会被改代码的人顺手删掉，ADR 不会。

---

## 四、DeepSeekAdapter：双向转换的真实形状

`DeepSeekAdapter` 大概 380 行（含 docstring），核心职责是四件事：

1. 接收 LLMClient Protocol 规定的 Anthropic 风格输入。
2. 转成 OpenAI 风格喂给 `openai.OpenAI().chat.completions.create`。
3. 把 OpenAI 响应转回 Anthropic 风格返回给 loop。
4. 把 openai SDK 的异常翻译成 ProviderError 子类。

我把双向转换分别拆成几个独立函数，便于单测覆盖。

### Anthropic → OpenAI（请求方向）

`tools` 转换最简单：

```python
def _to_openai_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for t in tools:
        out.append(
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {}),
                },
            }
        )
    return out
```

`messages` 转换稍复杂，因为 Anthropic 一条 message 的 `content` 可以是字符串、可以是 block 列表，block 里可能是 `text` / `tool_use` / `tool_result` 三种之一，还可能在同一条 user message 里混合 `text + tool_result`。OpenAI 的 messages 模型不允许这种混合，必须拆成多条。

```python
def _append_user_message(
    oai: list[dict[str, Any]],
    content: Any,
) -> None:
    if isinstance(content, str):
        oai.append({"role": "user", "content": content})
        return
    if not isinstance(content, list):
        oai.append({"role": "user", "content": str(content)})
        return

    text_parts: list[str] = []
    tool_result_blocks: list[dict[str, Any]] = []
    for block in content:
        btype = block.get("type") if isinstance(block, dict) else None
        if btype == "tool_result":
            tool_result_blocks.append(block)
        elif btype == "text":
            text_parts.append(block.get("text", ""))
        else:
            text_parts.append(json.dumps(block, ensure_ascii=False))

    if text_parts:
        oai.append({"role": "user", "content": "\n".join(text_parts)})

    for block in tool_result_blocks:
        raw = block.get("content", "")
        oai.append(
            {
                "role": "tool",
                "tool_call_id": block.get("tool_use_id", ""),
                "content": raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False),
            }
        )
```

这段代码本身不复杂，但有一个易错点：**一条 Anthropic user message 里有多个 tool_result block 时，必须拆成多条 OpenAI tool message，每条带自己的 `tool_call_id`**。我在写第一版时漏了，DeepSeek 直接报 "tool_call_id mismatch" 把请求打回来。单测里我专门加了一个 case 模拟"两个并行 tool_use 在上一轮 assistant 里被一起调出来，下一轮 user 里要拼两条 tool_result"，确保拆分逻辑被覆盖。

assistant 方向同样有易错点：

```python
def _append_assistant_message(
    oai: list[dict[str, Any]],
    content: Any,
) -> None:
    # ...省略 str / 非 list 兜底分支
    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for block in content:
        btype = block.get("type") if isinstance(block, dict) else None
        if btype == "text":
            text_parts.append(block.get("text", ""))
        elif btype == "tool_use":
            tool_calls.append(
                {
                    "id": block.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": block.get("name", ""),
                        "arguments": json.dumps(
                            block.get("input", {}), ensure_ascii=False
                        ),
                    },
                }
            )

    oai_msg: dict[str, Any] = {"role": "assistant"}
    oai_msg["content"] = "\n".join(text_parts) if text_parts else None
    if tool_calls:
        oai_msg["tool_calls"] = tool_calls
    oai.append(oai_msg)
```

`content` 没有 text 时必须置 `None`（不能置 `""`），否则 DeepSeek 在某些版本里会报 "content cannot be empty when tool_calls present"。这种约束 SDK 文档不会告诉你，要靠真实跑出来才能发现。`ensure_ascii=False` 也不能漏，否则中文 tool input 会被序列化成 unicode escape，DeepSeek 端解析回来是乱码。

### OpenAI → Anthropic（响应方向）

响应方向相对简单，但有一个状态字段需要特别处理：

```python
_FINISH_REASON_MAP: dict[str, str] = {
    "tool_calls": "tool_use",
    "stop": "end_turn",
    "length": "max_tokens",
}


def _from_openai_response(response: Any) -> dict[str, Any]:
    choice = response.choices[0]
    finish_reason = getattr(choice, "finish_reason", None) or "stop"
    stop_reason = _FINISH_REASON_MAP.get(finish_reason, "end_turn")

    message = choice.message
    content: list[dict[str, Any]] = []

    text = getattr(message, "content", None)
    if text:
        text = _strip_thinking_tags(text)
        if text:
            content.append({"type": "text", "text": text})

    tool_calls = getattr(message, "tool_calls", None) or []
    for tc in tool_calls:
        fn = tc.function
        try:
            parsed_input = json.loads(fn.arguments) if fn.arguments else {}
        except json.JSONDecodeError:
            parsed_input = {}
        content.append(
            {
                "type": "tool_use",
                "id": tc.id,
                "name": fn.name,
                "input": parsed_input,
            }
        )

    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
    output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0

    return {
        "stop_reason": stop_reason,
        "content": content,
        "usage": {
            "input_tokens": int(input_tokens or 0),
            "output_tokens": int(output_tokens or 0),
        },
    }
```

注意 `_strip_thinking_tags` 调用——这是第 26 轮接 MiniMax 时新加的，但它不只服务 MiniMax。我下面会专门讲。

### 错误翻译

错误翻译用类名匹配而不是 `isinstance`：

```python
def _translate_error(exc: Exception) -> ProviderError:
    class_name = type(exc).__name__
    msg = str(exc)

    if class_name == "AuthenticationError":
        return ProviderUnavailable(f"DeepSeek 认证失败: {msg}")
    if class_name == "APIConnectionError":
        return ProviderUnavailable(f"DeepSeek 连接失败: {msg}")
    if class_name == "RateLimitError":
        return RateLimited(f"DeepSeek 限流: {msg}")
    if class_name == "BadRequestError":
        lowered = msg.lower()
        if "context length" in lowered or "context_length" in lowered:
            return ContextLimitExceeded(f"DeepSeek 上下文超限: {msg}")
        return ProviderError(f"DeepSeek 请求错误: {msg}")
    return ProviderError(f"DeepSeek provider 错误: {class_name}: {msg}")
```

为什么不用 isinstance？因为如果用 isinstance，`bookscope.agent.adapters.deepseek` 顶层就必须 import openai；用户即便只用 Anthropic provider，也得 `pip install openai`。类名匹配让 lazy import 可以贯彻到底——adapter 内部只在构造 client 时才 import openai SDK，错误翻译时只看类名字符串。

这种小动作不是炫技，是把"依赖体量要小"具体落到代码上。

---

## 五、AnthropicAdapter：passthrough 是最容易低估的对照组

`AnthropicAdapter` 大概 180 行。它的 `messages_create` 几乎就是把请求原样转给 SDK：

```python
def messages_create(
    self,
    *,
    model: str,
    system: str,
    tools: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    max_tokens: int,
) -> dict[str, Any]:
    try:
        response = self._client.messages.create(
            model=model,
            system=system,
            tools=tools,
            messages=messages,
            max_tokens=max_tokens,
        )
    except Exception as exc:
        raise _translate_error(exc) from exc

    return _message_to_dict(response)
```

唯一的工作是把 SDK 返回的 `Message` 对象转成 plain dict（loop 用 dict 访问），以及做错误翻译。

这层薄 adapter 看起来像浪费：既然 AgentLoop 内部形态本来就是 Anthropic 风格，为什么不直接把 anthropic SDK 实例当 client 传进去？答案是：**保留 AnthropicAdapter 是为了让"双 provider 抽象跑通"有一个对照组**。如果哪天 DeepSeekAdapter 出现一处可疑行为，我可以马上换成 AnthropicAdapter 跑一遍，看看是 adapter 层逻辑错了还是 DeepSeek 端的特性。这种"基线对照"在调试 provider 行为差异时是无价的。

而且即便是 passthrough，仍然要做错误翻译，否则 loop 层的错误处理分支就会塞满 if-isinstance(exc, anthropic.APIError) / if-isinstance(exc, openai.APIError) 的混合判断。把异常归并到 `ProviderError` 家族（`ProviderUnavailable` / `RateLimited` / `ContextLimitExceeded`）是 adapter 层最容易被忽略但最重要的职责之一。

---

## 六、长尾的第一道：astron-code-latest 的裸 ASCII 引号

第 16 轮我接入讯飞星辰的 astron-code-latest。当时我以为这会是一次很轻的接入：astron 走 OpenAI 兼容端点，复用 DeepSeekAdapter，只换 `base_url` 和 `model` 名。第一次冒烟跑出来确实成功了，5-token sanity check 过了，simple Q&A 也过了。

然后我跑了一个真实的作家题，问 "杨涟在审讯过程中说过哪句最具决心的话"，期待 agent 调 search_chunks 找到原文，然后把那句话当 citation 引出来。

agent 调对了 tool，原文也找到了。但最后的 final answer 直接 LLMFormatError 炸了。

trace 里看到 LLM 返回的 raw text 大概是这样：

```
{"answer": "杨涟在审讯中说出了"我视死如归"这一表态，体现……", "citations": [...]}
```

注意 `"我视死如归"` 这部分——astron 模型在 answer 字符串值里直接用 ASCII 双引号引用原文，没有转义成 `\"`。这是一个完全合法的中文标点选择（中文里引号就是这么用的），但放在 JSON 里就破裂。`json.loads` 在 `"我视死` 那里就把字符串 value 截断了，后面的内容全成了语法错误。

我第一反应是改 prompt：在 `citation_format_v1.md` 里加硬约束 "answer 字段内严禁使用 ASCII 双引号 `\"`，引用原文时改用全角引号 `「」` 或中文书名号"。提了一版，跑 100 题，astron 错失率从大约 17% 降到 13%。我又加强 prompt，跑 100 题，错失率 12%。再调，11%。

到这里我意识到 prompt 调不动了。astron 这个模型在生成 answer 时倾向于用 ASCII 引号引原文，是一种习惯模式，不是简单的"它不知道规则"。模型的训练分布让它在引用原文时几乎条件反射式地打 `"`，而不是 `「」`。

prompt 不行就上 autofix。我在 loop.py 的 `_parse_final_answer` 里加了一道兜底：

```python
def _autofix_unescaped_answer_quotes(json_text: str) -> str | None:
    """针对 astron-code 等 code 模型在 answer 字段裸用 ASCII `"` 的破裂修复。

    前提：顶层 schema 固定为 {"answer": "...", "citations": [...]}，且字段顺序
    answer 先于 citations（citation_format_v1 明文要求）。本函数用这个位置约束
    定位 answer 字符串值的起止边界，然后把中间所有未经 `\\` 转义的裸 ASCII `"`
    补上转义，返回修复后的 JSON 文本。
    """
    head = _AUTOFIX_ANSWER_HEAD_RE.search(json_text)
    if head is None:
        return None
    value_start = head.end()
    tail = _AUTOFIX_CITATIONS_TAIL_RE.search(json_text, value_start)
    if tail is None:
        return None
    value_end = tail.start()
    original_value = json_text[value_start:value_end]
    fixed_value = re.sub(r'(?<!\\)"', r'\\"', original_value)
    if fixed_value == original_value:
        return None
    return json_text[:value_start] + fixed_value + json_text[value_end:]
```

思路是"我知道顶层 schema 是 `{"answer": "...", "citations": [...]}`，answer 字段一定先于 citations，那我就用 regex 定位 answer 值的起止边界，把中间所有未转义的 `"` 补上 `\`"。这是一个**定向**修复，只修这一种已知失败模式，不试图做通用 JSON repair。

为什么不上通用 lenient JSON parser（json5、demjson3）？两个理由。

一是 BookScope 不希望在依赖里多一个不必要的库，违背"依赖体量要小"。

二是定向修复让"为什么这道题被修了"在代码里非常清楚——一看函数名 `_autofix_unescaped_answer_quotes` 就知道在修什么，未来某天这种行为消失了，可以放心删掉。lenient parser 是"无差别宽容"，会把所有 JSON 错误都吞掉，破裂的根因反而被掩盖。

第 16 轮我加这道 autofix 时，loop.py 里同时有一处 trace 增强——format_error 异常上挂 `.trace` 和 `.raw_text`：

```python
except LLMFormatError as exc_fe:
    if format_retries_used >= self._format_retry_limit:
        trace.outcome = "format_error"
        trace.duration_ms = _elapsed_ms(start)
        exc_fe.trace = trace  # type: ignore[attr-defined]
        exc_fe.raw_text = final_text  # type: ignore[attr-defined]
        raise
```

把炸掉的原始文本挂到异常上，post-mortem 时就能看到 agent 走到 final answer 之前调了哪些 tool、留下什么上下文、final text 长什么样。这对定位"是引号转义问题还是结构错位"非常关键。

第 16 轮 astron 接入工作量统计：约 50 行 smoke 分支代码 + 一道 autofix（约 30 行含 docstring）+ 没有改 adapter 本身。

第 19 轮我把 astron 一等公民化——加进 API 层的 provider 选择枚举、加 session 注入、加 trace 标识。382/382 测试全绿，约 13 个新单测覆盖 provider 选择路径与 autofix 边界。

第 19 轮做完时我以为 astron 接入到此为止了。它确实再也没有给我新的麻烦，直到接 minimax 时我意识到 astron 的"裸引号问题"其实是某一类问题的特例。

---

## 七、长尾的第二道：MiniMax M2.7 的 `<think>` 块

第 26 轮接 MiniMax M2.7。又是 OpenAI 兼容端点，又是改 base_url 和 model 名。我以为复用 DeepSeekAdapter 就行。

5-token sanity check 过了。simple Q&A 过了。第一道作家题——也就是问《明朝那些事儿》第 11 章的某个具体细节——返回的 final text 长这样：

```
<think>
让我看看用户问的是什么。他问的是杨涟在审讯过程中的表现……
我需要先看 search_chunks 的结果……
[一大段思考链]
</think>
{"answer": "...", "citations": [...]}
```

reasoning model 的标志：把 thinking trace inline 在 content 里以 `<think>...</think>` 段返回。Anthropic Claude 的 thinking 是单独的 `thinking` content block，OpenAI 的 reasoning 是独立的 `reasoning_content` 字段，但 minimax 把它直接拼在 `content` 里，靠 XML-like 标签划分。

`json.loads` 看到开头是 `<` 就直接死了。autofix 也救不了——前面那一大段 think 文本根本不是 JSON。

我先在 DeepSeekAdapter 里加了 `_strip_thinking_tags`：

```python
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

这个函数挂在 OpenAI → Anthropic 转换的入口处：

```python
text = getattr(message, "content", None)
if text:
    text = _strip_thinking_tags(text)
    if text:
        content.append({"type": "text", "text": text})
```

注意 `_OPEN_THINK_RE` 这个兜底——如果 model 在 think 内部就被 max_tokens 截断了（生成停在 `</think>` 之前），残留的开放 `<think>` 段也得抹掉，否则下游还是会被卡住。这种 edge case 我跑了大约 30 道作家题才捞出一例，但一旦碰上，整道题就废了。

加完 strip 之后 minimax 的 simple Q&A 全过。然后我跑作家题，又炸了。

这次炸的不是 think 块，是 control char。raw text 长这样：

```json
{"answer": "杨涟在第 11 章的审讯场景里有几个关键节点。
第一个节点是……
第二个节点是……", "citations": [...]}
```

注意 answer 字符串里那些换行——在 JSON 字符串内部，原始的 `\n` 必须 escape 成 `\\n`，但 minimax 直接把 raw newline 写进了 `"..."` 内部。`json.loads` 报 `Invalid control character at: line N column M`。

第二道 autofix 加进 loop.py：

```python
def _autofix_control_chars_in_strings(json_text: str) -> str | None:
    """通用 autofix —— string value 内裸 ASCII control char (\\n / \\r / \\t)
    转成 \\n / \\r / \\t escape。

    背景：MiniMax-M2.x 等 reasoning model 在生成多行 JSON 字符串时，常把
    raw newline 直接写进 "..." 内部，json.loads 报 Invalid control
    character at: line N column M。reviewer 的长 dimension 评语尤其
    多见。
    """
    out: list[str] = []
    in_string = False
    fixed = False
    i = 0
    n = len(json_text)
    while i < n:
        ch = json_text[i]
        if not in_string:
            if ch == '"':
                in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == "\\":
            out.append(ch)
            if i + 1 < n:
                out.append(json_text[i + 1])
                i += 2
            else:
                i += 1
            continue
        if ch == '"':
            in_string = False
            out.append(ch)
            i += 1
            continue
        if ch == "\n":
            out.append("\\n")
            fixed = True
        elif ch == "\r":
            out.append("\\r")
            fixed = True
        elif ch == "\t":
            out.append("\\t")
            fixed = True
        else:
            out.append(ch)
        i += 1
    if not fixed:
        return None
    return "".join(out)
```

这是一个 state machine 写法的 autofix，扫一遍 JSON 文本，跟踪 in_string 状态，遇到 string 内部的 raw newline / carriage return / tab 就 escape。

第 26 轮 minimax 接入工作量统计：约 30 行 smoke + reviewer + batch 分支 + DeepSeekAdapter 加 `_strip_thinking_tags`（约 15 行）+ control-char autofix（约 35 行）+ 配套单测约 8 个。

接入完成的那个晚上我做了一件事：把这两道 autofix 串到 `_parse_final_answer` 的兜底链里：

```python
try:
    obj = json.loads(json_slice)
except json.JSONDecodeError:
    autofixed = _autofix_unescaped_answer_quotes(json_slice)
    if autofixed is None:
        autofixed = _autofix_unescaped_quotes_in_all_string_values(
            json_slice,
        )
    if autofixed is None:
        raise LLMFormatError(
            "failed to parse JSON and autofix did not apply"
        ) from None
    try:
        obj = json.loads(autofixed)
    except json.JSONDecodeError as exc:
        raise LLMFormatError(
            f"failed to parse JSON: {exc}"
        ) from exc
```

兜底顺序我特意排过：先试定向（`_autofix_unescaped_answer_quotes`，快、精准、只改 answer 字段），失败再退到通用（`_autofix_unescaped_quotes_in_all_string_values`，state machine 全字段扫，能修任意嵌套字段里的裸引号但偶有英文文本误判风险）。后来加 control-char 修复时按同一原则串进去。

---

## 八、把每家 patch 摆成清单看

接到现在，整个 adapter 层 + loop autofix 链的状态是这样：

| Provider | 接入轮次 | base_url 改动 | model 名 | 非协议行为 | 对应 patch |
| --- | --- | --- | --- | --- | --- |
| DeepSeek（默认） | 第 8 轮 | `https://api.deepseek.com/v1` | `deepseek-chat` | 基本守约 | DeepSeekAdapter 双向转换（基线） |
| Anthropic（备选） | 第 8 轮 | SDK 直连 | `claude-sonnet-4-6` | 几乎 passthrough | AnthropicAdapter（near-passthrough） |
| 讯飞 astron-code-latest | 第 16 轮 | 自定义 | `astron-code-latest` | answer 字段裸 ASCII `"` 引用原文 | `_autofix_unescaped_answer_quotes`（定向）+ `_autofix_unescaped_quotes_in_all_string_values`（通用） |
| MiniMax M2.7 | 第 26 轮 | 自定义 | `minimax-m2-7` | content 内 inline `<think>` 块；string value 内 raw newline | `_strip_thinking_tags`（adapter 内）+ `_autofix_control_chars_in_strings`（loop 兜底） |

四家 provider，五处碎片，三道 loop 层 autofix，一个 adapter 层 strip helper。每一处都说"我兼容 OpenAI 标准"或"我兼容 Anthropic Messages API"，但每一处都有自己的脾气。

我再列一下 onboarding cost 真实数据：

- 第 8 轮 DeepSeek + Anthropic 双 adapter 首发：约 560 行 adapter 代码 + 约 50 个单测。这是基线投入。
- 第 16 轮 astron 接入：约 50 行 smoke 分支 + 30 行定向 autofix + 40 行通用 autofix + 没改 adapter 本身。
- 第 19 轮 astron 一等公民化（API 层）：382/382 测试全绿，约 13 个新单测。
- 第 26 轮 minimax 接入：约 30 行 smoke / reviewer / batch 分支 + 15 行 strip helper + 35 行 control-char autofix + 约 8 个新单测。

总账：四家 provider 的累计 adapter 层 + loop 兼容层投入大约 800 行代码 + 80 个单测。其中 base 基线占 560 行 / 50 测，"长尾税"占约 240 行 / 30 测。也就是说**长尾税在我接的前四家 provider 里，已经吃掉了基线投入的 30%**。

而且这只是已经暴露的部分。我相信下一家 GLM-4.5 或 qwen-max 接入时，会有第三种、第四种碎片冒出来。

---

## 九、类比：接 LLM 像接外部 API，每家都说我兼容标准

我想说一段类比。

接外部 API 这件事在工程师生涯里我做过太多遍——支付网关、地图服务、短信网关、社交登录、对象存储——每一家都有自己版本的"我兼容 X 标准"。S3 兼容是个标准，但你接 minio 跟接阿里云 OSS 跟接 Cloudflare R2 的实际签名细节、错误码、metadata 字段命名都有不同。OAuth 2.0 是个标准，但 GitHub、Google、微信、企业微信对 scope / refresh token / token 过期行为各有自己的脾气。

LLM provider 现在处于完全相同的阶段。"OpenAI 兼容"不是一个紧标准，是一个市场宣传用语。每家 provider 都把自己的 chat completions endpoint 做得"看起来像 OpenAI"——它们读 `model` / `messages` / `tools` / `temperature` 这些字段，返回 `choices[0].message`，对开发者第一次接入时给出一种"无痛切换"的错觉。但只要你跑真实负载，差异就会逐项暴露：

- `tools` 字段里 `function.parameters` schema 的某些 keyword（`additionalProperties` / `nullable`）不同 provider 支持度不一样。
- `tool_calls` 的 id 命名规则不一样，DeepSeek 是 `call_xxx`，astron 是 `chatcmpl-tool-xxx`，minimax 是另一种。
- `finish_reason` 值枚举范围不一样，部分 provider 在工具调用断流时返回 `tool_use` 而不是 `tool_calls`。
- reasoning model 的思考链承载方式不一样，OpenAI o1 用 `reasoning_content`，Claude 用 `thinking` block，DeepSeek-R1 用单独字段，MiniMax 直接 inline 在 content。
- `usage` 字段有的有 `cached_tokens` 子分项，有的没有。
- `content` 字符串里的换行处理标准不一样——这就是 minimax 那一道 control char。
- 引用原文的标点偏好不一样——这就是 astron 那一道裸引号。

每一处都不是"协议 bug"，都是 provider 的训练分布、tokenizer 习惯、postprocess 规则在生产场景下的真实形态。"OpenAI 兼容"是一份框架性的契约，但**真实的语义协议是每家自己的**。

这件事直到我接到第三家 provider 才真正想清楚。在那之前我一直在期待 "下一家会更顺"。第三家不会更顺。第四家不会更顺。第五家也不会更顺。**只要 LLM 不是一个完全标准化的协议（它现在不是，未来五年内大概率也不是），adapter 层的长尾税就会持续征收**。

---

## 十、反思一：adapter 抽象的真实价值不是统一，是命名空间

我最初设计 adapter 层时心里想的是"把 provider 差异都吸收掉，让 loop 看到一个干净统一的接口"。这个想法只对了一半。

对的那一半：协议层的 happy path 确实可以统一。所有 adapter 都实现 `messages_create`，loop 可以无差别调用，不知道底下跑的是哪家 provider。这一层抽象是有价值的。

错的那一半：以为协议层的统一就够了。实际上 adapter 的真实价值不在它**包住**了什么，而在它**给每家碎片划出了一个可定位的命名空间**。

举例。第 16 轮 astron 的裸引号问题暴露后，我给那道 autofix 起的名字是 `_autofix_unescaped_answer_quotes`。第 26 轮 minimax 的 control char 问题暴露后，名字是 `_autofix_control_chars_in_strings`。它们都挂在 loop 层的兜底链里，不在 adapter 层。但每个名字都直接点出了"这是为哪种 provider 行为加的 patch"。

如果没有 adapter 层、loop 直接和具体 SDK 打交道，这些 patch 会塞进各种 if-isinstance / try-except 分支里，命名困难、定位困难、回归困难。**有了 adapter 层之后，每家 provider 的脾气都有了显式名字，命名让 patch 可以独立维护、独立单测、独立删除**。

`_strip_thinking_tags` 这个名字现在挂在 DeepSeekAdapter 里——因为我接 minimax 时复用 DeepSeekAdapter 当 OpenAI 兼容基线。但它实际上服务的是"任意 reasoning model 把 thinking inline 在 content 里"这种行为。命名上是 `_strip_thinking_tags`，不是 `_minimax_strip` 也不是 `_thinking_block_handler`，因为我希望未来 deepseek-r1 / qwen-qwq / glm-zero 接入时能直接受益。

这是 adapter 层另一个被低估的价值：**通用化收益的"折旧"**。第一次接入 minimax 时这道 strip 是"长尾税"——我为了它写了 15 行代码。但下次再接 deepseek-r1 / qwen-qwq / glm-zero 时它已经是免费基础设施。长尾税不是单调累加的，每一道 patch 都在某种程度上为后续 provider 折旧——前提是命名足够通用，挂载位置足够正确。

所以我现在对 adapter 层的理解是：**它不是一个把所有 provider 揉成一团的滤镜，是一个让每家 provider 的脾气都有姓有名的 namespace**。Protocol 是这个 namespace 的入口契约，每家 adapter 是 namespace 内的一个文件夹，loop 兜底链是 namespace 的边界处理区。

---

## 十一、反思二：通用化与定制化的平衡点不在协议层，在数据形态层

ADR-003 里我把 `LLMClient` Protocol 设计得非常薄——只一个方法、关键字参数、返回 plain dict。这是协议层的极简主义。

但碎片暴露的过程让我意识到：**协议层的极简主义不能解决 provider 差异，因为差异不在协议层，差异在数据形态层**。

什么意思？

协议层 = "messages_create 接受 model / system / tools / messages / max_tokens"，五个参数全部 keyword-only。这层我不需要兼容性 hack。

数据形态层 = `messages` 里每一条 message 的 content 长什么样、`tools` schema 的 input_schema 字段怎么写、返回的 content blocks 是哪种形态、stop_reason 取哪些值、usage 字段如何统计。这层每一处细节都是 provider 差异的栖息地。

我在 ADR-003 里把内部数据形态绑定为"Anthropic 风格"——content blocks + stop_reason + tool_use/tool_result。这是一个**定制化**选择，不是**通用化**选择。我没有把数据形态抽象成一个中性的 `AssistantTurn` dataclass（虽然 ADR-003 提到这是未来演化方向），而是直接选了一家的形态当内部基准。

为什么这个选择反而是对的？因为**真正的 provider 差异不会因为内部形态从 Anthropic 风格改成 OpenAI 风格而消失**。它们只会从 DeepSeekAdapter 搬到 AnthropicAdapter。astron 的裸引号、minimax 的 think 块、reasoning_content 的承载方式——这些差异在任何内部形态下都得有人处理。

所以"通用化"在协议层应该极致（Protocol 只一个方法），在数据形态层应该有一家具体偏向（选 Anthropic 或选 OpenAI 都行，关键是**选一个**），在 patch 层应该是定向 + 通用兜底的双层结构（先试定向 fix，失败退到通用 fix）。这三层的通用化程度是不同的，混淆它们会写出"协议很薄但 adapter 巨厚、还是不兼容"的奇怪结构。

我在 BookScope 学到的另一句话：**抽象层的厚度应该和它要解决的差异类型对齐**。协议层抽象差异是接口差异（哪些方法、哪些参数），数据形态层抽象的是结构差异（block 长什么样、字段叫什么），patch 层抽象的是行为差异（同样的请求模型给出不同形态的响应）。三层各管各的事。

---

## 十二、反思三：onboarding cost 的真实组成

我在第 16 轮、第 19 轮、第 26 轮三次接入完成时，分别在 STATE.md 上记过工作量数字。当时我的统计粒度是"代码行数 + 单测数"。第 26 轮接完 minimax 后我重新看这些数字，意识到自己一直在低估接入成本。

代码行数和单测数只是"显性成本"。真正吃时间的是**实战暴露**——你必须真的用这家 provider 跑足够多样的负载，让它暴露出自己的脾气。astron 的裸引号问题在 simple Q&A 上不会暴露，必须跑作家题（让它引用原文）。minimax 的 think 块在 5-token sanity check 上不会暴露，必须让它真的进入 reasoning。control char 问题更隐蔽——它在 reviewer agent 跑长 dimension 评语时最常见，普通 query 几乎碰不上。

这意味着接入新 provider 的真实 onboarding cost 由四块组成：

1. **API 接入成本**：base_url / model 名 / API key 注入。如果走 OpenAI 兼容端点，这块成本接近零。
2. **基线 sanity check 成本**：5-token 短测 + simple Q&A。能确认 provider 能调起来、能返回字符串。这块成本几小时。
3. **实战暴露成本**：跑真实作家题 / 长答复 / reviewer 评估等多种负载，让 provider 把自己的脾气暴露出来。**这块是大头**，每家 provider 至少要几天时间，跑几百道题才能把碎片捞干净。
4. **Patch 维护成本**：对每个暴露的碎片写 autofix / strip helper / 单测，确保未来不退化。

第 1 + 第 2 块合计可能只占总成本的 20%。第 3 + 第 4 块占 80%。我之前在 STATE.md 上记的"约 30 行 smoke 分支 + 8 个新单测"只反映了第 1、2、4 块，完全没反映第 3 块。第 3 块的成本是"我跑了 200 道题才发现 control char 问题"。这件事如果不显式记录，会让"接入新 provider 很容易"的错觉一直延续下去，导致接下一家时再次低估。

所以我现在给自己的接入 ritual 加了三个观察点：

- **观察点 A：5-token sanity check**。`messages_create` 返回是否结构化正确，stop_reason / usage / content 三字段是否齐全。
- **观察点 B：一次 batch 跑**。用 BookScope 标准测试集（明朝那些事儿 P1 作家题，目前 25 道）批量跑一遍。看有多少道触发 LLMFormatError、多少道答复明显短或不引用原文、多少道超时。
- **观察点 C：一次 reviewer 跑**。用 reviewer agent 评估上一步的答复，看 reviewer 自己的 JSON 输出有没有破裂（reviewer 评语很长，是 control char 重灾区）。

三个观察点全过，才能说接入完成。任何一个观察点炸了都要写一道 patch + 单测，再回头跑一遍。

---

## 十三、反思四：长尾税永远不会清零，但可以折旧

写到这里我想强调一个反共识的判断。

很多人接 adapter 层的时候会希望"等我接完前几家 provider，把所有碎片都摸清楚，未来加新家就一劳永逸"。这个期待是错的。

LLM provider 的形态在变化中——新模型发布、新 reasoning 范式、新工具调用语法、新长上下文策略。每过半年都会有新的"非协议行为"被引入。今天我处理 think 块、半年后可能要处理新一代的 multi-turn reasoning trace 格式，可能要处理 native 工具调用之外的 "code execution" content 块，可能要处理 cached prompt 的 usage 字段。

长尾税不会清零。但它有两种"折旧"机制让它可承受：

1. **通用化折旧**：第一次为某家 provider 写的 patch，如果命名得当、挂载位置正确，能为后续 provider 免费服务。`_strip_thinking_tags` 是典型例子——它服务 minimax，未来也服务 deepseek-r1 / qwen-qwq / glm-zero。
2. **流程化折旧**：把"接入 ritual"标准化（5-token + batch + reviewer 三观察点），让暴露过程从"凭经验跑几天"变成"按 checklist 半天跑完"，把第 3 块成本压下来。

这两种折旧加起来，未来加第五家、第六家 provider 的边际成本应该会比第三家、第四家低。但永远不会变成零。

**永远不会变成零这件事不是设计失败，是 LLM provider 这个市场的形态决定的**。adapter 层的设计目标不应该是"消除长尾税"，应该是"让长尾税可见、可定位、可折旧"。

---

## 十四、提案：scripts/adapter_smoke_check.py

基于上面的反思，我想在 BookScope 内部立一个新工具的提案。

工具名：`scripts/adapter_smoke_check.py`。

形态：CLI 脚本，接受参数 `--adapter <name> --base-url <url> --model <name> --api-key-env <ENV_VAR>`，自动跑三个观察点并产生一份接入报告。

伪代码大致长这样：

```python
def main(args):
    adapter = build_adapter(args.adapter, args.base_url, args.model, args.api_key)

    # 观察点 A：5-token sanity check
    a_result = run_5token_sanity(adapter)
    print(f"[A] 5-token sanity: {a_result.status}")
    if a_result.status != "pass":
        report.fail("A", a_result)
        return

    # 观察点 B：batch 跑明朝 P1 作家题
    b_result = run_p1_batch(adapter, batch_size=25, parallel=4)
    print(f"[B] P1 batch: {b_result.passed}/{b_result.total} passed")
    print(f"    LLMFormatError: {b_result.format_errors}")
    print(f"    short answers: {b_result.short_answers}")
    print(f"    timeouts: {b_result.timeouts}")
    if b_result.format_errors > 0:
        # 把炸掉的 raw_text 全部 dump 到 reports 目录
        dump_format_errors(b_result.format_error_traces, args.adapter)

    # 观察点 C：reviewer 跑
    c_result = run_reviewer(adapter, b_result.successful_traces)
    print(f"[C] reviewer: {c_result.passed}/{c_result.total} judged")
    print(f"    reviewer JSON breakage: {c_result.json_errors}")
    if c_result.json_errors > 0:
        dump_format_errors(c_result.json_error_traces, args.adapter)

    # 出报告
    write_report(args.adapter, a_result, b_result, c_result)
```

报告内容应该包含：

- 接入是否通过（A/B/C 全过 = 通过）。
- 每个观察点的统计指标（通过率、错误类型分布、平均耗时、token 用量）。
- 所有 LLMFormatError 的 raw_text 摘要——这是后续写 autofix 的素材。
- 与已知 adapter（DeepSeek、Anthropic）相比的相对指标。

这个工具一立起来，未来接第五家、第六家 provider 时就有了清晰的入口：跑一遍 smoke check，看报告，写 patch，再跑一遍直到 A/B/C 全过。从"凭经验探"变成"按流程跑"。

ADR 里我会把这个工具列为"接入新 provider 的强制 ritual"——任何新 adapter 的 PR，必须附带 `adapter_smoke_check.py` 的输出报告，三个观察点全过才允许 merge。

---

## 十五、回到第一性：长尾税收背后到底是什么

写到最后，我想再退一步思考。

provider adapter 的长尾税收，本质上是**多供应商抽象在没有真正强协议的市场里的必然代价**。LLM 不像 SQL，没有 ANSI 标准。LLM 不像 HTTP，没有 RFC。LLM 现阶段甚至不像 OAuth 2.0——OAuth 至少有一份 spec，各家在 spec 之上加自己的东西。LLM 的"OpenAI 兼容"是一份事实标准（de facto），不是规范标准（de jure），所以每家 provider 都可以在保持"看起来像 OpenAI"的同时，在自己训练分布、tokenizer、后处理逻辑里塞进自己的脾气。

这种现状会持续多久？我估计至少五年。在那之前，任何想做"和书对话"或"让 LLM 帮我做 X"的开源工具，只要它要支持多 provider，就要面对长尾税收。区别只在于把税收明面化（adapter 层 + 命名空间 + autofix 链），还是把它埋在 if-else 里、埋在 try-except 里、埋在 prompt 工程里、埋在用户报错里。

BookScope 选了明面化。它的成本是 adapter 层 + loop 兜底链占了几百行代码、占了 30% 的相对维护量；它的收益是每一道 patch 都有名字、有单测、有 ADR、有可被未来 provider 折旧的可能。我现在愿意为这个收益付那个成本。

---

## 十六、给未来读者的几条话

如果你正在为自己的 LLM 工具做 provider 抽象，我想留几条话给你。

1. **不要相信"OpenAI 兼容"是一份紧协议**。它是市场宣传用语。把它当成"happy path 兼容、edge case 各家不同"的松框架，不要假设每家行为一致。

2. **adapter 层的真实价值不是统一，是命名空间**。给每家 provider 的脾气一个显式名字。命名让 patch 可独立维护、独立单测、独立删除。

3. **协议层要薄，数据形态层要选一家具体偏向，patch 层要定向 + 通用兜底**。三层抽象的厚度应该和它们要解决的差异类型对齐。

4. **接入 ritual 必须显式标准化**。5-token sanity check + batch 跑 + reviewer 跑三个观察点，任何一个炸了都要写 patch + 单测。流程化是对长尾税最有效的折旧方式。

5. **每道 patch 进 autofix 链时，先试定向，再退通用**。定向 patch 快、精准、可删除；通用 patch 兜底但容易误判。两者串联使用，让 happy path 不被通用兜底污染。

6. **短期技术债写进 ADR，不要写进注释**。注释会被改代码的人顺手删掉，ADR 不会。BookScope 的内部形态绑定 Anthropic 风格是 v1 遗留，我把它写在 ADR-003 的"未来演化路径"里，每次重读都会被提醒。

7. **接 LLM provider 像接外部 API**。每家都说"我兼容 X"，每家都有自己的脾气。把你接支付网关 / 对象存储 / 短信服务的工程经验拿过来，会比从零设想 LLM 架构更省事。

8. **长尾税永远不会清零，但可以折旧**。通用化折旧 + 流程化折旧两种机制并用，让税额随 provider 数累加得越来越慢，而不是线性甚至指数增长。

---

## 十七、收尾

第 26 轮接完 minimax 那天晚上我做了一件事——把 adapter 层 + autofix 链一起重新读了一遍。读完之后我没有觉得"这层架构终于稳了"，反而觉得"它会一直变，而且变得有迹可循"。这种感觉对我来说比"稳定"更踏实。

稳定意味着架构在某个点上停止演化，意味着对应的现实不再变化。但 BookScope 面对的现实——LLM provider 市场——肯定会继续变化。adapter 层正确的形态不是"稳定到不再改动"，是"每次改动都能落在一个清晰的、有名字的、可单测的位置上"。

四道 autofix + 一个 strip helper，是 BookScope 当前对这个现实的应答。下一道 autofix 会因为下一家 provider 出现，名字会因为它具体的脾气而被起出来，挂载位置会按"协议层 / 数据形态层 / patch 层"三层的原则被决定，单测会保护它不退化，ADR 会让它的来由不被遗忘。

这就是 provider adapter 的长尾税收——一份可见、可定位、可折旧的工程账本。它不会消失。但它可以被管理。

---

> **状态**：草稿 · 作者未定稿
>
> 本草稿为案例研究文档的工作版本，未经作者本人定稿润色，请勿对外引用。
