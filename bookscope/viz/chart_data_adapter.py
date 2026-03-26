"""ChartDataAdapter — decouples Pydantic schemas from chart renderers.

This is the only place that knows about both domain models and Plotly.
Renderers receive plain dicts/lists; they never import from bookscope.models.

Transformations:
    list[EmotionScore]  →  EmotionTimelineData  (line chart)
    list[EmotionScore]  →  EmotionHeatmapData   (emotion × chunk heatmap)
    list[StyleScore]    →  StyleRadarData        (radar chart)
"""

from dataclasses import dataclass, field

from bookscope.models import ChunkResult, EmotionScore, StyleScore

_EMOTION_FIELDS = (
    "anger", "anticipation", "disgust", "fear", "joy", "sadness", "surprise", "trust"
)

_STYLE_FIELDS = (
    "avg_sentence_length", "ttr", "noun_ratio", "verb_ratio", "adj_ratio", "adv_ratio"
)

# Expected [lo, hi] ranges for normalizing each style metric to [0, 1]
_STYLE_RANGES: dict[str, tuple[float, float]] = {
    "avg_sentence_length": (5.0, 40.0),
    "ttr": (0.2, 0.95),
    "noun_ratio": (0.0, 0.45),
    "verb_ratio": (0.0, 0.35),
    "adj_ratio": (0.0, 0.20),
    "adv_ratio": (0.0, 0.15),
}

_STYLE_LABELS = {
    "avg_sentence_length": "Sentence Length",
    "ttr": "Vocabulary Richness",
    "noun_ratio": "Noun Density",
    "verb_ratio": "Verb Density",
    "adj_ratio": "Adj Density",
    "adv_ratio": "Adv Density",
}


@dataclass
class EmotionTimelineData:
    """Adapted payload for EmotionTimelineRenderer."""

    x: list[int]                      # chunk indices
    emotions: dict[str, list[float]]  # emotion name → per-chunk score list


@dataclass
class EmotionHeatmapData:
    """Adapted payload for EmotionHeatmapRenderer."""

    z: list[list[float]]           # shape: [n_emotions, n_chunks] — row = emotion, col = chunk
    x: list[int]                   # chunk indices (columns)
    y: list[str]                   # emotion names (rows)
    hover_texts: list[str] = field(default_factory=list)  # per-chunk text snippets (optional)


@dataclass
class StyleRadarData:
    """Adapted payload for StyleRadarRenderer."""

    labels: list[str]         # display names for each metric
    values: list[float]       # normalized [0, 1] book-average per metric
    raw_means: dict[str, float]  # actual (unnormalized) per-metric averages


class ChartDataAdapter:
    """Transforms domain models into renderer-ready data structures."""

    @staticmethod
    def emotion_timeline(scores: list[EmotionScore]) -> EmotionTimelineData:
        """Adapt a list of EmotionScores for the emotion timeline chart.

        Args:
            scores: Ordered list of EmotionScore objects (one per chunk).

        Returns:
            EmotionTimelineData with x-axis indices and per-emotion series.
            Returns empty data structure for empty input.
        """
        if not scores:
            return EmotionTimelineData(
                x=[],
                emotions={field: [] for field in _EMOTION_FIELDS},
            )

        sorted_scores = sorted(scores, key=lambda s: s.chunk_index)

        x = [s.chunk_index for s in sorted_scores]
        emotions: dict[str, list[float]] = {
            field: [getattr(s, field) for s in sorted_scores]
            for field in _EMOTION_FIELDS
        }

        return EmotionTimelineData(x=x, emotions=emotions)

    @staticmethod
    def emotion_heatmap(
        scores: list[EmotionScore],
        chunks: list[ChunkResult] | None = None,
        snippet_len: int = 160,
    ) -> EmotionHeatmapData:
        """Adapt EmotionScores for the emotion × chunk heatmap.

        Returns a 2D grid where rows = emotions, columns = chunk indices.

        Args:
            scores: Ordered emotion scores.
            chunks: Optional chunk list for hover text snippets.
            snippet_len: Max characters of chunk text shown on hover.
        """
        if not scores:
            return EmotionHeatmapData(
                z=[[] for _ in _EMOTION_FIELDS],
                x=[],
                y=list(_EMOTION_FIELDS),
            )

        sorted_scores = sorted(scores, key=lambda s: s.chunk_index)
        x = [s.chunk_index for s in sorted_scores]
        z = [
            [getattr(s, emotion) for s in sorted_scores]
            for emotion in _EMOTION_FIELDS
        ]

        hover_texts: list[str] = []
        if chunks:
            chunk_map = {c.index: c for c in chunks}
            for idx in x:
                c = chunk_map.get(idx)
                if c:
                    snippet = c.text[:snippet_len].replace("\n", " ")
                    if len(c.text) > snippet_len:
                        snippet += "…"
                    hover_texts.append(snippet)
                else:
                    hover_texts.append("")

        return EmotionHeatmapData(z=z, x=x, y=list(_EMOTION_FIELDS), hover_texts=hover_texts)

    @staticmethod
    def style_radar(scores: list[StyleScore]) -> StyleRadarData:
        """Adapt a list of StyleScores for the style radar chart.

        Averages all chunks and normalizes each metric to [0, 1] using
        expected prose ranges so the radar axes are comparable.

        Args:
            scores: List of StyleScore objects (one per chunk).

        Returns:
            StyleRadarData ready for StyleRadarRenderer.
            Returns empty data structure for empty input.
        """
        if not scores:
            return StyleRadarData(labels=[], values=[], raw_means={})

        n = len(scores)
        raw_means: dict[str, float] = {
            metric: sum(getattr(s, metric) for s in scores) / n
            for metric in _STYLE_FIELDS
        }

        labels: list[str] = []
        values: list[float] = []
        for metric in _STYLE_FIELDS:
            lo, hi = _STYLE_RANGES[metric]
            normalized = (raw_means[metric] - lo) / (hi - lo)
            values.append(max(0.0, min(1.0, normalized)))
            labels.append(_STYLE_LABELS[metric])

        return StyleRadarData(labels=labels, values=values, raw_means=raw_means)
