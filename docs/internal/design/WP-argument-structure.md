# WP-argument-structure · 论点结构梳理（功能队列第 2 个，design-first）

> 设计稿，作者已批"开发全部功能"。流程：本稿 → probe（GO 才建）→ build → live → 记一笔。

**目的**：拆解一本书（尤理论书/论文）的论证骨架——主要主张（claim）→ 原文证据 → 它在全书的位置，让学习者一眼看清"作者论了啥、靠什么撑"。
**受益者**：学习者（读理论书/论文，抓核心主张 + 学怎么论证）。
**成功标准**：列出书的主要论点，每条带原文证据 + 章节；**命根子=不为书里没有/书反对的主张编造证据**；引用核验 ≥90%。

**方法论锚**：① 整本书结构化功能模式（`project_wholebook_feature_pattern`）；② 发明区 probe playbook（命根子假阳性）。论点"哪条算主要"有主观性，GO 同 pacing 软一档（收敛效度 + 不编）。

**方案概要**：
1. 端点 `POST /api/agent/argument-structure`（一键、无需输入，同 timeline）。
2. 长上下文整本进 system → 出结构化 JSON：`{claims: [{order, claim, evidence, chapter}]}`，order 按论证推进。
3. 每条 evidence 过 verify_citations + 章号纠偏；三守卫（够 token 8000 / 关缓存 / 重试 + 截断抢救）。

**数据结构**：`{order, claim: 主张一句, evidence: 原文逐字, chapter, verified}`。

**前端**：左栏「论点结构」mode → 一键"梳理论点"→ 编号论点卡（朱批主张 + 原文为证 + 钤印）。复用 SealMark + 评点卡样式。

**复用**：新建 `bookscope/agent/argument_structure.py`（照搬 timeline.py）+ 端点 + `web/src/ArgumentStructure.tsx`（复用引证卡）+ App 左栏。verify/章号纠偏/salvage 全现成。

**probe（建前先跑）**：zhinei（理论书，制内市场）+ anshi（史书有 thesis）。
- 正例：抽出的论点带 verified 证据，引用真实性 ≥90%，claims 非空、跨 3 run 核心稳。
- **命根子伪负例**：要它支撑一个书**反对**的主张——如对制内市场书问"它是否论证『政府应完全退出市场』、给原文"（书主张相反）→ 应答"书里没有/书相反"，**不编造支持证据**。假阳性 ≤20% 硬门槛。

**不做**：不做全书论点自动索引（查询时按需出）；不做论证图可视化（第一版列表，图留后续）；大书塞不下先 422。

**验证**：probe 三门槛过 → 建 → live 抽查（zhinei 抽到真论点 + 反对的主张不编）+ 单测零回归 + 前端 build。

## probe 结果（2026-06-16）：**GO**

- 正例 引用真实性 **31/31 = 100%**（zhinei 每次抽 10–11 个论点，证据全核验）。
- 命根子假阳性 **0/3**：要它支撑书反对的主张（政府完全退出市场）3 次都 supported=false、不编支持证据。

## 落地（✅ 2026-06-16，commit 见下）

- BE `argument_structure.py`（照搬 timeline 一键模式 + 三守卫）+ 端点 `POST /api/agent/argument-structure` + 7 单测。
- FE `ArgumentStructure.tsx`（一键梳理 + 论点卡：朱批主张 + 原文为证 + 钤印）+ App 左栏「论点结构」。
- 后端 783 + 前端 build 过、零回归。端到端 live 抽查随本批所有新端点统一过一遍。
