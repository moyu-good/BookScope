"""``R0ChapterRangeBackend`` 单测。

关键原则：**不跑真 ingest pipeline**（不 load epub、不跑 cleaner + chunker）。
真 ingest 要跑文件 IO + 正则检测 + 段落合并，不适合单测粒度。用 mock
的 ``R0ChapterRecord`` 列表直接喂给 backend，验证 Protocol 一致性、
边界、超范围与 dispatcher 集成。

覆盖点：
- Protocol 结构型一致（``ChapterTextBackend``）
- ``get_chapters`` 正常路径：返回多章、单章、端点正确
- ``get_chapters`` 产出为 ``ChapterText`` 且 ``source_version == "r0"``
- ``total_words`` 小 / 超范围的语义
- ``get_chapters`` 的 ``ValueError``：start > end、start < 1、end < 1
- ``get_chapters`` 的 ``ChapterNotFound``：end 超过总章节数、空书
- Dispatcher 集成：通过 ``get_chapter_range(params, backend)`` 触发
  20 万字上限校验
"""

from __future__ import annotations

import inspect

import pytest

from bookscope.agent.backends import R0ChapterRangeBackend, R0ChapterRecord
from bookscope.agent.tools import ChapterTextBackend
from bookscope.agent.tools.errors import ChapterNotFound, ChapterRangeTooLarge
from bookscope.agent.tools.get_chapter_range import (
    CHAPTER_RANGE_WORD_LIMIT,
    GetChapterRangeInput,
    get_chapter_range,
)
from bookscope.agent.tools.schemas import ChapterText

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _record(chapter: int, words: int = 500, title: str | None = None) -> R0ChapterRecord:
    """制造一条 ``R0ChapterRecord`` 用的便捷 helper。"""
    return R0ChapterRecord(
        chapter=chapter,
        title=title if title is not None else f"第{chapter}章",
        # full_text 必须非空（Pydantic ``ChapterText`` 校验）。
        full_text=f"章节{chapter}原文：" + ("甲" * max(words, 1)),
        word_count=words,
    )


@pytest.fixture()
def sample_records() -> list[R0ChapterRecord]:
    """六章的 mock 数据，每章 500 字，合计 3000 字（远低于 20 万字上限）。"""
    return [_record(n, words=500) for n in range(1, 7)]


# ---------------------------------------------------------------------------
# Protocol 结构型检查
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_backend_satisfies_chapter_text_backend_protocol(self, sample_records):
        """``R0ChapterRangeBackend`` 必须满足 ``ChapterTextBackend`` Protocol。"""
        backend = R0ChapterRangeBackend(sample_records)
        assert hasattr(backend, "total_words")
        assert hasattr(backend, "get_chapters")
        assert callable(backend.total_words)
        assert callable(backend.get_chapters)

        # 最小签名检查：避免硬编码细节。
        total_sig = inspect.signature(backend.total_words)
        get_sig = inspect.signature(backend.get_chapters)
        assert {"start", "end"}.issubset(total_sig.parameters.keys())
        assert {"start", "end"}.issubset(get_sig.parameters.keys())

        # structural typing：直接赋给 Protocol 变量不应报错。
        typed: ChapterTextBackend = backend
        assert callable(typed.total_words)


# ---------------------------------------------------------------------------
# get_chapters 正常路径
# ---------------------------------------------------------------------------


class TestGetChaptersHappyPath:
    def test_returns_three_chapters_as_chapter_text_with_r0_tag(
        self,
        sample_records,
    ):
        """``get_chapters(1, 3)`` 返回 3 章，每条是 ``ChapterText`` 且
        ``source_version == "r0"``。
        """
        backend = R0ChapterRangeBackend(sample_records)
        out = backend.get_chapters(1, 3)

        assert len(out) == 3
        assert all(isinstance(c, ChapterText) for c in out)
        assert [c.chapter for c in out] == [1, 2, 3]
        assert all(c.source_version == "r0" for c in out)

    def test_single_chapter_boundary(self, sample_records):
        """``get_chapters(1, 1)`` 返回单章（边界）。"""
        backend = R0ChapterRangeBackend(sample_records)
        out = backend.get_chapters(1, 1)

        assert len(out) == 1
        assert out[0].chapter == 1

    def test_preserves_title_and_full_text(self, sample_records):
        """返回的 ``ChapterText`` 应忠实携带 title / full_text。"""
        backend = R0ChapterRangeBackend(sample_records)
        out = backend.get_chapters(2, 2)

        assert out[0].title == "第2章"
        assert "章节2原文：" in out[0].full_text


# ---------------------------------------------------------------------------
# total_words
# ---------------------------------------------------------------------------


class TestTotalWords:
    def test_positive_sum_over_range(self, sample_records):
        """``total_words(1, 5)`` 返回正整数；每章 500 字，合计 2500。"""
        backend = R0ChapterRangeBackend(sample_records)
        assert backend.total_words(1, 5) == 2500

    def test_single_chapter_word_count(self, sample_records):
        backend = R0ChapterRangeBackend(sample_records)
        assert backend.total_words(3, 3) == 500

    def test_total_words_raises_chapter_not_found_on_overflow(
        self,
        sample_records,
    ):
        """``total_words`` 对超范围 end 抛 ``ChapterNotFound``。

        选择"抛错"而非"返回已有章节字数总和"——这是 r0 的自然语义：
        agent 提了个部分越界的范围，就说明它对章节目录理解不准，应该让
        agent 收到结构化错误并收缩范围，而不是静默给出不完整数据。
        dispatcher 层走 ``total_words`` 做上限检查时，这种错误会直接
        冒到 agent，被 agent loop 按 ``ToolError`` 捕获转译成自我修正
        提示。
        """
        backend = R0ChapterRangeBackend(sample_records)
        with pytest.raises(ChapterNotFound):
            backend.total_words(1, 999)


# ---------------------------------------------------------------------------
# ValueError：非法 start/end
# ---------------------------------------------------------------------------


class TestInputValueErrors:
    def test_start_greater_than_end_raises_value_error(self, sample_records):
        backend = R0ChapterRangeBackend(sample_records)
        with pytest.raises(ValueError, match="start_chapter"):
            backend.get_chapters(5, 3)

    def test_start_below_one_raises_value_error(self, sample_records):
        backend = R0ChapterRangeBackend(sample_records)
        with pytest.raises(ValueError, match=r"start_chapter must be >= 1"):
            backend.get_chapters(0, 3)

    def test_end_below_one_raises_value_error(self, sample_records):
        backend = R0ChapterRangeBackend(sample_records)
        with pytest.raises(ValueError, match=r"end_chapter must be >= 1"):
            # start 合法、end 非法的情形
            backend.get_chapters(1, 0)

    def test_total_words_reuses_same_validation(self, sample_records):
        backend = R0ChapterRangeBackend(sample_records)
        with pytest.raises(ValueError):
            backend.total_words(-1, 3)


# ---------------------------------------------------------------------------
# ChapterNotFound：超过总章节 / 空书
# ---------------------------------------------------------------------------


class TestChapterNotFound:
    def test_end_beyond_last_chapter_raises_chapter_not_found(
        self,
        sample_records,
    ):
        """``get_chapters(1, 999)`` 当 999 超过总章节数时抛 ``ChapterNotFound``。"""
        backend = R0ChapterRangeBackend(sample_records)
        with pytest.raises(ChapterNotFound, match="exceeds the last available"):
            backend.get_chapters(1, 999)

    def test_start_not_present_raises_chapter_not_found(self):
        """构造时只给 2、3、4 章——start=1 不存在时抛 ``ChapterNotFound``。"""
        backend = R0ChapterRangeBackend(
            [_record(2, 100), _record(3, 100), _record(4, 100)]
        )
        with pytest.raises(ChapterNotFound, match="not present"):
            backend.get_chapters(1, 3)

    def test_empty_book_raises_chapter_not_found(self):
        """空书（mock 0 章）``get_chapters(1, 1)`` 抛 ``ChapterNotFound``。"""
        backend = R0ChapterRangeBackend([])
        with pytest.raises(ChapterNotFound, match="no chapter records"):
            backend.get_chapters(1, 1)

    def test_empty_book_total_words_also_raises(self):
        backend = R0ChapterRangeBackend([])
        with pytest.raises(ChapterNotFound):
            backend.total_words(1, 1)


# ---------------------------------------------------------------------------
# 构造参数的卫生性
# ---------------------------------------------------------------------------


class TestConstructorHygiene:
    def test_duplicate_chapter_rejected(self):
        """章节号重复说明上层装配出错，构造直接报错避免静默合并。"""
        with pytest.raises(ValueError, match="duplicate chapter"):
            R0ChapterRangeBackend([_record(1, 100), _record(1, 200)])

    def test_unsorted_input_is_sorted_internally(self):
        """构造时传入乱序列表，backend 内部应按 chapter 升序排序。"""
        backend = R0ChapterRangeBackend(
            [_record(3, 300), _record(1, 100), _record(2, 200)]
        )
        out = backend.get_chapters(1, 3)
        assert [c.chapter for c in out] == [1, 2, 3]
        assert [c.word_count for c in out] == [100, 200, 300]


# ---------------------------------------------------------------------------
# Dispatcher 集成：通过 get_chapter_range(params, backend) 走全链路
# ---------------------------------------------------------------------------


class TestDispatcherIntegration:
    def test_end_to_end_under_limit(self, sample_records):
        """dispatcher 正常 delegate，返回按 chapter 升序的 ``ChapterText``。"""
        backend = R0ChapterRangeBackend(sample_records)
        inp = GetChapterRangeInput(start_chapter=1, end_chapter=3)
        out = get_chapter_range(inp, backend)

        assert len(out) == 3
        assert [c.chapter for c in out] == [1, 2, 3]
        assert all(c.source_version == "r0" for c in out)

    def test_dispatcher_triggers_chapter_range_too_large(self):
        """20 万字上限必须在 **dispatcher 层** 触发（不是 backend 自作主张）。

        构造超过上限的单章：全书仅 1 章、字数 20_0001，通过 dispatcher
        调用时应该在拉 ``get_chapters`` 之前就被 ``total_words`` 拒掉。
        """
        over_limit = CHAPTER_RANGE_WORD_LIMIT + 1
        backend = R0ChapterRangeBackend(
            [_record(1, words=over_limit, title="超长章节")]
        )
        inp = GetChapterRangeInput(start_chapter=1, end_chapter=1)

        with pytest.raises(ChapterRangeTooLarge) as excinfo:
            get_chapter_range(inp, backend)

        assert excinfo.value.word_count == over_limit
        assert excinfo.value.limit == CHAPTER_RANGE_WORD_LIMIT

    def test_dispatcher_propagates_chapter_not_found(self, sample_records):
        """backend 抛 ``ChapterNotFound`` 时 dispatcher 应原样传出，
        让 agent loop 层统一转成结构化 error。
        """
        backend = R0ChapterRangeBackend(sample_records)
        inp = GetChapterRangeInput(start_chapter=1, end_chapter=99)

        with pytest.raises(ChapterNotFound):
            get_chapter_range(inp, backend)
