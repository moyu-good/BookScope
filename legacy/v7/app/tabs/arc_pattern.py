"""Arc Pattern tab — story shape card + valence line chart."""

import html as _html

import streamlit as st


def render_arc_pattern(emotion_scores, arc, arc_display_name: str, arc_classifier, T: dict) -> None:
    st.markdown(f"<p class='bs-desc'>{T['arc_desc']}</p>", unsafe_allow_html=True)

    if len(emotion_scores) >= 6:
        arc_desc_text = T["arc_descriptions"].get(arc.value, "")
        safe_arc_desc = _html.escape(arc_desc_text)
        safe_arc_display = _html.escape(arc_display_name)
        st.markdown(
            f"""
            <div style="background:rgba(124,58,237,0.15);border:1px solid #7c3aed;
                        border-radius:12px;padding:1rem 1.25rem;margin-bottom:1rem;">
                <div style="font-size:1.4rem;font-weight:700;color:#a78bfa;
                            margin-bottom:0.4rem;">{safe_arc_display}</div>
                <div style="color:#cbd5e1;font-size:0.95rem;">{safe_arc_desc}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        valences = arc_classifier.valence_series(emotion_scores)
        st.subheader(T["arc_valence_title"])
        st.markdown(
            f"<p class='bs-desc'>{T['arc_valence_caption']}</p>", unsafe_allow_html=True
        )
        st.line_chart({i: v for i, v in enumerate(valences)})
    else:
        st.info(T["arc_short"])
