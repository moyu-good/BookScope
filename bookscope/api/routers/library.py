"""Library router — CRUD /api/library/*."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from bookscope.api.dependencies import require_session
from bookscope.services.derived_fields import compute_derived_fields
from bookscope.store.repository import AnalysisResult, Repository

logger = logging.getLogger(__name__)
router = APIRouter()
_repo = Repository()


class LibrarySaveRequest(BaseModel):
    session_id: str
    tags: list[str] = []


@router.post("/api/library/save")
async def library_save(req: LibrarySaveRequest):
    session = require_session(req.session_id)
    if not session.has_analysis:
        raise HTTPException(status_code=409, detail="Analysis not yet available")

    stored = AnalysisResult.create(
        book_title=session.title,
        emotion_scores=session.emotion_scores,
        style_scores=session.style_scores,
        arc_pattern=session.arc_pattern or "Unknown",
        chunk_strategy="book_chunker",
        total_chunks=len(session.chunks),
        total_words=session.total_words,
        detected_lang=session.language,
        knowledge_graph=session.knowledge_graph,
    )
    path = _repo.save(stored)
    if req.tags:
        _repo.save_notes(path, {"tags": req.tags})

    return {"saved": True, "filename": path.name, "path": str(path)}


@router.get("/api/library")
async def library_list():
    items = []
    for p in _repo.list_results():
        try:
            r = _repo.load(p)
            notes = _repo.load_notes(p)
            items.append({
                "filename": p.name,
                "title": r.book_title,
                "arc_pattern": r.arc_pattern,
                "total_chunks": r.total_chunks,
                "total_words": r.total_words,
                "language": r.detected_lang,
                "analyzed_at": r.analyzed_at,
                "tags": notes.get("tags", []),
            })
        except Exception:
            logger.warning("Failed to load %s", p.name)
    return {"items": items, "total": len(items)}


@router.get("/api/library/{filename}")
async def library_get(filename: str):
    for p in _repo.list_results():
        if p.name == filename:
            r = _repo.load(p)
            notes = _repo.load_notes(p)
            return {"filename": filename, "analysis": r.model_dump(), "notes": notes}
    raise HTTPException(status_code=404, detail="Not found")


@router.delete("/api/library/{filename}")
async def library_delete(filename: str):
    for p in _repo.list_results():
        if p.name == filename:
            _repo.delete(p)
            return {"deleted": True}
    raise HTTPException(status_code=404, detail="Not found")


@router.get("/api/library/{filename}/analysis")
async def library_analysis(filename: str):
    """Return library item in same shape as /api/book/{id}/overview."""
    for p in _repo.list_results():
        if p.name == filename:
            r = _repo.load(p)
            derived = compute_derived_fields(
                emotion_scores=r.emotion_scores,
                style_scores=r.style_scores,
                arc_pattern=r.arc_pattern,
                book_type="fiction",
                ui_lang="en",
            )
            result = {
                "title": r.book_title,
                "language": r.detected_lang,
                "total_chunks": r.total_chunks,
                "total_words": r.total_words,
                "arc_pattern": r.arc_pattern,
                "dominant_emotion": derived.dominant_emotion,
                "valence_series": derived.valence_series,
                "readability": {
                    "score": derived.readability_score,
                    "label": derived.readability_label,
                    "confidence": derived.readability_confidence,
                },
                "reader_verdict": {
                    "sentence": derived.reader_verdict.sentence,
                    "for_you": derived.reader_verdict.for_you,
                    "not_for_you": derived.reader_verdict.not_for_you,
                    "confidence": derived.reader_verdict.confidence,
                },
                "emotion_scores": [s.model_dump() for s in r.emotion_scores],
                "style_scores": [s.model_dump() for s in r.style_scores],
                "extraction_status": "done",
            }
            if r.knowledge_graph:
                kg = r.knowledge_graph
                result["overall_summary"] = kg.overall_summary
                result["themes"] = kg.themes
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
            return result
    raise HTTPException(status_code=404, detail="Not found")
