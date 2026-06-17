# JSON Parse 长征：从定向引号到通用引号到控制字符的四道 autofix

> **状态**：草稿 · 作者未定稿
>
> 视角：工程史诗 / autofix 演化
> 涵盖：第 24 / 25 / 26 轮的四道 autofix
> slug：article-05-json-parse-long-march

---

## 起点：一段被低估的 prompt 约定

在 BookScope 的 r1-agent-loop 代际里，有一段看起来非常无害的 prompt 叫 `citation_format_v1.md`。它的意思一句话就讲完：你这个 LLM，最后给我吐一段 JSON，长这样——

```json
{
  "answer": "<你的综合答复，中文字符串>",
  "citations": [
    {"chapter": <整数>, "snippet": "<原文片段，非空字符串>"}
  ]
}
```

我把它写进 prompt 的时候，心里想的是：JSON 是结构化输出最普适的协议，所有家的 LLM 都被 OpenAI / Anthropic / DeepSeek 这一线训练得"会输出 JSON"。我自己再把 `answer` / `citations` 两个字段写得明明白白，外加最小 schema 约束（`citations` 必须是 list、必须有 chapter / snippet 字段、snippet 非空），LLM 就该照做。

这是我那时候的天真假设。

事实是：从 `r1-agent-loop` 第 24 轮开始，到第 26 轮（也就是我现在写这篇文章的当下），我在 `bookscope/agent/loop.py` 里堆了**四道 autofix**——一道针对一个具体 LLM 的具体违约方式。每一道 autofix 都不是我闭门造车，是某次跑 query 当场炸掉、我把 `raw_text` 挂上 trace、看了具体破裂位置之后，回手补上的工程兜底。

这篇文章是这条 autofix 链的一份完整工程史。我会按时间顺序把四道 autofix 的发现现场、raw text 的真实样子、状态机或正则实现、和单测策略一道一道讲清楚。中间会贴大量真实代码——这不是讲解性的伪代码，是 BookScope 当前主线分支上跑得起的代码。

我想留下的不是"看，我做了 autofix"，而是另一件更重要的事：

> **BookScope 与 LLM 的对话本质上是一种协议博弈**。prompt 约定 JSON 输出，但每家 LLM 都在某种细微方式上违约。autofix 链不是 defensive 工程，是"实战暴露 → 精确响应"的迭代记录。每一道 autofix 对应一种 LLM 的行为偏差，按发现顺序展开就是一份 cross-provider 实战兼容性目录。

按下面这条时间线展开：

| 轮次 | autofix 名 | 触发 LLM | 问题类型 |
|---|---|---|---|
| 第 24 轮 | `_autofix_unescaped_answer_quotes` | 讯飞星辰 astron-code-latest | answer 字段裸 ASCII `"` |
| 第 25 轮 | `_autofix_unescaped_quotes_in_all_string_values` | astron-code（reviewer 输出） | 任意嵌套字段裸 ASCII `"` |
| 第 26 轮 | `_strip_thinking_tags` | MiniMax-M2.7 | content 内 `<think>...</think>` |
| 第 26 轮 | `_autofix_control_chars_in_strings` | MiniMax-M2.7（reviewer 输出） | string 内 raw `\n` / `\r` / `\t` |

四道 autofix 一串读下来你会发现：每个 LLM 都在用自己的方式"几乎对"，但都不严格守约。我今天和 LLM 工作的体感是：**没有"会输出 JSON"这件事，只有"在某种 prompt + 某种 model + 某种话题下，恰好这次输出了 JSON"**。

---

## 第一道：第 24 轮的 `_autofix_unescaped_answer_quotes`

### 触发现场

第 24 轮是 P1 作家场景的首次跑通。我那次问 BookScope 的题是关于《明朝那些事儿》第 17 章前后李善长被诛杀的铺垫连贯性——这是作家口味的问题，不是百科口味的问题：作家想看的是叙事铺垫够不够，不是百科条目对不对。

第一次跑：73.9 秒、11 条 citation、答案像样。

第二次跑：当场炸了。trace 上的 `outcome` 是 `format_error`，挂着 raw_text。我把 raw_text 拷出来肉眼读，看到了类似这样的东西（脱敏到示意级别，原始结构一致）：

```text
{"answer": "书中点明他"外表宽厚，却心胸狭窄"的性格底色，并在第 17 章前后通过三次铺垫预示了诛杀。", "citations": [{"chapter": 17, "snippet": "原文片段..."}]}
```

肉眼看是"对的"——它确实就是想引用原文的"外表宽厚，却心胸狭窄"那一段。问题在 JSON 这一层：

- `answer` 字段在 JSON 里是字符串。字符串的边界是 ASCII 直双引号 `"`。
- `"外表宽厚` 那一段里的开头那个 `"` 不是 escape 出来的 `\"`，是裸的 ASCII `"`。
- `json.loads` 看到那个裸 `"` 就认为 `answer` 字符串结束了。

对 `json.loads` 来说，这段输入的 `answer` 值其实是 `"书中点明他"`，后面跟了一段 `外表宽厚，却心胸狭窄`——它会在 `外` 这个汉字处报"Expecting ',' delimiter"，因为它不知道这汉字算什么。

我把 `citation_format_v1.md` 里关于内嵌引号的一节贴出来：

```markdown
## 内嵌引号规则（违反会导致 JSON parse 失败）

`answer` 与 `snippet` 字段本身就是 JSON 字符串，**内部绝对不能出现未转义的 ASCII 直双引号 `"`**。

正确做法（按优先级）：
1. **中文文本优先用中文全角引号 `"…"`**——例如：书中点明他`"外表宽厚，却心胸狭窄"`。JSON 层看不到全角引号，最安全。
2. 英文词句必须用直引号时，**写成 `\"…\"`**（反斜杠转义）。
3. **禁止**裸 `"…"`——例如 `"answer": "他说"你好"然后走了"` 会在 `"你好"` 的第一个 `"` 处破坏 JSON 结构，整个 final answer 被判格式错误。
```

意思都写得很清楚了。但 astron-code-latest 不读这一段。或者它读了——但下意识反应是"我要引用原文，原文是中文，中文当然就用 ASCII 双引号引"。

这就是我那个晚上学到的第一件事：**prompt 写"硬约束"是没有意义的，LLM 是统计模型，不是 schema validator**。它能违背的就一定会违背——只看违背的概率。

### 选定向 autofix 而不是逼 LLM 改

我那时候有两条路：

**路径 A**：再去 prompt 上加压。改成"如果你违反了我会拒绝你的回复"——LLM 框架确实会拒绝：`_parse_final_answer` 里的 `LLMFormatError` 一抛，loop 会回写一条补正提示进 messages 让 LLM 重试。

**路径 B**：写 autofix。承认 LLM 会违约，改成在 parse 层做最后一道兜底。

我选了 B。理由是：

1. 路径 A 很贵。补正一次 = 重新跑一轮 LLM 调用，token 烧、latency 涨。第 24 轮那次 query 的 LLM 调用本身就是 70+ 秒的事。
2. 路径 A 不一定有效。LLM 重试还是可能继续违约——尤其如果是 model 本身的训练偏置而不是 prompt 注意力问题。
3. 我盯过具体 raw_text 之后，发现这是一个**有结构的违约**——不是 LLM 在乱来。它就是把 `answer` 内部的引用文字用 ASCII `"` 裹住，仅此一种模式。

第三条很关键。"有结构的违约"意味着**有结构的修复**可能。

### 实现：靠位置约束做定向修

我在 `loop.py` 写了 `_autofix_unescaped_answer_quotes`：

```python
_AUTOFIX_ANSWER_HEAD_RE = re.compile(r'"answer"\s*:\s*"')
_AUTOFIX_CITATIONS_TAIL_RE = re.compile(r'"\s*,\s*"citations"\s*:')


def _autofix_unescaped_answer_quotes(json_text: str) -> str | None:
    """针对 astron-code 等 code 模型在 answer 字段裸用 ASCII `"` 的破裂修复。

    前提：顶层 schema 固定为 ``{"answer": "...", "citations": [...]}``，且字段顺序
    answer 先于 citations（citation_format_v1 明文要求）。本函数用这个位置约束
    定位 answer 字符串值的起止边界，然后把中间所有未经 `\\` 转义的裸 ASCII `"`
    补上转义，返回修复后的 JSON 文本。

    返回 ``None`` 表示"无法定位 answer 值的边界"，调用方据此抛更明确的错误。
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

读法是这样的：

1. `_AUTOFIX_ANSWER_HEAD_RE` 找 `"answer": "` 这个开头串——它一定出现，因为 prompt 强约束 JSON schema 第一字段就是 answer。
2. `_AUTOFIX_CITATIONS_TAIL_RE` 找 `", "citations":` 这个结束串——它一定出现，因为 prompt 强约束第二字段是 citations 而不是别的。
3. 这两个 regex 把 answer 字段值的起止位置框出来。
4. 在这两个位置之间，用 `re.sub(r'(?<!\\)"', r'\\"', ...)` 把所有"前面没有 `\`"的裸 ASCII `"` 转成 `\"`。负向断言 `(?<!\\)` 是关键——已经合规转义的 `\"` 不再处理，避免把 `\"` 变成 `\\"`。

最关键的位置约束有两条：

- **answer 字段在 citations 字段之前**——这是 `citation_format_v1.md` 明文要求的，prompt 训得 LLM 守这个顺序。
- **顶层 schema 只有这两个 key**——所以 `"\s*,\s*"citations"` 一定意味着 answer 值的真结束。

这两条约束让我可以**完全不做 JSON 通用解析**，只用纯 regex 做位置定位 + 内部 substitute——快、精准、不引入新依赖。

### 单测策略：三个最小用例

每道 autofix 我都坚持三件事：

1. **typical-input-fixed**：典型违约输入应能被修复并 parse 成功
2. **clean-input-returns-None**：合规输入应返回 None，让上层不必重复 parse
3. **preserves-already-escaped**：已经合规转义的 `\"` 不会被二次转义

`tests/agent/test_agent_loop.py` 第 791-808 行的用例覆盖了第 1 条：

```python
def test_unescaped_ascii_quotes_in_answer_autofixed(self) -> None:
    """astron-code 等模型在 answer 字段裸用 ASCII `"` 引用原文时的兜底修复。"""
    broken = (
        '{"answer": "书中点明他"外表宽厚，却心胸狭窄"的性格底色。", '
        '"citations": [{"chapter": 17, "snippet": "原文"}]}'
    )
    client = _FakeClient([_FakeResponse(content=[_text_block(broken)])])
    loop = _make_loop(client)
    result = loop.query("q")
    assert result.trace.outcome == "success"
    assert '"外表宽厚' in result.answer
    assert "心胸狭窄" in result.answer and "性格底色" in result.answer
    assert result.citations == [{"chapter": 17, "snippet": "原文"}]
```

这个 case 是直接从第 24 轮的 raw_text 里截取脱敏后写进单测的——我刻意不用 helper 函数 `_final_json_text`，因为 helper 会经过 `json.dumps` 二次正确转义，反而把破裂场景洗掉了。要测破裂，就要手写 raw JSON 字符串。

第 825-838 行覆盖第 3 条：

```python
def test_wellformed_json_with_escaped_quotes_not_touched(self) -> None:
    """合法的 JSON（内嵌引号已正确 `\\"` 转义）不走 autofix 路径。"""
    clean = (
        '{"answer": "合法转义的内嵌引号 \\"like this\\" 应该原样还原。", '
        '"citations": [{"chapter": 1, "snippet": "原文"}]}'
    )
    client = _FakeClient([_FakeResponse(content=[_text_block(clean)])])
    loop = _make_loop(client)
    result = loop.query("q")
    assert result.trace.outcome == "success"
    assert '"like this"' in result.answer
    assert '\\"' not in result.answer
```

这条很重要——它防回归。如果未来某次我手抖把 `(?<!\\)` 拿掉，这条单测会立刻 RED：原本合规的 `\"` 会被当成裸引号继续转义成 `\\"`，answer 里就会冒出反斜杠。这是 autofix 工程里最容易写错的地方：**修一种破裂的同时不能制造另一种破裂**。

第 760-789 行覆盖了 markdown fence + 裸引号的复合场景——LLM 经常顺手把 JSON 包在 ```json ... ``` 里，autofix 要在 strip fence 之后跑：

```python
def test_unescaped_quotes_in_fenced_json_also_fixed(self) -> None:
    """markdown fence 包裹 + answer 内裸引号 复合失败场景也能 autofix。"""
    broken_fenced = (
        '```json\n'
        '{"answer": "他说"你好"然后走了", '
        '"citations": [{"chapter": 1, "snippet": "片段"}]}\n'
        '```'
    )
    client = _FakeClient([_FakeResponse(content=[_text_block(broken_fenced)])])
    loop = _make_loop(client)
    result = loop.query("q")
    assert result.trace.outcome == "success"
    assert '"你好"' in result.answer
    assert result.citations == [{"chapter": 1, "snippet": "片段"}]
```

这个 case 里 LLM 同时违反两条规则（fence 包裹 + 裸引号），autofix 链得能串起来——`_strip_code_fence` 先剥围栏，`_autofix_unescaped_answer_quotes` 再修引号，组合起来才通。

### 第一道 autofix 的代价表

回头看，第一道 autofix 让我多写了：

- 50 行实现代码（`_autofix_unescaped_answer_quotes` + 两个 regex 常量）
- 3 个单测用例（typical / clean / preserves-escaped）
- 1 段 `_parse_final_answer` 里的串联调用

收益是：astron-code-latest 的破裂率从 100% 直接降到 0%。第 24 轮当晚我用李善长那道作家题反复跑了 3 次没再炸。

但故事远远没结束。

---

## 第二道：第 25 轮的 `_autofix_unescaped_quotes_in_all_string_values`

### 触发现场：reviewer 是个新世界

第 25 轮我做的事是**配 AI reviewer**——按 NORTH_STAR 的"作家第一读者反馈"原则，让另一个 LLM 当审稿人评 BookScope 的 answer 质量。reviewer 输出 5 维度评分 + per-维点评 + overall + top issues + single_most_valuable_improvement。

reviewer 的 JSON 比 loop 复杂多了：

```json
{
  "scores": {
    "structural_judgment": 5,
    "evidence_density": 5,
    "honesty": 5,
    "actionability": 4,
    "cross_chapter_coherence": 5
  },
  "per_dimension_comment": {
    "structural_judgment": "明确判断如\"连贯\"且\"五个节点\"，远超复述",
    "evidence_density": "证据命中\"狗\"之隐喻，引用密度高"
  },
  "overall": "这份答复是\"极出色\"的第一读者反馈。",
  "top_issues": ["缺乏\"批判性\"审视", "第五节点\"悬空\""],
  "single_most_valuable_improvement": "加入\"心理转变\"的补写建议"
}
```

我把 reviewer 跑起来的第一次，astron-code 给我吐了类似这样的东西：

```text
{"scores": {"structural_judgment": 5, ...},
 "per_dimension_comment": {
   "structural_judgment": "明确判断如"连贯"且"五个节点"，远超复述",
   "evidence_density": "证据命中"狗"之隐喻"
 },
 "overall": "这份答复是"极出色"的第一读者反馈。",
 ...}
```

破裂位置一目了然——和第一道 autofix 是同一种 ASCII 引号违约，只是这次出现在 `per_dimension_comment.structural_judgment`、`per_dimension_comment.evidence_density`、`overall`、`top_issues[0]`、`top_issues[1]`、`single_most_valuable_improvement` 这一堆嵌套字段里。

定向 autofix `_autofix_unescaped_answer_quotes` 完全不管用——它只认 `"answer": "..."` 这个顶层结构，reviewer 的 JSON 顶层第一个字段是 `scores`，第二个是 `per_dimension_comment`，根本走不到 head regex 的命中分支。

我那时候面对一个工程决策点：

- **方案 1**：为 reviewer 写专门的定向 autofix——做一个对 `per_dimension_comment.*` / `overall` / `top_issues[*]` / `single_most_valuable_improvement` 都生效的版本。
- **方案 2**：写一个**通用** autofix——对任意嵌套字段里的裸引号都生效。

方案 1 短期看快、能用；但意味着 reviewer schema 一改我就得改 autofix。第 25 轮我刚把 reviewer rubric 定下来，下一轮（其实就是第 26 轮，那时还没发生）很可能要改 schema——加 dimension、改 dimension 的命名。

方案 2 难一点，但写一次永久。而且我隐约知道：如果 LLM 在 reviewer 里这么干，那它在 loop 里只要哪天 schema 复杂一点（比如 citations 的 snippet 也开始裸引号），就还会再这么干。

我选了方案 2。

### 实现：状态机 + peek 启发式

通用 autofix 的难点是：**不依赖位置约束的情况下，怎么判断"这个 ASCII `"` 是字符串真结束，还是字符串内部的裸引号"**。

我用的启发式叫 **peek 后续非空白字符**：

> 处于 JSON 字符串 value 内部时遇到 `"`，往后跳过所有空白字符，看下一个非空白字符是什么——
>
> - 如果是 `,` / `}` / `]` / `:`，或者已到 EOF，说明这个 `"` 后面接的是 JSON 结构层 token，那它就是字符串真结束。
> - 否则，说明它后面接的是字符串内容（汉字 / 字母 / 标点），那它就是裸内嵌，要转义。

这个启发式来源于一个观察：**JSON 语法里，字符串结束的 `"` 后面必然跟结构层 token**。值的字符串后面只能跟 `,`（数组或对象的下一个元素分隔）、`}`（对象结束）、`]`（数组结束），或者一直到末尾；key 的字符串后面只能跟 `:`。除此之外的字符意味着 `"` 不是真结束。

实现是一个手写状态机：

```python
_JSON_STRUCTURAL_AFTER_QUOTE = frozenset(",}]:")
_JSON_WHITESPACE = frozenset(" \t\n\r")


def _autofix_unescaped_quotes_in_all_string_values(json_text: str) -> str | None:
    """通用 autofix —— 状态机扫描，对任意字符串 value 内部的裸 ASCII `"` 转义。

    启发式判定：处于 JSON 字符串 value 内部时遇到 `"`，peek 后续非空白
    字符；若是 ``,``/``}``/``]``/``:`` 或 EOF，视为字符串真结束；否则
    视为裸内嵌，插入 `\\` 转义。
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
        # in_string
        if ch == "\\":
            # 复制转义对（比如 \" / \\ / \n）
            out.append(ch)
            if i + 1 < n:
                out.append(json_text[i + 1])
                i += 2
            else:
                i += 1
            continue
        if ch == '"':
            # peek 下一个非空白字符
            j = i + 1
            while j < n and json_text[j] in _JSON_WHITESPACE:
                j += 1
            if j >= n or json_text[j] in _JSON_STRUCTURAL_AFTER_QUOTE:
                # 真结束
                in_string = False
                out.append(ch)
                i += 1
            else:
                # 裸内嵌，转义
                out.append("\\")
                out.append(ch)
                fixed = True
                i += 1
            continue
        out.append(ch)
        i += 1
    if not fixed:
        return None
    return "".join(out)
```

几个工程细节：

1. **跨 escape pair**：遇到 `\` 时连同下一字符一起拷贝。这意味着 `\"` 这个合规转义对被原样保留，不会触发 peek 启发式。换句话说，**autofix 不动已经合规的部分**。
2. **peek 跨空白**：JSON 允许 `"foo"   ,` 这样的结构层带空白。peek 时要跳过 whitespace 才能看到真正的下一 token。
3. **`fixed` flag**：只有真插了 `\` 才返回修复版本；否则返回 None。这让上层知道 "这次没动 → 不必重新 parse"。

### 与定向 autofix 的关系：先精准后兜底

通用 autofix 写出来之后，我有两个选择：

- 把定向 autofix 删掉，全用通用版
- 保留定向 autofix，先试它，命中不到再退到通用版

我选了后者。`_parse_final_answer` 里的调用链是这样：

```python
autofixed = _autofix_unescaped_answer_quotes(json_slice)
if autofixed is None:
    autofixed = _autofix_unescaped_quotes_in_all_string_values(
        json_slice,
    )
if autofixed is None:
    raise LLMFormatError(
        "failed to parse JSON and autofix did not apply"
    ) from None
```

理由是：

1. **定向 autofix 更精准**——它知道顶层 schema 是 `answer` + `citations`，做的事不会出错。
2. **定向 autofix 更安全**——它有位置约束，不会误伤别的字段。
3. **通用 autofix 是兜底**——它有启发式，理论上会有边界 case。

把它们串成"先精准后兜底"是工程上比较稳的姿态。如果将来某天通用 autofix 在某个特定 case 下误判了，我可以把那个 case 在定向 autofix 里专门处理掉，绕开通用版本。

### 已知 limitation：纯英文场景的误判

我在 docstring 里诚实地写了通用 autofix 的边界：

```python
"""
**已知 limitation**：纯英文文本中 `"word", next` 这样的场景会让通用
autofix 误判（"word" 后的 `",` 看起来像真结束）。本项目主用场景是
中文叙事答复（中文有全角标点 `，`/`。`/`）`，误判概率极低），
所以接受这个 trade-off。未来若要支持英文作家题，需切到真正的
lenient JSON parser（json5 / demjson3）。
"""
```

什么意思？

假设 LLM 输出了一段英文答复：

```text
{"answer": "He said "hello", then walked away.", "citations": [...]}
```

按 peek 启发式扫到第一个内嵌 `"` 时：

- 当前位置是 `"` 后面跟着 `hello`
- 下一个非空白字符是 `h`，不在 `,}]:` 集合里 → 判定为裸内嵌 → 转义。OK。

继续扫到第二个内嵌 `"`（`hello` 后面那个）：

- 当前位置是 `"` 后面跟着 `, then`
- 下一个非空白字符是 `,` → 在 `,}]:` 集合里 → **判定为字符串真结束** → 不转义。

这是误判。状态机会以为 `answer` 字段值就是 `He said "hello`，后面 `then walked away.` 全成了游离 token。后续 `json.loads` 会在 `then` 处再次报错。

为什么我接受这个 trade-off？

1. **BookScope 的核心场景是中文小说**。NORTH_STAR 第 1 条："作者本人作为长篇网络小说创作者的第一读者工具"——作者写的是中文小说，answer 里的引用绝大多数是中文。
2. **中文叙事文本天然用全角标点**。`"hello"` 在中文里会写成 `"hello"`——而中文全角引号 `"` 不是 ASCII `"`，状态机根本不把它当字符串边界，直接跳过。这是个意外的福利。
3. **citation_format_v1.md 第 1 条优先级**就是"中文文本优先用中文全角引号"——如果 LLM 跟着 prompt 走，这个 limitation 永远不触发。
4. **ASCII 引号违约场景的中文文本占比**在 P1 验证里是 100%——我从来没见过 astron-code 在英文段落里裸用 ASCII 引号。

未来如果要做英文小说支持（这是 NORTH_STAR 的中长期目标之一），我需要切到真正的 lenient JSON parser。`json5` 和 `demjson3` 是两个候选——它们都把 JSON5 / 宽松 JSON 当一等公民解析，不依赖启发式。但那是另一篇文章。

### 单测策略：reviewer 形态 + 嵌套 + 边界

通用 autofix 有 4 个单测：

第 840-871 行覆盖 reviewer 的典型嵌套结构：

```python
def test_generic_autofix_unit_reviewer_shape(self) -> None:
    """通用 autofix 单元测试——覆盖 reviewer 的典型嵌套结构。"""
    import json as _json
    from bookscope.agent.loop import (
        _autofix_unescaped_quotes_in_all_string_values,
    )

    broken = (
        '{"scores": {"a": 5, "b": 4}, '
        '"per_dimension_comment": {'
        '"a": "明确判断如"连贯"且"五个节点"，远超复述", '
        '"b": "证据命中"狗"之隐喻"'
        '}, '
        '"overall": "这份答复是"极出色"的第一读者反馈。", '
        '"top_issues": ["缺乏"批判性"审视", "第五节点"悬空""], '
        '"single_most_valuable_improvement": "加入"心理转变"的补写建议"}'
    )
    # 原文炸
    import pytest as _pt
    with _pt.raises(_json.JSONDecodeError):
        _json.loads(broken)
    # autofix 后通
    fixed = _autofix_unescaped_quotes_in_all_string_values(broken)
    assert fixed is not None
    obj = _json.loads(fixed)
    assert obj["scores"]["a"] == 5
    assert '"连贯"' in obj["per_dimension_comment"]["a"]
    assert '"狗"' in obj["per_dimension_comment"]["b"]
    assert '"极出色"' in obj["overall"]
    assert len(obj["top_issues"]) == 2
    assert '"批判性"' in obj["top_issues"][0]
    assert '"心理转变"' in obj["single_most_valuable_improvement"]
```

这个 case 我特意把所有可能违约的字段都塞进去——`per_dimension_comment` 的两个嵌套 string、`overall` 的 string、`top_issues` 数组里的两个 string、最后的 `single_most_valuable_improvement` string。状态机要能处理对象嵌对象、数组里的字符串、跨多层嵌套——一个 case 全覆盖。

第 873-880 行是 clean-input：

```python
def test_generic_autofix_returns_none_on_clean_json(self) -> None:
    """没有裸引号的 JSON 应返回 None（避免多余 parse）。"""
    clean = '{"a": "hello", "b": "world", "c": [1, 2, 3]}'
    assert _autofix_unescaped_quotes_in_all_string_values(clean) is None
```

第 882-894 行是 preserves-escaped：

```python
def test_generic_autofix_preserves_escaped_quotes(self) -> None:
    """已正确转义的 `\\"` 不被二次处理。"""
    clean = '{"a": "he said \\"hi\\""}'
    import json as _json
    assert _json.loads(clean)["a"] == 'he said "hi"'
    assert _autofix_unescaped_quotes_in_all_string_values(clean) is None
```

第 896-913 行是 reviewer 场景在 loop 层的 end-to-end：

```python
def test_generic_autofix_rescues_nested_unescaped_quotes(self) -> None:
    """通用 autofix 能处理嵌套字段里的裸引号（reviewer 场景模拟）。"""
    broken = (
        '{"answer": "简单回答。", '
        '"citations": [{"chapter": 1, '
        '"snippet": "原文里他"说"了一句话。"}]}'
    )
    client = _FakeClient([_FakeResponse(content=[_text_block(broken)])])
    loop = _make_loop(client)
    result = loop.query("q")
    assert result.trace.outcome == "success"
    assert '"说"' in result.citations[0]["snippet"]
```

注意这个 case：**裸引号出现在 `citations[0].snippet` 里**。定向 autofix 只管 `answer` 字段，覆盖不到 `snippet`——通用 autofix 才能救。这个 case 同时验证两件事：(a) 通用 autofix 能扫嵌套字段；(b) 它在 loop 的端到端调用链里能挂上。

### 第二道 autofix 的代价表

第二道 autofix 让我多写了：

- 65 行实现代码（状态机 + 两个常量集合）
- 4 个单测用例（reviewer-shape / clean / preserves-escaped / nested-end-to-end）
- 1 段 docstring 解释 limitation 和 trade-off

但更重要的是：**它把 JSON 修复从"针对一个 LLM 的一种违约"扩展到了"针对任意 LLM 的一类违约"**。这是 cross-provider 兼容性目录的第一行。

第 24 / 25 轮过完，我以为长征就到这里了。然后第 26 轮，作者把 provider 切成了 MiniMax-M2.7。

---

## 第三道：第 26 轮的 `_strip_thinking_tags`

### 触发现场：reasoning model 的副作用

第 26 轮的开端只有一句话："切到 minimax 2.7"。

我那时候已经把 DeepSeekAdapter 写得 provider-agnostic——只要 base_url 改一行 + api_key 改一行，就可以从 DeepSeek 切到任何 OpenAI 兼容 provider。MiniMax 的 base_url 是 `https://api.minimaxi.com/v1`，model 名是 `MiniMax-M2.7`。改完跑了一个 5-token sanity check。

content 字段长这样：

```text
<think>
The user is asking me to respond. I should think about this carefully...
Let me consider the question and provide a structured answer.
</think>

{"answer": "...", "citations": [...]}
```

完蛋。MiniMax-M2.7 是 reasoning model——它把"思考链"以 `<think>...</think>` 标签的形式 inline 在 content 字段里返回。这对终端用户是好事（看模型怎么想），但对 BookScope 是灾难——`_parse_final_answer` 拿到这段 content 之后会先试 `json.loads`，失败；再试 `_extract_first_json_object` 找第一个花括号对，找到的是 `{` 后面跟着 `"answer": "..."`——但前面那一大段 `<think>` 文字全被当成 LLM 的"自由文本前缀"。

这个 case 的特殊之处在于：**`_extract_first_json_object` 其实能找到正确的 JSON**——它确实从第一个 `{` 扫到匹配的 `}`，把 thinking 段当成前缀跳过了。

那为什么还需要 strip 呢？因为：

1. **`<think>` 块里可能有花括号**——LLM 思考时会写代码片段、JSON 示例。`{` 出现在 thinking 里，`_extract_first_json_object` 就可能从那里开始抓，抓到的不是真 JSON。
2. **`<think>` 块里的引号会污染状态机**——通用 autofix 状态机会把 thinking 段里的 ASCII `"` 当成字符串边界来 toggle `in_string`，扫完 thinking 段之后，到了真 JSON 起点时 `in_string` 状态可能已经错了。
3. **token 浪费**——thinking 段经常上千 token，downstream 流程都得处理这些噪声。

最干净的修法：**在 adapter 层 strip 掉 thinking 标签**，让 loop 拿到的 content 已经是纯 final answer。

### 实现：在 adapter 层做 surgical 处理

我把 strip 放在了 `bookscope/agent/adapters/deepseek.py`——也就是 OpenAI → Anthropic 转换层：

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

调用点在 `_from_openai_response` 把 content 拼出来时：

```python
text = getattr(message, "content", None)
if text:
    text = _strip_thinking_tags(text)
    if text:
        content.append({"type": "text", "text": text})
```

### 为什么 strip 放 adapter 层而不是 loop 层

这是第三道 autofix 最关键的设计决策。

我有两条候选路径：

**路径 A**：在 `_parse_final_answer` 里加一个 `_strip_thinking_tags` 调用——和 `_strip_code_fence` 并列。
**路径 B**：在 `DeepSeekAdapter._from_openai_response` 里 strip——content 在到达 loop 之前就已经是干净的。

我选了 B，理由是：

1. **复用范围**。loop 用 content、reviewer 用 content、未来的 KG extractor（minimal_kg.py 那一支）也会用 content。strip 放 adapter 层，下游所有 consumer 都自动受益，零侵入。
2. **provider-specific 处理放 adapter-specific 位置**。`<think>` 标签是 reasoning model 的产物——MiniMax-M2.7 / deepseek-r1 / qwen-qwq / glm-zero 都会用。这是 provider 层的现象，不是 loop 层的现象。loop 不该知道 "我在和 reasoning model 说话"。
3. **non-reasoning model 的零成本**。astron-code-latest / claude-sonnet / gpt-4 都不会输出 `<think>`——`if "<think" not in text.lower(): return text` 这一行 fast path 让它们零开销。

`<think` 这个 fast path 是个性能上的微小但重要的细节。`re.sub` 即使没有命中也要扫整个字符串——对一段 4000 token 的 content 做无意义 regex 扫描是浪费。`in` 操作符是字符串字面量搜索，CPython 内部用 SIMD 优化，比正则快一个数量级。

### 兜底：开放 think 标签

注意第二条 regex `_OPEN_THINK_RE`——它是 `<think\b[^>]*>.*` 而不是 `<think\b[^>]*>.*?</think>`。

这个兜底是给 max_tokens 截断的场景：

```text
<think>
The user is asking about...
[模型还在 thinking 时被 max_tokens 截断]
```

模型还没写完 thinking 就被强制 stop——`</think>` 永远不会出现。第一条 regex `_THINK_BLOCK_RE` 找不到匹配，会原样保留。这种 case 下 content 里只有 thinking 没有 final answer，本来就该 fail。但残留的 `<think>` 起始标签 + 半截思考文本会让下游 `_parse_final_answer` 报"no valid JSON object"——这没问题。但 trace 里挂的 raw_text 全是 thinking 噪声，post-mortem 时刺眼。

所以第二条 regex 兜底——找到 `<think>` 起始标签后，截到末尾全干掉。这样 trace 里看到的 raw_text 是干净的"我没写出 JSON"——而不是"我在思考然后被截断了"。

### 第三道 autofix 的代价表

第三道 autofix 让我多写了：

- 13 行实现代码（一个 helper + 两个 regex）
- 1 行 `_from_openai_response` 里的调用
- 0 个 loop 层修改

它是四道里最便宜的一道——因为它不在 loop 层，不污染 _parse_final_answer 的串联逻辑。但它的影响最广——loop / reviewer / 未来的 KG extractor 都受益。

第 26 轮跑通的第一个 query 就是 v3 prompt + minimax 跑 q1。dur 179s / cite 6 / total 17/25——分数虽然不高（这是另一个故事，见后），但**JSON parse 全程没炸**。`<think>` strip 第一战告捷。

---

## 第四道：第 26 轮的 `_autofix_control_chars_in_strings`

### 触发现场：reviewer 又坏了

第 26 轮的故事进行到一半——v3 prompt 跑出 17/25 之后，我意识到 minimax 用训练记忆 hallucinate。我写了 v3.1 prompt，加了三条硬约束（至少一次 tool 调用 / 禁靠训练记忆 / "我已经知道" ≠ "我已经查过"）。

第二次 pilot 跑 v3.1 时，BookScope 这一端的 generation 通了——tool 调用 7 次（5 search + 1 chapter_range + 1 search），cite 7 条，dur 217s。然后到 reviewer 这一步又炸了。

报错信息很具体：

```text
Invalid control character at: line 14 column 106 (char 1234)
```

我去翻 reviewer 的 raw_text，定位到 line 14 column 106：

```text
"per_dimension_comment": {
  "structural_judgment": "这份答复在结构层面有以下三个判断
其一，节奏密度评估"密集"是有依据的
其二，五个节点的展开符合作家视角
其三，伏笔回收的判断略显薄"
}
```

发现了——line 14 是 `per_dimension_comment.structural_judgment` 这个 long comment 字段的内部。column 106 那个位置是 raw `\n`——MiniMax-M2.7 在长字符串里直接塞了换行符，没有转义成 `\n`。

JSON spec 严格规定字符串内的 control character (`\n` / `\r` / `\t`) 必须 escape。`json.loads` 是个严格 parser，碰到 raw newline 就报"Invalid control character"。这是和 ASCII 引号违约同一类问题，但触发条件不一样——前者是模型想引用文本，后者是模型想换行排版。

### 这是 minimax 特有问题吗

这是个值得停下来想的问题——**为什么 astron-code 没出过这个？为什么是 minimax 才出？**

我的猜测：reasoning model 在 thinking 之后写 final answer 时，倾向于把答案分行写。它在内部表征里的"换行"是真换行，而不是字面 `\n`。在写出 JSON 时，它没有显式触发"我现在在 JSON 字符串内、要 escape"的约束。astron-code 不是 reasoning model，它的输出风格更紧凑，更像"按 prompt 直接写"——一段 string value 经常是一长行。

这是个观察，不是定论。我没在所有 reasoning model 上验证过。但这个观察支持一个工程判断：**autofix 链不可能完结**。每出一个新一代模型，就可能出一种新违约方式。

### 实现：状态机 + escape 三个 control char

control-char autofix 的实现和通用 quote autofix 是同构的——都是状态机扫描 + 在 string 内时做转义。区别在转义对象：

```python
def _autofix_control_chars_in_strings(json_text: str) -> str | None:
    """通用 autofix —— string value 内裸 ASCII control char (\\n / \\r / \\t)
    转成 ``\\n`` / ``\\r`` / ``\\t`` escape。

    背景：MiniMax-M2.x 等 reasoning model 在生成多行 JSON 字符串时，常把
    raw newline 直接写进 ``"..."`` 内部，json.loads 报 ``Invalid control
    character at: line N column M``。reviewer 的长 dimension 评语尤其
    多见。

    与 ``_autofix_unescaped_quotes_in_all_string_values`` 串联使用：
    quote 修先做 → 仍 parse 失败再试 control-char 修 → 再 parse。
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
        # in_string
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

读法：

1. `in_string` 状态机和通用 quote autofix 一致——`"` 切换状态、`\X` 跳过 escape pair。
2. **关键差别**：control-char autofix 不需要 peek 启发式。在 string 内遇到 `"` 直接当成真结束——因为这道 autofix 假设输入已经过通用 quote autofix 处理（或者不需要 quote autofix）。
3. 在 string 内时，遇到 raw `\n` / `\r` / `\t` 直接 escape 成 `\\n` / `\\r` / `\\t`。
4. struct 层的 `\n`（用于格式化）保留——状态机当时在 `in_string=False`，会走 `out.append(ch)` 原样保留。

### 单测：验证 struct 层 newline 不被动

最关键的一个 case 是验证：**JSON 结构层的 newline（用于格式化）不被改动**。

```python
def test_control_char_autofix_does_not_touch_outside_string(self) -> None:
    """JSON 结构层的 newline（用于格式化）不被改动。"""
    import json as _json
    from bookscope.agent.loop import _autofix_control_chars_in_strings

    # struct 层的 \n 是合法的（whitespace），string 内的 \n 是非法的
    broken = '{\n  "comment": "第一行\n第二行"\n}'
    with __import__("pytest").raises(_json.JSONDecodeError):
        _json.loads(broken)
    fixed = _autofix_control_chars_in_strings(broken)
    assert fixed is not None
    # struct 层 newline 仍在（格式化保留），但 string 内 newline 已 escape
    assert _json.loads(fixed)["comment"] == "第一行\n第二行"
```

这个 case 很重要。MiniMax-M2.7 输出的 JSON 经常是格式化的（每个 key 一行）——struct 层有大量合法 newline。autofix 不能见 newline 就 escape，否则 JSON 结构会被破坏。状态机的 `in_string` flag 是这道 autofix 的核心——它把"在字符串内"和"在结构层"两种 context 分开。

其他三个 case：

```python
def test_control_char_autofix_escapes_raw_newline(self) -> None:
    """string value 内 raw `\\n` autofix 转 `\\\\n`（minimax-m2 reviewer 实战）。"""
    broken = '{"comment": "第一行\n第二行\n第三行"}'
    with __import__("pytest").raises(_json.JSONDecodeError):
        _json.loads(broken)
    fixed = _autofix_control_chars_in_strings(broken)
    assert fixed is not None
    obj = _json.loads(fixed)
    assert obj["comment"] == "第一行\n第二行\n第三行"


def test_control_char_autofix_escapes_raw_tab_and_cr(self) -> None:
    """raw `\\t` 与 `\\r` 同样被 escape。"""
    broken = '{"a": "x\ty\rz"}'
    fixed = _autofix_control_chars_in_strings(broken)
    assert fixed is not None
    assert _json.loads(fixed)["a"] == "x\ty\rz"


def test_control_char_autofix_returns_none_when_clean(self) -> None:
    """已转义的 JSON 应返回 None（不重复处理）。"""
    clean = '{"a": "hello\\nworld", "b": "x\\ty"}'
    assert _autofix_control_chars_in_strings(clean) is None
```

三件事：实战 newline / 多种 control char (`\t` / `\r`) / clean-input-returns-None。

### reviewer 的双轮 autofix 组合

第 26 轮的另一个工程决策：**reviewer 的 autofix 链怎么组合**。

reviewer 同时面临两种破裂——quote 违约（继承自第 25 轮 astron 时代的问题）+ control char 违约（minimax 时代新增）。这两种破裂可能单独发生，也可能在同一个 raw_text 里**叠加**发生：minimax 输出的某段 long comment 既有内嵌 ASCII `"` 又有 raw `\n`。

`reviewer.py` 的 `_parse_review_json` 里做了双轮组合：

```python
autofixed = _autofix_unescaped_answer_quotes(json_slice)
if autofixed is None:
    autofixed = _autofix_unescaped_quotes_in_all_string_values(
        json_slice,
    )
if autofixed is None:
    autofixed = _autofix_control_chars_in_strings(json_slice)
else:
    # 引号修过的版本里仍可能有 string-内 control char
    ctrl_fixed = _autofix_control_chars_in_strings(autofixed)
    if ctrl_fixed is not None:
        autofixed = ctrl_fixed
if autofixed is None:
    exc = LLMFormatError(
        "reviewer JSON parse failed and autofix did not apply"
    )
    exc.raw_text = text  # type: ignore[attr-defined]
    raise exc from None
try:
    obj = json.loads(autofixed)
except json.JSONDecodeError as jexc:
    # 第二轮：在 quote-fixed 之后再试 control-char autofix
    ctrl_only = _autofix_control_chars_in_strings(autofixed)
    if ctrl_only is not None and ctrl_only != autofixed:
        try:
            obj = json.loads(ctrl_only)
        except json.JSONDecodeError as jexc2:
            exc = LLMFormatError(
                f"reviewer JSON parse failed: {jexc2}"
            )
            exc.raw_text = text  # type: ignore[attr-defined]
            raise exc from jexc2
    else:
        exc = LLMFormatError(f"reviewer JSON parse failed: {jexc}")
        exc.raw_text = text  # type: ignore[attr-defined]
        raise exc from jexc
```

读法（按场景分支）：

- **场景 1：定向 quote autofix 命中** → 直接 parse 修复版本
- **场景 2：通用 quote autofix 命中** → 在 quote-fixed 版本上**再叠加**一次 control-char autofix，因为 minimax 经常两种问题同发
- **场景 3：quote autofix 都没命中**（input 里没裸引号）→ 单独试 control-char autofix
- **场景 4：合成的 autofix 仍 parse 失败** → 第二轮再试一次 control-char autofix（quote autofix 修过引号但没修 control char 的情况）
- **场景 5：所有 autofix 串联仍失败** → 抛 `LLMFormatError`，挂 raw_text 给 post-mortem

这套链是 reviewer 在第 26 轮第二次 pilot 失败之后，我盯着报错和 raw_text 一遍一遍调出来的。看起来繁琐，但每条分支都对应一个真发生过的破裂场景。

### 第四道 autofix 的代价表

第四道 autofix 让我多写了：

- 38 行实现代码（状态机版本）
- 4 个单测用例（newline / tab+cr / clean / does-not-touch-struct）
- reviewer.py 的双轮 autofix 组合逻辑（约 30 行 if/else）

第三次 pilot 跑通：dur 217s / cite 7 / tool_calls 真数 7。reviewer 终于不炸了——v3.1+minimax 跑全 5 题平均 20.0/25。这个分数本身有故事（公开书训练污染），但那是 article-04 的事，不是这篇。

---

## 横向对比：四道 autofix 的工程画像

我把四道 autofix 横向放一起对比一下：

| 维度 | 定向 quote | 通用 quote | think strip | control char |
|---|---|---|---|---|
| 触发轮次 | 第 24 | 第 25 | 第 26 | 第 26 |
| 触发 LLM | astron-code-latest | astron-code（reviewer） | MiniMax-M2.7 | MiniMax-M2.7（reviewer） |
| 实现方式 | regex 位置定位 + substitute | 状态机 + peek 启发式 | regex 删除 | 状态机 + escape |
| 处理位置 | loop 层 | loop 层 + reviewer 层 | adapter 层 | loop 层 + reviewer 层 |
| 代码行数 | ~50 | ~65 | ~13 | ~38 |
| 单测数 | 3 | 4 | 0（隐式 e2e 覆盖） | 4 |
| 已知 limitation | 顶层 schema 顺序绑定 | 纯英文场景误判 | 不闭合标签兜底处理 | 假设 quote autofix 已先做 |
| 关键不变量 | (?<!\\) 负向断言保护已转义 | in_string flag + escape pair 跳过 | fast path 在无 `<think` 时早返回 | in_string 区分 struct/string 层 |

几条横向观察：

**1. 处理位置跟违约性质走**

`<think>` strip 放 adapter 层——因为它是 provider 层的现象，所有 downstream consumer 都该受益。其它三道放 loop / reviewer 层——因为它们是 JSON 解析层的现象，和 adapter 无关（理论上 Anthropic 的 Claude 也可能违约）。

**2. 状态机比正则扎实**

定向 quote autofix 用的是正则。它能用是因为有强位置约束。通用 quote autofix 和 control-char autofix 都退到了状态机——因为没有位置约束的情况下，正则的"全局贪婪 / 非贪婪"很容易踩坑。手写状态机虽然啰嗦，但每一步状态转移都可肉眼审计。

**3. 单测数量和复杂度成正比**

第 24 轮的定向 quote 因为 schema 简单，3 个 case 够。第 25 轮的通用 quote 要覆盖嵌套字段，4 个 case。第 26 轮的 control-char 要覆盖 newline/tab/cr/struct-层不被动，4 个 case。`<think>` strip 只在 adapter 层做，而且 fast path 简单到不需要专门单测——loop 的 e2e 测试已经隐式覆盖。

**4. 每道 autofix 都有"关键不变量"**

这是我后来回看时才看出来的。每道 autofix 都有一个"如果违反这个不变量就会破坏一切"的核心约束：

- 定向 quote：`(?<!\\)` 负向断言——不能把已经合规的 `\"` 二次转义
- 通用 quote：`in_string` 状态机 + escape pair 跳过——不能把 struct 层的 `"` 当成 string 边界
- think strip：fast path 早返回——不能让无标签场景多扫一次正则
- control char：`in_string` 区分——不能把 struct 层的 newline 当成需要 escape 的 control char

这些不变量都被相应的"preserves-X"或"does-not-touch-X"单测保护起来。如果未来某次重构破坏了不变量，这些单测会立刻 RED。

---

## 反思：autofix 是工程上的成功，是 prompt 系统的失败

四道 autofix 写完，单测全绿，reviewer 跑 5 题 batch 全通——工程上这是个胜利。但我得诚实地说一件事：

**这一切本来都不该发生**。

如果 prompt + LLM 能稳定守约 JSON，autofix 链根本不需要存在。`citation_format_v1.md` 的 36 行规则、loop_system_prompt 里的 schema 约束——只要 LLM 严格遵守，整个 autofix 模块都是死代码。

但实际是，每个 LLM 都在用自己的方式"几乎对"：

- astron-code 喜欢用 ASCII `"` 直接引用原文
- MiniMax-M2.7 喜欢在 long comment 里换真换行
- 各家 reasoning model 都喜欢 inline thinking 段

我对这个现象做几条反思：

**1. prompt 不是 schema validator**

我在 `citation_format_v1.md` 里写"违反这条规则会导致 JSON parse 失败"——这是给人看的。LLM 看到这一条不会突然变成 schema-aware 的。LLM 只会按统计倾向输出，statitistical 倾向被训练数据塑造，训练数据里 ASCII `"` 比 `\"` 频繁得多。

**2. 早期"我会输出 JSON"的承诺是一种宽松解读**

OpenAI / Anthropic / DeepSeek 一线 LLM 在 marketing 上都会说"我支持 structured output / JSON mode"。这是真的——但意思是"我大概率能输出可解析的 JSON"。"大概率"这个词在工程上不能用——99% 的 success rate 在 production 跑 100 次 query 就有 1 次 fail，10000 次就 100 次 fail。

**3. cross-provider 是兼容性测试矩阵的根源**

ADR-002 v2 里我把 BookScope 设计成 provider-agnostic——通过 `LLMClient` Protocol 抽象、`DeepSeekAdapter` / `AnthropicAdapter` 做 OpenAI / Anthropic 双向翻译。意图是让用户 BYOK 任意 provider。但 provider-agnostic 的副作用是**测试矩阵爆炸**——每加一种 provider 就可能加一种违约方式。autofix 链就是这个矩阵的具体表现。

**4. 没有 lenient JSON parser 是一劳永逸方案**

我写完第 26 轮，盯着四道 autofix，认真想过"是不是该切到 json5 / demjson3"。

`json5` 支持：
- 字符串可以用单引号或双引号
- key 可以不加引号
- 字符串内可以有 raw newline（multi-line strings）
- 注释（`//` 和 `/* */`）

`demjson3` 更宽容，几乎接受任何"看起来像 JSON"的输入。

但切到 lenient parser 有它自己的代价：

- **依赖膨胀**——`json5` 是纯 Python 实现，速度比 stdlib `json` 慢 3-5 倍
- **silent acceptance**——lenient parser 会接受很多本不该接受的输入，比如混杂的 `'foo'` 单引号 string、漏写的字段。这些被接受的"几乎合法"输入可能会让 schema 校验变得更复杂
- **每家 LLM 还会发明新的违约方式**——lenient parser 解决的是"已知违约方式"的子集；下一代模型出来时还会新增

我的判断是：autofix 链是个**演化型**工程模块。它不是一次性方案，它是和 LLM 行为偏差共生的产物。每出一个新 LLM、每出一种新 prompt、每出一种新 use case，都可能新增一道 autofix。它就像 web 开发里的"浏览器兼容性 hack"——理论上不该有，实际上永远在演化。

未来的方向我倾向于这样：

1. **保留现有四道 autofix 作为"已知违约方式"的精确响应层**
2. **在所有 autofix 都失败时，加一道 lenient parser 兜底**——比如 `json5.loads` 作为 last-resort fallback。它的作用不是替代 autofix，是兜底接住"未知违约"
3. **对每次 lenient parser 救场的 case 写 post-mortem**——把"未知违约"提升为"已知违约"，决定要不要给它专门写一道 autofix
4. **持续在 case-study 里记录违约目录**——这一篇文章本身就是这个目录的第一版

---

## 收尾：一份 cross-provider 兼容性目录

把四道 autofix 串起来读，本质上是一份**实战 cross-provider 兼容性目录**：

```text
LLM 行为偏差 → autofix 响应：

[astron-code-latest] answer 字段裸 ASCII `"`
  → _autofix_unescaped_answer_quotes (regex 位置定位)

[astron-code-latest] reviewer 嵌套字段裸 ASCII `"`
  → _autofix_unescaped_quotes_in_all_string_values (状态机 + peek)

[MiniMax-M2.7] content 内 <think>...</think>
  → _strip_thinking_tags (adapter 层 regex 删除)

[MiniMax-M2.7] reviewer string 内 raw \n
  → _autofix_control_chars_in_strings (状态机 + escape)
```

如果未来切到 deepseek-r1 / qwen-qwq / glm-zero / Claude Opus 4.5 / GPT-4o / 任何新一代模型，这个目录会继续增长。我已经能预想到几个潜在的下一行：

- **某些 model 会输出 `'single quoted strings'`**——目前 stdlib `json` 不接受单引号
- **某些 model 会在 array 末尾留 trailing comma**——`[1, 2, 3,]`
- **某些 model 会在 key 上不加引号**——`{name: "foo"}` 而不是 `{"name": "foo"}`
- **某些 reasoning model 的 thinking 标签是别的名字**——不是 `<think>` 而是 `<scratchpad>` / `<reasoning>` / `<analysis>`

每一条都是潜在的下一道 autofix。

但我现在不主动写——按 KISS 原则，**不在违约真发生之前预写 autofix**。预写的 autofix 是没有 raw_text 验证的，可能修一种没出现过的破裂、引入一种新的回归。

第四道 autofix 写完那一晚，我的状态是这样的：v3.1+minimax 跑通 5 题 batch，平均 20.0/25——分数被公开书训练污染拖累，但 BookScope 的 generation pipeline 完整跑通了。reviewer pipeline 完整跑通了。JSON parse 全程没炸。

这是工程的胜利。但工程的胜利同时是 prompt 系统的失败——四道 autofix 的存在本身证明了：在 BookScope 当前的 prompt + provider 矩阵下，没有一家 LLM 能稳定守约 JSON。

所以我把这条长征写下来。不是为了庆祝胜利，是为了让下一个写类似系统的人——可能是我自己几个月后回来看，可能是 fork BookScope 的某位读者——知道：

> autofix 不是一次性写完的工程，是和 LLM 共生的工程史。
> 每一道 autofix 对应一种 LLM 行为偏差。
> 按发现顺序展开，就是一份 cross-provider 实战兼容性目录。
> 这份目录永远不会完结——因为新一代 LLM 还会发明新的违约方式。

第 26 轮的当下，autofix 链是四道。第 30 轮、第 50 轮、第 100 轮的 BookScope，可能是六道、八道、十道。每多一道，case-study 就多一行。

这本身就是这本案例研究存在的意义之一——把那些"工程上看不见但实际上反复发生"的小事，记下来。

---

> **状态**：草稿 · 作者未定稿
> 末段对未来 lenient JSON parser（json5 / demjson3）的可能性已做简短讨论。后续如果切到 lenient parser，本文需要新增一节"为什么我们最终还是切了"。
