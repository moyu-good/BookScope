# WP-语义检索（本地 embedding · 不要第二把 key）设计草稿

> **结果（2026-06-12）：本地小 embedding 已实测否决** —— bge-small-zh 在 kuicheng 上语义 recall 反退（0.567→0.517）、680万字建索引 8min。检索方向重框为"按书大小 + 问题类型选模式 + 长上下文/缓存优先"，见 `docs/internal/research-notes/003-retrieval-paradigm-for-book-analysis.md`。本稿留作设计→实测→否决的研究轨迹（案例研究素材）。
>
> **性质：设计草稿（已被 research-notes/003 取代方向）。**

**日期**：2026-06-12
**上游**：ROADMAP 地基层「语义检索转正」+ 作者反馈"用户不可能专门准备两个 api"
**方法论锚**：戴明·先量后改 —— ADR-006 已否过本地 embedding，**不假设它行、也不假设它不行**，先量轻量新方案再决定；叠影响分析先行（改默认检索路径 + 改 ADR 都是有影响的改动）。

---

## 1. 目的

BM25 对不上语义（"盐铁会议" vs 原文"《盐铁论》"、隐伏笔），检索捞不到对的原文 → 答案地基塌。向量检索补这个短板。

- **约束（作者定）**：不能逼用户配第二把 key（一把 DeepSeek key 够用），不破"禁 GPU"。
- **受益者**：所有作家诊断（尤其伏笔追踪主轴的硬案例）+ 任何语义型提问的用户。
- **成功标准**：golden set 的 semantic 类 recall@5 相对 BM25-only 涨 + 零第二 key + 不破 GPU + 建索引耗时可接受。

---

## 2. 必须正视的障碍（设计先行闸门抓出来的）

提"本地 CPU embedding"时没核 ADR-006。读代码发现：**ADR-006 已明确否决本地 embedding**——理由是 `sentence_transformers` 的 1-2GB 模型隐含 GPU 依赖、"CPU 上首次 encode 数千 chunk 不可接受"（`embedding_provider.py` 头注 + ADR-006）。

所以"本地 embedding"不是现成可用，**是要推翻一条已生效 ADR**。

**但** ADR-006 的数据是针对**重模型**（sentence_transformers 1-2GB）。这两年有更轻的路它没评估过：

- **fastembed**（Qdrant，ONNX runtime）：跑 bge-small 级小模型（~100MB）纯 CPU，比 sentence_transformers 快一个量级、不拉 GPU。
- ONNX 量化小模型（bge-small-zh-v1.5 ~95MB 等）。

这条路 **可能** 改写 ADR-006 的结论——但没测过不算数。这就是本 WP 要先量的东西。

---

## 3. 方案概要（先量后改）

1. **可行性 probe 先行**：加候选 `LocalEmbeddingProvider`（fastembed / ONNX 小模型），实现现有 `EmbeddingProvider` Protocol（`name`/`dim`/`encode_documents`/`encode_queries`，drop-in）。拿 kuicheng（4315 chunk）实测三数：① CPU 建索引耗时 + 内存峰值 ② 依赖体量（wheel 大小、装得动吗、确认不拉 CUDA）③ golden set recall@5（vs BM25-only、vs SiliconFlow 三方对照）。**建索引这步丢后台跑**（正好示范无 subagent 的并行打法）。
2. **决策闸**：
   - 耗时可接受（目标：大书建索引几分钟级，不是 ADR-006 说的"不可接受"）+ recall 涨 + 不破 GPU → **本地 embedding 转默认**，补一条 ADR 修订 ADR-006。
   - 不可接受 → **诚实回退**：语义检索要么走 SiliconFlow（第二把 key，作者已否）、要么 BM25-only 维持 + 把 DeepSeek LLM 重排做强（在 BM25 召回内重排，半个补丁）。**不硬上一个跑不动的本地模型。**
3. **接入**：候选 provider 进 `get_embedding_provider()` 解析链（本地优先 → SiliconFlow 可选加速 → 都没有退 BM25）。`vector_store` / FAISS 索引不用改（Protocol 兼容）。

---

## 4. 影响范围（批准后才动）

- `bookscope/store/embedding_provider.py`：加 `LocalEmbeddingProvider` + 工厂解析链调整
- 新依赖：fastembed / onnxruntime（CPU wheel，**确认不拉 GPU/CUDA**）
- ADR-006 修订（本地 embedding 在轻量 ONNX 下重新评估）+ 落地后补新 ADR
- `vector_store` / FAISS：不变（Protocol 兼容）
- 验证复用 `scripts/eval_retrieval.py` + 74 条 golden set

---

## 5. 不做

- 不用 `sentence_transformers` 重模型（ADR-006 否的就是它）
- 不依赖 GPU
- 不强制 SiliconFlow / 不逼用户配第二把 key
- probe 没过判定线前，不把本地 embedding 设默认（不假设它行）

---

## 6. 验证方法

可行性 probe 三数（建索引耗时/内存、依赖体量、golden set recall@5 三方对照）+ 不破 GPU 确认。三条过线才转默认；不过线走第 3 节的诚实回退。
