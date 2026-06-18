"""Tests for the promoted public helper ``detect_chapters``.

Previously ``_detect_chapters`` was a private helper that ``R0BookAssembler``
had to reach into with a ``noqa SLF001``.  The promotion to a public name
removes that per-call-site friction.  Tests here:

1. Cover the documented behaviour of ``detect_chapters`` on typical Chinese
   inputs (headed chapters, untitled text, and prologue handling).
2. Assert the backward-compat ``_detect_chapters`` alias keeps working so
   ``legacy/v7`` and any external vendored copy keep importing cleanly.
"""

from __future__ import annotations

from bookscope.ingest import book_chunker
from bookscope.models import BookText

# ---------------------------------------------------------------------------
# Public helper behaviour
# ---------------------------------------------------------------------------


def test_detect_chapters_splits_on_chinese_chapter_headings() -> None:
    text = (
        "第一章 开端\n第一段文字。\n\n"
        "第二章 发展\n第二段文字。\n\n"
        "第三章 高潮\n第三段文字。\n"
    )
    chapters = book_chunker.detect_chapters(text)
    assert [c[0] for c in chapters] == [1, 2, 3]
    assert chapters[0][1].startswith("第一章")
    assert "第一段文字" in chapters[0][2]
    assert "第二段文字" in chapters[1][2]


def test_detect_chapters_returns_single_chapter_when_no_headings() -> None:
    text = "普通正文，不包含任何章节标题，整段应当作为单一章节返回。"
    chapters = book_chunker.detect_chapters(text)
    assert len(chapters) == 1
    assert chapters[0][0] == 1
    assert chapters[0][1] == ""
    assert chapters[0][2] == text


def test_detect_chapters_treats_long_prologue_as_chapter_zero() -> None:
    # Prologue longer than CHUNK_CHAR_MIN (300) should be lifted out.
    prologue = "序言正文。" * 100  # well over 300 chars
    text = prologue + "\n第一章 开端\n正文开始。"
    chapters = book_chunker.detect_chapters(text)
    assert chapters[0][0] == 0
    assert chapters[0][1] == "序"
    assert chapters[1][0] == 1


def test_detect_chapters_skips_short_preamble() -> None:
    # Short preamble should be dropped, not made chapter 0.
    text = "短引子。\n第一章 正式开始\n正文。"
    chapters = book_chunker.detect_chapters(text)
    assert len(chapters) == 1
    assert chapters[0][0] == 1


def test_detect_chapters_ignores_long_lines_that_look_like_headings() -> None:
    """Lines exceeding ``_MAX_HEADING_LINE_LEN`` should not be headings.

    Guard against matching "第X章" buried inside narrative sentences.
    """
    fake_heading_long_line = (
        "话说第一章这类说法只是人物口中的随口一提，"
        "整段其实都在描述主角心理活动和周遭环境细节，"
        "绝不是真正的章节标题，因此不该被切分。"
    )
    chapters = book_chunker.detect_chapters(fake_heading_long_line)
    assert len(chapters) == 1


# ---------------------------------------------------------------------------
# Backward-compat alias
# ---------------------------------------------------------------------------


def test_private_alias_points_to_public_helper() -> None:
    assert book_chunker._detect_chapters is book_chunker.detect_chapters


def test_private_alias_still_callable() -> None:
    text = "第一章 甲\n段落 A。\n\n第二章 乙\n段落 B。"
    result_public = book_chunker.detect_chapters(text)
    result_alias = book_chunker._detect_chapters(text)
    assert result_public == result_alias


# ---------------------------------------------------------------------------
# chunk_book 新字段填充（ChunkResult.chapter）
# ---------------------------------------------------------------------------


def _raw_text_with_two_chapters() -> str:
    # Each chapter body padded well above CHUNK_CHAR_MIN so chunk_book keeps them.
    body_a = "章节一正文。" * 80
    body_b = "章节二正文。" * 80
    return f"第一章 开端\n{body_a}\n\n第二章 发展\n{body_b}\n"


def test_chunk_book_populates_chapter_field_on_regular_chapters() -> None:
    book = BookText(title="测试书", raw_text=_raw_text_with_two_chapters(), language="zh")
    chunks = book_chunker.chunk_book(book)
    assert chunks, "sanity: the sample input should yield at least one chunk"
    for c in chunks:
        assert c.chapter is not None
        assert c.chapter >= 1

    chapters_seen = sorted({c.chapter for c in chunks})
    assert chapters_seen == [1, 2]


def test_chunk_book_marks_prologue_as_chapter_zero() -> None:
    prologue = "这是序章正文。" * 80  # > CHUNK_CHAR_MIN so it survives as chapter 0
    book = BookText(
        title="测试书",
        raw_text=prologue + "\n第一章 开端\n正文开始。" * 80,
        language="zh",
    )
    chunks = book_chunker.chunk_book(book)
    prologue_chunks = [c for c in chunks if c.chapter == 0]
    chapter_one_chunks = [c for c in chunks if c.chapter == 1]
    assert prologue_chunks, "expected at least one chunk tagged as prologue (chapter=0)"
    assert chapter_one_chunks, "expected at least one chunk tagged as chapter 1"


def test_chunk_book_assigns_chapter_one_when_no_headings() -> None:
    book = BookText(
        title="无章书",
        raw_text="没有章节标题的长段落，全文应当被视为第一章。" * 80,
        language="zh",
    )
    chunks = book_chunker.chunk_book(book)
    assert chunks
    for c in chunks:
        assert c.chapter == 1


# ---------------------------------------------------------------------------
# 真实脏书鲁棒性（WP-robust-chapter-detection）—— 主干章号脊
# ---------------------------------------------------------------------------


def test_detect_chapters_strips_toc_double_counting() -> None:
    """类别 A：目录整列回目（body 空）+ 正文回目 → 只留正文那批，真章号不翻倍。"""
    toc = "第一回 甲\n第二回 乙\n第三回 丙\n"
    body = (
        "第一回 甲\n" + "甲的正文。" * 30 + "\n\n"
        "第二回 乙\n" + "乙的正文。" * 30 + "\n\n"
        "第三回 丙\n" + "丙的正文。" * 30 + "\n"
    )
    chapters = book_chunker.detect_chapters(toc + body)
    real = [c[0] for c in chapters if c[0] != 0]
    assert real == [1, 2, 3]  # 不是 1..6
    body_by_num = {c[0]: c[2] for c in chapters}
    assert "甲的正文" in body_by_num[1]
    assert "丙的正文" in body_by_num[3]


def test_detect_chapters_strips_frontmatter_excerpt() -> None:
    """类别 B：正文前塞高章号精彩片段（有 body）→ 剥掉它，真章节回到 1..3，摘录并入序。"""
    excerpt = "第五回 名场面\n" + "提前摘出的精彩片段正文。" * 30 + "\n\n"
    main = (
        "第一回 起\n" + "第一回正文。" * 30 + "\n\n"
        "第二回 承\n" + "第二回正文。" * 30 + "\n\n"
        "第三回 转\n" + "第三回正文。" * 30 + "\n"
    )
    chapters = book_chunker.detect_chapters(excerpt + main)
    real = [c[0] for c in chapters if c[0] != 0]
    assert real == [1, 2, 3]
    body_by_num = {c[0]: c[2] for c in chapters}
    assert "第一回正文" in body_by_num[1]


def test_detect_chapters_volume_restart_falls_back_to_ordinal() -> None:
    """类别 D：卷册重编号（1..2 两遍）→ 脊覆盖率仅半，退序号，不崩、不丢卷。"""
    vol = (
        "第一回 甲\n" + "甲正文。" * 30 + "\n\n"
        "第二回 乙\n" + "乙正文。" * 30 + "\n\n"
    )
    chapters = book_chunker.detect_chapters(vol + vol)
    real = [c[0] for c in chapters if c[0] != 0]
    assert len(real) == 4          # 两卷四回都留住，没被脊吞掉
    assert real == sorted(real)    # 退序号后仍单调（1..4）


def test_detect_chapters_clean_book_uses_real_numbers_unchanged() -> None:
    """干净书（真章号单调）→ 用真章号、脊=全部章头、行为不变。"""
    text = (
        "第一章 开端\n" + "开端正文。" * 30 + "\n\n"
        "第二章 发展\n" + "发展正文。" * 30 + "\n\n"
        "第三章 高潮\n" + "高潮正文。" * 30 + "\n"
    )
    chapters = book_chunker.detect_chapters(text)
    assert [c[0] for c in chapters] == [1, 2, 3]
