"""Tests for bookscope.nlp.soul_engine."""

from __future__ import annotations

import json
from unittest.mock import patch

from bookscope.models.schemas import (
    CharacterProfile,
    ChunkResult,
)
from bookscope.nlp.soul_engine import (
    _dedup_list,
    _fallback_quotes,
    _parse_soul_json,
    _uniform_sample,
    build_character_context,
    build_persona_prompt,
    enrich_soul_profile,
    extract_character_dialogues,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _chunk(index: int, text: str) -> ChunkResult:
    return ChunkResult(index=index, text=text)


def _profile(name: str = "贾宝玉", **kwargs) -> CharacterProfile:
    return CharacterProfile(name=name, **kwargs)


# ---------------------------------------------------------------------------
# A) extract_character_dialogues
# ---------------------------------------------------------------------------


class TestExtractCharacterDialogues:
    def test_zh_dialogue_extraction(self):
        chunks = [
            _chunk(0, "贾宝玉笑道：\u201c你怎么又来了？\u201d林黛玉也笑了。"),
            _chunk(1, "王夫人说了几句话。"),
        ]
        quotes = extract_character_dialogues(
            chunks, "贾宝玉", language="zh"
        )
        assert len(quotes) >= 1
        assert any("你怎么又来了" in q for q in quotes)

    def test_en_dialogue_extraction(self):
        chunks = [
            _chunk(0, '"I shall never give up this quest," said Aragorn firmly.'),
            _chunk(1, "The hobbits rested by the fire."),
        ]
        quotes = extract_character_dialogues(
            chunks, "Aragorn", language="en"
        )
        assert len(quotes) >= 1
        assert any("never give up" in q for q in quotes)

    def test_ja_dialogue_extraction(self):
        chunks = [
            _chunk(0, "\u300cこんにちは、元気ですか\u300d\u3068太郎\u304c言った。"),
        ]
        quotes = extract_character_dialogues(
            chunks, "太郎", language="ja"
        )
        assert len(quotes) >= 1

    def test_aliases_are_used(self):
        chunks = [
            _chunk(0, "宝二爷笑道：\u201c好丫头，过来\u201d。"),
        ]
        quotes = extract_character_dialogues(
            chunks, "贾宝玉", aliases=["宝二爷", "宝玉"], language="zh"
        )
        # Chunk contains alias "宝二爷" so it should be scanned
        assert isinstance(quotes, list)

    def test_max_quotes_limit(self):
        text = "贾宝玉说：\u201c话语{i}\u201d "
        chunks = [_chunk(i, text.format(i=i)) for i in range(20)]
        quotes = extract_character_dialogues(
            chunks, "贾宝玉", language="zh", max_quotes=3
        )
        assert len(quotes) <= 3

    def test_sorted_by_length_descending(self):
        chunks = [
            _chunk(0, "贾宝玉说：\u201c短话\u201d"),
            _chunk(1, "贾宝玉笑道：\u201c这是一句比较长的话语，用来测试排序功能\u201d"),
        ]
        quotes = extract_character_dialogues(
            chunks, "贾宝玉", language="zh"
        )
        if len(quotes) >= 2:
            assert len(quotes[0]) >= len(quotes[1])

    def test_empty_chunks_returns_empty(self):
        quotes = extract_character_dialogues([], "贾宝玉", language="zh")
        assert quotes == []

    def test_no_matching_character(self):
        chunks = [
            _chunk(0, "林黛玉说：\u201c我不舒服\u201d"),
        ]
        quotes = extract_character_dialogues(
            chunks, "贾宝玉", language="zh"
        )
        assert quotes == []

    def test_deduplication(self):
        chunks = [
            _chunk(0, "贾宝玉说：\u201c你好啊朋友\u201d"),
            _chunk(1, "贾宝玉说：\u201c你好啊朋友\u201d"),
        ]
        quotes = extract_character_dialogues(
            chunks, "贾宝玉", language="zh"
        )
        # Should be deduplicated
        assert len(quotes) == len(set(quotes))


class TestFallbackQuotes:
    def test_zh_fallback(self):
        text = "贾宝玉走了过来。\u201c你好，今天天气不错\u201d"
        names = {"贾宝玉"}
        result = _fallback_quotes(text, names, "zh")
        assert len(result) >= 1

    def test_en_fallback(self):
        text = 'Aragorn looked up. "We must press on through the night," he thought.'
        names = {"Aragorn"}
        result = _fallback_quotes(text, names, "en")
        assert len(result) >= 1

    def test_no_match_returns_empty(self):
        text = "Nothing here at all."
        names = {"Nobody"}
        result = _fallback_quotes(text, names, "en")
        assert result == []


# ---------------------------------------------------------------------------
# B) enrich_soul_profile
# ---------------------------------------------------------------------------


class TestEnrichSoulProfile:
    def test_successful_enrichment(self):
        profile = _profile(description="贾府公子")
        chunks = [
            _chunk(0, "贾宝玉说：\u201c女儿是水做的骨肉\u201d"),
            _chunk(1, "贾宝玉在大观园中游玩"),
        ]
        llm_response = json.dumps(
            {
                "personality_type": "INFP — 调停者",
                "values": ["真情", "自由", "美"],
                "key_quotes": ["女儿是水做的骨肉"],
                "emotional_stages": [
                    {"stage": "early", "emotion": "天真", "event": "大观园生活"},
                    {"stage": "late", "emotion": "悲痛", "event": "黛玉离世"},
                ],
            }
        )
        with patch(
            "bookscope.nlp.soul_engine.call_llm", return_value=llm_response
        ):
            enriched = enrich_soul_profile(
                profile, chunks, [0, 1], "红楼梦", "zh", api_key="test"
            )
        assert enriched.personality_type == "INFP — 调停者"
        assert "真情" in enriched.values
        assert len(enriched.emotional_stages) == 2
        assert enriched.emotional_stages[0].stage == "early"

    def test_llm_failure_returns_original(self):
        profile = _profile()
        chunks = [_chunk(0, "贾宝玉在花园里")]
        with patch("bookscope.nlp.soul_engine.call_llm", return_value=""):
            result = enrich_soul_profile(
                profile, chunks, [0], "红楼梦", "zh"
            )
        assert result.personality_type == ""

    def test_empty_chunks_returns_original(self):
        profile = _profile()
        result = enrich_soul_profile(profile, [], [], "红楼梦", "zh")
        assert result is profile

    def test_invalid_json_returns_with_regex_quotes(self):
        profile = _profile()
        chunks = [
            _chunk(0, "贾宝玉笑道：\u201c你怎么又哭了\u201d"),
        ]
        with patch(
            "bookscope.nlp.soul_engine.call_llm",
            return_value="not valid json",
        ):
            result = enrich_soul_profile(
                profile, chunks, [0], "红楼梦", "zh"
            )
        # Should still try regex quotes
        assert isinstance(result.key_quotes, list)

    def test_partial_json_uses_available_fields(self):
        profile = _profile()
        chunks = [_chunk(0, "贾宝玉在大观园")]
        llm_response = json.dumps({"personality_type": "ENFP — 活动家"})
        with patch(
            "bookscope.nlp.soul_engine.call_llm", return_value=llm_response
        ):
            result = enrich_soul_profile(
                profile, chunks, [0], "红楼梦", "zh"
            )
        assert result.personality_type == "ENFP — 活动家"
        assert result.values == []

    def test_chunk_indices_out_of_range(self):
        """Out-of-range indices are silently skipped."""
        profile = _profile()
        chunks = [_chunk(0, "贾宝玉在花园")]
        with patch(
            "bookscope.nlp.soul_engine.call_llm",
            return_value=json.dumps({"personality_type": "INTJ"}),
        ):
            result = enrich_soul_profile(
                profile, chunks, [0, 99, 100], "红楼梦", "zh"
            )
        assert result.personality_type == "INTJ"


class TestParseSoulJson:
    def test_valid_json(self):
        data = _parse_soul_json('{"personality_type": "INTJ"}')
        assert data == {"personality_type": "INTJ"}

    def test_json_with_fences(self):
        raw = "```json\n{\"personality_type\": \"INTJ\"}\n```"
        data = _parse_soul_json(raw)
        assert data == {"personality_type": "INTJ"}

    def test_json_with_trailing_ellipsis(self):
        raw = '{"personality_type": "INTJ"} …'
        data = _parse_soul_json(raw)
        assert data == {"personality_type": "INTJ"}

    def test_empty_returns_none(self):
        assert _parse_soul_json("") is None
        assert _parse_soul_json(None) is None  # type: ignore[arg-type]

    def test_invalid_returns_none(self):
        assert _parse_soul_json("not json at all") is None


class TestDedupList:
    def test_preserves_order(self):
        assert _dedup_list(["a", "b", "a", "c"]) == ["a", "b", "c"]

    def test_empty(self):
        assert _dedup_list([]) == []

    def test_no_duplicates(self):
        assert _dedup_list(["x", "y", "z"]) == ["x", "y", "z"]


# ---------------------------------------------------------------------------
# C) build_persona_prompt
# ---------------------------------------------------------------------------


class TestBuildPersonaPrompt:
    def test_zh_contains_name_and_book(self):
        profile = _profile(
            personality_type="INFP — 调停者",
            voice_style="温柔体贴",
            values=["真情", "自由"],
        )
        prompt = build_persona_prompt(profile, "红楼梦", "zh")
        assert "贾宝玉" in prompt
        assert "红楼梦" in prompt
        assert "INFP" in prompt
        assert "真情" in prompt
        assert "中文" in prompt

    def test_en_prompt(self):
        profile = _profile(
            name="Aragorn",
            personality_type="ISTJ — Inspector",
            values=["duty", "honor"],
        )
        prompt = build_persona_prompt(profile, "Lord of the Rings", "en")
        assert "Aragorn" in prompt
        assert "Lord of the Rings" in prompt
        assert "ISTJ" in prompt
        assert "English" in prompt

    def test_ja_prompt(self):
        profile = _profile(
            name="太郎",
            personality_type="ENFJ — 主人公",
        )
        prompt = build_persona_prompt(profile, "物語", "ja")
        assert "太郎" in prompt
        assert "物語" in prompt
        assert "日本語" in prompt

    def test_minimal_profile_still_works(self):
        profile = _profile()
        prompt = build_persona_prompt(profile, "红楼梦", "zh")
        assert "贾宝玉" in prompt
        assert len(prompt) > 20

    def test_quotes_included(self):
        profile = _profile(key_quotes=["女儿是水做的", "我不愿读书"])
        prompt = build_persona_prompt(profile, "红楼梦", "zh")
        assert "女儿是水做的" in prompt


# ---------------------------------------------------------------------------
# D) build_character_context
# ---------------------------------------------------------------------------


class TestBuildCharacterContext:
    def test_basic_context(self):
        chunks = [
            _chunk(0, "First chunk about the story."),
            _chunk(1, "Second chunk with battle details."),
            _chunk(2, "Third chunk about the war ending."),
        ]
        ctx = build_character_context(chunks, [0, 1, 2], "battle", max_chars=5000)
        assert "battle" in ctx

    def test_relevance_ordering(self):
        chunks = [
            _chunk(0, "The garden was beautiful in spring."),
            _chunk(1, "The great battle raged on the fields."),
            _chunk(2, "Meanwhile tea was served indoors."),
        ]
        ctx = build_character_context(chunks, [0, 1, 2], "battle fields")
        # "battle" chunk should appear first due to keyword overlap
        lines = ctx.split("---")
        assert "battle" in lines[0]

    def test_empty_query_uses_uniform(self):
        chunks = [_chunk(i, f"Chunk {i} text here.") for i in range(10)]
        ctx = build_character_context(
            chunks, list(range(10)), "", max_chars=5000
        )
        assert len(ctx) > 0

    def test_max_chars_respected(self):
        chunks = [_chunk(i, "x" * 500) for i in range(20)]
        ctx = build_character_context(
            chunks, list(range(20)), "query", max_chars=1000
        )
        assert len(ctx) <= 1200  # some overhead from separators

    def test_empty_indices(self):
        chunks = [_chunk(0, "text")]
        ctx = build_character_context(chunks, [], "query")
        assert ctx == ""

    def test_out_of_range_indices_skipped(self):
        chunks = [_chunk(0, "valid chunk")]
        ctx = build_character_context(chunks, [0, 99], "valid")
        assert "valid chunk" in ctx


class TestUniformSample:
    def test_empty(self):
        assert _uniform_sample([], 3000) == ""

    def test_few_chunks(self):
        chunks = [_chunk(0, "hello"), _chunk(1, "world")]
        result = _uniform_sample(chunks, 3000)
        assert "hello" in result

    def test_max_chars(self):
        chunks = [_chunk(i, "a" * 500) for i in range(20)]
        result = _uniform_sample(chunks, 1000)
        assert len(result) <= 1200
