"""BookScope — LLM narrative insight via Claude API.

Standalone module: does NOT implement AnalyzerProtocol (which returns EmotionScore;
this module returns str).
# TODO(v0.7): wrap in protocol if LLM returns structured EmotionScore

Public API:
    generate_narrative_insight(result: AnalysisResult, lang: str) -> str
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


def _cache_key(result) -> str:
    """Stable cache key: book title + MD5 of emotion scores string.

    Uses hashlib.md5 (not Python's hash()) for cross-process stability.
    """
    emotion_hash = hashlib.md5(
        str(result.emotion_scores).encode()
    ).hexdigest()[:8]
    return f"llm_insight_{result.book_title}_{emotion_hash}"


def _build_prompt(result, lang: str) -> str:
    """Build the ~200-token literary analyst prompt."""
    # Top 3 emotions by average score
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

    # Arc pattern + description
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

    # Style scores compact JSON
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
        f"You are a literary analyst. Given this book's analysis data:\n"
        f"- Top emotions: {top_3_str}\n"
        f"- Arc pattern: {arc_label} ({arc_desc})\n"
        f"- Style scores: {style_avgs}\n"
        f"Write 2-3 sentences describing the emotional experience of reading this book. "
        f"Be specific. Use {lang_name} language. No generic praise."
    )


def generate_narrative_insight(result, lang: str) -> str:
    """Generate a 2-3 sentence LLM narrative insight for the given analysis result.

    Returns an empty string if the API key is absent (caller should hide the card).
    Appends ' …' if the response appears truncated (no sentence-ending punctuation).

    Uses st.session_state as the cache store (key: _cache_key(result)).
    """
    api_key = _get_api_key()
    if not api_key:
        return ""

    # Check session-state cache first
    ck = ""
    if st is not None:
        try:
            ck = _cache_key(result)
            cached = st.session_state.get(ck)
            if cached is not None:
                return cached
        except Exception:
            ck = ""

    prompt = _build_prompt(result, lang)

    try:
        import anthropic

        # Use stable model alias; snapshot claude-haiku-4-5-20251001 is equivalent.
        # TODO(v0.7): expose model selector in sidebar
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-haiku-4-5",
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
        # Surface specific Anthropic errors as Streamlit warnings when available
        _warn_user(exc)
        return ""


def _warn_user(exc: Exception) -> None:
    """Show a Streamlit warning for known Anthropic API errors."""
    if st is None:
        return
    try:
        import anthropic

        if isinstance(exc, (
            anthropic.APIError,
            anthropic.RateLimitError,
            anthropic.APITimeoutError,
        )):
            st.warning("AI insight unavailable — try again later")
        # Other exceptions are silently swallowed (feature is non-critical)
    except Exception:
        pass
