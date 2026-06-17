# Citation 输出格式 · v1

## 最终答案必须是单个 JSON 对象

答复时，不要再调用任何 tool；直接返回一段 JSON 文本（可被 `json.loads` 解析）：

```json
{
  "answer": "<你的综合答复，中文字符串>",
  "citations": [
    {"chapter": <整数>, "snippet": "<原文片段，非空字符串>"}
  ]
}
```

## 硬约束

- 顶层对象必须包含且仅包含 `answer` 与 `citations` 两个字段。
- `answer`：字符串，长度不限；可以为空字符串（但只在"数据不足以作答"时允许）。
- `citations`：数组，**长度 >= 1**。每条必须同时具备：
  - `chapter`：整数，章节号，>= 1。
  - `snippet`：字符串，非空，直接来自 tool 返回的 `text` / `full_text` 字段（可做最小裁剪，但不得改写）。

## 内嵌引号规则（违反会导致 JSON parse 失败）

`answer` 与 `snippet` 字段本身就是 JSON 字符串，**内部绝对不能出现未转义的 ASCII 直双引号 `"`**。

正确做法（按优先级）：

1. **中文文本优先用中文全角引号 `"…"`**——例如：书中点明他`"外表宽厚，却心胸狭窄"`。JSON 层看不到全角引号，最安全。
2. 英文词句必须用直引号时，**写成 `\"…\"`**（反斜杠转义）。
3. **禁止**裸 `"…"`——例如 `"answer": "他说"你好"然后走了"` 会在 `"你好"` 的第一个 `"` 处破坏 JSON 结构，整个 final answer 被判格式错误。

这条规则在 answer 字段尤其常被违反（因为 answer 经常需要引用原文）；请在写 answer 时有意识地把所有内嵌引号改成全角 `"…"`。

## 不符合格式会被拒绝

agent loop 框架会在收到你的 final answer 后做一次 schema 校验：
- 缺 `citations` 字段、`citations` 为空 list、citation 缺 `chapter` 或 `snippet` 任一字段，均视为格式错误。
- 第一次格式错误时，框架会把一条补正提示追加到 messages 让你重试一次。
- 仍然格式错误会直接抛 `LLMFormatError`，本次 query 失败。

请一次就把格式做对。
