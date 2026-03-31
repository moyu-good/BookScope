"""NarrativeProtocol — ABC for pluggable LLM narrative backends.

Separates narrative text generation (AnalysisResult → str) from the
EmotionScore-producing AnalyzerProtocol (which operates at chunk level).

Usage::

    from bookscope.nlp.narrative_protocol import NarrativeProtocol, ClaudeBackend

    backend = ClaudeBackend()                  # key from env / st.secrets
    text = backend.generate(result, lang="en", genre_type="fiction")

Available backends:
    ClaudeBackend   — Anthropic Claude (wraps llm_analyzer.generate_narrative_insight)
    OpenAIBackend   — stub, raises NotImplementedError
    OllamaBackend   — stub, raises NotImplementedError
"""

from abc import ABC, abstractmethod


class NarrativeProtocol(ABC):
    """ABC for backends that generate a narrative insight string.

    All implementations receive an AnalysisResult-like object and return a
    2-3 sentence string describing the reading experience.

    **Non-raising contract:** return ``""`` on failure so callers can safely
    skip the card without try/except.
    """

    @abstractmethod
    def generate(
        self,
        result,
        lang: str = "en",
        genre_type: str = "fiction",
    ) -> str:
        """Generate a narrative insight for the given analysis result.

        Args:
            result:     AnalysisResult with emotion_scores, style_scores,
                        arc_pattern, book_title, etc.
            lang:       UI language code (``"en"`` / ``"zh"`` / ``"ja"``).
            genre_type: Book type lens
                        (``"fiction"`` / ``"nonfiction"`` / ``"academic"`` /
                        ``"essay"``).

        Returns:
            2-3 sentence narrative string, or ``""`` on failure / missing key.
        """


class ClaudeBackend(NarrativeProtocol):
    """Anthropic Claude narrative backend.

    Wraps :func:`bookscope.nlp.llm_analyzer.generate_narrative_insight` so
    existing session-state caching and model selection logic are preserved.

    Args:
        api_key: Anthropic API key.  ``None`` → resolved from environment /
                 Streamlit secrets inside ``generate_narrative_insight``.
        model:   Claude model ID passed to the Anthropic client.
                 Defaults to ``"claude-haiku-4-5"`` (fast, low-cost).
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-haiku-4-5",
    ) -> None:
        self._api_key = api_key
        self._model = model

    def generate(
        self,
        result,
        lang: str = "en",
        genre_type: str = "fiction",
    ) -> str:
        import os

        from bookscope.nlp.llm_analyzer import generate_narrative_insight

        if self._api_key:
            os.environ.setdefault("ANTHROPIC_API_KEY", self._api_key)
        return generate_narrative_insight(result, lang=lang, genre_type=genre_type)


class OpenAIBackend(NarrativeProtocol):
    """OpenAI narrative backend — not yet implemented."""

    def generate(
        self,
        result,
        lang: str = "en",
        genre_type: str = "fiction",
    ) -> str:
        raise NotImplementedError(
            "OpenAIBackend is not yet implemented. "
            "Use ClaudeBackend or contribute an implementation."
        )


class OllamaBackend(NarrativeProtocol):
    """Ollama local-model narrative backend — not yet implemented."""

    def generate(
        self,
        result,
        lang: str = "en",
        genre_type: str = "fiction",
    ) -> str:
        raise NotImplementedError(
            "OllamaBackend is not yet implemented. "
            "Use ClaudeBackend or contribute an implementation."
        )
