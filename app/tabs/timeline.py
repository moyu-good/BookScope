"""Timeline tab — emotion timeline with multiselect filter."""

import streamlit as st

from bookscope.models import EmotionScore
from bookscope.viz import ChartDataAdapter, EmotionTimelineRenderer


def render_timeline(emotion_scores, T: dict, emotion_fields: tuple) -> None:
    st.markdown(f"<p class='bs-desc'>{T['timeline_desc']}</p>", unsafe_allow_html=True)

    emotion_display = {T["emotion_names"].get(e, e.capitalize()): e for e in emotion_fields}
    selected_labels = st.multiselect(
        T["timeline_select"],
        options=list(emotion_display.keys()),
        default=list(emotion_display.keys()),
        key="timeline_emotions",
    )
    selected_keys = [emotion_display[lbl] for lbl in selected_labels]

    if selected_keys:
        filtered = [
            EmotionScore(
                chunk_index=s.chunk_index,
                **{e: getattr(s, e) for e in selected_keys},
            )
            for s in emotion_scores
        ]
        timeline_data = ChartDataAdapter.emotion_timeline(filtered)
        timeline_data.emotions = {
            k: v for k, v in timeline_data.emotions.items() if k in selected_keys
        }
        st.plotly_chart(
            EmotionTimelineRenderer().render(timeline_data), use_container_width=True
        )
    else:
        st.info(T["timeline_empty"])
