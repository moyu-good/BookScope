"""Tool 1：search_chunks — 按自然语言 query 在 chunk 层做语义检索。

ADR-001 约束：章节 scope 和角色过滤是一等公民参数，不外包给 LLM。
本文件只负责 schema + dispatcher 骨架；真正的检索后端（FAISS + BM25）
由 ChunkRetrievalBackend Protocol 定义。

**默认 backend 实现**：
    ``bookscope.agent.backends.r0_search_chunks.R0SearchChunksBackend``——
    把 r0 v7 的 ``SessionVectorStore``（FAISS + BM25 RRF 融合）包装成
    本 Protocol 形态。构造时需外部补齐 chunk-to-chapter 映射与
    chunk-to-characters 映射，因为 r0 的 ``ChunkResult`` 不带这两份元数据。

dispatcher 本身目前仍抛 ``NotImplementedError``（骨架签名锁定），
下一轮把骨架切换为 "直接 delegate" 时只需把 body 改为
``return backend.retrieve(...)`` 即可，signature 不动。
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from bookscope.agent.tools.schemas import ChunkMatch


class SearchChunksInput(BaseModel):
    """`search_chunks` 的入参 schema。"""

    model_config = ConfigDict(frozen=True)

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


class ChunkRetrievalBackend(Protocol):
    """chunk 检索后端的抽象接口。

    r1 首轮接入 v7 的 FAISS + BM25 混合检索；后续可替换为任何实现，
    只要满足"返回按 relevance_score 降序的 ChunkMatch 列表"契约。
    """

    def retrieve(
        self,
        query: str,
        chapter_scope: tuple[int, int] | None,
        character_filter: list[str] | None,
        top_k: int,
    ) -> list[ChunkMatch]:
        """执行一次带 scope 和 character 过滤的 top-k 检索。"""
        ...


def search_chunks(
    params: SearchChunksInput,
    backend: ChunkRetrievalBackend,
) -> list[ChunkMatch]:
    """schema 层入口，定义参数契约。

    实际分发路径：AgentLoop._dispatch_tool → search_chunks_cached
    （bookscope/agent/_internal/search_cache.py），再调 backend.retrieve()。
    本函数不在生产路径上被调用，保留作 Protocol 契约的可读说明。
    """
    return backend.retrieve(
        query=params.query,
        chapter_scope=params.chapter_scope,
        character_filter=params.character_filter,
        top_k=params.top_k,
    )
