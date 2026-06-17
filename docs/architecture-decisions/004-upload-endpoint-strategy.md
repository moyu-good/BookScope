# ADR-004：upload 端点策略 —— 新书上传如何产出 book session

## Status

**事后追认**（作者口头批准，2026-06-10 按现状追认；方案 B 已实现）

- 代际：r1-agent-loop
- 作者：moyu-good
- 创建日期：2026-04-20
- 最后更新：2026-06-10

## Context / 背景

r1 的 FastAPI 入口已建好 `/api/agent/ask` 端点（ADR-002 v2、ADR-003 落地），但该端点要求请求体携带一个已存在的 `book_session_id`。目前 session 只能由 smoke test 脚本或 pytest fixture 手工装配 `R0BookAssembler` 并注册到 `BookSessionStore`。真要让用户 upload 一本书走完整链路，必须新增一个 `POST /api/books/upload` 端点。

该端点需要产出四样东西并喂进 `R0BookAssembler`：

1. `BookText` —— 走 `bookscope/ingest/loader.py` + `cleaner.py` 即可（`.txt` / `.epub` / `.pdf` 三种格式均已支持）。
2. `list[ChunkResult]` —— 走 `bookscope/ingest/book_chunker.py` 即可（`chunk_book()` 三层分块对长篇中文小说已验证）。
3. `BookKnowledgeGraph`（至少含 `CharacterProfile` 列表且每个 profile 带 `name` / `key_chapter_indices`）—— **本 ADR 要解决的核心问题**。
4. `SessionVectorStore`（FAISS + BM25 索引）—— `bookscope/store/vector_store.py` 仍在原位，调用方式未变。

前三项里只有 KG 卡住：r0 代际使用的 KG 提取链路（`legacy/v7/bookscope/services/extraction_pipeline.py` + `legacy/v7/bookscope/nlp/knowledge_extractor.py` 以及 `chunk_scanner.py` / `chunk_selector.py` / `ner_extractor.py` / `relation_extractor.py` 等一整套文件）已在 2026-04-20 的归档动作里挪进 `legacy/v7/`。按 `legacy/v7/README.md` 的约定，r1 代码不得依赖 `legacy/v7/` 下任何模块。

回到 r1 实际需要什么。三个 r0 backend 对 KG 的**最小**消费只看两条路径：`R0ListCharactersBackend` 读 `CharacterProfile.name` / `canonical_name` / `aliases`，以及通过 `build_chapter_character_map` helper 从 `key_chapter_indices` 反推章节→角色映射。`R0SearchChunksBackend` 则借由 `R0BookAssembler._compute_chunk_to_characters_map` 在 chunk 过滤层间接使用同一份映射。至于 `chapter_analyses` / `theme_analyses` / `narrative_rhythm` / `chapter_summaries`，r1 的三个 backend 一个都不读。

## Decision

**Status：待作者选择。副管理推荐方案 B。**

### 方案 A：复活 v7 extraction pipeline

把 `legacy/v7/bookscope/services/extraction_pipeline.py` 与它的核心依赖 `knowledge_extractor.py` + `ner_extractor.py` + `relation_extractor.py` + `chunk_scanner.py` + `chunk_selector.py`（以及这些文件间接牵扯的 `llm_analyzer.py` / `llm_utils.py` / `prompt_builders.py` 等）从 `legacy/v7/bookscope/nlp/` 迁回主树，命名为 `bookscope/nlp_legacy/`（用新目录名避免误导"归档"语义），然后在 upload 路由里调用。

- **成本**：首先要做一次完整的 import 图审计，确认复活链路不会把整个 v7 nlp 目录连带拉回来（`knowledge_extractor.py` 顶部即 `from bookscope.nlp import ...`，扇出较大）。其次 v7 的 pipeline 在 `run_extraction` 入口就写死依赖 `SessionData`（来自归档后的 `legacy/v7/bookscope/api/session_store.py`），需要改造为不依赖 session 类型、只接 `chunks + language + api_key`。再次 v7 内部走 `claude-haiku-4-5` 作为 Phase 1 cheap 模型并直接调 Anthropic SDK，与 ADR-003 adapter 层 + ADR-002 v2 的 DeepSeek 默认相悖；要么重接 adapter，要么承认两层 provider 抽象并存。
- **收益**：KG 质量最好（三阶段流水线对明朝系列已做过实战验证）；情感弧 / 叙事节奏 / 章节深度分析等 r1 当下不用但未来可能用到的字段可顺带复用；节省重新实现时间。
- **风险**：把归档拉回会让"r1 主线不依赖 legacy/v7"这条原则破功；v7 代码夹带的 tech debt（单文件过长、provider 硬绑、`SessionData` 入参耦合）会被 r1 继承；未来 r2 如果要动 KG 还要再次面对这些遗留代码。

### 方案 B：r1 自己做最简 KG 占位（**副管理推荐**）

在 `bookscope/agent/backends/minimal_kg_extractor.py` 新建一个 `MinimalKGExtractor` 类。构造函数接收 `client: LLMClient`（复用 ADR-003 adapter 层）。核心方法 `extract(chunks: list[ChunkResult], book_title: str, language: str) -> BookKnowledgeGraph`：把 chunks 按上下文预算切 batch，每个 batch 让 LLM 用 function calling 输出 JSON 格式的角色清单（`name` / `canonical_name` / `aliases` / `key_chapter_indices`），最后 merge 成一份 `BookKnowledgeGraph`。其它非必需字段（`chapter_analyses` / `narrative_rhythm` / `theme_analyses` / `emotional_stages` 等）一律留空或 None。

- **成本**：新写一个模块约 150-250 行代码（含 prompt 模板、batch / merge 逻辑、JSON schema 校验）；质量弱于 v7 三阶段流水线（单轮 map-reduce vs 多轮深挖 + Phase 2 智能选择）；超长书一次调用可能触发 context overflow，必须分 batch 并在 merge 阶段处理同名角色与 `key_chapter_indices` 合并。
- **收益**：r1 主线不引入 legacy 依赖；符合 ADR-003 "provider-agnostic"精神（通过 `LLMClient` Protocol 调 LLM，不绑任何一家）；tool backend 真正用得上的三个字段够用；未来要升级到 RAPTOR / GraphRAG / HippoRAG 等 SOTA KG 提取路径时，替换 `MinimalKGExtractor` 实现即可，upload 端点与 tool backend 都不动。
- **风险**：最低。某本书 KG 提取失败时，可降级为 "本书无 KG" —— `list_characters` 返回空列表、`search_chunks` 的 character 过滤通道被绕过，但 agent loop 不阻塞。

### 方案 C：不做 upload，只接受已有 AnalysisResult JSON 导入

upload 端点只接受 `.json` 文件。要求调用方事先提供符合 r1 schema 的 `AnalysisResult`（`book_title` + chunks + KG 三件套齐备）。r1 既不做 ingest 也不做 KG 提取。配套提供迁移脚本 `scripts/migrate_r0_to_r1.py`：从旧 r0 Repository 的 JSON 文件加载 `AnalysisResult`，按 r1 schema 转写。

- **成本**：几乎零开发成本（10-20 行 upload 路由 + 迁移脚本）。用户门槛高：先得有一份合规 JSON 才能用。作者自己也没有这样的 JSON（r0 的 `bookscope/services/extraction_pipeline.py` 已归档，想新跑一份都得先复活 A 方案）。
- **收益**：完全避开 KG 方案决策；保持 r1 主线最薄。
- **风险**：实际上是推迟决策而非解决。upload 端点无法接收新书，北极星"以《明朝那些事儿》为基线验证 r1 优于 r0 / 微读 / ChatGPT / Claude 直通"里隐含的"先得能上传书"这一步直接过不去，与"r1 代际完整可用"的定位冲突。

### 推荐理由

副管理推荐 **方案 B**，三条理由：

1. **架构纯粹性**。r1 代际的定位是"查询时智能代理 + r0 基础数据层"。r0 基础层的边界就是 `bookscope/models/` + `bookscope/ingest/` + `bookscope/store/` + `bookscope/utils/`（见 `legacy/v7/README.md` 的"与 r1 的关系"段），分析层本来就不在 r0 基础里。r1 自己做一份轻量 KG 提取比回收 v7 分析层更符合代际独立性。
2. **工程量可控**。DeepSeek function calling 做"chunks → character profiles" 单轮抽取，按明朝系列（~50 万字、350-400 chunks）规模估计，分 10-20 个 batch 跑，总调用成本几美元以内。作者已在北极星里明确成本不设红线。单元测试用 mock `LLMClient`，无需真 API。
3. **演化路径清晰**。未来引入更深的 KG 抽取方法（RAPTOR 的层级摘要、GraphRAG 的社区检测、HippoRAG 的知识索引）时，只需要实现一个新的 `KGExtractor` 并替换，upload 路由和三个 backend 的签名都不动。方案 A 把 v7 拉回会让后续升级额外背一层遗留。

方案 A 的代价是把刚做完的"v7 归档"动作部分推翻，并引入不可预期的 provider 绑定与 tech debt 传染。方案 C 是推迟而非解决，且在作者自己都没有合规 JSON 的前提下连"跑通一本新书"都做不到。

### Decision 实现要点（方案 B 落地步骤）

1. 新建 `bookscope/agent/backends/minimal_kg_extractor.py`。
2. 在该模块定义 `MinimalCharacterProfile` Pydantic 模型（仅含 `name` / `canonical_name` / `aliases` / `key_chapter_indices` 四字段；在输出前通过 `CharacterProfile.model_validate` 升级为 r0 schema 的完整对象，其它字段取默认值）。
3. 定义 `MinimalKGExtractor`：构造函数接收 `client: LLMClient` + `model: str`（默认由调用方显式传，避免绑死 `deepseek-chat`）；prompt 模板分 system / user 两段，system 段写输出 JSON 约束与示例，user 段拼当前 batch 的 chunks 文本。
4. 实现 `extract(chunks, book_title, language) -> BookKnowledgeGraph`：
   - 按 chunk 累计字符数切 batch（每 batch 控制在约 30-50 chunk，避免 context 溢出，具体阈值由常量可调）。
   - 每个 batch 调 `client.messages_create` 拿 tool_use block，`json.loads` 解析成 `list[MinimalCharacterProfile]`。
   - merge 阶段按 `canonical_name` 去重，合并各来源 batch 的 `key_chapter_indices` 为排序去重后的联合集合，合并 `aliases`。
   - 返回 `BookKnowledgeGraph(book_title=..., language=..., characters=[...])`；其余字段全部走默认值（空列表 / 空串）。
5. 新增 `bookscope/api/routes/books.py`，路由 `POST /api/books/upload`：
   - `multipart/form-data` 接收 `.epub` / `.txt` / `.pdf` 文件 + `provider` + `api_key` + 可选 `model`；写到临时路径；
   - 调 `bookscope.ingest.loader.load_text` 得 `BookText`；
   - 调 `bookscope.ingest.book_chunker.chunk_book` 得 `list[ChunkResult]`；
   - 经 `build_llm_client`（`dependencies.py` 已有）拿 adapter，构造 `MinimalKGExtractor`，跑 `extract`；
   - 构造 `SessionVectorStore` 并索引所有 chunks；
   - 构造 `R0BookAssembler`，注册到 `BookSessionStore` 并返回 `session_id`；
   - 失败路径：KG 提取异常时记录 trace 并降级为空 KG 继续建 session（`list_characters` 仍可返回空列表，`search_chunks` 仍可走 chunk 文本检索），在响应体里标记 `kg_status = "degraded"`。
6. Smoke test 脚本可选升级：加 `--from-epub <path>` flag，走新 upload 链路再调用 `/api/agent/ask`，用于端到端回归。
7. 单元测试：mock `LLMClient` 固定返回夹具 JSON，覆盖 happy path、JSON 解析失败、单 batch 超限、角色合并冲突、空 chunks 等分支；路由层用 FastAPI `TestClient` 覆盖 happy path 与降级路径。
8. 文档：在 `STATE.md` 记录本 decision 与 `MinimalKGExtractor` 首版工程量，在 `CHANGELOG.md` 记入本 ADR 与 upload 端点首次出现。

## Consequences / 后果

**变好的一面：**

- r1 可以真接受新书上传、端到端跑完 upload → ask 闭环。
- r0 / r1 代际界限不再含糊：r0 只管原始数据（ingest + store），KG 抽取明确归到 r1 的 backend 层。
- KG 提取方式可插拔：未来换 SOTA 方法不动调用方。
- adapter 层（ADR-003）得到第二个使用者（第一个是 AgentLoop），validate provider-agnostic 抽象对批量 LLM 调用场景同样适用。

**要付出的代价：**

- 多一个 150-250 行的模块 + 对应测试（约 10-15 个 test case）。
- 首版 KG 提取质量不如 v7 多轮流水线。北极星要求"以《明朝那些事儿》为基线，r1 > r0 / 微读 / ChatGPT / Claude 直通"，后续做对比实验时必须记录：r1 的 KG 来自轻量 extractor，不是 v7 流水线，该实验差异不是"r1 架构的直接能力差"。
- 上传一本书首次会触发 10-20 个 LLM 调用（batch 抽取）。需要在路由层对调用方明示"upload 非即时"，并留 SSE 或 job id 形式的异步接口空间（本 ADR 暂不展开，可在 ADR-005 book session 持久化里一起谈）。

## Alternatives Considered

- **方案 A 驳回**：把 v7 的分析管线拉回主树会把刚做完的"v7 归档"部分推翻，违背"r1 主线不依赖 legacy"的现行约定，并带进 provider 硬绑（`claude-haiku-4-5` 写死）与 `SessionData` 入参耦合等 tech debt，与 ADR-003 的 adapter 抽象冲突。
- **方案 C 驳回**：只接受已有 JSON 等于把问题踢给"谁来生成这份 JSON"，而这个"谁"当前没有实现路径 —— v7 产出链路已归档，作者手上没有可用的 r1 schema JSON。端点无法接收新书，与代际完整可用目标冲突。
- **直接跳过 KG，让 `list_characters` 永远返回空**：等价于永久放弃三工具里的一个维度。`list_characters_in_chapter` 是北极星明确列为 r1 里程碑的三工具之一，单独腐化不接受。

## 批准记录

- **待作者选择**：A / B / C
- 副管理推荐：**B**（r1 自做最简 KG 占位）
- 作者口头批准后进入实施
