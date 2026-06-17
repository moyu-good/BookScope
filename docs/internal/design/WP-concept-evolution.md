# WP-concept-evolution · 跨章概念演进对照（功能队列第 5 个，design-first）

> 设计稿，作者已批"开发全部功能"。流程：本稿 → probe（GO 才建）→ build → live → 记一笔。

**目的**：给一个概念，看它在全书怎么一步步发展——每个阶段在哪章、概念被怎么用/深化/转义、带原文。帮学习者抓概念的演变脉络（理论书尤其需要）。
**受益者**：学习者（读理论书，跟一个核心概念怎么从提出到展开到深化）。
**成功标准**：列出概念的演进阶段（章节有序 + 这一处怎么发展 + 原文）；**命根子=书里没有的概念返空、不编造演进**；引用核验。

**方法论锚**：① 整本书结构化功能模式；② 发明区 probe playbook（命根子假阳性）。本功能是「实体回溯」的近亲（都是按用户给的单位、长上下文回溯 + verify），差别=回溯的是"概念怎么变"不是"实体在哪现"。也是概念图能力的时间维延伸。

**方案概要**：
1. 端点 `POST /api/agent/concept-evolution`，入参 `book_session_id` + `concept` + provider/key/...。
2. 长上下文整本进 system（概念放 user 消息保前缀缓存）→ 出结构化 JSON：`{stages: [{order, chapter, development: 这一处概念怎么发展, snippet}]}`，order 按章节先后。
3. 每条 snippet 过 verify_citations + 章号纠偏；三守卫照焊。**空 stages 合法**（概念不在书里 → []，命根子）。

**数据结构**：`{order, chapter, development, snippet, verified}`。

**前端**：左栏「概念演进」mode → 输概念名 → 竖向演进轨迹（每阶段 development + 原文 + 钤印）。复用 EntityRecall 形态 + SealMark。

**复用**：新建 `concept_evolution.py`（**几乎照搬 entity_recall.py**：empty→[] 合法 + verify + salvage + retry，prompt 换成"概念演进"）+ 端点 + `ConceptEvolution.tsx`（近 EntityRecall）+ App 左栏。

**probe**：zhinei（理论书）。
- 正例：真概念（如"市场"/"国家能力"）的演进阶段带 verified 原文，引用真实性 ≥90%、stages 非空、跨 3 run 稳。
- **命根子伪负例**：书里没有的概念（如"量子纠缠"，同 exp-014 concept graph 命根子）→ 返空、不编演进。假阳性 ≤20% 硬门槛。

**不做**：不做概念自动抽取索引（按用户给的概念查询时回溯）；不做演进图可视化（第一版竖列）；大书塞不下先 422。

**验证**：probe 过 → 建 → live 抽查（zhinei 真概念演进 + 不存在概念返空）+ 单测零回归 + 前端 build。

## probe 结果（2026-06-16）：先 **NO-GO** → 设计调整后建

- 命根子假阳性 **0/6 = 0%**（量子纠缠/区块链全返空、不编演进）——完美。
- 正例引用真实性 **34/41 = 82.9% < 90%**——**没过**。拖低的是"国家"这种极抽象/泛在概念：某次给 9 阶段只 2 条逐字核验得上（其余转述/编的 snippet）；具体概念（制内市场 4/4、10/10）则近满分。

**设计调整（回设计层，probe gate 起作用了）**：抽象概念模型易松手给非逐字 snippet。加
**verify-filter 守卫**——核验不过的演进阶段**直接丢，只 ship 核验过的**（同 style_issues，
不像 entity_recall 保留 unverified）。这样：① shipped 输出按构造 100% 核验、不会拿编的 snippet
误导；② 命根子 0% 已证。evidence-first 立得住。probe 数据里核验过的阶段（制内市场 ~7、国家
~20 跨 run）足够有用，filter 只去噪不伤召回主体。**据此建（带 filter）**。

## 落地（✅ 2026-06-16，commit 见下）

- BE `concept_evolution.py`（照搬 entity_recall + **核验不过的阶段丢**[style_issues 守卫]，
  empty→[] 合法）+ 端点 `POST /api/agent/concept-evolution` + 单测（含 unverified 被丢）。
- FE `ConceptEvolution.tsx`（输概念 + 演进竖列 + 钤印）+ App 左栏「概念演进」。
