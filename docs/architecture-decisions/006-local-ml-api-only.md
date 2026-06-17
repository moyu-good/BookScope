# ADR-006：r1 本地 ML 模型推理全部 API 化

## Status

**作者 2026-04-24 口头批准**（副管理起草 · 同日定稿）

- 代际：r1-agent-loop
- 起草：副管理
- 创建日期：2026-04-24
- 最后更新：2026-04-24
- 决策：**本地 cross-encoder / sentence-transformers 全部下线；reranker 按 embedding 的模式 API 化；embedding 保留 Tier 1 SiliconFlow API**

## Context / 背景

2026-04-24 第 16 轮（r1 首次端到端真 API 跑通）暴露了一条硬约束违规路径：

### 现场数据

- smoke test：`test明朝那些事儿.epub`（32164 字，1069 chunk），真调 astron-code-latest 回答"这本书里主要有哪几个角色？"
- 前四轮均超时或卡死；最后一轮通过 `enable_rerank=False` hack 熔断后 **82.3 秒**出答案（4 iterations / 6 tool 调用 / 56k input + 1.3k output token / 7 条 citation）
- 第三轮的 trace 表明：agent 只调了 1 次 `search_chunks`，本地 tool 执行耗时 **892 秒**；astron 本身只消耗 1928 input / 34 output token
- 单步 benchmark：`SessionVectorStore.search` 在 1069 chunk 的真 epub 上单次耗时 **209–393 秒**。构造（ctor）只 6.65s，纯 BM25 score 计算毫秒级——耗时全在 `_maybe_rerank` 里的 cross-encoder CPU 推理

### 违规的两条硬约束

- **禁止 GPU 依赖**（`CLAUDE.md` + `docs/internal/NORTH_STAR.md`）：`CrossEncoder` 是 transformer 重模型，CPU 上 45 条 (query, chunk) pair 推理要数百秒；实际使用隐含 GPU 需求。本项目 Web 产品必须在普通用户 CPU 上可跑，任何隐含 GPU 的路径一律否决
- **10 秒读取目标**（memory `feedback_performance_target.md`）：单次 `search_chunks` 200+ 秒完全不可用

### 本地重模型依赖清单（审计结果）

| 文件 | 依赖 | 模型 | 性质 |
|------|------|------|------|
| `bookscope/store/vector_store.py` L104–110 | `_get_reranker()` | `CrossEncoder(_RERANKER_NAME)` | **违规**，本次熔断对象 |
| `bookscope/store/embedding_provider.py` L146–148 | Tier 2 `SentenceTransformer(_QWEN3_MODEL)` | Qwen3-Embedding-0.6B（1.2 GB） | 本地 fallback，同违规 |
| `bookscope/store/embedding_provider.py` L192–194 | Tier 3 `SentenceTransformer(_BGE_M3_MODEL)` | BAAI/bge-m3（2.2 GB） | 本地 fallback，同违规 |

### 已有 API-first 资产

`embedding_provider.py` 顶层定义了 `EmbeddingProvider` Protocol（与 ADR-003 `LLMClient` 同模式），且 Tier 1 默认就是 SiliconFlow API。这份基础设施可以直接复用给 reranker——只是 reranker 漏了一口没走 Protocol。

## Decision

**作者 2026-04-24 口头明令："全部 API 化"**。转译为工程决策：

### D-1：删除 reranker 本地实现

- 删 `vector_store.py` 的 `_get_reranker()` / `_reranker` / `_RERANKER_NAME` / `_RERANKER_CHAR_LIMIT` 以及 `rerank()` 方法与 `_maybe_rerank()` 调用点
- `sentence_transformers.CrossEncoder` 的 lazy import 一并清除
- 影响面：`search()` 的 `enable_rerank` 参数及默认行为一并下线；保留 `search_bm25 + search_vector + _rrf_fusion` 的 hybrid 主路径

### D-2：如需 rerank，走新 Protocol + API adapter

- 新增 `bookscope/store/reranker_provider.py`：`RerankerProvider` Protocol（`rerank(query, candidates, top_k) -> list[tuple[int, float]]`）
- 实现 `SiliconFlowRerankerProvider`：走 SiliconFlow `/v1/rerank` endpoint（BGE-reranker-v2-m3 等），BYOK
- 选型、启用与否、默认 top_k：**本 ADR 不指定**；ADR-007（若起草）再定。**第 17 轮实施先只做 D-1 下线，rerank 能力完全移除**——`search` 直接返回 BM25/vector fused 结果

### D-3：删除 embedding 本地 Tier 2 / Tier 3

- 删 `embedding_provider.py` 里 `SentenceTransformer` 相关全部代码（Tier 2 Qwen3 + Tier 3 BGE-M3 本地实现）
- 保留 Tier 1 `SiliconFlowEmbeddingProvider`（已是 API）
- `get_embedding_provider()` 简化为：有 `SILICONFLOW_API_KEY` → 返回 provider；没有 → 返回 `None`（BM25-only 降级）
- 影响面：`BOOKSCOPE_EMBEDDING_PROVIDER` 环境变量相关分支简化

### D-4：依赖清理

- `pyproject.toml`：`sentence-transformers` 从必需依赖移除（如存在）；`torch` / `transformers` 一并审查
- 本项目**禁止**在核心依赖里出现 `torch` / `transformers` / `sentence-transformers` / `sentencepiece` 等 ML 重库。测试与开发工具可以按需 pin 到 `[dev]` extras，但 runtime 路径不得触达

### D-5：API 化边界

明确**不在本 ADR 范围**的本地计算：

- BM25（纯算法，`rank_bm25` 库，无 ML 模型）——保留
- jieba 分词（字典查表）——保留
- FAISS（纯向量检索库，无 ML 推理）——保留
- epub 解析 / chunker / KG 装配——保留

**API 化** = **本地 ML 模型推理必须全部通过 API 完成**，不是把所有计算移到远端。

## Consequences

### 好

- 硬约束对齐：再无 GPU 隐含依赖，再无 200+ 秒的 tool 调用
- 依赖瘦身：`sentence-transformers` + `torch`（几 GB）全部从运行时消失
- 一致性：reranker 与 embedding / LLM 走同一 provider-adapter 模式，架构概念收敛
- 冷启动加速：不再 lazy-load 2 GB 模型

### 代价

- **离线可用性下降**：SiliconFlow API 宕机或 key 配额耗尽时 embedding 不可用（降级到 BM25-only，可接受）
- **rerank 能力暂时归零**：D-2 把 rerank 留给 ADR-007，本轮 `search()` 是 fused 结果直出。在高召回场景下精度略降——但 82 秒成功案例表明 agent 自己能通过多轮 tool use 补偿
- **对 provider 的依赖加深**：SiliconFlow 若倒闭或换 pricing 模型，需要换 provider。风险通过 Protocol + 多 adapter 形式对冲（未来可加 volcengine / 自建 vllm）

### 撤回条件

如果发生以下任一，重开本 ADR：

- 真实场景里 "BM25+vector fused without rerank" 的 recall@10 在实验 001 rubric 上持续低于目标阈值
- 作者本人小说草稿跑得显著不准，诊断后发现"缺 rerank"是首要瓶颈
- 合规原因要求全本地运行（私密手稿场景）

## 实施计划（第 17 轮）

**本 ADR 不在第 16 轮实施**，仅登记决策与熔断状态。第 17 轮专门执行：

1. D-3 先（embedding Tier 2/3 删除，影响面窄）
2. D-1（reranker 删除 + `vector_store.py` 的 `search` 简化）
3. D-4（`pyproject.toml` 清理）
4. 单测相应调整（删掉 rerank 相关测试、embedding 本地 Tier 测试）
5. 作者确认 SiliconFlow API key 状态，如无则 r1 默认 BM25-only 继续跑

D-2（`RerankerProvider` Protocol + SiliconFlow adapter）**不作为** 第 17 轮必做项；作为 ADR-007 候选。

## Related

- `CLAUDE.md` 技术栈："禁止 GPU 依赖"硬约束
- `docs/internal/NORTH_STAR.md` 不变量
- memory `feedback_no_gpu.md`
- memory `feedback_performance_target.md`（10 秒读取）
- ADR-003（provider adapter layer，embedding / LLM 已走此模式）
- `scripts/smoke_test_r1.py` 第 16 轮真实验数据
- `bookscope/store/vector_store.py` + `bookscope/store/embedding_provider.py`

## 作者签字

**作者 2026-04-24 口头批准**（session 内"全部 API 化"指令）。副管理转译为本 ADR 的 D-1 / D-2 / D-3 / D-4 / D-5 五条。第 17 轮按"实施计划"节推进。
