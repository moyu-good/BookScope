"""Export router — GET /api/export/{id}/json|markdown."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response

from bookscope.api.dependencies import require_session
from bookscope.store.repository import AnalysisResult

router = APIRouter()


def _build_stored(session) -> AnalysisResult:
    return AnalysisResult.create(
        book_title=session.title,
        emotion_scores=session.emotion_scores or [],
        style_scores=session.style_scores or [],
        arc_pattern=session.arc_pattern or "Unknown",
        chunk_strategy="book_chunker",
        total_chunks=len(session.chunks),
        total_words=session.total_words,
        detected_lang=session.language,
        knowledge_graph=session.knowledge_graph,
    )


@router.get("/api/export/{session_id}/json")
async def export_json(session_id: str):
    session = require_session(session_id)
    stored = _build_stored(session)
    content = stored.model_dump_json(indent=2)
    filename = f"{session.title}_analysis.json"
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/api/export/{session_id}/markdown")
async def export_markdown(session_id: str):
    session = require_session(session_id)
    stored = _build_stored(session)
    content = stored.to_markdown_report()
    filename = f"{session.title}_report.md"
    return Response(
        content=content,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
