# 实验 002 · 私域稿 vs 公开书 baseline · 训练污染假设的可证伪检验

**起草日期**：2026-04-27（第 26 轮后）
**起草人**：项目负责人 + AI 副管理
**状态**：草案 · 等作者批准段 2 私稿提供 + 段 1 冷门书选择
**关联文档**：
- `docs/internal/STATE.md` 第 26 轮
- `docs/internal/experiments/001-baseline-comparison-mingchao.md`（实验 001 公开书 baseline）
- `docs/internal/case-study/articles/article-01-public-book-baseline-contamination.md`
- `docs/internal/case-study/articles/article-10-north-star-validated-by-data.md`

---

## 1. 实验目标

第 26 轮 v3.1+minimax 在《明朝那些事儿》baseline 上的 5 题 batch 全 LOSE 平均 -4.8 分。10 篇深度 article 集体归因"MiniMax-M2.7 训练数据包含本书引发的训练污染"——但**没有任何一篇提出可证伪检验**。

本实验设计两段对照，分离三个混淆变量：

| 变量 | 第 26 轮 batch | 段 1 实验 | 段 2 实验 |
|------|----------------|-----------|-----------|
| Generator | astron → minimax | 保持 minimax | 保持 minimax |
| Prompt | v2 → v3.1 | 保持 v3.1 | 保持 v3.1 |
| **Baseline 文本** | 《明朝那些事儿》 | **冷门中文书** | **作者私域稿** |

第 26 轮一次性变了 generator + prompt + 同一本公开书三件，结论混淆。

---

## 2. 段 1 · 训练污染假设的可证伪检验

### 假设

**H1**：MiniMax-M2.7 在《明朝那些事儿》上的 -4.8 分退化主要由训练污染驱动（模型见过本书全文，靠记忆 hallucinate 绕开 tool）。

**H0（零假设 / alternative）**：minimax 在所有 baseline 上都给"够用即停"风格的 5-7 条 citation，与是否见过测试集无关——这是模型风格而非训练污染。

### 实验设计

- **不变**：minimax M2.7 / v3.1 prompt / 5 题作家诊断题（节奏 / 支线密度 / 伏笔回收 / 角色转变可信度 / 设定漂移）/ reviewer rubric_v1
- **替换**：baseline 文本从《明朝那些事儿》换为一本"minimax 训练数据**几乎肯定不包含**"的中文叙事文本

### 冷门书选择标准

满足以下三条：

1. **中文叙事文本**（小说优先；作家诊断题对叙事文有效，对工具书 / 学术书无效）
2. **2024 年后出版**（minimax M2.7 是 2026-03-18 发布，但训练 cutoff 不明；2024 年后的书相对安全）
3. **印量低 / 网络流传少**（避免 fan fiction / 二创让模型间接见过）

**候选**（待作者确认）：
- 一本网文出版物（作者了解作品但 minimax 训练应未包含）
- 一本 2024-2025 年出版的中长篇小说（实体书，电子版未广泛流传）
- 一本译介中文版的外语冷门小说（双重过滤，原书有训练数据但译者新发挥）

### 判定标准

跑完段 1 batch 后，看三个 metric 与第 26 轮 v3.1+minimax 在《明朝》上的对比：

| Metric | 第 26 轮在《明朝》 | 段 1 在冷门书 | H1 / H0 倾向 |
|--------|-------------------|---------------|--------------|
| **平均 citation 数** | 5.8 条 / 题 | 待测 | 若 8+ → H1（训练污染坐实）；若仍 5-7 → H0（风格因素） |
| **平均 tool_calls** | 3.6 次 / 题 | 待测 | 若 6+ → H1；若仍 2-4 → H0 |
| **5 维平均总分** | 20.0 / 25 | 待测 | 若 23+ → H1（在干净 baseline 上恢复正常）；若仍 18-21 → H0 |
| **citation coverage ratio** | 0.7771 | 待测 | 不是判别 metric，但记录用于纵深分析 |

### 预期成本

- 段 1 跑 1 次 batch：约 14-20 分钟（参考第 26 轮 862.9s + 题目复杂度差异）
- 约 60-100 万 input token / 1.5-3 万 output token
- 自动 reviewer 5 次（同 batch 内）

### 失败模式预案

- **冷门书 epub 切分异常**：BookScope `book_chunker._detect_chapters` 假设标准章节 header；若冷门书章节标号特殊（如"上 / 中 / 下"或纯数字），需要先在 `chunk_book` 测一次，必要时打 manual workaround
- **冷门书字数过大**：超过 50 万字的 epub 在 BM25 索引上 OK，但 `get_chapter_range` 触发 20 万字上限风险高；BookScope 已有相应 ChapterRangeTooLarge 错误，agent 会改路径
- **冷门书诊断题不适用**：若书的体裁不是叙事文（散文 / 诗集 / 短篇集），五道作家诊断题（节奏 / 支线 / 伏笔 / 转变 / 漂移）不一定都有 ground truth，可能 reviewer 维度评分体系本身崩溃。换书或换题目。

---

## 3. 段 2 · NORTH_STAR 第 1 条真验证

### 假设

**H2**：作家自己未公开稿子是 BookScope 的真用例。在私域文本上，minimax M2.7 没有任何"训练记忆"可以 fall back，必须 tool 调用——BookScope 与 ChatGPT 直通的差异稳定显现。

### 实验设计

- **不变**：minimax M2.7 / v3.1 prompt / reviewer rubric_v1
- **替换**：
  - **Baseline 文本**：作者自己未公开网文稿子片段（建议 5-10 万字 / 含至少 3 处主线 + 2 处支线）
  - **5 道作家题**：**由作者本人出题**（这是 NORTH_STAR 第 1 条 + CLAUDE.md 第五节"作者不可替代的事"的硬约束——AI 不代出题）

### 作者准备清单

请作者按以下顺序准备：

1. **稿子文件**：
   - 格式：epub / txt / docx 任一（BookScope `book_chunker` 主力是 epub，txt 也支持；docx 需提前转 txt）
   - 字数：5-10 万字最佳（太短题目跑不起来，太长 KG 抽取代价高）
   - 章节结构：清晰 header（"第 X 章 标题"或类似），便于 chunker 识别
   - **匿名化**：放进 `test/` 目录前确认不含项目身份信息（CLAUDE.md 第一节硬规则——你自己稿子里如果有真名 / 现实公司名，要先脱敏）
   - 命名：`test/private-{slug}.epub` 或 `test/private-{slug}.txt`

2. **5 道作家诊断题**（建议覆盖 5 类）：
   - **节奏评估题**：稿子里某段叙事节奏是否匀速 / 哪一段最密 / 最稀
   - **支线密度题**：某个支线 / 配角的出场分布与刻画立体度
   - **伏笔回收题**：某条铺垫的章节分布与回收完成度
   - **角色转变可信度题**：主角某段心境 / 立场转变是靠事件展开还是凭感觉跳跃
   - **设定漂移题**：某规则 / 世界观 / 角色底色是否前后一致

   每道题严格按"针对自己稿子"设计，不要泛化。

3. **预期答案的 ground truth**（仅作者本人知道）：
   - 你写稿子的时候哪几章是真的"快了"或"慢了"？
   - 哪条伏笔你自己其实没回收到位？
   - 哪个角色你自己觉得设定有偏移？
   
   这是你后续亲跑评估的私人参考；不需要给 BookScope。

### 判定标准

段 2 不依赖 5 维评分胜负——因为作家私稿评估**只有作者本人可以最终判定**。BookScope 的产出是"5 道题 × 5 道答案 × 5 套 citation"，作者亲读 → 判断每道答案是否：

- **是真第一读者反馈**：BookScope 给的诊断与你自己心知肚明的"稿子薄弱处"是否对得上？
- **citation 是否真在稿子里**：每条 citation 是否能在你稿子里找到（minimax 没法用训练记忆胡编因为它没见过）
- **修改建议是否可执行**：能不能直接落到改稿 TODO

成功标志：**至少 3/5 道题的反馈让作者真听得进去**。这是 NORTH_STAR 第 1 条的实证。

### 副管理观察点

AI 在段 2 不参与"答案质量评估"——只跑 batch 收集数据。reviewer 评分仍跑（数据点保留），但**作者亲读才是 ground truth**。

---

## 4. 执行命令模板（待 baseline 文本到位时启用）

### 段 1 命令

```bash
# 假设冷门书 epub 已落到 test/cold-book-{slug}.epub
MINIMAX_API_KEY=sk-cp-... \
PYTHONIOENCODING=utf-8 \
BOOKSCOPE_SMOKE_EPUB=test/cold-book-{slug}.epub \
python scripts/run_batch_r1.py \
  --questions docs/internal/experiments/data/v2-batch-01.json \
  --output docs/internal/experiments/data/exp002-seg1-minimax-cold-book.json \
  --batch-id exp002-seg1-cold-book \
  --generator-prompt loop_system_prompt_v3.1
```

注：题目集复用 v2-batch-01.json 的 5 道（仅 question 字段被使用）。书的领域可能让题目"问得不贴切"——若是这样在执行前要把 5 道题改写成对冷门书有意义的形态，新 questions JSON 落 `docs/internal/experiments/data/exp002-seg1-questions.json`。

### 段 2 命令

```bash
# 假设作者私稿已落到 test/private-{slug}.epub，作者题目落 docs/internal/experiments/data/exp002-seg2-questions.json
MINIMAX_API_KEY=sk-cp-... \
PYTHONIOENCODING=utf-8 \
BOOKSCOPE_SMOKE_EPUB=test/private-{slug}.epub \
python scripts/run_batch_r1.py \
  --questions docs/internal/experiments/data/exp002-seg2-questions.json \
  --output docs/internal/experiments/data/exp002-seg2-minimax-private.json \
  --batch-id exp002-seg2-private \
  --generator-prompt loop_system_prompt_v3.1
```

### 对照报告

```bash
# 段 1 对照第 26 轮《明朝》baseline
python scripts/compare_batches.py \
  --baseline docs/internal/experiments/data/v3.1-minimax-batch-01.json \
  --candidate docs/internal/experiments/data/exp002-seg1-minimax-cold-book.json

# 段 2 对照第 26 轮《明朝》baseline
python scripts/compare_batches.py \
  --baseline docs/internal/experiments/data/v3.1-minimax-batch-01.json \
  --candidate docs/internal/experiments/data/exp002-seg2-minimax-private.json
```

---

## 5. 实验完成判据

### 段 1 完成判据

- 5 题 batch 全部 outcome=success
- 分类记录 H1 / H0 倾向（按上方 metric 表）
- 对照报告写入 `docs/internal/experiments/001-baseline-comparison-mingchao.md` 的"段 1 后续"或新建 002 文档

### 段 2 完成判据

- 5 题 batch 全部 outcome=success
- **作者亲读所有 5 道答案 + citation**（不可代替）
- 作者判定：3/5 道题反馈是否"真第一读者级"
- 作者判定：citation 是否能在自己稿子里找到对应位置

### 整体实验结论

实验 002 完成后，至少能回答两个问题：

1. **第 26 轮 -4.8 分退化的根因是训练污染还是 minimax 风格？**（H1 vs H0）
2. **NORTH_STAR 第 1 条是否被实证支持？**（H2 验证）

无论结果如何，都给 BookScope 第 27 轮提供方向数据——是 BookScope 的"哥白尼时刻"或"焦耳实验"。

---

## 6. 已经揭示的方法论 lesson（实验设计前）

第 26 轮后写的 10 篇 article 集体里，**6 篇**估算或推测过 citation coverage。post-process 实算后揭示：

- v2+astron baseline 平均 76.1%
- v3.1+minimax candidate 平均 77.7%

candidate **比 baseline 高**——但总分仍 -4.8 分。**article-06 估算的"38%"被实算反证**。这一翻转告诉我们：

- **citation 数量与 citation 覆盖率不直接相关**：v2 给 10-13 条但 answer 也提到更多章节（13 章对 5 章），最终覆盖率与 v3.1 持平
- **"覆盖率高"≠"分数高"**：reviewer 评 evidence_density 看的是"关键节点厚度"，不是"对位率"
- **AI 估算的数据 narrative 不可信，必须实算**：10 篇 article 里至少有 1 篇用了错的估算数字论证。研究 infra 的价值（article-09 论点）由此被自我证实

这个 lesson 直接驱动了本实验设计中"判定 metric 表"的字段选择——**所有判定字段必须由 batch runner 实算输出，禁止 AI 估算**。

---

## 7. 副管理 take

第 27 轮**强烈推荐**先跑段 2（作者私稿），后跑段 1（冷门书）。理由：

- 段 2 直接回到 NORTH_STAR 第 1 条 — 第 1 条是 BookScope 存在的理由，没有第 1 条 BookScope 是空中楼阁
- 段 1 是科学 hygiene 但分离假设的紧迫性低于回到 NORTH_STAR
- 若段 2 出现"真第一读者级反馈 ≥ 3/5"，BookScope r1 代际可宣告**P1 真验证通过**，r1 → r2 升级讨论可启动
- 若段 2 失败（minimax 在私稿上仍偷懒 / citation 仍稀薄），段 1 才有意义——确认是不是模型风格因素

但段 2 需要作者准备稿子 + 题目（CLAUDE.md 第五节硬约束），副管理不代做。等待作者就绪。

---

## 附录 · 实验执行历史日志（待跑后填）

留空。每段 batch 跑完后追加一节：执行日期 / batch_id / 平均分 / 关键观察。
