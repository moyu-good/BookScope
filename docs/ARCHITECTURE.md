# BookScope 架构总图

> 一张图看懂 BookScope 整体怎么运转。新接触代码的人从这里入门，再去看 `architecture-decisions/` 的逐条 ADR。
> 表格里的文件 / 函数名是定位锚点；行号(标 ✓ 的)是抽查时的快照，代码会变，以函数名为准。

## 一句话

BookScope 是个"读整本书的 AI 工具"：上传一本书，提问时由 agent 从原文现场找答案，**每条结论带原文引用，没有原文证据的结论一律不输出**。服务任何要深读长文本的人——小说家、研究者、深度读者。

## 设计哲学

抛弃"提前把书嚼碎、做静态展示"的旧范式（r0），改成**轻索引 + 查询时智能代理 + 原文证据**：

- **上传时**只做最小必要的索引（解析、分块、建检索索引），本该很轻
- **提问时**所有分析、推理、对比都由 agent 循环现场做，逐条回到这本书的原文
- "没证据不输出"是底线——不让模型凭训练记忆编，逼它每句话落到原文

运行时走 **r2 协议**（OpenAI function calling，ADR-007）。

---

## 主链路一：上传建库（一次性）

```
书 (bytes)
 │
 ├─ load_text         解析 epub/txt/pdf          → BookText{raw_text,title,language}
 ├─ clean             Unicode 正规化、压空白      → 纯文本
 ├─ detect_chapters   章节检测（中英正则+卷头）   → [(章号,标题,正文)] + ChapterDetectionStats
 ├─ chunk_book        分块（~1500字）+ 上下文头   → list[ChunkResult{index,text,chapter}]
 ├─ KG 抽取 ⚠️        MinimalKGExtractor 抽角色   → BookKnowledgeGraph{characters}
 ├─ 建索引            SessionVectorStore          → BM25(必)+向量(可选), retrieval_mode
 ├─ 装配              R0BookAssembler             → 算 chunk→章/角色映射，出 3 个 backend
 └─ 注册持久化        store.register              → JSON 存档(ADR-005) + L3 预热缓存
```

| 环节 | 文件 | 函数 | 说明 |
|------|------|------|------|
| 上传入口 | `bookscope/api/routes/books.py` | `upload_book` ✓:77 / `upload_book_stream` ✓:178 | 同步 + 流式两版 |
| ingest 三件套 | 同上 | `_run_ingest_or_raise` ✓:134调用/414定义 | load→clean→chunk |
| 解析 | `bookscope/ingest/loader.py` | `load_text` | epub/txt/pdf 分发 |
| 分块 | `bookscope/ingest/book_chunker.py` | `chunk_book_with_stats` / `detect_chapters_with_stats` | 章节检测 + 分块 |
| 数据结构 | `bookscope/models/schemas.py` | `BookText` / `ChunkResult` | chunk 带 index/text/chapter |
| KG 抽取 | `bookscope/agent/backends/minimal_kg_extractor.py` | `MinimalKGExtractor.extract` | 上传链路唯一的重 LLM 步骤，首次上传耗时主因 |
| 建索引 | `bookscope/store/vector_store.py` | `SessionVectorStore` ✓:96 | BM25 必建，向量可选 |
| 装配 | `bookscope/agent/backends/r0_assembler.py` | `R0BookAssembler.build_all` | 出 search/chapter_range/list_characters 三 backend |

KG 抽取是上传链路上唯一的重 LLM 步骤，也是首次上传耗时的主因。它产出的轻量角色索引只服务 `list_characters_in_chapter` 工具，查询期调用占比很低；之后重开同一本书走 L3 缓存直接命中，不再重抽。

---

## 主链路二：查询出答案（每次提问）

```
问题
 │
 ├─ route_question      路由：agent_loop / summary / character / chapter_content
 ├─ (可选) fast_path    一次检索 + 一次 LLM，失败回退 agent_loop
 │
 └─ AgentLoop.query     ── agent 主循环 ──────────────────────────┐
      │                                                            │
      ├─ 调 LLM（带 L2 缓存）                                       │
      ├─ LLM 决定调哪个工具 → 并发执行 → 原文捞回 evidence_registry │ 反复
      ├─ (WP5) 空转检测 / 接近超时强制综合                          │
      └─ LLM 给最终答案 ◄──────────────────────────────────────────┘
            │
            ├─ parse_final_answer    抽 {answer, citations[{chapter,snippet}]}
            ├─ verify_citations      逐条核验引用是否真在原文 → verified/match_score
            └─ (异步) review_answer  开发期评分，失败不阻断
       → 返回 {answer, citations, trace, review, route_type}
```

| 环节 | 文件 | 函数 | 说明 |
|------|------|------|------|
| 查询入口 | `bookscope/api/routes/agent.py` | `agent_ask`:76 | 同步 + 流式 |
| 路由 | 同上 | `route_question` | 分流快路径/agent 循环 |
| 快路径 | `bookscope/agent/fast_path.py` | `run_fast_path` | 简单题省一轮，失败回退 |
| agent 主循环 | `bookscope/agent/loop_r2.py` | `AgentLoop.query`:394起 | r2 OpenAI function calling |
| 引用核验 | `bookscope/agent/citation_check.py` | `verify_citations` ✓:85 | 阈值 `CONTAINMENT_THRESHOLD=0.6` ✓:23 |
| reviewer | `bookscope/agent/reviewer.py` | `review_answer` ✓:116 | **非主链路，异步评分，开发用** |

### 三个工具（agent 在查询时调）

| 工具 | 实现 backend | 作用 |
|------|------|------|
| `search_chunks` | `bookscope/agent/backends/r0_search_chunks.py` (`retrieve`) | 检索原文片段，返回 `ChunkMatch`(带 relevance_score/retrieval_mode) |
| `get_chapter_range` | `r0_assembler` 的 chapter_range backend | 按章号拉原文 |
| `list_characters_in_chapter` | 同上 list_characters backend | 列某章角色（KG 的出口，仅 0.5% 调用） |

检索实际走 `SessionVectorStore.search`（✓:195），BM25 + 向量用 RRF 融合。

> **长上下文转默认**：塞得进所选模型上下文窗口的书，问答默认走「整本进 system 固定段」而非检索——引用真实性实测与 RAG 持平、稳定前缀让缓存稳态命中 ≥90%；超大书才回退到上面的 BM25 + 向量混合检索。

---

## 主链路三：整本书结构化功能（关系图 / 曲线 / 伏笔…）

「问书」之外的全书功能走另一套机制，**不进 agent 循环**。1.x 起（ADR-010 章脉转向）分两条路：

### A. 从「章脉」派生（叙事曲线 / 节奏 / 叙事流 / 关系图）

整本只精读一次，出一份带原文证据的逐章结构「章脉」，各视图从它派生——不再每个功能各跑一遍全书（旧法十个功能把整本 input 重发十遍）。

```
传书后首次：build_chapter_spine ── 分维 map-reduce(人物维 + 情节维)逐段抽 → 按真章号合并 → 章脉
              （D-7 按字数+章数双闸切段防输出截断;book-first 书在前指令在后,DeepSeek 前缀缓存复用）
缓存(book 级,接 L3)：同书重开秒出,不重抽
派生视图：relationship_graph_from_spine / narrative_curve_from_spine / …(纯计算,0 次 LLM)
点开现取：章级锚视图(关系图边 / 叙事流同场对)不带 upfront 证据,前端点开调 /agent/spine-evidence
          现取那一章的支撑句(纯检索,出路 B,贴「查询时证据现场取」)
```

**几百万字的书也跑得动**（map-reduce 分段，不需整本塞进窗口）；首次精读一遍是固有成本（前端大书提醒条会提前告诉用户），读完缓存住、之后各视图秒出。

### B. 各跑全书（时间线 / 伏笔 / 支线 / 实体 / 母题 / 概念 / 一致性 / 论点 / 文体 / 知识卡 / 改稿 / 前情 / 声口）

需要跨章 / 跨时序推理或 query-scoped 的功能**不能**从逐章章脉 naive 派生（时间线要把倒叙还原成真实时序、伏笔要 setup→payoff 跨章配对），仍走「分段 map-reduce + 结构化 JSON + 条粒度证据核验」。

| 关注点 | 说明 |
|--------|------|
| 端点 | `bookscope/api/routes/agent.py` 下的 `/agent/*`：character-graph / character-flow / narrative-curve / pacing-curve（走 A 章脉）· timeline / foreshadow-arcs / subplot-weave / entity-recall / recap / motif-tracking / argument-structure / concept-evolution / writing-technique / study-cards / style-issues / character-voice（走 B）· spine-evidence（A 的点开取证，纯检索不调 LLM） |
| 章脉模块 | `chapter_spine.py`(建)/ `_internal/chapter_spine_cache.py`(缓存)/ `chapter_spine_views.py`(派生)/ `chapter_spine_canon.py`(别名合并)/ `chapter_spine_evidence.py`(取证) |
| 三道可靠性守卫 | ① max_tokens 给够 + D-7 章闸（结构化输出长，截断了抢救已闭合的条目）② 关缓存防坏响应 poison ③ 失败重试 |
| 运行用量 | `_UsageRecorder` 把 LLM client 包一层，旁路记每次调用的 token，组装进响应 `trace`，前端据此显示读了多少字 / 花了多少 token |

---

## 四层缓存

| 层 | 文件 | 缓存什么 | 键 | 何时命中 |
|----|------|---------|----|---------|
| L1 | `_internal/search_cache.py` | search_chunks 结果 | session+query+scope 的 hash | agent 循环里检索前 |
| L2 | `_internal/llm_cache.py` | LLM 调用结果 | model+system+messages 的 hash (SQLite 持久化) | 每次调 LLM 前 |
| L2.5 | 同上 | — | prompt_version | prompt 升级时按版本失效 |
| L3 | `_internal/book_cache.py` | 整本书装配体(WarmedBook) | session_id (LRU+磁盘pickle) | 读 session 时(非上传) |
| 章脉 | `_internal/chapter_spine_cache.py` | 整本精读出的逐章章脉(list[dict]) | chunks文本+model+genre 的 hash (SQLite,同 kg_cache.db 不同表) | 派生视图建图前；同书一次后命中 |

DeepSeek 前缀缓存：长上下文的 system 固定段、章脉抽取的 book-first 前缀都保持 byte 一致以保命中（实测同段重读 ~100% 命中）；多轮对话前情提要接 system 末尾可变段（保前缀稳定）。

---

## 关键设计约束（读代码才知道的"暗规则"）

- **reviewer 不在主链路**：答案返回后异步评分，失败返 None 不影响 ask。只是开发期评估工具，不该做成给用户看的评分卡（三方共识待降级）。
- **向量不可用自动降级**：没 embedding key 时 `SessionVectorStore` fallback 到 BM25-only，`retrieval_mode` 标记降级状态。⚠️ "默认到底走 hybrid 还是 bm25" 的真相待第 2 步代码验证后补入。
- **citation 核验非执法**：`verified=False` 的引用保留不删，靠 `match_score` 字段观测分布（WP1 设计）——核验只做了"原文存在性"(recall 侧)，缺 ALCE 的 precision 侧。
- **空转检测（WP5）**：连续 2 轮检索 query/chunk 高度重叠 → 注入"停检"提示；接近超时 → 强制综合轮。
- **多轮对话（ADR-009）**：每问把上轮前情提要接 system 末尾，每轮变但缓存前缀稳。

---

## 已知限制与演进方向

- **几百万字大书的全书功能首次跑慢且费**——章脉转向(ADR-010)后改 map-reduce 分段,大书不再"不可用",但首次要把整本精读一遍(读一遍书的固有成本,DeepSeek 前缀缓存救不了第一次读);读完章脉缓存住、之后各视图秒出。前端大书提醒条提前告诉用户这一次性成本。
- **首次上传偏慢**——主要耗在 KG 抽取这一步的重 LLM 调用;重开同一本书走 L3 缓存即快。
- **深度诊断题延迟偏高**——现场读原文 + 多轮推理，不是查缓存；问题更具体能更快。
- **session 是内存态**——后端进程重启后已上传的书要重新上传（持久化是后续方向）。
- **引用核验目前做存在性（recall 侧）**——拿引文比对原文判「是否真有」；论断支撑度（precision 侧）由 `/agent/check-citations` 在答完后补判。
- **reviewer 是开发期评估工具**——异步评分、不展示给用户（同一个 AI 给自己打分会偏高，对用户无参考价值）。
