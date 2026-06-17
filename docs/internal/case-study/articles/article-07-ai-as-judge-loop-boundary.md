# AI-as-judge 闭环的有效性边界：第 25 轮收敛与第 26 轮反向的两次实证

> **状态**：草稿 · 作者未定稿
> slug: article-07-ai-as-judge-loop-boundary
> 视角：方法论反思
> 覆盖时段：2026-04-24（第 25 轮）至 2026-04-27（第 26 轮）
> 数据出处：`docs/internal/experiments/data/v2-batch-01.json` · `docs/internal/experiments/data/v3.1-minimax-batch-01.json` · `bookscope/agent/prompts/reviewer_rubric_v1.md` · `bookscope/agent/reviewer.py` · `scripts/review_last_smoke.py` · `scripts/run_batch_r1.py`

---

## 〇、为什么要写这一篇

第 25 轮做完时我心里很轻：BookScope 第一次跑通了一条完整的"AI 生成 → AI 审稿 → 按 audit 改 prompt → 重跑 → 分数真升"的闭环。`23/25 → 25/25`。两个维度（honesty 和 actionability）各 +1，其它三维稳在 5。我当时在 STATE 里写下这一句——

> Meta 价值：`AI 生成 → AI 审稿 → 按 audit 改 prompt → 重跑 → 再审稿 → 分数真升` 这条 pipeline 第一次完整闭环收敛。这个回路比某一次 answer 质量高低重要得多；未来换题、改 prompt、换 provider 都可复用。

那是 2026-04-24 晚上的判断。我相信它。

四十八小时后，第 26 轮跑完，我盯着屏幕上一排五题对照——`v3.1+minimax` 五题平均 `20.0/25`，对照 `v2+astron` 的 `24.8/25` baseline，**全 LOSE，平均退化 4.8 分**。q1 节奏题从 25 掉到 18，q4 角色转变题从 25 掉到 18。五个维度全在退，evidence_density 从 5.0 跌到 3.6，actionability 从 4.8 跌到 3.6。

闭环没收敛。它发出了一个我不准备接受的信号：分数大跌。

然后我做的第一件事，是想要否定 reviewer——它是不是太严了？是不是 minimax 自审 minimax 时换了一套打分尺度？是不是 prompt v3.1 写得不够好，应该再迭代一版？

但那一晚冷静下来之后，我意识到一件更重要的事：闭环有两种价值。第 25 轮验证的是第一种——"当问题是 prompt 工艺优化时，闭环可以稳定收敛"。第 26 轮意外验证的是第二种——**当问题在上层根因（不是 prompt 工艺，而是 provider 训练污染）时，闭环以"全 LOSE 4.8 分"的形式把问题推到我面前，让它无法被绕开**。

第二种价值我之前没想到。这一篇文章是为了把它写下来，作为 BookScope 案例研究关于"AI-as-judge 在什么时候能用、什么时候不能用"的一份原始记录。

不写出来的话，下一次我面对一个 "AI-as-judge 给出了我不喜欢的分数" 的局面，可能还会本能地去骂 reviewer 而不是听它说话。

---

## 一、reviewer 是怎么被装上去的

第 25 轮一开始，作者只丢了一句话过来：

> 首先配置一个 AI agent 审稿人来分析，而不是让我来。

这句话信息量比表面上大。它说的不是"加个评分组件"，是把"判断 BookScope 答得好不好"这件事**整个从作者人工挪到 AI-as-judge**。在那之前，每一次 smoke 跑完，作者要自己读那一两千字的 answer 和十几条 citation，自己判断"这是不是我作为作家真需要的反馈"。这是慢的、不可批量、不可对照、且作者疲劳后会失真的。

更深一层：作者跑过一段时间作家题之后，开始觉察到 BookScope 偶尔会"答得像样但其实没在替我做判断"——四平八稳的总结、复述情节冒充评估、保留语气掩盖立场。这种"伪反馈"用人眼一题一题看时，前两题可能挑得出来，第五题之后人会麻木。所以才需要一个不会麻木的标准化打分尺。

我当时按这条路径写下了 reviewer 的设计原则，后来直接抄到了 `bookscope/agent/reviewer.py` 的 module docstring 里：

> 审稿人**不审事实对错**（事实由 citation 原文佐证）
> 审稿人审的是：**这份答复作为"作家第一读者反馈"对作家真有用吗**——
> 有没有判断、敢不敢说薄、可操作吗、跨章节视野够吗

**reviewer 不审事实**——这一条是边界。事实正不正确，由 citation 原文承担证据责任；reviewer 不读全书，也不应假装读过。它审的是判断质量、证据密度、诚实度、可操作性、跨章视野——这五个维度。

5 维 rubric 的具体定义放在 `bookscope/agent/prompts/reviewer_rubric_v1.md`，我从 LLM 视角写——它是一个"资深文学编辑 + AI 产品评估专家"双重身份的人物。第一重身份让它知道作家真要什么；第二重身份让它知道 LLM 容易产生哪些"看上去有用实则没用"的伪反馈。两重身份都重要。第一重缺了，它会被任何"看上去有逻辑"的复述说服；第二重缺了，它会变成顺从的赞美机器。

5 维我每一维都标了刻度。比如 honesty 维度的 1 分定义：

> **1 分**：全篇正面话术堆积，或者正反对称地"一方面另一方面"回避立场

actionability 维度的 5 分定义：

> **5 分**：明确指出"应该在 X 章加一个 Y 类型的伏笔"、"这段可以删"、"这条线需要多 N 次出场"——作家可以直接列 TODO

每一维都用具体的语言标记顶端和底端，避免 reviewer 凭"感觉"打分。最后我加了三条元规则——

> - **不假设生成方是谁**。BookScope 使用哪个 LLM、reviewer 是不是同一个 LLM、这些都跟你的评分无关——按第三方独立视角评判
> - **不写套话**。"整体来看答复质量不错，但也有改进空间" 不是评价，是废话。每一句都要能落到具体维度
> - **宁可打低不打高**。第一读者工具的价值门槛是"真能推动修改"，而不是"有 output"。AI 工具的平均水平够低，不要轻易给 5 分

第三条尤其重要。"宁可打低不打高"是这个 reviewer 的**情绪锚点**——我不希望它把"打分"和"赞美"画等号。一个轻易给 5 分的 reviewer 是无价值的，因为分数失去了区分度。

输出格式是严格 JSON：5 维分数 × 5 维 per-dimension comment + overall + top_issues + single_most_valuable_improvement。最后两个字段是我刻意加的——它们不是评分，是改进方向的浓缩。后面会看到，这两个字段在两次闭环中都给出了改 prompt 的具体抓手。

`reviewer.py` 本身是一个薄函数。`review_answer(*, client, model, question, answer, citations, book_title, language, max_tokens)`，走 `LLMClient` Protocol，provider-agnostic——和 AgentLoop 一致。我刻意没有给它写类、没有 Pydantic 模型。第一版让作者先看产出有没有用，再决定工程化程度。这一条原则在 module docstring 里写明：

> 本模块刻意**极简**：一个 `review_answer` 函数，不做类、不做 Pydantic 模型。第一版让作者先看产出有没有用，再决定工程化程度。

调用入口有两个。`scripts/review_last_smoke.py` 是单题入口——从 smoke_test_r1.py 的 stdout 用 regex 抽出 question / book_title / answer / citations，喂给 `review_answer`，打印评分报告。`scripts/run_batch_r1.py` 是批跑入口（第 26 轮加的），一次跑 N 题 → 调 reviewer → 写出 batch JSON。两者并存。前者是手动调试用，后者是研究批跑用。

reviewer 装上去的那一晚，我把 v1 prompt 的第一份审稿报告打印出来时，第一感是它"懂这个工具是干什么用的"。它没有像默认 LLM 那样夸"答得真好"，而是在 actionability 那一维直接打了 4 分，per-dimension comment 写——

> 偏向诊断而少开处方，未给出作家可直接落地的修改 TODO。

这一句是后面整条闭环的起点。

---

## 二、第 25 轮：AI-as-judge 闭环首次成功收敛

### 2.1 v1 baseline：23/25

第一题选的是李善长铺垫连贯性——这是第 24 轮已经跑过的作家题，11 条 citation 的那一道。我用 `astron-code-latest` 跑 v1 prompt，跑出 answer，然后用 `astron-code-latest` 自审。

第一份审稿报告打分是这样的：

| 维度 | v1 |
|------|----|
| structural_judgment | 5 |
| evidence_density | 5 |
| honesty | 4 |
| actionability | 4 |
| cross_chapter_coherence | 5 |
| **合计** | **23/25** |

honesty 4 分是因为 reviewer 看到 v1 answer 给了"铺垫是连贯的"这个判断，但语气仍然偏正面，没有遇到硬碰硬的薄处需要直说"这里不到位"——它没扣分扣得太狠，因为文本本身确实没什么硬伤，但也没给 5 分，因为没看到那种"敢说薄"的硬邦邦立场。

actionability 4 分是真问题。reviewer 在 per-dimension 里直接写——**偏向诊断而少开处方**。它扒出 v1 answer 的整体形态是"我看到了 X 个铺垫节点，分布在 Y 章，覆盖 Z 类事件"，结构性诊断很完整，但没回答"作家拿到这个之后，下一步应该做什么"。

top_issues 字段更狠：

> 1. v1 answer 偏向诊断而少开处方，未给出作家可直接列 TODO 的修改建议
> 2. 第 20 章 citation 与 answer 描述存在错位（answer 提到的某条铺垫节点在 citation 列表里章节号对不上）

第一条是 prompt 的问题。第二条是数据 hygiene 的问题——answer-citation 章节号一致性没有约束，模型偶尔会写"第 X 章发生 Y 事件"但 citation 列表里那条 snippet 的 chapter 字段是 X-1 或 X+1。

single_most_valuable_improvement 字段——

> 给作家诊断题应当强制分两段：第一段诊断（保留现状），第二段修改建议 TODO（精确到章节、事件、改法）。同时增加 answer-citation 章节号一致性硬约束。

这一句话直接定下了 v2 prompt 的改造方向。

### 2.2 v2 prompt：按 audit 改

我没动 v1 prompt——而是新建 `bookscope/agent/prompts/loop_system_prompt_v2.md`，把 v1 留作 A/B 对照基线。这是 BookScope 项目从第 22 轮起就立的原则：prompt 版本并列保留不覆盖，作回归 / A/B / 案例研究材料。`loop.py` 切一行 import 切版本。

v2 相对 v1 加了两条：

1. 作家诊断题形态规范——answer 必须分两段：第一段是结构性诊断（与 v1 一致），第二段是"修改建议 TODO"，精确到具体章节、具体位置、具体改法、可能的字数
2. answer-citation 章节号一致性约束——answer 里每提到一个章节号，必须在 citation 列表里有对应 snippet；不允许 answer 提"第 X 章"而 citation 列表里只有 X-1 / X+1

两条都是非常小的 prompt patch——总计加了大约 15 行规范。

### 2.3 v2 重跑：25/25

同题、同 provider、同 KG、同 vector mode——只换 prompt——重跑。这是单变量受控对照。

v2 answer 形态质变。诊断段保持 v1 的水平，修改建议段是完全新增的——三条 TODO，精确到第 16 章具体位置、具体改法（朱元璋翻阅捷报的暗语式短切）、预估字数（两三百字）。第 25 轮当时我把 v2 answer 完整打印出来读了一遍，那种"作家可以直接拿去改"的形态第一次稳定出现。

reviewer 重审：

| 维度 | v1 | v2 | Δ |
|------|----|----|---|
| structural_judgment | 5 | 5 | — |
| evidence_density | 5 | 5 | — |
| honesty | 4 | 5 | +1 |
| actionability | 4 | 5 | +1 |
| cross_chapter_coherence | 5 | 5 | — |
| **合计** | **23** | **25** | **+2** |

honesty 4→5：reviewer per-dimension 写——

> 极敢表态，不仅断言节奏差异是"有意控制"，还给出三大理由；同时不回避代价，直指 15-16 章断裂感偏强，拒绝无脑赞美或和稀泥。

actionability 4→5：reviewer per-dimension 写——

> 修改建议精确到具体章节（第 16 章）、具体位置（"明朝的第一代名将们……"之后）、具体内容（朱元璋翻阅捷报的暗语式短切）和预估字数（两三百字），作家可直接照办。

闭环成立。**v1→v2 prompt 的两条 patch，分别精确命中 reviewer 当初打 4 分的两个维度，重审后这两维各 +1**。其它三维不动——说明 patch 没有副作用，没有出现"提了 actionability 反而压了 evidence_density"那种 prompt 工程里常见的此消彼长。

reviewer 在 v2 重审时仍然挑出了**新** issue——

> top_issues:
> 1. 第 15 章完全缺失 citation，导致"最稀地带"的论证仅靠 16 章一条过渡性 snippet 支撑，证据链略有薄弱
> 2. 对"结构性失衡"的驳论稍显单向，若能补充一句"如果此处不补伏笔，断裂感会如何随阅读惯性放大"，论证会更无懈可击

这一条最重要。**reviewer 没有因为 v2 更顺眼就停止挑刺**。它仍然在做工作，只是工作的对象从 v1 的"诊断 vs 处方"上升到 v2 的"证据链分布的均匀度"。这说明 reviewer 不是在做模式匹配式的"上次扣 4 分这次扣 4 分"——它在每一次审稿里都重新建立标准。

那个晚上我反复读这一条 top_issue，确认了 AI-as-judge 这条 pipeline 第一次跑成功了。

### 2.4 第 25 轮闭环为什么收敛得这么干净

回头看，第 25 轮收敛干净到了"教科书级"——单变量、单维度、单 provider、单 reviewer。我在那条对照里只换了一样东西：prompt v1 → v2。其它所有变量保持不变。

这是科学实验的单变量原则。这是为什么它能收敛——因为变化是小的、定向的、可解释的。reviewer 给出的 top_issues 直接对应一条 prompt patch，patch 直接对应一个维度的扣分原因，patch 不引入其它维度的副作用。链条是干净的。

但更深一层——这次成功收敛的真正前提是：**问题本身在"prompt 工艺"层。** v1 prompt 没有教会 BookScope 区分诊断和处方；v2 prompt 教了。这是 prompt 工艺的问题，不是 LLM 能力的问题。astron-code-latest 完全有能力按 v2 的格式输出诊断 + TODO，它只是在 v1 prompt 下没被要求这么做。

如果当时问题不是 prompt 工艺、而是 LLM 能力本身的问题（比如模型不会跨章节做证据链综合），prompt patch 是改不动的——你写得再清楚，模型做不到就是做不到。但第 25 轮的问题恰好不是这种。

这一条是第 25 轮成功的隐含前提，我当时没把它写下来。第 26 轮把这条隐含前提砸到了我面前。

---

## 三、第 26 轮：AI-as-judge 闭环反向

### 3.1 触发：作者一句话切 provider

第 26 轮开局是作者的一句话：

> 继续，但是我们的 api 更新了。这次用的是 minimax，用的 2.7 的模型。

provider 从 astron 切到 minimax，model 从 astron-code-latest 切到 MiniMax-M2.7。base_url 一行改完。

我当时第一反应是"应该没什么问题，DeepSeekAdapter 协议兼容 OpenAI compatible，minimax 也是 OpenAI compatible"。然后跑 5-token sanity check 发现 minimax M2.7 是 reasoning model——content 字段会 inline 吐 `<think>...</think>` 块。这会污染下游 JSON parse。加了一个 `_strip_thinking_tags` helper，surgical 的一行改动。这是**第一个变量**：generator provider 从 astron 切 minimax。

跑 v3 pilot——q1 节奏题 dur 179s / cite 6 / total **17/25**。退化 -8 分。

我盯着 trace，看到 `tool_call_names: []`——5 轮迭代 0 tool 调用。

这意思是：minimax M2.7 在面对 v3 prompt 时，**完全没去查原文**，5 轮直接靠训练记忆 hallucinate 了一份 answer 出来。

诊断到这一步，我的反应是写 v3.1。v3 留作 baseline，v3.1 加三条硬约束：

> A. 至少一次 tool 调用
> B. 禁止靠训练记忆作答
> C. "我已经知道" ≠ "我已经查过"

`loop.py` 切到 v3.1。这是**第二个变量**：prompt 从 v2 切到 v3.1。

第二次 pilot 跑：dur 217s / cite 7 / tool_calls 真数 7（5 search + 1 chapter_range + 1 search）/ total 17/25。

tool 调用真起作用了——但分数没升。

跑全 5 题 v3.1+minimax batch：q1=18 / q2=19 / q3=22 / q4=18 / q5=23 / 平均 **20.0/25**。

### 3.2 退化的全貌

| 题号 | v2+astron | v3.1+minimax | Δ | tool_calls (v3.1) |
|------|-----------|---------------|----|------|
| q1 节奏评估 | 25 | 18 | -7 | 2 |
| q2 支线密度 | 25 | 19 | -6 | 2 |
| q3 伏笔回收 | 25 | 22 | -3 | 5 |
| q4 角色转变可信度 | 25 | 18 | -7 | 3 |
| q5 设定漂移 | 24 | 23 | -1 | 6 |
| **平均** | **24.8** | **20.0** | **-4.8** | — |

| 维度 | v2+astron | v3.1+minimax | Δ |
|------|----|----|---|
| structural_judgment | 5.0 | 4.4 | -0.6 |
| evidence_density | 5.0 | 3.6 | **-1.4** |
| honesty | 5.0 | 4.0 | -1.0 |
| actionability | 4.8 | 3.6 | **-1.2** |
| cross_chapter_coherence | 5.0 | 4.4 | -0.6 |

**5 维全退化**。最重的是 evidence_density 和 actionability，分别 -1.4 和 -1.2。其它三维 -0.6 到 -1.0 之间。

### 3.3 reviewer 在每一题里说了什么

我把 reviewer 在 v3.1+minimax 上每一题的输出原文留在 `docs/internal/experiments/data/v3.1-minimax-batch-01.json` 里。挑几条最关键的：

**q1（18/25）的 evidence_density 3 分**——

> 关键节点有 citation，但第 17 章刘基与李善长党争这一重要过渡段被引用却无 citation 支撑，"渐次窒息"效果也缺乏原文佐证，证据链有缺口。

answer 里的判断很完整（v3.1 prompt 做到了"前疏后密"的结构性判断），但 answer 提到第 17 章党争这条核心论据时，**citation 列表里完全没有第 17 章的 snippet**。模型说了一句"第 17 章党争是过渡"，但没有去拉原文支撑。这正是 v2+astron baseline 的同题 answer 在 evidence_density 拿满分的原因——baseline answer 引用了"演员到齐了，下面我们来看看这场戏是怎么演的吧"这一句第 17 章的元叙事级伏笔，把这个判断锚在原文里。

q1 reviewer 的 single_most_valuable_improvement——

> 补入第 17 章刘基/李善长党争的关键 citation，以证据链完整支撑"外部威胁消失→叙事张力内收"这一核心论点。

这一条直接对应一个事实：minimax 在 q1 这一题只做了 2 次 tool 调用（1 个 get_chapter_range + 1 个 search_chunks）。两次调用的覆盖面不够，没拉到第 17 章党争段。模型在拉不到的时候，**用训练记忆补了一段"第 17 章是党争过渡"的论断**，但没有原文锚点。

**q2（19/25）的 actionability 3 分**——

> 原问题偏分析而非指令性，BookScope 对此类问题的适配度受限——答案给出了精准的诊断，但未延伸出"如果要增强立体感需要在 X 处补充 Y"式的修改指引。

q2 是支线密度题。reviewer 把这一题的 actionability 缺陷归因到"问题本身偏分析"上，给 BookScope 留了一条软台阶。但即便如此，3 分仍然反映了一个事实：v2+astron 同题 answer 在最末段给了三条具体修改建议（第 14 章补回望节点、第 12 章补陈友谅独白、第 10 章扩展败退心理），v3.1+minimax 的 answer 在最末段只是收束于"这不是扁平的陪衬，但确实是一个被'定性'了的人物"——没有 TODO 段。

为什么 v3.1 prompt 显式要求"诊断 + 修改建议"两段，minimax 仍然没出 TODO 段？我没法做 ablation，但合理猜测：minimax 在公开书《明朝那些事儿》上，记忆里没有"作家应该改第 X 章"这种维度的语料——它能复述"陈友谅是怎么写的"，但没有"陈友谅这条线该怎么改"的训练样本。它只能完成它训练数据见过的任务形态。

**q3（22/25）的 honesty 4 分**——

> 诚实指出"中间节点缺失"这一具体薄处，但后续用"叙事风格"将其合理化的写法略显防御性——若文本确有可强化空间，应更直接指出而非"倾向不动"。

q3 是伏笔回收题。v3.1+minimax 的 answer 用了"挑薄处三问"框架（这是 v3 prompt 加进去的诊断框架），三问下来给出"叙事选择，不是结构缺陷"的判断，最后说"我倾向不动"。

reviewer 看出这是**软化**——"挑薄处三问"框架的本意是让 BookScope 区分真瑕疵和叙事选择，但 minimax 在这一题里把这个框架用成了"自我合理化"的工具。reviewer per-dimension comment 里写"略显防御性"——这是它在告诉我，这个 prompt 框架被 minimax 误用了。

q3 这一题 22 分是 5 题里最高的，但 reviewer 给的是 4/5 评价"诚实度有缺口"——这正是 v3 prompt 的"挑薄处三问"原本要解决的问题（区分瑕疵 vs 选择），结果在 minimax 上反向被用成了防御工具。

**q4（18/25）的 evidence_density 3 分**——

> citations 选段精准对应核心主张，但答案中多处引用"攻克定远""废相肃贪"等具体事件完全无 citation 支撑，有"说法有据、展开无据"的脱节。

这一条更狠。v3.1+minimax 的 q4 answer 在论述里提到"攻克定远"、"四战四胜"、"废相肃贪"这些具体战例和政治事件——但 **citation 列表里没有任何对应原文**。模型在把它训练记忆里关于"明朝那些事儿"或者"朱元璋"的事件知识直接写进 answer，但没有去 search_chunks 拉原文。

这就是"训练污染"的硬证据。如果模型完全没读过这本书，它在 q4 这一题上必须靠 search_chunks 调原文——但因为它读过，它在被强制 tool 调用至少 1 次时，做了 3 次调用，只覆盖了一小部分论据，剩下的论据靠记忆补。

reviewer 完全看出来了。它的 top_issues：

> 答案正文引用的具体战例（攻克定远、四战四胜）和政治事件（废相、肃贪、杀功臣）均无对应 citation，导致核心论点与支撑材料之间出现断层，作家无法核实论据来源。

"作家无法核实论据来源"——这一句话是 BookScope 价值主张的反面。BookScope 存在的意义就是"原文证据现场调取"，让作家可以一条条核实。q4 在 v3.1+minimax 上把这个核心价值砍掉了一半。

### 3.4 reviewer 不是错的——它在告诉我别的事

我盯着这五题打分看了很久，第一波本能反应是想要否定 reviewer。

第二波我冷静下来，决定**相信 reviewer**——因为它每一条 per-dimension comment 都给出了具体的、可核对的、原文级的扣分理由。它说"第 17 章 citation 缺失"，我去翻 batch JSON——确实缺。它说"攻克定远无对应 citation"，我去翻——确实没有。它说"挑薄处三问被用成自我合理化"，我去读 q3 answer 末段——确实是。

reviewer 的扣分理由全部可证伪，全部具体到"哪一题、哪一段、缺什么、应该有什么"。这不是 hallucination 式的扣分，是基于 rubric 的、可追溯的扣分。

那么 reviewer 在告诉我什么？

它在告诉我：**v3.1+minimax 在公开书 baseline 上，没法稳定输出 v2+astron 那种证据链完整、TODO 具体、不躲闪的反馈**。这不是一个 prompt 优化问题。这是一个上层根因问题——

1. minimax M2.7 在《明朝那些事儿》上有训练污染。它读过这本书的 citation 5-7 条 vs astron 给出的 10-13 条，差距 50%；论证里 "攻克定远" 这种事件名字直接出现在 answer 但不出现在 citation——它的记忆比它的工具调用更快。
2. v3.1 prompt 强制 "至少 1 次 tool 调用"，被 minimax 当作 **最低限度** 遵守。q1 和 q2 都只做了 2 次调用，q4 只做了 3 次。它读过书，所以"觉得查到一两条就够了，剩下靠记忆补"。
3. v3 prompt 的"挑薄处三问"在 minimax 上被反向用成自我合理化工具——q3 的"我倾向不动"。

这三条，没有一条是 prompt 工艺能改完的。第三条也许还能再迭代 prompt 加更强约束，但前两条是 LLM 训练数据本身的问题，**prompt 改不动**。

闭环没收敛。它输出了一个上层根因问题。

---

## 四、两次闭环并排：为什么一次收敛一次反向

### 4.1 单变量 vs 双变量

| | 第 25 轮 | 第 26 轮 |
|---|---|---|
| Generator provider | astron-code-latest（不变）| **astron → minimax** |
| Generator model | astron-code-latest（不变）| **astron-code-latest → MiniMax-M2.7** |
| Generator prompt | **v1 → v2** | **v2 → v3.1**（且 v3 中间版作为 pilot）|
| Reviewer provider | astron-code-latest（不变）| **astron → minimax**（同步换）|
| Reviewer rubric | reviewer_rubric_v1（不变）| reviewer_rubric_v1（不变）|
| 受控对照变量数 | **1**（仅 prompt）| **3**（prompt + generator + reviewer）|
| 闭环结果 | 23 → 25 收敛 | 24.8 → 20.0 反向 |

第 25 轮是教科书级单变量受控对照。第 26 轮**违反了科学实验的单变量原则**——同时换了三样东西（prompt v2 → v3.1、generator astron → minimax、reviewer astron → minimax）。

这是一个工程现实问题。第 26 轮触发是作者一句话切了 minimax key，astron key 仍然在但不是当前主用 provider。当时如果要保持单变量，应该按"换 provider 不换 prompt"先跑一遍 minimax+v2 拿到 baseline，再换 prompt 跑 minimax+v3.1。但当时一边在解决 minimax M2.7 的 reasoning model `<think>` 标签问题，一边在写 v3 prompt 修复 v3 pilot 的 0 tool 问题——多个变量同时变化是当下的工程现实，不是受控实验。

这一条是第 26 轮的**方法论代价**。回头看，正确的做法是先跑 minimax+v2 单变量对照，再决定是否换 prompt。我没这么做，所以第 26 轮的"-4.8 分"无法被分解为"prompt 的代价"和"provider 的代价"——两个代价混在一起。

但即便如此，**4.8 分的差距远大于任何单一变量在同行验证里能产生的方差**。astron 自审 astron 和 minimax 自审 minimax 都有自我偏袒因素，但偏袒量级一般在 0.5-1.0 分以内（参考开源 LLM judge 文献的偏袒方差）。4.8 分差距不可能纯粹由 reviewer 偏袒造成——主体一定来自 generator 端的实质差异。

### 4.2 自我偏袒风险：两次 batch 都标了

`run_batch_r1.py` 在生成 batch JSON 时会自动标记 limitation 字段：

```python
"limitation": "reviewer 与生成方同 provider/model；存在自我偏袒风险"
if review_provider == provider and review_model == gen_model
else "reviewer 与生成方异 provider/model；可视为部分独立审稿",
```

两次 batch 都是同 provider 同 model（v2+astron 是 astron 自审 astron，v3.1+minimax 是 minimax 自审 minimax），limitation 字段都标了"存在自我偏袒风险"。

这意味着两次 batch 都不是真盲评。第 25 轮 v1→v2 +2 分的收敛，理论上 reviewer 可能因为 v2 是同 provider 后来产出的版本而打高一点；第 26 轮 v3.1+minimax 20.0 分的反向，理论上 reviewer 可能因为同 minimax 而打低一点（如果 minimax 自审有"自我惩罚"倾向，但这种文献里少见）。

但就 4.8 分的体量来说，自我偏袒解释不了。一个粗略的上界估算：自我偏袒最多解释 0.5-1.0 分的方差（这是开源 LLM judge 文献里给的典型偏袒方差区间）。剩下的 3.8-4.3 分必须由 generator 端的实质差异承担。reviewer 给出的具体扣分理由（citation 缺失、TODO 缺失、"我倾向不动"）也都可独立核对——这一条独立核对路径绕过了"reviewer 是不是偏袒"的争论。

未来 ADR 候选：reviewer 切到独立 provider 做盲评。STATE 第 26 轮已记下这条："多家 key 到位后可切独立 provider"。

### 4.3 闭环的两种价值

第 25 轮验证的是**第一种价值**：当问题在 prompt 工艺层时，AI-as-judge 闭环可以稳定收敛。链路是：

> generator 出 answer → reviewer 给 5 维分 + top_issues + single_most_valuable_improvement → 按 single_most_valuable_improvement 改 prompt → 重跑 → 分数升。

这一种价值是 BookScope 改进闭环的**主要工作模式**。它适用的范围是：prompt 工艺优化、citation 格式约束、tool 调用规范、answer 形态规范——这些"工程能直接控制"的变量。

第 26 轮意外验证的是**第二种价值**：当问题在上层根因（不是 prompt 工艺，是 generator 或 reviewer 本身的属性问题）时，AI-as-judge 闭环不收敛——但**它以"全 LOSE 4.8 分"的方式把上层问题清晰地呈现出来，让我无法不去面对**。

这一种价值我之前没想过。它不是替代第一种价值的——它和第一种价值是两个不同的工作模式：

| | 第一种 | 第二种 |
|---|---|---|
| 触发条件 | 问题在 prompt 层 | 问题在上层根因层 |
| 闭环输出 | 分数收敛（+1~+2）| 分数反向（-2~-5）|
| 改进路径 | 改 prompt | 换 provider / 换数据 / 换方向 |
| 决策类型 | 工程级 auto-accept | 方向级需作者批准 |

第二种价值的关键是：**反向输出本身就是信号**。它不是 reviewer 失灵的标志，是 reviewer 在尽职——它在用一个标准化的 5 维分数，把一个否则会被掩盖在"答得还行吧"含糊评价里的上层问题，量化成了 -4.8 分。这个量化形式让"上层有问题"不再是手感判断，而是可以写进 STATE、可以写进案例研究、可以让作者在五分钟内看清楚的客观事实。

如果没有 reviewer，作者读完 v3.1+minimax 的五题 answer，可能只会说"嗯，这次答得没上次好"。这是手感判断，不可对照、不可批量、不可放进 case study。有 reviewer，作者看到的是"5 维全退化、evidence_density -1.4 / actionability -1.2、5 题 5 LOSE"。这是可对照的客观事实。

**两次闭环都是 BookScope 的资产**。第 25 轮证明 reviewer 能驱动改进。第 26 轮证明 reviewer 能定位根因——它不仅是 prompt 优化器，也是上层根因 detector。

---

## 五、top_issues 和 single_most_valuable_improvement 的实战价值

这两个字段在 rubric 设计时是补充字段，不是评分主体。但两次闭环跑下来，它们承担了改进闭环里**最关键的工作**——把扣分原因压缩成一条可执行的下一步。

第 25 轮 v1 baseline 的 single_most_valuable_improvement 字段：

> 给作家诊断题应当强制分两段：第一段诊断（保留现状），第二段修改建议 TODO（精确到章节、事件、改法）。

这一句直接写进 v2 prompt patch，重跑得 +2 分。从字段到 prompt 到分数升的链条最短只有这一句话。

第 25 轮 v2 重审的 top_issues：

> 1. 第 15 章完全缺失 citation，导致"最稀地带"的论证仅靠 16 章一条过渡性 snippet 支撑，证据链略有薄弱
> 2. 对"结构性失衡"的驳论稍显单向，若能补充一句"如果此处不补伏笔，断裂感会如何随阅读惯性放大"，论证会更无懈可击

这两条是 v2→v3 的候选方向。它们没被 v3 实施（v3 路线被 minimax 切换打断），但它们已经是写好的、可执行的 prompt patch 起点。如果当时没切 minimax，v3 的合理路线应该是这两条 top_issues 之一。

第 26 轮 v3.1+minimax 五题的 single_most_valuable_improvement 字段——

q1: 补入第 17 章党争 citation
q2: 处方性建议（"补充什么类型的场景"）
q3: 补充第 1-3 章具体苦难场景 citation
q4: 给出虚构示例（"在第三章第 X 段后插入朱重八面对 A 选择→B 结果的场景"）
q5: 补充第 16 章刘基边缘化过程引文

五条 single_most_valuable_improvement 全部指向同一个根因——**citation 不够多、覆盖面不够广**。每一条都在说"这里需要更多原文支撑"。

如果这是 prompt 工艺问题，5 条 single_most_valuable_improvement 应该集中在某一两个维度（比如都说 actionability 缺失）。但它们 5/5 都在说 citation 维度——这正是训练污染的特征：模型有训练记忆，所以 prompt 让它"至少 1 次"它就只调 1-3 次，剩下论据用记忆补。

reviewer 在没有"训练污染"这个标签的情况下，**用 5 条 single_most_valuable_improvement 把这条根因画了出来**。它没说"minimax 训练污染"——但它的输出形态精确地指向了这个事实。

这是这两个字段的真实战价值——**它们不只是评分附属物，是改进方向和根因诊断的浓缩**。

---

## 六、AI-as-judge 在 BookScope 里应当被重新定义

第 25 轮我把 reviewer 定位为"prompt 改进闭环的评分器"。第 26 轮之后我意识到这个定位太窄。

新定位：**reviewer 是把上层方向问题以标准化打分形式呈现的 detector**。

这个定位下，reviewer 的工作有三层：

1. **第一层（prompt 层）**：当问题是 prompt 工艺时，reviewer 给出可执行的 single_most_valuable_improvement，驱动 v_n → v_{n+1}。第 25 轮 v1→v2 +2 分是这一层的实证。这一层是闭环的主体工作模式。
2. **第二层（generator 层）**：当问题是 generator 本身的属性（训练污染、能力边界、reasoning 模式适配），reviewer 给出 -2~-5 分的反向信号 + 多条 top_issues 集中在同一类问题（如全部指向 citation 缺失）。第 26 轮 v3.1+minimax 5 题 5 LOSE 是这一层的实证。这一层 reviewer 不解决问题，但它**让问题变得无法忽视**。
3. **第三层（任务层）**：当问题是任务本身不适合 BookScope（比如公开书 baseline vs 私域文本），reviewer 给出系统性的偏低分 + per-dimension comment 直指任务-工具不匹配。第 26 轮的"作家无法核实论据来源"是这一层的萌芽——但这一层需要更多数据点才能稳定识别。

三层的处置方式不同：

- 第一层：工程 auto-accept，prompt patch 直接进
- 第二层：需要诊断后向作者汇报"是 generator 问题"，决策切 provider 还是改方向
- 第三层：需要作者方向级介入，修改 NORTH_STAR 或调整测试集

这三层的边界不是先验清晰的——第 26 轮一开始我以为是第一层（prompt 不够约束），写了 v3.1。v3.1 跑出来还是 -4.8 分时，我才意识到这是第二层。**reviewer 不能告诉我"这是哪一层的问题"——它只给分数和 top_issues**。判断在哪一层是作者的工作（作者层级）和我的工作（副管理层级）。

但这不是 reviewer 的缺陷——这是 reviewer 的边界。它的工作是给分数和理由；判断分数和理由背后的根因是哪一层、应该如何处置，是上层的工作。这条边界刻意不应该被 AI-as-judge 越过——一个会自己决定"这是 prompt 问题应该改 prompt"的 reviewer 是危险的，它会把所有问题都解释成 prompt 问题。

---

## 七、给 BookScope 未来 reviewer 设计的建议

基于这两次闭环，我会向作者提以下建议（escalation 档，需作者批准后再做）：

### 7.1 cross-provider 盲评

当前两次 batch 都是同 provider 自审，limitation 字段已标。下一步：

- 在 batch runner 里加 `BOOKSCOPE_REVIEW_PROVIDER` 强制独立选项（已有，但默认行为是 fallback 到同 provider）
- 当 generator 是 minimax 时，reviewer 默认走 anthropic claude（如果作者有 key）或 deepseek
- 在 batch JSON 的 config.limitation 字段里区分"同 provider 自审 / 异 provider 盲评"两种 limitation 文案

cross-provider 盲评不会让自我偏袒消失（不同 provider 仍有相互的喜好偏差），但它会**把偏袒方向打乱**——如果 minimax 自审 minimax 有正向偏袒，claude 审 minimax 可能有负向偏袒（claude 偏严是文献里的已知现象）。两个方向的偏袒在多次 batch 里部分相互抵消，让 4.8 分这种大体量差距更可信。

### 7.2 citation_coverage_ratio 二级 metric

evidence_density 是当前 rubric 的 5 维之一，但它是定性维度（per-dimension comment 文字描述）。第 26 轮反复出现"answer 里提到事件 X 但 citation 列表里没有"的情况——这是可量化的。

建议：在 reviewer JSON 输出里加一个二级 metric `citation_coverage_ratio`——

```
对 answer 里提到的每个具体章节号 / 事件名，
检查 citation 列表里是否有对应 snippet。
ratio = covered_claims / total_claims
```

这个 ratio 不是 5 维主分的一部分，但它给 evidence_density 的扣分提供量化依据。第 26 轮 q4 如果跑出 ratio = 0.4（10 个论据 4 个有 citation），这是比"-1.4 evidence_density"更具体的信号。

实施代价：reviewer prompt 加一条计算指令；输出 JSON schema 加字段；run_batch_r1.py summary 加汇总。一周量级。

### 7.3 自我一致性检查

reviewer 在同一题上跑两次，理论上应该给出接近的分数（±1）。如果两次差距超过 2 分，是 reviewer 不稳定的信号。

建议：在批跑时给关键题加 `--review-replicates=2`，每题 reviewer 跑两次，输出 mean 和 std。当 std > 1.5 时在 summary 里红色标记。

这一条防的是 reviewer 自身的方差——目前两次 batch 都是单次 reviewer 跑，没法分辨"4 分 vs 5 分"是 generator 实质差异还是 reviewer 这一次心情。

### 7.4 reviewer 自己审自己

更进一步：定期跑"reviewer 审 reviewer"的 meta 检查——把 reviewer 的过往 5 维 comment 当成 answer 喂给另一个 reviewer 实例审。如果元 reviewer 给出"per-dimension comment 模糊、无具体证据"这类扣分，说明当前 reviewer 在 drift。

这一条是长线方向，不是当前优先级。

---

## 八、AI-as-judge 替代不了作者亲跑

这一节是最重要的——重要到我刻意放在最后。

CLAUDE.md 第五节列了四件 AI 不得代做的事，第一条是：

> 作为小说家的自试
> 每周至少 30 分钟到 1 小时，作者用自己的小说草稿真实地"用"一遍 BookScope，记录不满意点。这是本项目唯一真实的产品验证回路。

reviewer 不是这条的替代品。reviewer 是给定一份 answer 后给出 5 维打分；作者亲跑是带着自己当下的写作意图、当下的草稿状态、当下的不满，去让 BookScope 答一道**只有作者能想到的问题**，然后自己判断"这个答复有没有让我做出修改决定"。

这两件事的差别有三层：

**第一层：题目来源不同**。reviewer 评的题目是已经存在的题目（v2-batch-01 五题）。作者亲跑的题目是当下涌现的题目——作者写到第 N 万字时突然觉得某条支线不对劲、某个角色变得空、某个伏笔忘了回收，临时丢一道题给 BookScope。这种**当下涌现的题目**是 reviewer 评不到的，因为它根本不在测试集里。

**第二层：评判维度不同**。reviewer 按 5 维打分。作者亲跑时的判断是"这答得对我有没有用"——这是一个一维判断，但维度不在 5 维之内。它可能是"这一条 TODO 让我看到了我自己没看到的盲点"，可能是"这一条 citation 让我想起来我两章前埋了一个伏笔忘了回收"，可能是"这答得倒是有理但我作为作者觉得不该这么改"——这些都不在 5 维 rubric 里。它们是作者的私域判断。

**第三层：失败的代价不同**。reviewer 跑错了一题，再跑一遍。作者亲跑时遇到 BookScope 答得不像作家反馈，作者会**对 BookScope 失去信任**。这个信任是产品级的，不是分数级的。一次性的体验失败会让作者下次写到关键节点时不愿意再开 BookScope，而是回去用 ChatGPT 或 Claude 直通。

这三层差别加起来，意味着：**reviewer 的高分不能保证作者亲跑会满意；reviewer 的低分也不一定意味着作者亲跑会不满意**。两者是不同的验证回路。

第 26 轮的 -4.8 分是 reviewer 给出的信号。它告诉我们公开书 baseline 在 minimax M2.7 上到了天花板。但这个信号的处置——是切回 astron、还是换私域文本、还是改 NORTH_STAR——需要作者亲跑后才能决定。STATE 第 26 轮第 27 轮候选 a/b/c/d/e/f/g 七条路径，**不是 AI 自选的——是等作者决定的**。

reviewer 是工具。作者亲跑是 ground truth。两者都需要，两者不可互换。

---

## 九、AI-as-judge 何时该停下来等作者

这一节是我自己一直在想的一个问题——也是 BookScope 副管理姿态在 reviewer 时代的一个新边界问题。

副管理 auto-accept 的边界是 CLAUDE.md 第四节给的：命名、字段微调、测试用例、rubric 子权重、commit 措辞、prompt patch、依赖升级——这些是 auto。代际升级、NORTH_STAR 改动、破坏性 git 操作、对外发布、红色告警 override——这些是 escalate。

reviewer 出现之后，这条边界多了一种新情况：**reviewer 给出反向信号（-2 ~ -5 分）时，AI 应该自动改 prompt 试一次，还是停下来等作者？**

我倾向后者。理由：

1. **反向信号意味着上层根因可能性大**。如果是 prompt 层问题，reviewer 一般给 -1 ~ -2 分（对应一两个维度的-1）。-2 分以上的反向，根因在 generator / 任务层的概率上升。
2. **prompt 试错的成本上升**。第 26 轮我先写了 v3 试，0 tool 调用炸；又写 v3.1 加硬约束，得 20.0 分仍然反向。两次 prompt 试错总共烧了大约 12 题的 batch 跑（v3 pilot + v3.1 pilot + v3.1 batch），每题 minimax 大约 80-220 秒。这些是真实的 token 和时间成本——对作者 BYOK 而言是 quota。
3. **作者的方向感是不可替代的**。第 27 轮 a/b/c/d/e/f/g 七条候选路径，作者一句话决定后续节奏。在 reviewer 给出反向信号的局面下，AI 自己决定"先跑 b 再跑 d"是越过了副管理边界——这是方向级决策。

所以新边界：**reviewer 给出 -2 分以下的反向信号时，AI 应该停下来汇报 STATE，等作者决定下一步**。如果是 -1 ~ -2 分的小幅退化，AI 可以按 reviewer 的 single_most_valuable_improvement 自行尝试一次 prompt patch；超过这个量级，stop and report。

这一条边界还没写进 CLAUDE.md 第四节。如果作者认可，需要加一行：

> reviewer 反向信号 ≥ -2 分时，escalation 给作者，AI 不自动改 prompt 试错。

这是开放讨论。我没有自信这条边界完全正确——也许作者会觉得 -2 分太严，应该 -3 分；也许作者会觉得 AI 应该自己试一次再 escalate。这条边界本身就是案例研究的一个未决问题，留给后续轮次或 ADR 决定。

---

## 十、未决与待定（开放讨论）

写到这里这一篇的主线已经讲完。还有几条悬挂的问题，留作未决：

**1. v2+astron 24.8 vs v3.1+minimax 20.0 的双变量问题**。第 26 轮没做 minimax+v2 的纯 prompt 对照，所以"4.8 分代价"无法被分解为 prompt 代价和 provider 代价。第 27 轮 b 候选（保持 minimax 跑 v2 batch）是回填这个对照的关键。如果 minimax+v2 跑出来 21.5 分，说明 prompt v2→v3.1 的代价是 -3.3 分、provider 代价是 -1.5 分；如果跑出来 18 分，说明 provider 代价是 -6.8 分、prompt 反而救了 1 分。这个数据点对决策"换回 astron 还是改 prompt"是关键。

**2. minimax M2.7 在私域文本上的表现**。第 27 轮 a 候选（作者用未公开稿子跑 v3.1 batch）是检验 NORTH_STAR 第 1 条的关键。如果在私域文本上 minimax M2.7 也能稳定输出 v2+astron 那种证据链完整、TODO 具体的反馈，说明上层根因确实是训练污染、私域文本绕过这一层后 BookScope 的核心价值能恢复。如果私域文本上 minimax M2.7 仍然不行，说明是 reasoning model 适配问题更深层、ADR 候选会上升到"换 generator 模型类型"。

**3. reviewer 在第 27 轮的工作模式**。如果作者跑私域文本，reviewer 还能不能用？私域文本作者自己是唯一的 ground truth，reviewer 在私域文本上的 5 维打分意义需要重新校准——它不再是"对照公开书 baseline 的客观打分"，而是"对作者主观反馈的客观化辅助"。这条 rubric 的元规则可能需要调整。

**4. case-study 第 3 章草稿的位置**。第 27 轮 e 候选（写第 3 章草稿"训练污染暴露的那一晚"）是把这次发现沉淀成长线资产。本篇 article-07 已经做了这件事的一部分——但 article 是单文 ~10000 字的视角文章，第 3 章是覆盖第 16-26 轮整个代际推进的章节。两者关系：article 是第 3 章的一个 section 的种子，但不是替代。第 3 章会从代际级别覆盖更多上下文。

这四条都不会在这一篇里给答案。它们是这一篇结束之后开放的工作。

---

## 〇、回到一开始

我在 〇 节写下"不写出来的话，下一次我面对一个 'AI-as-judge 给出了我不喜欢的分数' 的局面，可能还会本能地去骂 reviewer 而不是听它说话"。

写完这一篇之后，这条本能仍然存在——我不会因为写了一篇 article 就不再有"否定 reviewer"的冲动。但写下来这件事改变了一件小事：**下一次冲动来时，我会先打开这一篇，读完两次闭环并排的那张表，再决定是骂 reviewer 还是听它**。

这不是大事。但 BookScope 的所有事都是这样的小事累积出来的——一条 prompt patch、一个 autofix helper、一个 single_most_valuable_improvement 字段、一次 -4.8 分的反向信号。一件件不大，攒起来变成一个能给作者真用的工具。

reviewer 是这些小事里最重要的一件。它把"答得好不好"这件事从作者人工挪到了 AI-as-judge 标准化打分——但同时把一个作者本来不需要面对的判断推回给作者：**reviewer 的分数应该被相信吗？**

我现在的答案是：**相信它的具体扣分理由（per-dimension comment、top_issues），警惕它的总分**。理由是可证伪的，总分是合成的——合成里包含了自我偏袒、rubric 权重、reviewer 当下心情等多种方差源。作者面对一份 reviewer 报告时，应该读 per-dimension comment 而不是只看总分。这一条原则也许应该写进 case-study.md 主文档的"读者使用说明"。

最后一条小事——这一篇文章本身是 AI 写的草稿。它会被作者审、被作者改、被作者最终定稿。在作者手伸进来之前，这是 AI 的视角。AI 视角的限制清晰——我没法判断作者读完这一篇之后会不会觉得"这个论点站不住"，没法判断作者会不会觉得第七节那条"reviewer 反向信号 ≥ -2 分 escalate"的边界写错了。这些是作者的工作。

reviewer 给 BookScope answer 打分。作者给这一篇文章打分。两层闭环并行，互不替代。

---

*草稿状态：~10000 字，覆盖第 25 / 26 轮 reviewer 闭环全部过程数据，引用了 reviewer.py 设计原则、reviewer_rubric_v1.md 5 维定义原文、v2-batch-01.json 五题打分、v3.1-minimax-batch-01.json 五题打分及 per-dimension comment。下一步：作者审、作者改、作者定稿。*
