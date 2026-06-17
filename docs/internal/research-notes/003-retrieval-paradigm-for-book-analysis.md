# 研究笔记 003 · 检索范式调研——embedding 不是书籍分析的全部

**日期**：2026-06-12
**触发**：本地 embedding 可行性 probe 翻车（小模型语义反退）+ 作者问"书籍分析用 embedding 对不对、有没有更好的办法 / 更好的 embedding"
**方法**：联网查 2025-2026 最新论文 / 对比 + 结合本项目实测。问题触发式研究（NORTH_STAR）。

---

## 一句话结论

"embedding 对不对"问错了——**书籍分析不是一种检索问题，是三种，embedding 只擅长其中一种（语义查找，且要强模型）**。BookScope 的差异化（作家诊断、关系图）恰恰落在 embedding 不擅长的另外两种上。下一步不该在 embedding 上加注，该按"书大小 + 问题类型"选检索模式，并**优先 probe"长上下文 + 缓存"**——它一箭三雕，顺带解决检索 miss、全局题、和 ≥90% 缓存目标。

---

## 一、书籍分析是三类问题，不是一类

| 类型 | 例子 | embedding 行不行 | 该用什么 |
|---|---|---|---|
| **① 语义查找** | "书里哪讲了 X" | 行（**要强模型**）| 强 embedding / BM25+agent 改写 |
| **② 结构 / 关系 / 多跳** | 人物关系、概念勾连、伏笔→回收因果链 | 不行（相似 ≠ 关系）| 图（GraphRAG / NodeRAG）|
| **③ 全局 / 聚合** | 节奏曲线、全书主题、整体结构 | 根本不行（没有单一段落能答）| 层级摘要树（RAPTOR）/ 长上下文 |

②③ 正是 BookScope 的差异化所在，而 embedding 对它俩无能为力。本地 embedding probe 翻车，一半是模型太弱、一半是**拿 embedding 去干它本来就不擅长的活**。

---

## 二、长上下文 + 缓存（最该重视的一条）

2026 研究共识（[Long Context vs RAG 评测](https://arxiv.org/abs/2501.01880)、[When Retrieval Succeeds and Fails](https://arxiv.org/pdf/2510.09106)）：**书籍级长文档推理，长上下文（整本进 context 直接读）常胜 RAG**——前提模型够强（强模型受益大，弱模型才更依赖检索）。代价：lost-in-the-middle、注意力二次方算力成本。

对 BookScope **三线合一**：

- **检索质量**：没有"没捞到对的段"这种 miss；②③ 全局 / 关系题天然能答。
- **≥90% 缓存目标**：长上下文 + 前缀缓存 = 钉书复用、越问越省（即上次成本讨论的"钉稳定上下文"，见 `WP-agent-token-budget`）。
- **边界**：塞得进 1M context 的书走这条（普通书几十万 token 塞得下）；680 万字超大书塞不下，退回检索。

---

## 三、结构化检索（②类，对应关系图 + 伏笔）

[GraphRAG / NodeRAG](https://arxiv.org/pdf/2504.11544)：LLM 抽实体 + 关系建图，检索沿关系多跳——做"关系 / 多跳"问题，纯 chunk 相似检索做不到。正对应作者要的人物关系图 / 概念图 + 伏笔因果链。按 BookScope"查询时 + 原文证据"做，不做 r0 静态预算展示。RAPTOR（层级摘要树）服务 ③ 全局题。

---

## 四、更强的 embedding（只帮 ①）

强模型：[Qwen3-Embedding](https://github.com/QwenLM/Qwen3-Embedding)（MTEB 多语第一 70.58）、bge-m3（568M，中文开源标杆，dense+sparse+多向量）。但强 = 重：Qwen3-8B 巨大、bge-m3 ~2.2GB，CPU 慢或要 API/GPU——**撞回"强 = 重 / 要第二把 key"那堵墙**。且再强也只补 ①，碰不了 ②③。bge-m3 via SiliconFlow 是务实的强 embedding 路（可选档，不当默认）。参考 [开源 embedding 2026 指南](https://www.bentoml.com/blog/a-guide-to-open-source-embedding-models)。

---

## 五、本地小 embedding 负结果（实测存档）

`bge-small-zh-v1.5`（90MB、512 维）在 kuicheng（4315 chunk）实测：

- 建索引 **473s（~8min，110ms/chunk）**。
- recall@5 分型：**语义 0.567→0.517（退步）**、位置 0.000→0.375、角色 0.292→0.167、整体 0.380→0.407。
- 整体 +0.027 是假象（全靠位置题，而位置题该走章节路由不该走检索）；真该补的语义反而退。
- **判定 NO-GO**：小模型太弱，hybrid 融合反而稀释 BM25 本来对的语义结果。数据 `retrieval-eval-kuicheng-hybrid-2026-06-12.json`。
- 印证 ADR-006 的精神，比"CPU 慢"更深一层：**CPU 跑得动的小模型，质量不够**。

---

## 六、对 BookScope 的含义

**最终形态 = 按"书大小 + 问题类型"选检索模式的路由**：塞得下 → 长上下文 + 缓存；关系 / 结构 → 图；纯语义查找 → 强 embedding（可选 SiliconFlow）或 BM25 + agent 改写。agent loop 已经在路由，扩它就行。

下一步排序：

1. **长上下文 + 缓存可行性 probe**（优先，研究前沿 + 撞 ≥90% 缓存目标）：拿能塞下的书实测，全书进 context 的答题质量 vs 当前 RAG + 缓存命中率。
2. 结构化检索接上关系图 / 伏笔功能（②类）。
3. 强 embedding 作可选档，不当无钥匙默认。

---

## Sources

- [Long Context vs RAG: An Evaluation and Revisits (arXiv 2501.01880)](https://arxiv.org/abs/2501.01880)
- [When Retrieval Succeeds and Fails: Rethinking RAG (arXiv 2510.09106)](https://arxiv.org/pdf/2510.09106)
- [LongRAG (arXiv 2410.18050)](https://arxiv.org/pdf/2410.18050)
- [NodeRAG: Graph-based RAG with Heterogeneous Nodes (arXiv 2504.11544)](https://arxiv.org/pdf/2504.11544)
- [Qwen3-Embedding](https://github.com/QwenLM/Qwen3-Embedding) · [开源 embedding 2026 指南](https://www.bentoml.com/blog/a-guide-to-open-source-embedding-models)
