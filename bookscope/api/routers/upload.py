"""Upload router — POST /api/upload."""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, Form, UploadFile

from bookscope.api.session_store import SessionData, new_session_id, put_session
from bookscope.ingest import clean, load_text
from bookscope.ingest.book_chunker import chunk_book
from bookscope.nlp import detect_language
from bookscope.utils.nltk_setup import ensure_nltk_data

logger = logging.getLogger(__name__)
router = APIRouter()

ensure_nltk_data()


@router.post("/api/upload")
async def upload(
    file: UploadFile = File(...),
    book_type: str = Form("fiction"),
    ui_lang: str = Form("en"),
):
    """Upload a book file. Returns session metadata."""
    raw = await file.read()
    # Try UTF-8 first, then fallbacks
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")

    title = (file.filename or "Untitled").rsplit(".", 1)[0]
    from bookscope.models.schemas import BookText

    book = BookText(title=title, raw_text=clean(text))
    lang = detect_language(book.raw_text[:2000])
    book = BookText(title=title, raw_text=book.raw_text, language=lang)

    chunks = chunk_book(book)
    total_words = sum(c.word_count for c in chunks)

    # Build vector store
    vector_store = None
    try:
        from bookscope.store.vector_store import SessionVectorStore
        vector_store = SessionVectorStore(chunks)
    except Exception:
        logger.warning("Vector store init failed, RAG search disabled")

    session_id = new_session_id()
    session = SessionData(
        session_id=session_id,
        title=title,
        book=book,
        chunks=chunks,
        total_words=total_words,
        language=lang,
        book_type=book_type,
        ui_lang=ui_lang,
        vector_store=vector_store,
    )
    put_session(session)

    return {
        "session_id": session_id,
        "title": title,
        "language": lang,
        "total_chunks": len(chunks),
        "total_words": total_words,
    }
