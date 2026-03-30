"""BookScope — sidebar rendering."""

import streamlit as st

from bookscope.app_utils import set_lang
from bookscope.store import Repository


def render_sidebar_inputs(ui_lang: str, T: dict) -> tuple:
    """Render sidebar inputs section.

    Returns:
        (book_type, uploaded, url_input, strategy, chunk_size, min_words)
    """
    with st.sidebar:
        # Language selector
        lang_options = ["en", "zh", "ja"]
        lang_display = {"en": "🇬🇧 English", "zh": "🇨🇳 中文", "ja": "🇯🇵 日本語"}
        selected_lang = st.radio(
            "Language / 语言 / 言語",
            options=lang_options,
            format_func=lambda x: lang_display[x],
            index=lang_options.index(ui_lang),
            horizontal=True,
            key="lang_radio",
        )
        if selected_lang != ui_lang:
            set_lang(selected_lang)
            st.rerun()

        st.divider()
        st.markdown(f"### {T['sidebar_header']}")
        st.caption(T["sidebar_tagline"])

        # Book type selector (before upload — prevents wrong-default Quick Insight)
        book_type_opts = ["fiction", "academic", "essay"]
        book_type = st.radio(
            T["book_type_label"],
            options=book_type_opts,
            format_func=lambda x: T[f"type_{x}"],
            horizontal=True,
            key="book_type_radio",
        )

        st.divider()

        uploaded = st.file_uploader(
            T["upload_label"],
            type=["txt", "epub", "pdf"],
            help=T["upload_types"],
        )
        url_input = st.text_input(T["url_label"], placeholder=T["url_placeholder"])

        st.divider()
        st.subheader(T["chunking_header"])
        strategy = st.radio(
            T["strategy_label"],
            options=["paragraph", "fixed"],
            format_func=lambda x: (
                T["strategy_paragraph"] if x == "paragraph" else T["strategy_fixed"]
            ),
            index=0,
            key="strategy",
        )
        chunk_size = st.slider(
            T["chunk_size_label"], 100, 1000, 300, step=50,
            disabled=(strategy != "fixed"),
            key="chunk_size",
        )
        min_words = st.slider(T["min_words_label"], 10, 200, 50, step=10, key="min_words")

        st.divider()
        st.subheader(T["saved_header"])
        repo = Repository()
        saved = repo.list_results()
        if saved:
            for p in saved[:5]:
                col1, col2, col3 = st.columns([3, 1, 1])
                col1.caption(p.stem)
                if col2.button(T["load_btn"], key=f"load_{p.name}"):
                    st.session_state["_loaded_result"] = repo.load(p)
                    st.rerun()
                if col3.button("🗑", key=f"del_{p.name}", help="Delete"):
                    repo.delete(p)
                    st.session_state.pop("_loaded_result", None)
                    st.rerun()
        else:
            st.caption(T["no_saved"])

    return book_type, uploaded, url_input, strategy, chunk_size, min_words


def render_sidebar_detected_lang(detected_lang: str, T: dict) -> None:
    """Append detected language label to sidebar (called after analysis completes)."""
    with st.sidebar:
        st.divider()
        lang_label = T["lang_labels"].get(detected_lang, detected_lang)
        st.caption(f"{T['detected_lang']}: **{lang_label}**")
