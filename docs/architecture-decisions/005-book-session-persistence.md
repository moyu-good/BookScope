# ADR-005：book session 持久化策略 —— JSON per session vs SQLite vs Redis

## Status

**事后追认**（作者口头批准，2026-06-10 按现状追认；方案 A 已实现为 `JSONFileSessionStorage`）

- 代际：r1-agent-loop
- 起草：副管理
- 创建日期：2026-04-20
- 最后更新：2026-06-10
- 已实现：**方案 A**（JSON file per session，见 `bookscope/api/session_storage.py`）

## Context / 背景

当前 `bookscope/api/book_sessions.py` 的 `BookSessionStore` 是纯内存实现：一个 `dict[str, R0BookAssembler]` 加一把 `threading.Lock`，外加模块级单例。进程退出时全部 session 随内存蒸发。这种实现在 r1 开发期跑 smoke test 与单测够用，但作者把 BookScope 作为长线自用工具，每次重启都要重新 ingest 一本 50 万字的书、重建 KG、重算 FAISS 索引，是不可接受的。

每个 book session 保存的状态来自已装配好的 `R0BookAssembler` 实例，内部挂着以下四部分（见 `bookscope/agent/backends/r0_assembler.py`）：

- `BookText`：原始 `raw_text` + `title` + `language` + `word_count`，按《明朝那些事儿》第一卷单卷估算约 50 万字符，序列化 JSON 体量约 1-2 MB。
- `list[ChunkResult]`：约 400 个 chunk，每个携带 `index` / `text` / `word_count`，合计 JSON 体量约 2-4 MB。
- `BookKnowledgeGraph`：`chapter_summaries` + `chapter_analyses` + `characters` + `narrative_rhythm` 等，JSON 体量 100 KB-1 MB 级。
- 可选 `SessionVectorStore`：BM25 倒排 + FAISS IndexFlatIP（1024 维，约 400 向量），合计约 2-10 MB；**该组件可选，丢失后可重建，但重建昂贵（embedding provider 批量请求 + FAISS 建索引，按国内 provider 估算需 10-30 秒）**。

此外需要跟踪会话级元数据：`session_id`、`book_title`、`created_at`、`last_accessed_at`。

使用场景：单用户（作者本人）自用，典型并发 1-10 个 session，session 级 TTL 不在本 ADR 范围。

**关键约束**（来自 `docs/internal/NORTH_STAR.md`）：

- BYOK 原则：不嵌入任何托管服务或 hosted 数据库。
- 不引入 GPU 依赖：Web 产品必须 CPU 可跑。
- 国内网络优先：外部服务（Redis / PostgreSQL）会额外增加作者的本地部署负担。
- Python 3.11+，Pydantic v2。

**已有资产**：`bookscope/store/repository.py` 的 `Repository` 类已经沉淀了"JSON-on-disk + 按书 slug 建文件"的模式，本 ADR 的任何方案都应优先考虑能否与该习惯对齐。`bookscope/store/vector_store.py` 的 `SessionVectorStore` **当前尚无 save / load API**，这是本 ADR 需要显式补齐的工程缺口。

## Decision

**Status: 待作者选择。副管理推荐方案 A。**

以下三个候选方案，每个给出实现形态、成本、收益、风险四栏。

### 方案 A：JSON file per session（副管理推荐）

**怎么做**

每个 session 落盘为独立目录，结构如下：

```text
data/sessions/
  <session_id>/
    metadata.json          # {session_id, book_title, created_at, last_accessed_at}
    book_text.json         # BookText.model_dump_json()
    chunks.json            # [ChunkResult.model_dump_json(), ...]
    kg.json                # BookKnowledgeGraph.model_dump_json()
    vector_index/
      faiss.index          # FAISS.write_index 产出的二进制
      bm25.pkl             # BM25 倒排（jieba tokenized + doc freqs）
      manifest.json        # 记录 embedding provider 名称、维度、chunk 数
```

服务启动时扫一遍 `data/sessions/*/metadata.json`，在内存里维护 `session_id → 路径` 轻索引；`R0BookAssembler` 本体采用 **懒加载**——只在 `BookSessionStore.get(session_id)` 首次命中该 id 时从磁盘反序列化，命中后缓存在内存直至进程退出。

**成本**

- 中等代码量：~200 行（save + load + manifest 管理 + 懒加载调度）+ 对 `SessionVectorStore` 补 `save_to_dir` / `load_from_dir` 两个方法（约 60 行）。
- 单 session 反序列化在 50 万字规模下测得约 0.5-1 秒（Pydantic 反序列化是瓶颈）；懒加载策略把这个成本摊到首次访问时，启动期零 IO。

**收益**

- 零外部依赖，完全本地文件系统即可，符合 BYOK 本地化精神。
- 文件可读：作者可直接打开 `kg.json` 人眼审阅 KG 提取质量，这是 r1 开发期宝贵的调试手段。
- 迁移备份简单：`rsync -a data/sessions/ backup/` 即完成；跨机器搬迁也只是复制目录。
- 与 `Repository` 已有的 JSON-on-disk 习惯一致，零新概念引入。
- 演化路径清晰：未来 r2 若要切到 SQLite 或 Postgres，只需在 `SessionStorage` Protocol 下追加新 adapter，不冲击上层。

**风险**

- 最低。文件系统崩溃会丢该 session 的数据，但既无外部服务就没有额外故障面；作者可自行做 rsync 备份。
- 单 session 首次加载 0.5-1 秒属可接受延迟，后续访问命中内存缓存。

### 方案 B：SQLite

**怎么做**

单文件 SQLite 作为 session store。schema：

```sql
CREATE TABLE book_sessions (
    session_id         TEXT PRIMARY KEY,
    book_title         TEXT NOT NULL,
    created_at         TEXT NOT NULL,   -- ISO-8601 UTC
    last_accessed_at   TEXT NOT NULL,
    book_text_blob     BLOB NOT NULL,
    chunks_blob        BLOB NOT NULL,
    kg_blob            BLOB NOT NULL,
    vector_index_path  TEXT             -- 指向 data/sessions/<id>/vector_index/
);

CREATE INDEX idx_last_accessed ON book_sessions(last_accessed_at);
```

文本类字段序列化为 UTF-8 编码的 JSON bytes 存入 BLOB；vector_index 因体量大仍留在独立目录，库里只存路径。

**成本**

- 无新增 pip 依赖（`sqlite3` 是 Python 标准库）。
- ~200 行 CRUD + 连接池管理 + 事务封装。
- 需要决定 BLOB 序列化约定（纯 JSON bytes 最安全；pickle 跨 Python 版本脆弱；msgpack 要多引一个依赖）。

**收益**

- 单文件便于备份、锁与并发由 SQLite 引擎托管，ACID 事务天然保证。
- 查询灵活：按 `last_accessed_at` 排序、按 `book_title` LIKE 过滤等都是一句 SQL。
- 若未来作者想实现"session 列表分页 + 按时间过滤"的 UI，SQL 比目录扫描更顺手。

**风险**

- 对单用户 1-10 个 session 的场景属过度工程，业务查询需求实际上不存在。
- BLOB 内容不可读：作者调试 KG 时必须先 `sqlite3 data/bookscope.db "SELECT kg_blob FROM ..."` 再反序列化，开发期调试链路变长。
- BLOB 跨版本兼容：若未来改 Pydantic schema，反序列化失败不会被 SQLite 层感知，只能在 `model_validate_json` 时报错，诊断路径比 JSON 文件更绕。

### 方案 C：Redis + serialization

**怎么做**

外部 Redis 作 session store，每 session 序列化成 `book_session:<session_id>` 的 Hash，字段对应 BookText / ChunkResult / KG 的 JSON 字符串；vector_index 由于体量超 Redis 推荐值（10 MB+）仍放本地目录。作者需自行跑 Redis（本机 brew / Docker）并在配置里填连接串。

**成本**

- 引入 `redis` Python 客户端依赖 + 外部 Redis 实例运维。
- ~150 行 CRUD（Redis 客户端 API 比 SQLite 简洁，但多一层连接健康检查）。
- 网络往返延迟，即使本机 Redis 也有 1-2 ms 往返，高频访问时累计影响可见。

**收益**

- 延迟最低（纯内存 + O(1) Hash 访问）。
- 可扩展到多进程 / 多机场景。

**风险**

- 违反"不依赖外部服务"的隐含原则（NORTH_STAR 虽未显式禁 Redis，但 BYOK + 不嵌入 hosted LLM 的精神延伸到基础设施层就是"作者跑起 BookScope 不应要求额外运维"）。
- 单用户场景下纯度过度：作者不会并发多进程，Redis 的所有优势都用不上。
- 作者需要理解 Redis 命令才能调试 session 存储，开发期心智负担上升。
- Redis 默认无持久化或 AOF/RDB 配置不当会导致进程重启丢 session，又得让作者维护 `redis.conf`——跟 ADR 的出发点背道而驰。

### 推荐理由

副管理推荐 **方案 A**，四点理由按权重排序：

1. **单用户零外部依赖**：作者自己跑 BookScope，不应被要求额外起 Redis / 建 SQLite schema / 理解二进制 blob 格式。JSON + 目录是心智最轻的形态。
2. **文件可见性是资产不是缺点**：r1 开发期作者会频繁人工审阅 `kg.json` 验证 KG 提取质量；SQLite BLOB 会埋没这个能力，Redis 更甚。调试路径短于一切短期性能增益。
3. **演化路径清晰**：若未来 r2 或多用户部署需要数据库，新增 `SQLiteSessionStorage` 或 `PostgreSQLSessionStorage` 作为 `SessionStorage` Protocol 的新 adapter 即可（adapter 模式复用 ADR-003 的抽象套路），方案 A 不会成为阻碍。
4. **与 r0 既有 Repository 习惯一致**：统一"JSON-on-disk 按 slug / id 建目录"的持久化心智模型，新成员（或未来的副管理）理解一份就够。

方案 B 对单用户场景过度工程；方案 C 违反"无外部服务"的隐含精神。

### 方案 A 落地要点

1. 新建 `bookscope/api/session_storage.py`，内含 `SessionStorage` Protocol 与 `JSONFileSessionStorage` 实现。
2. 定义 Protocol：

   ```python
   from pathlib import Path
   from typing import Protocol

   from bookscope.agent.backends.r0_assembler import R0BookAssembler


   class SessionStorage(Protocol):
       """Book session 持久化后端抽象。

       实现方负责把 R0BookAssembler 的四份内部状态序列化到后端存储，
       反过来也能无损还原。加载失败时抛 SessionLoadError（新增异常）。
       """

       def save(self, session_id: str, assembler: R0BookAssembler) -> None:
           ...

       def load(self, session_id: str) -> R0BookAssembler:
           ...

       def list_all(self) -> list[str]:
           ...

       def delete(self, session_id: str) -> None:
           ...
   ```

3. 实现 `JSONFileSessionStorage(root: Path)`：`save` 把 BookText / chunks / KG 分别写到 `root/<id>/*.json`，并调用新增的 `SessionVectorStore.save_to_dir(root/<id>/vector_index)`；`load` 反向重建并把 vector_store 作为可选参数喂回 `R0BookAssembler`。
4. 给 `SessionVectorStore` 补 `save_to_dir(path: Path) -> None` 与 `load_from_dir(path: Path) -> SessionVectorStore` 类方法：前者用 `faiss.write_index` 写二进制 + `pickle.dump` 存 BM25 状态 + 写 manifest；后者反向，并校验 manifest 里的 embedding provider 名称与当前配置匹配（不匹配时抛错而非静默降级）。
5. 改造 `BookSessionStore`：构造函数新增可选 `storage: SessionStorage | None` 参数；`get(session_id)` 命中内存时直接返回，未命中则先查 `storage.list_all()`，存在则调用 `storage.load` 懒加载；`register` 时同步调用 `storage.save`。
6. 在 `bookscope/api/dependencies.py` 的 `get_book_session_store()` 里，默认注入 `JSONFileSessionStorage(root=Path("data/sessions"))`；测试 fixture 可注入 `tmp_path` 或纯内存替身。
7. 单元测试：
   - `tests/test_json_file_session_storage.py`：save / load roundtrip 对所有字段（BookText、chunks、KG）做深等价断言；list_all / delete 的行为；非法目录结构的错误处理；manifest 不匹配时拒绝 load。
   - `tests/test_vector_store_persistence.py`：`SessionVectorStore` 的 save_to_dir / load_from_dir roundtrip，BM25 搜索结果一致，FAISS ntotal 一致。
   - 扩展 `tests/test_agent_ask.py`：追加"注册 session → 销毁 store → 重建 store 指向同一目录 → 访问同 id"的端到端场景，使用 `tmp_path` fixture。
8. 文档同步：`README.md` 增补"持久化目录 `data/sessions/`"章节；`CHANGELOG.md` 记录 session 持久化上线。
9. 性能参考：《明朝那些事儿》第一卷单 session 预估总体量 10-50 MB；load 实测应 < 1 秒，save 实测应 < 2 秒（FAISS 二进制写入是主要耗时）。

可选增强（不阻塞本 ADR 落地）：

- 追加 `POST /api/sessions/{session_id}/flush` 端点让作者显式触发全量 save。
- `data/sessions/` 的 TTL / LRU 淘汰策略留到后续独立 ADR，本版不做。

## Consequences / 后果

**变好的一面**

- 进程重启保留所有 session 状态，免除重新 ingest + KG 抽取 + 向量建索引的 30 秒到数分钟延迟。
- 作者可直接在 `data/sessions/<id>/` 检查 KG、chunks、metadata，开发期调试链路最短。
- 迁移备份只需复制目录，跨机器搬迁零摩擦。
- `SessionStorage` Protocol 留出未来切换后端的扩展点，不阻塞 r2 往数据库方向演进。

**要付出的代价**

- 约 260 行新代码（storage 模块 + vector_store 扩展）+ 对应测试约 150 行。
- `data/sessions/` 会随使用积累，需要作者按需清理；本 ADR 不定 TTL 策略。
- `SessionVectorStore` 的二进制持久化依赖 FAISS 与 jieba 版本兼容性，若未来大版本变更 BM25 或 FAISS，需要 manifest 校验逻辑拒绝不兼容的旧快照。

## Alternatives Reconsidered / 替代方案

方案 B SQLite 在单用户 1-10 session 的实际负载下，业务上根本用不到 ACID 事务与 SQL 查询能力；BLOB 不可读还恶化调试体验，驳回。方案 C Redis 强制作者运维外部服务，违背 BYOK 精神；本机延迟优势在单用户场景无需求，驳回。两者都可作为未来多用户 / 生产部署的候选 adapter，但 r1 当前阶段不实施。

## 批准记录

- **待作者选择**：A / B / C
- 副管理推荐：**A**（JSON file per session）
- 作者口头批准后进入实施阶段，并由副管理完成落地要点第 1-9 项
