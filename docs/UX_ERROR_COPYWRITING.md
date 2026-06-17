# UX 错误兜底文案

第 33 轮起草（Sprint 1 PM deliverable）。BookScope 当前的 provider / agent 错误是从后端原样冒到前端的——用户会看到 `Error code: 422 - {'http_code': '422'}` 这种东西。这份文档把 5 类常见失败的用户友好提示文案先定下来，Sprint 2 BE 落地 UI 显示时直接拿。

**写作底线**（每条文案都要满足）：

- 不超过 3 句话，5 秒内读完
- 给一个具体的下一步建议（"试试 X" / "建议 Y"）
- 不暴露 provider 名字、HTTP 状态码、内部错误码
- 中文像中文（不堆"surgical 修""退避""降级"这种术语）
- 体现 BookScope 已经替用户兜底（"已自动重试 N 次"）

用户群不只服务作者本人——任何带长文本进来的创作者 / 深度读者都要能看懂这些提示。

---

## 1. ContentFiltered —— 内容审核拒答

**错误名**：`ContentFiltered`（继承 `ProviderError`）

**触发条件**：当前选用的 LLM 厂商对输出内容做了安全审核，把答复判为敏感拒绝返回。最常见是 MiniMax HTTP 422 `output new_sensitive`，OpenAI 也有 `content_policy_violation`。常因书里某段原文 + 题面措辞组合触发，间歇性，不一定每次都拒。

**用户看到的提示**：

> 这道题碰到了 AI 厂商的内容审核。BookScope 已经自动换了 3 种说法重试，还是没过。建议把题面里敏感的字眼换个说法再问一次，或者切到设置里的另一家厂商试试。

**不该出现**：

- "MiniMax 422 new_sensitive (1027)"
- "触发了 provider 的 safety filter"
- 原始 stack trace
- "translated content 触发审核策略" 这种翻译腔

---

## 2. RateLimited —— 厂商限流

**错误名**：`RateLimited`（继承 `ProviderError`）

**触发条件**：你 BYOK 用的那家 LLM 厂商当前对你的 key 做了请求频率限制。常见是免费档 / 试用档 key 短时间内请求过多，或厂商整体高峰期。

**用户看到的提示**：

> AI 厂商现在请求太多忙不过来。BookScope 已经自动等了一会儿重试 3 次还是不行。建议过 1 分钟再试一次，或者去厂商后台看看你的 key 是不是有调用次数上限。

**不该出现**：

- "rate_limit_exceeded HTTP 429"
- "已自动 exponential backoff"
- "退避策略已耗尽"
- 提具体哪家厂商的限流规则

---

## 3. ContextLimitExceeded —— 上下文超长

**错误名**：`ContextLimitExceeded`（继承 `ProviderError`）

**触发条件**：当前 session 的对话历史 + 检索到的原文证据加起来，超过了 LLM 厂商单次能处理的字数上限。常见是连续问了几十轮问题、或这本书很厚 + 题面要求大量原文引用。

**用户看到的提示**：

> 这次对话已经积累得太长，AI 一次处理不过来了。建议在左上角点"新对话"重开一个 session 继续问，刚问过的关键结论可以复制带过去。

**不该出现**：

- "token 超过 context window 上限"
- "max_tokens=128000 已耗尽"
- "请清空 message 历史"
- "切到 context 更长的 provider"（普通用户不知道这是什么意思）

---

## 4. MaxIterationsExceeded —— Agent 没收敛

**错误名**：`MaxIterationsExceeded`（继承 `AgentError`）

**触发条件**：BookScope 的 agent 跑了 N 轮（默认 12 轮）工具调用还是没给出最终答案。通常是问题太宽泛 / 题面没说清要找什么 / 这本书里证据点太散。

**用户看到的提示**：

> BookScope 翻了 12 轮还是没找到稳的答复。多半是这道题问得太宽。建议拆成两三个更具体的小问题分别问，比如把"主角的成长曲线"拆成"主角第几章发生关键转变""转变后他做了什么"。

**不该出现**：

- "agent loop exceeded max_iterations=12"
- "未达到收敛条件"
- "tool dispatch 链太深"
- "请反馈给我们"（空话，没具体下一步）

---

## 5. ProviderUnavailable / ConnectionError —— 厂商挂了或 key 失效

**错误名**：`ProviderUnavailable`（继承 `ProviderError`），也覆盖网络层 `ConnectionError`

**触发条件**：连不上 LLM 厂商。常见三种——API key 填错或过期、本地网络断了、厂商 endpoint 临时挂了。

**用户看到的提示**：

> 连不上 AI 服务。先在设置里检查一下你填的 API key 还有没有效，再看看自己网络通不通。两样都没问题的话，多半是厂商那边临时故障，过几分钟再试。

**不该出现**：

- "AuthenticationError 401" / "APIConnectionError"
- "DNS 解析失败"
- "endpoint 不可达"
- 直接甩一个 URL 让用户自己 ping

---

## PM 给 BE 的实施备忘录

Sprint 2 BE 落地时按下面的对照表来：

**错误捕获位置**：在 `bookscope/agent/loop.py` 顶层 `except AgentError` 之外加一层，把 `ProviderError` 子类和 `MaxIterationsExceeded` 翻译成上面这 5 段文案，再走 API 响应 envelope 返回前端。后端日志里继续保留原始 stack trace 给开发调试，**只是不下发到前端**。

**前端组件**：建议在 `web/` 里加一个 `<ErrorBanner>` 组件（横幅样式，问答区上方），收到错误码时显示对应文案。不用 toast——toast 会消失，用户读完想再看一眼就找不到了；横幅留着直到用户关闭或重新提问。

**带不带"重试"按钮**：

- ContentFiltered → 带"换个说法重试"按钮（清空当前题面让用户重写）
- RateLimited → 带"再试一次"按钮（60 秒倒计时后亮起）
- ContextLimitExceeded → 带"新建对话"按钮（直接开 session）
- MaxIterationsExceeded → 不带重试按钮，给"拆分问题"提示
- ProviderUnavailable → 带"打开设置检查 key"按钮 + "再试一次"按钮

**埋点**：5 类错误各自打点（错误码 + 触发时间 + 当前 provider，不要打用户题面），方便 PM 后续看哪类错误最高频再迭代文案。

**BYOK 提示**：错误文案里出现"AI 厂商""你的 key""你填的 API key"——不写具体厂商名（MiniMax / DeepSeek / Anthropic），保持 provider-agnostic。设置页才出现具体厂商名。

**i18n**：当前只写中文。英文版等 OSS 公开发布前 PM 再补一版，不在 Sprint 2 范围内。
