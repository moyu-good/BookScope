"""Tool 2：get_chapter_range — 按章节范围拉取完整原文。

ADR-001 硬约束：合计字数 > 200_000 时必须抛 ChapterRangeTooLarge，
禁止 agent 把整本长篇一把塞回 context。

**默认 backend 实现**：
    ``bookscope.agent.backends.r0_chapter_range.R0ChapterRangeBackend``——
    把一份按章节组织的 r0 原文清单包装成本 Protocol 形态。r0 没有把
    章节原文做结构化持久化（章节三元组只存在于 ``book_chunker.detect_chapters``
    的返回值中），因此该 backend 要求调用方在构造时显式传入
    ``list[R0ChapterRecord]``——详见该模块 docstring。多数调用方可以直接
    用 :meth:`R0BookAssembler.build_chapter_range_backend` 一键装配。
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bookscope.agent.tools.errors import ChapterRangeTooLarge
from bookscope.agent.tools.schemas import ChapterText

CHAPTER_RANGE_WORD_LIMIT: int = 200_000
"""ADR-001 定义的章节范围合计字数上限。"""


class GetChapterRangeInput(BaseModel):
    """`get_chapter_range` 的入参 schema。

    start_chapter 必须 <= end_chapter，端点皆含。
    """

    model_config = ConfigDict(frozen=True)

    start_chapter: int = Field(..., ge=1, description="起始章节号（含）")
    end_chapter: int = Field(..., ge=1, description="结束章节号（含）")

    @model_validator(mode="after")
    def _check_order(self) -> GetChapterRangeInput:
        if self.start_chapter > self.end_chapter:
            raise ValueError(
                "start_chapter 必须 <= end_chapter"
                f"（got start={self.start_chapter}, end={self.end_chapter}）"
            )
        return self


class ChapterTextBackend(Protocol):
    """章节原文后端的抽象接口。

    r1 首轮接入 r0 ingest 阶段落盘的章节原文存储。
    """

    def total_words(self, start: int, end: int) -> int:
        """返回 [start, end] 区间（含端点）章节的合计字数。"""
        ...

    def get_chapters(self, start: int, end: int) -> list[ChapterText]:
        """返回 [start, end] 区间（含端点）章节的完整原文，按章节号升序。"""
        ...


def get_chapter_range(
    params: GetChapterRangeInput,
    backend: ChapterTextBackend,
) -> list[ChapterText]:
    """按章节范围拉取完整原文。

    执行顺序：先问 backend 合计字数做硬上限检查，再拉取原文。
    这样即便 backend 实现里拉原文很贵，超限的请求也能在 O(1) metadata
    查询后就被拒绝，不会做无谓的 I/O。

    Args:
        params: 经过 schema 校验的入参。
        backend: 实现 ChapterTextBackend Protocol 的具体后端。

    Returns:
        按 chapter 升序的 ChapterText 列表。

    Raises:
        ChapterRangeTooLarge: 合计字数 > CHAPTER_RANGE_WORD_LIMIT。
    """
    word_count = backend.total_words(params.start_chapter, params.end_chapter)
    if word_count > CHAPTER_RANGE_WORD_LIMIT:
        raise ChapterRangeTooLarge(
            word_count=word_count,
            limit=CHAPTER_RANGE_WORD_LIMIT,
        )
    return backend.get_chapters(params.start_chapter, params.end_chapter)
