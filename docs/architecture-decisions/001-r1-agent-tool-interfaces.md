# ADR-001 · r1 查询时智能代理的三个核心 tool 接口规范

## Status

**事后追认**（作者口头批准，2026-06-10 按现状追认）

- 代际：r1-agent-loop（runtime 实际走 r2 协议，见 ADR-007）
- 作者：moyu-good
- 创建日期：2026-04-20
- 最后更新：2026-06-10

---

## Context / 背景

BookScope 正在从 r0（批量预处理 + 静态展示）代际转向 r1（查询时智能代理）。r0 的根因问题已在多次 dogfood 回顾中被明确锤破：LLM 算力全部烧在 ingest 阶段，书被"冻干"成一堆静态分析产物，查询时没有任何推理能力、无法给出原文证据、交互体验形同死物。通用 RAG 也已被判定为 commodity，单纯"塞进向量库再检索"并不构成 r1 要的差异点。

r1 代际的核心假设是：**真正的价值在用户提问那一刻才开始产生**。具体形态是——用户发起提问时 agent 才启动，agent 在一个 loop 内调用一组受控的 tool 拉取必要的书籍原文片段，做 reasoning，最后返回一个带原文引用（citation）的答案。所有静态产物（v7 的 chunk、KG、角色列表）降级为这些 tool 的后端数据源，而不再是直接面向用户的最终产物。

本 ADR 要定死的，是 r1 代际 agent 唯一被允许调用的三个核心 tool 的签名。该签名一旦签字落地，就是 agent loop 实现、实验设计、基准测试、prompt engineering 等所有下游工作的地基。

tool 设计的核心约束有三条，三者不是并列，而是三个主要维度的组合：

1. **原文引用必选**：每一次 tool 调用返回的数据都必须携带原文 text 字段，不允许 agent 仅凭总结性字段作答，否则 citation 就是空话。
2. **章节 scope 支持**：用户提问常带章节范围（"前五章"、"第三部分"），tool 必须把"按章节 scope"作为一等公民参数，而不是靠 agent 自己过滤。
3. **角色过滤支持**：BookScope 的差异点之一是"以角色为第一索引"，tool 必须能直接按角色做过滤，不应把角色过滤外包给 LLM。

BookScope 现有数据层已具备作为这些 tool 后端的能力：v7 产物里的 chunk 已做过 embedding、KG 里有角色的 canonical name、章节原文在 ingest 阶段已落到 chunk store。这些产物复用，不重做。

---

## Decision / 决策

r1 代际 agent 可调用的 tool **只有下面三个**，多一不加，少一不减。所有 tool 的 schema 用 Pydantic v2 描述，返回对象必须继承 `BaseModel`，并统一包含 `source_version: str` 字段（用于 r0 / r1 产出的区分追溯，例如 `"r0-v7"`、`"r1-ingest-v1"`）。

### 共享类型

```python
from pydantic import BaseModel, Field

class ToolResultBase(BaseModel):
    """所有 tool 返回对象必须继承此基类。"""
    source_version: str = Field(
        ...,
        description="产出该数据的 ingest 代际与版本号，用于 r0 与 r1 的追溯，例如 'r0-v7'、'r1-ingest-v1'",
    )
```

### Tool 1：`search_chunks`

**用途**：按自然语言 query 在 chunk 层做语义检索，可选章节范围和角色过滤。这是 agent 最常用的 tool，用于"我想找书里讲 X 的地方"。

**输入 schema**：

```python
class SearchChunksInput(BaseModel):
    query: str = Field(
        ...,
        description="自然语言查询，由 agent 基于用户问题生成",
        min_length=1,
    )
    chapter_scope: tuple[int, int] | None = Field(
        default=None,
        description="章节范围（起始, 结束），含端点；None 表示全书",
    )
    character_filter: list[str] | None = Field(
        default=None,
        description="仅返回涉及这些角色的 chunk；传入时使用 canonical_name 匹配",
    )
    top_k: int = Field(
        default=10,
        ge=1,
        le=50,
        description="返回前 K 个匹配，上限 50 防止 agent 一次把整本书拉回",
    )
```

**输出 schema**：

```python
class ChunkMatch(ToolResultBase):
    chunk_id: str = Field(..., description="chunk 的稳定 ID，跨 r0/r1 保持一致")
    chapter: int = Field(..., description="chunk 所在章节号")
    text: str = Field(
        ...,
        description="原文片段，必含；agent 必须基于此字段做 citation",
        min_length=1,
    )
    relevance_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="与 query 的相关性分数，0-1 归一",
    )
    contains_characters: list[str] = Field(
        default_factory=list,
        description="在此 chunk 中出现的角色的 canonical_name 列表",
    )
```

返回值类型：`list[ChunkMatch]`，长度不超过 `top_k`，按 `relevance_score` 降序。

### Tool 2：`get_chapter_range`

**用途**：按章节范围拉取完整原文。用于"agent 判断光靠 chunk 不够，需要读完整章节上下文"的场景。

**输入 schema**：

```python
class GetChapterRangeInput(BaseModel):
    start_chapter: int = Field(..., ge=1, description="起始章节号（含）")
    end_chapter: int = Field(..., ge=1, description="结束章节号（含）")
```

**输出 schema**：

```python
class ChapterText(ToolResultBase):
    chapter: int = Field(..., description="章节号")
    title: str = Field(..., description="章节标题，若无则为空串")
    full_text: str = Field(..., description="章节完整原文", min_length=1)
    word_count: int = Field(..., ge=0, description="章节字数（中文按字符计）")
```

返回值类型：`list[ChapterText]`，按 `chapter` 升序。

**硬约束**：若 `sum(word_count) > 200_000`（即合计超过 20 万字），必须抛 `ChapterRangeTooLarge` 错误而不是返回，防止 agent 误把全书一把塞回 context。错误消息中必须告知 agent 实际章节数与总字数，引导其改用 `search_chunks` 或收缩范围。

### Tool 3：`list_characters_in_chapter`

**用途**：列出某章节中出现的角色及其出场分布。用于"agent 判断应该先搞清楚某章节有哪些人"的场景，这是角色过滤与后续 `search_chunks` 的前置步骤。

**输入 schema**：

```python
class ListCharactersInChapterInput(BaseModel):
    chapter: int = Field(..., ge=1, description="章节号")
```

**输出 schema**：

```python
class CharacterRef(ToolResultBase):
    name: str = Field(..., description="在该章节中出现的原始称呼（可能是别名、尊称）")
    canonical_name: str = Field(
        ...,
        description="标准化后的角色名，跨 tool 保持一致，用于 character_filter 入参",
    )
    mention_count: int = Field(..., ge=1, description="该角色在此章节中的提及次数")
    first_appearance_position: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="在章节内首次出现的相对位置，0 表示章节开头、1 表示末尾",
    )
```

返回值类型：`list[CharacterRef]`，按 `mention_count` 降序。

---

## Consequences / 后果

### 变好的

- **Agent 能力边界明确**：LLM 能做什么、不能做什么，由三个 tool 的 schema 圈死，可复现、可测试、可评估。
- **Citation 从数据层开始强制**：`ChunkMatch.text` 与 `ChapterText.full_text` 字段不可选，agent 没有机会"凭感觉概括"。
- **r0 产出不被浪费**：v7 的 chunk、KG、角色列表全部降级为这三个 tool 的后端实现细节，数据层投资得到保留。
- **分层可测**：每个 tool 可单独写单元测试（给定输入 → 期望输出），agent loop 的行为可在"工具正确"与"推理正确"两个维度分别验证，出问题时不至于黑盒。
- **与通用 RAG 拉开差距**：`chapter_scope` 与 `character_filter` 是结构化约束，纯向量检索做不到；这是 BookScope 相对 commodity RAG 的第一条真实差异。

### 变 costly 的

- **Token 成本上升**：agent 每次会话要做多轮 tool call，比 r0 一次性预处理多消耗 LLM token。作者已明确 r1 不设成本红线，此条接受。
- **代码复杂度上升**：需新增 tool dispatcher 层、错误处理层（`ChapterRangeTooLarge`、`ChunkNotFound` 等），以及 agent loop 本身。整体复杂度比 r0 高一个量级。
- **一次 ingest 投入**：三个 tool 的后端依赖 semantic index（chunk embedding）、章节原文存储、角色倒排索引。这些部分 r0 已有，但需补齐到"查询时可用"的质量；`source_version` 字段的引入需要一次全量 re-ingest 标记。
- **Schema 锁定的迁移成本**：一旦 ADR 签字，后续若发现需要第四个 tool（例如按时间线检索），属于下一个 ADR 的范畴，不可随手加字段。

---

## Alternatives Considered / 替代方案

### 替代一：单个大 tool `analyze_book(question: str) -> str`

把整个 agent 能力封成一个"问一切答一切"的万能 tool。

**拒绝原因**：这等于把 LLM 彻底黑盒化，agent 没有能力可观测性、无法分层测试、无法调参、无法做 ablation study。违反 r1 代际"把推理过程打开"的核心意图。

### 替代二：数十个细粒度 tool

例如 `get_character_detail`、`get_chapter_summary`、`get_tension_peak`、`get_relationship_between`、`get_timeline_event` 等等。

**拒绝原因**：LLM 在 tool use 场景下的 selection cost 会随 tool 数量显著上升（prompt 要塞更多 schema、选错的概率提高），而三个 tool 加上参数组合已经可以覆盖绝大部分使用场景。少即是多；缺了再加，加了难减。

### 替代三：完全 RAG 范式（无 tool 选择，全部走向量检索）

只建一个向量索引，所有查询都走 `similarity_search(query, top_k)`。

**拒绝原因**：向量检索无法表达"第三至第五章范围内"或"只要涉及角色 X 的段落"这类结构化约束。这恰恰是 BookScope 相对通用 RAG 的真实差异点——书是有结构的文本，不是扁平的文档堆。放弃结构，就等于承认自己是 commodity。

---

## 落地路径

签字后，按下列步骤推进，目标是让第一次 agent loop 集成测试具备所有必要前置条件。

1. 在 `bookscope/agent/tools/` 下新增模块骨架：
   - `base.py`：`ToolResultBase`、通用错误类型（`ChapterRangeTooLarge`、`ChunkNotFound`、`CharacterNotFound`）。
   - `search_chunks.py`、`get_chapter_range.py`、`list_characters_in_chapter.py`：每个文件一组 schema + dispatcher。
2. 每个 tool 分别写 Pydantic schema（input / output）、dispatcher 函数（接 r0 产出），并配一份单元测试。Schema 单测覆盖字段约束（`ge`、`le`、`min_length` 等），dispatcher 单测覆盖典型路径与边界（空结果、范围过大、无效角色名）。
3. 后端实现复用 r0 产出：
   - `search_chunks` 读 v7 的 chunk store + embedding index。
   - `get_chapter_range` 读章节原文存储。
   - `list_characters_in_chapter` 读 KG 里的 character mention 倒排索引。
4. 为所有产出数据补 `source_version` 字段，配一次 backfill 脚本把 r0 产物打上 `"r0-v7"` 标记。
5. 写一份 tool dispatcher（把 LLM function call 映射到本地函数），并在 dispatcher 层做错误捕获 → 结构化 error 返回 agent，而不是崩 loop。
6. r1 agent loop 的第一次集成测试前，三个 tool 的单元测试必须全绿，覆盖率不低于 80%（与项目通用门槛一致）。
7. ADR 签字后开一个 GitHub issue（建议标题：`r1-agent-loop: implement three core tools per ADR-001`），把本文档链接挂进去，作为进度追踪入口。
8. 首个集成测试案例建议选"明朝那些事儿"的一个跨章节问答（例如"朱元璋对李善长态度的变化"），验证三个 tool 的组合调用能否产出带原文引用的答案。

---

## 签字

本 ADR 由作者口头批准后生效。不再使用电子签名位——作者在对话中说"开始"即视为批准。

---

**批准记录**：

- **已批准**（作者口头，2026-04-20）
- 口头记录：作者确认"电子签名就算了，直接跟你说开始就开始"
- 进入实施阶段
