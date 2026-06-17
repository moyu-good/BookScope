# Tool Calling 行为光谱：astron / minimax / deepseek / claude 在同一 agent loop 上的实证比较

> **状态**：草稿 · 作者未定稿
>
> 视角：cross-provider 实证研究
>
> 关联代际：r1-agent-loop（第 8 / 16 / 24 / 25 / 26 轮）
>
> 关联 ADR：ADR-002 v2、ADR-003

---

## 〇 · 这篇文章不是 LLM 排行榜

我写 BookScope 写到第 26 轮，桌上同时摆着四把 LLM 钥匙——astron-code-latest、MiniMax-M2.7、deepseek-chat、Claude Sonnet——任何一把都能在 90 秒内对《明朝那些事儿》吐出一段带 citation 的答复。中间有一刻我以为自己会写出一篇"哪家最强"的横评。

写不下去。因为四家在同一个 `LLMClient` Protocol 下跑出来的东西，差别根本不是"分数"这个一维变量能解释的。同一道作家题，astron-code-latest 跑 73.9 秒、调 6 次工具、吐 11 条 citation、JSON 还偷偷裸用 ASCII 引号；MiniMax-M2.7 跑 87.1 秒、调 2 次工具、吐 5 条 citation、reasoning trace inline 在 content 字段里塞 `<think>...</think>`；deepseek-chat 是 ADR-002 v2 把它选作默认 provider 时的"基准"，便宜、稳、function calling 干净；Claude Sonnet 是 BookScope agent loop 内部 message 形态的"语义原型"，但它在这套 production 里其实从没真正主跑过五题 batch。

四家不是排在一条线上的好坏。它们的差别更像四种"工作风格"——同样是被派去找十条原文证据，astron 像个刚进图书馆就把所有相关书架翻一遍的实习生，minimax 像个心里早有腹稿、查一两本佐证就够的资深编辑，deepseek 像个老老实实按 SOP 一步步执行的工程师，claude 则是这套 SOP 当年是他写出来的人。

这篇文章把四家的行为差异拆成四个维度——tool 调用倾向、citation 数量风格、JSON 格式守约程度、reasoning trace 暴露形态——然后实证给出每一家在 BookScope 上跑出过什么数据、留下过什么 bug、需要哪一段 autofix 才能在 production 里不炸。最后我会说一件比性能横评更重要的事：BookScope 的产品价值（evidence-from-text）需要的不是"最聪明的 LLM"，而是"老老实实查证的 LLM"。这两者不是同一件事，而且第二件事还在被新一代大模型的训练污染慢慢侵蚀。

匿名化提示：本文涉及到的"作者"指 BookScope 项目负责人，使用 git 身份 `moyu-good`；不出现真实姓名或公司名。

---

## 一 · 为什么先讲 deepseek（即便它在 BookScope 里跑得最少）

讲行为光谱之前，得先把"基准"在哪里讲清楚。

ADR-002 v1 在 2026-04-20 上午把默认 provider 锁定为 Claude Sonnet 4.6——理由是"Anthropic SDK 成熟、Sonnet 在 tool-use 推理深度上是 SOTA"。同一天下午，作者补充了 NORTH_STAR 不变量"LLM provider 国内优先"，v1 决策直接作废。v2 把默认改成了 `deepseek-chat`，论证里有一段我一直记得：

> 对 BookScope 这种"基于原文证据给出带 citation 的答复"的任务，DeepSeek 的能力边界完全够用。

注意这句话的语义。它没说"DeepSeek 比 Claude 强"——它说的是"够用"。一个产品级决策选 default provider 的判断标准，从来不是"哪家最强"，而是三个组合条件：

1. 便宜（学生 / 研究者拿得起 BYOK key）；
2. function calling 语义稳（OpenAI 兼容、不需要写第二套 schema 转换）；
3. 中文长文本理解到位（《明朝那些事儿》、网络小说草稿都跑得动）。

deepseek-chat 同时满足这三条。这就是为什么它是 BookScope 的"默认"——不是因为它在某个 benchmark 上排第一，而是因为它在三个约束的交集里最干净。

`bookscope/agent/adapters/deepseek.py` 的顶部 docstring 里明确写过这一点：

```python
"""DeepSeekAdapter —— ADR-002 v2 选定的**默认** provider。

ADR-002 v2 的背景是 BookScope 作为"开源学习项目 + GitHub Star 收集"
的定位：默认 provider 必须对国内外学生 / 研究者都极低门槛。DeepSeek
同时满足三点：

1. **便宜**：``deepseek-chat`` 每百万 token 比 Claude Sonnet 便宜
   一个数量级，让学生能真的跑起来而不是只看 README。
2. **开放 API**：OpenAI 兼容 endpoint（``/v1/chat/completions``），
   直接复用 ``openai`` SDK。
3. **工具调用支持完善**：DeepSeek 的 tool-use 能力在开源 provider
   里目前是最稳的，能撑起 ADR-001 要求的三 tool 主循环。
"""
```

deepseek 的"工程师人设"还体现在另一件事上：它是 BookScope OpenAI 兼容 adapter 的"模板"。astron-code-latest 接入（第 16 轮）和 MiniMax-M2.7 接入（第 26 轮）都没新写 adapter，而是复用 `DeepSeekAdapter` 加 base_url 切换。也就是说，BookScope 里其实有一类 provider——OpenAI 兼容家族——共用一份代码：

```python
# bookscope/api/dependencies.py（第 19 轮）
ASTRON_DEFAULT_BASE_URL = "https://maas-coding-api.cn-huabei-1.xf-yun.com/v2"

def build_llm_client_from_params(provider, api_key, base_url=None, ...):
    if provider == "astron":
        return DeepSeekAdapter(
            api_key=api_key,
            base_url=base_url or ASTRON_DEFAULT_BASE_URL,
        )
    if provider == "minimax":
        return DeepSeekAdapter(
            api_key=api_key,
            base_url=base_url or "https://api.minimaxi.com/v1",
        )
    if provider == "deepseek":
        return DeepSeekAdapter(api_key=api_key, base_url=base_url)
    if provider == "anthropic":
        return AnthropicAdapter(api_key=api_key)
    raise ValueError(f"unsupported provider: {provider}")
```

四个 if 分支里有三个返回 `DeepSeekAdapter`。从 BookScope 的工程视角，astron / minimax / deepseek 都是"用 OpenAI 兼容协议说话的 LLM"——adapter 不区分。但**它们在行为上的差异**全在 LLM 层面而不是 SDK 层面，于是同一个 adapter 跑出来的 trace 才能形成本文要讨论的"行为光谱"。

deepseek-chat 自己跑的真 batch 数据反而是四家里最少的——因为它是默认 provider，反倒被作者拿来当"对比组"，绝大多数 batch 实验都跑了 astron 或 minimax 来看新 provider 怎么样。这是个有意思的悖论：默认是基准，基准反而少跑。但本文要讲的"行为光谱"恰恰是站在 deepseek 这条基线上看出来的——把 astron 和 minimax 跟一个"老老实实按 OpenAI 标准 function calling"的预期对比，差异才显出来。

---

## 二 · 一张大表：四家在同一题上的行为指标

直接放数据。下表汇总四家 provider 在 BookScope 实际跑过的代表性 trace。q1-q5 是 v3.1-minimax-batch-01（5 道作家题），第 16 轮是 astron 跑的角色弧线题（baseline 测试），第 24 轮是 astron 跑的李善长铺垫连贯性题（P1 首次作家场景验证）。

| 轮次 / 题目 | provider | model | 时长 | iterations | tool_calls | citation 数 | 主要 tool | outcome |
|-------------|----------|-------|------|------------|------------|-------------|-----------|---------|
| 第 16 轮 baseline | astron | astron-code-latest | 82.3s | 4 | 6 | 7 | search_chunks × 5 + list_characters × 1 | success |
| 第 24 轮 李善长题 | astron | astron-code-latest | 73.9s | 3 | 6+ | 11 | search_chunks 演进式（宽搜→结局→起点→退休） | success |
| q1 节奏评估 | astron+v2 | astron-code-latest | 102.6s | 4 | 5 | 10 | search_chunks × 5 | 25/25 |
| q2 支线密度 | astron+v2 | astron-code-latest | 111.3s | — | — | 16 | search_chunks 多次 | 25/25 |
| q3 伏笔回收 | astron+v2 | astron-code-latest | — | — | — | 13 | search_chunks 多次 | 25/25 |
| q4 角色转变 | astron+v2 | astron-code-latest | — | — | — | 12 | search_chunks 多次 | 25/25 |
| q5 设定漂移 | astron+v2 | astron-code-latest | — | — | — | 11 | search_chunks 多次 | 24/25 |
| q1 节奏评估 | minimax+v3.1 | MiniMax-M2.7 | 87.1s | 3 | 2 | 5 | get_chapter_range × 1 + search_chunks × 1 | 18/25 |
| q2 支线密度 | minimax+v3.1 | MiniMax-M2.7 | 77.5s | 3 | 2 | 5 | search_chunks × 2 | 19/25 |
| q3 伏笔回收 | minimax+v3.1 | MiniMax-M2.7 | 124.7s | 4 | 5 | 6 | search_chunks × 5 | 22/25 |
| q4 角色转变 | minimax+v3.1 | MiniMax-M2.7 | 168.2s | 4 | 3 | 7 | search_chunks × 2 + get_chapter_range × 1 | 18/25 |
| q5 设定漂移 | minimax+v3.1 | MiniMax-M2.7 | 165.8s | 5 | 6 | 6 | search_chunks × 6 | 23/25 |
| 第 22 轮 真 KG pilot | astron | astron-code-latest | 109s（含抽 KG 46s） | 4 | 6 | 10 | 多 tool | success |
| baseline 横评 | deepseek | deepseek-chat | — | — | — | — | — | 默认 provider，少专题 batch |
| baseline 横评 | claude | claude-sonnet-4-6 | — | — | — | — | — | 内部 message 形态原型，无 production batch |

几条直接读出来的事：

**第一，astron 是"工具调用积极型"。** 第 16 轮 baseline 在通识题上调 6 次工具拿 7 条 citation；第 24 轮作家题调更多次拿 11 条 citation；v2 batch 5 题里 citation 平均落在 10-16 条区间——它默认会把 tool 跑到位。

**第二，minimax 是"够用即停型"。** 同一套作家题，v3.1 batch 5 题里 q1/q2 只调 2 次工具拿 5 条 citation 就收手；只有 q5 这种最难的题才调到 6 次 / 6 条 citation。citation 数从 astron 的 10-16 区间塌缩到 5-7 区间，差不多减半。

**第三，"调用次数与得分强相关"在 minimax 上特别明显。** v3.1 batch 里 q5（tool=6, total=23）和 q3（tool=5, total=22）接近 v2+astron 的水平；q1/q2（tool=2, total=18/19）拖低均值。最终五题平均从 v2+astron 的 24.8 退到 v3.1+minimax 的 20.0——差距全在"调不调工具"。

**第四，astron 在 P1 作家场景下的"宽搜→结局→起点→退休"演进式搜索**是行为光谱里最有意思的一种 path。它不是漫无目的相关词搜，而是像一个真做调研的编辑：先大网捞、看到大致弧线、然后回头查关键节点的起源、最后倒推到中段。这个 path 在 v2 batch 的 q1（节奏评估）里再次复现——5 次 search_chunks 把"火药埋藏"和"演员到齐"这两条元叙事级伏笔全挑出来了。

**第五，deepseek 和 claude 是"光谱的两端"——但都没在 production 上做完整的 5 题 batch。** deepseek 是默认 provider 但被作者拿来当对比基线，claude 是 BookScope 内部 message 形态的原型但作者手里没有 Anthropic key 跑生产。这两家的"行为指纹"在 BookScope 里更多是工程预期而不是观察事实——这本身就是 BookScope 这种"国内优先"项目的一种特征。

---

## 三 · astron-code-latest：积极调用 + 高引文密度 + 裸引号 JSON bug

astron-code-latest（讯飞星辰 code 系列）是 BookScope 第一家做完整端到端集成测试的 provider。第 16 轮跑通的那次，82.3 秒、4 iterations、6 tool 调用、7 条 citation——这组数据后来成了 BookScope 所有 provider 的"参考点"。

### 3.1 行为指纹：演进式 path

第 24 轮的李善长题是更典型的样本。题目是："李善长从开国功臣到被胡惟庸案牵连处死，书里对他政治立场转变的铺垫是分散在哪几章、什么事件节点？铺垫是否连贯，还是只靠结局一句话交代？"——一道**纯作家诊断题**，不是通识题。

astron 的搜索 path 从 trace 看是这样的：

1. **宽搜**：第一次 search_chunks query "李善长" 拿大致出场弧线；
2. **结局优先**：第二次 search_chunks query "胡惟庸案 李善长" 锁定第 20 章被处死；
3. **起点回查**：第三次 search_chunks query "李善长 投奔" 找到第 5 章首次出场和第 14 章审问张士诚的暴跳如雷；
4. **退休转折**：第四次 search_chunks query "李善长 退休" 找到第 17 章作者明示"演员到齐了"的元叙事级铺垫；
5. **中段补漏**：第五次 / 第六次 search_chunks query 补关键事件原文。

最后吐出 11 条 citation，包括第 14 章狗之隐喻这种**人物底色伏笔**——这条线索在第 16 / 22 轮的通识题跑里一次都没被挖到，只在作家题下浮现。

这就是所谓"工具调用积极型"在 production 里的真实样子：astron 在没有任何 prompt 强制的情况下默认会把工具用到位。第 25 轮 v2 batch 5 题里它的平均 citation 数 12.4 条，最少也有 10 条；第 16 轮 baseline 里它在 system prompt 没有"必须调用 N 次"约束的情况下也调了 6 次。

### 3.2 老毛病：在 answer 字段裸用 ASCII `"` 引用原文

astron 有一个让我跑了几个晚上之后才彻底意识到的 bug：**它在 final answer 字段里裸用 ASCII 直引号引用原文，违反 JSON 转义规则**。

具体长什么样？第 24 轮第二次跑李善长题的时候，agent loop 抛了 `LLMFormatError: failed to parse JSON`。我给异常挂上 `.raw_text` 之后看到的真正炸点是这样的：

```json
{
  "answer": "书中点明他"外表宽厚，却心胸狭窄"，这是李善长性格的底色...",
  "citations": [...]
}
```

注意 `"外表宽厚，却心胸狭窄"` 这一段。astron 想引用原文，但它没把内嵌的 `"` 转义成 `\"`，结果 `json.loads` 在第一个内嵌 `"` 处就把字符串 value 误判为结束，剩下的内容变成了 schema 之外的垃圾，整个 JSON 直接破裂。

我先试了 prompt 路径——在 `citation_format_v1.md` 加硬约束："answer 内嵌引号请用全角 `「」` 或转义成 `\"`"。**astron 不听**。第三次跑还是裸 ASCII `"`。这是一个 prompt 调不动的训练 artifact——code 系列模型在训练数据里大概见过太多裸引号文本，它在生成 JSON 字符串值时下意识把"引用原文"和"用 ASCII 引号包起来"绑在一起，没把"现在我在 JSON 字符串内部"这件事考虑进去。

prompt 调不动，那就在 parser 层兜底。

### 3.3 定向 autofix：`_autofix_unescaped_answer_quotes`

我利用顶层 schema 固定的位置约束写了一个**定向**的 autofix。BookScope 的 final answer schema 是固定的：`{"answer": "...", "citations": [...]}`，且 `citation_format_v1` 明文要求 answer 必须先于 citations。这就给了我一个稳定的位置锚点：

```python
# bookscope/agent/loop.py
_AUTOFIX_ANSWER_HEAD_RE = re.compile(r'"answer"\s*:\s*"')
_AUTOFIX_CITATIONS_TAIL_RE = re.compile(r'"\s*,\s*"citations"\s*:')


def _autofix_unescaped_answer_quotes(json_text: str) -> str | None:
    """针对 astron-code 等 code 模型在 answer 字段裸用 ASCII `"` 的破裂修复。

    前提：顶层 schema 固定为 ``{"answer": "...", "citations": [...]}``，且字段顺序
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

这是一个针对**单一失败模式**的定向修复，不是通用 JSON 修复器。只处理 answer 字段内的裸引号；不尝试修 citations 字段（因为 citations 是 tool 原文 snippet 回传，副管理已要求 LLM "不得改写"，破裂概率极低）。

第 24 轮做完这个修复后第四次跑：73.9 秒、3 iterations、11 条 citation、outcome=success。astron 的"积极工具调用 + 高 citation 密度"产品价值终于稳定输出了，代价是 BookScope 在 parser 层养了一个 provider-specific 的兜底。

第 25 轮做 reviewer agent 时发现 reviewer 自己也会在 5 维 rubric 评语里裸用引号——这次不是顶层 answer/citations 二元结构，是嵌套字段（`per_dimension_comment.honesty` 之类的字符串值）。定向版搞不定嵌套，于是写了第二层通用 autofix：`_autofix_unescaped_quotes_in_all_string_values`，状态机扫描，对任意字符串 value 内部的裸 `"` 做转义。loop.py 里的 fallback 链最后变成：

```python
# bookscope/agent/loop.py · _parse_final_answer 内部
try:
    obj = json.loads(json_slice)
except json.JSONDecodeError:
    autofixed = _autofix_unescaped_answer_quotes(json_slice)
    if autofixed is None:
        autofixed = _autofix_unescaped_quotes_in_all_string_values(json_slice)
    if autofixed is None:
        raise LLMFormatError("failed to parse JSON and autofix did not apply")
    obj = json.loads(autofixed)
```

定向先做（快、精准、修顶层 answer），失败再退到通用（覆盖任意嵌套）。两层都失败才抛 LLMFormatError。这是一个 loop 与 reviewer 共享的修复链——同一个状态机扫描函数被两边复用。

### 3.4 工程教训

astron 的整段故事教给 BookScope 三件事：

1. **prompt 不是万能的。** 训练 artifact 形成的输出习惯（裸 ASCII 引号）prompt 调不动，必须在 parser 层兜。
2. **定向修复优先于通用修复。** 顶层 schema 固定时定向版又快又精准；通用版做 fallback 兜嵌套场景。
3. **autofix 也要测。** 第 24 / 25 轮一共加了 7 个 autofix 单元测试（裸引号 / fenced+裸引号 / 合法 JSON 不误伤 / 通用版多种嵌套 case），保证回归保护。

---

## 四 · MiniMax-M2.7：reasoning trace inline + "够用即停"型

第 26 轮作者一句"切到 minimax 2.7"开始，BookScope 的 default provider 切到了 MiniMax-M2.7（2026-03-18 发布的 reasoning model）。一行 base_url 改完之后跑出来的事情比 astron 当年复杂得多。

### 4.1 第一坑：5-token sanity check 发现 inline `<think>` 块

接入 minimax 的第一件事是 sanity check——发个简单的 5-token 请求验证 SDK / base_url / api_key 三件套通了。结果 minimax 回的 content 字段里**直接 inline 了 `<think>...</think>` 块**：

```json
{
  "choices": [{
    "message": {
      "content": "<think>\n用户问的是简单算数，1+1=2。\n直接回答即可。\n</think>\n2"
    }
  }]
}
```

这是 reasoning model 的通病：思考链不通过单独字段返回（像 OpenAI o1 那样的 `reasoning_content`），而是 inline 在 content 主字段里以 XML-style 标签包起来。问题是 BookScope 的下游 JSON parser 完全不知道什么是 `<think>`，它只看到 content 里有一坨非 JSON 内容，直接破裂。

修复方式很短——在 `DeepSeekAdapter._from_openai_response` 里加一个 strip helper：

```python
# bookscope/agent/adapters/deepseek.py
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

这个 helper 写完之后我意识到一件好事——它对**未来所有 reasoning model** 都有用。deepseek-r1、qwen-qwq-32b、glm-zero——这些国内 reasoning model 都用同一套 inline `<think>` 模式。helper 加在 adapter 层之后，BookScope 不用关心 LLM 是不是 reasoning model，content 字段对外永远是干净的。non-reasoning model 路径上 `_strip_thinking_tags` 是 no-op（顶部 `if "<think" not in text.lower(): return text` 早返）。

### 4.2 第二坑：reviewer JSON 控制字符未转义

接入 minimax 跑 reviewer agent 时又炸了一次。这次的报错是：`json.JSONDecodeError: Invalid control character at: line N column M`。

minimax 在 reviewer 给的 5 维评语里直接把 raw newline 写进了 `"..."` 内部。json.loads 看到字符串内部的裸 `\n` 直接拒收。这是另一个 reasoning model 通病——它在生成多行 JSON 字符串时把"我现在在写 JSON 字符串内部"和"我在写 markdown 风格的多行评语"两件事的边界搞混了。

第二层 autofix 上场：

```python
# bookscope/agent/loop.py
def _autofix_control_chars_in_strings(json_text: str) -> str | None:
    """通用 autofix —— string value 内裸 ASCII control char (\\n / \\r / \\t)
    转成 ``\\n`` / ``\\r`` / ``\\t`` escape。

    背景：MiniMax-M2.x 等 reasoning model 在生成多行 JSON 字符串时，常把
    raw newline 直接写进 ``"..."`` 内部，json.loads 报 ``Invalid control
    character at: line N column M``。reviewer 的长 dimension 评语尤其
    多见。
    """
    out, in_string, fixed = [], False, False
    i, n = 0, len(json_text)
    while i < n:
        ch = json_text[i]
        if not in_string:
            if ch == '"':
                in_string = True
            out.append(ch); i += 1; continue
        if ch == "\\":
            out.append(ch)
            if i + 1 < n: out.append(json_text[i + 1]); i += 2
            else: i += 1
            continue
        if ch == '"':
            in_string = False; out.append(ch); i += 1; continue
        if ch == "\n":
            out.append("\\n"); fixed = True
        elif ch == "\r":
            out.append("\\r"); fixed = True
        elif ch == "\t":
            out.append("\\t"); fixed = True
        else:
            out.append(ch)
        i += 1
    if not fixed: return None
    return "".join(out)
```

跟 astron 那边的 quote autofix 串联：先 quote 修，再 ctrl 修。两轮都 fail 才抛 `LLMFormatError`。

### 4.3 行为指纹：tool 调用"够用即停"

接入修通之后才能开始看 minimax 真正的"行为"。v3.1+minimax batch 5 题的数据是这样的：

| 题号 | tool_calls | citation 数 | 总分 |
|------|-----------|-------------|------|
| q1 节奏评估 | 2 | 5 | 18 |
| q2 支线密度 | 2 | 5 | 19 |
| q3 伏笔回收 | 5 | 6 | 22 |
| q4 角色转变 | 3 | 7 | 18 |
| q5 设定漂移 | 6 | 6 | 23 |
| **平均** | **3.6** | **5.8** | **20.0** |

对比 v2+astron 同 5 题的平均：tool_calls 大致 5 次以上、citation 12 条以上、总分 24.8。

minimax 的"够用即停"在 q1 / q2 上最典型——它调一次 `get_chapter_range` 拿章节原文 + 一次 `search_chunks` 关键词搜，两次工具就觉得够了，5 条 citation 直接吐答案。这不是它"不会调"——v3.1 prompt 里我加了"至少一次 tool 调用"的硬约束，它**严格按最低限度执行**。"至少 1 次"就调 1 次起步，绝不主动加码。

q5（设定漂移题）调了 6 次工具拿 6 条 citation 拿 23 分——说明能力上没问题。它只是默认偏向"用训练记忆作答"，不主动做查证。

### 4.4 训练污染漏洞：硬证据

这才是第 26 轮真正最重要的发现。MiniMax-M2.7（2026-03-18 发布）训练数据**几乎肯定包含《明朝那些事儿》全文**——这本书是 2006-2009 年完成的公开中文长篇，全网各种格式都能爬到。

证据链有三条：

1. **citation 5-7 条 vs astron baseline 10-13 条**——明显偏少。如果模型完全不知道原文，被强制调工具的情况下应该把工具用到位拿更多 citation 才对。
2. **5 条 citation 在结构 / 字句上都很像真原文**——但比 astron 给出的 10-13 条**显著偏少**，说明模型并非"无能力查证"，而是"觉得查到一两条就够了，剩下靠记忆补"。
3. **直接 prompt "调用 X 函数"时 minimax 立刻触发 `tool_calls` 字段**——说明能调；query 时它**选择**不调。

这是**新一代大模型在公开书 baseline 上的训练污染漏洞**——模型即便强制 tool 至少 1 次，仍偏向用训练记忆作答，绕开 BookScope 的 evidence-from-text 机制。

5 题平均退化 4.8 分（24.8 → 20.0）这个数字看起来是"prompt v2 → v3.1 退化"或"provider astron → minimax 退化"，但拆开来根本不是这两个变量的事——是"模型见没见过测试集"这个第三变量在主导。

这一发现反过来强化了 NORTH_STAR 第 1 条——**作家自己未公开稿子（minimax 训练里没见过）才是真用例**。在私域文本上，模型没有任何"记忆"可以 fall back 到，**必须** tool 调用——只有这种场景下，BookScope 与 ChatGPT / Claude 直通的差异才能稳定显现。

第 26 轮的失败 batch 比第 25 轮的成功收敛对 BookScope 更重要：它实证暴露了公开书 baseline 的天花板。

---

## 五 · deepseek-chat：基准 provider 的"沉默存在"

第三家。deepseek-chat 在 BookScope 里的角色比较特殊——它是 ADR-002 v2 选定的默认 provider，但在 v2 / v3 / v3.1 的真实 batch 实验里**几乎没有它专题数据**。原因前面讲过，作者把它当对比基线，每次有新 provider 接进来就跑新的（astron / minimax），deepseek 反倒没拿到主要的实验位。

但 deepseek 的存在本身在 BookScope 里有三层意义：

### 5.1 工程意义：它是 OpenAI 兼容家族的"语义模板"

BookScope 不是为每家 provider 写一个 adapter。它是写一个 `DeepSeekAdapter`——所有走 OpenAI 兼容协议的 provider 都用它，只换 base_url。这个设计在 ADR-003 里被明确写下：

> **GLMAdapter / QwenAdapter / KimiAdapter**（后续补齐）：三家均提供 OpenAI 兼容端点，可复用 `DeepSeekAdapter` 的大部分转换逻辑。建议把 `DeepSeekAdapter` 的 format 转换抽象为 `OpenAICompatibleAdapter` 基类，后续三家继承该基类仅覆写 endpoint、模型名、鉴权细节。

第 19 轮的 astron 接入和第 26 轮的 minimax 接入证明了这条路径——两次都是一个 base_url 切换 + 一两个 helper 加进 DeepSeekAdapter（minimax 那次的 `_strip_thinking_tags`），核心 adapter 代码零改动。

deepseek 在 BookScope 里的"基准"意义是工程的——它不是性能基准，是**协议基准**。

### 5.2 决策史意义：v1→v2 翻案的中枢

ADR-002 v1（上午）锁定 Anthropic Sonnet 为默认。ADR-002 v2（下午）翻案改成 deepseek-chat。这不是性能比较的结论——是 NORTH_STAR 不变量"LLM provider 国内优先"加进来之后，v1 自动作废，v2 在合规候选里挑一家最稳的。

deepseek 之所以胜出（vs GLM / Qwen / Kimi），ADR-002 v2 论证写得很清楚：

> 四家均为国内首选候选，但综合评估 DeepSeek 胜出：function calling 成熟度最高、API 稳定性与 OpenAI 兼容层最干净、`deepseek-r1` 权重开放给未来本地验证留余地、价格档位适中。

注意每一条都不是"deepseek 比 GLM 强多少分"——是工程约束的乘积。这种"不是最强但最稳"的特征贯穿 deepseek 在 BookScope 里的整个故事。

### 5.3 行为指纹（推测）：标准型

deepseek 在 BookScope 没有完整的 5 题 batch 数据，但从 OpenAI 兼容协议和 function calling 一致性角度，可以推测它的行为指纹：

- **tool 调用倾向**：标准型——遇到 tool 描述里"必须先调 search_chunks"会按要求调；不会像 minimax 那样主动跳过，也不会像 astron 那样积极加码。
- **citation 数量风格**：估计在 7-10 条之间——靠 prompt 引导能拿到位，不会自己加码。
- **JSON 格式守约程度**：高——deepseek-chat 在 OpenAI function calling 协议上是"标准答案"，裸引号 / 控制字符未转义这类问题极少。
- **reasoning trace**：non-reasoning model 路径，content 字段干净，无 inline `<think>`。`deepseek-r1` 是 reasoning 变体，会触发 `_strip_thinking_tags` helper。

第 27 轮候选里有"provider 单变量分离：跑 astron+v2 复现 + minimax+v2 拆分换 generator 的代价"。如果做下去，把 deepseek 也补一份 v2 baseline batch 就能完整覆盖 OpenAI 兼容三家的行为光谱。这事儿目前还没做——属于"该做但优先级被作家自己稿子的 P1 验证压住"。

---

## 六 · Claude Sonnet：BookScope 内部 message 形态的"原型"

最后一家。Claude Sonnet 4.6 在 BookScope 里的位置比 deepseek 更微妙——它**根本没在 production 上跑过完整 5 题 batch**，但 BookScope 整个 agent loop 的 message 形态都是抄它的。

### 6.1 历史：v1 ADR 的遗产

ADR-002 v1（被 v2 作废的那个版本）选择 Claude Sonnet + 自建 loop 时，loop.py 的内部 message 形态直接采用了 Anthropic Messages API 的 `content blocks + stop_reason + tool_use/tool_result` 结构。理由 ADR-002 v2 的 第 14 条实现要点里讲过：

> 当前 AgentLoop 内部仍用 Anthropic tool_use block 形态（v1 遗留），`DeepSeekAdapter` 做 OpenAI function calling ↔ Anthropic tool_use 的双向转换。中期（r2 或下一次架构扫描）应把内部形态重构为 OpenAI function calling（业界事实标准），让 Anthropic adapter 做反向转换。

也就是说：

- BookScope **内部表达 tool calling 的语义**用的是 Anthropic 风格——`content` 是 block 列表，每个 block 是 `{"type": "text", ...}` 或 `{"type": "tool_use", "id": ..., "name": ..., "input": {...}}`。
- BookScope **对外说话的 99% provider** 是 OpenAI 兼容（deepseek / astron / minimax / 未来 GLM / Qwen / Kimi）。

中间是 `DeepSeekAdapter` 做双向翻译。Anthropic 那边只需要 `AnthropicAdapter` 做 near-passthrough——adapter 几乎不动，因为内部形态本来就是它的语言。

### 6.2 AnthropicAdapter 的 passthrough 实现

`bookscope/agent/adapters/anthropic.py` 的核心方法只有十几行：

```python
def messages_create(self, *, model, system, tools, messages, max_tokens):
    """Passthrough 调用 anthropic SDK，把 Message 对象转 dict。"""
    try:
        response = self._client.messages.create(
            model=model, system=system, tools=tools,
            messages=messages, max_tokens=max_tokens,
        )
    except Exception as exc:
        raise _translate_error(exc) from exc
    return _message_to_dict(response)
```

参数透传、SDK Message 对象转 plain dict、SDK 异常翻译为 `ProviderError` 子类——就这三件事。没有任何 schema 转换，因为不需要。

对比 DeepSeekAdapter 那边——它要做 Anthropic tool_use block ↔ OpenAI function calling tool_calls 的双向翻译，光 `_to_openai_messages` 一个函数就六十多行。两个 adapter 的代码体量差距大概是 7:1。

这是 ADR-003 显式标注的**技术债**——本来应该让 OpenAI 兼容 adapter 做 passthrough（业界事实标准），让 Anthropic adapter 做翻译；但因为 v1 历史原因反过来了。r2 或下一次架构扫描会修这个。

### 6.3 Claude 的"理论行为指纹"

虽然 BookScope 没有 Claude 的真 production batch，从 AnthropicAdapter 几乎是 passthrough 这点 + 业界共识可以推测：

- **tool 调用倾向**：高——Sonnet 4.6 在 tool-use 推理深度上是 SOTA，遇到复杂 query 会主动多轮调用 + 自我修正。
- **citation 数量风格**：高——"长上下文 + 深度推理"组合下，Claude 倾向于把工具用到位拿全证据。
- **JSON 格式守约程度**：极高——Sonnet 系列在 structured output 上几乎不出错，不会有 astron 那种裸引号毛病。
- **reasoning trace**：非 inline——extended thinking 是单独字段，不污染 content 字段，不需要 strip helper。

这些是"如果未来有 BYOK 用户拿 Claude key 跑 BookScope 大概会看到的样子"的预期，不是 BookScope 自己跑出来的实证。这本身就是"国内优先"项目的一种特征——主链路不依赖 Anthropic，但 adapter 留着，BYOK 用户真有 key 时按需切换。

---

## 七 · 行为光谱按 4 维度分类

把前面四节的零散观察整合成一张"行为光谱图"。四个维度：

### 7.1 维度一：tool 调用倾向

```
积极加码型 ────────────── 标准型 ────────────── 够用即停型
   astron                deepseek (推测)         minimax
                          claude (推测，倾向积极)
```

astron 在没有强制 prompt 的情况下默认会调 5+ 次工具；minimax 会按"至少 N 次"的硬约束严格执行最低限度；deepseek / claude 介于中间但都倾向积极（claude 因为推理深度，deepseek 因为遵循 prompt）。

**对 BookScope 的影响**：tool 调用次数与最终答案得分**强相关**——v3.1+minimax batch 里 tool=2 题平均 18-19 分，tool=5+ 题平均 22-23 分。这个相关性在 astron 那里反而看不出来，因为它默认就是 5+，落到了"够用以上"的区间。

### 7.2 维度二：citation 数量风格

```
高密度（10-16 条） ─── 中等密度（7-10 条） ─── 偏低密度（5-7 条）
     astron               deepseek/claude (推测)        minimax
```

直接对应 tool 调用倾向。astron 的 citation 数据在 v2 batch 5 题里是 10/16/13/12/11，平均 12.4 条；minimax 的 v3.1 batch 5 题是 5/5/6/7/6，平均 5.8 条。差距是 2 倍以上。

### 7.3 维度三：JSON 格式守约程度

```
高守约 ──────────── 中守约 ──────────── 低守约
claude/deepseek         minimax              astron
                  (control char 漏)      (裸 ASCII " 漏)
```

每家漏的方式不一样：

- **astron**：在 answer 字段裸用 ASCII `"` 引用原文。prompt 调不动，需要定向 autofix。
- **minimax**：在多行字符串值内塞 raw newline，触发 `Invalid control character`。需要 ctrl-char autofix。
- **deepseek/claude**：极少漏，protocol 守约高。

BookScope 的 parser autofix 链就是按这个光谱设计的——定向修先做（astron），通用 quote 修兜底（任意嵌套），control-char 修兜底（minimax）。三层 fallback。

### 7.4 维度四：reasoning trace 暴露形态

```
独立字段 ──────────── 无 reasoning trace ──────────── inline <think>
claude (extended)       deepseek-chat / astron        minimax / deepseek-r1
                                                       qwen-qwq / glm-zero
```

- **Claude**：extended thinking 是独立字段，不污染 content。
- **deepseek-chat / astron**：non-reasoning model，content 字段直出 final answer，干净。
- **minimax / deepseek-r1 / qwen-qwq / glm-zero**：reasoning trace inline 在 content 里以 `<think>...</think>` 块返回，需要 `_strip_thinking_tags` 在 adapter 层抹除。

这是 BookScope 在 adapter 层加 `_strip_thinking_tags` helper 的根本原因——helper 一次写好，未来所有 inline reasoning model 都受益，loop 本体零改动。

---

## 八 · 这不是 model size 或 cost 决定，是训练目标 × 是否见过测试集

讲到这里需要回头看一个问题：**为什么这四家会形成这样的行为光谱？**

最容易想到的解释是 model size——大模型多 tool 多 citation，小模型少 tool 少 citation。但实际上 astron-code-latest 不见得比 MiniMax-M2.7 大；MiniMax-M2.7 是 2026-03-18 发布的新一代 reasoning model，参数规模在前列。这条解释不成立。

第二个解释是 cost——便宜的 API 倾向少 tool 省 token，贵的 API 不在乎。但 deepseek 是四家里最便宜的之一，行为上反而是"标准型"（按 prompt 走），不像 minimax 那样省。这条也不成立。

我现在的判断是：行为光谱是**训练目标**和**是否见过测试集**两个变量的乘积。

### 8.1 训练目标决定 tool 调用倾向

- **astron-code-latest** 的 "code" 后缀暗示它是 code 模型——code 模型训练时大量见过 IDE / agent / function calling 场景，"调工具拿证据"是它的本能行为。这就是为什么它在没有任何 prompt 强制的情况下也会主动调 5+ 次。
- **MiniMax-M2.7** 是通用 reasoning model——它训练时被优化的目标是"推理深度 + 答案质量"，不是"调工具次数"。它倾向于"先想清楚再答"，工具被当成"必要时再用"的备选。这就是为什么它会"够用即停"。
- **deepseek-chat** 的训练目标在 function calling 上的成熟度是 ADR-002 v2 选它做默认的核心理由——它在 OpenAI 兼容协议上"按 prompt 走"的可预测性高于其他国内 LLM。
- **Claude Sonnet 4.6** 在 tool-use 推理深度上是 SOTA——它的训练目标里 "agent / function calling" 优先级很高。

四家训练目标的差异直接决定了行为光谱的"调工具倾向"维度。

### 8.2 训练数据决定"是否见过测试集"

第 26 轮 v3.1+minimax 在公开书 baseline 上的退化是这个变量的实证。MiniMax-M2.7 训练数据几乎肯定包含《明朝那些事儿》全文——它即便被强制至少调 1 次工具，仍偏向用训练记忆补完答案。

这个变量在 BookScope 公开书 baseline 上对所有"训练数据 cutoff 晚于 2009 年"的新一代 LLM 都成立。astron-code-latest（2026-04 上线）、MiniMax-M2.7（2026-03-18 发布）、deepseek-chat、Claude Sonnet 4.6——这四家的训练数据里大概都有《明朝那些事儿》。

为什么 astron 表现好？我现在的假设是 code 模型的训练目标"调工具拿证据"足够强，**压住了**"用记忆作答"的诱惑。它的训练目标决定了它即便见过原文也会去查证——查证是它的工程本能。

minimax 的 reasoning 训练目标"推理深度"则**没有压住**记忆——它的训练目标本身就鼓励"想清楚再答"，"想"自然包含"调用记忆"。

这是为什么我说**老老实实查证程度，不是 LLM 厂商可以单独优化的指标**。它是训练目标 × 训练数据的乘积，单边优化哪一边都不够。

### 8.3 推论：未来作家自己稿子上四家会重新洗牌

如果这个分析正确，未来 BookScope 切到作家自己未公开稿子（minimax 训练里**没见过**）的真用例上时，四家的行为光谱会**重新洗牌**：

- **astron** 大概仍然积极调用 + 高 citation——它的"调工具本能"是训练目标驱动的，与训练数据无关。
- **minimax** 会从"够用即停"变成"必须查证"——它没有记忆可以 fall back 到，被迫把工具用到位。
- **deepseek** 行为变化不大——它本来就按 prompt 走。
- **claude** 仍然高 citation——训练目标主导。

预测：在私域文本上 minimax 的 citation 数会从 5-7 条回升到 astron 同等水平的 10-12 条。这不是 LLM 厂商在优化什么，是"没记忆可作弊"被迫的结果。

第 27 轮候选 a 就是验证这个推论——用作家自己稿子跑 v3.1 batch。如果数据回升，BookScope 在私域文本上的产品价值（evidence-from-text）就有了硬证据。

---

## 九 · 反思：BookScope 为什么没出过"哪家最强"的排行榜

写到这里回到开头的问题。BookScope 跑了四家 LLM、收集了几十组 trace 数据，从来没出过"哪家最强"的横评结论。原因有三：

**第一，"最强"不是 BookScope 想要的指标。** 产品价值（evidence-from-text）需要的是"老老实实查证"，不是"最聪明"。这两件事在公开书 baseline 上甚至会反向相关——越强的模型记忆越深，越倾向用记忆作答。astron 在公开书 baseline 上跑得最好的原因不是它"最强"，是它的 code 训练目标"调工具"本能压过了记忆诱惑。换个角度说，BookScope 的目标客户（作家用自己稿子）场景下，这种比较就更没意义——所有 LLM 都没见过那本稿子，"最强"和"老老实实查"会重新合一。

**第二，BookScope 是 BYOK 工具，不是托管服务。** 用户自带 key、自己选 provider。BookScope 的工程职责是把"行为光谱"透明化——把每家的 tool 调用次数、citation 数、JSON 守约程度、autofix 命中情况都在 trace 里如实记录，让用户自己判断哪家适合自己的稿子。BookScope 不替用户决定。

**第三，"哪家最强"这种横评在 AI 时代是**commodity**——看一眼厂商发布会的 benchmark 就够了，不需要 BookScope 来再跑一遍。BookScope 的独特价值是"在同一个 evidence-from-text 工作场景下，把四家的工程行为差异以 trace 形态留下来"，这是没有任何 benchmark 工具能替代的。第 26 轮 v3.1+minimax 退化 4.8 分这件事在公开 benchmark 上根本看不出来——只有放在 BookScope 这种"必须现场查原文"的产品里才暴露出"训练污染绕开 evidence-from-text 机制"这个失败模式。

这一切让我想清楚一件事：**BookScope 的 adapter 层就是把行为光谱透明化的工程实证场**。每加一个 provider，光谱里多一个数据点；每发现一个 autofix 需求，光谱里多一道工程伤疤。三年后回头看，这套 trace 数据本身比某次"哪家最强"的瞬时排名有价值得多。

---

## 十 · 给 BookScope 未来加新 provider 的 adapter 接入 checklist

如果未来要把 GLM / Qwen / Kimi 接进来，从这次四家光谱的经验里能提炼出一份 checklist：

### 10.1 接入前

- [ ] **确认 provider 是不是 OpenAI 兼容**：是 → 复用 `DeepSeekAdapter` + 新 base_url；否 → 新写 adapter（参考 `AnthropicAdapter` 的 passthrough 形态或新写转换层）。
- [ ] **确认是不是 reasoning model**：是 → adapter 层的 `_strip_thinking_tags` 会自动覆盖；否 → no-op，无需改动。
- [ ] **确认 function calling 是不是支持多轮 + 并行 tool_use**：BookScope 的三 tool 主循环要求每轮可能并行返回多个 tool_use block。OpenAI 标准都支持，国内 OpenAI 兼容端点偶尔有阉割版，需要 sanity check。
- [ ] **确认 model 名字** + 默认 base_url：写进 `bookscope/api/dependencies.py` 的 `DEFAULT_MODEL_BY_PROVIDER` 与默认 base_url 常量。

### 10.2 接入中

- [ ] **写 5-token sanity check 脚本**：先发个 1+1=? 验证 SDK / base_url / api_key 三件套通了，且 response 形态符合 OpenAI 标准（content / tool_calls / usage 字段都在）。
- [ ] **跑 smoke test**：用 `scripts/smoke_test_r1.py` + 新 provider env 变量跑一道通识题。看 outcome / iterations / tool_calls / citation 数。
- [ ] **检查 final answer JSON 是否破裂**：如果 outcome=format_error，看 `LLMFormatError.raw_text` 找具体破裂模式。
  - 裸 ASCII `"` → 已有 `_autofix_unescaped_answer_quotes` + `_autofix_unescaped_quotes_in_all_string_values` 兜底。
  - raw newline / control char → 已有 `_autofix_control_chars_in_strings` 兜底。
  - 新破裂模式 → 加第三层 autofix，并补单元测试。
- [ ] **检查 reasoning trace 形态**：如果 content 字段含 inline 思考块（不一定是 `<think>` 标签，可能是其他自定义标签），扩展 `_strip_thinking_tags` 的正则。

### 10.3 接入后

- [ ] **跑完整 5 题作家 batch**：用 `scripts/run_batch_r1.py` 跑标准 5 题作家诊断（节奏 / 支线密度 / 伏笔回收 / 角色转变 / 设定漂移）。
- [ ] **跑 reviewer agent**：reviewer 自审一遍，看 5 维度 + total。
- [ ] **沉淀到 `docs/internal/experiments/data/`**：batch JSON 文件命名 `<prompt-version>-<provider>-batch-<NN>.json`，留作未来对比。
- [ ] **更新 `docs/internal/STATE.md`**：本轮 work focus 一段，分数对比表，关键诊断。
- [ ] **case-study 文章扩写**：本文（article-03）将来可以扩出"五家行为光谱"、"七家行为光谱"——每家进来加一节。

### 10.4 重要：不要替作家选 default

第 26 轮的训练污染发现告诉我们：**作家最终该用哪家 provider，依赖于他自己稿子的特征**。BookScope 工程层只负责"行为光谱透明化"——把每家的实测 trace 留给作家看；作家自己看完之后选哪家 BYOK，这是产品使用层面的事，不是工程默认值能替代的。

ADR-002 v2 选 deepseek 作"开箱默认"是工程考虑（便宜、稳、协议干净），不代表它在每个作家场景下都是最佳。第 27 轮候选 a 落地之后，可能某些作家场景反而该默认上 astron-code-latest。这件事必须留给作家自己决策。

---

## 〇 · 末段开放讨论：未来作家自己稿子上四家行为是否会重新洗牌？

写完 checklist 我意识到本文最有价值的论点不是已发生的实证，而是一个**还没验证的预测**。

第 26 轮的训练污染发现给了 BookScope 一个研究方向：**在私域文本上重测四家**。如果上面的分析正确，私域文本会让 minimax 的 citation 数从 5-7 条回升到 10+ 条；让 astron 保持高水平；让 deepseek 行为接近不变；让 claude 仍然高 citation。这套预测如果在第 27 / 28 轮的真私域 batch 上被实证，BookScope 的产品定位（evidence-from-text）就有了硬证据。

如果预测**反了**——比如 minimax 在私域文本上仍然偏向"少调工具"——那就说明它的"够用即停"是训练目标驱动的特征，与训练数据无关。这种情况下 BookScope 需要重新思考是否在 prompt 层加更强约束（v3.2: 至少 3 次 search_chunks），或者干脆把 minimax 从默认列表里挪出去。

这个开放问题的答案直接决定了 BookScope 第 27 轮之后的方向。我会在 P1 私域稿子 batch 跑完之后，扩写本文成 article-03b，把"预测 vs 实证"两组数据并排放出来。届时读者就能看到一个完整的"假设 → 验证"研究闭环。

到那时，BookScope 的 adapter 层就不只是把行为光谱透明化了——它会变成验证"训练目标 × 训练数据"假设的实证工具。这种工具在 BookScope 之外也有价值：任何依赖 LLM tool calling 的产品都可以用它来诊断自己的 LLM 选型在公开 benchmark 与私域真实场景之间是否一致。

---

## 关联 ADR / 工件

- `docs/architecture-decisions/002-r1-agent-loop-framework-choice.md`（v2 决策史，v1 锁定 Claude → v2 默认 deepseek）
- `docs/architecture-decisions/003-provider-adapter-layer.md`（LLMClient Protocol + adapter 层设计）
- `bookscope/agent/adapters/deepseek.py`（OpenAI 兼容家族通用 adapter，astron / minimax / deepseek 共用）
- `bookscope/agent/adapters/anthropic.py`（near-passthrough adapter，备选）
- `bookscope/agent/loop.py`（autofix 三层链：定向 quote / 通用 quote / 通用 ctrl-char）
- `docs/internal/experiments/data/v2-batch-01.json`（astron+v2，5 题平均 24.8/25）
- `docs/internal/experiments/data/v3.1-minimax-batch-01.json`（minimax+v3.1，5 题平均 20.0/25，训练污染硬证据）
- `docs/internal/experiments/data/v3-minimax-pilot-no-enforcement.json`（minimax+v3 无强制 tool 的 pilot，0 tool 的"误报"故事）
- `bookscope/agent/prompts/loop_system_prompt_v3.1.md`（强制 tool 至少 1 次的硬约束）

---

> 本文是 BookScope case-study 系列第三篇文章，覆盖第 8 / 16 / 24 / 25 / 26 轮的 cross-provider 实证比较。
>
> **状态**：草稿 · 作者未定稿。
