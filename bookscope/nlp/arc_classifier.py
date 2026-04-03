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

    # Canonical 100-point arc templates, y normalized to [0, 1].
    # Used by distance_to_arc() to score how closely a valence series
    # matches each classic arc pattern.
    _tmpl_x = np.linspace(0, 1, 100)
    ARC_TEMPLATES: dict[ArcPattern, np.ndarray] = {
        ArcPattern.RAGS_TO_RICHES: _tmpl_x.copy(),
        ArcPattern.RICHES_TO_RAGS: (1.0 - _tmpl_x).copy(),
        # U-shape: high→low→high  (protagonist falls into trouble, then recovers)
        ArcPattern.MAN_IN_HOLE:    (0.5 + 0.5 * np.cos(2 * np.pi * _tmpl_x)).copy(),
        # ∩-shape: low→high→low  (early success gives way to tragedy)
        ArcPattern.ICARUS:         (0.5 - 0.5 * np.cos(2 * np.pi * _tmpl_x)).copy(),
        # rise→fall→rise  (triumph, setback, ultimate win)
        ArcPattern.CINDERELLA:     np.clip(
            0.5 + 0.45 * np.sin(2 * np.pi * _tmpl_x - 0.15 * np.pi), 0.0, 1.0
        ).copy(),
        # fall→rise→fall  (brief hope between two struggles)
        ArcPattern.OEDIPUS:        np.clip(
            0.5 - 0.45 * np.sin(2 * np.pi * _tmpl_x - 0.15 * np.pi), 0.0, 1.0
        ).copy(),
    }

    def classify(self, scores: list[EmotionScore]) -> ArcPattern:
        """Classify the emotional arc of a sequence of EmotionScores.

        Args:
            scores: List of EmotionScore objects (at least 6 recommended).

        Returns:
            ArcPattern enum value. Returns UNKNOWN for very short sequences.
        """
        return self.classify_with_confidence(scores)[0]

    def classify_with_confidence(
        self, scores: list[EmotionScore]
    ) -> tuple[ArcPattern, float]:
        """Classify the arc and return a confidence score.

        Uses Reagan et al. (2016) method: compute Mean Absolute Error between
        the normalised valence series and each of the six canonical arc templates,
        then return the best-matching pattern with its confidence.

        Confidence is derived from the MAE of the best match:
            MAE < 0.15  → High   (confidence > 0.85)
            MAE < 0.30  → Moderate
            MAE >= 0.30 → Low — arc is ambiguous

        Returns:
            (ArcPattern, confidence) where confidence ∈ [0.0, 1.0].
            Returns (UNKNOWN, 0.0) for sequences shorter than _MIN_CHUNKS.
        """
        if len(scores) < _MIN_CHUNKS:
            return ArcPattern.UNKNOWN, 0.0

        valence_series = self.valence_series(scores)

        # Score all six named patterns; pick the one with lowest MAE.
        named_patterns = [p for p in ArcPattern if p != ArcPattern.UNKNOWN]
        best_pattern = ArcPattern.UNKNOWN
        best_mae = 1.0
        for pattern in named_patterns:
            mae = self.distance_to_arc(valence_series, pattern)
            if mae < best_mae:
                best_mae = mae
                best_pattern = pattern

        # Convert MAE to a 0-1 confidence score (lower MAE = higher confidence)
        confidence = max(0.0, min(1.0, 1.0 - best_mae))
        return best_pattern, confidence

    def valence_series(self, scores: list[EmotionScore]) -> list[float]:
        """Return the raw valence value for each score, sorted by chunk_index."""
        return [_valence(s) for s in sorted(scores, key=lambda s: s.chunk_index)]

    def distance_to_arc(
        self,
        valence_series: list[float],
        pattern: ArcPattern,
    ) -> float:
        """Mean absolute error between a valence series and an arc template.

        Both the series and the template are normalized to [0, 1] before
        comparison, so books of any length and emotional range are comparable.

        Args:
            valence_series: Raw valence values (at least 2 points).
            pattern:        Arc pattern to compare against.

        Returns:
            MAE in [0, 1] — lower means the series is closer to the pattern.
            Returns ``1.0`` for series shorter than 2 points or for
            ``ArcPattern.UNKNOWN`` (which has no template).
        """
        template = self.ARC_TEMPLATES.get(pattern)
        if template is None or len(valence_series) < 2:
            return 1.0

        series = np.array(valence_series, dtype=float)
        # Resample to 100 points so lengths are always comparable
        x_orig = np.linspace(0, 1, len(series))
        x_fine = np.linspace(0, 1, 100)
        series_100 = np.interp(x_fine, x_orig, series)

        # Normalize y to [0, 1]
        v_min, v_max = series_100.min(), series_100.max()
        span = v_max - v_min
        if span < 1e-9:
            series_norm = np.full(100, 0.5)
        else:
            series_norm = (series_100 - v_min) / span

        return float(np.mean(np.abs(series_norm - template)))
