"""Chat router — POST /api/chat/stream (general RAG chat)."""

from __future__ import annotations

import logging

import anthropic
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from bookscope.api.dependencies import require_api_key, require_session
from bookscope.api.session_store import ensure_vector_store
from bookscope.api.sse_utils import sse
from bookscope.nlp.chat_context import build_chat_context

logger = logging.getLogger(__name__)
router = APIRouter()


class ChatRequest(BaseModel):
    session_id: str
    message: str
    ui_lang: str = "en"
    model: str = "claude-haiku-4-5"


@router.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    """RAG-powered book chat. Returns SSE stream."""
    session = require_session(req.session_id)
    api_key = require_api_key()

    lang_name = {"en": "English", "zh": "Chinese", "ja": "Japanese"}.get(
        req.ui_lang, "English"
    )

    context = build_chat_context(
        book=session.book,
        graph=session.knowledge_graph,
        vector_store=ensure_vector_store(session),
        message=req.message,
    )

    system_prompt = (
        f"You are a knowledgeable book analyst. Answer questions about the book "
        f"using ONLY the provided context. Be specific, cite passages when possible. "
        f"Use {lang_name}."
    )

    def event_stream():
        try:
            client = anthropic.Anthropic(api_key=api_key)
            with client.messages.stream(
                model=req.model,
                max_tokens=800,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": f"{context}\n\nQuestion: {req.message}"}
                ],
            ) as stream:
                for text in stream.text_stream:
                    yield sse({"type": "message", "content": text})

            yield sse({"type": "done"})
        except Exception as e:
            logger.exception("Chat failed")
            yield sse({"type": "error", "message": str(e)})

    return StreamingResponse(event_stream(), media_type="text/event-stream")
