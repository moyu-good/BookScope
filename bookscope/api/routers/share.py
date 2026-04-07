"""Share router — /api/share/*."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from bookscope.api.dependencies import require_session
from bookscope.store.repository import AnalysisResult, Repository

router = APIRouter()
_repo = Repository()
_share_tokens: dict[str, str] = {}  # token → filename


class ShareCreateRequest(BaseModel):
    session_id: str


@router.post("/api/share/create")
async def share_create(req: ShareCreateRequest):
    session = require_session(req.session_id)
    if not session.has_analysis:
        raise HTTPException(status_code=409, detail="Analysis not yet available")

    stored = AnalysisResult.create(
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
    path = _repo.save(stored)
    token = uuid.uuid4().hex[:8]
    _share_tokens[token] = path.name
    return {"token": token, "url": f"/share/{token}"}


@router.get("/api/share/{token}")
async def share_get(token: str):
    filename = _share_tokens.get(token)
    if not filename:
        raise HTTPException(status_code=404, detail="Share token not found or expired")
    for p in _repo.list_results():
        if p.name == filename:
            r = _repo.load(p)
            return {"analysis": r.model_dump()}
    raise HTTPException(status_code=404, detail="Shared analysis not found")
