"""BookScope — Character relation extractor.

Extracts character relationships from fiction book excerpts using the LLM.
Only runs for lang="en" in v1.0; other languages return an empty RelationGraph.

Usage:
    from bookscope.nlp.relation_extractor import extract_character_relations
    graph = extract_character_relations(chunks, lang="en", api_key=key, model=model)
"""

import hashlib
import json
import logging

import streamlit as st
from pydantic import BaseModel

from bookscope.nlp.llm_analyzer import call_llm

logger = logging.getLogger(__name__)

_MAX_CHUNKS = 5        # "front N chapters" definition
_CHARS_PER_CHUNK = 600 # character budget per chunk excerpt


class CharacterRelation(BaseModel):
    source: str   # Character A name
    target: str   # Character B name
    relation: str # Relationship label (<=10 chars, e.g. "rivals", "lovers")


class RelationGraph(BaseModel):
    characters: list[str]
    relations: list[CharacterRelation]


def extract_character_relations(
    chunks: list,
    lang: str,
    api_key: str | None = None,
    model: str = "claude-haiku-4-5",
) -> RelationGraph:
    """Extract character relations from the first N chunks of a fiction book.

    Args:
        chunks:  list[ChunkResult] from the analysis pipeline.
        lang:    detected book language code ("en" / "zh" / "ja").
        api_key: Anthropic API key.
        model:   Claude model ID to use.

    Returns:
        RelationGraph with characters and relations lists.
        Returns empty graph if lang != "en", no chunks, or LLM call fails.
    """
    if lang != "en" or not chunks or not api_key:
        return RelationGraph(characters=[], relations=[])

    # Cache per book content (first N chunks)
    sample = chunks[: _MAX_CHUNKS]
    combined = "".join(getattr(c, "text", str(c))[:40] for c in sample)
    cache_key = "rel_graph_" + hashlib.md5(combined.encode()).hexdigest()[:8]

    cached = st.session_state.get(cache_key)
    if cached is not None:
        return cached

    text = "\n\n".join(
        getattr(c, "text", str(c))[:_CHARS_PER_CHUNK] for c in sample
    )

    prompt = (
        "You are extracting character relationships from book excerpts.\n"
        "Given these excerpts from a fiction book, identify the 3-6 most "
        "important characters and their relationships.\n"
        "Return ONLY valid JSON matching this schema — no markdown, no explanation:\n"
        '{"characters": ["Name1", "Name2", ...], '
        '"relations": [{"source": "A", "target": "B", "relation": "label"}, ...]}\n'
        "Each relation label must be <=10 characters (e.g. rivals, lovers, mentor, allies).\n"
        "Include only relations clearly supported by the text.\n\n"
        f"Excerpts (first {len(sample)} chapter(s)):\n{text}"
    )

    raw = call_llm(prompt, api_key=api_key, model=model, max_tokens=400) or ""
    graph = _parse_relation_graph(raw)
    st.session_state[cache_key] = graph
    return graph


def _parse_relation_graph(raw: str) -> RelationGraph:
    """Parse LLM JSON output into a RelationGraph, returning empty on failure."""
    if not raw:
        return RelationGraph(characters=[], relations=[])

    # Strip markdown code fences if present
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(
            line for line in lines if not line.startswith("```")
        ).strip()

    try:
        data = json.loads(text)
        characters = [str(c) for c in data.get("characters", []) if c]
        relations = []
        for r in data.get("relations", []):
            src = str(r.get("source", "")).strip()
            tgt = str(r.get("target", "")).strip()
            rel = str(r.get("relation", "")).strip()[:10]
            if src and tgt and rel:
                relations.append(CharacterRelation(source=src, target=tgt, relation=rel))
        return RelationGraph(characters=characters, relations=relations)
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.debug("relation_extractor: failed to parse LLM output: %s", exc)
        return RelationGraph(characters=[], relations=[])
