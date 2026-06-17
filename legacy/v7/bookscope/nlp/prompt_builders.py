"""Genre-specific prompt builders for narrative insights.

Extracted from bookscope/api/main.py (_build_narrative_prompt).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bookscope.models.schemas import EmotionScore, StyleScore

EMOTION_FIELDS = (
    "anger", "anticipation", "disgust", "fear",
    "joy", "sadness", "surprise", "trust",
)

ARC_DESC_MAP = {
    "Rags to Riches": "sustained emotional rise toward hope",
    "Riches to Rags": "sustained emotional fall toward darkness",
    "Man in a Hole": "fall then rise — protagonist recovers",
    "Icarus": "rise then fall — early success gives way to tragedy",
    "Cinderella": "rise, fall, then ultimate triumph",
    "Oedipus": "fall, brief rise, then fall again",
    "Unknown": "no clear arc detected",
}


def build_narrative_prompt(
    emotion_scores: list[EmotionScore],
    style_scores: list[StyleScore],
    arc_pattern: str,
    book_type: str,
    ui_lang: str,
) -> str:
    """Build a narrative insight prompt from analysis data.

    Distilled from llm_analyzer.py's genre-specific builders but decoupled
    from Streamlit and AnalysisResult objects.
    """
    lang_name = {"en": "English", "zh": "Chinese", "ja": "Japanese"}.get(
        ui_lang, "English"
    )
    n = len(emotion_scores)

    # Top 3 emotions
    if n > 0:
        avg_emotions = {
            f: round(sum(getattr(s, f) for s in emotion_scores) / n, 2)
            for f in EMOTION_FIELDS
        }
    else:
        avg_emotions = {}
    top_3 = sorted(avg_emotions.items(), key=lambda x: -x[1])[:3]
    top_3_str = ", ".join(f"{e}={v}" for e, v in top_3)

    # Style summary
    n_style = len(style_scores)
    avg_ttr = (
        round(sum(s.ttr for s in style_scores) / n_style, 2) if n_style else 0.5
    )
    avg_sent = (
        round(sum(s.avg_sentence_length for s in style_scores) / n_style, 2)
        if n_style
        else 15.0
    )

    arc_desc = ARC_DESC_MAP.get(arc_pattern, arc_pattern)

    if book_type in ("nonfiction", "academic", "technical", "self_help"):
        return (
            f"You are a reading advisor. Given this non-fiction book's data:\n"
            f"- Top emotions: {top_3_str}\n"
            f"- Argument trajectory: {arc_pattern} — {arc_desc}\n"
            f"- Style: TTR={avg_ttr}, avg_sentence_length={avg_sent}\n"
            f"Write 2-3 sentences about the reading experience: how dense it is, "
            f"what it demands from the reader, and a practical reading strategy. "
            f"Be specific. Use {lang_name}. No generic praise."
        )
    if book_type in ("essay", "biography", "poetry"):
        return (
            f"You are a literary companion. Given this essay/memoir's data:\n"
            f"- Emotional atmosphere: {top_3_str}\n"
            f"- Personal arc: {arc_pattern} — {arc_desc}\n"
            f"- Voice: TTR={avg_ttr}, avg_sentence_length={avg_sent}\n"
            f"Write 2-3 sentences on the author's voice, the emotional atmosphere, "
            f"and who would find it resonant. Be specific. Use {lang_name}. No generic praise."
        )
    return (
        f"You are a literary analyst. Given this fiction book's data:\n"
        f"- Top emotions: {top_3_str}\n"
        f"- Arc pattern: {arc_pattern} ({arc_desc})\n"
        f"- Style: TTR={avg_ttr}, avg_sentence_length={avg_sent}\n"
        f"Write 2-3 sentences describing the emotional experience of reading this book. "
        f"Be specific about what it FEELS like to read. "
        f"Use {lang_name}. No generic praise."
    )
