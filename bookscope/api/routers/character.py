"""Character router — per-character operations.

GET  /api/book/{id}/character/{name}       — full character profile
POST /api/book/{id}/character/{name}/enrich — on-demand soul enrichment (SSE)
POST /api/book/{id}/character/{name}/chat   — character persona chat (SSE)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from bookscope.api.dependencies import (
    require_api_key,
    require_knowledge_graph,
    require_session,
)
from bookscope.api.sse_utils import sse

logger = logging.getLogger(__name__)
router = APIRouter()


def _find_character(session, name: str):
    """Find character by name in knowledge graph, or raise 404."""
    require_knowledge_graph(session)
    for c in session.knowledge_graph.characters:
        if c.name == name:
            return c
    raise HTTPException(status_code=404, detail=f"Character '{name}' not found")


@router.get("/api/book/{session_id}/character/{name}")
async def get_character(session_id: str, name: str):
    """Return full character profile."""
    session = require_session(session_id)
    c = _find_character(session, name)
    return {
        "name": c.name,
        "aliases": c.aliases,
        "description": c.description,
        "voice_style": c.voice_style,
        "motivations": c.motivations,
        "arc_summary": c.arc_summary,
        "key_chapter_indices": c.key_chapter_indices,
        "personality_type": c.personality_type,
        "values": c.values,
        "key_quotes": c.key_quotes,
        "emotional_stages": [
            {"stage": es.stage, "emotion": es.emotion, "event": es.event}
            for es in (c.emotional_stages or [])
        ],
        "has_soul": bool(c.personality_type),
    }


class EnrichRequest(BaseModel):
    model: str = "claude-haiku-4-5"


@router.post("/api/book/{session_id}/character/{name}/enrich")
async def enrich_character(session_id: str, name: str, req: EnrichRequest = EnrichRequest()):
    """On-demand soul enrichment for a single character. Returns SSE stream."""
    session = require_session(session_id)
    api_key = require_api_key()
    character = _find_character(session, name)

    def event_stream():
        try:
            from bookscope.nlp.soul_engine import enrich_soul_profile

            yield sse({"type": "progress", "character": name, "status": "enriching"})

            enriched = enrich_soul_profile(
                profile=character,
                chunks=session.chunks,
                chunk_indices=character.key_chapter_indices,
                book_title=session.title,
                language=session.language,
                api_key=api_key,
                model=req.model,
            )

            # Update character in-place in knowledge graph
            for i, c in enumerate(session.knowledge_graph.characters):
                if c.name == name:
                    session.knowledge_graph.characters[i] = enriched
                    break

            yield sse({
                "type": "done",
                "character": {
                    "name": enriched.name,
                    "personality_type": enriched.personality_type,
                    "values": enriched.values,
                    "key_quotes": enriched.key_quotes,
                    "emotional_stages": [
                        {"stage": es.stage, "emotion": es.emotion, "event": es.event}
                        for es in (enriched.emotional_stages or [])
                    ],
                },
            })
        except Exception as e:
            logger.exception("Soul enrichment failed for %s", name)
            yield sse({"type": "error", "message": str(e)})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


class CharacterChatRequest(BaseModel):
    message: str
    ui_lang: str = "en"
    model: str = "claude-haiku-4-5"


@router.post("/api/book/{session_id}/character/{name}/chat")
async def character_chat(session_id: str, name: str, req: CharacterChatRequest):
    """Chat with a character persona. Returns SSE stream."""
    session = require_session(session_id)
    api_key = require_api_key()
    character = _find_character(session, name)

    def event_stream():
        try:
            from bookscope.nlp.soul_engine import (
                build_character_context,
                build_persona_prompt,
            )

            system_prompt = build_persona_prompt(
                character, session.title, session.language,
            )
            context = build_character_context(
                session.chunks,
                character.key_chapter_indices,
                req.message,
            )

            import anthropic

            client = anthropic.Anthropic(api_key=api_key)
            with client.messages.stream(
                model=req.model,
                max_tokens=800,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": f"{context}\n\nUser: {req.message}"}
                ],
            ) as stream:
                for text in stream.text_stream:
                    yield sse({"type": "message", "content": text})

            yield sse({"type": "done"})
        except Exception as e:
            logger.exception("Character chat failed for %s", name)
            yield sse({"type": "error", "message": str(e)})

    return StreamingResponse(event_stream(), media_type="text/event-stream")
