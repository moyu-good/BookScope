# 实验 004 · 跨题材稳定性：4 本书（历史/政经/网文/演义）的段位一致性与 std

**起草日期**：2026-06-10
**起草人**：项目负责人 + AI 副管理（RE 起草）
**状态**：~~设计完成，数据未齐~~ → **数据已齐，判定完成**（2026-06-10 当天 12 batch 全部跑完，见第 9 节；第 4-6 节保留为历史设计记录）
**关联文档**：
- `docs/internal/experiments/002-private-text-vs-public-baseline-falsification.md`（跨书对比设计思路）
- `docs/internal/experiments/006-sprint-6-kg-cache-validation-design.md`（4 组 quality probe 数据）
- `docs/internal/STATE.md` 第十七波（reviewer 全 null 问题）
- `docs/internal/ROADMAP.md` Sprint 3（跨题材基线，5/29-6/11 验收窗口）
- memory `feedback_probe_avoid_general_knowledge.md`
- memory `feedback_baseline_variance_first.md`
- memory `reference_minimax_reviewer_limit.md`

---

## 1. 实验目标

BookScope 的方向是服务任何长文本类型——历史小说、网文、政经论著、学术专著，不能只在一本热门演义上验证。但在第 33 轮（加入 anshi）和第十六波（加入 zhinei / kuicheng）之前，所有 batch 数据都来自《明朝那些事儿》一本书。

本实验的核心问题是：

**BookScope 的评分系统在不同题材上是否稳定？还是说分数主要由"模型对这本书的熟悉程度"决定，与题材本身无关？**

具体要回答三件事：
1. 4 本书在相同 5 道作家题上的平均得分差距有多大？
2. 同一本书 3 次跑的 std 是多少（区分 noise vs 真实题材差距）？
3. citation 密度（每题引用段落数）在不同题材上是否有系统性差异？

---

## 2. 测试书目

| 代号 | 书名 | 题材 | 已入仓 | 训练数据熟悉度预期 |
|------|------|------|--------|-----------------|
| mingchao | 《明朝那些事儿》 | 历史演义（热门普及书） | ✅ | 高 |
| anshi | 《安史之乱》（薛宗正） | 历史学术 | ✅ | 低 |
| zhinei | 《制内市场》（郑永年） | 政经论说 | ✅（第十六波） | 中 |
| kuicheng | 《亏成首富》（青衫取醉） | 网文 | ✅（第十六波） | 低（NORTH_STAR 第 1 条最贴近目标） |

四本书的选择覆盖了题材维度（叙事 vs 论说 vs 网文）和训练数据熟悉度维度（热门 vs 冷门）。这是实验 004 的核心设计：**不是只换一个变量，而是一次性看题材 × 熟悉度这两个维度的交叉效果**。

---

## 3. 实验设计

### 3.1 题目

使用 `docs/internal/case-study/test-book-templates.md` 中的 5 道作家题：

- q1：节奏评估题（叙事节奏密度分布）
- q2：支线密度题（配角 / 支线出场分布与立体度）
- q3：伏笔回收题（铺垫的章节分布与回收完成度）
- q4：角色转变可信度题（心境 / 立场转变的事件支撑）
- q5：设定漂移题（世界观 / 角色底色的前后一致性）

**注意**：q1（节奏评估题）在 anshi 上历史上不稳定，第十七波数据显示 anshi 两组都 q1 LoopTimeout。这是已知的题材相关不稳定点，需要在数据分析时单独标注。

### 3.2 批次设计

| 书 | 需要跑的 batch 数 | 当前已有数据 | 缺口 |
|----|-----------------|-------------|------|
| mingchao | ≥ 3 次 | exp006 有 2 组（empty / warm）；STATE 任务队列 v3.2 有 3 次跑（21.4 / 18.8 / 20.4） | 数据已有，可用 v3.2 的 3 次跑作 baseline |
| anshi | ≥ 3 次 | exp006 有 2 组（empty / warm）；v3.2 有 3-4 次跑数据 | 数据已有，可用现有数据 |
| zhinei | ≥ 3 次 | 第十六波只有 1 次端到端答题（未跑完整 5 题） | **缺 3 次完整 5 题 batch** |
| kuicheng | ≥ 3 次 | 第十六波只有 1 次端到端答题（未跑完整 5 题） | **缺 3 次完整 5 题 batch** |

mingchao 和 anshi 的数据已经足够，关键缺口是 zhinei 和 kuicheng 各缺 3 次 batch。

### 3.3 评分方式

**reviewer 必须用 DeepSeek 或 Anthropic，不能用 minimax**。

第十七波 exp006 的教训：minimax 在 reviewer 这条路径（作家诊断题 + 5 维度结构化打分）上稳定拒答，60 次调用全部返空。用 minimax 当 reviewer 的数据不可信。

本实验执行前提：**必须有可用的 DeepSeek 或 Anthropic API key**。这是当前 blocked 的主要原因。

### 3.4 核心 metric

每本书计算：
- 5 题平均得分（满分 25）
- 5 题 std（衡量稳定性，< 1.5 为好）
- citation 密度（每题平均引用段落数）
- q1 / q5 单题得分（这两道题历史上最不稳定）

跨书比较：
- mingchao 和 anshi 的得分差是否 > 两者 std 的 1.5 倍（即是否是真实题材差距而非 noise）
- zhinei（论说体）和 kuicheng（网文）的 citation 密度是否比叙事类书低（论说体按段落引用可能不如叙事书密）
- 4 本书是否存在"题材相关"的得分崖——即某类题材系统性低分

---

## 4. 当前数据状态

### 4.1 已有数据

**mingchao**（来自 exp006 + 第 33 轮第五部分）：

| 轮次 | 条件 | 平均分 | 数据来源 |
|------|------|--------|---------|
| v3.2 第 1 次 | warm | 21.4 | 第 33 轮第二部分 |
| v3.2 第 2 次 | — | 18.8 | 第 33 轮第五部分 |
| v3.2 第 3 次 | — | 20.4 | 第 33 轮第五部分 |
| exp006 empty | cache cold | 数据在 `docs/internal/experiments/data/` | 第十七波 |
| exp006 warm | cache warm | 数据在 `docs/internal/experiments/data/` | 第十七波 |

mingchao v3.2 三次：平均 20.2，std 1.06，范围 18.8-21.4。**数据已齐，可用于实验 004 分析**。

**anshi**（来自 exp006 + 第 33 轮）：

| 轮次 | 条件 | 平均分 | 数据来源 |
|------|------|--------|---------|
| v3.3 第 1-3 次 | — | 19/18/19 | 第 33 轮第三部分 |
| exp006 empty | cache cold | 数据在 `docs/internal/experiments/data/` | 第十七波 |
| exp006 warm | cache warm | 数据在 `docs/internal/experiments/data/` | 第十七波 |

anshi v3.3 三次：q5 std 0.47（vs v3.2 的 3.8），整体段位 19-20。**数据已齐，可用于实验 004 分析**。

**zhinei / kuicheng**：

第十六波的端到端答题是功能验证性质，不是完整 5 题 × 3 次的 batch。当时记录：
- zhinei（制内市场，398 chunks）：105s，10 citation，q 未跑完整套
- kuicheng（亏成首富，4319 chunks）：107s，13 citation，q 未跑完整套

两本书的系统跑数据**完全缺失**。

### 4.2 数据文件位置

现有相关数据文件（仅供参考，实验 004 专用数据待产出）：
```
docs/internal/experiments/data/
  ├── exp006-anshi-empty-*.json
  ├── exp006-anshi-warm-*.json
  ├── exp006-mingchao-empty-*.json
  └── exp006-mingchao-warm-*.json
```

实验 004 专用数据文件规划：
```
docs/internal/experiments/data/
  ├── exp004-zhinei-batch-01.json
  ├── exp004-zhinei-batch-02.json
  ├── exp004-zhinei-batch-03.json
  ├── exp004-kuicheng-batch-01.json
  ├── exp004-kuicheng-batch-02.json
  └── exp004-kuicheng-batch-03.json
```

---

## 5. 执行前置条件

实验 004 能启动，需要同时满足：

1. **reviewer 的 DeepSeek 或 Anthropic API key 到位**（minimax reviewer 全 null 已证实，不可用）
2. **Sprint 3 窗口确认延期**，新窗口定为 Sprint 4（6/12-6/25）
3. zhinei 和 kuicheng 的 EPUB 文件确认在测试目录中可正常读取（第十六波已入仓，应可用）

当前 blocked 原因：session 停摆 22 天（5/19-6/10），reviewer key 仍未到位。

---

## 6. 延期处置

### Sprint 3 窗口处置

原计划验收窗口 5/29-6/11 到期，QA batch 没跑。今日（6/10）是窗口最后一天，技术上到期。

建议处置：
- Sprint 3 验收目标滚动进 **Sprint 4 窗口（6/12-6/25）**
- 实验 004 列为 Sprint 4 第一优先 RE 任务（需 DeepSeek/Anthropic reviewer key 解锁）
- 不宣告 Sprint 3 失败——Sprint 3 的工程目标（zhinei + kuicheng 入仓 + 端到端答题）已在第十六波实际完成，只是 batch 验收数据缺口留给 Sprint 4

此处置需要作者裁决是否同意（进 FLAGS 等待确认）。

---

## 7. 实验完成判据

### 必须完成的部分

- [ ] zhinei × 3 次完整 5 题 batch（reviewer 用 DeepSeek/Anthropic）
- [ ] kuicheng × 3 次完整 5 题 batch（同上）
- [ ] 产出 6 个 `exp004-*.json` 数据文件
- [ ] 计算 4 本书各自的平均分 / std / citation 密度
- [ ] 判断跨书得分差是否 > noise（参考 mingchao std 1.06 的量级）

### 分析报告必须回答

- 4 本书得分是否有系统性题材相关差距（叙事 vs 论说 vs 网文）？
- citation 密度在论说类书（zhinei）上是否显著低于叙事类书？
- q1（节奏题）在非叙事类书上是否系统性不适用（预期 zhinei 更明显）？

### 可选扩展

如果 4 本书基础 batch 跑完后时间允许，可扩展到：
- 5 本书（加入老残游记或论语，已在 Sprint 3 prep 候选清单）
- provider 对比（同一本书用 DeepSeek 和 Anthropic 各跑一次，看 provider 差异是否大于题材差异）

---

## 8. 案例研究钩子

实验 004 的发现预计支撑以下 case-study 内容：

- **chapter-04 延伸**：从"换一本它没读过的书"（mingchao vs anshi）进一步到"4 本不同题材的书"
- **article-13（预留）**：跨题材稳定性——BookScope 对网文的支持是否真实有效（NORTH_STAR 第 1 条）
- **exp-002 闭环**：exp-002 段 2 的核心问题"私域稿"是否可用 kuicheng 作 proxy（网文 + 非公开 = 最接近作者私稿场景）

如果实验 004 发现 kuicheng（网文）和 mingchao（热门演义）得分接近，说明 BookScope 在网文上不依赖模型的训练记忆，是一个有力的正向证据。

---

## 9. 实跑数据与判定（2026-06-10）

### 9.1 跑批配置

设计时缺 DeepSeek key，实跑时 key 到位，干脆 4 本书全部重跑——没有沿用第 4 节里 mingchao v3.2 / anshi v3.3 的旧数据。原因：旧数据是 minimax + v3.2/v3.3 跑的，和新配置之间隔了 generator、reviewer、prompt 三个变量，混在一起没法比。

| 项 | 值 |
|----|-----|
| 生成端 | deepseek-chat，prompt `loop_system_prompt_v3.5`，citation_format_v1，bm25_only |
| 评分端 | deepseek-chat，reviewer_rubric_v1（**同模型自评**，每份 JSON 的 `config.limitation` 都记了"存在自我偏袒风险"） |
| 数据 | `docs/internal/experiments/data/exp004-{mingchao,anshi,zhinei,kuicheng}-run{1,2,3}.json` 共 12 份，commit `eca8a57` |
| 耗时 | 17:26:48 启动 → 17:46:45 收尾，**19 分 57 秒跑完 12 个 batch**（`exp004-batch.log`，仓库根、未跟踪）；单 batch 67.8–99.0s |

一个要单独记的字段语义差异：**DeepSeek reviewer 的评分数字在 `questions[].review.total`，`overall` 是文字总评——跟 minimax 时代的字段理解正好相反**。同一份 rubric，两家 provider 把"总分"和"总评"装进了相反的字段。这次靠人工核对认出来了，下次换 provider 还会再踩。follow-up 见 9.9 第 2 条。

### 9.2 主结果

| 书 | run1 | run2 | run3 | 书均分 | run 间 std | coverage 范围 | verified 率范围 |
|----|------|------|------|--------|-----------|--------------|----------------|
| mingchao | 23.2 | 22.4 | 22.6 | **22.7** | 0.42 | 0.68–0.91 | 0.98–1.00 |
| anshi | 22.4 | 23.0 | 22.75 | **22.7** | 0.31 | 0.47–0.69 | 0.99–1.00 |
| zhinei | 20.8 | 19.0 | 22.0 | **20.6** | **1.51（压线）** | 0.24–0.50 | 0.98–1.00 |
| kuicheng | 21.6 | 22.8 | 22.8 | **22.4** | 0.69 | 0.80–0.89 | **0.82**–0.98 |

- **跨书 std = 1.02**，验收线 ≤ 1.5，**过**。
- 60 题里 58 题有分。缺的 2 题（anshi run3 q1、zhinei run2 q5）都不是答题失败，是 reviewer 的 JSON 没写对——见 9.3。
- 全场 verified 率最低的 kuicheng run1（0.817）和全场最低单题分 kuicheng run1 q3（14 分）是同一起事故——见 9.4。

### 9.3 两道缺分题：分其实打出来了，是 JSON 格式翻车

读两题的 `review._raw_text`，reviewer 的评分、维度评语、top_issues 全在，写得还相当像样。翻车点各是一个低级格式错：

- **anshi run3 q1**：`per_dimension_comment` 最后一个键值对后面多了个逗号（trailing comma），严格 JSON parse 失败，error 记 `reviewer JSON parse failed and autofix did not apply`。raw 里的分是 5+4+5+3+5 = **22**。
- **zhinei run2 q5**：`top_issues` 第二条字符串用全角引号 `”` 收尾，字符串没闭合，整个对象判定为 `no valid JSON object`。raw 里的分也是 5+4+5+3+5 = **22**。

这跟 astron 时代的裸 ASCII 引号问题是一类病：LLM 写 JSON 时混进标点小错，现有两层 autofix（定向 + 通用）都没接住 trailing comma 和全角引号这两种。如果人工把这两个 22 分回收进去，anshi run3 均分从 22.75 变 22.6、zhinei run2 从 19.0 变 19.6——方向上不改任何结论，所以本报告一律按 JSON 落盘数字引用，不做人工修正。但 autofix 该补这两个 case（BE follow-up）。

### 9.4 深挖 1 · kuicheng run1 q3 = 14：低分和低 verified 率是同一起事故

q3 问的是"想亏钱的项目意外爆赚"这个核心反转的铺垫够不够厚。三个 run 同一道题，run2/run3 都拿 23，run1 只有 14。把三份答案摆在一起，差距一目了然：

- run2 答案 2014 字，逐案拆了摸鱼网咖 / 《回头是岸》 / Doubt VR 三次反转，每条线索挂章节号；run3 答案 2844 字，还把三个项目按铺垫厚度排了阶梯。
- **run1 答案只有 197 字**——就一段结论（"铺垫总体够厚，三者的反转都不是临场事后圆"），题目明确要求的"逐一检查"一个案例都没展开。

引用侧更难看。run1 q3 挂了 13 条 citation，**11 条 unverified**（`chunk_id` 全是 null，match_score 0.22–0.6）。整个 run1 60 条 citation 里 unverified 的 11 条**全部**来自 q3——其余四题 47 条全部 verified。也就是说 0.817 这个全场最低 verified 率，责任百分之百在这一题。

这 11 条 unverified citation 长什么样？不是原文摘抄，是**带评论的转述**。例如第 132 章那条："裴谦看向马洋……——这里埋下摸鱼网咖持续扩张的伏笔"——后半句是模型自己的解读，原文里没有这句话，逐字核验自然失败。run2 同题只有 2 条 unverified，run3 是 0 条。

reviewer 抓到的也是同一组问题：structural_judgment 2（"只给了结论没拆手法差异"）、actionability 2（"作家看完不知道哪条线要加料"）、evidence_density 3，评语里点名"只有两条标 verified""第 270 章那条 match_score 只有 0.22，几乎算误捡"。

**结论**：生成端这一把输出了"只有结论的短答案 + 摘要式引用"，citation 核验链（WP1，commit `5f3b716`）和 reviewer 从两个独立角度抓到了同一个问题——unverified 标记进了 reviewer 视野，分数被压下去。这是 citation 可信链的正面案例：坏输出没有混过去。剩下的问题在生成端——为什么 run1 会吐一个 197 字的残答案，值得 BE 查这一题的 trace。

### 9.5 深挖 2 · zhinei q2 std=3.2：分差掉在"有没有处方"

q2 问历史论证线（汉代盐铁专营到历代经济掌控）在书中是独立论证线还是注脚。三个 run 给分 23 / 18 / 24。

先说一致的：三个 run 的 structural_judgment 全是 5 分，核心结论一字不差——历史线是独立论证线，不是注脚。答案本身没有事实层面的分歧。

分差在两个软维度。run2 的 actionability 被打 **1 分**（run1 是 3、run3 是 4），honesty 被打 **3 分**（另两 run 都 5）。reviewer 对 run2 的原话："没有任何修改指引……这像一个书评，不是编辑反馈"、"对此类定性中可能存在的薄弱点完全回避了，整体语调偏向展示工作量"。对照答案：run2 的 1169 字确实通篇是梳理，既没点原书哪里薄、也没给一句"怎么改"；run1（2123 字）和 run3（1329 字）至少各自带了限定性判断。

但有一笔要诚实记下：run1 的 reviewer 评语同样写了"只有诊断没有处方"，actionability 却只扣到 3 分。**同等缺口，两次评分相差 2 分**——这道题的 std 一半来自生成端真实的行为差异（run2 确实没给处方），另一半来自 reviewer 自己对同一缺口的惩罚力度不稳。后者是 reviewer 方差，不是产品方差。

### 9.6 深挖 3 · zhinei q1 三 run 17/17/20，全场最低题：不是检索问题，是题型和 rubric 错配

先排除检索嫌疑：q1 三个 run 的 citation 是 16 / 15 / 14 条，verified 率 94%–100%，证据链完全正常。分掉在哪？actionability 三次是 **1 / 2 / 2**，外加 run1 的 evidence_density 2（答案列的案例清单——盐铁论、王安石、温州模式、土地财政——有一半没挂原文，是模型自己复述的）。

根因 reviewer 自己说破了。run3 的 actionability 评语原话："作家问的是『核心论点+支撑案例』，这偏向信息整理而非诊断修改，因此**可操作性天生不强**。"run1 的总评说得更直白："答复现在是考证笔记，不是审读意见。"

也就是说：zhinei 的 q1 是一道"核心论点是什么"的**综述题**，而 rubric 的 5 个维度里 actionability 占 5 分——综述题在这个维度上结构性拿不到分，答得再好上限也就 21–22。这和 memory `feedback_probe_avoid_general_knowledge.md` 是同一条教训的另一面：综述题不仅证据价值低，在作家 rubric 下也天然低分。**zhinei q1 的 17/17/20 测的不是 BookScope 在政论书上弱，是这道题和这把尺子不配套。**

给 PE 的 follow-up：政论书的题集要么把 q1 换成诊断题（"哪个案例对论证支撑最弱"就是 reviewer 评语里现成的好题），要么 rubric_v2 对综述题做维度降权。

### 9.7 跨题材观察：总分很平，coverage 才是分层的

总分跨书 std 只有 1.02，四本书看起来一样好。但 citation coverage 拉开了清晰的题材梯度：

> kuicheng 0.80–0.89　>　mingchao 0.68–0.91　>　anshi 0.47–0.69　>　**zhinei 0.24–0.50**

设计节 3.4 预测过"论说体按段落引用可能不如叙事书密"——coverage 数据证实了这个预测：叙事类（网文、演义）答案里的主张大都能挂回原文段落，政经论说类只有四分之一到一半能挂上。zhinei 的低 coverage、压线 std、最低均分是同一件事的三个表现：**论说体是当前这套"原文证据 + 作家 rubric"体系下最不服帖的题材**。

另一个第 8 节钩子的兑现：kuicheng（网文，模型训练数据熟悉度预期最低）均分 22.4，和 mingchao（热门演义，熟悉度最高）的 22.7 几乎持平，coverage 还是全场最高。这是"BookScope 在网文上不依赖训练记忆"的正向证据——但在同模型自评的前提下，这个结论的强度要打折，见 9.9 第 1 条。

### 9.8 Sprint 3 验收判定

| 验收条目 | 结果 |
|----------|------|
| 4 书 × 3 batch 跑完 | ✓ 12 份 JSON 落盘（commit `eca8a57`），60 题 58 题有分 |
| 跨书 std ≤ 1.5 | ✓ 实测 1.02 |
| 分析报告回答设计节问题 | ✓ 本节（题材差距 9.7 / noise 区分 9.2 / citation 密度 9.7 / q1 不适用性 9.6） |

**判定：过。** 附注两条：zhinei run 间 std 1.51 正好压线，是四本书里唯一的弱环；2026-06-10 一天内完成跑批 + 分析，原 Sprint 3 窗口（5/29–6/11）最后一天压哨交付，第 6 节的延期处置不再需要。

### 9.9 Limitation（引用上面任何数字前先读这节）

1. **同模型自评，22+ 均分不能跟 minimax 时代的 19–20 比。** 生成和评分都是 deepseek-chat，自我偏袒风险写在每份 JSON 的 `config.limitation` 里。从 minimax 时代到这次，generator、reviewer、prompt（v3.1 → v3.5）三个变量同时换了——这组数据的正确用法是**新 baseline 的第一组 std**（书内 0.31–1.51，跨书 1.02），不是"分数提升"的证明。下一次任何配置改动，先跟这组 std 比，差距不过 1 std 不下结论——memory `feedback_baseline_variance_first.md` 的纪律继续生效。
2. **DeepSeek 与 minimax 对 rubric 输出字段的语义理解相反**（total=数字总分 / overall=文字总评，minimax 时代相反）。rubric_v2 必须把输出 schema 钉死成字段名 + 类型 + 取值范围的硬约定，不能靠 provider 自己理解（PE follow-up）。
3. **与 exp006 数据不可直接比。** exp006 实跑的是 minimax + v3.1（exp006 文档第十节勘误），其 reviewer 60/60 全空另有根因（第十一节二次勘误）。两套数据在 provider、prompt 版本、reviewer 可用性三个维度上都不同，放在一张表里比就是错的。
4. **批跑脚本的元数据没按书替换。** 4 本书的 JSON 里 `book.path` 全是 `test明朝那些事儿.epub`，`kg_source` 全是 `manual_4_characters_朱元璋_李善长_徐达_常遇春`，anshi 的 `word_count` 记成 3134 也明显不对。答案内容、title、chunk_count 各书都对得上，评分数据本身可信，但 trace 元数据的可信度打了折——BE 要修，不然下次回查 trace 会被这些字段误导。
   **已修（2026-06-11）**，三处分开看：
   - `book.path`：`run_batch_r1.py` 原来用 `getattr(book, "source_path", "test明朝那些事儿.epub")` 兜底，而 `BookText` 根本没有 `source_path` 字段，所以永远写兜底值。改成从 `BOOKSCOPE_SMOKE_EPUB` 环境变量取（没设就用 `DEFAULT_EPUB`），与 `_load_book_session` 的实际加载路径一致。
   - `word_count`：根因在 `BookText.model_post_init` 用 `split()` 数词，中文没空格，数出来的是"段落数"量级。`schemas.py` 改成 CJK 文本按非空白字符计数。四本书修正后：anshi 3134 → 378171，zhinei 15441 → 448103，mingchao 32164 → 1480879，kuicheng 160443 → 5381554。
   - `kg_source`：脚本里写死的字符串改成从实际装配的 kg 对象动态推导。注意 12 份 JSON 的这个字段**值不用改**——exp004 实跑确实给所有书装的都是同一个手工 4 角色 KG（`_load_book_session` 不分书），字段当时说的是真话，错的是"写死、将来会说谎"这件事本身。
   12 份 JSON 的 `path` / `word_count` 已用 `scripts/backfill_exp004_metadata.py` 一次性修正（脚本幂等，重跑报 0 改动）。
5. **每书只有 3 run，std 自身的不确定度不小。** zhinei 的 1.51 究竟是真压线还是抽样运气，再跑 3 次才有把握；其中 run2 还缺 q5 一题（9.3），均分是 4 题算的。

---

## 附录 · 实验历史日志

| 日期 | batch_id | 书目 | reviewer | 平均分 | 关键观察 |
|------|----------|------|----------|--------|---------|
| 2026-06-10 | exp004-mingchao-run1 | mingchao | deepseek-chat | 23.2 | 全场最高 run |
| 2026-06-10 | exp004-mingchao-run2 | mingchao | deepseek-chat | 22.4 | — |
| 2026-06-10 | exp004-mingchao-run3 | mingchao | deepseek-chat | 22.6 | coverage 0.91 全场最高 |
| 2026-06-10 | exp004-anshi-run1 | anshi | deepseek-chat | 22.4 | — |
| 2026-06-10 | exp004-anshi-run2 | anshi | deepseek-chat | 23.0 | — |
| 2026-06-10 | exp004-anshi-run3 | anshi | deepseek-chat | 22.75 | q1 reviewer JSON trailing comma 缺分（9.3） |
| 2026-06-10 | exp004-zhinei-run1 | zhinei | deepseek-chat | 20.8 | q1=17 综述题低分（9.6） |
| 2026-06-10 | exp004-zhinei-run2 | zhinei | deepseek-chat | 19.0 | 全场最低 run；q5 全角引号缺分（9.3） |
| 2026-06-10 | exp004-zhinei-run3 | zhinei | deepseek-chat | 22.0 | — |
| 2026-06-10 | exp004-kuicheng-run1 | kuicheng | deepseek-chat | 21.6 | q3=14 残答案 + 11 条 unverified citation（9.4） |
| 2026-06-10 | exp004-kuicheng-run2 | kuicheng | deepseek-chat | 22.8 | — |
| 2026-06-10 | exp004-kuicheng-run3 | kuicheng | deepseek-chat | 22.8 | q3 citation 全 verified，与 run1 成对照 |
