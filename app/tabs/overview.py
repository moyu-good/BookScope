"""Overview tab — emotion DNA radar chart."""

import streamlit as st

from bookscope.viz.chart_data_adapter import ChartDataAdapter
from bookscope.viz.emotion_radar_renderer import EmotionRadarRenderer
from bookscope.viz.theme import DEFAULT_THEME


def render_overview(emotion_scores, T: dict, emotion_fields: tuple) -> None:
    st.markdown(f"<p class='bs-desc'>{T['overview_avg_desc']}</p>", unsafe_allow_html=True)

    if emotion_scores:
        st.subheader(T["overview_avg_emotions"])
        radar_data = ChartDataAdapter.build_emotion_radar_data(
            emotion_scores,
            emotion_colors=DEFAULT_THEME.emotion_colors,
        )
        renderer = EmotionRadarRenderer()
        fig = renderer.render(radar_data)
        st.plotly_chart(fig, use_container_width=True)
