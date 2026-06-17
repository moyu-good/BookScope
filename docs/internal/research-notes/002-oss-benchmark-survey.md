# 研究笔记 002 · 高星开源项目对标调研

**日期**：2026-06-10
**调研者**：RE（联网调研）
**目的**：为 BookScope 的设计缺口修补寻找已验证的工程做法，避免自己重新发明。
**配套文档**：`docs/internal/design/2026-06-10-design-gap-review.md`（缺口清单与工作包）

---

## 一、RAG 引擎工程实践

### dsRAG（D-Star-AI，~2k stars）

最贴 BookScope 需求的小而精项目，三个可搬做法：

1. **语义分段（semantic sectioning）**：给文档标行号，让 LLM 找每个语义连贯段的起止行，再生成描述性标题。比固定窗口更贴章节结构。
2. **AutoContext 上下文头**：把"文档级 + 节级"上下文（书名、章节标题、一句话概要）拼到每个 chunk 前**再做 embedding**——向量真正带上位置语义。
3. **RSE（Relevant Segment Extraction）**：检索后把相邻相关 chunk 拼回连续原文段，不给碎片。

出处：https://github.com/D-Star-AI/dsRAG · https://d-star-ai.github.io/dsRAG/concepts/overview/

### Anthropic Contextual Retrieval（官方工程文章）

与 AutoContext 同思路但有实测数据：每个 chunk 用 LLM 生成 50-100 token 上下文说明，prepend 后同时进 embedding **和 BM25 索引**。top-20 检索失败率降 49%，加 reranker 降 67%。用 prompt caching 后预处理成本约 $1.02/百万 token。BookScope 已是 FAISS+BM25 混合检索，接近即插即用。

出处：https://www.anthropic.com/news/contextual-retrieval

### microsoft/graphrag（~30k stars）

整体架构太重（实体图谱对小说成本极高，BookScope 不走这条路的决策有了对照依据），两点可搬：

- **text unit 双向溯源表**：chunk 与源文档间保留双向关联，专门服务 provenance
- **prepend_metadata**：导入时指定元数据列，自动以 `key: value` 复制进每个 chunk 开头

出处：https://microsoft.github.io/graphrag/index/default_dataflow/

### infiniflow/ragflow（~60k stars）

**分块可视化 + 人工干预**：上传后展示切块结果，允许人检查修正再进检索。对作者每周自试场景是低成本高回报功能。

出处：https://github.com/infiniflow/ragflow

---

## 二、citation / attribution 机制

### Anthropic Citations API

目前唯一在 API 层面**保证引文有效**的方案：文档按句子切块进 context，返回 `cited_text` 带字符索引区间，引文保证指向所提供文档的真实位置；且 `cited_text` 不计 output token。anthropic adapter 可直接接；对 DeepSeek / minimax 照这个协议自己实现校验层。

出处：https://platform.claude.com/docs/en/build-with-claude/citations

### LlamaIndex CitationQueryEngine（llama_index ~40k stars）

**编号引用 + 程序化核对**模式：检索到的 node 切成 512-token 引用单元，编号 Source 1..N 给 LLM，要求用 `[1]` 形式引用；回答后从 source_nodes 程序化映射回原文。核心实现一个文件。

BookScope 在此之上加一层：**LLM 给的引文文本与编号 chunk 做模糊匹配，匹配不上的 citation 标 unverified，不展示给用户**——"不靠 LLM 自觉"的最后一道闸。

出处：https://github.com/run-llama/llama_index/blob/main/llama-index-core/llama_index/core/query_engine/citation_query_engine.py

### RAGAS faithfulness（~10k stars）

可整个搬进 reviewer 评分回路：① LLM 把答案拆成原子 claim；② 逐条问"这条能否从检索到的 context 推出"；③ 得分 = 被支持的 claim 占比。两个注意点：judge 必须用强模型且**不能是生成模型自己**（呼应 minimax reviewer 全空拒答的教训）；RAGAS 还集成 Vectara HHEM-2.1-Open 开源幻觉分类器交叉验证（小模型 CPU 可跑，符合禁 GPU 约束）。

出处：https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/faithfulness/ · https://arxiv.org/pdf/2309.15217

---

## 三、agent loop 工程

### Anthropic 多代理研究系统（工程文章）

- **并行是延迟的最大杠杆**：单步并发 3+ 工具，复杂查询总耗时降 90%
- **预算规则写进 system prompt**：明确"简单事实题 3-10 次工具调用，对比题 10-15 次"，比硬 max_steps 截断体验好
- **上下文将满时把计划写到外部 memory**，再起新上下文接续
- **trace 看决策模式不看内容**：监控工具调用序列和交互结构，系统性诊断失败

出处：https://www.anthropic.com/engineering/multi-agent-research-system

### huggingface/smolagents（~20k stars）

- `max_steps` + `planning_interval=N`：每 N 步强制插入规划步，让转圈的 agent 重新审视目标——比数步数截断更能救回不收敛循环
- **step_callbacks 裁剪旧观察**：旧轮次检索到的长 chunk 在 N 步后压成一行摘要 + chunk id，要引用时凭 id 重拉
- `agent.memory.steps` 结构化 + `agent.replay()` 重放调试

出处：https://huggingface.co/docs/smolagents/tutorials/memory

### openai/swarm（已归档）

handoff 模式对单 agent 三工具的 BookScope 用处不大，不建议投入。

---

## 四、LLM 评估管线

### promptfoo（~10k stars，MIT）

- **声明式 YAML 测试配置**：prompt × provider × test case 矩阵，确定性断言与模型评分断言混用。v1~v3.5 并列保留策略可直接套这个格式管理
- **GitHub Action 自动回归**：PR 改 prompt 文件自动跑 before/after 对比，结果贴 PR comment

出处：https://github.com/promptfoo/promptfoo

### deepeval（~10k stars）

pytest 原生集成（`assert_test(test_case, [metric])`），BookScope 已有 pytest 基建，接入成本低；G-Eval 支持自定义 criteria + 思维链 judge。

出处：https://github.com/confident-ai/deepeval

### judge 校准（业界通行做法）

**人机一致率追踪**：积累人工标注（作者每周 dogfood 的不满意点是现成标注源），算 judge 评分与人工标签一致率，75-90% 视为可放量；不达标用人工纠正样本做 few-shot 校准。Anthropic 的 judge 设计：**单次 LLM 调用输出五项 0-1 分 + 一个 pass/fail**，比多次调用便宜且稳。

出处：https://www.evidentlyai.com/blog/how-to-align-llm-judge-with-human-labels

---

## 五、书籍 / 长文本特化项目

**结论：没有找到真正做"百万字整本书深度对话"的高星项目，这块是空白——正是 BookScope 的差异化所在**（可直接写进 case-study 定位论证）。

- **khoj**（~30k stars）：通用语义检索，无单本超长书的章节结构 / 角色追踪特化
- **anything-llm**（~50k stars）：大文档是公开痛点（issue #3033）；可搬的是产品化包装——workspace 隔离、文档管理 UI
- **stanford-oval/storm**（~25k stars）：方向相反（写文章），但**多视角提问**可搬——模拟不同立场读者对同一主题发问，用来生成评估题集和 probe 题，规避"常识题不证原文记忆"的坑

---

## 六、最值得搬的 10 件事（按性价比排序）

1. **Contextual chunk header**（dsRAG + Anthropic）：chunk 前拼"书名 + 章节 + 一句话前情"再进双索引。只改 ingest 一处，检索失败率近半下降有实证
2. **工具调用并行已落地，prompt 配套确认生效**（v3.5 内容已写，但见设计评审 P0——生产从没加载过 v3.5）
3. **citation 程序化校验**（LlamaIndex 编号模式）：引文与 chunk 模糊匹配，不匹配标 unverified
4. **RAGAS faithfulness 拆 claim 校验**进 reviewer：定位哪句话没根据
5. **promptfoo 式 prompt 回归 CI**：OSS 发布前必备质量闸门
6. **预算规则写进 system prompt**：简单题 3-10 次，复杂题放宽
7. **judge 人机一致率校准**：作者 dogfood 记录当标注集，75-90% 合格线
8. **step 级上下文裁剪**（smolagents 模式）：多轮对话不爆上下文的现成模式
9. **golden retrieval set + recall@k**：检索和生成分开归因
10. **分块可视化抽查**（RAGFlow）：服务作者每周自试，工作量一个页面
