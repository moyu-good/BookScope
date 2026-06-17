# WP-entity-recall · 实体回溯快查（功能队列第 1 个，design-first 设计稿）

> **性质：设计稿，待作者审批，批准前不动代码。** 2026-06-16 起草。
> 流程：本稿过闸 → 跑轻量可行性 probe（GO 才建）→ 开发 → anshi 真跑 → 记一笔。

---

## 目的（一行 Why）

读长书时"这人/这物之前在哪出现过、做过啥"靠手动往回翻——费劲又易漏。给一个实体，一次理清它全书的出现轨迹、每处带原文，省去翻找。

**受益者**：读者（跟人物/线索）、作家（查自己稿里某设定之前怎么写的）、学习者（一个概念在哪些地方被用到）。
**成功标准**：给定实体 → 真实出现处（章节有序 + 每处在做什么 + 原文核验）；① 召回够用、② **命根子=假阳性 0（不编不存在的出现）**、③ 每处带原文逐字核验。

## 方法论锚

1. **整本书结构化功能模式**（`project_wholebook_feature_pattern`）：单独端点 + 长上下文出结构化 JSON + 三可靠性守卫 + 自写 UI。实体回溯是这套的又一个投影，复用已验证路径最稳。
2. **发明区 probe playbook**（`project_invent_zone_probe_playbook`）：正例(召回)+伪负例(命根子假阳性≤20%硬门槛)+3 次取众数。治"编造出现"这个 evidence-first 命根子风险。

## 方案概要

1. 新端点 `POST /api/agent/entity-recall`：入参 `book_session_id` + `entity`（用户给的实体名/指称）+ provider/key/model/base_url。
2. 走**长上下文**（整本进 system，已转默认）让模型列出该实体的全书出现处：章节有序、每处一句"在做什么"、每处原文逐字片段。出结构化 JSON。
3. 每处 evidence 过 `verify_citations` 核验 + 章号纠偏（命中 chunk 的真章号覆盖模型自报）。**编造的出现 → snippet 核验不过 → 标未核验**，前端可滤/降级。
4. 塞不下长上下文的大书：第一版 422 不支持（同其他整本功能），后续补 RAG 版。

## 数据结构

```jsonc
// 响应
{
  "entity": "安禄山",
  "scanned": true,                  // false=书太大没扫
  "appearances": [
    {
      "order": 1,                   // 全书时序
      "chapter": 3,                 // 真章号（verify 后纠偏）
      "what": "身兼三镇节度使、初登场",  // 一句话该处在做什么
      "evidence": "原文逐字片段……",
      "verified": true              // verify_citations 给
    }
  ]
}
```

## 前端形态

- 左栏导航加一项「实体回溯」（mode = "entity"）。
- 主画布：CanvasHeader（❡ 实体回溯 + 版心线 + 说明）+ 一个输入框（输人/物/概念名）+「回溯」按钮 → 竖向轨迹列出每次出现（章号 + what + 点开看原文 + 核验过盖**钤印**）。
- 复用 `SealMark`（钤印核验）+ 时间线那套竖向列表样式（`Timeline.tsx` 形态）。
- 与"一键全书透视"的区别：本功能要用户**输入实体**再跑，不是点一下就出。

## 三可靠性守卫（整本结构化功能通病，必焊）

1. **够 token**：高频实体出现多 → 输出可能长，`max_tokens` 给够（8000，同时间线），配截断抢救。
2. **关缓存防 poison**：`cache_enabled=False`（结构化输出功能一律关，防坏响应被缓存）。
3. **重试 + 截断抢救**：parse 失败重试一次 + `_salvage_truncated` 救截断的 JSON（复用既有 helper）。

## 与现有功能的复用关系

- **后端**：新建 `bookscope/agent/entity_recall.py`，结构照搬 `timeline.py`（长上下文 + 结构化 + verify + 章号纠偏 + 三守卫）。`schemas.py` + `routes/agent.py` 加端点（同家族）。
- **前端**：新建 `web/src/EntityRecall.tsx`，复用 `SealMark` + 时间线竖向样式；`App.tsx` 左栏 NAV_MODES 加一项、主画布加一个 mode 分支。
- **不重复造轮子**：verify_citations / 章号纠偏 / salvage / 长上下文调用全是现成的。

## 可行性 probe（建设前先跑，GO 才建）

实体回溯强复用已验证模式（关系图/时间线同类），可行性高；唯一要验的是 **evidence-first 命根子**。轻 probe（anshi，3 次取众数）：

- **正例（召回）**：已知高频实体「安禄山」「灵宝（之战）」「杨国忠」——主要出现处找全没（对照原文）。
- **伪负例（命根子假阳性，硬门槛）**：给书里**不存在**的实体——如"诸葛亮在这本书里哪些地方出现"（安史之乱书里没诸葛亮）→ 应答"书里没有/没写"，**不编出现、不配假原文**。
- **门槛**：假阳性 ≤20%（硬，破则 NO-GO）；引用真实性 ≥90%；召回够用（主要出现处大部分命中）。3 次取众数。

### probe 结果（2026-06-16，`probe-entity-recall-20260616-131540.json`）：**GO**

- **命根子假阳性 0/6 = 0%**：朱元璋 / 岳飞（错朝代真人、书里没有）3 次全返回 0 处、不编造。✓
- **引用真实性 137/149 = 91.9%**（≥90% ✓）；召回代理：高频实体平均 15.2 个核验过出现/次（安禄山单次抽到 41 处全核验）。✓
- **关键发现 → 第 3 守卫是 load-bearing**：杨国忠（超高频）3 次有 2 次 JSON 解析失败——出现太多、输出超 8000 token 截断成坏 JSON。建设必须焊死：**够 token + 重试 + `_salvage_truncated` 抢救截断**，否则高频实体回溯不可靠。
- 次要：灵宝之战 1 次 19 处只 7 核验（模型掺了些转述/编的）——unverified 的由 verify_citations 标出、前端不当已核验展示，evidence-first 不破。

## 影响范围（批准后才动）

- 新增：`bookscope/agent/entity_recall.py`、`web/src/EntityRecall.tsx`、`scripts/probe_entity_recall.py`。
- 改：`bookscope/api/schemas.py`（请求/响应模型）、`bookscope/api/routes/agent.py`（端点）、`web/src/App.tsx`（左栏 NAV_MODES + 主画布 mode 分支）。
- 测试：`tests/agent/test_entity_recall.py`（结构化解析 / verify / 三守卫）+ 一次 live 抽查。

## 不做什么（scope 边界）

- **不做全书实体自动抽取索引**——那是 r0 批量预处理范式，违背查询时代理。只按用户给的实体、查询时回溯。
- **不做复杂实体消歧 / 共指消解 NLP**——靠长上下文模型自己判同一实体的不同指称。
- **不做"选中词即回溯"联动**——第一版独立输入框，选中联动留后续。
- **大书 RAG 版第一版不做**——塞不下先 422。

## 验证方法

probe 三门槛过 → 建设；建成后 anshi live 抽查（已知实体召回 + 不存在实体不编）+ 单测零回归 + 前端 build 过。

## 落地（✅ 2026-06-16，commit `f217f51`）

- BE `entity_recall.py`（照搬 timeline 结构 + 实体放 user 消息保前缀缓存 + 空 appearances 合法返 []）+ 端点 `POST /api/agent/entity-recall` + 8 条单测。
- FE `EntityRecall.tsx`（输入框 + 竖向轨迹 + 钤印）+ App 左栏「实体回溯」+ 主画布 mode 分支。
- **live 抽查 anshi**：安禄山 60/60 核验、杨国忠 14/14（probe 里截断翻车的超高频被 `_salvage_truncated` 救回）、朱元璋 scanned=true 0 出现（命根子不编造）。后端 776 + 前端 build 过、零回归。
- 已上线（:5173 左栏「实体回溯」）。下一个队列项：论点结构梳理（学习者）。
