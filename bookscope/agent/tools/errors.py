"""ADR-001 约定的 tool 层错误类型。

dispatcher 层会捕获这些错误并向 agent 返回结构化 error，
而不是让异常把整个 loop 崩掉。每个错误都要能被 LLM 看懂并自我修正，
因此异常消息本身就是给 agent 的"指引"。
"""

from __future__ import annotations


class ToolError(Exception):
    """所有 tool 层错误的根基类。

    dispatcher 只捕获该基类及其子类，其他异常仍按 bug 对待直接抛出。
    """


class ChunkNotFound(ToolError):
    """`search_chunks` 按 chunk_id 检索时未命中对应 chunk。"""


class ChapterRangeTooLarge(ToolError):
    """`get_chapter_range` 的范围合计字数超过硬上限。

    Attributes:
        word_count: 实际合计字数。
        limit: 触发该错误的字数硬上限（默认 200_000）。
    """

    def __init__(self, word_count: int, limit: int) -> None:
        self.word_count = word_count
        self.limit = limit
        super().__init__(
            f"Requested chapter range totals {word_count} words, "
            f"exceeds the hard limit of {limit}. "
            f"Switch to search_chunks or narrow the range."
        )


class ChapterNotFound(ToolError):
    """`get_chapter_range` 请求的章节号不存在。"""


class CharacterNotFound(ToolError):
    """`list_characters_in_chapter` 找不到该章节的任何角色记录。"""
