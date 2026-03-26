"""LexiconAnalyzer — Phase 1 emotion backend using nrclex.

nrclex wraps the NRC Emotion Lexicon (Mohammad & Turney, 2013).
It returns raw word-level affect counts across 8 Plutchik emotions.

We normalize counts to [0.0, 1.0] by dividing by total affected words,
so scores are comparable across chunks of different lengths.
"""

from nrclex import NRCLex  # type: ignore[import]

from bookscope.models import ChunkResult, EmotionScore

# NRC emotion keys → EmotionScore field names (1-to-1 mapping)
_NRC_FIELDS = ("anger", "anticipation", "disgust", "fear", "joy", "sadness", "surprise", "trust")


class LexiconAnalyzer:
    """Emotion analyzer backed by the NRC Emotion Lexicon via nrclex.

    Usage:
        analyzer = LexiconAnalyzer()
        score = analyzer.analyze_chunk(chunk)
    """

    def analyze_chunk(self, chunk: ChunkResult) -> EmotionScore:
        """Score one chunk across 8 Plutchik dimensions.

        Args:
            chunk: ChunkResult with non-empty .text.

        Returns:
            EmotionScore with normalized [0.0, 1.0] values.
            All zeros if the text contains no NRC-matched words.
        """
        if not chunk.text.strip():
            return EmotionScore(chunk_index=chunk.index)

        nrc = NRCLex()
        nrc.load_raw_text(chunk.text)
        raw: dict[str, float] = nrc.raw_emotion_scores

        # Total affect count for normalization (avoid div-by-zero)
        total = sum(raw.get(field, 0.0) for field in _NRC_FIELDS)

        if total == 0:
            return EmotionScore(chunk_index=chunk.index)

        return EmotionScore(
            chunk_index=chunk.index,
            **{field: raw.get(field, 0.0) / total for field in _NRC_FIELDS},
        )

    def analyze_book(self, chunks: list[ChunkResult]) -> list[EmotionScore]:
        """Analyze all chunks sequentially."""
        return [self.analyze_chunk(c) for c in chunks]
