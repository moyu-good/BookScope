"""Search router — POST /api/search."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from bookscope.api.dependencies import require_session

router = APIRouter()


class SearchRequest(BaseModel):
    session_id: str
    query: str
    max_results: int = 20


@router.post("/api/search")
async def search(req: SearchRequest):
    """Full-text keyword search across all chunks."""
    session = require_session(req.session_id)
    query_lower = req.query.lower()
    results = []

    for chunk in session.chunks:
        text_lower = chunk.text.lower()
        if query_lower not in text_lower:
            continue

        # Find all match positions
        positions = []
        start = 0
        while True:
            idx = text_lower.find(query_lower, start)
            if idx == -1:
                break
            positions.append([idx, idx + len(req.query)])
            start = idx + 1

        # Build preview around first match
        first_pos = positions[0][0] if positions else 0
        preview_start = max(0, first_pos - 60)
        preview_end = min(len(chunk.text), first_pos + 120)
        preview = chunk.text[preview_start:preview_end]
        if preview_start > 0:
            preview = "..." + preview
        if preview_end < len(chunk.text):
            preview += "..."

        results.append({
            "chunk_index": chunk.index,
            "text_preview": preview,
            "highlight_positions": positions,
            "match_count": len(positions),
        })

        if len(results) >= req.max_results:
            break

    return {"total_matches": len(results), "results": results}
