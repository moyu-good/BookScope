"""BookScope — Essay timeline renderer.

Renders a single-row horizontal Plotly timeline of key idea phrases
sampled from essay/memoir chunks, colored by dominant emotion per chunk.

Public API:
    render_essay_timeline(phrases, emotion_scores) -> go.Figure | None
"""

import plotly.graph_objects as go

_DEFAULT_COLOR = "#a78bfa"

_EMOTION_COLORS: dict[str, str] = {
    "anger": "#ef4444",
    "anticipation": "#f97316",
    "disgust": "#84cc16",
    "fear": "#6b7280",
    "joy": "#eab308",
    "sadness": "#3b82f6",
    "surprise": "#06b6d4",
    "trust": "#22c55e",
}

_EMOTION_FIELDS = (
    "anger", "anticipation", "disgust", "fear",
    "joy", "sadness", "surprise", "trust",
)


def render_essay_timeline(
    phrases: list[str],
    emotion_scores: list,
) -> go.Figure | None:
    """Build a Plotly horizontal single-row timeline of key idea phrases.

    Args:
        phrases:       Key phrases, one per sampled chunk (from extract_essay_phrases).
        emotion_scores: Full list of EmotionScore objects for all chunks.
                        Used for node color — phrases[i] maps to emotion_scores[i].
                        If emotion_scores is shorter than phrases, remaining nodes
                        use the default accent color #a78bfa.

    Returns:
        Plotly Figure (height=120px), or None if phrases is empty.
    """
    if not phrases:
        return None

    n = min(len(phrases), len(emotion_scores)) if emotion_scores else len(phrases)

    colors = []
    for i in range(len(phrases)):
        if i < n and emotion_scores:
            score = emotion_scores[i]
            dom = max(
                _EMOTION_FIELDS,
                key=lambda e, s=score: getattr(s, e, 0.0),
            )
            colors.append(_EMOTION_COLORS.get(dom, _DEFAULT_COLOR))
        else:
            colors.append(_DEFAULT_COLOR)

    x_vals = list(range(len(phrases)))
    y_vals = [0] * len(phrases)

    fig = go.Figure(
        data=go.Scatter(
            x=x_vals,
            y=y_vals,
            mode="markers+text",
            text=phrases,
            textposition="top center",
            textfont={"size": 9, "color": "#e6edf3"},
            marker={
                "size": 12,
                "color": colors,
                "line": {"width": 1, "color": "#374151"},
            },
            hovertext=phrases,
            hoverinfo="text",
            showlegend=False,
        ),
        layout=go.Layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            xaxis={
                "showgrid": False,
                "zeroline": False,
                "showticklabels": False,
                "range": [-0.5, len(phrases) - 0.5],
            },
            yaxis={
                "showgrid": False,
                "zeroline": False,
                "showticklabels": False,
                "range": [-1, 2],
            },
            margin={"l": 10, "r": 10, "t": 30, "b": 10},
            height=120,
        ),
    )
    return fig
