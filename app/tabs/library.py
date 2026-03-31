"""BookScope — Library Tab.

Shows all saved analyses (most recent 20), with dominant emotion badge,
arc name, detected language, and word count. Clicking a book loads it.

Mini comparison: select 2 books, overlay their emotional arcs using
EmotionComparisonRenderer.

Author cross-book comparison: group saved books by author, select an author,
overlay all their books' arcs using MultiBookComparisonRenderer.
"""

from collections import Counter

import streamlit as st

from bookscope.store import Repository
from bookscope.viz.chart_data_adapter import ChartDataAdapter
from bookscope.viz.emotion_comparison_renderer import EmotionComparisonRenderer
from bookscope.viz.multi_book_comparison_renderer import MultiBookComparisonRenderer

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

    # Build author → [(path, result)] map
    unknown_label = T.get("library_author_unknown", "Unknown")
    author_groups: dict[str, list] = {}
    for path, result in results:
        author = getattr(result, "author", "").strip() or unknown_label
        author_groups.setdefault(author, []).append((path, result))

    st.subheader(T.get("library_title", "Your Book Library"))

    # Author filter
    all_label = T.get("library_author_all", "All authors")
    author_names = sorted(author_groups.keys())
    if len(author_names) > 1:
        selected_author = st.selectbox(
            T.get("library_author_filter", "Filter by author"),
            options=[all_label] + author_names,
            key="lib_author_filter",
        )
        display_results = (
            author_groups[selected_author]
            if selected_author != all_label
            else results
        )
    else:
        display_results = results

    # Book list
    for path, result in display_results:
        dominants = Counter(s.dominant_emotion for s in result.emotion_scores)
        top_emotion = dominants.most_common(1)[0][0] if dominants else "—"
        emotion_icon = _EMOTION_ICONS.get(top_emotion, "✨")
        emotion_name_raw = top_emotion.capitalize()

        # Use localized emotion name if available
        emotion_name = T.get("emotion_names", {}).get(top_emotion, emotion_name_raw)

        author_str = getattr(result, "author", "").strip()
        author_badge = f" · {author_str}" if author_str else ""

        col_info, col_load = st.columns([5, 1])
        with col_info:
            st.markdown(
                f"**{result.book_title}**{author_badge} &nbsp;"
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

        # Reading diary (sidecar notes)
        notes = repo.load_notes(path)
        with st.expander(T.get("library_notes_label", "📝 Notes"), expanded=False):
            mood = st.slider(
                T.get("library_notes_mood", "Mood rating"),
                min_value=1, max_value=5,
                value=notes.get("mood_score") or 3,
                key=f"lib_mood_{path.name}",
            )
            quote = st.text_input(
                T.get("library_notes_quote", "Most memorable quote"),
                value=notes.get("memorable_quote", ""),
                placeholder=T.get(
                    "library_notes_quote_placeholder", "A sentence that stayed with you..."
                ),
                key=f"lib_quote_{path.name}",
            )
            _btn_label = T.get("library_notes_save", "Save notes")
            if st.button(_btn_label, key=f"lib_notes_save_{path.name}"):
                repo.save_notes(path, {"mood_score": mood, "memorable_quote": quote})
                st.success(T.get("library_notes_saved", "Notes saved."))

    st.divider()

    # ── Mini arc comparison (dual-book) ──────────────────────────────────────
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
    else:
        _, result_a = results[sel_a]
        _, result_b = results[sel_b]

        if not result_a.emotion_scores or not result_b.emotion_scores:
            st.warning(T.get(
                "library_compare_no_data",
                "One of the selected books has no emotion data.",
            ))
        else:
            comparison_data = ChartDataAdapter.build_emotion_arc_comparison_data(result_a, result_b)
            renderer = EmotionComparisonRenderer()
            fig = renderer.render(comparison_data)
            st.plotly_chart(fig, use_container_width=True)

    # ── Author cross-book comparison ─────────────────────────────────────────
    if len(author_names) >= 1:
        st.divider()
        st.subheader(T.get("library_author_compare_title", "Author Cross-Book Comparison"))

        selected_compare_author = st.selectbox(
            T.get("library_author_select", "Select author to compare"),
            options=author_names,
            key="lib_author_compare_select",
        )
        author_results = [
            r for _, r in author_groups.get(selected_compare_author, [])
            if r.emotion_scores
        ]

        if len(author_results) >= 2:
            multi_data = ChartDataAdapter.build_multi_book_comparison_data(author_results)
            multi_renderer = MultiBookComparisonRenderer()
            fig = multi_renderer.render(multi_data)
            st.plotly_chart(fig, use_container_width=True)
        elif len(author_results) == 1:
            st.info(T.get(
                "library_author_compare_need_more",
                "Need at least 2 books by this author to compare.",
            ))
        else:
            st.info(T.get(
                "library_author_compare_no_data",
                "No emotion data available for this author's books.",
            ))
