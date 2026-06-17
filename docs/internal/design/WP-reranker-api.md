# WP-reranker-api 设计草稿 · 给检索加一层 API rerank（接 SiliconFlow bge-reranker）

> **性质：设计草稿，待作者审，批准前不动代码。**

**日期**：2026-06-12
**状态**：草稿，待作者审
**上游**：ADR-006 D-2（reranker 走 API Protocol，留给 ADR-007）；ADR-007 提到 RerankerProvider 但"尚未实现，能力暂归零"
**起草**：moyu-good
**方法论锚**：戴明（无测量不改进）——先把"加 rerank 值多少分"变成 golden set 上的 before/after 数字，再决定默认开关；不靠直觉拍板。

---

## 1. 目的

一句话：**BM25 词面对不上、向量召回又把相关段排到第 7、第 8 位的题，靠 rerank 把真正相关的那条提到前面，让 agent 拿到的 top-k 更准。**

检索是答案的地基——agent 看不到的原文段，再聪明也引不出来。现在的短板有 golden set 实测撑着（`docs/internal/experiments/data/retrieval-eval-baseline-summary.md`）：

- **改述题**：query 说"盐铁会议""4 万亿刺激计划"，原文写"《盐铁论》记载的辩论""4万亿元的刺激计划"，BM25 词面对不上直接空手，zhinei 两题 recall 归零。
- **位置 / 角色题在大书上沉底**：kuicheng（4315 chunk）recall@5 = 0.380，只有小书的六成；主角名在几千个 chunk 里反复出现，真正"首次登场/定义性段落"被淹。

向量检索能召回到候选池里，但 RRF 融合只按"两路排名的倒数和"排序，排不准谁最相关。rerank 是个专门干"给 query 和候选段算精排分"的模型,正好补这一段。

外部佐证：Anthropic 实测 contextual retrieval 上叠 rerank，检索失败率降 67%，不叠只降 49%(`docs/internal/research-notes/002` 第一节)。这是检索质量最高的那根杠杆,而且 ADR-006 D-2 早把路指好了——走 API、CPU 可跑、不碰 GPU 红线——只是一直没人走。

---

## 2. 接在哪

### 数据流（加 rerank 后）

```
query
  │
  ├─ BM25 search  ─┐
  │                ├─ RRF 融合 → 候选池（取 oversample 条，比如 top_k×4）
  ├─ vector search ┘
  │
  ▼
[章节/角色过滤]  ← R0SearchChunksBackend.retrieve 现有逻辑
  │
  ▼
★ rerank 重排  ← 新插这一层：把过滤后的候选段连同 query 发给 SiliconFlow
  │              拿回每段的精排分，按精排分重新排序
  ▼
截 top_k → 归一化 relevance_score → 封装 ChunkMatch → 给 agent
```

### 具体插在哪个文件、哪一行

插在 **`bookscope/agent/backends/r0_search_chunks.py` 的 `R0SearchChunksBackend.retrieve`（124-197 行）**，不是更底层的 `SessionVectorStore.search`。理由：

- `retrieve` 这一层已经做完了 oversample → 章节/角色过滤（141-166 行），手里正好是"过滤后该精排的那批候选"。rerank 应该排过滤后的候选，不是排过滤前的——在更底层的 `search` 里排，会把待会儿要被章节过滤砍掉的段也一起算分，白花 API 钱。
- 现在 173-174 行是 `filtered.sort(key=按原始分降序)` 再 `trimmed = filtered[:top_k]`（174 行）。**rerank 就替换"按原始分排序"这一步**：候选先不截断，整批发去 rerank，按精排分排完再截 top_k。
- `search()`（vector_store.py:195-220）保持不动——它是纯检索层,不该知道 agent 的章节/角色过滤,职责清楚。

一句话定位：**RRF 出候选 → 章节角色过滤 → 在 `r0_search_chunks.py:173` 那次排序处插 rerank → 截 top_k 给 agent。**

### 取多少候选、rerank 后截多少

- 现在 `oversample_factor=3`（r0_search_chunks.py:101、141 行 `fetch_k = max(top_k * 3, top_k)`）。
- 加 rerank 后建议把候选池放宽到 **top_k × 4 ~ × 5**：rerank 的价值就是从更大候选池里挑准，候选给太少（比如只给 top_k 条）等于没给它发挥空间。具体倍数进验证方案调,先按 ×4 起。
- rerank 完按精排分排序,截 **top_k**(默认 5,跟现在一致)给 agent。
- 注意一个上限：SiliconFlow rerank 单次 `documents` 条数有上限(文档随模型变,**待核实具体上限**)。kuicheng 这种 4315 chunk 的大书,oversample 后候选池也就几十条(top_k×4=20),远没到上限,不用担心。但候选段每条文本长度要看 `max_chunks_per_doc`——长 chunk 会被 rerank 内部再切,这点实测时确认。

---

## 3. RerankerProvider 接口

按 ADR-006 D-2 的说法（"`RerankerProvider` Protocol，`rerank(query, candidates, top_k) -> list[tuple[int, float]]`"），照搬 `EmbeddingProvider` 的形状（embedding_provider.py:33-56）。

### Protocol（新文件 `bookscope/store/reranker_provider.py`，本稿不写实现）

```python
@runtime_checkable
class RerankerProvider(Protocol):
    @property
    def name(self) -> str: ...          # 例 "SiliconFlow/BAAI/bge-reranker-v2-m3"

    def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: int | None = None,
    ) -> list[tuple[int, float]]:
        """输入 query + 候选段文本列表，返回 [(原列表下标, 精排分), ...]，
        按精排分降序。下标对回调用方的候选列表，分数是模型给的相关性。"""
        ...
```

接口形状对齐 SiliconFlow 的 rerank 响应（已核实 docs.siliconflow.cn rerank API）：

- **endpoint**：`POST https://api.siliconflow.cn/v1/rerank`（跟 embedding 的 `/v1/embeddings` 同域同鉴权，BYOK）
- **请求**：`{"model": ..., "query": "...", "documents": [...], "top_n": N, "return_documents": false}`——`return_documents=false` 省流量,我们只要下标和分数,原文本地有。
- **响应**：`{"results": [{"index": 候选下标, "relevance_score": 分数}, ...]}`,已按分降序。直接映射成 `list[tuple[int, float]]`。
- **模型 id**：`BAAI/bge-reranker-v2-m3`(免费档)/ `Pro/BAAI/bge-reranker-v2-m3`(付费档,更稳)。默认用免费档 `BAAI/bge-reranker-v2-m3`。SiliconFlow 会定期调整在架模型,**生产前到 Models 页核一下 id 还在不在**。

### key 从哪来

跟 embedding 一模一样:

- 默认读环境变量。embedding 用 `SILICONFLOW_API_KEY`(embedding_provider.py:76)。rerank 复用**同一个** `SILICONFLOW_API_KEY`——同一家服务,一把 key 两个能力,用户不用配第二个。
- 工厂函数 `get_reranker_provider()` 照抄 `get_embedding_provider()` 的三段式(embedding_provider.py:126-151):显式 `BOOKSCOPE_RERANKER_PROVIDER=siliconflow` → 自动检测 `SILICONFLOW_API_KEY` 存在 → 兜底返回 `None`。
- BYOK 链路:upload / ask 端点的 key 怎么传进 embedding,rerank 就怎么传。`dependencies.py` 现在没把 SiliconFlow key 走 request(embedding 直接读 env),所以**第一版 rerank 也走 env 读 key**,跟 embedding 保持一致;将来要做"前端传 SiliconFlow key"时两个一起改。

---

## 4. 没 key 怎么办

**没有 key 就清清楚楚跳过 rerank,退回 RRF/过滤后的原顺序——绝不静默。** 这是项目反复强调的"降级要可见"(WP2a 已经为 embedding 降级做了这事)。

具体:

- `get_reranker_provider()` 返回 `None` 时(没 key / 依赖缺失 / 关掉了),`retrieve` 跳过 rerank 那一步,**就走现在 173-174 行的"按原始分排序 + 截 top_k"**——行为跟今天完全一样,零风险。
- **留痕**:扩展 `retrieval_mode` 的取值(`ChunkMatch.retrieval_mode` 现在是自由 `str | None`,schemas.py:54-61,加值不用改 schema 结构):

  | 检索状态 | retrieval_mode 值 |
  |---|---|
  | 向量可用 + rerank 跑了 | `"hybrid_rerank"` |
  | 向量可用 + 没 rerank（无 rerank key） | `"hybrid"`（现有值，不变） |
  | 无向量（BM25-only）+ rerank 跑了 | `"bm25_rerank"` |
  | 无向量 + 没 rerank | `"bm25_only"`（现有值，不变） |

  这样分数波动能精确归因:是检索糊了、还是没 rerank、还是 rerank 也救不回来,一眼看出来。
- **rerank API 当场失败怎么办**:有 key 但调用超时 / 报错 / 配额耗尽——**不让整个查询挂掉**,捕获异常 → 退回原排序 → `retrieval_mode` 标成 `"hybrid"`(没真 rerank 成功就不许标 `_rerank`)+ 记一条 warning。这跟 embedding "建索引失败退 BM25"同型(vector_store.py:119-120)。失败可见,不假装成功。

---

## 5. 配置开关

- **默认关(`off`)**。理由:① rerank 每次查询多一个 API 往返,项目对延迟敏感(见第 7 节),默认开会拖慢所有人;② 验证方案(第 6 节)还没给出"算改进"的数,没数据支撑前不该默认开;③ 跟项目"降级要可见、能力没验证不偷偷上"的姿态一致。
- 开关:环境变量 `BOOKSCOPE_RERANK=on|off`,默认 `off`。`on` 且有 `SILICONFLOW_API_KEY` 才真跑;`on` 但没 key → 按第 4 节退回 + 留痕(不是报错,是可见跳过)。
- 候选池倍数也开成可配:`BOOKSCOPE_RERANK_OVERSAMPLE`(默认 4),方便第 6 节扫不同倍数。
- **切默认开的条件**:等第 6 节 golden set 对照数据出来,recall@5 / MRR 过判定线(第 6 节给线),且延迟在可接受范围,才提一次"默认开"的改动给作者签。在那之前默认关。

---

## 6. 验证方案

复用现成的 74 条 golden set(`docs/internal/experiments/data/golden-retrieval-{book}.json`,四本书 19+20+17+18=74 条,人工通读标注)和 `scripts/eval_retrieval.py`。脚本现在已经按 `retrieval_mode` 自动分文件名(eval_retrieval.py:179),加 rerank 后多一档 mode,天然兼容。

### 跑法

四本书各跑两次,同 golden set:

1. **before**:`BOOKSCOPE_RERANK=off`,拿 hybrid 基线(需要 `SILICONFLOW_API_KEY` 跑出 hybrid,不是现在的 bm25_only 基线)。
2. **after**:`BOOKSCOPE_RERANK=on`,拿 hybrid_rerank。
3. 对比 recall@5 / recall@10 / MRR,**分 query_type 看**(semantic / positional / character)——rerank 主要该救 semantic(改述题)和大书的 character/positional 沉底问题。

> ⚠️ 前提:现在的基线汇总(`retrieval-eval-baseline-summary.md`)是 **bm25_only**(没 key)。要先补一组 **hybrid(无 rerank)** 基线当 before,不能拿 bm25_only 当 before 跟 hybrid_rerank 比——那会把"向量的功劳"和"rerank 的功劳"混在一起算,归因就错了。这一步先做。

### "算改进"的判定线

- **主判定**:四本书平均 **recall@5 相对 hybrid(无 rerank) 基线涨 ≥ 0.05**(绝对值,比如 0.66 → 0.71),且没有任何一本倒退超过 0.03。
- **次判定**:**MRR 涨 ≥ 0.05**(rerank 的核心价值是把对的提到前面,MRR 对位次最敏感,这条比 recall 更能体现 rerank)。
- **分型必看**:semantic 类 recall@5 至少涨 0.08(改述题是 rerank 最该救的,涨幅该最明显);kuicheng 大书的 character/positional 类有可见改善。
- **方差守卫**:embedding 和 rerank 都走 API,结果可能跑跑有浮动。按 `feedback_baseline_variance_first` 的规矩——同一本书的 hybrid 基线先跑 3 次求 std,after 的涨幅要超过 std 才算真改进,别拿单次跑当 ground truth。BM25 是确定的,hybrid/rerank 不是。
- 判定线没过 → 写进 STATE,默认继续关,rerank 这层留着但不上;过了 → 提"默认开"给作者签。

---

## 7. 成本 + 延迟

每次 `search_chunks` 多一个 SiliconFlow API 往返。

### 延迟

- 一次 rerank 调用:网络往返 + 模型给几十条候选算分。bge-reranker-v2-m3 是轻量 cross-encoder,SiliconFlow 在服务端跑,**估算单次 0.3 ~ 1.5 秒**(候选 20 条量级;网络抖动是大头,**实测确认**)。
- 放进整本书 10 秒目标看:现在单题已经偏慢(memory `feedback_performance_first_class`:单题 2-4 分钟,batch 17 分钟,本就是产品级问题)。rerank 加的零点几到一点几秒,**相对单题总耗时占比小**,不是延迟的主要矛盾。但 agent 一轮查询可能调多次 `search_chunks`,每次都 rerank → 累加。所以:
  - 默认关(第 5 节),不拖慢没开的人。
  - 开了之后,rerank 调用要算进 `LoopTrace` 的耗时拆分,让"rerank 占了多少秒"在 trace 里可见(跟 retrieval_mode 留痕同理)。
- **不做激进优化**(缓存 rerank 结果 / 并发 rerank 多个 query)——第一版先把功能跑通、把数据测出来,优化等数据说话。

### 成本

- SiliconFlow 免费档 `BAAI/bge-reranker-v2-m3` 不花钱(配额内);`Pro/` 付费档按 token 计费,rerank 的计费量 = query + 所有候选段的 token 数。
- 候选 20 条、每条几百字 → 单次 rerank input 大概几千到上万 token。付费档单价低(rerank 比 LLM 便宜一个量级),**单次查询成本估算 < 0.001 元量级**(付费档;免费档 0)。BYOK——花的是用户自己的 SiliconFlow 额度,项目不垫钱。
- 成本不是这层的主要顾虑,延迟才是。

---

## 8. 不做什么

- **不做本地 rerank 模型**。`sentence_transformers.CrossEncoder` 在 CPU 上几十条候选要数百秒(ADR-006 实测 209-393 秒),隐含 GPU 依赖,违反"禁 GPU"硬约束——ADR-006 D-1 已经把本地 reranker 删干净了,这条路彻底封死。只走 API。
- **不动 RRF 融合本身**(vector_store.py:440-460)。rerank 是叠在 RRF 之上的一层,不替换 RRF。
- **不动 `relevance_score` 归一化口径**。rerank 的精排分照样过 `_normalise_scores`(r0_search_chunks.py:205-226)映射到 [0,1],agent 侧解读不变。
- **不做前端选 rerank 模型 / 调 top_n 的 UI**。第一版纯后端 + 环境变量,UI 等功能验证过再说。
- **不动 golden set 标注本体**。74 条已标好,直接复用,不重标。
- **不在本稿写任何应用代码**。本稿是设计草稿,批准后才动 `reranker_provider.py` / `r0_search_chunks.py`。

---

## 影响范围（批准后才动）

- 新增 `bookscope/store/reranker_provider.py`(Protocol + SiliconFlowRerankerProvider + 工厂)
- 改 `bookscope/agent/backends/r0_search_chunks.py`(retrieve 在 173 行那次排序处插 rerank + retrieval_mode 取值扩展 + oversample 可配)
- 改 `bookscope/agent/tools/schemas.py`(ChunkMatch.retrieval_mode 的 docstring 补 `_rerank` 取值,字段类型不变)
- 配套:`scripts/eval_retrieval.py` 零改动(已按 mode 自动分文件名);新增单测覆盖"有 key 跑 rerank / 无 key 退回 / API 失败退回"三条路径
- ADR:rerank 落地等于兑现 ADR-006 D-2 + 填上 ADR-007 留的"能力暂归零"的坑,落地后补一条 ADR 记决策(选型 / 默认开关 / 验证结论)

## 估时

设计批准后:Protocol + adapter + 接入 ≈ 0.5 agent 天;补 hybrid 基线 + before/after 对照 ≈ 0.5 agent 天(取决于 SiliconFlow key 可用)。
