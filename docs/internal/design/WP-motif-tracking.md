# WP-motif-tracking · 主题母题追踪（功能队列第 6 个，design-first）

> 设计稿，作者已批"开发全部功能"。流程：本稿 → probe（GO 才建）→ build → live → 记一笔。

**目的**：追踪一个主题/母题在全书的复现——每处怎么体现、在哪章、带原文。帮读懂密度大的书 / 名著（一个母题反复出现、织进全书）。
**受益者**：读者（读名著/密度大的书，想看一个母题怎么贯穿）。
**成功标准**：列出母题的复现处（章节有序 + 这处怎么体现 + 原文）；**命根子=书里没有的母题返空、不编复现**；引用核验。

**scope 决策（evidence-first 红线）**：原任务含"典故注释"。**典故出处注释靠的是书外知识**（典故指向外部典籍），与 BookScope 立身之本"结论钉原文"冲突——v1 **只做原文可锚的母题复现追踪，典故外部注释不做**（要做得单开"外部知识"信任层，标清非原文核验，留后续）。诚实划界胜过混进编造风险。

**方法论锚**：① 整本书结构化功能模式；② 发明区 probe playbook。本功能是「实体回溯 / 概念演进」家族第三个（按用户给的单位长上下文回溯 + verify-filter）。

**方案概要**：
1. 端点 `POST /api/agent/motif-tracking`，入参 `book_session_id` + `motif` + provider/key/...。
2. 长上下文整本进 system（母题放 user 消息保前缀缓存）→ 出 JSON：`{occurrences: [{order, chapter, manifestation: 这处怎么体现该母题, snippet}]}`。
3. **verify-filter**（同概念演进：母题体现常是转述，核验不过的丢、只留逐字锚得住的）+ 章号纠偏 + 三守卫。空 occurrences 合法（母题不在书）。

**数据结构**：`{order, chapter, manifestation, snippet, verified}`。

**前端**：左栏「母题追踪」mode → 输母题 → 竖向复现轨迹 + 钤印。复用 EntityRecall 形态。

**复用**：新建 `motif_tracking.py`（照搬 concept_evolution：input + verify-filter + empty→[]）+ 端点 + `MotifTracking.tsx`（近 ConceptEvolution）+ App 左栏。

**probe**：anshi。
- 正例：真母题（如"正统/合法性"、"宣传"）的复现处带 verified 原文，引用真实性 ≥90%、非空、3 run 稳。
- **命根子伪负例**：书里没有的母题（如"赛博朋克"、"星际航行"）→ 返空、不编复现。假阳性 ≤20% 硬门槛。

**不做**：典故外部出处注释（见 scope 决策）；母题自动抽取索引；可视化（第一版竖列）；大书 422。

**验证**：probe 过 → 建 → live 抽查（anshi 真母题复现 + 不存在母题返空）+ 单测零回归 + 前端 build。

## probe 结果（2026-06-16）：**GO**

- 正例引用真实性 **23/24 = 95.8%**（宣传/正统；宣传高频在裸 probe 有截断，生产 salvage+verify-filter 兜住）。
- 命根子假阳性 **0/6**（赛博朋克/星际旅行全返空、不编复现）。

## 落地（✅ 2026-06-16，commit 见下）

- BE `motif_tracking.py`（照搬 concept_evolution + verify-filter）+ 端点 `POST /api/agent/motif-tracking` + 7 单测。
- FE `MotifTracking.tsx`（输母题 + 复现竖列 + 钤印）+ App 左栏「母题追踪」。
- 后端 812 + 前端 build 过、零回归。
