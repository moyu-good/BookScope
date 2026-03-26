"""ArcClassifier — detect emotional arc patterns from EmotionScore sequences.

Based on Reagan et al. (2016) "The emotional arcs of stories are dominated by
six basic shapes" — classifies the valence trajectory into one of six patterns.

Valence = (joy + anticipation + trust) - (anger + fear + sadness + disgust)

The six patterns:
    Rags to Riches  — sustained rise
    Riches to Rags  — sustained fall
    Man in a Hole   — fall → rise  (U-shape)
    Icarus          — rise → fall  (∩-shape)
    Cinderella      — rise → fall → rise
    Oedipus         — fall → rise → fall
"""

from enum import StrEnum

import numpy as np

from bookscope.models import EmotionScore


class ArcPattern(StrEnum):
    RAGS_TO_RICHES = "Rags to Riches"
    RICHES_TO_RAGS = "Riches to Rags"
    MAN_IN_HOLE = "Man in a Hole"
    ICARUS = "Icarus"
    CINDERELLA = "Cinderella"
    OEDIPUS = "Oedipus"
    UNKNOWN = "Unknown"


_MIN_CHUNKS = 6  # minimum data points for a meaningful classification


def _valence(score: EmotionScore) -> float:
    """Compute signed valence from a single EmotionScore."""
    positive = score.joy + score.anticipation + score.trust
    negative = score.anger + score.fear + score.sadness + score.disgust
    return positive - negative


class ArcClassifier:
    """Classifies the emotional arc shape of a book from its EmotionScores."""

    def classify(self, scores: list[EmotionScore]) -> ArcPattern:
        """Classify the emotional arc of a sequence of EmotionScores.

        Args:
            scores: List of EmotionScore objects (at least 6 recommended).

        Returns:
            ArcPattern enum value. Returns UNKNOWN for very short sequences.
        """
        if len(scores) < _MIN_CHUNKS:
            return ArcPattern.UNKNOWN

        sorted_scores = sorted(scores, key=lambda s: s.chunk_index)
        valences = np.array([_valence(s) for s in sorted_scores], dtype=float)

        # Fit degree-3 polynomial — this acts as a global smoother without
        # the edge-effect distortion of a convolution window.
        x = np.linspace(0, 1, len(valences))
        coeffs = np.polyfit(x, valences, 3)

        # Evaluate polynomial at 100 evenly spaced points
        x_fine = np.linspace(0, 1, 100)
        y_fine = np.polyval(coeffs, x_fine)

        # Count direction reversals (inflection points in first derivative)
        dy = np.diff(y_fine)
        sign_changes = int(np.sum(np.diff(np.sign(dy)) != 0))

        start, end = float(y_fine[0]), float(y_fine[-1])
        mid = float(y_fine[50])

        if sign_changes == 0:
            return ArcPattern.RAGS_TO_RICHES if end > start else ArcPattern.RICHES_TO_RAGS

        if sign_changes == 1:
            # Single inflection: valley (U) or peak (∩)
            return ArcPattern.MAN_IN_HOLE if mid < min(start, end) else ArcPattern.ICARUS

        # Two or more inflections → three-segment arcs
        q1 = float(y_fine[33])
        q3 = float(y_fine[66])
        # Cinderella: rises then falls then rises again (up-down-up)
        if q1 > start and q3 < q1:
            return ArcPattern.CINDERELLA
        # Oedipus: falls then rises then falls again (down-up-down)
        return ArcPattern.OEDIPUS

    def valence_series(self, scores: list[EmotionScore]) -> list[float]:
        """Return the raw valence value for each score, sorted by chunk_index."""
        return [_valence(s) for s in sorted(scores, key=lambda s: s.chunk_index)]
