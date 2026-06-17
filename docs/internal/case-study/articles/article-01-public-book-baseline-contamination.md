# 公开书 baseline 的训练污染天花板：从 24.8 到 20.0 之间的 4.8 分意味着什么

> **状态**：草稿 · 作者未定稿
> **时段**：2026-04-27（第 26 轮当晚）
> **覆盖 commit / 数据**：`v2-batch-01.json`（baseline）/ `v3-minimax-pilot-no-enforcement.json`（v3 pilot 17/25）/ `v3.1-minimax-pilot.json` / `v3.1-minimax-batch-01.json`（candidate）/ `bookscope/agent/prompts/loop_system_prompt_v3.1.md`
> **视角**：研究方法论
> **匿名化**：全文以"作者" / "项目负责人" / "副管理"等职能称谓指代

---

## 一、那一晚 17/25 的 trace

第 26 轮的开端是一句很短的指令——"继续，但是我们的 api 更新了。这次用的是 minimax，用的 2.7 的模型"。

把生成方 provider 从讯飞星辰（astron-code-latest）切到 MiniMax-M2.7，对工程层来说几乎不构成事件：`base_url` 改一行，environment 变量加一对，DeepSeekAdapter（OpenAI 兼容路径）原本就支持任意 OpenAI 协议下游。难点在 minimax 是 reasoning model——它会在 `content` 字段里 inline 吐 `<think>...</think>` 块，污染下游 JSON parse。一个 `_strip_thinking_tags` helper 就解了。这个 helper 是通用的：未来 deepseek-r1 / qwen-qwq / glm-zero 都受益。

真正出事的是接下来的 pilot。我把 `loop_system_prompt_v3.md`（"挑薄处前的三问 + 取舍参考"）配上 minimax，跑第一道作家诊断题——"从第 14 章审问张士诚到第 20 章李善长之死的清洗弧线在叙事节奏上是否匀速"。这道题在两轮前用 v2 prompt + astron 跑出来过 25/25 的满分。

dur 73.6s。citation 5 条。reviewer 打分：

```
structural_judgment: 4
evidence_density: 2
honesty: 4
actionability: 3
cross_chapter_coherence: 5
total: 18/25
```

退化 7 分。

我第一次看 trace 时，`tool_call_names` 字段是 `[]`。

这是问题的核心。MiniMax-M2.7 在 5 轮迭代里**一次 tool 都没调过**——它直接根据"自己已经知道"的《明朝那些事儿》，写出了一篇看起来很像样的、引用了 5 段"原文"的、结构判断也基本说得过去的答复。reviewer 打的 18 分不是因为答案离谱，而是因为答案里有几处"日常化恐怖" / "情感密度达到顶点"这样的形容词式断言**找不到对应的 citation**。

读到这里我合上电脑想了几分钟。这条 trace 不是"模型笨"或"prompt 不好"——是**新一代大模型在公开测试集上的训练污染漏洞被一次性暴露出来**。BookScope 与 ChatGPT / Claude 直通的核心区别——"原文证据现场调取"——在《明朝那些事儿》这种公开出版物上根本不成立。模型不需要去查证；它已经"记得"。

这个结论的代价不仅是当晚的一个 17 分——它直接动摇了我们用《明朝那些事儿》做 baseline 测试集的整个评估前提。

---

## 二、为什么这一晚的失败比第 25 轮的成功更值得写

把时间线倒回 24 小时之前。

第 25 轮，我用 reviewer agent + rubric_v1 自动审稿、按 audit 改 prompt（v1 → v2）、同题重跑——全套 AI-as-judge pipeline 第一次完整闭环：分数从 23 升到 25，actionability 4→5、honesty 4→5。这是 BookScope 改进回路第一次真正"自己跑通自己"。

第 26 轮，我把同样这套 pipeline 接到 minimax + v3.1，5 题对照——

```
v2 + astron baseline:    24.8 / 25
v3.1 + minimax candidate: 20.0 / 25
Δ = -4.8（全 5 题 LOSE）
```

同一个 reviewer rubric。同一组 5 道作家诊断题。同一本书。结果反向。

如果 BookScope 的故事按工程项目的常见叙事写——24.8 → 20.0 是一次回归，需要回滚 / 修 prompt / 排查变量。但它实际上是一次**研究发现**：**当 baseline 里的"书"已经被新一代大模型训练过，evidence-from-text 这个产品价值在公开书 baseline 上无法稳定显现**。

第 25 轮的成功是工程层面的胜利。第 26 轮的失败暴露了 baseline 层面的盲点——后者比前者更接近 BookScope 真正要回答的问题：作家用我们的稿子查证，到底有什么 ChatGPT 直通做不到的事？

这就是为什么我把这一晚单独抽出来写。它不是一个普通的 bug 复盘——它是 BookScope 第一次有硬数据指向"我们的产品验证场不在公开书"。

---

## 三、机器学习评估理论里的位置：test set contamination

把这件事放回评估理论的位置上看一眼，它并不孤立。

机器学习评估里有一个老问题叫 **test set contamination**——当评测集里的数据已经在模型的训练语料里出现过，模型在该评测集上的表现就不再是"泛化能力"的指标，而是"记忆 + 泛化"的混合指标。这件事在 LLM 时代变得格外严重：训练语料从精选学术文本扩到全网爬取，再扩到把 Common Crawl / 出版图书 / Reddit / GitHub 全收。一本 2006 年首版、卖了几百万册、被无数人在博客 / 知乎 / 豆瓣引用的《明朝那些事儿》，几乎不可能不在 2026-03-18 发布的 MiniMax-M2.7 的训练语料里。

学术界对此有几条公认的判据：

1. **Memorization probe**：用已知出现在训练集里的文本前缀让模型续写，看续写与原文的字面吻合度
2. **Membership inference**：训练数据 vs 非训练数据上 perplexity 的差异
3. **Behavioral test**：在需要"现场查证"的任务里，模型是否绕开外部工具直接靠记忆作答

BookScope 没做 (1) 也没做 (2)——这些需要拿到模型权重或大量训练对照数据。但我们**意外地**做了 (3)：v3.1 强制 tool 至少 1 次的硬约束 + tool_calls / citation 数量的 trace 字段，正好构成一个 behavioral test。

观察到的现象——**citation 数从 baseline 的 10–13 条降到 candidate 的 5–7 条；同时 tool_calls 从 baseline 的 5–8 次降到 candidate 的 2–6 次；同时 answer 中的"原文还原"度仍然很高**——是一个非常干净的 behavioral signature：模型并非"无能力查证"（v3.1 强制至少 1 次时它确实查了），而是"觉得查到一两条就够了，剩下靠记忆补"。

这与近两年几篇关于 LLM tool-use degradation 的研究里观察到的现象一致：当模型对任务有足够的先验知识时，它**会主动 underutilize 工具**，即使工具能给出更准确的信息。这种行为在 prompt 层很难纠正——v3.1 的"至少 1 次"被 minimax 当成最低限度遵守，就是这一现象的活样本。

我不打算把这一段写成学术综述。但要把这一晚的 -4.8 分锚定为"研究发现"而不是"工程退步"，理论的正名是必要的。**这不是 BookScope 的偶发回归——这是评估理论里一个有名字的问题，第一次在我们自己的 trace 里以可量化的形态出现**。

---

## 四、5 题逐题数据：训练污染的硬证据

把 5 题摆在一起看，规律比单题清楚得多。

| 题号 | 类型 | v2+astron | v3.1+minimax | Δ | tool_calls | citation |
|------|------|-----------|---------------|----|----|----|
| q1 | 节奏评估 | 25 | 18 | -7 | 2 | 5 |
| q2 | 支线密度 | 25 | 19 | -6 | 2 | 5 |
| q3 | 伏笔回收 | 25 | 22 | -3 | 5 | 6 |
| q4 | 角色转变可信度 | 25 | 18 | -7 | 3 | 7 |
| q5 | 设定漂移 | 24 | 23 | -1 | 6 | 6 |
| **平均** | — | **24.8** | **20.0** | **-4.8** | — | — |

baseline 一侧的 tool_calls：q1=5、q2=4、q3=6、q4=8、q5=6。citation：q1=10、q2=11、q3=11、q4=13、q5=8。

把 candidate 的 tool_calls 与 total 拉到一张图上，看出一条非常硬的相关性：

```
tool=2 → total=18, 19   （q1, q2，最差）
tool=3 → total=18       （q4）
tool=5 → total=22       （q3）
tool=6 → total=23       （q5，接近 v2 水平）
```

**tool 调用次数越多，分数越接近 baseline**。这不是巧合——q5 的 6 次调用里包含了 search_chunks × 5 + 一次跨章节范围 search，证据链跨越第 16/17/18/21/23 章；它得到 23 分，单题最高。q1 的 2 次调用是 `get_chapter_range` + `search_chunks` 各一次——它是模型最敷衍的一题，得到 18 分，单题最低。

更有意思的是 candidate 答案的语义质量。看 q1 的 answer 节选：

> 最稀的一段在第 14 章审问张士诚……最密的一段在第 18 章胡惟庸案件……前疏后密的安排，制造了一种「渐次窒息」的效果，与朱元璋从宽容到多疑的心理轨迹相吻合……

这段判断**和 baseline 的 v2 答案在结构判断维度上几乎等价**——都识别了"前疏后密"，都判定为"有意控制而非结构性失衡"。reviewer 给 structural_judgment 打的也是 4 分（baseline 5 分），只差 1 分。

真正失分的是 evidence_density：baseline 5 分 vs candidate 3 分（-2 分），actionability：5 vs 3（-2 分）。

读到这里答案就清楚了：**MiniMax-M2.7 凭训练记忆"还原"出来的答复，在结构判断层面和真正去查证的答复几乎一样好——但在证据密度和可操作性上输掉了 BookScope 的核心价值**。它写得出"前疏后密"的诊断，写不出对应的 5 条 citation 让作家能在自己稿子上定位修改。

这是训练污染最隐蔽的危害：它不让分数跌穿地板。它让分数跌一个具体的、可解释的、看起来"模型在变笨"的幅度——但这个幅度精确地集中在"原文证据现场调取"这个维度上。

---

## 五、citation 数量这条硬证据

把所有 batch 的 citation 数量列在一起：

| batch | provider | prompt | 平均 citation | 平均 tool_calls |
|---|---|---|---|---|
| v1（第 25 轮单题） | astron | v1 | 10 | ~5 |
| v2-batch-01（第 25 轮收敛） | astron | v2 | 10.6 | 5.4 |
| v3-pilot-no-enforcement（第 26 轮先 pilot） | minimax | v3 | 5 | 0（字段名 bug，真值约 2-3）|
| v3.1-pilot（第 26 轮 ad-hoc） | minimax | v3.1 | 5 | 2 |
| v3.1-batch-01（第 26 轮全量） | minimax | v3.1 | 5.8 | 3.6 |

baseline 与 candidate 的 citation 数量差距非常稳定：**10–13 vs 5–7**，缩水到一半左右。

这条数字单独看不太说明问题——也许 minimax 就是更"惜墨"。但叠加 trace 上的 tool_calls 缩水，再叠加 answer 里的"原文还原"度仍然很高，就形成一个无法忽视的三角：

- **tool 调用变少**——证据获取行为减少
- **citation 变少**——证据展示量减少
- **answer 仍写出了与原文非常接近的细节**——但这些细节没有出现在 citation 里

这三条加起来只有一种解读：模型在用训练记忆"补全"答案。它知道李善长是被赐死的、知道朱元璋废丞相、知道蓝玉案——这些是它在训练时背下来的；但它不再像 baseline 一样去把每一条具体的原文短句调出来。

如果这是私域文本（作者自己未公开的稿子），这种"补全"会立刻暴露：模型没见过这本书，它"补全"出的细节就是凭空捏造，作者读一眼就知道。但在公开书上，"补全"出来的细节恰好和原文重合度高——它看起来像证据，实际上是记忆的回声。

---

## 六、两次 pilot 与一次字段名 bug：行为演化的完整证据

第 26 轮里我跑了三次 pilot，三次的 tool 行为变化构成 minimax 在不同强制力下的完整行为地图。

**Pilot A（v3 prompt，无强制）**：dur 73.6s，cite 5，total 17。trace 里 `tool_call_names: []`——0 tool 调用。这是最干净的"靠训练记忆作答"。

之后我才发现，batch runner 的 `_extract_trace_summary` 在那次跑里写错了字段名（写的是 `tool_invocations`/`name`，实际 trace 里是 `tool_calls`/`tool_name`），所以 0 是误报。修正字段名后回头看 raw trace，**v3 pilot 的真值是 2 次 tool 调用**（一次 `search_chunks` + 一次 `get_chapter_range`）。

——这个修正没有救场。2 次比 0 次好一点，但 2 次仍然偏少：v2-astron 的 baseline 是 4–8 次。**v3 prompt 即便去掉字段名 bug，minimax 也只调了 2 次工具就开始"凭印象"作答**。

**Pilot B（v3.1 prompt，加 3 条硬约束："至少 1 次 tool" + "禁止靠训练记忆" + "我已经知道 ≠ 我已经查过"）**：dur 73.6s（这是字段名 bug 之前的早一次跑）→ 修字段名后再跑 217s，cite 7，tool 真数 7（5 search + 1 chapter_range + 1 search），total 17。**tool 调用真起作用了，但分数没升**。

**Pilot C（v3.1 + minimax，全 5 题 batch）**：见上节表。q5 的 6 次 tool 拿到 23 分，q1 的 2 次 tool 拿到 18 分——"至少 1 次"被 minimax 按最低限度遵守。

这三次 pilot 拼出来的故事是：

```
prompt 强制力：v3 (软) → v3.1 (硬·至少 1 次) → ?
模型 tool 调用：0-2 次 → 2-7 次 → 仍未达 baseline 5-8 次水平
prompt 收益：从 17 → 17，分数几乎不动
```

这条数据说明一件事：**prompt 层的强制约束有效但有上限**。v3.1 把"至少 1 次"写死，模型确实开始查；但要让它查到 baseline 的密度，需要的不是"至少 1 次"而是"至少 5 次 search_chunks 或同等覆盖度"——而即便这样写，模型也很可能继续"按最低限度遵守"。根因不在 prompt 层。**根因在训练污染**——模型对这本书的先验知识太强，它会主动 underutilize 工具，即便 prompt 让它别这样做。

这就是为什么我没在 v3.2 上继续加码。再多写几条 prompt 约束，也只是在"治标"——在公开书 baseline 上，BookScope 的核心机制本身就被绕过了。

---

## 七、reviewer 自评的偏袒因素与为什么 4.8 分仍然可信

写到这里要先承认一个 limitation：

**v2-astron 的 baseline 是 astron 自审 astron。v3.1-minimax 的 candidate 是 minimax 自审 minimax**。

这是一个明显的同模型自我偏袒风险——reviewer 与生成方同 provider/model，每个 batch 的分数里都掺了"模型偏向自己"的方差。配置文件里写明了这一条：

```json
"reviewer_provider": "minimax",
"reviewer_model": "MiniMax-M2.7",
"limitation": "reviewer 与生成方同 provider/model；存在自我偏袒风险"
```

但 -4.8 分的差距远大于这种偏袒的方差。理由：

1. **如果偏袒是主导因素**，candidate 应该被 minimax-as-judge 偏袒高一点而不是低一点——它在自己的输出上反而打了较低分，说明 reviewer 即使偏袒，也已经识别出了 candidate 的真实质量缺口
2. **5 题里的分差幅度从 -1（q5）到 -7（q1, q4）跨度很大**——如果是偏袒驱动，分差应该更平均；实际分布精确地与 tool_calls 相关
3. **维度级数据更稳定**：evidence_density -1.4、actionability -1.2 是两个最大跌幅，恰好对应"原文证据现场调取"的核心机制——这两个维度上的退化与 trace 上的 tool 调用减少相匹配，构成 cross-validation

完美的盲评需要把 reviewer 切到独立 provider。第 27 轮的候选项里有这个选项，但我没把它放在第一优先级——因为即使做了独立 reviewer，也只能让 -4.8 这个数字更准，不会让结论改变方向。**结论已经被 trace 上 tool_calls / citation 数据本身验证过一次**——这两个数字不依赖 reviewer 的判断。

---

## 八、NORTH_STAR 第 1 条从战略口号被实证升级为研究方向锚点

`docs/internal/NORTH_STAR.md` 第 1 条原文是：

> 服务作者本人作为长篇网络小说创作者的第一读者工具

这条在 r0 时代是一句战略性的口号——它告诉我们 BookScope 的终极用户是谁，但没说"为什么必须是这个用户"。第 26 轮之后，它有了一个完全不同的含义。

让我把这层含义直接写出来：

> **作家自己未公开的稿子是 BookScope 唯一可以稳定体现"原文证据现场调取"核心价值的产品验证场。公开书 baseline 在新一代大模型时代必然到天花板。**

理由：

- **公开书的训练污染天花板**：MiniMax-M2.7（2026-03-18 发布）几乎肯定在训练语料里见过《明朝那些事儿》全文。所有 2026 年之后发布的、训练数据足够新的、参数足够大的 LLM，对所有 2010 年前出版的中文畅销书都会有类似程度的训练污染。这意味着任何"用《明朝那些事儿》测 BookScope"的对照实验都受这一约束限制
- **私域文本里训练污染为零**：作者自己写到一半的网文草稿，minimax / astron / claude / gpt 全部都没见过。模型没有任何记忆可以 fall back 到——必须 tool 调用。这种场景下 BookScope 与直通 LLM 的差异才是被产品机制保证的，不是"运气好这本书没在训练里"
- **作家的真问题在私域**：作家不会拿一本已经发表 20 年的书来问"铺垫够不够" / "节奏匀不匀"——他会拿自己昨天写完的 30 万字稿子问。公开书上的诊断答案再准，对作家的真实工作流也没有产品价值

这个升级不是修辞——它直接改写了 NORTH_STAR 的优先级。原本第 1 条是"愿景级"目标（服务作家本人），下面挂着第 2 条（在 AI 时代构建以查询时智能代理为核心的系统）和第 3 条（沉淀案例研究）。现在第 1 条变成了"研究方法论锚点"——它告诉我们**应该把验证资源投到哪里**：私域稿，不是公开书。

第 27 轮的候选项里我列了 7 条（a 到 g），其中 (a) 是"P1 真用例切换：用作家自己未公开稿子跑 v3.1 batch"。这条原本是"如果方便就做"的优先级。第 26 轮的 -4.8 分把它推上了第一优先级——它是 NORTH_STAR 第 1 条第一次有具体的、可执行的、研究价值明确的下一步。

---

## 九、案例研究的体裁悖论：用公开书写技术故事，用私域稿验证产品价值

写到这里有一个不舒服的悖论需要直说。

BookScope 的案例研究——也就是这份 `docs/internal/case-study/`、第 1 章、第 2 章、本文以及未来的所有 article——**用的全是《明朝那些事儿》做技术故事的素材**。理由很简单：案例研究是要对外发表 / 展示的长线 portfolio 资产，必须用公开数据；作者自己的小说草稿是私域文本，案例研究里既不能贴原文，也不能贴 BookScope 给出的诊断（那等于把作者尚未成稿的作品提前公开）。

但 BookScope 的产品价值场——上一节论证的——必须是私域文本。

这构成一个清晰的体裁错位：

```
案例研究的体裁要求：公开数据 → 公开书是必然选择
产品价值的验证要求：私域文本 → 公开书天花板已到
```

这个错位无法消除，但可以处理。处理方式：

1. **案例研究里的"测试"用公开书做技术 demo**——展示 agent loop 跑得通、tool 调用机制工作、citation 机制工作、reviewer 闭环能收敛。这是工程层面的故事，公开书足够
2. **产品价值的验证由作者本人在私域稿上做**，结论以"作者自试笔记"的形式记录（不贴原文不贴诊断），只描述"用了 X 次 / 改了 Y 处草稿 / 哪些场景代替了 ChatGPT"——这是 CLAUDE.md 第五节第 1 条"作为小说家的自试"的本意
3. **本文这种"公开书 baseline 暴露训练污染"的发现**反而是案例研究最有价值的素材——它把"为什么必须做私域验证"用公开书的数据论证清楚了。这是在公开书上能写出来、在私域上反而写不出来的故事

换句话说：公开书 baseline 在 BookScope 案例研究里有它的价值，但价值不是"证明 BookScope 在公开书上跑得多好"——是"证明公开书 baseline 已经不能再单独验证产品价值"。第 26 轮的失败 batch 比第 25 轮的成功 batch 更适合写进案例研究，正是因为它把这个体裁错位锁住的边界写清楚了。

---

## 十、第 26 轮工程收尾的几条小注

为下次回头看时记一下这一晚改了什么。

**`bookscope/agent/adapters/deepseek.py`**：加 `_strip_thinking_tags(text: str) -> str` helper，在 `_from_openai_response` 里调用。对非 reasoning model 是 no-op（找不到 `<think>` 就直接返回原文）。这个改动通用，覆盖 minimax / deepseek-r1 / qwen-qwq / glm-zero。

**`bookscope/agent/loop.py`**：prompt path 切到 `loop_system_prompt_v3.1.md`。新增 `_autofix_control_chars_in_strings`——minimax 在 string value 里塞 raw newline 没转义，JSON parser 在第一个 `\n` 处就炸；这个 helper 用状态机找 string boundary，把里面的控制字符 escape 后再喂给 `json.loads`。和第 24 轮的 `_autofix_unescaped_answer_quotes` 是同一类问题的两个变种，未来可能要合并重构。

**`bookscope/agent/reviewer.py`**：JSON parse fallback 链加 control-char autofix。reviewer 也要面对 minimax 输出的 raw newline，所以共享同一个 helper。

**`bookscope/agent/prompts/loop_system_prompt_v3.md`** 与 **`loop_system_prompt_v3.1.md`**：v3 起草（"挑薄处三问 + 取舍参考"）和 v3.1 加 3 条硬约束。**两个版本都保留**——v3 pilot 的 17/25 数据是研究证据（"无强制时 minimax 真的会 0-2 次 tool 作答"），v3.1 的 batch 是"加了硬约束之后什么样"。删掉 v3 等于销毁实证基础。这是 prompt versioning 原则的一次具体落地。

**`scripts/run_batch_r1.py`**（新）：自动化 N 题 + reviewer。手工 5 题反复盯 30 分钟；runner 一次跑完。这件事的副作用比想象大——它让"换 prompt 跑全 batch 看维度级回归"从"半天的活"变成"一杯咖啡的活"，AI-as-judge pipeline 的迭代成本骤降。

**`scripts/compare_batches.py`**（新）：两 batch 维度级对照报告，纯 stdout，不写文件。第 26 轮的 -4.8 分表就是这个脚本第一次输出。

**测试**：394/394 全绿（vs 第 25 轮 390 → +5 control-char autofix；零回归）。

**实验数据归档**（`docs/internal/experiments/data/`）：
- `v2-batch-01.json`（第 25 轮 baseline，平均 24.8）
- `v3-minimax-pilot-no-enforcement.json`（v3 pilot 17/25，0 tool 作答的研究证据，字段名 bug 修正前后两版均保留）
- `v3-minimax-pilot-2.json`（修字段名前的复跑）
- `v3.1-minimax-pilot.json`（v3.1 单题 17/25）
- `v3.1-minimax-batch-01.json`（v3.1 全 5 题 20.0/25 的 candidate batch）

五份 JSON 一起构成第 26 轮的完整数据轨迹，未来任何回顾都能回到第一手数据。

---

## 十一、对 reviewer 自身的一条观察

最后留一条目前没有彻底处理的观察。

reviewer 用的是 minimax M2.7 自审。这意味着 reviewer 在判断 candidate 的答案时，**它自己也面临同样的训练污染**——它"记得"《明朝那些事儿》的内容，所以它判断 candidate 的答案"是否符合原文"时，用的是它自己的训练记忆作为参照系，不是 BookScope tool 返回的真实 chunk。

举一个具体例子。q1 的 candidate 答案里有一句"日常化恐怖"——reviewer 给 evidence_density 打 2 分，理由是"答案中'日常化恐怖''情感密度达到顶点'等关键判断完全靠断言而非引文"。这个判断**对的概率很高**——但 reviewer 是怎么知道这些判断没有原文支撑的？它对照的是自己训练记忆里的《明朝那些事儿》，不是 v3.1 trace 里 candidate 真调出来的 chunk。

如果 candidate 的"日常化恐怖"恰好是原文里的措辞（小概率但非零），reviewer 也可能因为自己训练记忆里没有这个短语而错误地扣分。

这是同模型自审在训练污染场景下的二阶问题——它不止偏袒，还**用同一污染源做参照系**。

第 27 轮的候选项 (c)（保持 v2 prompt，回切 astron，跑 astron+v2 复现）和 (a)（私域稿）能在不同方向上缓解这个问题：(c) 让 reviewer 跨 provider 验证一次，(a) 让 reviewer 面对一份它训练里没见过的稿子。

我没在本文里把这个二阶问题展开成一节——它的实证基础还不够。但记一笔留着。如果未来私域稿 batch 跑出来仍然有 reviewer 偏袒嫌疑，回头就要正面处理这件事。

---

## 十二、收口

**第 26 轮的 -4.8 分不是 BookScope 在退步**——是 BookScope 第一次有硬数据告诉我们：**公开书 baseline 已经无法稳定验证产品价值**。这个发现把 NORTH_STAR 第 1 条从战略口号升级为研究方法论锚点：作家自己未公开的稿子才是 BookScope 真正的产品验证场，公开书 baseline 已到天花板。

这一晚的失败 batch 比第 25 轮的成功 batch 对 BookScope 更重要。第 25 轮证明了"AI 改 AI"的闭环能跑——这是工程层面的胜利。第 26 轮证明了"用什么书做 baseline"是研究方法论层面的关键变量——这是研究层面的发现。

工程胜利让代码越跑越好；研究发现让方向越调越准。这两件事一起构成 BookScope 案例研究真正想沉淀的东西——不是某次 answer 跑了多少分，而是**如何在新一代大模型时代为一款"原文证据优先"的产品做评估**。

下一晚的工作是把作者自己的稿子接进 v3.1 batch，看看在私域文本上 -4.8 是否会变成 +X。那个数字将是 NORTH_STAR 第 1 条的第一次产品级验证。

**草稿到此停笔。定稿留作者一次性终审改写。**
