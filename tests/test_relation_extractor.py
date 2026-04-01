"""Tests for bookscope.nlp.relation_extractor."""

import json
from unittest.mock import MagicMock, patch

from bookscope.nlp.relation_extractor import (
    _parse_relation_graph,
    extract_character_relations,
)

# ---------------------------------------------------------------------------
# _parse_relation_graph
# ---------------------------------------------------------------------------

def test_parse_valid_json():
    raw = json.dumps({
        "characters": ["Alice", "Bob", "Carol"],
        "relations": [
            {"source": "Alice", "target": "Bob", "relation": "rivals"},
            {"source": "Alice", "target": "Carol", "relation": "allies"},
        ],
    })
    graph = _parse_relation_graph(raw)
    assert graph.characters == ["Alice", "Bob", "Carol"]
    assert len(graph.relations) == 2
    assert graph.relations[0].source == "Alice"
    assert graph.relations[0].relation == "rivals"


def test_parse_strips_markdown_fences():
    rel = '{"source":"X","target":"Y","relation":"friends"}'
    inner = f'{{"characters":["X","Y"],"relations":[{rel}]}}'
    raw = f"```json\n{inner}\n```"
    graph = _parse_relation_graph(raw)
    assert graph.characters == ["X", "Y"]
    assert graph.relations[0].relation == "friends"


def test_parse_truncates_relation_label_to_10_chars():
    raw = json.dumps({
        "characters": ["A", "B"],
        "relations": [{"source": "A", "target": "B", "relation": "verylonglabelhere"}],
    })
    graph = _parse_relation_graph(raw)
    assert len(graph.relations[0].relation) <= 10


def test_parse_empty_string_returns_empty_graph():
    graph = _parse_relation_graph("")
    assert graph.characters == []
    assert graph.relations == []


def test_parse_invalid_json_returns_empty_graph():
    graph = _parse_relation_graph("not json at all {")
    assert graph.characters == []
    assert graph.relations == []


def test_parse_missing_keys_returns_empty_graph():
    graph = _parse_relation_graph("{}")
    assert graph.characters == []
    assert graph.relations == []


def test_parse_skips_relations_with_empty_fields():
    raw = json.dumps({
        "characters": ["A", "B", "C"],
        "relations": [
            {"source": "", "target": "B", "relation": "allies"},   # empty source
            {"source": "A", "target": "", "relation": "rivals"},   # empty target
            {"source": "A", "target": "C", "relation": ""},        # empty relation
            {"source": "A", "target": "B", "relation": "lovers"},  # valid
        ],
    })
    graph = _parse_relation_graph(raw)
    assert len(graph.relations) == 1
    assert graph.relations[0].relation == "lovers"


# ---------------------------------------------------------------------------
# extract_character_relations — language guard
# ---------------------------------------------------------------------------

def test_returns_empty_for_non_english_lang():
    chunks = [MagicMock(text="Some text here")]
    for lang in ("zh", "ja", "ko", "fr"):
        graph = extract_character_relations(chunks, lang=lang, api_key="key")
        assert graph.characters == []
        assert graph.relations == []


def test_returns_empty_when_no_chunks():
    graph = extract_character_relations([], lang="en", api_key="key")
    assert graph.characters == []
    assert graph.relations == []


def test_returns_empty_when_no_api_key():
    chunks = [MagicMock(text="Some text here")]
    graph = extract_character_relations(chunks, lang="en", api_key=None)
    assert graph.characters == []
    assert graph.relations == []


# ---------------------------------------------------------------------------
# extract_character_relations — LLM call + caching
# ---------------------------------------------------------------------------

def _make_chunks(n: int = 3):
    chunks = []
    for i in range(n):
        c = MagicMock()
        c.text = f"Chapter {i} text with character mentions."
        chunks.append(c)
    return chunks


@patch("bookscope.nlp.relation_extractor.call_llm")
@patch("bookscope.nlp.relation_extractor.st")
def test_calls_llm_and_parses_result(mock_st, mock_call_llm):
    mock_st.session_state = {}
    llm_response = json.dumps({
        "characters": ["Elizabeth", "Darcy", "Bingley"],
        "relations": [
            {"source": "Elizabeth", "target": "Darcy", "relation": "rivals"},
            {"source": "Darcy", "target": "Bingley", "relation": "friends"},
        ],
    })
    mock_call_llm.return_value = llm_response

    graph = extract_character_relations(_make_chunks(), lang="en", api_key="test-key")

    assert "Elizabeth" in graph.characters
    assert "Darcy" in graph.characters
    assert len(graph.relations) == 2
    mock_call_llm.assert_called_once()


@patch("bookscope.nlp.relation_extractor.call_llm")
@patch("bookscope.nlp.relation_extractor.st")
def test_caches_result_in_session_state(mock_st, mock_call_llm):
    mock_st.session_state = {}
    mock_call_llm.return_value = json.dumps({
        "characters": ["A", "B"],
        "relations": [{"source": "A", "target": "B", "relation": "rivals"}],
    })

    chunks = _make_chunks()
    # First call
    graph1 = extract_character_relations(chunks, lang="en", api_key="test-key")
    # Second call — should hit cache, not call LLM again
    graph2 = extract_character_relations(chunks, lang="en", api_key="test-key")

    assert mock_call_llm.call_count == 1
    assert graph1.characters == graph2.characters


@patch("bookscope.nlp.relation_extractor.call_llm")
@patch("bookscope.nlp.relation_extractor.st")
def test_returns_empty_graph_when_llm_fails(mock_st, mock_call_llm):
    mock_st.session_state = {}
    mock_call_llm.return_value = ""

    graph = extract_character_relations(_make_chunks(), lang="en", api_key="test-key")
    assert graph.characters == []
    assert graph.relations == []


@patch("bookscope.nlp.relation_extractor.call_llm")
@patch("bookscope.nlp.relation_extractor.st")
def test_only_first_max_chunks_sent_to_llm(mock_st, mock_call_llm):
    """When more than _MAX_CHUNKS chunks are provided, only the first 5 are used."""
    mock_st.session_state = {}
    mock_call_llm.return_value = json.dumps({
        "characters": ["A", "B"],
        "relations": [{"source": "A", "target": "B", "relation": "rivals"}],
    })

    chunks = _make_chunks(10)  # 10 chunks, but only 5 should be sent
    extract_character_relations(chunks, lang="en", api_key="test-key")

    # The prompt passed to call_llm should only contain text from the first 5 chunks
    prompt_arg = mock_call_llm.call_args[0][0]
    assert "Chapter 5" not in prompt_arg  # chunk index 5 (6th) must not appear
    assert "Chapter 4" in prompt_arg       # chunk index 4 (5th) must appear
