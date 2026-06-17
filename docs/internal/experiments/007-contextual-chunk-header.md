# exp-007 · contextual chunk header 对检索质量的提升（设计）

**日期**：2026-06-10
**状态**：设计过闸，实跑进行中
**上游**：WP2 主体；研究笔记 002（Anthropic Contextual Retrieval 实测 top-20 失败率降 49%；dsRAG AutoContext）；golden set 基线（commit `05f0755`）

## 一、目的与假设

BM25-only 基线已量化三个短板：位置找系统性差（kuicheng r@5=0）、大书整体糊（kuicheng r@10=0.426）、改述型 query 不命中。假设：**每个 chunk 前拼"书名 + 章节 + 一句话前情"再进 BM25 索引**，能把章节词汇和上下文语义注入 chunk 表示，显著改善位置找与大书检索。

**可证伪判定**：anshi 与 kuicheng 两本书，recall@10 提升 < 5 个百分点 → 假设不成立，不进产品；≥ 10 个百分点且位置找显著改善 → 立 WP 进产品 ingest。中间地带 → 看成本（header 生成是一次性 ingest 成本）再判。

## 二、单变量纪律

- 对照组：现有 BM25-only 基线（retrieval-eval-{book}-bm25_only-2026-06-10.json）
- 实验组：同 chunker、同 golden set、同 BM25——唯一变量是 chunk 文本前是否拼 header
- 不引入 embedding（SiliconFlow key 缺位；混入会破坏单变量）

## 三、方法

1. header 生成：deepseek-chat，逐 chunk 输入（chunk 文本 + 书名 + 真章号 + 前一 chunk 末 200 字），输出 ≤ 60 字中文 header（"《书》第 N 章：一句话此处情节/论点"）；并发 10；L2 LLM 缓存自然去重
2. 书选 anshi（267 chunks，小书对照）+ kuicheng（4315 chunks，最差 case）；约 4600 次调用，DeepSeek 成本可忽略（作者已批）
3. 索引重建：header + "\n" + chunk_text 进 BM25；golden set expected_chunk_indices 不变（chunk 切分未动）
4. 跑 eval_retrieval 同款指标（recall@5/10、MRR、分题型），脚本 `scripts/exp007_contextual_header.py` 自含（不改产品代码与 eval_retrieval.py）

## 四、产出

- `docs/internal/experiments/data/exp007-headers-{book}.json`（header 全量，含生成 prompt 版本）
- `docs/internal/experiments/data/exp007-eval-{book}.json` + 本文档第五节实跑结果与判定

## 五、实跑结果与判定（2026-06-10 anshi 臂 · 2026-06-11 kuicheng 臂）

> 执行备注：原 RE 代理跑完 anshi 臂后 session 中断，kuicheng 臂由主 Claude 用同一脚本接管重跑（单变量条件不变）。header 生成零失败（anshi 267 + kuicheng 4315 全部成功）。

### 5.1 主结果

| 指标 | anshi 对照 | anshi 实验 | Δ | kuicheng 对照 | kuicheng 实验 | Δ |
|---|---|---|---|---|---|---|
| recall@5 | 0.662 | 0.636 | **−2.6pp** | 0.380 | 0.407 | +2.8pp |
| recall@10 | 0.785 | 0.772 | −1.3pp | 0.426 | 0.500 | **+7.4pp** |
| MRR | 0.693 | 0.702 | +0.9pp | 0.397 | 0.461 | +6.4pp |

kuicheng 分题型（r@10）：positional 0.125 → 0.375（**+25pp，假设的核心受益点兑现**）；character 0.375 → 0.458；semantic 0.567 → 0.567（零变化）。

### 5.2 判定：不进产品（按第一节可证伪规则的中间地带成本判）

- anshi（小书）：零提升甚至 r@5 略负——小书的 BM25 本来就能定位，header 反而稀释了 chunk 词频
- kuicheng（大书）：r@10 +7.4pp 落在 5~10pp 中间地带，规则是"看成本"。成本端：每本书 ingest 时全量 LLM 调用（kuicheng 4315 次，本次实测约 25 分钟）——与"整本书 10 秒内读取"的性能硬目标直接对抗，且收益集中在 positional 一类（4 条 query）
- **结论：现阶段不进产品 ingest。** 位置找的真问题（"第 N 章讲了什么"该走 get_chapter_range 不该走 BM25）更适合在 fast_path 路由层解决——agent 已有按章拉原文的 tool，检索层硬补章节词汇是绕远路
- 复评条件：将来接入 embedding（hybrid 检索）时，contextual header 对向量表示的增益可能远大于对 BM25 的增益（Anthropic 原文的 49% 降失败率正是 embedding 场景）——届时用本实验同款脚本零改动重测

### 5.3 三句诚实观察

1. 受益最大的是 positional（+25pp）——但它恰好是"不该用检索解决"的题型，提升的含金量打折
2. semantic 一类零变化——中文 BM25 + jieba 的词汇鸿沟没有被 60 字 header 弥合，改述型 query 还是要靠 embedding
3. Anthropic 的实证（top-20 失败率降 49%）不能直接移植到"中文 + BM25-only + 整本书"场景——发表级结论需要本地复测，又一条"测量仪器先于结论"
