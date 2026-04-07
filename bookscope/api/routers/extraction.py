"""Extraction router — POST /api/extract/{session_id}.

Unified endpoint replacing v4's separate /analyze and /extract.
Runs KG extraction and emotion/style analysis in parallel via SSE.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from bookscope.api.dependencies import get_api_key, require_session
from bookscope.api.sse_utils import sse
from bookscope.services.extraction_pipeline import run_extraction

router = APIRouter()


class ExtractRequest(BaseModel):
    model: str = "claude-haiku-4-5"


@router.post("/api/extract/{session_id}")
async def extract(session_id: str, req: ExtractRequest = ExtractRequest()):
    """Run parallel KG + emotion/style extraction. Returns SSE stream."""
    session = require_session(session_id)
    session.extraction_status = "running"
    api_key = get_api_key()

    def event_stream():
        for event in run_extraction(session, api_key=api_key, model=req.model):
            yield sse(event)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
