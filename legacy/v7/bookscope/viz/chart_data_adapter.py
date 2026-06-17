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
from bookscope.store import AnalysisResult

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


@dataclass
class EmotionRadarData:
    """Adapted payload for EmotionRadarRenderer (8-axis polar chart)."""

    labels: list[str]    # emotion display names (8)
    values: list[float]  # average score per emotion, normalized [0, 1]
    colors: list[str]    # hex color per axis
    avg_density: float = 0.0  # mean emotion_density across chunks (0-1)


@dataclass
class EmotionArcComparisonData:
    """Adapted payload for EmotionComparisonRenderer (dual-series arc overlay)."""

    x_a: list[float]       # normalized position [0, 1] for book A
    x_b: list[float]       # normalized position [0, 1] for book B
    series_a: list[float]  # valence scores (normalized) for book A
    series_b: list[float]  # valence scores (normalized) for book B
    label_a: str           # book A title
    label_b: str           # book B title


@dataclass
class MultiBookArcData:
    """Adapted payload for N-series arc comparison (author cross-book view)."""

    series: list[list[float]]    # one normalized valence series per book
    x_series: list[list[float]]  # normalized x positions per book (same length as series)
    labels: list[str]            # book titles


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

    @staticmethod
    def build_emotion_radar_data(
        scores: list[EmotionScore],
        emotion_colors: dict[str, str] | None = None,
    ) -> "EmotionRadarData":
        """Adapt EmotionScores for the Emotion DNA radar chart.

        Averages each of the 8 NRC emotion dimensions across all chunks.
        Each axis uses the emotion's canonical color from the theme palette.

        Args:
            scores: List of EmotionScore objects (one per chunk).
            emotion_colors: Optional mapping of emotion name → hex color.
                            Falls back to grey when absent.

        Returns:
            EmotionRadarData with 8 labeled, colored axes.
            Returns empty data structure for empty input.
        """
        if not scores:
            return EmotionRadarData(labels=[], values=[], colors=[])

        ec = emotion_colors or {}
        n = len(scores)
        labels: list[str] = []
        values: list[float] = []
        colors: list[str] = []
        for emotion in _EMOTION_FIELDS:
            labels.append(emotion.capitalize())
            values.append(sum(getattr(s, emotion) for s in scores) / n)
            colors.append(ec.get(emotion, "#888888"))

        avg_density = sum(s.emotion_density for s in scores) / n

        return EmotionRadarData(
            labels=labels, values=values, colors=colors, avg_density=avg_density
        )

    @staticmethod
    def build_emotion_arc_comparison_data(
        result_a: "AnalysisResult",
        result_b: "AnalysisResult",
    ) -> "EmotionArcComparisonData":
        """Build dual-series arc comparison data for two books.

        Computes per-chunk valence = joy + trust + anticipation − fear − sadness
        − anger − disgust, then normalizes both x-axis (position in book, 0→1)
        and y-axis (valence, 0→1) so books of different lengths overlay cleanly.

        Args:
            result_a: First AnalysisResult (book A).
            result_b: Second AnalysisResult (book B).

        Returns:
            EmotionArcComparisonData ready for EmotionComparisonRenderer.
        """

        def _valence(scores: list[EmotionScore]) -> list[float]:
            sorted_s = sorted(scores, key=lambda s: s.chunk_index)
            raw = [
                s.joy + s.trust + s.anticipation - s.fear - s.sadness - s.anger - s.disgust
                for s in sorted_s
            ]
            v_min, v_max = min(raw), max(raw)
            span = v_max - v_min
            if span == 0:
                return [0.5] * len(raw)
            return [(v - v_min) / span for v in raw]

        def _norm_x(n: int) -> list[float]:
            if n <= 1:
                return [0.0] * n
            return [i / (n - 1) for i in range(n)]

        sa = _valence(result_a.emotion_scores) if result_a.emotion_scores else []
        sb = _valence(result_b.emotion_scores) if result_b.emotion_scores else []

        return EmotionArcComparisonData(
            x_a=_norm_x(len(sa)),
            x_b=_norm_x(len(sb)),
            series_a=sa,
            series_b=sb,
            label_a=result_a.book_title,
            label_b=result_b.book_title,
        )

    @staticmethod
    def build_multi_book_comparison_data(
        results: "list[AnalysisResult]",
    ) -> "MultiBookArcData":
        """Build N-series arc comparison data for multiple books.

        Same valence formula as build_emotion_arc_comparison_data; normalizes
        x to [0, 1] per book so books of different lengths overlay cleanly.

        Args:
            results: List of AnalysisResult objects (2 or more).

        Returns:
            MultiBookArcData with one series per book.
        """
        def _valence(scores: list[EmotionScore]) -> list[float]:
            sorted_s = sorted(scores, key=lambda s: s.chunk_index)
            raw = [
                s.joy + s.trust + s.anticipation - s.fear - s.sadness - s.anger - s.disgust
                for s in sorted_s
            ]
            v_min, v_max = min(raw), max(raw)
            span = v_max - v_min
            if span == 0:
                return [0.5] * len(raw)
            return [(v - v_min) / span for v in raw]

        def _norm_x(n: int) -> list[float]:
            if n <= 1:
                return [0.0] * n
            return [i / (n - 1) for i in range(n)]

        series: list[list[float]] = []
        x_series: list[list[float]] = []
        labels: list[str] = []
        for r in results:
            vals = _valence(r.emotion_scores) if r.emotion_scores else []
            series.append(vals)
            x_series.append(_norm_x(len(vals)))
            labels.append(r.book_title)

        return MultiBookArcData(series=series, x_series=x_series, labels=labels)
