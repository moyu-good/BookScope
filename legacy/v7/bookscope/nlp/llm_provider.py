"""BookScope — Multi-provider LLM call abstraction.

Supports:
  - Anthropic Messages API (Claude)
  - OpenAI-compatible Chat Completions (DeepSeek, OpenRouter, Groq, Ollama, etc.)

All calls are thread-safe (per-call client construction).
"""

from __future__ import annotations

import logging

from bookscope.config import get_llm_settings

logger = logging.getLogger(__name__)


def call_llm(
    prompt: str,
    *,
    api_key: str | None = None,
    model: str | None = None,
    max_tokens: int = 500,
    system: str | None = None,
) -> str:
    """Unified LLM call supporting multiple providers.

    Resolution order for api_key / model:
      1. Explicit arguments (passed by caller)
      2. Global LLMSettings (configured via /api/settings)
      3. Environment variables
      4. Provider defaults

    Returns stripped response text, or "" on any error / missing key.
    """
    settings = get_llm_settings()
    resolved_key = api_key or settings.resolved_api_key()
    resolved_model = model or settings.resolved_model()

    if not resolved_key:
        return ""

    provider = settings.provider
    base_url = settings.base_url

    # If caller provided an explicit api_key that looks like an Anthropic key
    # but settings say openai_compatible, respect the settings provider.
    # If no settings configured, infer from key prefix.
    if not settings.api_key and api_key:
        if api_key.startswith("sk-ant-") and provider != "anthropic":
            provider = "anthropic"

    try:
        if provider == "openai_compatible":
            return _call_openai_compatible(
                prompt=prompt,
                api_key=resolved_key,
                model=resolved_model,
                max_tokens=max_tokens,
                system=system,
                base_url=base_url,
            )
        else:
            return _call_anthropic(
                prompt=prompt,
                api_key=resolved_key,
                model=resolved_model,
                max_tokens=max_tokens,
                system=system,
            )
    except Exception:
        logger.exception("LLM call failed (provider=%s, model=%s)", provider, resolved_model)
        return ""


def call_llm_stream(
    prompt: str,
    *,
    api_key: str | None = None,
    model: str | None = None,
    max_tokens: int = 500,
    system: str | None = None,
):
    """Streaming variant — yields text chunks.

    Falls back to single call_llm() if streaming not available.
    """
    settings = get_llm_settings()
    resolved_key = api_key or settings.resolved_api_key()
    resolved_model = model or settings.resolved_model()

    if not resolved_key:
        return

    provider = settings.provider
    base_url = settings.base_url

    try:
        if provider == "openai_compatible":
            yield from _stream_openai_compatible(
                prompt=prompt,
                api_key=resolved_key,
                model=resolved_model,
                max_tokens=max_tokens,
                system=system,
                base_url=base_url,
            )
        else:
            yield from _stream_anthropic(
                prompt=prompt,
                api_key=resolved_key,
                model=resolved_model,
                max_tokens=max_tokens,
                system=system,
            )
    except Exception:
        logger.exception("LLM stream failed (provider=%s)", provider)
        return


# ---------------------------------------------------------------------------
#  Anthropic backend
# ---------------------------------------------------------------------------

def _call_anthropic(
    prompt: str,
    api_key: str,
    model: str,
    max_tokens: int,
    system: str | None,
) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    kwargs: dict = dict(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    if system:
        kwargs["system"] = system
    message = client.messages.create(**kwargs)
    text = message.content[0].text.strip() if message.content else ""
    return _truncation_guard(text)


def _stream_anthropic(
    prompt: str,
    api_key: str,
    model: str,
    max_tokens: int,
    system: str | None,
):
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    kwargs: dict = dict(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    if system:
        kwargs["system"] = system
    with client.messages.stream(**kwargs) as stream:
        for chunk in stream.text_stream:
            yield chunk


# ---------------------------------------------------------------------------
#  OpenAI-compatible backend (DeepSeek, OpenRouter, Groq, Ollama, etc.)
# ---------------------------------------------------------------------------

def _call_openai_compatible(
    prompt: str,
    api_key: str,
    model: str,
    max_tokens: int,
    system: str | None,
    base_url: str = "",
) -> str:
    import openai

    client = openai.OpenAI(
        api_key=api_key,
        base_url=base_url or "https://api.deepseek.com",
    )
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=messages,
    )
    text = (response.choices[0].message.content or "").strip()
    return _truncation_guard(text)


def _stream_openai_compatible(
    prompt: str,
    api_key: str,
    model: str,
    max_tokens: int,
    system: str | None,
    base_url: str = "",
):
    import openai

    client = openai.OpenAI(
        api_key=api_key,
        base_url=base_url or "https://api.deepseek.com",
    )
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    stream = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=messages,
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta if chunk.choices else None
        if delta and delta.content:
            yield delta.content


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

def _truncation_guard(text: str) -> str:
    """Append ' …' if response appears truncated (no sentence-ending punctuation)."""
    if text and text[-1] not in ".!?。！？":
        return text + " …"
    return text
