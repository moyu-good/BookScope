"""Settings router — GET/PUT /api/settings.

BYOK configuration: users set their own LLM provider, API key, and model.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from bookscope.config import get_llm_settings, update_llm_settings

router = APIRouter()


class SettingsUpdate(BaseModel):
    provider: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None


@router.get("/api/settings")
async def read_settings():
    """Return current LLM settings (api_key masked)."""
    return get_llm_settings().to_dict()


@router.put("/api/settings")
async def write_settings(body: SettingsUpdate):
    """Update LLM settings. Only provided fields are changed."""
    updated = update_llm_settings(
        provider=body.provider,
        api_key=body.api_key,
        base_url=body.base_url,
        model=body.model,
    )
    return updated.to_dict()


@router.post("/api/settings/test")
async def test_connection(body: SettingsUpdate):
    """Test LLM connection with provided (or current) settings."""
    # Temporarily apply overrides for the test
    settings = get_llm_settings()
    test_key = body.api_key or settings.resolved_api_key()
    test_model = body.model or settings.resolved_model()
    test_provider = body.provider or settings.provider
    test_base_url = body.base_url if body.base_url is not None else settings.base_url

    if not test_key:
        return {"ok": False, "error": "未提供 API 密钥"}

    try:
        from bookscope.nlp.llm_provider import call_llm

        # Temporarily set settings for test
        saved = get_llm_settings()
        update_llm_settings(
            provider=test_provider,
            api_key=test_key,
            base_url=test_base_url,
            model=test_model,
        )
        try:
            result = call_llm("Reply with exactly: OK", max_tokens=10)
            if result:
                return {"ok": True, "reply": result}
            return {"ok": False, "error": "空响应 — 请检查 API 密钥和模型名称"}
        finally:
            # Restore original settings
            update_llm_settings(
                provider=saved.provider,
                api_key=saved.api_key,
                base_url=saved.base_url,
                model=saved.model,
            )
    except Exception as e:
        return {"ok": False, "error": str(e)}
