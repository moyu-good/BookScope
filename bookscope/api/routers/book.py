"""Book router — GET /api/book/{id}/overview, /characters."""

from __future__ import annotations

from fastapi import APIRouter

from bookscope.api.dependencies import require_session
from bookscope.services.derived_fields import compute_derived_fields

router = APIRouter()


@router.get("/api/book/{session_id}/overview")
async def book_overview(session_id: str):
    """Return progressive book overview — fields appear as they become available."""
    s = require_session(session_id)

    result: dict = {
        "title": s.title,
        "language": s.language,
        "total_chunks": len(s.chunks),
        "total_words": s.total_words,
        "book_type": s.book_type,
        "extraction_status": s.extraction_status,
    }

    # KG fields (available after KG extraction)
    if s.knowledge_graph:
        kg = s.knowledge_graph
        result["overall_summary"] = kg.overall_summary
        result["themes"] = kg.themes
        result["chapter_summaries"] = [
            {
                "chunk_index": ch.chunk_index,
                "title": ch.title,
                "summary": ch.summary,
                "key_events": ch.key_events,
                "characters_mentioned": ch.characters_mentioned,
            }
            for ch in kg.chapter_summaries
        ]
        result["characters_brief"] = [
            {
                "name": c.name,
                "description": c.description,
                "aliases": c.aliases,
                "arc_summary": c.arc_summary,
                "has_soul": bool(c.personality_type),
            }
            for c in kg.characters
        ]

    # Analysis fields (available after emotion/style analysis)
    if s.has_analysis and s.arc_pattern:
        derived = compute_derived_fields(
            emotion_scores=s.emotion_scores,
            style_scores=s.style_scores,
            arc_pattern=s.arc_pattern,
            book_type=s.book_type,
            ui_lang=s.ui_lang,
        )
        result["arc_pattern"] = s.arc_pattern
        result["dominant_emotion"] = derived.dominant_emotion
        result["valence_series"] = derived.valence_series
        result["readability"] = {
            "score": derived.readability_score,
            "label": derived.readability_label,
            "confidence": derived.readability_confidence,
        }
        result["reader_verdict"] = {
            "sentence": derived.reader_verdict.sentence,
            "for_you": derived.reader_verdict.for_you,
            "not_for_you": derived.reader_verdict.not_for_you,
            "confidence": derived.reader_verdict.confidence,
        }
        result["emotion_scores"] = [sc.model_dump() for sc in s.emotion_scores]
        result["style_scores"] = [sc.model_dump() for sc in s.style_scores]

    return result


@router.get("/api/book/{session_id}/characters")
async def book_characters(session_id: str):
    """Return character list from knowledge graph."""
    s = require_session(session_id)
    if not s.knowledge_graph:
        return {"characters": []}

    return {
        "characters": [
            {
                "name": c.name,
                "aliases": c.aliases,
                "description": c.description,
                "voice_style": c.voice_style,
                "motivations": c.motivations,
                "arc_summary": c.arc_summary,
                "key_chapter_indices": c.key_chapter_indices,
                "has_soul": bool(c.personality_type),
                "personality_type": c.personality_type,
            }
            for c in s.knowledge_graph.characters
        ]
    }
