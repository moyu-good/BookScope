"""Typed session store with JSON file persistence.

Sessions live in-memory for fast access and are persisted to
``data/sessions/{session_id}.json`` so they survive server restarts.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from bookscope.models.schemas import (
    BookKnowledgeGraph,
    BookText,
    ChunkResult,
    EmotionScore,
    StyleScore,
)

logger = logging.getLogger(__name__)

_SESSIONS_DIR = Path("data") / "sessions"


@dataclass
class SessionData:
    """Typed container for a single upload session."""

    session_id: str
    title: str
    book: BookText
    chunks: list[ChunkResult]
    total_words: int
    language: str
    book_type: str = "fiction"
    ui_lang: str = "en"

    # Extraction state (progressive)
    extraction_status: Literal["idle", "running", "done", "error"] = "idle"
    extraction_error: str | None = None

    # Analysis results (populated progressively)
    knowledge_graph: BookKnowledgeGraph | None = None
    emotion_scores: list[EmotionScore] | None = None
    style_scores: list[StyleScore] | None = None
    arc_pattern: str | None = None
    valence_series: list[float] | None = None

    # Vector store (lazy, set after upload — NOT persisted)
    vector_store: object | None = None  # SessionVectorStore; avoid import cycle

    @property
    def has_analysis(self) -> bool:
        return self.emotion_scores is not None

    @property
    def has_knowledge_graph(self) -> bool:
        return self.knowledge_graph is not None


# ── In-memory registry ──────────────────────────────────────────────────────

_sessions: dict[str, SessionData] = {}


def new_session_id() -> str:
    return uuid.uuid4().hex[:12]


def get_session(session_id: str) -> SessionData | None:
    return _sessions.get(session_id)


def put_session(session: SessionData) -> None:
    """Store session in memory and persist to disk."""
    _sessions[session.session_id] = session
    persist_session(session)


def all_sessions() -> dict[str, SessionData]:
    return _sessions


# ── JSON persistence ────────────────────────────────────────────────────────


def _serialize_session(session: SessionData) -> dict:
    """Convert SessionData to a JSON-serializable dict."""
    return {
        "session_id": session.session_id,
        "title": session.title,
        "book": session.book.model_dump(),
        "chunks": [c.model_dump() for c in session.chunks],
        "total_words": session.total_words,
        "language": session.language,
        "book_type": session.book_type,
        "ui_lang": session.ui_lang,
        "extraction_status": session.extraction_status,
        "extraction_error": session.extraction_error,
        "knowledge_graph": (
            session.knowledge_graph.model_dump() if session.knowledge_graph else None
        ),
        "emotion_scores": (
            [s.model_dump() for s in session.emotion_scores]
            if session.emotion_scores
            else None
        ),
        "style_scores": (
            [s.model_dump() for s in session.style_scores]
            if session.style_scores
            else None
        ),
        "arc_pattern": session.arc_pattern,
        "valence_series": session.valence_series,
    }


def _deserialize_session(data: dict) -> SessionData:
    """Rebuild SessionData from a persisted dict."""
    return SessionData(
        session_id=data["session_id"],
        title=data["title"],
        book=BookText.model_validate(data["book"]),
        chunks=[ChunkResult.model_validate(c) for c in data["chunks"]],
        total_words=data["total_words"],
        language=data["language"],
        book_type=data.get("book_type", "fiction"),
        ui_lang=data.get("ui_lang", "en"),
        extraction_status=data.get("extraction_status", "idle"),
        extraction_error=data.get("extraction_error"),
        knowledge_graph=(
            BookKnowledgeGraph.model_validate(data["knowledge_graph"])
            if data.get("knowledge_graph")
            else None
        ),
        emotion_scores=(
            [EmotionScore.model_validate(s) for s in data["emotion_scores"]]
            if data.get("emotion_scores")
            else None
        ),
        style_scores=(
            [StyleScore.model_validate(s) for s in data["style_scores"]]
            if data.get("style_scores")
            else None
        ),
        arc_pattern=data.get("arc_pattern"),
        valence_series=data.get("valence_series"),
        # vector_store is rebuilt lazily — not persisted
    )


def persist_session(session: SessionData) -> Path:
    """Save a single session to disk as JSON."""
    _SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    path = _SESSIONS_DIR / f"{session.session_id}.json"
    payload = json.dumps(
        _serialize_session(session), ensure_ascii=False, indent=2,
    )
    path.write_text(payload, encoding="utf-8")
    return path


def load_all_sessions() -> int:
    """Load all persisted sessions into memory. Returns count loaded."""
    if not _SESSIONS_DIR.exists():
        return 0
    count = 0
    for path in _SESSIONS_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            session = _deserialize_session(data)
            _sessions[session.session_id] = session
            count += 1
        except Exception:
            logger.warning("Failed to load session from %s", path, exc_info=True)
    return count


def delete_session_file(session_id: str) -> None:
    """Remove a persisted session file from disk."""
    path = _SESSIONS_DIR / f"{session_id}.json"
    path.unlink(missing_ok=True)


def ensure_vector_store(session: SessionData) -> object | None:
    """Lazily rebuild the vector store for a restored session."""
    if session.vector_store is not None:
        return session.vector_store
    try:
        from bookscope.store.vector_store import SessionVectorStore
        session.vector_store = SessionVectorStore(session.chunks)
    except Exception:
        logger.warning("Vector store rebuild failed for session %s", session.session_id)
    return session.vector_store
