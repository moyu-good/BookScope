"""WP3 章节识别鲁棒性测试（Phase A 观测 + Phase B 真章号）。

设计稿：``docs/internal/design/WP3-chapter-robustness.md``。覆盖四块：

1. 中文数字转换边界（四百二十 / 一千零一 / 两百 / 十 / 二十三）
2. 真章号解析 + 单调性守护（漏检留空 / 倒跳整书回退序号）
3. 卷头识别（卷X / 第X部 / 上中下篇 不占章节号）与 "(1)" 误判压制
4. Phase A 三条告警规则各一条触发用例
"""

from __future__ import annotations

import pytest

from bookscope.ingest.book_chunker import (
    WARN_NO_CHAPTERS,
    WARN_OVERDETECTION,
    WARN_PARSE_INCONSISTENT,
    WARN_TOO_COARSE,
    ChapterDetectionStats,
    chinese_numeral_to_int,
    chunk_book_with_stats,
    detect_chapters,
    detect_chapters_with_stats,
)
from bookscope.models import BookText

# 章正文填充：超过 CHUNK_CHAR_MIN(300) 保证 chunk_book 不丢
_BODY = "章节正文，向前推进。" * 40


# ---------------------------------------------------------------------------
# 中文数字转换
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("一", 1),
        ("十", 10),
        ("二十三", 23),
        ("两百", 200),
        ("两百三十", 230),
        ("四百二十", 420),
        ("一千零一", 1001),
        ("一万两千", 12000),
        ("九十九", 99),
        ("〇", 0),
        ("42", 42),
        ("４２", 42),  # 全角阿拉伯数字
    ],
)
def test_chinese_numeral_to_int(token: str, expected: int) -> None:
    assert chinese_numeral_to_int(token) == expected


@pytest.mark.parametrize("token", ["", "  ", "甲", "第", "一a", "卅"])
def test_chinese_numeral_to_int_rejects_garbage(token: str) -> None:
    """转不动必须返回 None——调用方按解析失败回退序号，绝不猜。"""
    assert chinese_numeral_to_int(token) is None


# ---------------------------------------------------------------------------
# Phase B：真章号解析
# ---------------------------------------------------------------------------


def test_true_chapter_number_parsed_from_heading() -> None:
    """第四十二章 → chapter=42，不是检测序号 1。"""
    text = f"第四十二章 风雪夜\n{_BODY}"
    chapters, stats = detect_chapters_with_stats(text)
    assert [c[0] for c in chapters] == [42]
    assert stats.chapters_detected == 1
    assert stats.parse_success_rate == 1.0


def test_true_chapter_numbers_survive_gap() -> None:
    """漏检中间一章（1、2、5）时序列仍严格递增 → 保留真章号不回退。"""
    text = (
        f"第一章 甲\n{_BODY}\n"
        f"第二章 乙\n{_BODY}\n"
        f"第五章 戊\n{_BODY}"
    )
    chapters, stats = detect_chapters_with_stats(text)
    assert [c[0] for c in chapters] == [1, 2, 5]
    assert WARN_PARSE_INCONSISTENT not in stats.warnings


def test_chunk_book_carries_true_chapter_number() -> None:
    """真章号一路透到 ChunkResult.chapter。"""
    text = f"第四十一章 上\n{_BODY}\n第四十二章 下\n{_BODY}"
    book = BookText(title="测试书", raw_text=text, language="zh")
    chunks, stats = chunk_book_with_stats(book)
    assert chunks
    assert sorted({c.chapter for c in chunks}) == [41, 42]
    assert isinstance(stats, ChapterDetectionStats)
    assert stats.chapters_detected == 2


def test_non_monotonic_sequence_falls_back_to_ordinals() -> None:
    """倒跳（第1章/第5章/第3章）→ 整书回退序号模式 + parse_inconsistent。"""
    text = (
        f"第1章 甲\n{_BODY}\n"
        f"第5章 乙\n{_BODY}\n"
        f"第3章 丙\n{_BODY}"
    )
    chapters, stats = detect_chapters_with_stats(text)
    assert [c[0] for c in chapters] == [1, 2, 3]
    assert WARN_PARSE_INCONSISTENT in stats.warnings
    # 解析本身全部成功——回退是单调性守护的决定，不是解析失败
    assert stats.parse_success_rate == 1.0


def test_duplicate_chapter_numbers_fall_back_to_ordinals() -> None:
    """重复章号（网文常见的"两个第三十章"）同样触发整书回退。"""
    text = (
        f"第二十九章 甲\n{_BODY}\n"
        f"第三十章 乙\n{_BODY}\n"
        f"第三十章 丙\n{_BODY}"
    )
    chapters, stats = detect_chapters_with_stats(text)
    assert [c[0] for c in chapters] == [1, 2, 3]
    assert WARN_PARSE_INCONSISTENT in stats.warnings


def test_prologue_keeps_chapter_zero_with_true_numbers() -> None:
    """长序文仍是 0 号"序"章，与真章号共存。"""
    prologue = "序言正文。" * 100  # 超过 CHUNK_CHAR_MIN
    text = f"{prologue}\n第四十二章 开端\n{_BODY}"
    chapters, _stats = detect_chapters_with_stats(text)
    assert [c[0] for c in chapters] == [0, 42]
    assert chapters[0][1] == "序"


# ---------------------------------------------------------------------------
# 卷头识别：不进章节列表不占号
# ---------------------------------------------------------------------------


def test_volume_marker_does_not_consume_chapter_number() -> None:
    """卷一 + 第一章..第三章 → 3 章，卷头只进 stats。"""
    text = (
        f"卷一\n"
        f"第一章 甲\n{_BODY}\n"
        f"第二章 乙\n{_BODY}\n"
        f"第三章 丙\n{_BODY}"
    )
    chapters, stats = detect_chapters_with_stats(text)
    assert [c[0] for c in chapters] == [1, 2, 3]
    assert stats.chapters_detected == 3
    assert stats.volume_markers_found == 1
    assert stats.pattern_hits.get("zh_volume") == 1


def test_titled_volume_markers_counted_not_numbered() -> None:
    """第X部 / 第X篇 带卷名也算卷头；章节号不受影响。"""
    text = (
        f"第一部 风云再起\n"
        f"第一章 甲\n{_BODY}\n"
        f"第二篇 山雨欲来\n"
        f"第二章 乙\n{_BODY}"
    )
    chapters, stats = detect_chapters_with_stats(text)
    assert [c[0] for c in chapters] == [1, 2]
    assert stats.volume_markers_found == 2


def test_pian_volume_requires_standalone_line() -> None:
    """独立行"上篇"是卷头；"上篇说到……"是正文回顾，不算。"""
    standalone = f"上篇\n第一章 甲\n{_BODY}"
    _, stats = detect_chapters_with_stats(standalone)
    assert stats.volume_markers_found == 1
    assert stats.pattern_hits.get("pian_volume") == 1

    inline = f"上篇说到主角刚进城。\n第一章 甲\n{_BODY}"
    _, stats2 = detect_chapters_with_stats(inline)
    assert stats2.volume_markers_found == 0


# ---------------------------------------------------------------------------
# "(1)" 模式收紧
# ---------------------------------------------------------------------------


def test_inline_paren_number_is_not_a_chapter() -> None:
    """行首 "(1)" 但行内还有正文 → 不算章节头。"""
    text = f"(1) 这是正文里的编号列表项，后面还跟着一整句话。\n{_BODY}"
    chapters, stats = detect_chapters_with_stats(text)
    assert stats.chapters_detected == 0
    assert len(chapters) == 1  # 全文一章兜底
    assert chapters[0][0] == 1


def test_standalone_paren_line_is_a_chapter() -> None:
    """strip 后整行就是 "（N）" 的短行才算章节头，真章号取括号里的数。"""
    text = f"（1）\n{_BODY}\n（2）\n{_BODY}"
    chapters, stats = detect_chapters_with_stats(text)
    assert [c[0] for c in chapters] == [1, 2]
    assert stats.pattern_hits.get("paren_chapter") == 2
    assert stats.parse_success_rate == 1.0


# ---------------------------------------------------------------------------
# Phase A：三条告警规则
# ---------------------------------------------------------------------------


def test_warning_no_chapters_detected() -> None:
    """全书 > 50000 字检出 ≤ 1 章 → no_chapters_detected。"""
    text = "全是正文没有任何章节标题。" * 5000  # 65000 字
    chapters, stats = detect_chapters_with_stats(text)
    assert len(chapters) == 1
    assert WARN_NO_CHAPTERS in stats.warnings


def test_warning_chapters_too_coarse() -> None:
    """平均章字数 > 100000 → chapters_too_coarse。"""
    fat_body = "字" * 110_000
    text = f"第一章 上\n{fat_body}\n第二章 下\n{fat_body}"
    _, stats = detect_chapters_with_stats(text)
    assert stats.chapters_detected == 2
    assert stats.avg_chapter_chars > 100_000
    assert WARN_TOO_COARSE in stats.warnings
    assert WARN_NO_CHAPTERS not in stats.warnings


def test_warning_suspicious_overdetection() -> None:
    """检出 > 3000 章 → suspicious_overdetection。"""
    text = "\n".join(f"第{i}章\n正文一句。" for i in range(1, 3002))
    _, stats = detect_chapters_with_stats(text)
    assert stats.chapters_detected == 3001
    assert WARN_OVERDETECTION in stats.warnings


def test_clean_detection_has_no_warnings() -> None:
    """正常书：无告警，指标填实。"""
    text = f"第一章 甲\n{_BODY}\n第二章 乙\n{_BODY}"
    _, stats = detect_chapters_with_stats(text)
    assert stats.warnings == []
    assert stats.chapters_detected == 2
    assert stats.parse_success_rate == 1.0
    assert stats.max_chapter_chars >= stats.avg_chapter_chars > 0


# ---------------------------------------------------------------------------
# stats 形态：API 透出用
# ---------------------------------------------------------------------------


def test_stats_to_dict_is_json_friendly() -> None:
    import json

    text = f"卷一\n第一章 甲\n{_BODY}"
    _, stats = detect_chapters_with_stats(text)
    payload = stats.to_dict()
    assert set(payload) == {
        "chapters_detected",
        "parse_success_rate",
        "avg_chapter_chars",
        "max_chapter_chars",
        "pattern_hits",
        "warnings",
        "volume_markers_found",
    }
    json.dumps(payload)  # 不抛即可


# 公文层级 fallback（research-notes/006 + exp-017）：无「第X章」但有「一、」「二、」…顶层小标题
# 时按它切段，免得意见整份落 1 章 → 条款维一次吐整份撞 token 上限（抽 0/17/141 随机）。
class TestGongwenSectionFallback:
    def test_gongwen_splits_by_top_level_sections(self):
        text = (
            "国务院办公厅关于加强X的意见\n各省人民政府：\n为加强X，现提出如下意见。\n"
            f"一、总体要求\n{_BODY}\n"
            f"二、主要任务\n{_BODY}\n"
            f"三、保障措施\n{_BODY}\n"
        )
        chapters = detect_chapters(text)
        # 三个顶层「一、」→ 三段（引言太短不单列序），章号 1/2/3、标题是「一、xxx」
        assert len(chapters) == 3
        assert [c[0] for c in chapters] == [1, 2, 3]
        assert chapters[0][1] == "一、总体要求"

    def test_no_top_level_marks_stays_one_chapter(self):
        # 普通叙述、无章头也无顶层「一、」→ 整份 1 章（原行为，novel / 散文不受影响）
        text = "这是一段没有章节也没有顶层数字标记的普通文字。" * 40
        assert len(detect_chapters(text)) == 1

    def test_fewer_than_three_marks_no_split(self):
        # 只 1-2 个「一、」→ 不切（避免正文里零星一句被当小标题），回退整份 1 章
        text = f"正文引子。\n一、就这一条\n{_BODY}\n二、还有一条\n{_BODY}\n"
        assert len(detect_chapters(text)) == 1

    def test_real_chapters_take_priority(self):
        # 有「第X章」→ 走主检测，公文 fallback 根本不触发
        text = f"第一章 开端\n{_BODY}\n第二章 风起\n{_BODY}\n"
        chapters = detect_chapters(text)
        assert len(chapters) == 2
        assert [c[0] for c in chapters] == [1, 2]
