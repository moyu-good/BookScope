"""BookScope — Library Tab.

Shows all saved analyses (most recent 20), with dominant emotion badge,
arc name, detected language, and word count. Clicking a book loads it.

Mini comparison: select 2 books, overlay their emotional arcs using
EmotionComparisonRenderer.

Architecture (v0.9 plan):
  - render_library_tab(T, ui_lang) -> None
  - Reuses Repository + existing load flow
  - try/except per file load for corrupted-save guard (H3)
  - EmotionComparisonRenderer for dual-series arc overlay
"""

from collections import Counter

import streamlit as st

from bookscope.store import Repository
from bookscope.viz.chart_data_adapter import ChartDataAdapter
from bookscope.viz.emotion_comparison_renderer import EmotionComparisonRenderer

_EMOTION_ICONS = {
    "anger": "😠", "anticipation": "🔮", "disgust": "🤢",
    "fear": "😱", "joy": "😊", "sadness": "😢",
    "surprise": "😲", "trust": "🤝",
}


def render_library_tab(T: dict, ui_lang: str) -> None:
    """Render the Library tab showing all saved analyses."""
    repo = Repository()
    saved_paths = repo.list_results()

    if not saved_paths:
        st.info(T.get(
            "library_empty",
            "No analyses saved yet. Analyze a book to add it to your library.",
        ))
        return

    # Load up to 20 most recent books with per-file error guard
    results = []
    for path in saved_paths[:20]:
        try:
            result = repo.load(path)
            results.append((path, result))
        except Exception:
            st.caption(f"⚠️ {path.stem} — corrupted, skipped")
            continue

    if not results:
        st.info(T.get("library_all_corrupted", "All saved analyses appear corrupted."))
        return

    st.subheader(T.get("library_title", "Your Book Library"))

    # Book list
    for path, result in results:
        dominants = Counter(s.dominant_emotion for s in result.emotion_scores)
        top_emotion = dominants.most_common(1)[0][0] if dominants else "—"
        emotion_icon = _EMOTION_ICONS.get(top_emotion, "✨")
        emotion_name_raw = top_emotion.capitalize()

        # Use localized emotion name if available
        emotion_name = T.get("emotion_names", {}).get(top_emotion, emotion_name_raw)

        col_info, col_load = st.columns([5, 1])
        with col_info:
            st.markdown(
                f"**{result.book_title}** &nbsp;"
                f"{emotion_icon} {emotion_name} · "
                f"{result.arc_pattern} · "
                f"{result.total_words:,} {T.get('hero_words', 'words').lower()} · "
                f"{result.analyzed_at[:10]}",
                unsafe_allow_html=True,
            )
        with col_load:
            if st.button(
                T.get("load_btn", "▶ Load"),
                key=f"lib_load_{path.name}",
                use_container_width=True,
            ):
                st.session_state["_loaded_result"] = result
                st.rerun()

    st.divider()

    # Mini arc comparison
    st.subheader(T.get("library_compare_title", "Compare Two Books"))
    titles = [r.book_title for _, r in results]
    book_labels = [f"{i+1}. {t[:50]}" for i, t in enumerate(titles)]

    col_a, col_b = st.columns(2)
    with col_a:
        sel_a = st.selectbox(
            T.get("library_compare_a", "Book A"),
            options=range(len(titles)),
            format_func=lambda i: book_labels[i],
            key="lib_compare_a",
        )
    with col_b:
        sel_b = st.selectbox(
            T.get("library_compare_b", "Book B"),
            options=range(len(titles)),
            format_func=lambda i: book_labels[i],
            index=min(1, len(titles) - 1),
            key="lib_compare_b",
        )

    if sel_a == sel_b:
        st.info(T.get("library_compare_same", "Select two different books to compare."))
        return

    _, result_a = results[sel_a]
    _, result_b = results[sel_b]

    if not result_a.emotion_scores or not result_b.emotion_scores:
        st.warning(T.get(
            "library_compare_no_data",
            "One of the selected books has no emotion data.",
        ))
        return

    comparison_data = ChartDataAdapter.build_emotion_arc_comparison_data(result_a, result_b)
    renderer = EmotionComparisonRenderer()
    fig = renderer.render(comparison_data)
    st.plotly_chart(fig, use_container_width=True)
