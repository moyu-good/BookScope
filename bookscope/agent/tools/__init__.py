"""`bookscope.agent.tools` — r1 代理唯一可调用的三个 tool。

本子包遵循 ADR-001 签字锁定的接口：
- search_chunks：按自然语言 query + 章节/角色过滤做语义检索
- get_chapter_range：按章节范围拉取完整原文
- list_characters_in_chapter：列出某章节中出现的角色

本模块只导出 public API（schema + dispatcher 函数 + 错误类），
backend 实现细节由各 tool 模块各自持有。
"""

from bookscope.agent.backends import (
    R0ChapterRangeBackend,
    R0ChapterRecord,
    R0ListCharactersBackend,
    R0SearchChunksBackend,
    build_chapter_character_map,
)
from bookscope.agent.tools.errors import (
    ChapterNotFound,
    ChapterRangeTooLarge,
    CharacterNotFound,
    ChunkNotFound,
    ToolError,
)
from bookscope.agent.tools.get_chapter_range import (
    ChapterTextBackend,
    GetChapterRangeInput,
    get_chapter_range,
)
from bookscope.agent.tools.list_characters_in_chapter import (
    CharacterIndexBackend,
    ListCharactersInChapterInput,
    list_characters_in_chapter,
)
from bookscope.agent.tools.schemas import (
    ChapterText,
    CharacterRef,
    ChunkMatch,
    SourceVersion,
)
from bookscope.agent.tools.search_chunks import (
    ChunkRetrievalBackend,
    SearchChunksInput,
    search_chunks,
)

__all__ = [
    # shared schemas
    "ChapterText",
    "CharacterRef",
    "ChunkMatch",
    "SourceVersion",
    # tool inputs
    "GetChapterRangeInput",
    "ListCharactersInChapterInput",
    "SearchChunksInput",
    # backend protocols
    "ChapterTextBackend",
    "CharacterIndexBackend",
    "ChunkRetrievalBackend",
    # concrete r0 backends
    "R0ChapterRangeBackend",
    "R0ChapterRecord",
    "R0ListCharactersBackend",
    "R0SearchChunksBackend",
    "build_chapter_character_map",
    # tool functions
    "get_chapter_range",
    "list_characters_in_chapter",
    "search_chunks",
    # errors
    "CharacterNotFound",
    "ChapterNotFound",
    "ChapterRangeTooLarge",
    "ChunkNotFound",
    "ToolError",
]
