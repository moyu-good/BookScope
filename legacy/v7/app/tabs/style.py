"""Style tab — style radar + per-metric trend line."""

import streamlit as st

from bookscope.viz import ChartDataAdapter, StyleRadarRenderer


def render_style(style_scores, T: dict) -> None:
    st.markdown(f"<p class='bs-desc'>{T['style_desc']}</p>", unsafe_allow_html=True)

    if style_scores:
        radar_data = ChartDataAdapter.style_radar(style_scores)
        st.plotly_chart(StyleRadarRenderer().render(radar_data), use_container_width=True)

        st.subheader(T["style_over_time"])
        metric_keys = list(radar_data.raw_means.keys())
        metric_labels = {
            T["style_metric_names"].get(k, k.replace("_", " ").title()): k
            for k in metric_keys
        }
        selected_metric_label = st.selectbox(
            T["style_pick"],
            options=list(metric_labels.keys()),
            key="style_metric",
        )
        selected_metric_key = metric_labels[selected_metric_label]
        help_text = T["style_metric_help"].get(selected_metric_key, "")
        if help_text:
            st.markdown(f"<p class='bs-desc'>{help_text}</p>", unsafe_allow_html=True)
        st.line_chart({s.chunk_index: getattr(s, selected_metric_key) for s in style_scores})
    else:
        st.info(T["style_no_data"])
