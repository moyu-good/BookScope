"""BookScope — LLM narrative insight via Claude API.

Standalone module: does NOT implement AnalyzerProtocol (which returns EmotionScore;
this module returns str).
# TODO(v0.8): wrap in protocol if LLM returns structured output

Public API:
    generate_narrative_insight(result, lang: str, genre_type: str = "fiction") -> str

genre_type values: "fiction" | "nonfiction" | "essay"
Each genre uses a different prompt optimised for what makes that book type interesting.
"""

import hashlib
import os

# Module-level streamlit import — None when running outside Streamlit (e.g. tests).
# Tests patch `bookscope.nlp.llm_analyzer.st` to control caching behaviour.
try:
    import streamlit as st
except ImportError:
    st = None  # type: ignore[assignment]


def _get_api_key() -> str | None:
    """Resolve ANTHROPIC_API_KEY from environment or Streamlit secrets.

    Local dev: set ANTHROPIC_API_KEY in .env (loaded by app/main.py at startup).
    Streamlit Cloud: add ANTHROPIC_API_KEY to st.secrets.
    Returns None if no key is available.
    """
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    if st is not None:
        try:
            return st.secrets.get("ANTHROPIC_API_KEY", None)
        except Exception:
            pass
    return None


def _cache_key(result, genre_type: str = "fiction") -> str:
    """Stable cache key: book title + MD5 of emotion scores string + genre type.

    Uses hashlib.md5 (not Python's hash()) for cross-process stability.
    Including genre_type prevents cache collision when the same book is analysed
    under different genre lenses.  "academic" is normalised to "nonfiction" so
    that UI-layer book_type values produce the same key as the canonical name.
    """
    normalized = "nonfiction" if genre_type == "academic" else genre_type
    emotion_hash = hashlib.md5(
        str(result.emotion_scores).encode()
    ).hexdigest()[:8]
    return f"llm_insight_{result.book_title}_{emotion_hash}_{normalized}"


# ---------------------------------------------------------------------------
# Prompt builders — one per genre type
# ---------------------------------------------------------------------------

def _build_prompt_fiction(result, lang: str) -> str:
    """~200-token prompt for fiction: emotional experience of reading this book."""
    emotion_fields = (
        "anger", "anticipation", "disgust", "fear",
        "joy", "sadness", "surprise", "trust",
    )
    n = len(result.emotion_scores)
    if n == 0:
        avg_emotions: dict = {}
    else:
        avg_emotions = {
            e: round(sum(getattr(s, e) for s in result.emotion_scores) / n, 2)
            for e in emotion_fields
        }
    top_3 = sorted(avg_emotions.items(), key=lambda x: -x[1])[:3]
    top_3_str = ", ".join(f"{e}={v}" for e, v in top_3)

    arc_label = result.arc_pattern
    arc_descriptions = {
        "Rags to Riches": "sustained emotional rise toward hope",
        "Riches to Rags":  "sustained emotional fall toward darkness",
        "Man in a Hole":   "fall then rise — protagonist recovers",
        "Icarus":          "rise then fall — early success gives way to tragedy",
        "Cinderella":      "rise, fall, then ultimate triumph",
        "Oedipus":         "fall, brief rise, then fall again",
        "Unknown":         "no clear arc detected",
    }
    arc_desc = arc_descriptions.get(arc_label, arc_label)

    n_style = len(result.style_scores)
    if n_style > 0:
        style_avgs = {
            "ttr":                 round(sum(s.ttr for s in result.style_scores) / n_style, 2),
            "avg_sentence_length": round(
                sum(s.avg_sentence_length for s in result.style_scores) / n_style, 2
            ),
            "noun_ratio":          round(
                sum(s.noun_ratio for s in result.style_scores) / n_style, 2
            ),
        }
    else:
        style_avgs = {}

    lang_name = {"en": "English", "zh": "Chinese", "ja": "Japanese"}.get(lang, "English")

    return (
        f"You are a literary analyst. Given this fiction book's analysis data:\n"
        f"- Top emotions: {top_3_str}\n"
        f"- Arc pattern: {arc_label} ({arc_desc})\n"
        f"- Style scores: {style_avgs}\n"
        f"Write 2-3 sentences describing the emotional experience of reading this book. "
        f"Be specific about what it FEELS like to read. "
        f"Use {lang_name} language. No generic praise."
    )


def _build_prompt_nonfiction(result, lang: str) -> str:
    """~200-token prompt for non-fiction: reading density, argument structure, strategy."""
    n_style = len(result.style_scores)
    if n_style > 0:
        avg_ttr = round(sum(s.ttr for s in result.style_scores) / n_style, 2)
        avg_sent = round(
            sum(s.avg_sentence_length for s in result.style_scores) / n_style, 2
        )
        avg_noun = round(sum(s.noun_ratio for s in result.style_scores) / n_style, 2)
    else:
        avg_ttr, avg_sent, avg_noun = 0.5, 15.0, 0.25

    # Reading time estimate at 238 wpm average
    total_words = getattr(result, "total_words", 0) or 0
    reading_hours = round(total_words / 238 / 60, 1) if total_words > 0 else None
    reading_time_str = f"~{reading_hours}h" if reading_hours else "unknown length"

    # Density label from heuristics
    if avg_noun > 0.32 or avg_sent > 22:
        density_label = "dense / specialist"
    elif avg_noun > 0.24 or avg_sent > 16:
        density_label = "moderate"
    else:
        density_label = "accessible"

    # Arc repurposed as argument trajectory for non-fiction
    arc_label = result.arc_pattern
    arc_as_argument = {
        "Rags to Riches": "builds from basics toward a strong conclusion",
        "Riches to Rags":  "opens with a bold claim, qualifies it heavily",
        "Man in a Hole":   "identifies a problem, explores depth, then resolves",
        "Icarus":          "strong opening thesis, somewhat qualified ending",
        "Cinderella":      "argues a point, faces counterarguments, then wins",
        "Oedipus":         "complex argument with multiple reversals",
        "Unknown":         "no clear argumentative arc",
    }
    arc_desc = arc_as_argument.get(arc_label, arc_label)

    lang_name = {"en": "English", "zh": "Chinese", "ja": "Japanese"}.get(lang, "English")

    return (
        f"You are a reading advisor. Given this non-fiction book's data:\n"
        f"- Reading density: {density_label} (TTR={avg_ttr}, noun_ratio={avg_noun}, "
        f"avg_sentence_length={avg_sent})\n"
        f"- Estimated reading time: {reading_time_str}\n"
        f"- Argument trajectory: {arc_label} — {arc_desc}\n"
        f"Write 2-3 sentences covering: how dense/accessible this book is, "
        f"the reading experience it demands, and a practical reading strategy "
        f"(e.g. linear, front-loaded, skimmable after chapter X). "
        f"Be specific. Use {lang_name} language. No generic praise."
    )


def _build_prompt_essay(result, lang: str) -> str:
    """~200-token prompt for essays/memoirs: author voice, emotional journey, intimacy."""
    emotion_fields = (
        "anger", "anticipation", "disgust", "fear",
        "joy", "sadness", "surprise", "trust",
    )
    n = len(result.emotion_scores)
    if n == 0:
        avg_emotions = {}
    else:
        avg_emotions = {
            e: round(sum(getattr(s, e) for s in result.emotion_scores) / n, 2)
            for e in emotion_fields
        }
    top_3 = sorted(avg_emotions.items(), key=lambda x: -x[1])[:3]
    top_3_str = ", ".join(f"{e}={v}" for e, v in top_3)

    arc_label = result.arc_pattern
    arc_as_journey = {
        "Rags to Riches": "moves from struggle toward acceptance or growth",
        "Riches to Rags":  "traces a loss or disillusionment",
        "Man in a Hole":   "descends into difficulty, then finds a way through",
        "Icarus":          "rises with ambition, then confronts limits",
        "Cinderella":      "a redemption or second-chance arc",
        "Oedipus":         "cycles through hope and loss",
        "Unknown":         "no clear personal arc",
    }
    arc_desc = arc_as_journey.get(arc_label, arc_label)

    n_style = len(result.style_scores)
    if n_style > 0:
        avg_sent = round(
            sum(s.avg_sentence_length for s in result.style_scores) / n_style, 2
        )
        avg_ttr = round(sum(s.ttr for s in result.style_scores) / n_style, 2)
        # adj_ratio as proxy for sensory/emotional writing
        avg_adj = round(
            sum(getattr(s, "adj_ratio", 0.0) for s in result.style_scores) / n_style, 2
        )
    else:
        avg_sent, avg_ttr, avg_adj = 15.0, 0.5, 0.08

    # Voice label heuristics
    if avg_sent < 14:
        voice_label = "short, punchy sentences — intimate and direct"
    elif avg_sent < 20:
        voice_label = "balanced sentences — reflective pace"
    else:
        voice_label = "long, winding sentences — immersive and contemplative"

    lang_name = {"en": "English", "zh": "Chinese", "ja": "Japanese"}.get(lang, "English")

    return (
        f"You are a literary companion. Given this essay/memoir's data:\n"
        f"- Emotional atmosphere: {top_3_str}\n"
        f"- Personal arc: {arc_label} — {arc_desc}\n"
        f"- Voice: {voice_label} (TTR={avg_ttr}, adj_ratio={avg_adj})\n"
        f"Write 2-3 sentences on: the author's voice and tone, the emotional atmosphere "
        f"of reading this book, and who would find it resonant. "
        f"Be specific. Use {lang_name} language. No generic praise."
    )


def _build_prompt(result, lang: str, genre_type: str = "fiction") -> str:
    """Dispatch to the correct genre-specific prompt builder.

    Accepts "academic" as a UI-layer alias for "nonfiction" so that the
    sidebar book_type value can be passed directly without mapping.
    """
    if genre_type in ("nonfiction", "academic"):
        return _build_prompt_nonfiction(result, lang)
    elif genre_type == "essay":
        return _build_prompt_essay(result, lang)
    else:
        return _build_prompt_fiction(result, lang)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_narrative_insight(
    result,
    lang: str,
    genre_type: str = "fiction",
) -> str:
    """Generate a 2-3 sentence LLM narrative insight for the given analysis result.

    Args:
        result:     AnalysisResult with emotion_scores, style_scores, arc_pattern, etc.
        lang:       UI language code ("en" / "zh" / "ja").
        genre_type: Book type lens ("fiction" / "nonfiction" / "essay").
                    Controls which prompt builder and card style is used.

    Returns an empty string if the API key is absent (caller should hide the card).
    Appends ' …' if the response appears truncated (no sentence-ending punctuation).
    Uses st.session_state as the cache store (key includes genre_type).
    """
    api_key = _get_api_key()
    if not api_key:
        return ""

    # Check session-state cache first
    ck = ""
    if st is not None:
        try:
            ck = _cache_key(result, genre_type)
            cached = st.session_state.get(ck)
            if cached is not None:
                return cached
        except Exception:
            ck = ""

    prompt = _build_prompt(result, lang, genre_type)

    try:
        import anthropic

        # Model: read from st.session_state["llm_model"] (set by sidebar selector).
        # Falls back to claude-haiku-4-5 when running outside Streamlit.
        _default_model = "claude-haiku-4-5"
        if st is not None:
            try:
                model_id = st.session_state.get("llm_model", _default_model)
            except Exception:
                model_id = _default_model
        else:
            model_id = _default_model

        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=model_id,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        text = message.content[0].text.strip() if message.content else ""

        # Truncation guard: append ' …' if response doesn't end with sentence punctuation
        if text and text[-1] not in ".!?。！？":
            text = text + " …"

        # Cache in session state
        if st is not None and ck:
            try:
                st.session_state[ck] = text
            except Exception:
                pass

        return text

    except Exception as exc:
        _warn_user(exc)
        return ""


def call_llm(
    prompt: str,
    api_key: str | None = None,
    model: str | None = None,
    max_tokens: int = 500,
) -> str:
    """Public single-call LLM wrapper for use by Chat Tab and other modules.

    Thread-safe: constructs a per-call Anthropic client; never reads session_state.
    Callers must resolve api_key and model in the main Streamlit thread and pass
    them as arguments if calling from a worker thread.

    Args:
        prompt:     The user prompt to send.
        api_key:    Anthropic API key.  If None, resolved via _get_api_key().
        model:      Model ID.  If None, falls back to claude-haiku-4-5.
        max_tokens: Max tokens in the LLM response.

    Returns:
        Stripped response text, or "" on any error / missing key.
    """
    resolved_key = api_key or _get_api_key()
    if not resolved_key:
        return ""
    resolved_model = model or "claude-haiku-4-5"
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=resolved_key)
        message = client.messages.create(
            model=resolved_model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = message.content[0].text.strip() if message.content else ""
        if text and text[-1] not in ".!?。！？":
            text = text + " …"
        return text
    except Exception:
        return ""


def _warn_user(exc: Exception) -> None:
    """Show a Streamlit warning for known Anthropic API errors."""
    if st is None:
        return
    try:
        import anthropic

        if isinstance(exc, anthropic.AuthenticationError):
            st.warning(
                "AI insight unavailable — API key invalid or missing. "
                "Set ANTHROPIC_API_KEY in your .env file or Streamlit secrets."
            )
        elif isinstance(exc, (
            anthropic.APIError,
            anthropic.RateLimitError,
            anthropic.APITimeoutError,
        )):
            st.warning("AI insight unavailable — try again later")
        # Other exceptions are silently swallowed (feature is non-critical)
    except Exception:
        pass
