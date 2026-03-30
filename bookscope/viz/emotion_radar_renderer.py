"""EmotionRadarRenderer — 8-axis NRC emotion DNA polar chart.

Receives an EmotionRadarData from ChartDataAdapter and produces a filled
Scatterpolar figure.  The fill color is keyed to the dominant emotion.
"""

import plotly.graph_objects as go

from bookscope.viz.base_renderer import BaseRenderer
from bookscope.viz.chart_data_adapter import EmotionRadarData
from bookscope.viz.theme import DEFAULT_THEME, BookScopeTheme


class EmotionRadarRenderer(BaseRenderer):
    """Renders a book's emotion fingerprint as a filled 8-axis radar chart."""

    def __init__(self, theme: BookScopeTheme = DEFAULT_THEME) -> None:
        super().__init__(theme)

    def render(self, data: EmotionRadarData) -> go.Figure:
        """Build a polar radar chart from EmotionRadarData.

        Args:
            data: Adapted payload produced by ChartDataAdapter.build_emotion_radar_data().

        Returns:
            Plotly Figure with a single filled Scatterpolar trace.
            Empty figure when data.labels is empty.
        """
        fig = go.Figure()

        if not data.labels:
            return fig

        # Close the polygon by repeating the first point
        labels = data.labels + [data.labels[0]]
        values = data.values + [data.values[0]]

        # Fill color keyed to the dominant emotion
        dominant_idx = data.values.index(max(data.values)) if data.values else 0
        dominant_color = data.colors[dominant_idx] if data.colors else "#7c3aed"
        fill_color = self._with_alpha(dominant_color, 0.25)

        fig.add_trace(
            go.Scatterpolar(
                r=values,
                theta=labels,
                fill="toself",
                fillcolor=fill_color,
                line=dict(color=dominant_color, width=2),
                name="Emotion DNA",
                hovertemplate="%{theta}: %{r:.3f}<extra></extra>",
            )
        )

        self._apply_dark_layout(fig, title="Emotion DNA")
        fig.update_layout(
            polar=dict(
                radialaxis=dict(
                    visible=True,
                    range=[0, 1],
                    gridcolor=self.theme.grid_color,
                    tickfont=dict(color=self.theme.font_color, size=10),
                ),
                angularaxis=dict(
                    gridcolor=self.theme.grid_color,
                    tickfont=dict(color=self.theme.font_color, size=11),
                ),
                bgcolor=self.theme.paper_color,
            ),
        )
        return fig
