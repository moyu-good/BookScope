"""Heatmap tab — emotion intensity heatmap."""

import streamlit as st

from bookscope.viz import ChartDataAdapter, EmotionHeatmapRenderer


def render_heatmap(emotion_scores, chunks, T: dict) -> None:
    st.markdown(f"<p class='bs-desc'>{T['heatmap_desc']}</p>", unsafe_allow_html=True)
    heatmap_data = ChartDataAdapter.emotion_heatmap(emotion_scores, chunks=chunks)
    fig_heatmap = EmotionHeatmapRenderer().render(heatmap_data)
    st.plotly_chart(fig_heatmap, use_container_width=True)
