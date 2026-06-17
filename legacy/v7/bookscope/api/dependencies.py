"""Shared FastAPI dependencies."""

from __future__ import annotations

import os

from fastapi import HTTPException

from bookscope.api.session_store import SessionData, get_session


def require_session(session_id: str) -> SessionData:
    """Get session or raise 404."""
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


def require_analysis(session: SessionData) -> None:
    """Raise 409 if analysis has not been run."""
    if not session.has_analysis:
        raise HTTPException(status_code=409, detail="Analysis not yet available")


def require_knowledge_graph(session: SessionData) -> None:
    """Raise 409 if KG has not been extracted."""
    if not session.has_knowledge_graph:
        raise HTTPException(
            status_code=409, detail="Knowledge graph not yet extracted"
        )


def get_api_key() -> str | None:
    """Resolve LLM API key from BYOK settings, then environment."""
    from bookscope.config import get_llm_settings

    settings = get_llm_settings()
    return settings.resolved_api_key()


def require_api_key() -> str:
    """Get API key or raise 422."""
    key = get_api_key()
    if not key:
        raise HTTPException(
            status_code=422,
            detail="未配置 API 密钥 — 请在「设置」页面配置你的 LLM 供应商和密钥",
        )
    return key
