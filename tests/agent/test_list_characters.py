"""bookscope.agent.tools.list_characters_in_chapter 的单测。

覆盖点：
- dispatcher 正确 delegate 到 backend
- 返回对象类型为 CharacterRef
- 入参 schema 的章节号下限
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from bookscope.agent.tools.list_characters_in_chapter import (
    CharacterIndexBackend,
    ListCharactersInChapterInput,
    list_characters_in_chapter,
)
from bookscope.agent.tools.schemas import CharacterRef


class _FakeCharacterBackend:
    """内存版角色倒排索引 backend。"""

    def __init__(self, mapping: dict[int, list[CharacterRef]]) -> None:
        self._mapping = mapping
        self.calls: list[int] = []

    def characters_in(self, chapter: int) -> list[CharacterRef]:
        self.calls.append(chapter)
        return self._mapping.get(chapter, [])


def _ref(canonical: str, count: int, pos: float = 0.1) -> CharacterRef:
    return CharacterRef(
        name=canonical,
        canonical_name=canonical,
        mention_count=count,
        first_appearance_position=pos,
        source_version="r0",
    )


class TestListCharactersInChapterInput:
    def test_accepts_chapter_one(self):
        inp = ListCharactersInChapterInput(chapter=1)
        assert inp.chapter == 1

    def test_rejects_zero_chapter(self):
        with pytest.raises(ValidationError):
            ListCharactersInChapterInput(chapter=0)


class TestListCharactersDispatcher:
    def test_delegates_to_backend(self):
        refs = [_ref("朱元璋", 12), _ref("李善长", 4)]
        backend = _FakeCharacterBackend({3: refs})
        inp = ListCharactersInChapterInput(chapter=3)

        out = list_characters_in_chapter(inp, backend)

        assert out == refs
        assert backend.calls == [3]
        assert all(isinstance(c, CharacterRef) for c in out)

    def test_empty_chapter_returns_empty_list(self):
        backend = _FakeCharacterBackend({})
        inp = ListCharactersInChapterInput(chapter=99)

        out = list_characters_in_chapter(inp, backend)

        assert out == []
        assert backend.calls == [99]

    def test_protocol_structural_typing(self):
        backend: CharacterIndexBackend = _FakeCharacterBackend({})
        assert callable(backend.characters_in)
