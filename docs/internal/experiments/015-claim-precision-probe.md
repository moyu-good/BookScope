# exp-015 · claim precision（引用-论断 entailment）可行性 probe（设计）

> **性质：probe 设计草稿（design-first 过闸）。** citation 精度第二半（分两类已建，这是 claim precision）。

**日期**：2026-06-15
**上游**：ROADMAP 地基「citation 分两类 / claim precision」+ exp-008 §9 + ALCE + [[project_invent_zone_probe_playbook]]

---

## 1. 目的

- **Why**：`verify_citations` 只查"snippet 在不在书里"（来源真实性），**不查"snippet 是否真支撑它挂的那个论断"**（claim entailment）。一条**真实但不相关**的引用能蒙混过关——比如论断"X 导致 Y"配一段只提到 X 的原文。evidence-first 的下一层精度就是这个：引用不仅要真，还要真撑得起话。exp-011 CP2 也暴露过 agent 会错误归因（把"实有X号称Y"当矛盾）。
- **受益者**：所有用户（信任）；案例研究（证据质量论证）。
- **成功标准**：见 §4。

## 2. 方法论锚

- **ALCE（citation precision/recall）**：业界衡量带引用生成的标准——precision=引用是否支撑陈述、recall=陈述是否都有引用。本 probe 验 precision 侧的判定可行性。
- **发明区 probe playbook**：正例（真支撑，judge 别误伤）+ 负例（错配，judge 要揪出）+ 命根子（假阳性硬门槛）+ 3 次。

一句话：把"引用撑不撑得起论断"做成一个 LLM-judge 的 entailment 判定，先验这个判定准不准、会不会误伤。

## 3. 方案概要

手工标注的「论断 + 引用片段」对（anshi 取材，judge 只看这一对、不需全书，便宜）：

- **正例（真支撑，应判 supported）**：论断与引用对得上。如 论断"安禄山身兼范阳平卢河东三镇节度使" + 引用"安禄山……范阳、平卢、河东三镇节度使"。
- **负例（错配，应判 unsupported）**三型：
  - 完全无关：论断 + 一段讲别的事的原文。
  - 提到但不支撑：论断"X 导致 Y" + 只提 X、没建立因果的原文。
  - 过度声称：论断把原文的"号称/可能"夸成"确实"。

judge prompt：「下面一个论断 + 一段原文，原文能支撑这个论断吗？只答 supported / unsupported + 一句理由」。每对 3 次取众数。

## 4. 验证方法（go/no-go）

- **召回（负例）**：揪出错配的比例（judge 判 unsupported）。
- **假阳性（正例，命根子硬门槛）**：把真支撑误判成 unsupported 的比例。≤20% 才 go——误伤真引用比漏判更糟（用户会不信任所有引用）。
- **三型判别**：完全无关该 100% 揪出；提到不支撑 / 过度声称是难项，看判别力。
- 召回 ≥60% + 假阳性 ≤20% → GO（建 entailment 层：答案产出后对每条 claim-citation 跑 judge，标 supported/weak）。

## 5. 影响范围 / 不做

- 新增 `scripts/probe_claim_precision.py`（手工标注对 + judge × 3，人工对标）。不动生产代码。
- **不做**：不建生产 entailment 层（probe 验证后才设计——每 claim 一次 LLM judge 有成本，要权衡）；不做 recall 侧（陈述是否都有引用，另一题）；CP2 过敏的 consistency-prompt 修是相关但独立的一块。

## 6. 实跑结果与判定

**跑于** 2026-06-15，10 对 × 3 次，flash。数据 `data/exp015-claim-precision.json`。

### 判分（对 §4）

| 维度 | 结果 | 判 |
|---|---|---|
| 假阳性（正例被误判 unsupported，命根子）| **0/4** | ✅ 真支撑全判对 |
| 召回（负例揪出 unsupported）| **6/6** | ✅ 错配全揪出 |
| 完全无关 | 2/2 | ✅ |
| 提到但不支撑（因果未建立）| 2/2 | ✅ 难项也中 |
| 过度声称（号称→确实、矛盾→和谐）| 2/2 | ✅ 难项也中 |

满分 10/10、跨 run 一致。难项尤其说明问题：N3"杨贵妃导致怠政"配只说"宠爱杨贵妃"的原文→揪出（因果没建立）；N5"确实二十万"配"号称二十万"→揪出（过度声称）；N6"配合无间"配"互不服气"→揪出（反向）。**这些正是 verify_citations 只查来源真实性抓不到的微妙误用。**

### 判定：GO

LLM-judge 能可靠判"引用撑不撑得起论断"的 entailment，假阳性 0、连难项都中。claim precision 可建。

### 建设方案 + 成本权衡（待作者定）

建 entailment 层：答案产出后对每条 claim-citation 跑一次 judge，标 `supported` / `weak`。成本是关键权衡——每条引用 +1 次小 LLM 调用（judge 不需全书、便宜，但答案有 1-5 条引用就 +1-5 次）。三种落法：
- **常开**：每次答都核，最稳但成本翻倍档。
- **opt-in 按钮**："核验这些引用"按钮，用户想查才查——成本可控、推荐起步。
- **只核 unverified/paraphrase**：逐字引用（match_type=quote）天然可信，只对转述的跑 entailment——省一半。

### caveat

1. 手工标注 10 对、错配偏明显；真实误用更隐蔽，建设后用真实答案复跑。
2. judge 也是 flash，自身可能错判——但 probe 显示在这些案例上稳。
3. CP2 过敏（consistency 把"号称/实有"当矛盾）是相关但独立的 prompt 修——本 probe 证明 judge 能分清"过度声称"，consistency prompt 可借同款判别加 guidance。
