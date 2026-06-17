"""Unit tests for bookscope.nlp.ArcClassifier."""

import pytest

from bookscope.models import EmotionScore
from bookscope.nlp.arc_classifier import ArcClassifier, ArcPattern


def make_score(idx: int, joy: float = 0.0, sadness: float = 0.0) -> EmotionScore:
    return EmotionScore(chunk_index=idx, joy=joy, sadness=sadness)


def rising_scores(n: int = 20) -> list[EmotionScore]:
    return [EmotionScore(chunk_index=i, joy=i / (n - 1)) for i in range(n)]


def falling_scores(n: int = 20) -> list[EmotionScore]:
    return [EmotionScore(chunk_index=i, sadness=i / (n - 1)) for i in range(n)]


def u_shape_scores(n: int = 20) -> list[EmotionScore]:
    """High joy at start/end, low in the middle (U shape → Man in a Hole)."""
    scores = []
    for i in range(n):
        t = i / (n - 1)
        joy = 1.0 - 2 * t if t < 0.5 else 2 * t - 1.0
        sadness = 1.0 - joy
        scores.append(EmotionScore(chunk_index=i, joy=max(0, joy), sadness=max(0, sadness)))
    return scores


class TestArcClassifier:
    def setup_method(self):
        self.clf = ArcClassifier()

    def test_returns_arc_pattern(self):
        result = self.clf.classify(rising_scores())
        assert isinstance(result, ArcPattern)

    def test_rising_is_rags_to_riches(self):
        assert self.clf.classify(rising_scores()) == ArcPattern.RAGS_TO_RICHES

    def test_falling_is_riches_to_rags(self):
        assert self.clf.classify(falling_scores()) == ArcPattern.RICHES_TO_RAGS

    def test_too_short_returns_unknown(self):
        scores = [make_score(i) for i in range(3)]
        assert self.clf.classify(scores) == ArcPattern.UNKNOWN

    def test_empty_returns_unknown(self):
        assert self.clf.classify([]) == ArcPattern.UNKNOWN

    def test_valence_series_length_matches_input(self):
        scores = rising_scores(15)
        series = self.clf.valence_series(scores)
        assert len(series) == 15

    def test_valence_series_sorted_by_chunk_index(self):
        scores = [make_score(2, joy=0.2), make_score(0, joy=0.0), make_score(1, joy=0.1)]
        series = self.clf.valence_series(scores)
        assert series[0] == pytest.approx(0.0)
        assert series[1] == pytest.approx(0.1)
        assert series[2] == pytest.approx(0.2)

    def test_all_arc_patterns_are_valid_enum_values(self):
        """Smoke test: classifier never returns an invalid enum."""
        for scores in [rising_scores(), falling_scores(), u_shape_scores()]:
            result = self.clf.classify(scores)
            assert result in ArcPattern.__members__.values()

    def test_cinderella_arc(self):
        """Rise → fall → rise should classify as Cinderella."""
        n = 30
        scores = []
        for i in range(n):
            t = i / (n - 1)
            # up for first third, down for middle third, up again for last third
            if t < 0.33:
                joy = t / 0.33
            elif t < 0.66:
                joy = 1.0 - (t - 0.33) / 0.33
            else:
                joy = (t - 0.66) / 0.34
            scores.append(EmotionScore(chunk_index=i, joy=joy))
        assert self.clf.classify(scores) == ArcPattern.CINDERELLA

    def test_oedipus_arc(self):
        """Fall → rise → fall should classify as Oedipus."""
        n = 30
        scores = []
        for i in range(n):
            t = i / (n - 1)
            # down for first third, up for middle third, down again for last third
            if t < 0.33:
                sadness = t / 0.33
            elif t < 0.66:
                sadness = 1.0 - (t - 0.33) / 0.33
            else:
                sadness = (t - 0.66) / 0.34
            scores.append(EmotionScore(chunk_index=i, sadness=sadness))
        assert self.clf.classify(scores) == ArcPattern.OEDIPUS


class TestClassifyWithConfidence:
    def setup_method(self):
        self.clf = ArcClassifier()

    def _cinderella_scores(self, n: int = 30) -> list[EmotionScore]:
        """Rise → fall → rise (W-shape valence)."""
        scores = []
        for i in range(n):
            t = i / (n - 1)
            if t < 0.33:
                joy = t / 0.33
            elif t < 0.66:
                joy = 1.0 - (t - 0.33) / 0.33
            else:
                joy = (t - 0.66) / 0.34
            scores.append(EmotionScore(chunk_index=i, joy=joy))
        return scores

    def _oedipus_scores(self, n: int = 30) -> list[EmotionScore]:
        """Fall → rise → fall (M-shape valence)."""
        scores = []
        for i in range(n):
            t = i / (n - 1)
            if t < 0.33:
                sadness = t / 0.33
            elif t < 0.66:
                sadness = 1.0 - (t - 0.33) / 0.33
            else:
                sadness = (t - 0.66) / 0.34
            scores.append(EmotionScore(chunk_index=i, sadness=sadness))
        return scores

    def test_returns_tuple_of_pattern_and_float(self):
        pattern, conf = self.clf.classify_with_confidence(rising_scores())
        assert isinstance(pattern, ArcPattern)
        assert isinstance(conf, float)

    def test_short_input_returns_unknown_zero(self):
        scores = [EmotionScore(chunk_index=i) for i in range(3)]
        pattern, conf = self.clf.classify_with_confidence(scores)
        assert pattern == ArcPattern.UNKNOWN
        assert conf == pytest.approx(0.0)

    def test_confidence_in_range(self):
        _, conf = self.clf.classify_with_confidence(rising_scores())
        assert 0.0 <= conf <= 1.0

    def test_confidence_high_for_clean_rags_to_riches(self):
        """A perfectly linear rising series should match the RAGS_TO_RICHES template
        with near-zero MAE, yielding confidence above 0.85."""
        pattern, conf = self.clf.classify_with_confidence(rising_scores(20))
        assert pattern == ArcPattern.RAGS_TO_RICHES
        assert conf > 0.85

    def test_cinderella_distance_lower_than_oedipus_distance(self):
        """The distance_to_arc for a rise-fall-rise series must be lower for
        CINDERELLA than for OEDIPUS, verifying the relative metric is sensible."""
        series = self.clf.valence_series(self._cinderella_scores())
        d_cin = self.clf.distance_to_arc(series, ArcPattern.CINDERELLA)
        d_oed = self.clf.distance_to_arc(series, ArcPattern.OEDIPUS)
        assert d_cin < d_oed

    def test_oedipus_distance_lower_than_cinderella_distance(self):
        """The distance_to_arc for a fall-rise-fall series must be lower for
        OEDIPUS than for CINDERELLA."""
        series = self.clf.valence_series(self._oedipus_scores())
        d_oed = self.clf.distance_to_arc(series, ArcPattern.OEDIPUS)
        d_cin = self.clf.distance_to_arc(series, ArcPattern.CINDERELLA)
        assert d_oed < d_cin

    def test_classify_backward_compat_still_returns_arc_pattern(self):
        """classify() must still return a bare ArcPattern, not a tuple."""
        result = self.clf.classify(rising_scores())
        assert isinstance(result, ArcPattern)
        assert not isinstance(result, tuple)
