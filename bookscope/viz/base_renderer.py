"""Abstract base class for all BookScope chart renderers.

Separation of concerns:
    Pydantic models  →  ChartDataAdapter  →  BaseRenderer  →  plotly Figure
                        (transform)          (render)

Renderers never import Pydantic schemas directly.
They receive pre-adapted data from ChartDataAdapter.
"""

from abc import ABC, abstractmethod
from typing import Any

import plotly.graph_objects as go

from bookscope.viz.theme import DEFAULT_THEME, BookScopeTheme


class BaseRenderer(ABC):
    """Base class every renderer must extend."""

    def __init__(self, theme: BookScopeTheme = DEFAULT_THEME) -> None:
        self.theme = theme

    @abstractmethod
    def render(self, data: Any) -> go.Figure:
        """Render adapted data into a Plotly Figure.

        Args:
            data: Renderer-specific adapted payload (from ChartDataAdapter).

        Returns:
            A fully configured plotly Figure ready for st.plotly_chart().
        """

    @staticmethod
    def _with_alpha(hex_color: str, alpha: float) -> str:
        """Convert a 6-digit hex color to an rgba() string with the given alpha."""
        hex_color = hex_color.lstrip("#")
        r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
        return f"rgba({r},{g},{b},{alpha})"

    def _apply_dark_layout(self, fig: go.Figure, title: str = "") -> go.Figure:
        """Apply the BookScope dark theme layout to any figure."""
        fig.update_layout(
            title=title,
            plot_bgcolor=self.theme.paper_color,
            paper_bgcolor=self.theme.background_color,
            font=dict(
                family=self.theme.font_family,
                size=self.theme.font_size,
                color=self.theme.font_color,
            ),
            xaxis=dict(gridcolor=self.theme.grid_color, showgrid=True),
            yaxis=dict(gridcolor=self.theme.grid_color, showgrid=True),
            legend=dict(bgcolor="rgba(0,0,0,0)"),
            margin=dict(l=40, r=20, t=50, b=40),
        )
        return fig
