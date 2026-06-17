"""Chunks tab — block explorer with emotion + style breakdown."""

import streamlit as st


def render_chunks(chunks, emotion_scores, style_scores, T: dict) -> None:
    st.subheader(T["chunks_title"])

    if chunks is None:
        st.info(T["chunks_unavailable"])
        return

    if not emotion_scores:
        st.info(T["chunks_no_match"])
        return

    chunk_idx = st.slider(T["chunks_slider"], 0, len(chunks) - 1, 0, key="chunk_slider")
    sel_chunk = chunks[chunk_idx]
    sel_emotion = next((s for s in emotion_scores if s.chunk_index == chunk_idx), None)
    sel_style = next((s for s in style_scores if s.chunk_index == chunk_idx), None)

    st.markdown(f"**{T['chunks_header'].format(chunk_idx, sel_chunk.word_count)}**")

    col_e, col_s = st.columns(2)

    with col_e:
        st.markdown(f"**{T['chunks_emotion_header']}**")
        if sel_emotion:
            score_dict = {k: v for k, v in sel_emotion.to_dict().items() if v > 0}
            if score_dict:
                sorted_items = sorted(score_dict.items(), key=lambda kv: kv[1], reverse=True)
                translated = {
                    T["emotion_names"].get(k, k.capitalize()): v
                    for k, v in sorted_items
                }
                st.bar_chart(translated)
            else:
                st.caption(T["chunks_no_match"])

    with col_s:
        st.markdown(f"**{T['chunks_style_header']}**")
        if sel_style:
            st.table({
                T["style_metric_names"].get(k, k.replace("_", " ").title()): [f"{v:.3f}"]
                for k, v in sel_style.to_dict().items()
            })

    with st.expander(T["chunks_show_text"], expanded=False):
        st.write(sel_chunk.text[:2000] + ("…" if len(sel_chunk.text) > 2000 else ""))
