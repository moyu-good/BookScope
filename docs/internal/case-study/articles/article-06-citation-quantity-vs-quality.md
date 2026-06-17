# Citation 数量 vs 质量：5 条 vs 13 条之间的真证据密度博弈

> **状态**：草稿 · 作者未定稿
>
> slug：article-06-citation-quantity-vs-quality
> 视角：评估系统设计
> 所属系列：BookScope 案例研究 · r1 代际
> 关联轮次：第 26 轮（provider 切 MiniMax-M2.7 + v3.1 prompt + 5 题 batch）

---

## 一、引子：一条本以为已经收敛的硬约束

我在 BookScope 第 11 轮把"每条结论必须有 citation 支撑"写进 system prompt 的时候，是把它当一条**已经解决**的问题来处理的。

逻辑很朴素：作家在自己稿子上要的不是"AI 觉得"，是"原文怎么写的"；那就让 LLM 每输出一段判断，都顺手挂一条 chapter + snippet。citation 字段是 schema 里的硬约束，缺字段直接 LLMFormatError，连 retry 一次的机会都给。我在第 24 轮的作家场景验证里跑了第一道真题——李善长铺垫连贯性——拿到 11 条 citation，每条都是关键节点的原文，章节号从 ch 14 到 ch 21 横跨七章，第一次让我感到"这套机制真的在工作"。

第 25 轮的 reviewer 闭环更让我安心。我配了一位 5 维 rubric 的 AI 审稿人，专门设了一个**evidence_density** 维度——评 citation 是不是真的支撑 answer 主张、是不是只是装饰。v2 prompt 跑五道作家题，evidence_density 全部满 5 分。"BookScope 的核心机制——原文证据现场调取——已经稳定了"，我在第 25 轮 STATE 里写下这句话，然后切到第 26 轮的 provider 切换工作。

第 26 轮把生成 provider 从讯飞 astron 切到 MiniMax-M2.7。一行 base_url，本来是收尾的工程动作。然后 batch runner 自动跑完 5 道题、reviewer 自动审完，输出报告——

evidence_density：**5.0 → 3.6**，五维里跌幅最大的一维。

每题平均 citation 数：**10.6 → 5.8**，几乎砍半。

q1 节奏评估：baseline 10 条 citation，candidate 5 条；evidence_density 5 → 3。reviewer 在 top_issues 里直接点："第 17 章的过渡作用被明确提及（刘基与李善长党争、废相讨论），但 citations 中完全缺失第 17 章的原文，整条'外部→内部'的过渡弧线因此建立在断言而非证据之上。"

这句话扎进我心里。因为它揭示了一件我之前从没想过的事：**"每条结论有 citation"和"answer 的每个章节论点都被 citation 覆盖"——不是同一件事**。

前者是 schema 层硬约束，BookScope 一直在做。后者是论证质量层软约束，BookScope 从来没有显式衡量过。第 26 轮之前没出问题，是因为 v2+astron 的 generator 自然就给到 10-13 条；第 26 轮换了 minimax，generator 的"够用即停"阈值降下来了，覆盖率破洞瞬间暴露。

这篇文章想把这件事写清楚——为什么 citation 数量有个边际收益曲线、为什么覆盖率比"是否有 citation"更重要、为什么 BookScope 应该把 citation 覆盖率作为 reviewer 的二级评估维度独立打分。

---

## 二、5 题逐题对比：数量减半的硬数据

先把第 26 轮跑出来的对照表摆开。两个 batch 用的题是完全一致的同 5 题（节奏评估、支线密度、伏笔回收、角色转变可信度、设定漂移），都跑《明朝那些事儿》同一份 epub，KG 都是同一份手工 4 角色。变量只有两处——generator 从 astron-code-latest 换到 MiniMax-M2.7，prompt 从 v2 换到 v3.1（v3.1 比 v2 多了"至少 1 次 tool 调用"硬约束）。

| 题号 | 题型 | baseline (v2+astron) | candidate (v3.1+minimax) | citation 数差 | answer 章节集 | citation 章节集 |
|------|------|---------------------|--------------------------|----|------|------|
| q1 | 节奏评估 | **10 条** | **5 条** | -5 | {14,15,16,17,18,19,20} | baseline {14,16,17,18,19,20} / candidate {14,15,18,19,20} |
| q2 | 支线密度 | **11 条** | **5 条** | -6 | {7,8,9,10,11,12,13,14,15,23,24} | baseline {8,9,10,11,12,13,15,24} / candidate {7,8,10,11,12} |
| q3 | 伏笔回收 | **11 条** | **6 条** | -5 | {1,2,3,4,13,14,17,18,19,21,22,23} | baseline {2,3,4,13,14,17,18,19,22,24} / candidate {1,3,19,22,23} |
| q4 | 角色转变可信度 | **13 条** | **7 条** | -6 | {3,4,5,6,9,10,12,14,17,18,19,21,22,23,24} | baseline {3,4,5,10,12,13,19,22,23,24} / candidate {3,4,5,23} |
| q5 | 设定漂移 | **8 条** | **6 条** | -2 | {5,6,14,16,17,18,21,22,23,24,28} | baseline {14,17,18,22,24,28} / candidate {16,17,18,21,23} |
| **平均** | | **10.6 条** | **5.8 条** | **-4.8** | | |

三个直觉性的发现先记下：

**第一，q5 是 candidate 的最好成绩**——5 题里 q5 的差距最小（仅 -2），而 q5 也是 candidate 唯一拿 23 分的题。这不是巧合：q5 candidate 的 tool_call_count 是 6 次（5 题里最多），citation 是 6 条，跨章 5 个章节。当 minimax 真的把工具调到位、citation 给到 6 条，分数立刻接近 baseline 水平。

**第二，q1 的 citation 数砍半幅度最猛**——10 条到 5 条，evidence_density 直接从 5 砸到 3。同时 q1 的 candidate tool_call 只有 2 次（v3.1 最低限度），是 5 题里最敷衍的一题。tool 调用少、citation 少、评分低——三件事高度同步发生。

**第三，q4 是 baseline 的最高 citation 数**（13 条），候选只 7 条。q4 是"角色转变可信度"——一个**天然需要跨章对比**的题型。baseline 的 13 条横跨 10 个章节，candidate 的 7 条只锚在 4 个章节（且其中 3 章集中在前期）。这个落差最能说明问题：跨章节论证的题，citation 数量不是越多越好，而是**够不够覆盖关键章节**。

数量不是空洞数字，是**章节覆盖能力**的代理变量。少 5 条不是省了 5 条字，是少覆盖了 5 个章节的论证支撑点——只要论证横跨这些章节，就一定漏。

---

## 三、reviewer 自己的话：top_issues 把 citation 缺失点出来

我后面会讨论"reviewer 同模型自审"的偏袒风险，但先把 reviewer 在每道题的 top_issues 中点 citation 缺失的原话摘出来——这是来自 minimax 自己审 minimax 的第三方视角，自审还能挑出这么多 citation 缺口，说明缺口确实是结构性的，不是 reviewer 的偏好。

**q1 节奏评估**（candidate 18/25）：

> 第 17 章的过渡作用被明确提及（刘基与李善长党争、废相讨论），但 citations 中完全缺失第 17 章的原文，整条"外部→内部"的过渡弧线因此建立在断言而非证据之上。

这条点得最准。candidate 的 answer 在分析"前疏后密"的成因时反复用第 17 章的党争、废相讨论作为转折支点，但 citation 列表里完全没有第 17 章。论点最关键的支点章节没有原文支撑，整条因果链就只是 LLM 的"我记得书里这么写"——这恰好是训练污染的典型呈现。

**q2 支线密度**（candidate 19/25）：

> 答案中"知人善任、组织能力强、舰队威力"等主张依赖作者叙述而非 citation 支撑，evidence_density 存在明显缺口。

candidate 在描述陈友谅刻画立体度时给出了"军事才能（知人善任、组织能力强、舰队威力）也有正面描写"这条主张，但 citation 列表里没有任何一条涉及组织能力或舰队的原文——读者无法通过 citation 验证这条判断。这不是单条论点的问题，是**论点-证据脱节**的系统性表现。

**q3 伏笔回收**（candidate 22/25，candidate 5 题里最高，但 evidence_density 仍只 4）：

> 铺垫端（第 1-3 章）的 citation 太轻——仅用档案格式和结论性句子，缺乏具体苦难场景引用，无法让作家直观感受这条线索的原始强度被摊薄了多少。

candidate 给的 ch 1 citation 是"家庭出身：（至少三代）贫农。生卒：1328－1398"——一句档案。ch 3 citation 是"一个武装到心灵的战士"——一句结论。reviewer 直接指出：作家需要的是父母饿死、讨地遭拒、被迫出家这些**具体场景**的原文，让作家直观感受铺垫的原始强度。baseline 在 ch 3 给的就是"四月初六朱重八的父亲饿死，初九大哥饿死，十二日，大哥长子饿死、二十二日，母亲饿死……朱重八已经没有了父母，没有了家，他所有的只是那么一点可怜的自尊"——同一章，原文力道完全不同。

**q4 角色转变可信度**（candidate 18/25）：

> 答案正文引用的具体战例（攻克定远、四战四胜）和政治事件（废相、肃贪、杀功臣）均无对应 citation，导致核心论点与支撑材料之间出现断层，作家无法核实论据来源。

q4 是缺口最严重的一题。candidate 的 answer 大段讲"前期童年到参军""中段三年漂泊""后期开国后以废相、肃贪、杀功臣等具体政治事件驱动性格展示"——但 citation 集中在 ch 3、4、5、23 四章，**完全没有 ch 17（废相）、ch 19（肃贪）、ch 22（杀功臣）的原文**。一个论"角色转变可信度"的诊断，跳过转变发生时的所有关键章节，靠 LLM 训练记忆的总结来论证——这是训练污染最赤裸的形态。

**q5 设定漂移**（candidate 23/25）：

> 答案提到"刘基被逐步边缘化""丞相制度废除动机"等早期铺垫段落时，citations 列表中对应原文缺失，导致证据链在此处有缺口，可能影响作家对此段分析的信任度。

q5 已经是 candidate 表现最好的题，evidence_density 4 分。但 reviewer 仍能挑出 citation 缺口——"刘基被逐步边缘化"这条主张提了，原文支撑没给。这条 issue 比 q1 的更难发现，但它说明同一个问题：**只要 generator 的"够用即停"阈值低，主张比 citation 多就是必然结果**。

五道题，五条 citation 缺失类 top_issue。这不是某一题的偶发问题，是 candidate 整批的系统性弱点。

---

## 四、citation 覆盖率：一个 BookScope 一直没有显式衡量的二级指标

让我把"citation 覆盖率"这个概念明确定义出来：

> **citation 覆盖率** = answer 中提到的章节号集 ∩ citations 中的章节号集 占 answer 章节集的比例
>
> coverage_ratio = |answer_chapters ∩ citation_chapters| / |answer_chapters|

这个定义有三个隐含假设：

1. **answer 提到章节号 = 论点关联到该章节**。当 candidate 写"第 17 章党争初起，叙事开始收束"时，第 17 章就是这条论点的关联章节，理论上应该有 ch 17 的 citation 来支撑"党争初起"这一具体主张。
2. **citation 章节 ⊇ answer 章节 才算完整论证**。citation 多于 answer 提到的章节是允许的（多出的可能是支撑某条横向判断的辅证），但 citation 章节集如果是 answer 章节集的真子集，就一定有论点没被覆盖。
3. **覆盖率不评估 citation 内容质量**。这是单纯的章节级覆盖，不评估每条 citation 是不是真的命中关键句——这个需要 reviewer 的 evidence_density 维度去做。覆盖率是"必要条件"，evidence_density 是"充分条件"。

把第 26 轮 5 题的覆盖率算出来：

| 题号 | answer 章节数 | candidate citation 章节数 | 交集 | candidate coverage_ratio | baseline citation 章节数 | baseline coverage_ratio |
|------|---|----|----|---------|----|---------|
| q1 | 7 | 5 | 4 | **57%** | 6 | 86% |
| q2 | 11 | 5 | 4 | **36%** | 8 | 73% |
| q3 | 12 | 5 | 4 | **33%** | 10 | 83% |
| q4 | 15 | 4 | 4 | **27%** | 10 | 67% |
| q5 | 11 | 5 | 4 | **36%** | 6 | 55% |
| **平均** | 11.2 | 4.8 | 4.0 | **38%** | 8.0 | **73%** |

candidate 平均覆盖率 38%，baseline 73%——**几乎双倍差距**。

更刺眼的是 q4。candidate 的 answer 跨 15 个章节做诊断，citation 章节只覆盖了其中 4 章——意味着 11 个章节的论点是无原文支撑的；超过三分之二的论证是"模型自己说的"。

q3 也类似。candidate 的 answer 跨 12 章铺贫农出身到清洗功臣的伏笔回收链，citation 章节只覆盖 4 章——剩下 8 章的论证全靠 LLM 训练记忆。

这才是第 26 轮真正暴露的问题。**evidence_density 只有 -1.4 分掉幅，但 coverage_ratio 是 -35 个百分点的掉幅**——后者大得多，前者只是后者投在 reviewer rubric 上的一个不完整投影。

---

## 五、深入 q1：当"前疏后密"的支点章节没有 citation 时

把 candidate 的 q1 当案例切开看一遍。

candidate 给出的论证结构是这样的——

- 最疏：第 14 章（审问张士诚）→ citation 有
- 中段过渡：第 15 章（北伐灭元）→ citation 有
- 中段过渡：第 16 章（远征沙漠）→ **citation 无**
- 节奏开始收束：第 17 章（党争 + 废相）→ **citation 无**
- 最密前段：第 18 章（胡惟庸案）→ citation 有
- 最密：第 19 章（肃贪大案）→ citation 有
- 收束：第 20 章（李善长之死）→ citation 有

answer 跨 7 章，citation 覆盖 5 章。漏了 ch 16、ch 17。

漏 ch 16 还可以理解——ch 16 在 candidate 的 answer 里只是带过性的"远征沙漠"。但漏 ch 17 是**致命**的。

为什么致命？因为 candidate 的核心论点是"前疏后密"，而 ch 17 正是论点的转折支点：

> 第 15 至 17 章则是一段特殊的「稀」——第 15 章用大量篇幅讲述蒙古兴起、文天祥殉国、明朝建立及徐达北伐，第 16 章续写远征沙漠与傅友德七战七胜，第 17 章才回到朝廷内部的政治斗争（刘基与李善长的党争、废相制度的深层讨论）。这段插曲式的内容表面与清洗功臣无关，实则是在为朱元璋心态的转变做铺垫：他扫平外患之后，权力失去了外部对手，内心的不安全感必然转向内部。

整段判断的支点是"ch 17 党争初起，叙事开始收束"——但 citation 列表里完全没有 ch 17 的原文。reviewer 立刻就抓到了这一点。

对比 baseline 的 q1，看看 ch 17 应该是什么样子的 citation：

> chapter 17：演员到齐了，下面我们来看看这场戏是怎么演的吧。先说一下淮西集团的首领李善长，他被朱元璋引为第一功臣，于洪武三年被封为韩国公

这一句"演员到齐了，下面我们来看看这场戏是怎么演的吧"是元叙事级伏笔——作者本人在这一句里明确告诉读者"前面铺的舞台搭好了，戏要开始了"。这恰好对应 candidate 想论证的"叙事张力开始收束"——但 candidate 没拿到这一句。

它**记得**作者写过这种话（训练污染所致），但它**没去查**。

更精确地说：candidate 在这道题上调了 2 次 tool（1 次 get_chapter_range + 1 次 search_chunks）。如果它再调 1 次 search_chunks（query="刘基 李善长 党争"或"废相 朱元璋"），ch 17 的原文应该就能拿到。但它没调，**因为它"觉得自己已经知道了"**。

这就是训练污染的精确机制：模型不是不能查，是**觉得不需要查**。"我已经知道"≠"我已经查过"——这条规则我在 v3.1 prompt 里专门写了 C 条，但 prompt 写了不等于模型遵守。

q1 candidate 的 18 分扣分，3 分扣在 evidence_density，2 分扣在 actionability。但它真正损失的，是**这道题作为 BookScope 验证用例的价值**——一道靠 LLM 训练记忆作答的节奏评估题，跟 ChatGPT/Claude 直接问没有区别。BookScope 的差异化能力（原文证据现场调取）在这一题上没体现。

---

## 六、citation 数量的边际收益曲线（假设）

把第 26 轮和第 24 轮、第 25 轮的真数据放在一起，加上文献阅读的直觉，我尝试画一条 citation 数量与论证可信度的边际收益曲线（注意：这是基于 BookScope 当前数据规模 + 文献直觉的**假设**，不是大样本统计结论）：

| citation 数 | 论证状态 | 可见现象 |
|---|---|---|
| **0 条** | schema fail | LLMFormatError，本次 query 不返回结果 |
| **1-3 条** | 不足 | 单点支撑，跨章节论证完全无原文锚点；作家几乎无法用 |
| **4-7 条** | 够基础但脆弱 | 关键节点能锚住，但 coverage_ratio 通常 < 50%；一旦论点跨多章必漏支点 |
| **8-12 条** | 稳健 | coverage_ratio 通常 ≥ 70%；论点-citation 一一对应较稳定 |
| **13+ 条** | 边际递减 | 多出来的 citation 倾向重复、近义、表层事件；reviewer 不会再加分 |

第 26 轮的数据正好落在分界线上：

- baseline 平均 10.6 条 → 落在"稳健"区间，evidence_density 5.0
- candidate 平均 5.8 条 → 落在"够基础但脆弱"区间，evidence_density 3.6

这条曲线对 BookScope 的产品意义是：**citation 数量不应该被当成"越多越好"的连续变量来追求，而应该被当成"达到稳健阈值"的离散判定来卡**。

具体来说：

- citation < 4 条 直接 reject（让 generator 重新跑或返回作家"证据不足"）
- citation 4-7 条 + coverage_ratio < 60% → reviewer 二级 metric 标红
- citation ≥ 8 条 + coverage_ratio ≥ 70% → 进入正常评估流程

这个判定不需要 reviewer 做精细评估——只需要 batch runner 自动算出来。是一个**纯结构性的卡口**，零 LLM 成本。

---

## 七、引文质量的另一面：8 条好 citation 怎么打败 13 条平庸 citation

但我必须承认——光看数量也会误导。

q5 是 baseline 5 题里 citation 数最少的一题（8 条），却拿了 24 分（仅次于满分），evidence_density 也是 5。这意味着 8 条**精选**citation 比 13 条平庸 citation 更有力。

把 baseline q5 的 8 条 citation 摘出来看（设定漂移题）：

> chapter 14：这件事情却给朱元璋造成了极大的心理阴影，他从此不敢相信任何人，连自己最放心，最得力的侄子都背叛自己，还有何人可以相信？对于朱元璋来说，火药已经埋藏在他的心里，就看何时爆发了。

> chapter 17：朱元璋是一个乡土观念很重的人，李善长是他的老乡，而且多年来只在幕后工作，从不抢风头，埋头干活，这样的一个人朱元璋是很放心的。相对的，刘基是一个外乡人，更重要的是，刘基对事情的判断比他还要准确！……换了你是皇帝，会容许这样的一个人在身边么？……不杀他已经不错了，还想要封赏么。

> chapter 18：朱元璋甘愿忍受胡惟庸的专横……他这样委屈自己，只因他的目标对手太过强大，这个对手并不是李善长，也不是淮西集团，而是胡惟庸身后那延续了上千年的丞相制度。

> chapter 22：朱元璋不作声，叫人找了一根带刺的木棍丢在朱标面前，让朱标去捡。朱标也不是白痴，看见有刺自然不动手。朱元璋冷冷的看着他说：「我杀人就是要替你拔掉这根木棍上的刺，这些都是危险人物。」

> chapter 28：朱允炆虽然从朱元璋那些学到了很多东西，但关键的一条规则他并没有领会，这也是朱元璋一生的信条。要么不做，要么做绝。

每一条都是**性格定性句**——"火药已经埋藏""换了你是皇帝""要么不做要么做绝""我杀人就是要替你拔掉这根木棍上的刺"。这些不是事件复述，是作者用来定性人物底色的元叙事级原文。

reviewer 给 q5 的 evidence_density 注释：

> citation 精准命中角色底色的定性句与深层动机，如第 14 章的心理阴影判词、第 17 章的'放心/不容许'对比、第 18 章的欲擒故纵，均为非表层伏笔级证据，直接支撑'猜忌底色前置'的核心主张。

8 条 citation，全是"判词级"原文。每一条都精准对应 answer 里"权力逻辑前置、不存在设定漂移"这一核心论点的某条具体子主张。这不是数量稀疏，是**密度极高**——每条 citation 的论证负载是平均水平的两倍。

对比 baseline q4（13 条 citation，最多）。q4 的 13 条里有几条比较稀——比如 ch 23 引了两条（一条"命运之神来到了朱重八的床边"，一条"他相信自己能够操控一切"），是为了支撑同一个"宿命论替代性格演变"的论点；ch 24 一条"孤家寡人"和 ch 22 一条"拔刺"分别支撑结尾呼应。13 条里大概 3-4 条有部分重复支撑。

这意味着 BookScope 的二级 metric 不能是简单的"citation 越多越好"。我们要的指标是：

1. **citation_count**（基础数量）
2. **coverage_ratio**（章节覆盖率）—— 上节定义
3. **citation_per_unique_chapter**（章节平均 citation 密度）—— 衡量 citation 是否过度集中在某几章
4. **(可选) citation_quality_score**（每条 citation 的论证负载）—— 这个需要 LLM 做，先不做

数量是必要条件，但不是充分条件。质量需要 reviewer 的 evidence_density 维度去判，不是 batch runner 能算的。但 batch runner 能在论证开始之前就把 quantity + coverage 的硬数据摆出来，让 reviewer 不至于把 evidence_density 5/3 这样**结构性的差距**压成 1.4 分的小幅波动。

---

## 八、reviewer rubric 第二条的评分逻辑（以及它没看见的盲区）

把 reviewer_rubric_v1.md 的 evidence_density 维度抄一遍——

> **2. 证据密度与精度（evidence_density）**
>
> citation 是真正支撑 answer 主张的关键原文，还是 decoration？尤其注意非表层伏笔——隐喻性描写、性格定性句、对话中的暗示。
>
> - **5 分**：citation 精准命中关键节点，包括非表层伏笔（比如一句隐喻、一段性格描写）；每条 citation 都能对应 answer 里的一个具体主张
> - **3 分**：citation 多但集中在表层事件（"主角做了 X"），缺伏笔级证据
> - **1 分**：citation 稀少、或只是目录级 snippet / 无关段落

这条 rubric 设计得很好——它直接对接到我作为长篇网文作者最在意的"伏笔识别"。第 24 轮 baseline 在 q1 拿满分，靠的就是 reviewer 识别出"火药埋藏""演员到齐"这两处元叙事级伏笔被命中。

但 rubric 有一个我之前没意识到的**盲区**：

它评估的是"citation 命中的质量"，没评估"citation 没命中的代价"。

具体地：

- baseline q1 给 10 条 citation，覆盖 ch 14/16/17/18/19/20，主张支点全部有原文 → 5 分
- candidate q1 给 5 条 citation，覆盖 ch 14/15/18/19/20，**漏 ch 17 这个支点章节** → 3 分

reviewer 给 candidate 3 分的依据是"证据链有缺口"，但 3 分这个数字来自"citation 多但集中在表层"这条标尺——它是一个**饱和量表**，没设计来表达"应该覆盖 7 章但只覆盖了 5 章"这种**离散缺口**。

把 5/5 → 3/5 翻译回结构差异，掉的是"citation 数量"和"章节覆盖率"两个维度。但 1.4 分的均值掉幅，远不足以反映"覆盖率从 73% 跌到 38%"这个 35 个百分点的真实差距。

这就是我说的"二级 metric"必要性——

> evidence_density（reviewer 评分）评估 citation 命中质量，**反映"对的事情有没有做对"**
>
> coverage_ratio（结构指标）评估 citation 覆盖广度，**反映"该做的事情有没有都做到"**

两件事不重叠。reviewer 看 q1 的 5 条 citation 都是好 citation（每条命中事件节点），所以给 3 分而不是 1 分。但 BookScope 作为一套面向作家的评估系统，不应该满足于"5 条好 citation"——应该要求"5 条好 citation + 论证覆盖到论点的所有章节"。

---

## 九、一个被反向证明的真相：v2 没说"必须给 citation"，astron 老老实实给了 10-13 条

第 26 轮跑完后我去 diff 了 v2 和 v3.1 的 prompt 文本——想看看是不是 v3.1 prompt 里某条规则把 citation 数量压低了。

结果是：**v2 prompt 完全没有 explicit 说"每个论点都要有 citation"**。

v2 的 citation 相关约束就是 citation_format_v1.md 那几条——schema 层硬约束（必须有 citation 数组、必须有 chapter + snippet 字段、长度 ≥ 1）。没有"每条主张都要 citation 支持"、没有"覆盖论证涉及的所有章节"、没有"至少 N 条 citation"。schema 硬约束只要求"非空"。

v2+astron 在零文字层 citation 强约束的情况下，平均给 10.6 条 citation。

v3.1+minimax 在 explicit 强调 tool 调用 + 强调禁止训练记忆作答 + "我已经知道"≠"我已经查过"的情况下，平均给 5.8 条 citation。

**写得越细的 prompt 不一定产出越守约。**

这不是"prompt 工程没用"。astron 之所以给 10.6 条，根因不在 v2 prompt，在 astron-code-latest 这个 generator 的训练倾向——它训练里大概率包含了大量"工程化输出 + 详尽引用"模式，所以在 schema 只要求非空时它依然给得满满当当。minimax M2.7 训练里更多是"reasoning + 高效作答"模式，加上《明朝那些事儿》全文几乎肯定在它的训练数据里——它**真心觉得 5 条够了**。

这两件事告诉我：

**citation 数量不是 prompt 能稳定控制的变量。它是 generator 的训练倾向 + 训练污染 + tool-use 倾向三者综合的结果。**

我可以在 v3.2 prompt 里加"至少 8 条 citation"——但这会变成另一种敷衍。模型会凑数：把同一段切成两条 citation、或引用无关段落充数。我已经在第 25 轮看过这种凑数模式（v1 prompt 时 reviewer 在 top_issues 提到"第 20 章 citation 与 answer 错位"），写硬数字门槛只会让它更糟。

正确的做法是：

1. prompt 层不强行规定数量（保持 v2 的"宽 prompt + 强 schema"风格）
2. batch runner 自动算 citation_count、coverage_ratio、unique_chapters
3. reviewer 看到结构指标后再做语义评估，evidence_density 评分不需要承担"数量警示"职责
4. 如果 coverage_ratio 持续偏低（比如某 generator 平均 < 50%），就是该换 generator 的信号——而不是改 prompt

第 26 轮 candidate 平均 38% 覆盖率，是该换 generator 的信号，不是该改 prompt 的信号。这个判断和第 26 轮的 root cause 诊断（minimax 训练污染）方向一致——**问题不在 v3.1 prompt，问题在 minimax 在公开书 baseline 上不需要 tool**。

---

## 十、给 batch runner 加二级 metric 的可行性分析

提议把以下三个字段加到 batch JSON 的每题里：

```json
"citation_metrics": {
  "citation_count": 7,
  "chapters_referenced_in_answer": [3, 4, 5, 6, 9, 10, 12, 14, 17, 18, 19, 21, 22, 23, 24],
  "chapters_with_citation": [3, 4, 5, 23],
  "coverage_ratio": 0.27,
  "unique_chapters_in_citations": 4,
  "citations_per_chapter_avg": 1.75
}
```

实现成本估算：

- **chapters_referenced_in_answer**：从 answer 字符串里抽"第 N 章"或"ch N"的章节号——一个 regex `r'第([一二三四五六七八九十百千\d]+)章'` 加一个中文数字到阿拉伯数字的转换。中等复杂度，但 deterministic。50 行 Python。
- **chapters_with_citation**：直接从 citations 数组取 chapter 字段去重。5 行 Python。
- **coverage_ratio**：交集除并集。3 行 Python。
- **citation_count**：现有字段。0 行。
- **citations_per_chapter_avg**：count / unique_chapters。1 行。

总实现成本：50-70 行 Python，0 LLM 调用，0 额外 latency。可以加在 `scripts/run_batch_r1.py` 的 `_extract_trace_summary` 之后，作为新的 `_compute_citation_metrics` helper。

集成路径建议：

1. 第 27 轮（如果作者批准）：先实现 `_compute_citation_metrics`，重跑第 26 轮的 v2-batch-01 和 v3.1-minimax-batch-01——直接拿到第 26 轮的 coverage_ratio 真值，验证我这篇文章里的估算（73% vs 38%）
2. 第 28 轮：把 metric 加到 reviewer 的 prompt context 里——reviewer 评 evidence_density 时能看到 coverage_ratio = X%，让评分更校准
3. 第 29 轮：在 `compare_batches.py` 输出里加 coverage_ratio diff 列，做 batch 间对比时直接显示"这次 batch 的 citation 覆盖率掉了 35 个点"

这三个动作总成本估计 200-300 行代码，分三轮做，每轮可独立验证。比"改 prompt 试一次再跑全 batch"的成本低，但产生的诊断价值高很多。

唯一的工程风险点是**章节号抽取的鲁棒性**——answer 里章节号的写法不统一（"第 14 章"、"第十四章"、"ch 14"、"14 章"、"原书第十三章"等多种）。我手动看了 baseline 和 candidate 的 10 道 answer，至少 5 种写法。这个 regex 需要兼容比较多 case。但即使首版 regex 漏抽 10-15% 的章节号，coverage_ratio 的相对差距（73% vs 38%）依然显著——绝对值会漂，相对趋势是稳的。

---

## 十一、把这件事放回 BookScope 的整体定位里

第 11-15 轮我做了"查询时装配"的架构演进，第 16 轮跑通端到端，第 17 轮砍掉 reranker 守住 CPU 约束，第 22 轮接真 KG，第 24-25 轮跑通作家场景验证 + AI reviewer 闭环。

第 26 轮第一次让我看到：**架构机制可以是对的，但单一 metric 不够诊断系统健康度**。

evidence_density 5.0 是好数字。我在第 25 轮看到这个数字时，没意识到它身后藏着"baseline generator 自然输出 10+ 条 citation"这个隐性条件。换 generator 的瞬间，5.0 → 3.6 是**机制本身**的反应——但它把 4.8 分均分到 5 道题、5 维度上，每条 issue 看起来都不刺眼。

直到我手算了 coverage_ratio：73% → 38%，**35 个百分点**的掉幅，和 4.8 分的均值是同一件事的两种呈现。**结构指标比综合分数更刺眼，因为它没有被均值平滑**。

把这个反思推广到 BookScope 的整体设计原则——

1. **每个核心机制都需要至少一个结构指标**，不能只靠 LLM 综合评分。citation 机制 → coverage_ratio；KG 机制 → unique_characters_used；search 机制 → tool_call_count_total（已有）。
2. **结构指标应该比 LLM 评分跑得早、跑得便宜**。结构指标在 batch runner 里 deterministic 算出，LLM 评分在 reviewer 里语义评估。前者卡硬阈值，后者评细节。
3. **当结构指标和 LLM 评分背离时，相信结构指标**。如果 evidence_density 给 5.0 但 coverage_ratio 是 40%，说明 LLM reviewer 被"5 条好 citation"蒙过去了，没看到"漏覆盖 60% 章节"——以结构指标为准。
4. **不要试图用 prompt 修结构问题**。citation 数量这种事，根因在 generator 训练倾向 + 训练污染。改 prompt 是把症状转移到别处，不是解决。

第 26 轮原本是我准备"工程收尾，slot in case study 第 3 章"的轮次。结果它变成了"暴露第 25 轮收敛背后的覆盖率盲区，提出 BookScope 二级 metric 设计"的轮次。

这是 BookScope 这种"持续 self-test 工具"应该带来的副作用。我希望——也相信——后面还会出现更多这种"以为已经解决的问题被另一组数据重新揭穿"的瞬间。每一次都是一次结构升级的机会。

---

## 十二、收口：5 条 vs 13 条之间的真问题

回到题目。"5 条 vs 13 条"不是一个数量博弈。它是三个相互纠缠的问题被压在了一组数据上：

**第一个问题：citation 数量是 generator 训练倾向的副产品，不是 prompt 能稳定控制的。** v2+astron 自然给 10-13 条；v3.1+minimax 即便强制 tool 调用至少 1 次，依然只给 5-7 条。第 26 轮的真因是 minimax 在公开书 baseline 上有训练污染——它"觉得自己已经知道"，所以工具调到最低限度，citation 给到最低限度。

**第二个问题：BookScope 的硬约束（每条结论必须有 citation）是 schema 层的，不是论证层的。** schema 只要求 citations 数组非空、每条有 chapter + snippet。schema 不能保证 answer 中提到的每个章节都有对应 citation。第 25 轮之前没出问题，是因为 baseline generator 自然给得很多，覆盖率自然就高；不是因为机制设计在管这件事。

**第三个问题：evidence_density 这个 LLM rubric 维度，把"质量"和"覆盖率"压在了一个数字里——并且更倾向评质量。** reviewer 对 candidate q1 的 5 条 citation 评 3 分，依据是"证据链有缺口"——但 3/5 这个分数远不足以表达"应该覆盖 7 章但只覆盖了 5 章"这个 35 个百分点的离散损失。

针对这三个问题的设计响应：

| 问题 | 响应 | 实施轮次（建议） |
|---|---|---|
| citation 数量受 generator 训练倾向影响 | 接受，不试图用 prompt 修；用结构指标识别低输出 generator | 第 27-28 轮 |
| schema 层硬约束不管覆盖率 | 在 batch runner 加 coverage_ratio 计算，自动写入 batch JSON | 第 27 轮 |
| evidence_density 维度评分平滑了离散覆盖率损失 | 把 coverage_ratio 作为独立二级 metric，与 evidence_density 并列输出；reviewer prompt context 加入 coverage_ratio 让评分更校准 | 第 28 轮 |

把 coverage_ratio 落到代码上是最简单的一步——50 行 Python，零 LLM，零延迟。但它会改变 BookScope 的诊断分辨率：从"五维 25 分制 + 综合评分"升级为"五维 25 分 + 三个结构指标"，让我能更早识别哪些 batch 是"分数还行但覆盖率塌了"的伪绿灯。

第 26 轮的 candidate 看似"分数掉了 4.8 分"，本质上是"覆盖率塌了 35 个点"。如果我在第 25 轮就有 coverage_ratio 这个指标，第 26 轮 candidate 跑出来的瞬间就会被标红——红的不是 evidence_density 3.6，是 coverage_ratio 38%。

5 条 vs 13 条不是 5 vs 13 的问题。是 38% 覆盖率 vs 73% 覆盖率的问题。是 BookScope 还没看见自己一直没看见的那个维度的问题。

第 27 轮，我准备先把这 50 行 Python 写了——然后回头看第 26 轮的 batch JSON，应该能更精确说出当时到底发生了什么。

---

*草稿 · 作者未定稿 · BookScope 案例研究 · r1 代际*

*关联文件：`docs/internal/STATE.md` · `bookscope/agent/prompts/citation_format_v1.md` · `bookscope/agent/prompts/reviewer_rubric_v1.md` · `bookscope/agent/tools/schemas.py` · `docs/internal/experiments/data/v2-batch-01.json` · `docs/internal/experiments/data/v3.1-minimax-batch-01.json`*

*下一篇候选：article-07 「coverage_ratio 落地：50 行 Python 改写第 26 轮诊断结论」 · 视角：工程实施*
