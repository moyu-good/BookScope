"""Upload router — POST /api/upload."""

from __future__ import annotations

import logging
import tempfile
import threading
from pathlib import Path

from fastapi import APIRouter, File, Form, UploadFile

from bookscope.api.session_store import SessionData, new_session_id, put_session
from bookscope.ingest import clean
from bookscope.ingest.loader import load_text
from bookscope.ingest.book_chunker import chunk_book
from bookscope.nlp import detect_language
from bookscope.utils.nltk_setup import ensure_nltk_data

logger = logging.getLogger(__name__)
router = APIRouter()

ensure_nltk_data()

# Large book threshold: books above this get vector store built asynchronously
_ASYNC_VECTOR_THRESHOLD = 200  # chunks


def _build_vector_store_async(session: SessionData) -> None:
    """Build vector store in background thread, update session when done."""
    try:
        from bookscope.store.vector_store import SessionVectorStore
        session.vector_store = SessionVectorStore(session.chunks)
        logger.info("Vector store built for %s (%d chunks)", session.session_id, len(session.chunks))
    except Exception:
        logger.warning("Async vector store build failed for %s", session.session_id)


@router.post("/api/upload")
async def upload(
    file: UploadFile = File(...),
    book_type: str = Form("fiction"),
    ui_lang: str = Form("en"),
):
    """Upload a book file. Returns session metadata."""
    raw = await file.read()
    filename = file.filename or "Untitled.txt"
    suffix = Path(filename).suffix.lower()

    # Detect format by magic bytes (filename may be garbled on Windows with CJK chars)
    is_zip = raw[:4] == b"PK\x03\x04"  # EPUB is a ZIP container
    is_pdf = raw[:5] == b"%PDF-"

    if suffix in (".epub", ".pdf") or is_zip or is_pdf:
        # Determine correct suffix for temp file
        if is_pdf:
            suffix = ".pdf"
        elif is_zip and suffix != ".epub":
            suffix = ".epub"
        # Binary formats: write to temp file and use load_text() for proper parsing
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(raw)
            tmp_path = Path(tmp.name)
        try:
            # Let load_text extract title from file metadata (epub/pdf)
            # Only use filename as fallback
            book = load_text(tmp_path)
            book.raw_text = clean(book.raw_text)
            # If metadata title is missing/generic, fall back to filename
            if not book.title or book.title == tmp_path.stem:
                book.title = filename.rsplit(".", 1)[0]
        finally:
            tmp_path.unlink(missing_ok=True)
    else:
        # Plain text: decode with fallbacks
        for enc in ("utf-8", "latin-1", "cp1252"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = raw.decode("utf-8", errors="replace")
        from bookscope.models.schemas import BookText
        book = BookText(title=filename.rsplit(".", 1)[0], raw_text=clean(text))

    title = book.title
    lang = detect_language(book.raw_text[:2000])
    book.language = lang

    chunks = chunk_book(book)
    total_words = sum(c.word_count for c in chunks)

    # Build vector store: sync for small books, async for large ones
    vector_store = None
    if len(chunks) <= _ASYNC_VECTOR_THRESHOLD:
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

    # Large books: build vector store in background
    if len(chunks) > _ASYNC_VECTOR_THRESHOLD and vector_store is None:
        thread = threading.Thread(
            target=_build_vector_store_async,
            args=(session,),
            daemon=True,
        )
        thread.start()

    return {
        "session_id": session_id,
        "title": title,
        "language": lang,
        "total_chunks": len(chunks),
        "total_words": total_words,
    }
