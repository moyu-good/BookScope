"""Overview tab — average emotion scores bar chart."""

import streamlit as st


def render_overview(emotion_scores, T: dict, emotion_fields: tuple) -> None:
    st.markdown(f"<p class='bs-desc'>{T['overview_avg_desc']}</p>", unsafe_allow_html=True)

    if emotion_scores:
        avg_data_raw = {
            e: sum(getattr(s, e) for s in emotion_scores) / len(emotion_scores)
            for e in emotion_fields
        }
        sorted_emotions = sorted(avg_data_raw.items(), key=lambda kv: kv[1], reverse=True)
        avg_data_translated = {
            T["emotion_names"].get(k, k.capitalize()): round(v, 4)
            for k, v in sorted_emotions
        }
        st.subheader(T["overview_avg_emotions"])
        st.bar_chart(avg_data_translated)
