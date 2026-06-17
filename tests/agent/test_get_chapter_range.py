"""bookscope.agent.tools.get_chapter_range 的单测。

覆盖点：
- 合计字数 > 20 万时抛 ChapterRangeTooLarge 且携带 word_count + limit
- 合计字数 <= 20 万时正常 delegate 到 backend
- GetChapterRangeInput 的字段校验（start <= end、ge=1 等）
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from bookscope.agent.tools.errors import ChapterRangeTooLarge
from bookscope.agent.tools.get_chapter_range import (
    CHAPTER_RANGE_WORD_LIMIT,
    ChapterTextBackend,
    GetChapterRangeInput,
    get_chapter_range,
)
from bookscope.agent.tools.schemas import ChapterText

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _FakeChapterBackend:
    """内存版章节 backend，覆盖 ChapterTextBackend Protocol。"""

    def __init__(
        self,
        chapters: list[ChapterText],
        total_words_override: int | None = None,
    ) -> None:
        self._chapters = chapters
        self._total_words_override = total_words_override
        self.total_words_calls: list[tuple[int, int]] = []
        self.get_chapters_calls: list[tuple[int, int]] = []

    def total_words(self, start: int, end: int) -> int:
        self.total_words_calls.append((start, end))
        if self._total_words_override is not None:
            return self._total_words_override
        return sum(c.word_count for c in self._chapters if start <= c.chapter <= end)

    def get_chapters(self, start: int, end: int) -> list[ChapterText]:
        self.get_chapters_calls.append((start, end))
        return [c for c in self._chapters if start <= c.chapter <= end]


def _chapter(ch: int, words: int) -> ChapterText:
    return ChapterText(
        chapter=ch,
        title=f"第{ch}章",
        full_text="x" * max(words, 1),
        word_count=words,
        source_version="r0",
    )


# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------


class TestGetChapterRangeInput:
    def test_accepts_single_chapter(self):
        inp = GetChapterRangeInput(start_chapter=3, end_chapter=3)
        assert inp.start_chapter == 3

    def test_rejects_zero_chapter(self):
        with pytest.raises(ValidationError):
            GetChapterRangeInput(start_chapter=0, end_chapter=1)

    def test_rejects_reversed_range(self):
        with pytest.raises(ValidationError):
            GetChapterRangeInput(start_chapter=5, end_chapter=3)


# ---------------------------------------------------------------------------
# get_chapter_range dispatcher
# ---------------------------------------------------------------------------


class TestGetChapterRangeDispatcher:
    def test_within_limit_delegates_to_backend(self):
        backend = _FakeChapterBackend([_chapter(1, 100), _chapter(2, 200)])
        inp = GetChapterRangeInput(start_chapter=1, end_chapter=2)

        out = get_chapter_range(inp, backend)

        assert len(out) == 2
        assert [c.chapter for c in out] == [1, 2]
        assert backend.total_words_calls == [(1, 2)]
        assert backend.get_chapters_calls == [(1, 2)]

    def test_over_limit_raises_chapter_range_too_large(self):
        over = CHAPTER_RANGE_WORD_LIMIT + 1
        backend = _FakeChapterBackend([], total_words_override=over)
        inp = GetChapterRangeInput(start_chapter=1, end_chapter=50)

        with pytest.raises(ChapterRangeTooLarge) as excinfo:
            get_chapter_range(inp, backend)

        # 错误必须携带实际 word_count 和 limit，供 agent 自我修正
        assert excinfo.value.word_count == over
        assert excinfo.value.limit == CHAPTER_RANGE_WORD_LIMIT
        # 超限时不应调用 get_chapters，避免昂贵 I/O
        assert backend.get_chapters_calls == []

    def test_exactly_at_limit_is_allowed(self):
        backend = _FakeChapterBackend(
            [_chapter(1, CHAPTER_RANGE_WORD_LIMIT)],
            total_words_override=CHAPTER_RANGE_WORD_LIMIT,
        )
        inp = GetChapterRangeInput(start_chapter=1, end_chapter=1)

        out = get_chapter_range(inp, backend)

        assert len(out) == 1

    def test_protocol_structural_typing(self):
        # _FakeChapterBackend 不显式继承 ChapterTextBackend——
        # 通过 Protocol 的 structural typing 也应被接受。
        backend: ChapterTextBackend = _FakeChapterBackend([_chapter(1, 10)])
        assert callable(backend.total_words)
        assert callable(backend.get_chapters)
