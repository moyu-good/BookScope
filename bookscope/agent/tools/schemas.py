"""ADR-001 三个 tool 的共享输出类型与 source_version 字段类型。

本模块集中定义 agent 可见的 Pydantic 返回对象：ChunkMatch、ChapterText、
CharacterRef。所有返回对象都是 frozen——agent 不应该也无法原地修改 tool
返回的数据，这是 r1 代际"数据从 backend 单向流向 agent"的硬约束。

source_version 字段采用 Literal["r0", "r1"]，用于追溯每条数据是来自 r0
批量预处理产出（例如 v7 的 chunk store）还是 r1 在线重新生成的产物。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SourceVersion = Literal["r0", "r1"]
"""数据产出代际标记。

- ``"r0"``：来自 r0 批量预处理（ingest 阶段）的存量产物。
- ``"r1"``：来自 r1 在线 agent loop 重新生成或补齐的数据。
"""


class ChunkMatch(BaseModel):
    """`search_chunks` 的单条命中结果。

    agent 必须基于 ``text`` 字段做 citation，不允许只引用 chunk_id。
    """

    model_config = ConfigDict(frozen=True)

    chunk_id: str = Field(..., description="chunk 的稳定 ID，跨 r0/r1 保持一致")
    chapter: int = Field(..., description="chunk 所在章节号", ge=1)
    text: str = Field(
        ...,
        description="原文片段；agent 必须基于此字段做 citation",
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
    source_version: SourceVersion = Field(
        ...,
        description="产出该 chunk 的代际标记（r0 / r1）",
    )
    retrieval_mode: str | None = Field(
        default=None,
        description=(
            "产出该 chunk 时检索层的实际模式（WP2a 检索降级可见 + "
            "WP-reranker-api rerank 留痕），自由字符串、加值不改 schema 结构："
            '"hybrid"（BM25 + 向量融合）、"bm25_only"（embedding 不可用，降级'
            '纯关键词检索）；叠了 rerank 且真跑成功时升成 "hybrid_rerank" / '
            '"bm25_rerank"（没 key / 关了 / rerank API 失败则保持 "hybrid" / '
            '"bm25_only" 不变）；store 不支持该属性时为 None（向后兼容）'
        ),
    )


class ChapterText(BaseModel):
    """`get_chapter_range` 返回的单个完整章节原文。"""

    model_config = ConfigDict(frozen=True)

    chapter: int = Field(..., description="章节号", ge=1)
    title: str = Field(..., description="章节标题，若无则为空串")
    full_text: str = Field(
        ...,
        description="章节完整原文",
        min_length=1,
    )
    word_count: int = Field(
        ...,
        ge=0,
        description="章节字数（中文按字符计）",
    )
    source_version: SourceVersion = Field(
        ...,
        description="产出该章节文本的代际标记（r0 / r1）",
    )


class CharacterRef(BaseModel):
    """`list_characters_in_chapter` 返回的单个角色出场信息。"""

    model_config = ConfigDict(frozen=True)

    name: str = Field(
        ...,
        description="在该章节中出现的原始称呼（可能是别名、尊称）",
    )
    canonical_name: str = Field(
        ...,
        description="标准化后的角色名，跨 tool 保持一致，用于 character_filter 入参",
    )
    mention_count: int = Field(
        ...,
        ge=1,
        description="该角色在此章节中的提及次数",
    )
    first_appearance_position: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="在章节内首次出现的相对位置，0 表示章节开头、1 表示末尾",
    )
    source_version: SourceVersion = Field(
        ...,
        description="产出该角色索引的代际标记（r0 / r1）",
    )
