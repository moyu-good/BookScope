"""bookscope.agent.tools.schemas 的 Pydantic schema 单测。

覆盖点：
- 三个返回类型的正确创建
- frozen=True 带来的不可变性
- source_version 只接受 Literal["r0", "r1"]
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from bookscope.agent.tools.schemas import (
    ChapterText,
    CharacterRef,
    ChunkMatch,
)

# ---------------------------------------------------------------------------
# Fixture data
# ---------------------------------------------------------------------------


def _chunk_match_payload() -> dict:
    return {
        "chunk_id": "ch03-p12",
        "chapter": 3,
        "text": "朱元璋沉默地看着李善长，良久不语。",
        "relevance_score": 0.87,
        "contains_characters": ["朱元璋", "李善长"],
        "source_version": "r0",
    }


def _chapter_text_payload() -> dict:
    return {
        "chapter": 3,
        "title": "风起南京",
        "full_text": "洪武三年春，……",
        "word_count": 4231,
        "source_version": "r0",
    }


def _character_ref_payload() -> dict:
    return {
        "name": "朱老板",
        "canonical_name": "朱元璋",
        "mention_count": 12,
        "first_appearance_position": 0.08,
        "source_version": "r0",
    }


# ---------------------------------------------------------------------------
# ChunkMatch
# ---------------------------------------------------------------------------


class TestChunkMatch:
    def test_create_ok(self):
        m = ChunkMatch(**_chunk_match_payload())
        assert m.chunk_id == "ch03-p12"
        assert m.relevance_score == pytest.approx(0.87)
        assert m.contains_characters == ["朱元璋", "李善长"]
        assert m.source_version == "r0"

    def test_frozen_is_immutable(self):
        m = ChunkMatch(**_chunk_match_payload())
        with pytest.raises(ValidationError):
            m.relevance_score = 0.1  # type: ignore[misc]

    def test_invalid_source_version_rejected(self):
        payload = _chunk_match_payload()
        payload["source_version"] = "r2"
        with pytest.raises(ValidationError):
            ChunkMatch(**payload)

    def test_relevance_score_bounds(self):
        payload = _chunk_match_payload()
        payload["relevance_score"] = 1.1
        with pytest.raises(ValidationError):
            ChunkMatch(**payload)

    def test_empty_text_rejected(self):
        payload = _chunk_match_payload()
        payload["text"] = ""
        with pytest.raises(ValidationError):
            ChunkMatch(**payload)


# ---------------------------------------------------------------------------
# ChapterText
# ---------------------------------------------------------------------------


class TestChapterText:
    def test_create_ok(self):
        ct = ChapterText(**_chapter_text_payload())
        assert ct.chapter == 3
        assert ct.word_count == 4231

    def test_frozen_is_immutable(self):
        ct = ChapterText(**_chapter_text_payload())
        with pytest.raises(ValidationError):
            ct.word_count = 0  # type: ignore[misc]

    def test_invalid_source_version_rejected(self):
        payload = _chapter_text_payload()
        payload["source_version"] = "legacy"
        with pytest.raises(ValidationError):
            ChapterText(**payload)

    def test_word_count_non_negative(self):
        payload = _chapter_text_payload()
        payload["word_count"] = -1
        with pytest.raises(ValidationError):
            ChapterText(**payload)


# ---------------------------------------------------------------------------
# CharacterRef
# ---------------------------------------------------------------------------


class TestCharacterRef:
    def test_create_ok(self):
        c = CharacterRef(**_character_ref_payload())
        assert c.canonical_name == "朱元璋"
        assert c.mention_count == 12
        assert c.first_appearance_position == pytest.approx(0.08)

    def test_frozen_is_immutable(self):
        c = CharacterRef(**_character_ref_payload())
        with pytest.raises(ValidationError):
            c.mention_count = 1  # type: ignore[misc]

    def test_invalid_source_version_rejected(self):
        payload = _character_ref_payload()
        payload["source_version"] = "v7"
        with pytest.raises(ValidationError):
            CharacterRef(**payload)

    def test_mention_count_min_one(self):
        payload = _character_ref_payload()
        payload["mention_count"] = 0
        with pytest.raises(ValidationError):
            CharacterRef(**payload)

    def test_position_bounds(self):
        payload = _character_ref_payload()
        payload["first_appearance_position"] = 1.5
        with pytest.raises(ValidationError):
            CharacterRef(**payload)
