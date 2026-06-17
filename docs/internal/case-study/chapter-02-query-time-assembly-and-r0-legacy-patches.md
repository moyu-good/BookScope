# 第 2 章 · 查询时装配的代价：r0 数据层遗产与缺口修补

> **状态**：草稿 · 作者未定稿
> **时段**：2026-04-19 至 2026-04-21（第 11–15 轮）
> **覆盖 commit**：`f541306` / `e2bbf20` / `bbec6fa` / `afed961` / `02152e6`
> **与第 1 章的关系**：第 1 章讲"5 天激进的架构重构"，本章讲"五轮慢慢收尾的数据层遗产修补"——节奏对比本身就是本章的读点

---

## 一、第 1 章用到的 `upload` 端点与 `session_id`，从哪里来？

读过第 1 章的读者会记得，第 20 轮前端 MVP 里一条核心流程：

```
上传 epub → POST /api/books/upload → 拿到 session_id
→ POST /api/agent/ask { book_session_id, question } → 带 citation 的答案
```

这个流程的两个关键资产—— `POST /api/books/upload` 的完整 ingest + KG 抽取 + 持久化链路、`JSONFileSessionStorage` 的"按 session 目录存盘"结构——不是凭空出现的。它们是**第 11–15 轮五轮工作的产出**。

从第 11 轮到第 15 轮，r1 代际**没有产生新的惊艳功能**。它只做一件事：**把第 1–10 轮堆出来的"理论能跑"的 r1 大脑层，实际接到一份可持久化的数据基座上**。这个过程暴露出 r0 数据层的三个结构性缺口，并用三种不同级别的 workaround 逐个闭合。

这一章的主角不是新特性——是**遗产**与**缺口**。r1 继承 r0 的 ingest / KG / chunker 代码时，原本以为是"捡现成"。到第 4–10 轮搭 agent loop 时才发现，r0 的数据 schema 和数据 API 有好几个地方**根本没为 agent 时代设计**——agent 需要的几种反向查询，r0 都是用"一次性批量扫描"的方式算过一遍就扔。

本章按时间顺序讲五个 commit，最后反思一个问题：**三个小缺口为什么拖了五轮才修完？**

---

## 二、三个缺口的浮现：第 4–10 轮的 backend 接入史

时间倒回第 4–6 轮。r1 第 1–3 轮搭完 AgentLoop 骨架 + 三个 tool 的 Pydantic schema 后，开始逐个接入 r0 数据后端：

| Tool | 需要什么反向查询 | r0 有没有 |
|------|------------------|-----------|
| `search_chunks` | "给我关于 X 的 top-k chunk，可按章节 / 角色过滤" | 有 hybrid retriever；但**缺 chunk → chapter 映射** + **缺 chunk → characters 倒排** |
| `get_chapter_range` | "章节 A 到章节 B 的完整原文" | 没有——`BookText.raw_text` 是一大坨字符串；章节识别在 `book_chunker._detect_chapters` 里是**私有局部变量**，切完 chunk 就扔 |
| `list_characters_in_chapter` | "章节 X 出现的角色列表" | KG 层只有角色级的 `key_chapter_indices`（哪些章节出现过该角色）；**没有 chunk 级的角色倒排** |

这三个缺口在第 4–6 轮被**第一次表面化**，但 r1 副管理当时没强改 r0 的 schema——那属于代际级变动，副管理 auto-accept 权限不够。副管理的选择是**构造参数注入 workaround**：

```python
# bookscope/agent/backends/r0_search_chunks.py（第 4 轮产出）
class R0SearchChunksBackend:
    def __init__(
        self,
        store: ChunkRetrievalBackend,
        chunk_to_chapter: dict[int, int] | None = None,        # 外部注入
        chunk_index_to_characters: dict[int, list[str]] | None = None,  # 外部注入
    ) -> None:
        ...
```

```python
# bookscope/agent/backends/r0_chapter_range.py（第 5 轮产出）
class R0ChapterRangeBackend:
    def __init__(self, chapters: Iterable[R0ChapterRecord]) -> None:
        # R0ChapterRecord 由调用方在外部自己装配——先 clean 再跑私有
        # _detect_chapters 再打包。属"我们没 r0 API，调用方帮我们凑一下"
        ...
```

```python
# bookscope/agent/backends/r0_list_characters.py（第 6 轮产出）
class R0ListCharactersBackend:
    def __init__(
        self,
        kg: BookKnowledgeGraph,
        mention_counts: dict[str, int] | None = None,    # 外部注入
        first_positions: dict[str, int] | None = None,   # 外部注入
    ) -> None:
        ...
```

三个 backend 都在**构造期索要本应由 r0 数据层直接提供的辅助映射**。这把"数据层不够"这个问题推后到了"调用方装配期"——第 7 轮的 `R0BookAssembler` 就是那个"统一装配点"。

这条 workaround 路径让第 4–10 轮推进得快（10 轮里把 agent loop 从骨架推到能跑），代价是在 `docs/internal/STATE.md` 的"需作者决策"区挂了三条永久提醒：

1. ~~r0 缺失 chunk-to-chapter 映射~~（第 15 轮闭合）
2. r0 缺失 chunk-to-characters 倒排索引（**至今未闭合**，见本章第九节）
3. ~~r0 未把"按章节的完整原文"结构化持久化~~（第 14 轮部分闭合）

**这三条**是第 11–15 轮修补的主旋律。

---

## 三、第 11 轮：ADR-004 / ADR-005 双起草

时间走到第 11 轮（commit `f541306`），r1 agent loop 骨架 + 三个 tool backend 都已接入，**但 session 怎么存？书怎么上传？**这两件事还没设计。

两份 ADR 同期起草：

**ADR-004 · upload 端点策略**——"客户端如何把一本书交给 r1 并得到 session_id"。三方案：

- **A**：复活 v7 的完整预处理流水线（NER / KG / 向量索引都跑）。优点：数据齐备；代价：与 r1 "轻量索引" 哲学严重冲突，ingest 30 分钟级别
- **B**：r1 自做最简 KG（LLM-based 角色抽取 + jieba 分词 + BM25 构建）。优点：对齐 r1 哲学；代价：需要新写一个 KG 抽取器
- **C**：只收 `AnalysisResult`（把 ingest 责任推给客户端）。优点：服务端零计算；代价：非作者本人上传体验极差

**副管理推荐 B**。

**ADR-005 · book session 持久化策略**——"session 装配好的数据（BookText + chunks + KG + vector store）如何存盘"。三方案：

- **A**：JSON file per session（每 session 一个目录，包含 `metadata.json` / `book_text.json` / `chunks.json` / `kg.json` / `vector_index/`）
- **B**：SQLite 单库（一张表一个 session）
- **C**：Redis（内存 + 持久化）

**副管理推荐 A**。理由：作者 CEO 自用 + BYOK 原则 + 不引外部服务 + Python 文件 I/O 零依赖。

两份 ADR 2026-04-20 口头提交给作者。作者回的是 **"B + A"**——两个推荐都通过。没有二次讨论，没有反方案。

这条"作者一句话批准"跟第 1 章的"全部 API 化"是**同一种决策模式**——作者在主干上踩准，让副管理在枝节上跑得快。这种模式效率极高，但对**副管理起草 ADR 的完整度**要求也高：三方案的对比、每个方案的代价、推荐的理由必须列清楚，作者才有一秒决断的底气。ADR-004 和 ADR-005 加起来约 6000 字，第 11 轮副管理在文档上花的时间远超后面几轮的代码时间。

---

## 四、第 12 轮：双 ADR 实施（commit `e2bbf20`）

方案选定后第 12 轮就是实施。一次 commit 完成两件大事：

### `MinimalKGExtractor`（ADR-004B）

约 350 行。核心接口：

```python
extractor = MinimalKGExtractor(client=adapter, model="deepseek-chat")
kg = extractor.extract(chunks=chunks, book_title="...")
```

**provider-agnostic**：走 `LLMClient` Protocol（ADR-003），不耦合 DeepSeek / Anthropic / astron 任一具体 adapter。

**map-reduce 策略**：`max_chunks_per_batch=60`，每批 chunk 装进 prompt 问 LLM "这批里出现哪些角色"，每批返回一组 `{name, canonical_name, key_chapter_indices}` 的 JSON entries。全书扫一遍后，`_merge_and_build_profiles` 按 `canonical_name` 合并同一个人的别名（例如"朱重八 / 朱元璋 / 朱国瑞"合成一个 `CharacterProfile`）。

**成本**：32K 字书 = 1069 chunk / 60 = 18 个 batch ≈ 18 次 LLM 调用。按 deepseek-chat ~10s/call 估，整本书 3 分钟；按第 1 章 pilot 观测的 astron ~100s/call，30 分钟。这个成本结构第 16 轮真跑后才显形，第 12 轮落地时是理论值。

### `JSONFileSessionStorage`（ADR-005A）

`SessionStorage` Protocol + 具体实现。目录结构：

```text
data/sessions/
  <session_id>/
    metadata.json          # session_id / book_title / created_at / last_accessed_at
    book_text.json         # BookText.model_dump_json()
    chunks.json            # [ChunkResult.model_dump_json(), ...]
    kg.json                # BookKnowledgeGraph.model_dump_json()
    vector_index/          # ← 第 12 轮留白（第 13 轮闭合）
```

`BookSessionStore` 从"纯内存 dict"升级为"可选 storage 懒加载"——未命中内存时按 session_id 从磁盘 reconstitute `R0BookAssembler`，命中则直接返回。

### `POST /api/books/upload`（把两者串起来）

multipart form（`file` / `book_title` / `provider` / `api_key` / ...），返回 `BookUploadResponse { session_id, book_title, chunk_count, character_count }`。

第 12 轮测试 **366/366 全绿**（第 11 轮 309 基线 + 57：19 KG + 25 storage + 12 upload + 现有 test_agent_ask 补持久化场景）。

### 一条自认的尾巴

第 12 轮 commit message 末尾直接承认 `vector_index/` 目录留白——`SessionVectorStore` 当时**没有** `save_to_dir` / `load_from_dir`。load 时 vector store 一律为 `None`，agent 的 `search_chunks` 只能走 BM25 纯算法路径（reranker 也依赖 vector，但当时 reranker 还没被第 16 轮活检，问题没显形）。

自认尾巴这个动作很重要——它让第 13 轮有明确的"我们知道这条尾巴在哪儿"开始点，不用再重新审计代码找它。

---

## 五、第 13 轮：`SessionVectorStore` 持久化（commit `bbec6fa`）

直奔第 12 轮的尾巴去。

### 关键设计：manifest 驱动的 provider 契约

存盘不只是把数据写进磁盘——**存盘必须记录"是哪个 embedding provider 算的"**。不然 load 时用另一个 provider 的查询向量对上旧的文档向量，会得到无意义的相似度。

`manifest.json` 长这样：

```json
{
  "version": 1,
  "chunk_count": 1069,
  "has_vector": true,
  "embedding_provider": "SiliconFlow/BAAI/bge-m3",
  "embedding_dim": 1024
}
```

`load_from_dir` 做两道校验：

1. 版本号匹配（未来 schema 变更时给明确的拒绝信号）
2. 当前进程的 provider 名必须与 manifest 一致——不一致抛 `VectorStoreProviderMismatch`

ADR-005 明文"**不允许静默降级到错模型**"——这条契约在第 13 轮用代码落地。如果未来作者换 provider，旧 session 会主动失效，必须重建；**不能**在用户不知道的情况下拿旧向量去匹配新查询。

### 降级的严格边界

load 路径上还有个判断："vector index 损坏时应该怎么办？"

最终选择：**记 warning → vector_store 降级为 `None` → 让 session 整体继续可用**。理由：vector store 可以随时从 chunks 重建，是"可再生的性能加速器"；但 book / chunks / KG 是**权威状态**，不能因为一个加速器丢了就中断 session。

这条"权威 vs 可再生"的分区，在第 13 轮 commit 里写得很显眼——是后续所有缓存/索引设计的默认姿态。

### 数字

第 13 轮新增 21 个测试（17 个 vector_store 持久化 + 4 个 JSONFileSessionStorage vector_index 集成），全量 **387/387** 全绿。

---

## 六、第 14 轮：`detect_chapters` 公共化（commit `afed961`）

第 14 轮动手处理 STATE 里第 3 条"需作者决策"：**r0 未把章节原文做结构化持久化**。

副管理没动 schema（那是代际级），只做一件小事：把 `book_chunker._detect_chapters` 的下划线去掉，改为 `detect_chapters`，提升为公共 API。文件末尾加 `_detect_chapters = detect_chapters` 作为 backcompat alias 保住 legacy/v7 和任何外部 vendored 调用方。

单一 rename 为什么要单独一轮？因为 r1 的两个地方（`r0_chapter_range.py` 和 `get_chapter_range.py` 两个 docstring 以及 `R0BookAssembler._compute_chapter_records`）原本在调用 `book_chunker._detect_chapters`——**跨包 import 一个下划线开头的符号**。Python 不禁止，但是**严重违反包封装约定**：任何时候上游重写那个函数名都会默默破坏 r1。

第 14 轮的本质是**把隐式依赖提升为显式依赖**。rename 零行为改动，但把"r1 违规依赖 r0 私有 API"这条坏味道从代码库里扫掉。新增 `tests/test_book_chunker_public_api.py`（7 用例覆盖头章切分 / 无章节 / 序章 / 短引子丢弃 / 长标题行豁免 / alias 一致性 / alias 可调用），全量 **394/394** 绿。

这是那种"**不做没事、做了让未来少一次诡异 bug**"的工程投入。副管理 auto-accept 范围内——不需要作者批准。

---

## 七、第 15 轮：`ChunkResult.chapter` 字段（commit `02152e6`）

第 15 轮闭合 STATE 第 1 条缺口——**chunk-to-chapter 映射缺失**。

这个缺口此前的 workaround 是：`R0BookAssembler._compute_chunk_to_chapter_map` 从 chunk 文本首行用 regex 扒 `第 X 章` 模式反向推断章节号。问题一堆：

- chunk 首行不一定是章节头（中间切片常见）
- 中文数字要映射（`十三` / `二十` / `一百零三` 各种形态）
- 识别失败时只能返回 `None`，agent 的 chapter_scope 过滤完全落空

正确解法是 **schema 级修正**：给 `ChunkResult` 加一个 `chapter: int | None` 字段，`chunk_book` 在切 chunk 的同时把 `detect_chapters` 算过的章节号**直接填进去**。

这是一次**代际级 schema 变动**，副管理 auto-accept 权限不够。第 15 轮的决策流程：

1. 副管理在 STATE 里准备了 `escalation c` 卡片（说明缺口、方案、向后兼容策略）
2. 作者**口头批准**："2026-04-21 批准 escalation c"
3. 副管理实施：加字段 + 更新 `chunk_book` + `R0BookAssembler` 的快路径 + 向后兼容的 fallback（老 JSON 缺字段时默认 `None`，退回 regex 路径）

`ChunkResult.chapter` 字段的 docstring 特意写了一条契约：

> r1 assembler 负责 0→>=1 的 normalize，消费方不要二次解释

这条契约是为了防止下游（agent / 前端 / 未来的消费者）对 `chapter=0` 有不同解读——有人认为 0 是序章，有人认为 0 是"章节未识别"。集中解释权落在 assembler，消费方按正整数用就行。

15 个测试新增（5 models + 3 chunker + 2 assembler），全量 **404/404** 绿。

这一轮的时间成本远超代码量——`chunk_book` 一行改动（`chapter=ch_num`），但**围绕它的向后兼容策略讨论 + 单测设计 + STATE 记录的 escalation 决策流程**占了大半个轮次。代际级动作就是这个代价。

---

## 八、未闭合的缺口：chunk-to-characters 倒排索引

STATE 第 2 条"需作者决策"缺口——**r0 没有 chunk 级的角色倒排索引**——截至本章成稿时仍是 workaround 状态。

现状：`R0SearchChunksBackend` 依然通过构造参数 `chunk_index_to_characters: dict[int, list[str]]` 接受外部注入；没注入时 agent 的 `character_filter` 参数一律过滤为空（保守：没证据就不命中）。

**为什么没闭合**？三个理由叠加：

1. **优先级**：`search_chunks` 的 `character_filter` 是 agent 偶尔用到的 optional filter。agent 通常先跑语义 query（`search_chunks(query="朱元璋与李善长的关系")`）就够，很少精确地 `character_filter=["李善长"]`。缺口的痛还没到"必须修"
2. **工程代价**：正确做法是在 r0 NER / KG 阶段顺手落一份 `dict[int, list[str]]` 进 `BookKnowledgeGraph`。但这会让 KG schema 再增一字段，而 KG 本身还在演进（ADR-004B 的 MinimalKGExtractor 刚落地 5 轮），现在动 schema 等于往两个变动方向叠加
3. **MinimalKGExtractor 的抽取粒度**：extractor 按 batch 处理（60 chunk / batch），"角色出现在哪个 chunk" 这个信息在 batch 内是可见的，但合并阶段按 `canonical_name` 聚合时丢失了 per-chunk 粒度。要重拾需要改 extractor 的 merge 逻辑——也是个代际级改动

这条缺口预计会**留到 r2 代际**或者"某个正式实验暴露它的优先级"时再处理。r1 代际的 `STATE.md` 会一直把它挂在"需作者决策"区做提醒。

这不是耻辱，是**有意识的技术债**。

---

## 九、反思：三个缺口为什么拖了五轮？

第 11–15 轮一共跨了三个日历日（2026-04-19 至 04-21）。每轮实际代码量都不大——第 14 轮就是一个 rename；第 15 轮就是加一个字段；第 13 轮密度最高但也只有约 200 行。

**拖的原因不是技术难度，是三层决策边界**：

1. **副管理 auto-accept 边界**：加字段改 schema 是代际级，副管理不自动动。第 15 轮必须显式向作者递 escalation c 等口头批准
2. **r0 / r1 代际边界**：副管理倾向 "**不改 r0 schema**" 做 workaround（构造参数注入、公共化下划线函数），因为 r0 的测试覆盖、文档、用户假设（legacy/v7 可能还有下游）都是风险面。每次动 schema 必须判断"是否值得跨越这道边界"
3. **ADR 级决策链**：第 11 轮两份 ADR 起草、第 12 轮实施——加起来两个日历日；第 13 轮 manifest 契约设计 + provider 不匹配时的错误路径选择——也需要判断而不是拍脑袋写

所以五轮分布的不是"代码复杂度"，是**判断的颗粒度**。每一轮副管理在做的工作是"**在当前信息下把哪条缺口用哪种粒度闭合**"——有的用 workaround、有的用 public rename、有的 escalate 到 schema 字段。这些判断靠堆工时不来，靠"停下来想清楚"。

**代价 vs 收益**：三轮收尾 + 两份 ADR + 完整测试覆盖（404 全绿）+ ADR-005A 的 manifest 契约——这些让第 16 轮首次真 API 跑通时，**数据层没有任何意外**。整个第 1 章的"5 天激进重构"能在几小时内发生，前提是第 11–15 轮已经把数据基座夯实。

如果没有第 11–15 轮的慢修补，第 16 轮第一次真跑就会在"session 持久化丢了什么"或者"chunk 没章节号怎么 filter"这类小问题上撞一堆墙。**第 1 章能以那个节奏发生，是第 2 章慢节奏的红利**。

---

## 十、指向下一章

第 11–15 轮的慢节奏工作之所以能存在，是因为**r1 的 agent loop 框架选择 + provider adapter 层**已经在第 7–10 轮确立。没有 `LLMClient` Protocol，`MinimalKGExtractor` 就没法 provider-agnostic；没有 AgentLoop 自建轻量循环，第 12 轮没法把 KG 抽取和 upload 端点串成一条路径。

第 3 章将回到第 7–10 轮，讲 **ADR-002 v2 的 provider 选择翻案**——为什么一开始副管理选了 Anthropic 原生 tool use，后来被作者的 "LLM 国内优先" 一句话推翻，重做成 DeepSeek function calling 默认 + Anthropic 备选，以及 Adapter 层如何消化"Anthropic 风格"和"OpenAI 风格" tool use 之间的双向格式转换。

那一章的读点是：**ADR 被推翻后，代码层面真实发生了什么重构，以及这个重构为什么没打破第 11–15 轮的工作**。

---

## 附录：本章涉及的资料索引

- ADR-004 · upload 端点策略（方案 B：r1 自做最简 KG）
- ADR-005 · book session 持久化策略（方案 A：JSON per session）
- `bookscope/agent/backends/minimal_kg_extractor.py`
- `bookscope/agent/backends/r0_search_chunks.py` / `r0_chapter_range.py` / `r0_list_characters.py` / `r0_assembler.py`
- `bookscope/api/routes/books.py`（upload 端点）
- `bookscope/api/session_storage.py`（ADR-005A 实现）
- `bookscope/store/vector_store.py`（第 13 轮持久化 API）
- `bookscope/ingest/book_chunker.py`（第 14 轮公共化 + 第 15 轮填 chapter）
- `bookscope/models/schemas.py`（第 15 轮 `ChunkResult.chapter`）
- STATE.md 第 11–15 轮多次更新
- Commit chain：`f541306` · `e2bbf20` · `bbec6fa` · `afed961` · `02152e6`
