"""Tests for bookscope.ingest.book_chunker (three-layer chunking)."""

from __future__ import annotations

from bookscope.ingest.book_chunker import (
    CHUNK_CHAR_MIN,
    CHUNK_CHAR_TARGET,
    _build_header,
    _detect_chapters,
    _merge_paragraphs,
    _split_long_text,
    chunk_book,
)
from bookscope.models.schemas import BookText
from bookscope.nlp.knowledge_extractor import _sample_indices

# ---------------------------------------------------------------------------
# _detect_chapters
# ---------------------------------------------------------------------------

class TestDetectChapters:
    def test_chinese_chapter_headings(self):
        text = "第一章 少年天子\n朱元璋出生于...\n\n第二章 群雄逐鹿\n天下大乱..."
        chs = _detect_chapters(text)
        assert len(chs) == 2
        assert "第一章" in chs[0][1]
        assert "第二章" in chs[1][1]

    def test_numeric_chapter_headings(self):
        text = "第1章 开端\n内容...\n\n第2章 发展\n更多内容..."
        chs = _detect_chapters(text)
        assert len(chs) == 2

    def test_hui_style_headings(self):
        """水浒传/红楼梦 style: 第X回"""
        text = "第一回 张天师祈禳瘟疫\n话说...\n\n第二回 洪太尉误走妖魔\n却说..."
        chs = _detect_chapters(text)
        assert len(chs) == 2
        assert "第一回" in chs[0][1]

    def test_no_chapters_returns_whole_text(self):
        text = "这是一段没有章节标题的文本。\n\n另一段内容。"
        chs = _detect_chapters(text)
        assert len(chs) == 1
        assert chs[0][0] == 1  # chapter number
        assert "这是一段" in chs[0][2]

    def test_prologue_before_first_chapter(self):
        prologue = "前言\n" + "这是很长的前言内容。" * 50 + "\n\n"
        body = "第一章 正文\n正文内容开始..."
        chs = _detect_chapters(prologue + body)
        # Should have prologue (ch 0) + chapter 1
        ch_nums = [c[0] for c in chs]
        assert 0 in ch_nums  # prologue detected
        assert any("第一章" in c[1] for c in chs)

    def test_english_chapter_headings(self):
        text = "Chapter 1\nOnce upon...\n\nChapter 2\nThe next day..."
        chs = _detect_chapters(text)
        assert len(chs) == 2


# ---------------------------------------------------------------------------
# _merge_paragraphs
# ---------------------------------------------------------------------------

class TestMergeParagraphs:
    def test_merges_short_paragraphs(self):
        paras = "\n\n".join(["短段落。" * 10] * 5)
        chunks = _merge_paragraphs(paras, CHUNK_CHAR_TARGET, CHUNK_CHAR_MIN, 0, "zh")
        # 5 short paragraphs of ~50 chars each = ~250 total, should merge
        total_chars = sum(len(c) for c in chunks)
        assert total_chars > 0
        assert len(chunks) <= 5  # merged, not 1:1

    def test_respects_target_size(self):
        # Create text that's 5x the target
        big_text = "\n\n".join(["这是一段中文内容。" * 50] * 10)
        chunks = _merge_paragraphs(big_text, CHUNK_CHAR_TARGET, CHUNK_CHAR_MIN, 0, "zh")
        for c in chunks:
            assert len(c) <= CHUNK_CHAR_TARGET * 3  # allow some overflow

    def test_empty_text(self):
        assert _merge_paragraphs("", CHUNK_CHAR_TARGET, CHUNK_CHAR_MIN, 0, "zh") == []

    def test_single_short_paragraph(self):
        chunks = _merge_paragraphs("很短。", CHUNK_CHAR_TARGET, 2, 0, "zh")
        assert len(chunks) == 1

    def test_overlap_creates_continuity(self):
        para1 = "第一段内容。" * 100  # long enough to be its own chunk
        para2 = "第二段内容。" * 100
        chunks_no_overlap = _merge_paragraphs(
            f"{para1}\n\n{para2}", CHUNK_CHAR_TARGET, CHUNK_CHAR_MIN, 0, "zh"
        )
        chunks_overlap = _merge_paragraphs(
            f"{para1}\n\n{para2}", CHUNK_CHAR_TARGET, CHUNK_CHAR_MIN, 150, "zh"
        )
        # With overlap, chunks may share trailing/leading text
        assert len(chunks_overlap) >= len(chunks_no_overlap)


# ---------------------------------------------------------------------------
# _split_long_text
# ---------------------------------------------------------------------------

class TestSplitLongText:
    def test_splits_by_chinese_punctuation(self):
        text = "第一句话。第二句话。第三句话。" * 100
        chunks = _split_long_text(text, CHUNK_CHAR_TARGET, CHUNK_CHAR_MIN, "zh")
        assert len(chunks) >= 1
        for c in chunks:
            assert len(c) > 0

    def test_english_splitting(self):
        text = "First sentence. Second sentence. Third sentence. " * 100
        chunks = _split_long_text(text, CHUNK_CHAR_TARGET, CHUNK_CHAR_MIN, "en")
        assert len(chunks) >= 1


# ---------------------------------------------------------------------------
# _build_header
# ---------------------------------------------------------------------------

class TestBuildHeader:
    def test_regular_chapter(self):
        h = _build_header("红楼梦", 3, "第三回 贾雨村夤缘复旧职")
        assert "红楼梦" in h
        assert "第三回" in h

    def test_prologue(self):
        h = _build_header("测试书", 0, "序")
        assert "序章" in h

    def test_no_title(self):
        h = _build_header("测试", 5, "")
        assert "第5章" in h


# ---------------------------------------------------------------------------
# chunk_book (integration)
# ---------------------------------------------------------------------------

class TestChunkBook:
    def test_basic_chinese_novel(self):
        parts = []
        for i in range(1, 6):
            para = f"第{i}章的段落内容。" * 30
            ch_body = "\n\n".join([para] * 10)
            parts.append(f"第{i}章 标题{i}\n{ch_body}")
        raw = "\n\n".join(parts)

        book = BookText(title="测试小说", raw_text=raw, language="zh")
        chunks = chunk_book(book)

        assert len(chunks) > 0
        # 5 chapters with ~15000 chars total → ~10-30 chunks, not 50
        assert len(chunks) < 50
        # Each chunk should have a contextual header
        assert any("《测试小说》" in c.text for c in chunks)

    def test_no_chapters_still_works(self):
        raw = "\n\n".join(["一段没有章节标记的文本。" * 50] * 20)
        book = BookText(title="散文集", raw_text=raw, language="zh")
        chunks = chunk_book(book)
        assert len(chunks) > 0

    def test_english_book(self):
        raw = ""
        for i in range(1, 4):
            raw += f"Chapter {i}\n"
            raw += "\n\n".join(["This is a paragraph. " * 40] * 8)
            raw += "\n\n"

        book = BookText(title="Test Novel", raw_text=raw, language="en")
        chunks = chunk_book(book)
        assert len(chunks) > 0
        assert any("Test Novel" in c.text for c in chunks)

    def test_short_book_not_over_chunked(self):
        raw = "第一章 唯一的章节\n这是一本很短的书。内容就这么多。"
        book = BookText(title="短篇", raw_text=raw, language="zh")
        chunks = chunk_book(book)
        assert len(chunks) <= 3


# ---------------------------------------------------------------------------
# _sample_indices (extraction sampling)
# ---------------------------------------------------------------------------

class TestSampleIndices:
    def test_small_total_returns_all(self):
        assert _sample_indices(10, 60) == list(range(10))

    def test_large_total_samples(self):
        indices = _sample_indices(500, 60)
        assert len(indices) <= 60
        assert 0 in indices         # first chunk included
        assert 499 in indices       # last chunk included

    def test_indices_sorted(self):
        indices = _sample_indices(1000, 50)
        assert indices == sorted(indices)

    def test_no_duplicates(self):
        indices = _sample_indices(200, 60)
        assert len(indices) == len(set(indices))
