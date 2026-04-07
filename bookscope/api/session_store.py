"""Typed in-memory session store.

Replaces the untyped dict-based _sessions from v4 main.py.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Literal

from bookscope.models.schemas import (
    BookKnowledgeGraph,
    BookText,
    ChunkResult,
    EmotionScore,
    StyleScore,
)


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

    # Vector store (lazy, set after upload)
    vector_store: object | None = None  # SessionVectorStore; avoid import cycle

    @property
    def has_analysis(self) -> bool:
        return self.emotion_scores is not None

    @property
    def has_knowledge_graph(self) -> bool:
        return self.knowledge_graph is not None


# Global session registry
_sessions: dict[str, SessionData] = {}


def new_session_id() -> str:
    return uuid.uuid4().hex[:12]


def get_session(session_id: str) -> SessionData | None:
    return _sessions.get(session_id)


def put_session(session: SessionData) -> None:
    _sessions[session.session_id] = session


def all_sessions() -> dict[str, SessionData]:
    return _sessions
