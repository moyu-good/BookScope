# 001 · Agentic RAG 与长文本推理方向 · 论文地图 v1

> 版本：v1（初稿，AI 起草）
> 日期：2026-04-20
> 状态：未验证 — 所有 paper 的"实验日期 / 实验结果"字段均留待 r1 首版落地后再填写

---

## 前言

这份笔记是 BookScope 第一份论文研究笔记，是**初稿**，不是综述。

起草背景：2026-04-20 项目进入 r1 代际重建（从 r0-baseline 的三阶段离线流水线，切换到 agent loop + 查询时检索）。在 r1 正式开工前，先由 AI 基于其 knowledge cutoff 之前的认知，把"r1 开发过程中最可能触及的难题方向"预先整理成一份 paper 地图，作为后续遇到具体难题时的弹药库索引。

按项目 `docs/internal/WORKFLOW.md` 第四条：论文是遇到真难题时的弹药库，不是起点。因此本文档的作用是**索引**，不是**精读**：每篇 paper 只压缩到"所解问题 / 方法本质 / 与 BookScope 的关联 / 拟尝试"四个短段，方便后续在工程层踩到具体坑时快速定位。

按第七节的格式约定，二层研究笔记需要"实验日期"和"实验结果"两个强制字段。本文档的 v1 初稿阶段，**所有 paper 这两个字段统一填写"尚未验证（待 r1 首版落地后跑对应实验）"**，但保留字段占位，方便后续版本直接填入。这意味着严格意义上本文档还不是"完成的二层研究笔记"，它是研究笔记的前置索引。

后续节奏：r1 开发过程中每遇到一个真难题，就回来更新本文档对应条目（或拆出新编号文件）；当某个主线的 paper 积累到成体系时，独立成 `002-xxx.md`、`003-xxx.md`。

---

## 主线一 · Agentic RAG 范式

### Paper · Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection

- **作者与年份**：Asai et al., 2023（ICLR 2024）
- **引用数**：待核实（保守估计 500+）
- **所解问题**：传统 RAG 无条件检索，既检索了不必要的片段（噪声），也无法对自己生成的结论做质量自评
- **方法本质**：训练模型输出"反思 token"——在生成时自行判断"是否需要检索 / 本次检索结果是否相关 / 生成的句子是否被证据支撑"。把检索决策和生成质量评估内嵌到解码过程
- **与 BookScope 的关联**：r1 的 agent loop 本质就是"检索—生成—自评—再检索"的循环。Self-RAG 的反思 token 设计是当前 agent loop 最直接的参考。尤其适合 BookScope 场景下"读者问一个书里没有明确答案的问题"时，判断何时停止深挖、何时承认未知
- **拟尝试**：r1 agent loop 里把"retrieve? / relevant? / supported?"三个判断点显式写成 agent step，而不是隐式混在一次 prompt 里。对比"单 prompt 全活"和"三段显式 self-critique"的 citation 命中率
- **实验日期**：尚未验证（待 r1 首版落地后跑对应实验）
- **实验结果**：尚未验证

### Paper · Corrective Retrieval Augmented Generation (CRAG)

- **作者与年份**：Yan et al., 2024
- **引用数**：待核实
- **所解问题**：检索结果质量不稳定时，LLM 容易把低质量证据也照单全收，导致幻觉
- **方法本质**：引入一个轻量级评估器给检索结果打分，分为"正确 / 错误 / 模糊"三档。错误档触发 Web 搜索回退，模糊档触发检索结果重写和再分解，正确档正常使用
- **与 BookScope 的关联**：BookScope 的检索源主要是单本书的分块，不像开放域那样有 Web 回退。但 CRAG 的"三档分流 + 错误回退"思路可以本地化为——当分块检索得分全部低于阈值时，降级为"基于章节 summary 的粗粒度回答"而不是强答
- **拟尝试**：在 r1 的 retrieval 层加一个轻量 reranker，把 top-k 分数分布做成三档分流。对"书中查无此事"类问题观察是否能稳定触发降级而不是瞎编
- **实验日期**：尚未验证（待 r1 首版落地后跑对应实验）
- **实验结果**：尚未验证

### Paper · RAPTOR: Recursive Abstractive Processing for Tree-Organized Retrieval

- **作者与年份**：Sarthi et al., 2024（ICLR 2024）
- **引用数**：待核实
- **所解问题**：单层 chunk retrieval 在长文档上丢失了跨段落、跨章节的抽象语义
- **方法本质**：对文档分块后做递归聚类——把相似块聚为一组，让 LLM 为每组生成摘要；再把摘要当作新节点继续聚类、摘要，直到树根。检索时同时查询叶子（原文）和内部节点（不同抽象层级的摘要）
- **与 BookScope 的关联**：非常贴近 BookScope 的核心难题——一本书既需要句子级证据，也需要章节级/全书级主旨。r0-baseline 里的"章节摘要 + 全书总结"本质是简化版 RAPTOR。r1 可以考虑把这种层级显式做成可被 agent 查询的多层树
- **拟尝试**：为 `test明朝那些事儿.epub` 建一棵 RAPTOR 树（叶=chunk, 中=章节, 根=全书），对比单层 chunk-only 检索和多层检索在"全书主旨类"问题上的差异
- **实验日期**：尚未验证（待 r1 首版落地后跑对应实验）
- **实验结果**：尚未验证

### Paper · HippoRAG: Neurobiologically Inspired Long-Term Memory for Large Language Models

- **作者与年份**：Gutiérrez et al., 2024
- **引用数**：待核实
- **所解问题**：长文档中的跨文档、跨段落的实体关联记忆，朴素向量检索无法有效建模
- **方法本质**：借鉴海马体索引理论——用 OpenIE 抽取实体和关系构建知识图谱，再用 Personalized PageRank 做图上检索。相当于把"联想式检索"显式建模
- **与 BookScope 的关联**：书籍是典型的跨段落实体网络（人物、事件、时间线）。r0-baseline 里的 knowledge_extractor 已经在做 KG 抽取，但缺的是"图上跳转式检索"。HippoRAG 的 PPR 检索可能是把 KG 真正用起来的关键
- **拟尝试**：对比单一向量检索、KG-only 检索、HippoRAG 混合检索在"这个人物和某事件的关系"类问题上的召回
- **实验日期**：尚未验证（待 r1 首版落地后跑对应实验）
- **实验结果**：尚未验证

---

## 主线二 · 长文本推理与 Lost in the Middle

### Paper · Lost in the Middle: How Language Models Use Long Contexts

- **作者与年份**：Liu et al., 2023（TACL 2024）
- **引用数**：待核实（高引，估计 1000+）
- **所解问题**：LLM 声称支持长上下文，但实际上对上下文中部的信息利用率远低于首尾
- **方法本质**：构造多文档 QA 基准，把正确文档放在上下文不同位置，观察准确率曲线。发现大多数模型都呈 U 型：首尾强，中间塌陷
- **与 BookScope 的关联**：核心警示——哪怕模型支持 200k context，把整本书丢进去也不等于模型真的"读了"。这直接支持了 BookScope 必须做 retrieval、不能走全文 context 路线的选择。同时也提醒 retrieval 后的拼接顺序需要把关键证据放在首尾
- **拟尝试**：r1 的检索结果拼接时，故意把最高分证据放在首位或末位（而不是按相关性顺序），对比 answer 质量
- **实验日期**：尚未验证（待 r1 首版落地后跑对应实验）
- **实验结果**：尚未验证

### Paper · RULER: What's the Real Context Size of Your Long-Context Language Models?

- **作者与年份**：Hsieh et al., 2024（NVIDIA）
- **引用数**：待核实
- **所解问题**：厂商宣称的 context window（例 128k、200k）是"能塞下"，不是"能用好"。缺一套能测量真实有效 context size 的 benchmark
- **方法本质**：设计 13 个合成任务（多值检索、多跳推理、聚合、变量追踪等），在不同上下文长度下测试模型。给出"有效 context"的量化估计
- **与 BookScope 的关联**：BookScope 在选型 embedding + LLM 组合时需要知道 agent loop 每步给模型喂多少 context 是"真的有效"。RULER 的方法论（尤其多值检索 / 变量追踪）可以本地化为"一本书里的多处人物提及"评测
- **拟尝试**：按 RULER 思路，在 `test明朝那些事儿.epub` 上造几个针对性任务（例：某人物在全书出现的所有场景），测 r1 链路的有效上下文
- **实验日期**：尚未验证（待 r1 首版落地后跑对应实验）
- **实验结果**：尚未验证

### Paper · CLongEval: A Chinese Benchmark for Evaluating Long-Context Large Language Models

- **作者与年份**：Qiu et al., 2024
- **引用数**：待核实
- **所解问题**：长上下文评测大多是英文语料，中文长文本（尤其是书籍级）的模型行为缺乏标准化评测
- **方法本质**：构建中文长文本 benchmark，含 7 个任务类别，文本长度覆盖到 200k 中文 token 量级。重点测试长文摘要、长文 QA、键值检索等
- **与 BookScope 的关联**：BookScope 首个标准测试集是明朝系列（中文、百万字级），英文 benchmark 很难外推。CLongEval 的任务构造方法可以直接借鉴用来构造 BookScope 内部评测
- **拟尝试**：对照 CLongEval 的任务分类，为 BookScope 内部建立 5-10 个标准 query，跑定期回归
- **实验日期**：尚未验证（待 r1 首版落地后跑对应实验）
- **实验结果**：尚未验证

---

## 主线三 · 书籍级 QA 与叙事理解

### Paper · NovelQA: A Benchmark for Long-Range Novel Question Answering

- **作者与年份**：2024
- **引用数**：待核实
- **所解问题**：现有 QA benchmark 的文档长度远短于一本真实小说，无法评测模型对"整本书"的理解
- **方法本质**：以真实英文小说为素材，构造需要跨章节、跨情节关联才能回答的问题集。区分"单段可答"和"全书才可答"两类
- **与 BookScope 的关联**：和 BookScope 的核心使用场景（对一本书提问）同构。可以把 NovelQA 的问题分类框架（事实/关系/情节推理/主题）直接套用到中文书
- **拟尝试**：照 NovelQA 的问题分类，对明朝系列第一册手工造 30 条标准问题，作为 r1 的 golden set
- **实验日期**：尚未验证（待 r1 首版落地后跑对应实验）
- **实验结果**：尚未验证

### Paper · The NarrativeQA Reading Comprehension Challenge

- **作者与年份**：Kočiský et al., 2017
- **引用数**：待核实（经典，高引）
- **所解问题**：早期 QA 数据集（SQuAD 等）答案通常直接出现在文本中，模型可以靠 pattern match。叙事类问题需要真正的理解
- **方法本质**：以书籍和电影剧本为源，答案不直接出现在文本中，需要通过情节推理得出。问题由读者在只看过书的情况下写出，答案也是自由文本
- **与 BookScope 的关联**：它提出的"答案不在文本字面"的评测思路，对 BookScope 非常关键——读者问"这本书想表达什么"时，答案也不在任何一个 chunk 里。该类问题可能永远不能靠 retrieve-then-read 解决
- **拟尝试**：把 BookScope 的问题类型显式拆成"字面可答 / 情节推理 / 主题抽象"三类，分别统计 r1 的表现
- **实验日期**：尚未验证（待 r1 首版落地后跑对应实验）
- **实验结果**：尚未验证

### Paper · QuALITY: Question Answering with Long Input Texts, Yes!

- **作者与年份**：Pang et al., 2022
- **引用数**：待核实
- **所解问题**：多选题 QA 数据集大多短文本，长文本多选 QA 缺乏
- **方法本质**：平均 5000 词英文短篇叙事 + 专家撰写的多选题，题目设计确保必须读全文才能答。引入"时间受限 vs 无时间限制"两种标注对照
- **与 BookScope 的关联**：多选题评测比自由文本评测**可自动化**，这对 BookScope 建立回归测试很关键。QuALITY 的出题规范（确保必须读全文）可以学
- **拟尝试**：把 BookScope 的 golden set 里选 10 条改造成多选题，用作日常自动回归
- **实验日期**：尚未验证（待 r1 首版落地后跑对应实验）
- **实验结果**：尚未验证

### Paper · BookSum: A Collection of Datasets for Long-form Narrative Summarization

- **作者与年份**：Kryscinski et al., 2021
- **引用数**：待核实
- **所解问题**：长文本摘要数据集的"文档长度"和"摘要抽象度"都不够。书籍级摘要基本没有
- **方法本质**：收集公有领域书籍 + 章节级人工摘要（部分来自 SparkNotes 等学习资料）。提供段落 / 章节 / 全书三个粒度的摘要评测
- **与 BookScope 的关联**：BookScope 的"章节摘要 + 全书总结"输出本质上就是 BookSum 任务。借鉴其评测方法（尤其 ROUGE 之外的事实一致性度量）可用于本地输出质检
- **拟尝试**：借用 BookSum 的章节摘要评测指标框架，对 r1 生成的章节摘要做事实一致性打分
- **实验日期**：尚未验证（待 r1 首版落地后跑对应实验）
- **实验结果**：尚未验证

---

## 主线四 · Grounded Generation 与 Citation

### Paper · ALCE: Enabling Large Language Models to Generate Text with Citations

- **作者与年份**：Gao et al., 2023
- **引用数**：待核实
- **所解问题**：LLM 生成带引用的文本时，引用经常与生成内容对不上（引用了错误的源，或者生成的断言其实没有任何源支持）
- **方法本质**：提出 citation recall（生成的每个断言是否至少有一个源支持）和 citation precision（引用的每个源是否真的支持断言）两个核心指标，并系统对比不同 prompting / retrieval / fine-tuning 策略
- **与 BookScope 的关联**：BookScope 的核心交付物之一是"每个断言都可以回溯到原文的哪一段"。ALCE 的 recall/precision 双指标是评测 citation 质量的直接参考
- **拟尝试**：r1 的每个生成答案强制输出 `[chunk_id]` 引用，按 ALCE 的 recall/precision 两个维度量化
- **实验日期**：尚未验证（待 r1 首版落地后跑对应实验）
- **实验结果**：尚未验证

### Paper · RARR: Researching and Revising What Language Models Say, Using Language Models

- **作者与年份**：Gao et al., 2023
- **引用数**：待核实
- **所解问题**：LLM 先说话后引用——往往是先生成断言，再硬找证据支撑，结果引用和内容脱节
- **方法本质**：生成后对每个断言做 fact-check——用检索获取证据，和生成内容比对，发现矛盾时修改原文而不是硬塞引用。流程：Research → Revise → 保留原结构
- **与 BookScope 的关联**：BookScope 的风险场景——读者问一个书里没明说的结论，LLM 编造了一个看起来合理的断言并塞了个不相关的 chunk_id 作为引用。RARR 的"后置修正"流程可以作为 agent loop 最后一步的质量闸
- **拟尝试**：在 r1 agent loop 的收尾加一个 verify step，对每个生成句做一次独立 fact-check
- **实验日期**：尚未验证（待 r1 首版落地后跑对应实验）
- **实验结果**：尚未验证

---

## r1 首版优先参考判断

r1 首版的核心路径是"agent loop + retrieval + grounded generation"，这条主路径上最直接可用的 paper 有三篇：

**最优先三篇**：
1. **Self-RAG** — agent loop 的循环结构（retrieve / relevant / supported 三个反思点）最能直接搬用。r1 要做的第一件事就是把这三个判断显式写成 agent 的三个 step
2. **ALCE** — BookScope 的价值承诺之一就是"每句话可回溯原文"，citation recall/precision 是验证这个承诺是否兑现的最直接指标。应该从第一天就上这套评测
3. **Lost in the Middle** — 不是方法论，是**警示**：哪怕用了 128k context LLM，中部信息也用不好。这直接支持了 BookScope 必须走 retrieval、不能走"整本书塞进 context"的路线，也指导了检索结果的拼接顺序

**次优先两篇**：
4. **CRAG** — 检索质量低时的降级策略。r1 第一版可以简化实现，只做"全低分时降级到章节摘要"就够
5. **CLongEval** — 中文长文本评测方法论，r1 内部 golden set 构造需要参考

**后续（r2 或更晚）**：
- **RAPTOR / HippoRAG** — 多层/图式检索，r1 先把单层搞扎实
- **NovelQA / NarrativeQA / QuALITY / BookSum** — 评测端的参考，r1 golden set 成型后深入
- **RULER / RARR** — r1 稳定运行后做量化分析和后置校验时再回来

优先级排序的逻辑：**r1 首版必须验证的命题是"agent loop 能否做出 grounded 的回答"**，所以选的是能直接指导 loop 结构（Self-RAG）、能量化成败（ALCE）、能避免路径错误（Lost in the Middle）的三篇。其他 paper 都是 r1 跑通后的优化资源。

---

## 本文档的更新机制

- 本文档编号 `001`，标记为 `v1` 初稿
- 本文档的**完成定义**：所有 paper 的"实验日期 / 实验结果"字段都填入真实实验记录。当前 v1 阶段这两个字段全部是占位符，因此本文档严格意义上**不是**一份完成的二层研究笔记，它是研究笔记的前置索引
- 后续每次二层研究（在 r1 开发中遇到真难题、真正回来精读某篇 paper 时）应该：
  - 在对应主线下补充新 paper（如在市面上发现更新的 agentic RAG 变体）
  - 把对应条目的"拟尝试"更新为"已跑 / 结果 X"，同时填入"实验日期"和"实验结果"
  - 版本号递进：v1 → v2 → v3
- 如果某条主线的 paper 积累成体系（例如单独针对"citation 质量评测"凑出了 5+ 篇），抽出成 `002-citation-quality.md`、`003-xxx.md` 等独立文件，本文档保留索引
- 不强制综述完整性——这份文档是弹药库的索引，不是领域综述。只收录对 BookScope 具体难题可能适用的 paper，不追求"agentic RAG 全景"
- 参考精读的 paper 原始 PDF / HTML 链接本文档不内嵌（避免链接失效），作者需要精读时按标题在 Semantic Scholar / arXiv 重新检索

---

*本文档 v1 起草：2026-04-20，AI 基于 knowledge cutoff 前认知。本文档一切"引用数"字段保留"待核实"，正式精读某篇时再补。*
