"""EmotionTimelineRenderer — renders the 8-emotion arc chart.

Receives an EmotionTimelineData from ChartDataAdapter and produces a
filled-area Plotly figure with one trace per Plutchik emotion.
"""

import plotly.graph_objects as go

from bookscope.viz.base_renderer import BaseRenderer
from bookscope.viz.chart_data_adapter import EmotionTimelineData
from bookscope.viz.theme import DEFAULT_THEME, BookScopeTheme


class EmotionTimelineRenderer(BaseRenderer):
    """Renders emotion arcs as overlapping filled-area traces."""

    def __init__(self, theme: BookScopeTheme = DEFAULT_THEME) -> None:
        super().__init__(theme)

    def render(self, data: EmotionTimelineData) -> go.Figure:
        """Build a multi-trace area chart from EmotionTimelineData.

        Args:
            data: Adapted payload produced by ChartDataAdapter.emotion_timeline().

        Returns:
            Plotly Figure with one filled-area trace per emotion.
            Empty figure (no traces) when data.x is empty.
        """
        fig = go.Figure()

        for emotion, scores in data.emotions.items():
            color = self.theme.emotion_colors.get(emotion, "#888888")
            fig.add_trace(
                go.Scatter(
                    x=data.x,
                    y=scores,
                    name=emotion.capitalize(),
                    mode="lines",
                    line=dict(color=color, width=1.5),
                    fill="tozeroy",
                    fillcolor=self._with_alpha(color, 0.15),
                    hovertemplate="%{y:.3f}<extra>%{fullData.name}</extra>",
                )
            )

        self._apply_dark_layout(fig, title="Emotional Arc")
        fig.update_layout(
            xaxis_title="Chunk",
            yaxis_title="Score (normalized)",
            yaxis=dict(range=[0, 1], gridcolor=self.theme.grid_color, showgrid=True),
            hovermode="x unified",
        )
        return fig

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _with_alpha(hex_color: str, alpha: float) -> str:
        """Convert a 6-digit hex color to an rgba() string with the given alpha."""
        hex_color = hex_color.lstrip("#")
        r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
        return f"rgba({r},{g},{b},{alpha})"
