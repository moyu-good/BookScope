"""BookScope v5 — Unified FastAPI backend.

Progressive disclosure architecture:
  Upload → Extract (KG + analysis parallel) → Book Overview → Character Deep Dive → Chat

Run:
    uvicorn bookscope.api.app:app --reload --port 8000
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from bookscope import __version__
from bookscope.api.routers import (
    book,
    character,
    charts,
    chat,
    export,
    extraction,
    library,
    search,
    session,
    settings,
    share,
    upload,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Restore persisted sessions on startup."""
    from bookscope.api.session_store import load_all_sessions

    count = load_all_sessions()
    if count:
        logger.info("Restored %d persisted session(s)", count)
    yield


app = FastAPI(title="BookScope API", version=__version__, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(upload.router)
app.include_router(session.router)
app.include_router(extraction.router)
app.include_router(book.router)
app.include_router(character.router)
app.include_router(chat.router)
app.include_router(search.router)
app.include_router(charts.router)
app.include_router(library.router)
app.include_router(export.router)
app.include_router(share.router)
app.include_router(settings.router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": __version__}
