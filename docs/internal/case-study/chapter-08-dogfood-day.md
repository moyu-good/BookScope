# 第 8 章 · dogfood 一日：作者打开浏览器后 4 句话触发的 UX 重构

> **状态**：草稿 · 作者未定稿
> **时段**：2026-05-13（作者首日完整 dogfood + 同日 9 commit 修）
> **覆盖 commit**：`391d59a`（FE · ErrorBanner 文案重写）/ `c05b865`（BE · RouteDecisionEvent SSE）/ `bae4b17`（FE · RouteDecisionBanner + 计时器）/ `e90d616`（FE · KG 改"解析" + 快/深问加时长）/ `9b7f77b`（BE-A · fast_path 砍 5 类到 2 类）/ `e854cd4`（BE-B · 问题处理引擎）/ `99ab6cb`（BE-C · reviewer 重答带批评回路）/ `b16cd5f`（FE-A · QuestionBreakdown）/ `d387dda`（FE-B · 重答按钮带 previous_review）
> **与前 7 章的关系**：chapter-05 讲 r2 代际切换 / chapter-06 讲性能那一日 / chapter-07 讲 reviewer 走出实验室；chapter-08 讲 reviewer 走出实验室之后**用户视角第一次回来锤**的那一日

---

## 一、序：浏览器开了，4 句话回来了

前 7 章都是工程团队在闭门做。

副管理派 BE / FE / PE / QA / RE / OPS 一波接一波跑 sprint，benchmark 数据漂亮、单测 600 全绿、reviewer 走出实验室、r2 切完。BookScope 在工程视角里非常体面。

2026-05-13 这一天作者第一次真把浏览器打开——上传 epub、问题、看答案、看评分卡。整套流程没崩，回答出来了，评分卡也出来了。然后作者丢回 4 句反馈：

> "思考的整体时间太长了，但是我又完全不知道具体要花费多长时间。"
>
> "出了点问题，BookScope 已经记下了。建议过 1 分钟再试，或者把题面换个说法。——这个中文表达很奇怪。"
>
> "快问深问这个区分关键词很差，就按照字数分吧，字数越长你就需要整理问题，需要一个问题的处理引擎。"
>
> "reviewer 是让你自我进化的嘛？"

四句话——下午一点五十四到三点半，BookScope 一日跑出 9 个 commit。代码量不大（最大的 BE-B 也才 358 行新模块），但每一个 commit 都把 BookScope 从"工程师视角"往"用户视角"挪一小段。

这是 NORTH_STAR 第 1 条第一次**真激活**——"服务作者本人作为长篇网络小说创作者的第一读者工具"不再是文档里的字，是浏览器里跑的真东西。reviewer 走出实验室是 chapter-07 那天的事；用户视角走进实验室是这一天的事。

下面四节按四句话顺序串。

---

## 二、第一句：思考时间长但不知道要多久

作者点了一道题，BookScope 答了十几秒——他等着。

问题不在于"十几秒"，问题在于"不知道要多少秒"。chapter-06 那天 fast_path 已经把后端切成 5 类路由——通识题 3-12 秒、评论题 5-15 秒、摘要题 5-15 秒、评分题 3-10 秒、深度题 30-90 秒——但是这一切 UI 完全不告诉用户。

用户点完题看到一个 progress timeline 一直转，转十秒、转二十秒、转五十秒——他不知道是 BookScope 在快路径上慢了，还是已经进了深度路径要等一分钟，还是已经卡住该重试。

这一笔锤得最直白——**后端有 5 类路由分级，前端却完全瞎**。

### RouteDecisionEvent：SSE 第一帧就是路由

`c05b865` 加了一个新的 SSE 事件 `RouteDecisionEvent`，让 fast_path 在路由判定完的那一刻立刻 emit 出去——比 iteration_start 还早一帧。

`bookscope/agent/events.py` 加 frozen dataclass：

```python
@dataclass(frozen=True)
class RouteDecisionEvent:
    type: Literal["route_decision"] = "route_decision"
    route_type: RouteType  # 5 类
    human_label: str       # 中文标签
    expected_duration_seconds_min: int
    expected_duration_seconds_max: int
```

`fast_path.py` 加两张 `Final` 映射表——一张 `_ROUTE_EXPECTED_DURATION` 把 5 个 route_type 映射到 `(min, max)` 秒，另一张 `_ROUTE_HUMAN_LABEL` 映射到中文（通识题 / 评论题 / 摘要题 / 评分题 / 深度题）。`run_fast_path` 入口先 emit RouteDecisionEvent，再 emit iteration_start——保证 SSE 第一帧就是路由。

agent_loop 直接走的题（fast_path 判定为长题 / 含诊断词的）也要 emit——所以 `loop.py` 和 `loop_r2.py` 的 query 函数都加 keyword-only `emit_route_decision: bool = True`，入口条件 emit `RouteDecisionEvent("agent_loop")`。fast_path 兜底走 agent_loop 时传 False 不重复 emit——这条契约写在 commit message 里给 FE 看。

13 个新单测覆盖：dataclass frozen / 5 类 emit / agent_loop direct emit / fast_path 兜底不重复 / response 含 route_type / 映射表完整 / human_label 中文。`pytest 600/600` 全绿。

### RouteDecisionBanner：emoji + elapsed + 三态文案

`bae4b17` FE 接通。`web/src/RouteDecisionBanner.tsx` 约 120 行独立组件——`useElapsedSeconds` hook 1 秒 tick + cleanup，三态文案：

- 正常（`elapsed <= expected_max`）：`"📖 看起来是【通识题】，预计 3-12 秒。 已用 5 秒"`
- 比预期慢（`expected_max < elapsed <= 1.5x`）：`"已用 18 秒（比预期慢）"`——计时器变印章红 + bold
- 超 1.5x：`"但 agent 还在查。 已用 35 秒"`——文案给用户一个"还在跑没卡死"的信号

5 类各加 emoji 前缀（📖 通识 / ✍️ 评论 / 📝 摘要 / ⭐ 评分 / 🔍 深度）——一眼识别 + 不引入图标库依赖。

视觉上 banner 内嵌进 ProgressTimeline 左竖线区，底部 `border-b` 分段，不另起 card——融入既有进度条节奏，不抢镜。`label` 印章红 + bold / 预期时长 `ink-muted` / 超时计时器变红——状态从颜色直读，不靠文字解释。

### 关键决策：5 类路由还是改回去？

写这一笔的时候副管理犹豫过——既然 fast_path 后端已经分 5 类，UI 上是不是就该展示 5 类标签？

但是这条 banner 写到第 2 个 commit（bae4b17）的时候，第三句反馈已经回来了——"按字数分吧"。所以 5 类 RouteType `Literal` 的 contract 保留（向后兼容已 emit 的事件），但底层实际只会产生 2 类。这件事第三节再展开。

`npm run build` 1.04s 过，gzip 73.98 KB 在 300 KB 预算内。零新依赖。

### 顺手的一笔：KG → 解析

`e90d616` 是同一个反馈的尾巴。作者顺带说了一句"上传按钮上的 KG 是啥"。

原文案 `"上传并抽取 KG"`——`KG` 是 Knowledge Graph 的简写，副管理写代码时下意识用了工程缩写。普通用户根本不知道 KG 是什么，更不知道这跟"问书"有什么关系。

改成 `"上传并解析"`——"解析"用户能直接理解（涵盖切分 / 抽取角色 / 建索引），不暴露工程细节。loading 文案 `"抽取中 · 大书需数分钟"` 改 `"解析中 · 大书需几分钟"`。

同 commit 顺带改了 SuggestedQuestions 那一组——"快问"标签加 `"（几秒就答）"`、"深问"加 `"（要查证一两分钟）"`。让 UI 标签跟 RouteDecisionEvent 的 `"预计 X-Y 秒"` 对应。

还有一道快问换题：删 `"这本书讲了什么？"`——它实际命中 REVIEW_KEYWORDS 跑 fast_review 5-15 秒，挂在"快问"组里名不副实；换成 `"一共有多少章？"` 真跑 fast_general 3-12 秒。

这条小事的教训：**UI 标签上写的预期时长跟后端实际跑的时长必须对上**，不然 BookScope 自己骗自己。

---

## 三、第二句：中文表达很奇怪

作者第二句反馈砍在最尴尬的地方——ErrorBanner 的 fallback 文案。

> "出了点问题，BookScope 已经记下了。建议过 1 分钟再试，或者把题面换个说法。"

这条文案副管理一个月前写的，自己读过几遍觉得没问题。作者一句话锤穿——"中文表达很奇怪"。

锤穿之后回头读，问题在哪一目了然：

- "BookScope 已经记下了"——这是给运维看的（日志有了），不是给用户看的。用户根本不在乎 BookScope 内部记没记
- "建议过 1 分钟再试"——为什么是 1 分钟？没原因。模糊
- "题面"——"题面"这个词是工程师术语，用户问的就是"问题"

### 全 6 段重写

`391d59a` 全 6 段重写，每段同时砍翻译腔 + 砍废话 + 缩短：

| 类型 | 改前 | 改后 |
|------|------|------|
| ContentFiltered | "这道题碰到了 AI 厂商的内容审核。BookScope 已经自动换了 3 种说法重试，还是没过。建议把题面里敏感的字眼换个说法再问一次..." | "碰上 AI 内容审查了。换了三种说法重试都没过。把题里敏感的字换个说法再问，或者去设置里挑另一家厂商。" |
| RateLimited | "调用次数上限" 翻译腔 | "看看你这把 key 还剩多少额度" |
| ContextLimitExceeded | "重开一个 session 继续问" 夹英文 | "点左上「新建对话」重开一次" |
| MaxIterationsExceeded | "主角的成长曲线" 文论术语堆砌 | 给具体题例「主角在第几章发生转变」「转变以后他做了什么」 |
| Fallback | "BookScope 已经记下了。建议过 1 分钟再试，或者把题面换个说法。" | "出问题了。再试一次，或者把题改个写法。" |

按钮文案也跟着缩：

- `"换个说法重试"` → `"换个说法重问"`
- `"再试一次"` → `"再问一次"`
- `"打开设置检查 key"` → `"去设置看 key"`
- `"再试一次"`（次按钮）→ `"再试"`

字符串嵌套引号用「」中文角引号——顺手规避 JS 双引号嵌套语法错误。

### 反思：硬规则需要 dogfood 触发才能验

CLAUDE.md 第三条"中文写作硬规则"，加上 memory 里那条 `feedback_natural_chinese.md`——这两条不是新规则，是作者反复强调过几遍的规则。

但是 ErrorBanner 这一个月里没人锤过。BookScope 跑 batch 不报错，没人路过这个 fallback 文案；副管理写的时候自己读过觉得"这中文还行"——硬规则被绕过去了。

直到作者真用一遍，一句"中文表达很奇怪"——文案才被认真重写。

教训不是"规则没写清楚"——规则写得很清楚。教训是**硬规则需要 dogfood 触发才能验**。规则文件上的字加不出代码的诚信，只有真用过、真被锤过、真重写过——规则才在产品里活下来。

这跟 chapter-07 末尾那条"reviewer 也要遵守中文像人话"是一脉的——任何 LLM agent 的 prompt、任何 UI 文案、任何对外文档——CLAUDE.md 第三条都管。每个新出现的产出口都要走一遍 dogfood 才能被规则真覆盖到。

`npm run build` 1.77s 过、gzip 73.26 KB。零代码逻辑改动、零后端改动、零测试改动——纯文案，但产品视角第一次真清晰起来。

---

## 四、第三句：字数分 + 问题处理引擎

第三句反馈砍在 BookScope 路由设计的根上：

> "快问深问这个区分关键词很差，就按照字数分吧，字数越长你就需要整理问题，需要一个问题的处理引擎，然后继续处理才对。"

两件事——(a) fast_path 路由从关键词分改字数分、(b) 长题进 agent_loop 前先过一个处理引擎。

### Push back 的一段：纯字数会把短深题打死

副管理第一反应不是直接接，是 push back——纯字数分会出问题。

副管理给的反例三条：

1. `"作者最强的论点是什么？"` 12 字——字数短，但这是深题
2. `"这本书最让人意外的发现是什么？"` 14 字——字数短，深题
3. `"和同类书比，这本独到在哪里？"` 14 字——字数短，深题

如果纯字数 ≥ 30 才进 agent_loop，这三道都会被打进 fast_general 跑 3-12 秒的快路径——而这恰恰是作家本人最关心的几类题（chapter-04 里 P1 验证靠的就是这类题，memory `feedback_p1_writer_vs_general_questions.md` 记过）。打死它们就是把 BookScope 真正的价值砍掉。

副管理给的修正方案是"**字数主信号 + 诊断词兜底**"——

```
字数 ≥ 30 → agent_loop
字数 < 30 + 含诊断词 → agent_loop
字数 < 30 + 无诊断词 → fast_general
```

诊断词清单扩到 8 个新加项：评价 / 怎么 / 如何 / 论点 / 最强 / 意外 / 独到 / + 原有变体——刚好覆盖上面三个反例。

作者点头——方向定下来。

### `9b7f77b`：5 类砍到 2 类

`fast_path.py` `_route_question` 重构。砍 4 个 keyword set（RATING / REVIEW / SUMMARY / ENUMERATION），只保留 DIAGNOSTIC_KEYWORDS。

`RouteDecision` 的 `Literal` 5 个值保留——contract 兼容已 emit 的 RouteDecisionEvent + FE emoji 表 + chapter-06 里的引用——但实际路由只会产生 `fast_general` / `agent_loop` 两类。这是一条"接口保留 + 实现收窄"的写法，避免给 FE 制造无意义的破坏性变更。

`prompts/fast_path/` 下 4 份子类 prompt（fast_review / fast_summary / fast_rating / fast_general）不删——chapter-06 还在引用，后续 sprint 可能复用。加一个 `README.md` 注明"现在不再被路由命中，但作历史素材保留"。

5 个新单测覆盖关键场景：

- 短题无诊断词 → fast_general
- 短题含诊断词 → agent_loop
- "作者最强的论点是什么？" 12 字 → agent_loop（反例修复证明）
- "这本书最让人意外的发现是什么？" → agent_loop
- "和同类书比，这本独到在哪里？" → agent_loop

最后一行最关键——三个反例直接写进测试，**保证以后任何人改 fast_path 都不会再把它们打死**。

顺带修了一个 e2e 测试坑——`_post_ask` helper 原题面 `"测试问题"`（5 字、无诊断词）现在会走 fast_general 路径，错误处理 e2e 测试会被新 fast_path 引入一次额外 LLM 调用打破假设。改成 `"分析这道测试题"`（带"分析"诊断词，进 agent_loop）——既保留 e2e 测试意图，又顺应新路由逻辑。

### `e854cd4`：问题处理引擎

作者那句"需要一个问题的处理引擎"翻译成工程语言——长题（≥ 30 字）入 agent_loop 之前先调一次 LLM 拆题、改写、推荐查询章节，把结果作 system context 喂给 generator。

新模块 `bookscope/agent/question_processor.py` 358 行。

`ProcessedQuestion` frozen dataclass：

```python
@dataclass(frozen=True)
class ProcessedQuestion:
    original_question: str
    subquestions: list[str]                    # 1-3 个
    recommended_chapters: list[int] | None     # None = 全书
    difficulty: Literal["simple", "medium", "complex"]
    processing_duration_seconds: float
```

`process_question` 一次 LLM 调用 + JSON 输出 + 严格 schema。整段 try/except 包死——任何失败（LLM 抛 / JSON 非法 / 超时 / 字段非法）都返 fallback `ProcessedQuestion(subquestions=[original])`，**永远不抛异常给上游**。subquestions > 3 截断、recommended_chapters 非 `list[int]` 设 None、difficulty 不在枚举值默认 medium——三道防线全在 processor 内部消化。

prompt `bookscope/agent/prompts/question_processor_v1.md` 75 行——中文指令明示"**只是拆题不要回答用户问题**"+ 严格 JSON schema 示例。这条指令避免 LLM 直接给答案污染下游 generator 的上下文。

接入两处——`loop.py` + `loop_r2.py` 入口镜像复述：长题且 env flag `BOOKSCOPE_QUESTION_PROCESSING_ENABLED` on 时调 processor → emit `QuestionProcessedEvent` → addendum 拼到 system prompt 末尾喂 generator。fast_general 短题不走 processor——3-12 秒的快路径多花 10 秒拆题等于把快路径杀掉。

19 个新单测——dataclass / happy path / 兜底 / event / addendum / agent_loop 接入 6 组全过。pytest 618/618 全绿。

### `b16cd5f`：FE 拆题可视化

`web/src/QuestionBreakdown.tsx` ~120 行独立组件。视觉对齐 RouteDecisionBanner——同 `pb-2 mb-2 border-b` 分隔节奏，融入既有进度条。

子问列表 `ol` 数字编号 + `tabular-nums` 等宽 + `pl-7` 缩进；印章红强调"X 个子问题"计数；ink 显示子问题正文；ink-muted 显示章节范围 + 难度 + 耗时。

难度中文映射 simple → 简单 / medium → 中等 / complex → 复杂。推荐章节渲染分四种：null → 全书 / 单个 → 第 X 章 / 连续 → 第 X-Y 章 / 离散 → 第 X / Y / Z 章。

最关键的 fallback——`subquestions` 长度 1 且等于 `original` 时整组件 `return null` 不渲染。避免"BookScope 把你的题拆成 1 个"这种冗余 UI 噪音。这条 fallback 跟 BE-B 那条"永不抛异常永远返 ProcessedQuestion"对应——BE 保证 fallback 不崩，FE 保证 fallback 不刷屏。

bundle 238.10 kB / gzip 74.78 KB，仍在 300 KB 预算内。零新依赖。

### 这一节的元层观察

作者那句"快问深问区分关键词很差"——锤的是 BookScope 工程师视角和用户视角的具体边界。

工程师视角觉得"细分越多越精准"——5 类 keyword set 是更细致的设计。但用户视角不需要 5 类——他只需要"快 vs 深"，其余 4 类细分对他没意义。把 5 类砍到 2 类不是损失精度，是去除噪音。

更深一层——作者那句"需要一个问题的处理引擎"实际上不是要求一个新模块，是要求"BookScope 在面对长题时能比 generator 多一步思考"。这件事副管理之前没主动想——agent_loop 收到长题直接进多轮推理，没人觉得需要先拆题。直到作者一句话——这一步才被加进去。

---

## 五、第四句：reviewer 是让你自我进化的嘛？

最后一句锤得最深：

> "reviewer 是让你自我进化的嘛？"

作者看到评分卡 15/25 分 + 完整 5 维评语，自然问出这句话。

副管理本来想答"是的"——但话到嘴边卡住，因为事实不是。

### 锤穿的事实：当前 reviewer 只给用户看分

chapter-07 那天 reviewer 走出实验室，UI 上多了评分卡——但是用户点"重答"按钮**还是同 prompt 重跑碰运气**。reviewer 给的 5 维评语和 top_issues 不会作为提示喂回 generator。

真正的自我进化回路在哪里？在副管理手上——研究端跑 batch、看 reviewer 评分、改 prompt v1 → v2 → v3.4（chapter-03 / 04 已讲）。这是**人工自我进化**，不是 BookScope 自己的回路。

作者那句话锤穿的就是这个 gap——"看分"和"用分改"是两件事，BookScope 只做了前者。

### `99ab6cb`：BE 加 previous_review 注入

`bookscope/api/schemas.py` 加 `PreviousReviewHint`：

```python
class PreviousReviewHint(BaseModel):
    total_score: int = Field(..., ge=0, le=25)
    dimension_comments: dict[str, str] = Field(default_factory=dict)
    top_issues: list[str] = Field(default_factory=list, max_length=5)

class AgentAskRequest(BaseModel):
    # 现有字段保留
    previous_review: PreviousReviewHint | None = None
```

`PreviousReviewHint` 是 `Review` 模型的瘦身版——不要求 FE 传整个 Review，只传够注入 prompt 的关键信息（分数 + 5 维评语 + top 5 issues）。

`bookscope/api/routes/agent.py` 加几个 helper——`_REVIEW_DIMENSION_LABELS` 把 5 维英文 key 映射到中文（判断而非复述 / 证据厚度 / 诚实度 / 可操作 / 跨章节视野），`_format_dimension_comments` 按固定顺序拼接 bullet，`_build_review_addendum` 总装 addendum。

addendum 实例：

```
---
上一次回答这道题，reviewer 评分 14/25，并指出以下问题：

5 维度评语：
- 判断而非复述：判断模糊
- 证据厚度：原文证据少
- 诚实度：保留够
- 可操作：操作不具体
- 跨章节视野：只看第一章

主要问题：
- 铺垫举证不够
- 节奏判断绕了一圈没落地

这次重答请针对这些具体问题修正——不要重复同样的失误。
```

最后那一句"**不要重复同样的失误**"是关键——不只是"知道上次哪里没答好"，更是"明确告诉 generator 不要再犯"。

`AgentLoop` 构造函数加 keyword-only `extra_system_prompt`，baked 进 `_system_prompt`。`loop_r2` / `fast_path.run_fast_path` 同样接通。

兜底三条：previous_review 含非法字段 fallback 不注入不崩；top_issues 超 5 截断（Pydantic max_length 已守）；5 维评语全空注入说明"（无 5 维评语）"。

18 个新单测——9 条硬约束覆盖（无注入路径 / addendum 含分 + 评语 + issues / 5 维顺序固定 / 中文标签 / 缺维度 fallback / 空 top_issues / 非法格式 fallback / stream endpoint 同支持 / addendum 不互相覆盖）。pytest 618/618 全绿。

### `d387dda`：FE 重答按钮带 previous_review

ReviewCard 加 `PreviousReviewHint` interface export + `buildPreviousReviewHint(review: Review)` 转换函数。

`onRedo` callback 签名从 `() => void` 改成 `(prev: PreviousReviewHint) => void`。按钮 onClick 内联 `buildPreviousReviewHint(review)` 传出。

按钮文案 `"重答这道题"` → `"带上次批评重答"`——名字直接说出回路语义。tooltip `"带着上次评分重答 · 让 generator 知道哪几维没答好"`——再厚一层说明。

`web/src/App.tsx` 联动改：`streamAskAgent` 加 `previousReview` 参数 + POST body 加 `previous_review` 字段；`runAsk` 加可选 `previousReview` 参数；`handleRedo` wrapper wire 给 `ReviewCard.onRedo`。

### 回路完整接通

从评分到重答的完整链路：

1. BE reviewer 评分 → SSE ReviewEvent emit
2. FE 显示评分卡 + 重答按钮
3. 用户点重答 → FE 把 review 转 PreviousReviewHint 传 POST
4. BE 收到 → `_build_review_addendum` 拼到 system prompt 末尾
5. AgentLoop 拿 extra_system_prompt baked 进 `_system_prompt`
6. generator 这次答时看到"上次哪里没答好要改"
7. 结果：评分 < 18 重答能针对 5 维短板改，不是同 prompt 碰运气

这是 BookScope 第一次有真意义上的"自我进化回路"——不再依赖副管理人工调 prompt，用户每次点重答都在 BookScope 内部触发一次"针对短板的改答"。

bundle 不变，gzip 74.78 KB。

### 反思：reviewer 的二级身份

chapter-07 末尾写过——reviewer 从"研究侧评估器"切到"用户侧第二视角"。那是 reviewer 角色的第一次迁移。

`99ab6cb` + `d387dda` 让 reviewer 又多了一层身份——**generator 的内部反馈源**。reviewer 不只是给用户看分，它给的 5 维评语和 top_issues 直接喂回 generator 让下一次答得更好。

这一层身份对 BookScope 长期质量的意义比"给用户看分"更大——它把"自我进化"从副管理一个人手上转移到 BookScope 本身。副管理还会继续跑 batch 调 prompt（reviewer + generator prompt 长期演化），但是用户每一次"带上次批评重答"都在做一次微型的 prompt 优化——只对这一道题、只对这一次回答、只针对这次的 5 维短板。

作者那句"reviewer 是让你自我进化的嘛？"——这之后才是。

---

## 六、dogfood 一日的元层观察

四句话九 commit 跑完，回头看几件事——

### 反馈不是 bug 报告，是边界检测

作者四句话里没有一句是"BookScope 崩了"或"BookScope 算错了"——四句全是**产品视角和工程师视角的边界**。

- **第一句**（思考时间长不知道多久）：后端有 5 类路由分级，前端完全瞎——工程师视角觉得"后端做了细分就够"，用户视角需要把细分**告诉用户**
- **第二句**（中文表达很奇怪）：错误兜底文案是"运维视角"写的——"BookScope 已经记下了"是给运维看的（日志有了），不是给用户看的（用户不在乎 BookScope 内部记没记）
- **第三句**（按字数分 + 问题处理引擎）：fast_path 5 类关键词是工程师视角设计——"细分越多越精准"。用户视角不需要 5 类，只需要"快 vs 深"——其余 BookScope 自己判
- **第四句**（reviewer 让你自我进化的嘛）：reviewer 接 user-facing 是工程师视角的进步——"让用户也能看到分"。但用户视角真正想要的不是"看分"，是"知道下次怎么改"——这才是 reviewer 重答回路出现的真原因

### 这些差距只能靠真 dogfood 发现

文档读多少遍都看不出来。CLAUDE.md 第三条中文写作硬规则、memory `feedback_natural_chinese.md`、memory `feedback_user_not_only_author.md`——三条都明示"用户视角不是工程师视角"。三条都被遵守。但是产品里这四个 gap 没被发现。

原因不是规则不够清楚——原因是规则覆盖不到没出现过的产出口。ErrorBanner 文案没人在 batch 里读过，RouteDecision 标签没在评估里出现过，"重答按钮带 previous_review" 这件事在工程方案里根本没成为问题。

只有真打开浏览器、真上传 epub、真点题、真等十几秒、真看错误兜底、真看评分卡——这些产出口才被一次性曝光。一次 dogfood 触发九 commit——比一个月在闭门工程里改 90 commit 的产品价值高。

### 这一天的 push back

值得记的一笔——副管理在第三句反馈那里 push back 过。

作者说"按字数分"——副管理没有立刻接，而是给出三个反例（"作者最强的论点是什么？" 12 字、"这本书最让人意外的发现是什么？" 14 字、"和同类书比，这本独到在哪里？" 14 字）+ 修正方案"字数主信号 + 诊断词兜底"。

作者点头——方案定下来。这条 push back 救了 BookScope——纯字数分会把 P1 验证最依赖的几类短深题打死（memory `feedback_p1_writer_vs_general_questions.md` 记过：作家不需要通识题、需要的恰恰是 12-14 字的短深题）。

这是 CLAUDE.md 第二条"批判性辅助硬规则"在产品决策里第一次真起作用——副管理不是顺从执行者，看到方向偏了立刻给具体理由。

教训：dogfood 反馈不等于直接执行。作者的反馈是产品视角的真实信号，但**翻译成工程方案时该 push back 的就 push back**——产品视角和工程视角都要在场，最后定的方案才完整。

### Sprint 10 那一天

按 ROADMAP，Sprint 10 是作者亲笔润色定稿 case-study 的那一周。chapter-08 这一天写的是"用户视角第一次回来锤工程视角"——那一周大概率会触发同样的差距曝光：**"案例研究内部语境"vs"对外发表语境"也会有类似 reframe**。

副管理 RE 这一个月草拟了 chapter-01 到 08 八章——按"内部语境"写，给 BookScope 团队（副管理 + 派出去的 agent）看。但 case-study 对外发表那一刻读者不是 BookScope 团队，是其他想搞 AI 评估 / 长文本 retrieval / 查询时代理的工程师。

那一周可能会出现的反馈：

- 哪些章节"太内部"——只有跟着 sprint 跑过的人才看懂
- 哪些技术细节作者不在意但读者会在意（反之亦然）
- 哪几个 framing 翻转点没讲清楚——读者抓不到那一刻发生了什么

到那一周再看。chapter-08 是 dogfood 进产品；chapter-09 或 chapter-10 大概率会是 dogfood 进 case-study。

---

## 七、一日 9 commit 的尾巴

按时间排：

| commit | 时间 | 内容 | 行数 |
|--------|------|------|------|
| `391d59a` | 13:54 | FE · ErrorBanner 5 + fallback 文案重写 | +10 / -11 |
| `c05b865` | 13:54 | BE · RouteDecisionEvent SSE + 13 测试 | +669 / -8 |
| `bae4b17` | 13:55 | FE · RouteDecisionBanner + elapsed 计时器 | +222 / -4 |
| `e90d616` | 14:11 | FE · KG 改"解析" + 快/深问加预期时长 | +6 / -6 |
| `9b7f77b` | 15:19 | BE-A · fast_path 砍 5 类到 2 类 | +140 / -149 |
| `e854cd4` | 15:20 | BE-B · 问题处理引擎 + 19 测试 | +1142 / -6 |
| `99ab6cb` | 15:21 | BE-C · reviewer 重答带批评回路 + 18 测试 | +729 / -0 |
| `b16cd5f` | 15:31 | FE-A · QuestionBreakdown 接拆题事件 | +192 / -4 |
| `d387dda` | 15:32 | FE-B · 重答按钮带 previous_review | +42 / -6 |

13:54 到 15:32——一小时三十八分钟。前 4 commit（391d59a → c05b865 → bae4b17 → e90d616）是"路由可视化 + 文案重写"那一组，集中在下午两点；后 5 commit（9b7f77b → e854cd4 → 99ab6cb → b16cd5f → d387dda）是"fast_path 重构 + 问题处理引擎 + reviewer 回路"那一组，集中在下午三点。中间一小时多用来跟作者来回 push back + 定方案 + 派 BE-A / BE-B / BE-C 三个 agent 并发（参考 memory `project_team_concurrency_default.md` 的并发模式）。

代码量加起来 +3152 行 / -194 行——但回头看每一行都能追到那四句话之一。这是 chapter-08 想留下来的具体性——**用户视角和工程视角的距离在产品里能用 commit hash 量化**。

reviewer 走出实验室是 chapter-07 那天；用户视角走进 BookScope 是 chapter-08 这一天。两件事接在一起——这才让 NORTH_STAR 第 1 条"服务作者本人作为长篇网络小说创作者的第一读者工具"在工程里真活下来。

下一次 dogfood 大概率还会出现新的四句话。但这一天的 9 commit 已经让 BookScope 第一次有了**用户视角的形状**。

---

*本章草稿到此为止。dogfood 一日 9 commit 已覆盖、4 句反馈对应 4 节展开、push back 那段在第四节明示。定稿由作者在里程碑点统一润色。*
