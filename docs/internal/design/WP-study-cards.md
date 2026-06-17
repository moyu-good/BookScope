# WP-study-cards · 知识点卡片 + 苏格拉底测我（功能队列第 8 个，design-first）

> 设计稿，作者已批"开发全部功能"。流程：本稿 → probe（GO 才建）→ build → live → 记一笔。

**目的**：据书出知识点卡片，每张含一个知识点 + 一道苏格拉底式自测题（先自己想、再翻看答案）+ 原文。帮学习者内化 + 自检理解。
**受益者**：学习者（拿书学东西，想要可自测的知识卡片）。
**成功标准**：列出书的知识点卡片（知识点 + 自测题 + 原文）；**命根子=不编书里没有的知识点、不编原文**；引用核验。

**scope 决策**：原任务"知识点卡片 + 苏格拉底测我"。完整的**多轮互动苏格拉底对话**（AI 追问→你答→再追问）状态/UI 重，v1 不做；**v1 = 知识点卡片 + 每张一道苏格拉底自测题**（卡片"先想后翻"形态，自测，不是 AI 实时追问）。完整对话留后续（可复用 ask 的多轮）。诚实划界。

**方法论锚**：① 整本书结构化功能模式；② 发明区 probe playbook。是 [[writing_technique]]/[[argument_structure]] 形态（一键 + verify-filter）。

**方案概要**：
1. 端点 `POST /api/agent/study-cards`（一键）。
2. 长上下文整本进 system → 出 JSON：`{cards: [{order, concept: 知识点名, point: 解释, question: 苏格拉底自测题, chapter, snippet: 原文依据}]}`。
3. **verify-filter**（snippet 核验不过的丢、只留锚得住的）+ 章号纠偏 + 三守卫。

**数据结构**：`{order, concept, point, question, chapter, snippet, verified}`。

**前端**：左栏「知识卡片」mode → 一键"出卡片"→ 卡片列表：正面显示 concept + 苏格拉底自测题，点"翻看"展开 point 解释 + 原文 + 钤印。复用 SealMark + 卡片样式 + 局部 reveal。

**复用**：新建 `study_cards.py`（照搬 writing_technique 一键 + verify-filter）+ 端点 + `StudyCards.tsx`（卡片 + 翻看）+ App 左栏。

**probe**：zhinei（理论书，知识密度高）。
- 正例：抽出的卡片带 verified 原文、引用真实性 ≥90%、非空、3 run 稳。
- **命根子伪负例**：问书里**没教**的知识点——如"这本书是否讲解了'量子计算原理'？给原文"（制内市场书不会）→ 应答"没有"，**不编**。假阳性 ≤20% 硬门槛。

**不做**：多轮互动苏格拉底对话（见 scope）；卡片导出/间隔重复 SRS（留后续）；大书 422。

**验证**：probe 过 → 建 → live 抽查（zhinei 出真知识卡 + 没教的不编）+ 单测零回归 + 前端 build。

## probe 结果（2026-06-16）：**GO**

- 正例引用真实性 **26/26 = 100%**（zhinei 每次出 6–10 张卡）。
- 命根子假阳性 **0/6**（量子计算/光合作用，制内市场书没教，3 次全 taught=false、不编）。

## 落地（✅ 2026-06-16，commit 见下）

- BE `study_cards.py`（照搬 writing_technique 一键 + verify-filter）+ 端点 `POST /api/agent/study-cards` + 7 单测。
- FE `StudyCards.tsx`（一键出卡 + 卡片"先想自测题、翻看解释+原文" + 钤印）+ App 左栏「知识卡片」。
- 后端 826 + 前端 build 过、零回归。**功能队列 8 个全部交付**。
