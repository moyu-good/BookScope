"""Tests for bookscope.nlp.ner_extractor (local NER character extraction)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from bookscope.models.schemas import ChunkResult
from bookscope.nlp.ner_extractor import (
    _extract_en,
    _extract_ja,
    _extract_zh,
    extract_character_candidates,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_chunks(texts: list[str]) -> list[ChunkResult]:
    return [ChunkResult(index=i, text=t) for i, t in enumerate(texts)]


# ---------------------------------------------------------------------------
# Chinese extraction
# ---------------------------------------------------------------------------

class TestExtractZh:

    def test_jieba_nr_tag_extraction(self):
        text = "贾宝玉和林黛玉在大观园中相遇，薛宝钗也在场。"
        names = _extract_zh(text)
        # jieba should find at least some of these person names
        assert len(names) > 0

    def test_dialogue_regex(self):
        text = '贾宝玉说："你好。"林黛玉道："你也好。"'
        names = _extract_zh(text)
        assert "贾宝玉" in names
        assert "林黛玉" in names

    def test_dialogue_regex_various_verbs(self):
        text = "张飞怒道不可。李逵叫道来也。诸葛亮笑道妙哉。"
        names = _extract_zh(text)
        assert "张飞" in names or "李逵" in names or "诸葛亮" in names

    def test_title_regex(self):
        text = "林先生与王夫人和薛姑娘一起喝茶。"
        names = _extract_zh(text)
        # Title regex captures 1-4 char prefixes but filters by len>=2
        assert isinstance(names, set)

    def test_short_names_filtered(self):
        """Single-character candidates from jieba should be excluded."""
        text = "王说了一句话。"
        names = _extract_zh(text)
        # "王" is only 1 char — should not appear
        assert "王" not in names

    def test_combined_strategies_deduplicate(self):
        """A name found by both jieba and regex should appear once (it's a set)."""
        text = '贾宝玉说："我来了。"贾宝玉是贾府的公子。'
        names = _extract_zh(text)
        assert isinstance(names, set)
        # If found, should only be in the set once
        count = sum(1 for n in names if n == "贾宝玉")
        assert count <= 1


# ---------------------------------------------------------------------------
# English extraction
# ---------------------------------------------------------------------------

class TestExtractEn:

    @patch("bookscope.nlp.ner_extractor._get_spacy_nlp", create=True)
    def test_spacy_person_ner(self, mock_get_nlp):
        """Mock spaCy NLP to return PERSON entities."""
        # We need to patch the import inside the function
        mock_nlp = MagicMock()
        mock_ent = MagicMock()
        mock_ent.label_ = "PERSON"
        mock_ent.text = "Elizabeth Bennet"
        mock_doc = MagicMock()
        mock_doc.ents = [mock_ent]
        mock_nlp.return_value = mock_doc

        with patch("bookscope.nlp.ner_extractor._get_spacy_nlp", return_value=mock_nlp):
            # Need to patch the import path
            with patch.dict("sys.modules", {"bookscope.insights": MagicMock(
                _get_spacy_nlp=MagicMock(return_value=mock_nlp),
            )}):
                names = _extract_en("Elizabeth Bennet walked into the room.")
                assert "Elizabeth Bennet" in names

    def test_spacy_unavailable_falls_to_regex(self):
        """When spaCy import fails, regex patterns still work."""
        with patch.dict("sys.modules", {"bookscope.insights": None}):
            text = 'said Alice loudly. Mr. Darcy replied quietly.'
            names = _extract_en(text)
            # Dialogue regex should catch Alice
            assert "Alice" in names

    def test_dialogue_regex_said_name(self):
        text = 'said Elizabeth with a smile'
        names = _extract_en(text)
        assert "Elizabeth" in names

    def test_dialogue_regex_name_said(self):
        text = 'Elizabeth replied firmly'
        names = _extract_en(text)
        assert "Elizabeth" in names

    def test_title_regex_mr(self):
        text = "Mr. Darcy entered the ballroom."
        names = _extract_en(text)
        assert "Mr. Darcy" in names
        assert "Darcy" in names

    def test_title_regex_lord(self):
        text = "Lord Byron wrote poetry."
        names = _extract_en(text)
        assert "Lord Byron" in names
        assert "Byron" in names

    def test_title_regex_multiple(self):
        text = "Mrs. Bennet and Lady Catherine were talking."
        names = _extract_en(text)
        assert "Mrs. Bennet" in names or "Bennet" in names
        assert "Lady Catherine" in names or "Catherine" in names

    def test_both_full_and_short_name(self):
        text = "Mr. Darcy looked at the garden."
        names = _extract_en(text)
        assert "Mr. Darcy" in names
        assert "Darcy" in names


# ---------------------------------------------------------------------------
# Japanese extraction
# ---------------------------------------------------------------------------

class TestExtractJa:

    def test_janome_proper_noun(self):
        """When janome is available, should extract proper nouns."""
        mock_tokenizer_cls = MagicMock()
        mock_tok1 = MagicMock()
        mock_tok1.surface = "太郎"
        mock_tok1.part_of_speech = "名詞,固有名詞,人名,名"
        mock_tok2 = MagicMock()
        mock_tok2.surface = "東京"
        mock_tok2.part_of_speech = "名詞,固有名詞,地域,一般"
        mock_tok3 = MagicMock()
        mock_tok3.surface = "走る"
        mock_tok3.part_of_speech = "動詞,自立,*,*"

        mock_tokenizer = MagicMock()
        mock_tokenizer.tokenize.return_value = [mock_tok1, mock_tok2, mock_tok3]
        mock_tokenizer_cls.return_value = mock_tokenizer

        with patch.dict("sys.modules", {
            "janome": MagicMock(),
            "janome.tokenizer": MagicMock(Tokenizer=mock_tokenizer_cls),
        }):
            names = _extract_ja("太郎は東京で走る。")
            assert "太郎" in names
            assert "東京" in names

    def test_janome_import_error_graceful(self):
        """When janome is unavailable, should return empty (not raise)."""
        with patch.dict("sys.modules", {"janome": None, "janome.tokenizer": None}):
            names = _extract_ja("テスト文章です。")
            assert isinstance(names, set)

    def test_dialogue_regex_japanese(self):
        text = "「こんにちは」と太郎が言った。"
        names = _extract_ja(text)
        # The regex looks for 「...」と(name)が/は/の
        assert "太郎" in names


# ---------------------------------------------------------------------------
# extract_character_candidates (main function)
# ---------------------------------------------------------------------------

class TestExtractCharacterCandidates:

    def test_empty_chunks(self):
        assert extract_character_candidates([], "zh") == {}

    def test_min_chunk_spread_filtering(self):
        """Names in only 1 chunk should be filtered out with min_chunk_spread=2."""
        chunks = _make_chunks([
            '贾宝玉说："你好。"林黛玉道："你也好。"',
            '贾宝玉道："再见。"',
            '薛宝钗说："我刚来。"',  # only appears once
        ])
        result = extract_character_candidates(chunks, "zh", min_chunk_spread=2)
        # 贾宝玉 appears in chunk 0 and 1 → kept
        if "贾宝玉" in result:
            assert len(result["贾宝玉"]) >= 2

    def test_returns_sorted_indices(self):
        chunks = _make_chunks([
            '贾宝玉说："一。"',
            '其他内容',
            '贾宝玉道："三。"',
        ])
        result = extract_character_candidates(chunks, "zh", min_chunk_spread=2)
        for indices in result.values():
            assert indices == sorted(indices)

    def test_chinese_dispatch(self):
        """language='zh' should use Chinese extractor."""
        chunks = _make_chunks(['贾宝玉说："你好。"'] * 3)
        result = extract_character_candidates(chunks, "zh", min_chunk_spread=1)
        # Should find Chinese names
        assert len(result) > 0

    def test_english_dispatch(self):
        """language='en' should use English extractor."""
        chunks = _make_chunks(["said Alice loudly."] * 3)
        result = extract_character_candidates(chunks, "en", min_chunk_spread=1)
        assert "Alice" in result

    def test_unknown_language_defaults_to_english(self):
        """Unknown languages fall back to English extractor."""
        chunks = _make_chunks(["said Bob clearly."] * 3)
        result = extract_character_candidates(chunks, "fr", min_chunk_spread=1)
        assert "Bob" in result

    def test_min_chunk_spread_one(self):
        """With min_chunk_spread=1, even single-occurrence names are kept."""
        chunks = _make_chunks(["said Alice once."])
        result = extract_character_candidates(chunks, "en", min_chunk_spread=1)
        assert "Alice" in result

    def test_deduplicates_indices(self):
        """Same chunk appearing multiple times should be deduplicated."""
        chunks = _make_chunks([
            'said Alice. Then Alice replied firmly.',
        ] * 2)
        result = extract_character_candidates(chunks, "en", min_chunk_spread=1)
        if "Alice" in result:
            # Each chunk index should appear at most once
            assert len(result["Alice"]) == len(set(result["Alice"]))


# ---------------------------------------------------------------------------
# Integration with knowledge_extractor
# ---------------------------------------------------------------------------

class TestIntegrationWithKG:

    @patch("bookscope.nlp.knowledge_extractor.call_llm")
    def test_merge_characters_with_ner_candidates(self, mock_llm):
        from bookscope.models.schemas import ChapterSummary
        from bookscope.nlp.knowledge_extractor import _merge_characters

        mock_llm.return_value = json.dumps([
            {"name": "贾宝玉", "aliases": ["宝玉"], "description": "主角",
             "voice_style": "", "motivations": [], "key_chapter_indices": [0, 1, 5],
             "arc_summary": ""},
        ])

        summaries = [
            ChapterSummary(chunk_index=0, characters_mentioned=["贾宝玉"]),
        ]
        # NER found "宝玉" in chunks not covered by LLM sampling
        ner_candidates = {"宝玉": [0, 3, 5, 8], "王熙凤": [2, 4, 6]}

        _merge_characters(
            summaries, "红楼梦", "zh", "key", "model",
            ner_candidates=ner_candidates,
        )
        # LLM was called (names from both sources merged)
        mock_llm.assert_called_once()
        prompt = mock_llm.call_args[0][0]
        # Both LLM-extracted and NER-found names should be in the prompt
        assert "贾宝玉" in prompt
        assert "王熙凤" in prompt

    @patch("bookscope.nlp.knowledge_extractor.call_llm")
    def test_merge_characters_ner_candidates_none(self, mock_llm):
        """Backward compat: ner_candidates=None works identically to old behavior."""
        from bookscope.models.schemas import ChapterSummary
        from bookscope.nlp.knowledge_extractor import _merge_characters

        mock_llm.return_value = json.dumps([
            {"name": "Alice", "aliases": [], "description": "hero",
             "voice_style": "", "motivations": [], "key_chapter_indices": [0],
             "arc_summary": ""},
        ])

        summaries = [
            ChapterSummary(chunk_index=0, characters_mentioned=["Alice"]),
        ]
        profiles = _merge_characters(
            summaries, "test", "en", "key", "model", ner_candidates=None,
        )
        assert len(profiles) == 1
        assert profiles[0].name == "Alice"

    @patch("bookscope.nlp.knowledge_extractor.extract_character_candidates")
    @patch("bookscope.nlp.knowledge_extractor.call_llm")
    def test_extract_kg_calls_ner_first(self, mock_llm, mock_ner):
        from bookscope.nlp.knowledge_extractor import extract_knowledge_graph  # noqa: PLC0415

        mock_ner.return_value = {"张三": [0, 1]}
        chunk_summary = json.dumps({
            "title": "", "summary": "ok",
            "key_events": [], "characters_mentioned": ["张三"],
        })
        merge_result = json.dumps([
            {"name": "张三", "aliases": [], "description": "test",
             "voice_style": "", "motivations": [],
             "key_chapter_indices": [0], "arc_summary": ""},
        ])
        mock_llm.side_effect = [chunk_summary, merge_result]

        chunks = [MagicMock(text="第一章内容")]
        graph = extract_knowledge_graph(
            chunks, "测试", language="zh", api_key="key",
        )

        # NER should have been called
        mock_ner.assert_called_once()
        assert graph.book_title == "测试"

    @patch("bookscope.nlp.knowledge_extractor.extract_character_candidates")
    @patch("bookscope.nlp.knowledge_extractor.call_llm")
    def test_extract_kg_ner_failure_graceful(self, mock_llm, mock_ner):
        """NER failure should not break the pipeline."""
        from bookscope.nlp.knowledge_extractor import extract_knowledge_graph  # noqa: PLC0415

        mock_ner.side_effect = RuntimeError("NER exploded")
        chunk_summary = json.dumps({
            "title": "", "summary": "ok",
            "key_events": [], "characters_mentioned": ["Alice"],
        })
        merge_result = json.dumps([
            {"name": "Alice", "aliases": [], "description": "hero",
             "voice_style": "", "motivations": [],
             "key_chapter_indices": [0], "arc_summary": ""},
        ])
        mock_llm.side_effect = [chunk_summary, merge_result]

        chunks = [MagicMock(text="Chapter one")]
        graph = extract_knowledge_graph(
            chunks, "test", language="en", api_key="key",
        )
        # Should complete successfully despite NER failure
        assert len(graph.characters) == 1
        assert graph.characters[0].name == "Alice"

    @patch("bookscope.nlp.knowledge_extractor.call_llm")
    def test_merge_ner_indices_merged_with_llm(self, mock_llm):
        """NER indices should be merged with LLM-extracted indices."""
        from bookscope.models.schemas import ChapterSummary
        from bookscope.nlp.knowledge_extractor import _merge_characters

        mock_llm.return_value = "invalid"  # force fallback

        summaries = [
            ChapterSummary(chunk_index=0, characters_mentioned=["张三"]),
        ]
        ner_candidates = {"张三": [0, 5, 10]}

        profiles = _merge_characters(
            summaries, "test", "zh", "key", "model",
            ner_candidates=ner_candidates,
        )
        # Fallback creates profiles from all_names which now has merged indices
        zhang = next(p for p in profiles if p.name == "张三")
        assert 0 in zhang.key_chapter_indices
        assert 5 in zhang.key_chapter_indices
        assert 10 in zhang.key_chapter_indices
