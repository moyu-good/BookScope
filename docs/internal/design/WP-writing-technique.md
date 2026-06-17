# WP-writing-technique · 写作手法分析（功能队列第 7 个，design-first）

> 设计稿，作者已批"开发全部功能"。流程：本稿 → probe（GO 才建）→ build → live → 记一笔。

**目的**：分析作者的写作手法——怎么论证、怎么结构、怎么铺陈/用语，每个手法配原文例子。帮学习者"学手艺"。
**受益者**：学习者（想学写作/论证手艺，看高手怎么写）。
**成功标准**：列出书里显著的写作手法（手法 + 怎么用 + 原文例子 + 章节）；**命根子=不编造书里没用的手法、不编原文**；引用核验。

**方法论锚**：① 整本书结构化功能模式；② 发明区 probe playbook。手法"哪些显著"有主观性，GO 同 pacing/style 软一档——验"不编 + 例子锚得住原文"，不号称"穷尽所有手法"。

**方案概要**：
1. 端点 `POST /api/agent/writing-technique`（一键，同 argument-structure）。
2. 长上下文整本进 system → 出 JSON：`{techniques: [{order, technique: 手法名, how: 怎么用的, snippet: 原文例子, chapter}]}`。
3. **verify-filter**（手法例子常转述，核验不过的丢、只留逐字锚得住的）+ 章号纠偏 + 三守卫。

**数据结构**：`{order, technique, how, snippet, chapter, verified}`。

**前端**：左栏「写作手法」mode → 一键"分析手法"→ 手法卡（手法名 + 怎么用 + 原文例子 + 钤印）。复用评点卡 + SealMark。

**复用**：新建 `writing_technique.py`（照搬 argument_structure 一键 + 加 verify-filter[同 style_issues]）+ 端点 + `WritingTechnique.tsx`（近 ArgumentStructure）+ App 左栏。

**probe**：anshi（史书，有叙事/论证/史料运用等手法）。
- 正例：抽出的手法带 verified 原文例子，引用真实性 ≥90%、非空、3 run 稳。
- **命根子伪负例**：问书里**没用**的手法——如"这本书是否大量用第二人称叙事 / 意识流？给原文"（史书不会）→ 应答"没有/极少"，**不编例子**。假阳性 ≤20% 硬门槛。

**不做**：不做写作打分/优劣评判（只描述手法 + 给例子）；不做改写示范；大书 422。

**验证**：probe 过 → 建 → live 抽查（anshi 抽真手法 + 没用的手法不编）+ 单测零回归 + 前端 build。

## probe 结果（2026-06-16）：**GO**

- 正例引用真实性 **16/17 = 94.1%**（每次抽 5–6 个手法）。
- 命根子假阳性 **0/6**（问第二人称/意识流，史书不用，3 次全 used=false、不编例子）。

## 落地（✅ 2026-06-16，commit 见下）

- BE `writing_technique.py`（照搬 style_issues 一键 + verify-filter）+ 端点 `POST /api/agent/writing-technique` + 7 单测。
- FE `WritingTechnique.tsx`（一键分析 + 手法卡 + 钤印）+ App 左栏「写作手法」。
- 后端 819 + 前端 build 过、零回归。
