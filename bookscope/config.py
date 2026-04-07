"""BookScope — Centralized BYOK (Bring Your Own Key) configuration.

Users configure their own LLM provider, API key, model, and base URL.
Settings are stored in-memory (server lifetime) and can be updated via
the /api/settings REST endpoint.

Fallback chain: settings store → environment variables → disabled.
"""

from __future__ import annotations

import os
import threading
from dataclasses import asdict, dataclass, field


@dataclass
class LLMSettings:
    """LLM provider configuration.

    provider:
        "anthropic"          — Anthropic Messages API (default)
        "openai_compatible"  — Any OpenAI-compatible endpoint
                               (DeepSeek, OpenRouter, Groq, Ollama, etc.)
    """

    provider: str = "anthropic"
    api_key: str = ""
    base_url: str = ""  # only used for openai_compatible
    model: str = ""  # empty = use provider default

    def resolved_model(self) -> str:
        """Return model with sensible default per provider."""
        if self.model:
            return self.model
        if self.provider == "openai_compatible":
            return "deepseek-chat"
        return "claude-haiku-4-5"

    def resolved_api_key(self) -> str | None:
        """Return API key from settings, then env vars, then None."""
        if self.api_key:
            return self.api_key
        # Fallback to env vars
        if self.provider == "anthropic":
            return os.environ.get("ANTHROPIC_API_KEY")
        return os.environ.get("OPENAI_API_KEY") or os.environ.get("LLM_API_KEY")

    def is_configured(self) -> bool:
        """True if an API key is available (from settings or env)."""
        return bool(self.resolved_api_key())

    def to_dict(self) -> dict:
        """Serialize to dict (masks api_key for safety)."""
        d = asdict(self)
        if d["api_key"]:
            key = d["api_key"]
            d["api_key_preview"] = key[:8] + "..." + key[-4:] if len(key) > 12 else "***"
        else:
            d["api_key_preview"] = ""
        d.pop("api_key")
        d["is_configured"] = self.is_configured()
        d["resolved_model"] = self.resolved_model()
        return d


# ---------------------------------------------------------------------------
#  Global singleton — thread-safe
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_settings = LLMSettings()


def get_llm_settings() -> LLMSettings:
    """Read current LLM settings (thread-safe snapshot)."""
    with _lock:
        return LLMSettings(
            provider=_settings.provider,
            api_key=_settings.api_key,
            base_url=_settings.base_url,
            model=_settings.model,
        )


def update_llm_settings(
    provider: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> LLMSettings:
    """Update LLM settings. Only provided fields are changed."""
    with _lock:
        if provider is not None:
            _settings.provider = provider
        if api_key is not None:
            _settings.api_key = api_key
        if base_url is not None:
            _settings.base_url = base_url
        if model is not None:
            _settings.model = model
        # Return a safe copy
        return LLMSettings(
            provider=_settings.provider,
            api_key=_settings.api_key,
            base_url=_settings.base_url,
            model=_settings.model,
        )
