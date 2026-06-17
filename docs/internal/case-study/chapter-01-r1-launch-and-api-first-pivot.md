# 第 1 章 · r1 首次真 API 跑通与 API-first 架构重构

> **状态**：草稿 · 作者未定稿
> **时段**：2026-04-24（第 16–20 轮，一天内五个 commit）
> **覆盖 commit**：`8ca0671` / `077b8ec` / `03f0b0e` / `01a56db` / `b9f2951`

---

## 一、5 天前的 r1：代码齐备，但从未真跑

进入第 16 轮之前，r1-agent-loop 代际已经积累了 15 轮工作：

- **数据层**：r0 的 ingest / chunker / KG 装配复用；新增 `ChunkResult.chapter` 字段（第 15 轮）、`detect_chapters` 公共 API（第 14 轮）、`SessionVectorStore` 持久化（第 13 轮）
- **大脑层**：`AgentLoop` 核心 + 三个 tool（search_chunks / get_chapter_range / list_characters_in_chapter）+ citation 强制机制（第 7 轮）
- **Provider 层**：`LLMClient` Protocol + DeepSeek / Anthropic 双 adapter（第 8 轮 ADR-003）
- **FastAPI 入口**：`POST /api/books/upload` + `POST /api/agent/ask`（第 10–12 轮）
- **持久化**：`JSONFileSessionStorage`（第 12 轮 ADR-005A）
- **最小 KG 抽取**：`MinimalKGExtractor`（第 12 轮 ADR-004B）
- **测试**：404 全绿

从 STATE.md 第 15 轮末尾看，代码链路明明已经无尾巴。但有一条一直没闭合：**作者当时没有任何 LLM provider 的 API key**。所有测试都是 mock adapter；所有 "integration" 都是纯 Python 栈内的集成，从未真的把请求送到 provider 那头。

这一状态持续了多轮。副管理每轮都在 STATE.md 的 "未完成 / 挂起" 区记同一条："Smoke test 真 API 验证 · 等作者拿到任一国内 LLM provider 的 API key"。

然后第 16 轮开始时，作者在 session 里贴出了一条讯飞星辰（astron）的 API：

```
api：<redacted>:<redacted>
modelId：astron-code-latest
openai_url:  https://maas-coding-api.cn-huabei-1.xf-yun.com/v2
```

接下来的六个小时，r1 从"理论可跑"跨到"真的跑起来"；同时一口气活检出一条**违反项目最高优先级约束**的代码路径，并在当天完成了一次 API-first 架构重构。

---

## 二、第一次失败：loop timeout 的表面错误

`DeepSeekAdapter` 早就支持自定义 `base_url`（docstring 明说"私有部署 / 代理走 OpenRouter 时可覆盖"）。接入 astron 本质上是零代码改动——只要在 smoke test 脚本里加一个 provider 分支，把 astron 的 base_url / model / api_key 环境变量喂进同一个 adapter。

`scripts/smoke_test_r1.py` 加了一个 `astron` 分支后第一跑，立刻炸：

```
[smoke] agent loop 失败: LoopTimeout: agent loop exceeded
  timeout_seconds=90.0 (elapsed 174.1s)
```

`AgentLoop` 默认 timeout 90 秒；agent 跑了 174 秒都没收敛。

最朴素的第一反应：**astron 太慢，timeout 调大**。改成 600 秒。

第二跑：还是炸，`elapsed 893s`。

这时作者还在继续说"继续"——我的判断是：再盲目调 timeout 没意义，必须看 trace 才知道 agent 在做什么。但 `LoopTimeout` 异常不带 trace（`trace` 是 `query()` 方法里的局部变量，异常被 raise 时丢失）。

第 16 轮第一个非表面的工程改动由此产生：

```python
# bookscope/agent/loop.py
except LoopTimeout as exc_to:
    trace.outcome = "timeout"
    trace.duration_ms = _elapsed_ms(start)
    exc_to.trace = trace  # type: ignore[attr-defined]
    raise
```

让 `LoopTimeout` / `MaxIterationsExceeded` / `ToolDispatchError` 都挂 `.trace` 属性。smoke test 捕获后就能 `json.dumps(exc.trace.model_dump())` dump 出全部轨迹——不管成功失败。

第三跑（带 trace dump）的结果揭穿了"astron 太慢"这个误判：

```json
{
  "iterations": 1,
  "tool_calls": [
    {
      "tool_name": "search_chunks",
      "input": {"query": "主要角色人物介绍", "top_k": 15},
      "output_summary": "list[15]",
      "elapsed_ms": 892448,
      "attempt": 1,
      "status": "ok"
    }
  ],
  "total_input_tokens": 1928,
  "total_output_tokens": 34,
  "duration_ms": 898354,
  "outcome": "timeout"
}
```

**astron 根本不慢**——1928 input / 34 output token，它一秒内就返回了 tool call 决策。耗时全在本地 `search_chunks` 上：**一次 BM25 检索在 1069 chunk 的真 epub 上耗时 892 秒**。

这个数字荒谬到不可能是 BM25 本身——BM25 对 1000 chunk 应该是毫秒级。瓶颈在别处。

---

## 三、bench 与真凶：cross-encoder reranker

写一个 5 行的 benchmark 脚本（单独构造 `SessionVectorStore` + 3 次 `search` 计时）：

```
[bench] load_text: 0.98s, words=32164
[bench] chunk_book: 0.24s, chunks=1069
[bench] SessionVectorStore ctor: 6.65s
[bench] search_chunks x1: 393.00s, hits=15
[bench] search_chunks x1: 216.55s, hits=15
[bench] search_chunks x1: 209.46s, hits=15
```

ctor 正常；BM25 `get_scores` 在这个量级毫秒级。但 `search()` 默认路径里有个 `_maybe_rerank` 分支，走的是 `_get_reranker()` → `sentence_transformers.CrossEncoder(BAAI/bge-reranker-v2-m3)` 本地 CPU 推理。1069 chunk 下 fetch top-k×3 = 45 个候选对，每个 (query, chunk) pair 喂给一个 transformer 模型算分——CPU 上 200+ 秒完全合理。

这条路径**不是新写的**——是 r0 遗留的 hybrid 检索"默认开 rerank 提升精度"逻辑。r1 继承 `SessionVectorStore` 时没有明确下线它。

**真正刺眼的不是慢——是它违反了两条最高优先级的项目约束**：

1. `CLAUDE.md` 技术栈节明写："禁止 GPU 依赖。Web 产品必须在普通 CPU 上可跑；任何强制 GPU 的方案一律否决"
2. 长期记忆 `feedback_performance_target.md`："整本书必须 10 秒内读取"

`CrossEncoder` 表面上是 CPU 可跑——所以之前没人拦。但实际性能只有在 GPU 上才可用；CPU 上单次 search 200+ 秒意味着"产品上不可用"。**它通过了代码静态检查，但不通过真实跑的活检**。

这是一个典型的"约束的影子":代码里没有 `import torch`，没有显式 CUDA 调用，但依赖链的某一层（`sentence-transformers` → `transformers` → `torch`）让整个栈在 CPU 上变成灾难级性能。静态审查看不到，只有真跑才暴露。

---

## 四、熔断与活检报告

为了当天能继续跑通 smoke，副管理先在 `r0_search_chunks.py` 里加了一条常数熔断：

```python
raw_candidates = self._store.search(query, fetch_k, enable_rerank=False)
```

带着这条 hack 重跑，整条链路在 **82.3 秒**内给出答案（4 iterations / 6 tool 调用 / 56k input + 1.3k output token / 7 条原文 citation）。

这个数字值得停下来看一眼。82 秒对一个 32K 字书、1069 chunk、4 轮 agent tool use 的查询而言，是"勉强可用"。82 秒里绝大部分时间花在 astron 本身的推理（600 秒 timeout 看，astron 每轮 tool 决策 ~20 秒，整个 loop 6 次外加 final answer 生成）——这是**模型本身的特性**，不是工程可优化的。

但**本地 tool 必须 < 100ms**。本轮之前它是 892 秒。差了四个数量级。

这个差距就是 ADR-006 要关闭的。

提交给作者的活检报告（session 实时给出）总结了三件事：

1. r1 工程上是通的（链路、协议、adapter、tool 调度、citation 机制全部 work）
2. astron 没毛病（token 用量合理、语义质量 OK）
3. **但有一条代码路径违反硬约束**，需要代际级决策

作者当时的一句话直接定调了方向：**"全部 API 化"**。

---

## 五、ADR-006：从三选一到单选

副管理原本准备的是个三方案 ADR-006：删除 reranker / 做可选开关 / API 化。作者在看到活检报告后不等副管理列完就给了"全部 API 化"。

这是一个**实际上比三选一更激进**的决策。"API 化"不只是 reranker——审计 `bookscope/store/embedding_provider.py` 发现里面还有两个本地 tier：

```
Tier 1（默认）：SiliconFlow API — 已是 API
Tier 2（可选）：Local Qwen3-Embedding-0.6B（1.2 GB）
Tier 3（高级）：Local BAAI/bge-m3（2.2 GB）
```

Tier 2 / Tier 3 当前不是默认路径，但代码在，依赖在（`sentence-transformers`），未来随时可能被启用。作者的"全部"二字把它们一并纳入。

ADR-006 最终定调为**五条命令**：

- **D-1**：删除 `CrossEncoder` reranker 本地实现
- **D-2**：reranker 能力暂时归零；若未来需要，按 embedding 的 Protocol + adapter 模式做 API-based RerankerProvider（留 ADR-007）
- **D-3**：删除 embedding Tier 2 / Tier 3 本地实现
- **D-4**：`sentence-transformers` / `torch` / `transformers` 从 runtime 依赖清单移除
- **D-5**：划定 API 化**边界**——BM25（纯算法）/ jieba（字典）/ FAISS（向量库）/ ingest / chunker 不纳入。API 化 = ML 模型推理，不是"所有计算"

D-5 这一条后来看是最重要的。"全部 API 化"如果字面解读可能变成"把所有本地计算迁到远端"——那会把 BM25 / jieba / 读 epub 都往 API 推，偏离初衷。D-5 把范围收回到"ML 模型推理"，让这条原则可操作。

---

## 六、第 17 轮实施：626 行减重

第 17 轮是纯 refactor，用 commit `077b8ec` 一次完成。净删除 **626 行**（约 500 行本地 ML 代码 + 约 200 行对应测试 − 约 80 行签名调整与 export 清理）。

具体动作：

| 文件 | 改动 |
|------|------|
| `bookscope/store/vector_store.py` | 删 `_RERANKER_NAME` / `_RERANKER_CHAR_LIMIT` / `_reranker` 全局 / `_get_reranker()` / `rerank()` / `_maybe_rerank()`；`search()` 的 `enable_rerank` 参数移除 |
| `bookscope/store/embedding_provider.py` | 重写为 API-only，341 → 155 行；删 `Qwen3LocalProvider` / `BgeM3LocalProvider` / `_is_model_cached()` 与所有本地常量；factory 简化为 "SILICONFLOW_API_KEY 在 → SiliconFlow；不在 → None" |
| `bookscope/store/__init__.py` | export 清理 |
| `bookscope/agent/backends/r0_search_chunks.py` | 撤销第 16 轮的 `enable_rerank=False` 临时 hack；Protocol 里对应形参删除 |
| `tests/test_reranker.py` | **整个文件删除**（267 行，17 个用例） |
| `tests/test_embedding_provider.py` | 341 → 181 行，只保留 SiliconFlow + 简化后的 factory 测试 |
| `pyproject.toml` | 删 `sentence-transformers>=2.6.0`（唯一 ML 重依赖） |

测试从 404/404 降到 **369/369** 全绿——减少的 35 个用例全部来自已废弃的能力（reranker 17 个 + embedding 本地 tier 约 18 个），**零业务回归**。

`pip install -e .` 的产物明显瘦身——原本 `sentence-transformers` 会拖 `torch`（~2 GB）、`transformers`（~200 MB）、`tokenizers` 等一坨依赖，删掉后全走了。r1 的运行时从这一刻开始**不再有任何本地 transformer 推理代码路径**。

---

## 七、第 18 轮：把真 KG 抽取接回 smoke（但默认关）

第 17 轮完成后链路是干净的，但**第 16 轮的 pilot 观测留了一条尾巴**：

smoke test 脚本里的 `BookKnowledgeGraph` 是手工造的——只有 4 个角色（朱元璋 / 李善长 / 徐达 / 常遇春）。trace 表明 agent 在真跑时调了 4 次 `list_characters_in_chapter`，每次都拿到同样的 4 个名字，对 answer 的丰富性贡献为零；answer 里提到的 50+ 角色几乎全是 `search_chunks` 拿到的原文 snippet 里推理出来的。

正式实验前这是个硬伤。`MinimalKGExtractor`（第 12 轮 ADR-004B 产出）已经能从 chunks 抽角色清单——但**它没被 smoke test 调过**。

第 18 轮把 extractor 接进 smoke test，但加了一道**成本开关**：

```bash
BOOKSCOPE_SMOKE_EXTRACT_KG=1 \
BOOKSCOPE_SMOKE_KG_CHUNK_LIMIT=20 \
python scripts/smoke_test_r1.py
```

- 默认关：smoke 5 秒 warmup + 1 分钟 query 的快速迭代特性不变
- `EXTRACT_KG=1` 打开：走 `MinimalKGExtractor`
- `KG_CHUNK_LIMIT=N` 可把输入限到前 N 个 chunk 控制成本

**为什么不默认打开**？粗估：1069 chunk / 60 per batch = **18 次 LLM 调用**；按 astron 现场 ~100s/call 估，全量跑一次要 **30 分钟 / 几十万到上百万 input token**。smoke 的职责是"5 分钟内验证链路通"，不该每跑一次都付 30 分钟的仪式成本。opt-in 把成本决策权交回作者。

Extractor 失败降级到手工 KG（不中断链路）——任何 `ProviderError` / `LLMFormatError` 都被 smoke 的 try-except 吃掉，然后 warn + fallback。

---

## 八、第 19 轮：astron 作为 API 层一等公民

筹划第 19 轮本想直接做前端 MVP。但审计 `bookscope/api/` 时发现：

```python
# bookscope/api/schemas.py
provider: Literal["deepseek", "anthropic"] = "deepseek"
```

**API 层不认 astron**。smoke test 能用是因为它绕过 FastAPI 直接构造 `DeepSeekAdapter + base_url`——前端做完就没用了，作者点"问问题"时只能选他没 key 的 provider。

所以第 19 轮被临时插队——前端必须先等这条后端门槛。

改动很小但面宽：

- `schemas.py` 的 `provider` Literal 加 `"astron"`；新增可选 `base_url: str | None = None`字段（**通用字段**，不是 astron 专属；deepseek 走代理 / OpenRouter 也可用；anthropic 忽略）
- `dependencies.py` 的 `DEFAULT_MODEL_BY_PROVIDER` 加 `"astron": "astron-code-latest"`；新增常量 `ASTRON_DEFAULT_BASE_URL`；`build_llm_client_from_params` 加 `base_url` 参数，astron 分支复用 `DeepSeekAdapter(api_key, base_url=...)`
- `routes/books.py` upload form 的 Literal + 新增 `base_url: Form(None)`
- 测试：新建 `tests/api/test_dependencies.py`（11 用例）；`test_agent_ask.py` 加 2 个 astron 用例；`test_books_upload.py` mock 签名同步

382/382 全绿（369 + 13）。

这一轮的设计决策有一个**值得记录**的细节：`base_url` 不设计为"astron 专属字段"。而是把它做成**通用的"OpenAI 兼容 endpoint 覆盖"**。这让 deepseek 用户也可以用（比如走 OpenRouter 代理、私有部署），anthropic 用户的请求可以带但会被忽略。API 层对客户端暴露的是一个**语义上干净的字段**，而不是"为 astron 打了个补丁"。

---

## 九、第 20 轮：前端最小 UI

后端门槛清完，第 20 轮做了纯前端——`web/` 目录，10 个文件，约 550 行 TS / TSX / CSS。

技术栈严格对齐 `CLAUDE.md` 的约定：React 19 + Vite 6 + TypeScript 5 + Tailwind v4。**零第三方 UI 组件库**（不引 shadcn / chakra / mui），纯 Tailwind utility；数据层用浏览器原生 `fetch`，不引 axios / react-query。`vite.config.ts` 配 `/api/*` → `localhost:8000` dev proxy，浏览器看到的是同源请求，CORS 自然不在考虑范围。

单组件 `App.tsx` 约 410 行，三段式（配置 / 上传 / 问答），所有状态本地 `useState`，表单校验 + 错误 banner。API 对接与 `bookscope.api.schemas` 1:1 对齐：`POST /api/books/upload`（multipart）+ `POST /api/agent/ask`（JSON）。provider 默认选中 astron，`base_url` 预填讯飞星辰 URL。

设计上刻意**避开"默认 Tailwind 模板"观感**（项目的 `rules/web/design-quality.md` 明令反对模板化）：

- 书页暖白 + 朱砂红 accent（章节序号 / 引用左边条 / 按钮底色）
- 中式段落序号（壹 / 贰 / 叁）替代 1 / 2 / 3
- 中文优先字体栈：display 用 PingFang / Noto Serif CJK / 思源宋体，body 用 PingFang / Noto Sans CJK
- Citation snippet 用左边框衬线风格（仿传统读书摘录），而不是 uniform card

**隐私约束**：API key 只存 React state（内存），不写 localStorage / cookie / 任何后端；UI 文案明示"仅本地会话，刷新即失效"。这是 BYOK 原则在前端的落地。

副管理**刻意不跑 `npm install`**——Windows 下会触发几百个包 + 大量权限提示，且 npm install 本身属于作者本地环境操作，不在 AI 主循环的合理 scope 里。作者 pull 后两条命令起跑：

```bash
cd web && npm install && npm run dev
# 另一端
uvicorn bookscope.api.app:app --reload
```

测试层面：前端 MVP **不引入 test runner**。UI 级回归靠作者的亲跑验收。

---

## 十、结语：约束的代价与收益

五天内五个 commit，讲的是同一件事：**硬约束在真实世界里如何从纸面转向代码**。

### 约束的代价

- **引入 API 依赖**：SiliconFlow 宕机或 key 配额耗尽时，embedding 层降级到 BM25-only；provider 若倒闭或调整 pricing，需要换。对冲手段是 Protocol + 多 adapter 形态，但代价真实存在
- **Rerank 能力暂时归零**：精度损失尚未量化；第 16 轮的 pilot answer 质量（82 秒 / 7 citation / 50+ 角色覆盖）表明 agent 本身的多轮 tool use 能部分补偿，但缺乏 recall@10 级别的正式对比
- **本地可用性下降**：离线场景（私密手稿 / 无网络）目前不支持。如果作者未来写非公开小说时在飞机上想用 BookScope，BM25-only 模式的"阅读智能"会显著降级

### 约束的收益

- **依赖瘦身**：`sentence-transformers` + `torch` + `transformers` 约 2 GB 级的 ML 依赖从 runtime 消失；冷启动无 2 GB 模型 lazy-load 的尾巴
- **对齐硬约束**：`CLAUDE.md` 的 "禁止 GPU 依赖"、"10 秒读取目标"、"BYOK" 三条在代码层对齐，不再有"静态审查通过但真跑违规"的隐藏路径
- **架构概念收敛**：LLM / embedding / （未来的）reranker 全部走同一 provider-adapter 模式（ADR-003 铺的路径），未来扩 provider（volcengine / 自建 vllm）是加一个 adapter 的事，不是代际级改动
- **前端直接可对接**：第 19 轮 astron 作为一等 provider 后，前端在第 20 轮不用再碰任何 Python 代码，纯浏览器端 fetch 就能跑完整流程

### 学到的

1. **"通过测试"不等于"能真跑"**。r1 前 15 轮 404 个单测全绿，但从来没有请求真的经过 provider 边界。第 16 轮 6 小时内活检出两套设计缺陷：`LoopTimeout` 丢 trace、本地 cross-encoder 违规。这两件事**任何 mock 测试都抓不到**——它们只在真实延迟分布、真实 chunk 数量、真实模型调用频率下显形
2. **硬约束需要"活检"**。静态审查（代码里没 `import torch`）不足以证明"不依赖 GPU"；要在 CPU 上跑真实数据量看时间。BookScope 之所以没早被坑是因为 r0 的用户都在有 GPU 的环境里跑——没有约束，就没有痛点，就没有活检机会
3. **作者的一句话决策是架构加速器**。"全部 API 化"这五个字省去了副管理起草"三方案 ADR"的 30–60 分钟；而且作者的决策**比副管理准备的三选一更激进**（同时动到 embedding Tier 2/3，副管理原本只提 reranker）。这个经验支持"CEO + AI 团队"模式中"作者掌握方向键"的设定——AI 在枝节上跑得快，作者在主干上踩得准

下一章（[chapter-02](./chapter-02-query-time-assembly-and-r0-legacy-patches.md)）回溯第 11–15 轮，讲 r1 继承 r0 时遇到的三个数据层结构性缺口（chunk-to-chapter 映射 / 章节原文结构化持久化 / chunk-to-characters 倒排），以及 `MinimalKGExtractor` + `JSONFileSessionStorage` + 三种不同级别 workaround 的慢修补过程。与本章"5 天激进"的节奏对比，第 2 章讲的是"五轮慢慢收尾"——**第 1 章能以那个节奏发生，是第 2 章慢节奏的红利**。

---

## 附录：本章涉及的资料索引

- ADR-001 · r1 agent tool 接口
- ADR-002 v2 · AgentLoop 框架选择（DeepSeek function calling 默认 + Anthropic 备选）
- ADR-003 · Provider adapter 层
- ADR-006 · 本地 ML 全 API 化（本章核心）
- Experiment 001 · 基线对比实验设计（含第 16 轮 Pilot 观测）
- STATE.md · 2026-04-24 第 16–20 轮多次更新
- Commit chain：`8ca0671` · `077b8ec` · `03f0b0e` · `01a56db` · `b9f2951`
