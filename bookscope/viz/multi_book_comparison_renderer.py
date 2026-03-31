"""MultiBookComparisonRenderer — N-series arc overlay for author cross-book view.

Accepts MultiBookArcData (N normalized valence series) and renders them as
overlapping line traces so multiple books by the same author can be compared
on the same [0, 1] axis.
"""

import plotly.graph_objects as go

from bookscope.viz.base_renderer import BaseRenderer
from bookscope.viz.chart_data_adapter import MultiBookArcData
from bookscope.viz.theme import DEFAULT_THEME, BookScopeTheme

# Rotates through BookScopeTheme palette — 8 distinct colors
_SERIES_COLORS = [
    "#a78bfa",  # purple
    "#34d399",  # emerald
    "#fb923c",  # orange
    "#60a5fa",  # blue
    "#f472b6",  # pink
    "#facc15",  # yellow
    "#4ade80",  # green
    "#f87171",  # red
]


class MultiBookComparisonRenderer(BaseRenderer):
    """Renders N books' emotional arcs overlaid for author-level comparison."""

    def __init__(self, theme: BookScopeTheme = DEFAULT_THEME) -> None:
        super().__init__(theme)

    def render(self, data: MultiBookArcData) -> go.Figure:
        """Build an N-series arc overlay from MultiBookArcData.

        All series are normalized to [0, 1] on both axes, enabling comparison
        across books of any length.

        Args:
            data: Adapted payload from ChartDataAdapter.build_multi_book_comparison_data().

        Returns:
            Plotly Figure with one filled-area trace per book.
            Empty figure when data.series is empty.
        """
        fig = go.Figure()

        for i, (x, series, label) in enumerate(
            zip(data.x_series, data.series, data.labels)
        ):
            if not series:
                continue
            color = _SERIES_COLORS[i % len(_SERIES_COLORS)]
            fig.add_trace(
                go.Scatter(
                    x=x,
                    y=series,
                    name=label,
                    mode="lines",
                    line=dict(color=color, width=2),
                    fill="tozeroy",
                    fillcolor=self._with_alpha(color, 0.10),
                    hovertemplate="%{y:.3f}<extra>%{fullData.name}</extra>",
                )
            )

        self._apply_dark_layout(fig, title="Author Arc Comparison")
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
