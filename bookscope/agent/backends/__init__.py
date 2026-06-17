"""`bookscope.agent.backends` — r1 tool 的 backend 适配层。

本子包把 r0 代际（批量预处理 ingest 阶段）落盘的存量产物——FAISS + BM25
混合检索的 ``SessionVectorStore``、章节原文存储、KG 角色索引——包装成
r1 ``bookscope.agent.tools`` 子包下三个 Protocol 规定的形态（
``ChunkRetrievalBackend`` / ``ChapterTextBackend`` / ``CharacterIndexBackend``）。

设计原则：
- 只做 **wrapping**，不改 r0 代码。r0 的数据结构缺失字段时，由外部传入
  辅助映射（例如 chunk_id → chapter 的映射、chunk_id → 角色列表的映射）
  来补齐，绝不绕道回去修改 r0 存储。
- 所有 backend 返回的 Pydantic 对象的 ``source_version`` 字段填 ``"r0"``，
  追溯该数据来自 r0 批量预处理产出。
- 若 r0 根本没有某项能力（例如 r0 的 ``ChunkResult`` 不带章节号映射），
  backend 构造函数必须显式接受外部补齐后的映射；在映射缺失时抛
  ``NotImplementedError`` 并在 ``docs/internal/STATE.md`` 的"需作者决策"区记录。
"""

# 本块 import 顺序是刻意的（r0_assembler 必须最后），见下方注释，勿让 lint 重排。
# isort: off
from bookscope.agent.backends.r0_chapter_range import (
    R0ChapterRangeBackend,
    R0ChapterRecord,
)
from bookscope.agent.backends.r0_list_characters import (
    R0ListCharactersBackend,
    build_chapter_character_map,
)
from bookscope.agent.backends.r0_search_chunks import R0SearchChunksBackend

# r0_assembler 放在最后——它 import 同包的其它 backend，依赖它们先进名字空间。
# 同时 r0_assembler 会间接触发 ``bookscope.agent.tools.errors`` 的加载，
# 后者经由 ``tools/__init__`` 回头 import 本模块的 backend 符号；必须等
# 前三个 backend 已绑定到 ``bookscope.agent.backends`` 名字空间才安全。
from bookscope.agent.backends.r0_assembler import R0BookAssembler

# 占位 KG 提取器（ADR-004 方案 B）：依赖 adapter 层；独立模块，无顺序要求。
from bookscope.agent.backends.minimal_kg_extractor import MinimalKGExtractor
# isort: on

__all__ = [
    "MinimalKGExtractor",
    "R0BookAssembler",
    "R0ChapterRangeBackend",
    "R0ChapterRecord",
    "R0ListCharactersBackend",
    "R0SearchChunksBackend",
    "build_chapter_character_map",
]
