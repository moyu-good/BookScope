"""Tool 3：list_characters_in_chapter — 列出某章节中出现的角色。

ADR-001 用途：agent 在 `search_chunks` 前用此 tool 先看清"本章有谁"，
是 character_filter 参数的前置步骤，避免 agent 瞎猜角色名。

**默认 backend 实现**：
    ``bookscope.agent.backends.r0_list_characters.R0ListCharactersBackend``——
    把 r0 KG 的 ``CharacterProfile`` 列表包装成本 Protocol 形态。
    r0 只做到章节粒度（``key_chapter_indices``），缺 ``mention_count`` 与
    ``first_appearance_position``，因此该 backend 要求调用方在构造时
    显式传入 ``chapter_character_map`` 并按需提供精确 ``mention_counts`` /
    ``first_positions`` 覆盖默认回退——详见该模块 docstring。
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from bookscope.agent.tools.schemas import CharacterRef


class ListCharactersInChapterInput(BaseModel):
    """`list_characters_in_chapter` 的入参 schema。"""

    model_config = ConfigDict(frozen=True)

    chapter: int = Field(..., ge=1, description="章节号")


class CharacterIndexBackend(Protocol):
    """角色倒排索引后端的抽象接口。

    r1 首轮接入 r0 KG 抽取产物中的 character mention 倒排索引。
    """

    def characters_in(self, chapter: int) -> list[CharacterRef]:
        """返回该章节中出现的全部角色，按 mention_count 降序。"""
        ...


def list_characters_in_chapter(
    params: ListCharactersInChapterInput,
    backend: CharacterIndexBackend,
) -> list[CharacterRef]:
    """按章节号列出角色。

    本 tool 逻辑极薄——直接 delegate 到 backend；
    后端负责保证按 mention_count 降序的契约。

    Args:
        params: 经过 schema 校验的入参。
        backend: 实现 CharacterIndexBackend Protocol 的具体后端。

    Returns:
        按 mention_count 降序的 CharacterRef 列表（章节无角色时为空列表）。
    """
    return backend.characters_in(params.chapter)
