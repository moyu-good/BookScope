"""``R0BookAssembler`` 单测。

测试原则：**不跑真 FAISS、不跑真 LLM、不依赖 epub**。仅用手工构造的
``BookText`` + ``list[ChunkResult]`` + ``BookKnowledgeGraph`` 验证装配器
的推断逻辑、映射正确性与降级行为。向量 store 使用最简替身
(``_FakeVectorStore``)。
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from bookscope.agent.backends import (
    R0BookAssembler,
    R0ChapterRangeBackend,
    R0ListCharactersBackend,
    R0SearchChunksBackend,
)
from bookscope.agent.backends.r0_chapter_range import R0ChapterRecord
from bookscope.models.schemas import (
    BookKnowledgeGraph,
    BookText,
    CharacterProfile,
    ChunkResult,
)

# ---------------------------------------------------------------------------
# 测试替身
# ---------------------------------------------------------------------------


class _FakeVectorStore:
    """最小 ``SessionVectorStore.search`` 替身。"""

    def __init__(
        self,
        results: Sequence[tuple[ChunkResult, float]] | None = None,
    ) -> None:
        self._results = list(results) if results else []
        self.call_count = 0

    def search(
        self,
        query: str,
        top_k: int = 5,
    ) -> list[tuple[ChunkResult, float]]:
        self.call_count += 1
        return list(self._results[:top_k])


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_book_text() -> BookText:
    """构造一本小书：两章（第一章、第二章），每章几段文字。

    r0 ``book_chunker.detect_chapters`` 用的正则要求章节标题行本身
    匹配 ``第X章/回/节`` 等前缀；本 fixture 构造的章节行满足该格式。
    """
    raw = (
        "第一章 开国\n"
        "朱元璋称帝建都南京。李善长受封韩国公。\n"
        "国泰民安。\n\n"
        "第二章 削藩\n"
        "朱棣起兵靖难。姚广孝献计。\n"
        "迁都北京。\n"
    )
    return BookText(title="明朝那些事儿", raw_text=raw, language="zh")


@pytest.fixture()
def sample_chunks(sample_book_text: BookText) -> list[ChunkResult]:
    """构造带 r0 header 的 chunks：两条，分别对应第一章、第二章。

    真跑 ``chunk_book`` 会产出类似的结果，但本测试用手工数据更可控。
    header 格式和 ``_build_header`` 保持一致——这是装配器 parse 的契约。
    """
    return [
        ChunkResult(
            index=0,
            text=(
                "[《明朝那些事儿》第一章 开国]\n"
                "朱元璋称帝建都南京。李善长受封韩国公。国泰民安。"
            ),
        ),
        ChunkResult(
            index=1,
            text=(
                "[《明朝那些事儿》第二章 削藩]\n"
                "朱棣起兵靖难。姚广孝献计。迁都北京。"
            ),
        ),
    ]


@pytest.fixture()
def sample_kg() -> BookKnowledgeGraph:
    """KG：四个角色覆盖两章。

    ``key_chapter_indices`` 按 "agent 层标准化章节号"（1-based、无序章）
    写，与装配器的 chapter_character_map 语义对齐。
    """
    return BookKnowledgeGraph(
        book_title="明朝那些事儿",
        characters=[
            CharacterProfile(name="朱元璋", key_chapter_indices=[1]),
            CharacterProfile(name="李善长", key_chapter_indices=[1]),
            CharacterProfile(name="朱棣", key_chapter_indices=[2]),
            CharacterProfile(name="姚广孝", key_chapter_indices=[2]),
        ],
    )


# ---------------------------------------------------------------------------
# 主入口：build_all
# ---------------------------------------------------------------------------


class TestBuildAll:
    def test_returns_three_backend_keys(
        self,
        sample_book_text: BookText,
        sample_chunks: list[ChunkResult],
        sample_kg: BookKnowledgeGraph,
    ) -> None:
        """``build_all`` 返回含三个约定键的 dict。"""
        assembler = R0BookAssembler(
            book_text=sample_book_text,
            chunks=sample_chunks,
            knowledge_graph=sample_kg,
            session_vector_store=_FakeVectorStore(),
        )
        bundle = assembler.build_all()
        assert set(bundle.keys()) == {"search", "chapter_range", "list_characters"}

    def test_search_lazy_built_when_vector_store_missing_with_chunks(
        self,
        sample_book_text: BookText,
        sample_chunks: list[ChunkResult],
        sample_kg: BookKnowledgeGraph,
    ) -> None:
        """session_vector_store 为 None 但 chunks 非空时 lazy build 一个救回旧 session。"""
        assembler = R0BookAssembler(
            book_text=sample_book_text,
            chunks=sample_chunks,
            knowledge_graph=sample_kg,
            session_vector_store=None,
        )
        bundle = assembler.build_all()
        assert bundle["search"] is not None  # lazy build 兜底
        assert isinstance(bundle["chapter_range"], R0ChapterRangeBackend)
        assert isinstance(bundle["list_characters"], R0ListCharactersBackend)

    def test_search_is_none_when_both_vector_store_and_chunks_missing(
        self,
        sample_book_text: BookText,
        sample_kg: BookKnowledgeGraph,
    ) -> None:
        """vector_store 为 None 且 chunks 也空时 search 才真的为 None。"""
        assembler = R0BookAssembler(
            book_text=sample_book_text,
            chunks=[],
            knowledge_graph=sample_kg,
            session_vector_store=None,
        )
        bundle = assembler.build_all()
        assert bundle["search"] is None
        assert isinstance(bundle["chapter_range"], R0ChapterRangeBackend)
        assert isinstance(bundle["list_characters"], R0ListCharactersBackend)


# ---------------------------------------------------------------------------
# build_search_chunks_backend
# ---------------------------------------------------------------------------


class TestBuildSearchBackend:
    def test_returns_backend_when_store_provided(
        self,
        sample_book_text: BookText,
        sample_chunks: list[ChunkResult],
        sample_kg: BookKnowledgeGraph,
    ) -> None:
        assembler = R0BookAssembler(
            book_text=sample_book_text,
            chunks=sample_chunks,
            knowledge_graph=sample_kg,
            session_vector_store=_FakeVectorStore(),
        )
        backend = assembler.build_search_chunks_backend()
        assert isinstance(backend, R0SearchChunksBackend)

    def test_lazy_build_when_store_missing_with_chunks(
        self,
        sample_book_text: BookText,
        sample_chunks: list[ChunkResult],
        sample_kg: BookKnowledgeGraph,
    ) -> None:
        """vector_store 为 None 但 chunks 非空时 lazy build 一个，不再返回 None。"""
        assembler = R0BookAssembler(
            book_text=sample_book_text,
            chunks=sample_chunks,
            knowledge_graph=sample_kg,
            session_vector_store=None,
        )
        backend = assembler.build_search_chunks_backend()
        assert backend is not None
        assert isinstance(backend, R0SearchChunksBackend)

    def test_returns_none_when_both_store_and_chunks_missing(
        self,
        sample_book_text: BookText,
        sample_kg: BookKnowledgeGraph,
    ) -> None:
        """vector_store 为 None 且 chunks 也空才真返 None。"""
        assembler = R0BookAssembler(
            book_text=sample_book_text,
            chunks=[],
            knowledge_graph=sample_kg,
            session_vector_store=None,
        )
        assert assembler.build_search_chunks_backend() is None


# ---------------------------------------------------------------------------
# build_chapter_range_backend
# ---------------------------------------------------------------------------


class TestBuildChapterRangeBackend:
    def test_always_returns_backend(
        self,
        sample_book_text: BookText,
        sample_chunks: list[ChunkResult],
        sample_kg: BookKnowledgeGraph,
    ) -> None:
        assembler = R0BookAssembler(
            book_text=sample_book_text,
            chunks=sample_chunks,
            knowledge_graph=sample_kg,
            session_vector_store=None,
        )
        backend = assembler.build_chapter_range_backend()
        assert isinstance(backend, R0ChapterRangeBackend)

    def test_chapter_range_backend_can_serve_get_chapters(
        self,
        sample_book_text: BookText,
        sample_chunks: list[ChunkResult],
        sample_kg: BookKnowledgeGraph,
    ) -> None:
        """构造的 chapter_range backend 能真的跑 get_chapters。"""
        assembler = R0BookAssembler(
            book_text=sample_book_text,
            chunks=sample_chunks,
            knowledge_graph=sample_kg,
        )
        backend = assembler.build_chapter_range_backend()
        out = backend.get_chapters(1, 2)
        assert len(out) == 2
        assert out[0].chapter == 1
        assert out[1].chapter == 2
        assert "朱元璋" in out[0].full_text
        assert "朱棣" in out[1].full_text


# ---------------------------------------------------------------------------
# build_list_characters_backend
# ---------------------------------------------------------------------------


class TestBuildListCharactersBackend:
    def test_always_returns_backend(
        self,
        sample_book_text: BookText,
        sample_chunks: list[ChunkResult],
        sample_kg: BookKnowledgeGraph,
    ) -> None:
        assembler = R0BookAssembler(
            book_text=sample_book_text,
            chunks=sample_chunks,
            knowledge_graph=sample_kg,
        )
        backend = assembler.build_list_characters_backend()
        assert isinstance(backend, R0ListCharactersBackend)

    def test_characters_in_chapter_returns_expected(
        self,
        sample_book_text: BookText,
        sample_chunks: list[ChunkResult],
        sample_kg: BookKnowledgeGraph,
    ) -> None:
        """构造的 list_characters backend 能真的跑 characters_in。"""
        assembler = R0BookAssembler(
            book_text=sample_book_text,
            chunks=sample_chunks,
            knowledge_graph=sample_kg,
        )
        backend = assembler.build_list_characters_backend()
        ch1 = backend.characters_in(1)
        ch2 = backend.characters_in(2)
        names1 = {r.canonical_name for r in ch1}
        names2 = {r.canonical_name for r in ch2}
        assert names1 == {"朱元璋", "李善长"}
        assert names2 == {"朱棣", "姚广孝"}


# ---------------------------------------------------------------------------
# 内部：_compute_chunk_to_chapter_map
# ---------------------------------------------------------------------------


class TestChunkToChapterMap:
    def test_parses_header_for_chapter_one_and_two(
        self,
        sample_book_text: BookText,
        sample_chunks: list[ChunkResult],
        sample_kg: BookKnowledgeGraph,
    ) -> None:
        """chunk 0 → 章 1、chunk 1 → 章 2。"""
        assembler = R0BookAssembler(
            book_text=sample_book_text,
            chunks=sample_chunks,
            knowledge_graph=sample_kg,
        )
        mapping = assembler._compute_chunk_to_chapter_map()
        assert mapping == {0: 1, 1: 2}

    def test_chunk_without_parseable_header_skipped(
        self,
        sample_book_text: BookText,
        sample_kg: BookKnowledgeGraph,
    ) -> None:
        """header 无法 parse 且无 chapter 字段的 chunk 不进 mapping。"""
        chunks = [
            ChunkResult(
                index=0,
                text="[《明朝那些事儿》第一章 开国]\n正文...",
            ),
            ChunkResult(
                index=1,
                text="没有 header 的裸文本 chunk",
            ),
        ]
        assembler = R0BookAssembler(
            book_text=sample_book_text,
            chunks=chunks,
            knowledge_graph=sample_kg,
        )
        mapping = assembler._compute_chunk_to_chapter_map()
        assert 0 in mapping
        assert 1 not in mapping

    def test_uses_chunk_chapter_field_when_present(
        self,
        sample_book_text: BookText,
        sample_kg: BookKnowledgeGraph,
    ) -> None:
        """有 ``ChunkResult.chapter`` 字段时优先走 schema 快路径，
        即使 header 文字不可解析也能建出映射。"""
        chunks = [
            ChunkResult(
                index=0,
                text="没有 header 的裸文本 chunk（章 1）",
                chapter=1,
            ),
            ChunkResult(
                index=1,
                text="另一段无 header 文本（章 2）",
                chapter=2,
            ),
        ]
        assembler = R0BookAssembler(
            book_text=sample_book_text,
            chunks=chunks,
            knowledge_graph=sample_kg,
        )
        mapping = assembler._compute_chunk_to_chapter_map()
        assert mapping == {0: 1, 1: 2}

    def test_schema_field_takes_precedence_over_header_regex(
        self,
        sample_book_text: BookText,
        sample_kg: BookKnowledgeGraph,
    ) -> None:
        """chunk.chapter 与 header 冲突时以 schema 字段为准
        （chunk_book 新版填的就是 raw 章节号，比 header regex 可靠）。"""
        chunks = [
            ChunkResult(
                index=0,
                text="[《书》第二章 误标]\n正文",  # header 说 2
                chapter=1,                            # field 说 1
            ),
        ]
        assembler = R0BookAssembler(
            book_text=sample_book_text,
            chunks=chunks,
            knowledge_graph=sample_kg,
        )
        mapping = assembler._compute_chunk_to_chapter_map()
        # 样书 sample_book_text 含 "第一章 开国" / "第二章 削藩"，无序章，
        # raw_to_norm 是 {1:1, 2:2}；chunk.chapter=1 → norm 1。
        assert mapping == {0: 1}


# ---------------------------------------------------------------------------
# 内部：_compute_chunk_to_characters_map
# ---------------------------------------------------------------------------


class TestChunkToCharactersMap:
    def test_infers_characters_from_chapter_map(
        self,
        sample_book_text: BookText,
        sample_chunks: list[ChunkResult],
        sample_kg: BookKnowledgeGraph,
    ) -> None:
        """chunk 的角色列表 = 它所属章节的所有角色。"""
        assembler = R0BookAssembler(
            book_text=sample_book_text,
            chunks=sample_chunks,
            knowledge_graph=sample_kg,
        )
        mapping = assembler._compute_chunk_to_characters_map()
        assert set(mapping[0]) == {"朱元璋", "李善长"}
        assert set(mapping[1]) == {"朱棣", "姚广孝"}

    def test_empty_kg_yields_empty_mapping(
        self,
        sample_book_text: BookText,
        sample_chunks: list[ChunkResult],
    ) -> None:
        """KG 无任何角色时 chunk→characters 应为空 dict。"""
        empty_kg = BookKnowledgeGraph(book_title="X", characters=[])
        assembler = R0BookAssembler(
            book_text=sample_book_text,
            chunks=sample_chunks,
            knowledge_graph=empty_kg,
        )
        mapping = assembler._compute_chunk_to_characters_map()
        assert mapping == {}


# ---------------------------------------------------------------------------
# 内部：_compute_chapter_records
# ---------------------------------------------------------------------------


class TestChapterRecords:
    def test_produces_two_records_for_sample_book(
        self,
        sample_book_text: BookText,
        sample_chunks: list[ChunkResult],
        sample_kg: BookKnowledgeGraph,
    ) -> None:
        """``_compute_chapter_records`` 对两章的样本书产出两条 record。"""
        assembler = R0BookAssembler(
            book_text=sample_book_text,
            chunks=sample_chunks,
            knowledge_graph=sample_kg,
        )
        records = assembler._compute_chapter_records()
        assert len(records) == 2
        assert all(isinstance(r, R0ChapterRecord) for r in records)
        assert [r.chapter for r in records] == [1, 2]

    def test_empty_book_yields_empty_records(
        self,
        sample_kg: BookKnowledgeGraph,
    ) -> None:
        """空书 raw_text → 无 chapter records。"""
        assembler = R0BookAssembler(
            book_text=BookText(title="空", raw_text="", language="zh"),
            chunks=[],
            knowledge_graph=sample_kg,
        )
        records = assembler._compute_chapter_records()
        assert records == []


# ---------------------------------------------------------------------------
# 集成：装配出来的 backend 跑真操作
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_search_backend_retrieve_end_to_end(
        self,
        sample_book_text: BookText,
        sample_chunks: list[ChunkResult],
        sample_kg: BookKnowledgeGraph,
    ) -> None:
        """装配出 search backend，通过假 store 跑 retrieve 拿到结构化结果。"""
        store = _FakeVectorStore(
            results=[
                (sample_chunks[0], 0.9),
                (sample_chunks[1], 0.6),
            ],
        )
        assembler = R0BookAssembler(
            book_text=sample_book_text,
            chunks=sample_chunks,
            knowledge_graph=sample_kg,
            session_vector_store=store,
        )
        backend = assembler.build_search_chunks_backend()
        assert backend is not None
        matches = backend.retrieve(
            query="朱元璋",
            chapter_scope=None,
            character_filter=None,
            top_k=10,
        )
        assert len(matches) == 2
        assert matches[0].source_version == "r0"
        # chunk 0 的角色列表应被装配器推断进去
        assert "朱元璋" in matches[0].contains_characters

    def test_chapter_range_and_list_characters_wire_up_cleanly(
        self,
        sample_book_text: BookText,
        sample_chunks: list[ChunkResult],
        sample_kg: BookKnowledgeGraph,
    ) -> None:
        """不提供 vector_store 时，其它两个 backend 仍能端到端工作。"""
        assembler = R0BookAssembler(
            book_text=sample_book_text,
            chunks=sample_chunks,
            knowledge_graph=sample_kg,
        )
        chapter_backend = assembler.build_chapter_range_backend()
        character_backend = assembler.build_list_characters_backend()

        chapters = chapter_backend.get_chapters(1, 1)
        assert chapters[0].chapter == 1
        assert chapters[0].source_version == "r0"

        refs = character_backend.characters_in(2)
        assert {r.canonical_name for r in refs} == {"朱棣", "姚广孝"}
