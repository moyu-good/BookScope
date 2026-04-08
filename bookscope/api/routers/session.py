"""Session router — list, get, status."""

from __future__ import annotations

from fastapi import APIRouter

from bookscope.api.dependencies import require_session
from bookscope.api.session_store import all_sessions

router = APIRouter()


@router.get("/api/sessions")
async def list_sessions():
    """Return all active (in-memory) sessions for the 'recent' list."""
    items = []
    for s in all_sessions().values():
        items.append(
            {
                "session_id": s.session_id,
                "title": s.title,
                "language": s.language,
                "total_words": s.total_words,
                "total_chunks": len(s.chunks),
                "extraction_status": s.extraction_status,
                "has_knowledge_graph": s.has_knowledge_graph,
                "has_analysis": s.has_analysis,
                "book_type": s.book_type,
            }
        )
    return {"sessions": items}


@router.get("/api/session/{session_id}")
async def get_session(session_id: str):
    """Return session metadata."""
    s = require_session(session_id)
    return {
        "session_id": s.session_id,
        "title": s.title,
        "language": s.language,
        "total_chunks": len(s.chunks),
        "total_words": s.total_words,
        "has_analysis": s.has_analysis,
        "has_knowledge_graph": s.has_knowledge_graph,
    }


@router.get("/api/session/{session_id}/status")
async def get_session_status(session_id: str):
    """Return extraction status for frontend polling."""
    s = require_session(session_id)

    # Which characters have soul enrichment
    soul_status = {}
    if s.knowledge_graph:
        for c in s.knowledge_graph.characters:
            soul_status[c.name] = bool(c.personality_type)

    return {
        "extraction_status": s.extraction_status,
        "has_knowledge_graph": s.has_knowledge_graph,
        "has_analysis": s.has_analysis,
        "has_soul_enrichment": soul_status,
    }
