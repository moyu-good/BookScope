"""Compute derived fields from raw analysis scores.

Extracted from bookscope/api/main.py where this logic was duplicated in
/api/analyze, /api/session/{id}/analysis, /api/library/{id}/analysis,
and /api/share/{token}/analysis.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from bookscope.insights import build_reader_verdict, compute_readability

if TYPE_CHECKING:
    from bookscope.models.schemas import EmotionScore, ReaderVerdict, StyleScore


@dataclass
class DerivedFields:
    """All fields derived from raw emotion/style scores."""

    dominant_emotion: str
    readability_score: float
    readability_label: str
    readability_confidence: float
    reader_verdict: ReaderVerdict
    valence_series: list[float]


def compute_derived_fields(
    emotion_scores: list[EmotionScore],
    style_scores: list[StyleScore],
    arc_pattern: str,
    book_type: str = "fiction",
    ui_lang: str = "en",
) -> DerivedFields:
    """Compute all derived fields from raw analysis scores."""
    from bookscope.nlp.arc_classifier import ArcClassifier

    # Dominant emotion
    dominants = (
        Counter(s.dominant_emotion for s in emotion_scores)
        if emotion_scores
        else Counter()
    )
    top_emotion = dominants.most_common(1)[0][0] if dominants else "joy"

    # Readability
    readability_score, readability_label, read_confidence = compute_readability(
        style_scores, ui_lang
    )

    # Reader verdict
    verdict = build_reader_verdict(
        arc_value=arc_pattern,
        top_emotion_key=top_emotion,
        style_scores=style_scores,
        book_type=book_type,
        ui_lang=ui_lang,
    )

    # Valence series
    classifier = ArcClassifier()
    valence = classifier.valence_series(emotion_scores) if emotion_scores else []

    return DerivedFields(
        dominant_emotion=top_emotion,
        readability_score=readability_score,
        readability_label=readability_label,
        readability_confidence=read_confidence,
        reader_verdict=verdict,
        valence_series=valence,
    )
