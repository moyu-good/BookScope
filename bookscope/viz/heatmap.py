"""EmotionHeatmapRenderer — renders an emotion × chunk heatmap."""

import plotly.graph_objects as go

from bookscope.viz.base_renderer import BaseRenderer
from bookscope.viz.chart_data_adapter import EmotionHeatmapData
from bookscope.viz.theme import DEFAULT_THEME, BookScopeTheme


class EmotionHeatmapRenderer(BaseRenderer):
    """Renders a 2-D heatmap: rows = 8 Plutchik emotions, columns = chunks."""

    def __init__(self, theme: BookScopeTheme = DEFAULT_THEME) -> None:
        super().__init__(theme)

    def render(self, data: EmotionHeatmapData) -> go.Figure:
        """Build an annotated heatmap from EmotionHeatmapData.

        Args:
            data: Adapted payload produced by ChartDataAdapter.emotion_heatmap().

        Returns:
            Plotly Figure. Empty figure when data.x is empty.
        """
        fig = go.Figure()

        if not data.x:
            return fig

        # Build customdata (n_emotions × n_chunks) from per-chunk hover texts
        if data.hover_texts:
            customdata = [data.hover_texts for _ in data.y]
            hovertemplate = (
                "Chunk %{x}<br>%{y}: %{z:.3f}"
                "<br><br><i>%{customdata}</i>"
                "<extra></extra>"
            )
        else:
            customdata = None
            hovertemplate = "Chunk %{x}<br>%{y}: %{z:.3f}<extra></extra>"

        # Dynamic range: use actual data maximum so colors span the real
        # distribution.  NRC per-emotion values typically sit in 0.03–0.30,
        # so a fixed zmax=1.0 would leave most cells near-zero and grey.
        # Blues is a single-hue scale with no positive/negative connotation
        # (RdYlGn mapped anger=green which was visually misleading).
        all_vals = [v for row in data.z for v in row if v is not None]
        dynamic_zmax = max(all_vals) * 1.1 if all_vals else 1.0

        fig.add_trace(
            go.Heatmap(
                z=data.z,
                x=data.x,
                y=[label.capitalize() for label in data.y],
                colorscale="Blues",
                zmin=0.0,
                zmax=dynamic_zmax,
                customdata=customdata,
                hovertemplate=hovertemplate,
                colorbar=dict(
                    title=dict(
                        text="Score",
                        font=dict(color=self.theme.font_color),
                    ),
                    tickfont=dict(color=self.theme.font_color),
                ),
            )
        )

        self._apply_dark_layout(fig, title="Emotion Heatmap")
        fig.update_layout(
            xaxis_title="Chunk",
            yaxis_title="Emotion",
            xaxis=dict(showgrid=False),
            yaxis=dict(showgrid=False),
            height=380,
        )
        return fig
