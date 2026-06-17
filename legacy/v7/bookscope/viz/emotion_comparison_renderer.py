"""EmotionComparisonRenderer — dual-series arc overlay for book comparison.

Subclass of EmotionTimelineRenderer.  Accepts EmotionArcComparisonData
(two normalized valence series) and renders them as overlapping filled-area
traces so books of different lengths can be compared on the same [0, 1] axis.
"""

import plotly.graph_objects as go

from bookscope.viz.chart_data_adapter import EmotionArcComparisonData
from bookscope.viz.emotion_timeline import EmotionTimelineRenderer
from bookscope.viz.theme import DEFAULT_THEME, BookScopeTheme

# Fixed colors for series A and B so they are always distinguishable
_COLOR_A = "#a78bfa"   # purple
_COLOR_B = "#34d399"   # emerald


class EmotionComparisonRenderer(EmotionTimelineRenderer):
    """Renders two books' emotional arcs overlaid for direct comparison."""

    def __init__(self, theme: BookScopeTheme = DEFAULT_THEME) -> None:
        super().__init__(theme)

    def render(self, data: EmotionArcComparisonData) -> go.Figure:  # type: ignore[override]
        """Build a dual-series arc overlay from EmotionArcComparisonData.

        Both series are normalized to [0, 1] on both axes, enabling comparison
        across books of any length.

        Args:
            data: Adapted payload from ChartDataAdapter.build_emotion_arc_comparison_data().

        Returns:
            Plotly Figure with two filled-area traces (series A and B).
            Empty figure when both series are empty.
        """
        fig = go.Figure()

        if data.series_a:
            fig.add_trace(
                go.Scatter(
                    x=data.x_a,
                    y=data.series_a,
                    name=data.label_a,
                    mode="lines",
                    line=dict(color=_COLOR_A, width=2),
                    fill="tozeroy",
                    fillcolor=self._with_alpha(_COLOR_A, 0.15),
                    hovertemplate="%{y:.3f}<extra>%{fullData.name}</extra>",
                )
            )

        if data.series_b:
            fig.add_trace(
                go.Scatter(
                    x=data.x_b,
                    y=data.series_b,
                    name=data.label_b,
                    mode="lines",
                    line=dict(color=_COLOR_B, width=2),
                    fill="tozeroy",
                    fillcolor=self._with_alpha(_COLOR_B, 0.15),
                    hovertemplate="%{y:.3f}<extra>%{fullData.name}</extra>",
                )
            )

        self._apply_dark_layout(fig, title="Emotional Arc Comparison")
        fig.update_layout(
            xaxis_title="Position in book (normalized)",
            yaxis_title="Valence (normalized)",
            yaxis=dict(range=[0, 1], gridcolor=self.theme.grid_color, showgrid=True),
            xaxis=dict(
                tickformat=".0%",
                gridcolor=self.theme.grid_color,
                showgrid=True,
            ),
            hovermode="x unified",
        )
        return fig
