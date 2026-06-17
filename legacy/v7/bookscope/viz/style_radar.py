"""StyleRadarRenderer — renders the style fingerprint as a Plotly radar chart."""

import plotly.graph_objects as go

from bookscope.viz.base_renderer import BaseRenderer
from bookscope.viz.chart_data_adapter import StyleRadarData
from bookscope.viz.theme import DEFAULT_THEME, BookScopeTheme


class StyleRadarRenderer(BaseRenderer):
    """Renders a book's style profile as a filled radar (spider) chart."""

    def __init__(self, theme: BookScopeTheme = DEFAULT_THEME) -> None:
        super().__init__(theme)

    def render(self, data: StyleRadarData) -> go.Figure:
        """Build a radar chart from StyleRadarData.

        Args:
            data: Adapted payload produced by ChartDataAdapter.style_radar().

        Returns:
            Plotly Figure with a single filled radar trace.
            Empty figure when data.labels is empty.
        """
        fig = go.Figure()

        if not data.labels:
            return fig

        # Close the polygon by repeating the first point
        labels = data.labels + [data.labels[0]]
        values = data.values + [data.values[0]]

        fig.add_trace(
            go.Scatterpolar(
                r=values,
                theta=labels,
                fill="toself",
                fillcolor="rgba(100,149,237,0.25)",
                line=dict(color="#6495ed", width=2),
                name="Style Profile",
                hovertemplate="%{theta}: %{r:.3f}<extra></extra>",
            )
        )

        self._apply_dark_layout(fig, title="Style Fingerprint")
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
