"""Tests for bookscope.nlp.knowledge_extractor."""

import json
from unittest.mock import MagicMock, patch

from bookscope.models.schemas import (
    BookKnowledgeGraph,
    ChapterSummary,
    CharacterProfile,
)
from bookscope.nlp.knowledge_extractor import (
    _extract_chunk_summary,
    _merge_characters,
    _parse_json,
    _strip_fences,
    extract_knowledge_graph,
)

# ---------------------------------------------------------------------------
# _strip_fences
# ---------------------------------------------------------------------------

def test_strip_fences_removes_json_fences():
    raw = '```json\n{"a": 1}\n```'
    assert _strip_fences(raw) == '{"a": 1}'


def test_strip_fences_noop_for_plain_json():
    raw = '{"a": 1}'
    assert _strip_fences(raw) == '{"a": 1}'


def test_strip_fences_handles_empty_string():
    assert _strip_fences("") == ""


# ---------------------------------------------------------------------------
# _parse_json
# ---------------------------------------------------------------------------

def test_parse_json_valid():
    data = _parse_json('{"key": "value"}')
    assert data == {"key": "value"}


def test_parse_json_with_fences():
    data = _parse_json('```json\n{"key": "value"}\n```')
    assert data == {"key": "value"}


def test_parse_json_invalid_returns_none():
    assert _parse_json("not json") is None


def test_parse_json_empty_returns_none():
    assert _parse_json("") is None


def test_parse_json_none_input_returns_none():
    assert _parse_json(None) is None


# ---------------------------------------------------------------------------
# _extract_chunk_summary — mock call_llm
# ---------------------------------------------------------------------------

@patch("bookscope.nlp.knowledge_extractor.call_llm")
def test_extract_chunk_summary_valid_json(mock_llm):
    mock_llm.return_value = json.dumps({
        "title": "第一章",
        "summary": "主角出场",
        "key_events": ["初遇", "相识"],
        "characters_mentioned": ["张三", "李四"],
    })
    result = _extract_chunk_summary(0, "一些文本", "zh", "fake-key", "model")
    assert result.chunk_index == 0
    assert result.title == "第一章"
    assert result.summary == "主角出场"
    assert result.key_events == ["初遇", "相识"]
    assert result.characters_mentioned == ["张三", "李四"]
    assert mock_llm.call_count == 1


@patch("bookscope.nlp.knowledge_extractor.call_llm")
def test_extract_chunk_summary_english(mock_llm):
    mock_llm.return_value = json.dumps({
        "title": "Chapter 1",
        "summary": "The hero appears",
        "key_events": ["Meeting"],
        "characters_mentioned": ["Alice"],
    })
    result = _extract_chunk_summary(0, "some text", "en", "fake-key", "model")
    assert result.title == "Chapter 1"
    assert result.characters_mentioned == ["Alice"]


@patch("bookscope.nlp.knowledge_extractor.call_llm")
def test_extract_chunk_summary_retry_on_first_failure(mock_llm):
    mock_llm.side_effect = [
        "invalid json{{{",
        json.dumps({
            "title": "",
            "summary": "retry succeeded",
            "key_events": [],
            "characters_mentioned": [],
        }),
    ]
    result = _extract_chunk_summary(0, "text", "zh", "key", "model")
    assert result.summary == "retry succeeded"
    assert mock_llm.call_count == 2


@patch("bookscope.nlp.knowledge_extractor.call_llm")
def test_extract_chunk_summary_fallback_after_two_failures(mock_llm):
    mock_llm.return_value = "not json"
    result = _extract_chunk_summary(0, "text", "zh", "key", "model")
    assert result.chunk_index == 0
    assert result.summary == ""
    assert result.key_events == []
    assert mock_llm.call_count == 2


@patch("bookscope.nlp.knowledge_extractor.call_llm")
def test_extract_chunk_summary_handles_none_response(mock_llm):
    mock_llm.return_value = None
    result = _extract_chunk_summary(0, "text", "zh", "key", "model")
    assert result.summary == ""


@patch("bookscope.nlp.knowledge_extractor.call_llm")
def test_extract_chunk_summary_handles_fenced_json(mock_llm):
    inner = json.dumps({
        "title": "Ch",
        "summary": "ok",
        "key_events": [],
        "characters_mentioned": ["Bob"],
    })
    mock_llm.return_value = f"```json\n{inner}\n```"
    result = _extract_chunk_summary(0, "text", "en", "key", "model")
    assert result.summary == "ok"
    assert result.characters_mentioned == ["Bob"]


# ---------------------------------------------------------------------------
# _merge_characters
# ---------------------------------------------------------------------------

@patch("bookscope.nlp.knowledge_extractor.call_llm")
def test_merge_characters_valid(mock_llm):
    mock_llm.return_value = json.dumps([
        {
            "name": "贾宝玉",
            "aliases": ["宝玉", "宝二爷"],
            "description": "贾府公子",
            "voice_style": "温柔多情",
            "motivations": ["追求自由"],
            "key_chapter_indices": [0, 1, 2],
            "arc_summary": "从天真到觉悟",
        },
    ])
    summaries = [
        ChapterSummary(chunk_index=0, characters_mentioned=["贾宝玉", "宝玉"]),
        ChapterSummary(chunk_index=1, characters_mentioned=["宝二爷"]),
    ]
    profiles = _merge_characters(summaries, "红楼梦", "zh", "key", "model")
    assert len(profiles) == 1
    assert profiles[0].name == "贾宝玉"
    assert "宝玉" in profiles[0].aliases


@patch("bookscope.nlp.knowledge_extractor.call_llm")
def test_merge_characters_empty_names(mock_llm):
    summaries = [ChapterSummary(chunk_index=0, characters_mentioned=[])]
    profiles = _merge_characters(summaries, "test", "zh", "key", "model")
    assert profiles == []
    mock_llm.assert_not_called()


@patch("bookscope.nlp.knowledge_extractor.call_llm")
def test_merge_characters_fallback_on_invalid_json(mock_llm):
    mock_llm.return_value = "not json"
    summaries = [
        ChapterSummary(chunk_index=0, characters_mentioned=["Alice"]),
        ChapterSummary(chunk_index=1, characters_mentioned=["Bob"]),
    ]
    profiles = _merge_characters(summaries, "test", "en", "key", "model")
    assert len(profiles) == 2
    names = {p.name for p in profiles}
    assert "Alice" in names
    assert "Bob" in names


@patch("bookscope.nlp.knowledge_extractor.call_llm")
def test_merge_characters_handles_wrapped_dict(mock_llm):
    """LLM might return {"characters": [...]} instead of bare list."""
    mock_llm.return_value = json.dumps({
        "characters": [
            {"name": "Alice", "aliases": [], "description": "hero",
             "voice_style": "", "motivations": [], "key_chapter_indices": [0],
             "arc_summary": ""},
        ]
    })
    summaries = [ChapterSummary(chunk_index=0, characters_mentioned=["Alice"])]
    profiles = _merge_characters(summaries, "test", "en", "key", "model")
    assert len(profiles) == 1
    assert profiles[0].name == "Alice"


# ---------------------------------------------------------------------------
# extract_knowledge_graph — integration-level with mocked LLM
# ---------------------------------------------------------------------------

@patch("bookscope.nlp.knowledge_extractor.call_llm")
def test_extract_knowledge_graph_no_chunks(mock_llm):
    graph = extract_knowledge_graph([], "test", api_key="key")
    assert graph.book_title == "test"
    assert graph.chapter_summaries == []
    assert graph.characters == []
    mock_llm.assert_not_called()


@patch("bookscope.nlp.knowledge_extractor.call_llm")
def test_extract_knowledge_graph_no_api_key(mock_llm):
    graph = extract_knowledge_graph(
        [MagicMock(text="hello")], "test", api_key=None
    )
    assert graph.chapter_summaries == []
    mock_llm.assert_not_called()


@patch("bookscope.nlp.knowledge_extractor.call_llm")
def test_extract_knowledge_graph_full_flow(mock_llm):
    """Two chunks → 2 summary calls + 1 merge call = 3 LLM calls."""
    chunk_summary_1 = json.dumps({
        "title": "Ch1", "summary": "开场",
        "key_events": ["事件A"], "characters_mentioned": ["张三"],
    })
    chunk_summary_2 = json.dumps({
        "title": "Ch2", "summary": "发展",
        "key_events": ["事件B"], "characters_mentioned": ["张三", "李四"],
    })
    merge_result = json.dumps([
        {"name": "张三", "aliases": [], "description": "主角",
         "voice_style": "", "motivations": ["生存"],
         "key_chapter_indices": [0, 1], "arc_summary": "成长"},
        {"name": "李四", "aliases": [], "description": "配角",
         "voice_style": "", "motivations": [],
         "key_chapter_indices": [1], "arc_summary": ""},
    ])
    mock_llm.side_effect = [chunk_summary_1, chunk_summary_2, merge_result]

    chunks = [MagicMock(text="第一章内容"), MagicMock(text="第二章内容")]
    graph = extract_knowledge_graph(
        chunks, "测试小说", language="zh", api_key="key"
    )

    assert graph.book_title == "测试小说"
    assert len(graph.chapter_summaries) == 2
    assert graph.chapter_summaries[0].title == "Ch1"
    assert graph.chapter_summaries[1].summary == "发展"
    assert len(graph.characters) == 2
    assert graph.characters[0].name == "张三"
    assert mock_llm.call_count == 3


@patch("bookscope.nlp.knowledge_extractor.call_llm")
def test_extract_knowledge_graph_progress_callback(mock_llm):
    mock_llm.return_value = json.dumps({
        "title": "", "summary": "s",
        "key_events": [], "characters_mentioned": [],
    })
    progress_log = []
    chunks = [MagicMock(text="a"), MagicMock(text="b"), MagicMock(text="c")]
    extract_knowledge_graph(
        chunks, "test", api_key="key",
        progress_callback=lambda cur, tot: progress_log.append((cur, tot)),
    )
    assert progress_log == [(1, 3), (2, 3), (3, 3)]


@patch("bookscope.nlp.knowledge_extractor.call_llm")
def test_extract_knowledge_graph_chunk_text_attribute(mock_llm):
    """Handles chunks with .text attribute (ChunkResult) or plain strings."""
    mock_llm.return_value = json.dumps({
        "title": "", "summary": "ok",
        "key_events": [], "characters_mentioned": [],
    })
    # Chunk without .text attribute — should use str(chunk)
    graph = extract_knowledge_graph(
        ["raw string chunk"], "test", api_key="key"
    )
    assert len(graph.chapter_summaries) == 1
    assert graph.chapter_summaries[0].summary == "ok"


# ---------------------------------------------------------------------------
# Schema model tests
# ---------------------------------------------------------------------------

def test_chapter_summary_defaults():
    s = ChapterSummary(chunk_index=0)
    assert s.title == ""
    assert s.summary == ""
    assert s.key_events == []
    assert s.characters_mentioned == []


def test_character_profile_defaults():
    p = CharacterProfile(name="test")
    assert p.aliases == []
    assert p.voice_style == ""
    assert p.motivations == []
    assert p.key_chapter_indices == []
    assert p.arc_summary == ""


def test_book_knowledge_graph_defaults():
    g = BookKnowledgeGraph(book_title="test")
    assert g.language == "zh"
    assert g.chapter_summaries == []
    assert g.characters == []
    assert g.overall_summary == ""
    assert g.themes == []


def test_book_knowledge_graph_serialization():
    g = BookKnowledgeGraph(
        book_title="红楼梦",
        language="zh",
        chapter_summaries=[ChapterSummary(chunk_index=0, summary="开篇")],
        characters=[CharacterProfile(name="宝玉", aliases=["贾宝玉"])],
        overall_summary="四大名著之一",
        themes=["爱情", "家族"],
    )
    data = json.loads(g.model_dump_json())
    assert data["book_title"] == "红楼梦"
    assert len(data["chapter_summaries"]) == 1
    assert len(data["characters"]) == 1
    assert data["themes"] == ["爱情", "家族"]

    # Round-trip
    g2 = BookKnowledgeGraph.model_validate(data)
    assert g2.book_title == g.book_title
    assert g2.characters[0].aliases == ["贾宝玉"]
