"""BookScope — welcome screen + topnav (Option C: no sidebar)."""

import os

import streamlit as st

from bookscope.app_utils import set_lang
from bookscope.store import Repository


class _CachedUpload:
    """Mimics st.UploadedFile interface for cached bytes from a previous upload."""

    def __init__(self, data: bytes, name: str):
        self._data = data
        self.name = name

    def getvalue(self) -> bytes:
        return self._data

    def read(self) -> bytes:
        return self._data


def render_sidebar_inputs(ui_lang: str, T: dict) -> tuple:
    """Render topnav + welcome screen inputs (Option C: no sidebar).

    Returns:
        (book_type, uploaded, url_input, strategy, chunk_size, min_words)
    """
    # ── Defaults from session_state ──────────────────────────────────────────
    book_type = st.session_state.get("book_type", "fiction")
    strategy = st.session_state.get("_adv_strategy", "paragraph")
    chunk_size = st.session_state.get("_adv_chunk_size", 300)
    min_words = st.session_state.get("_adv_min_words", 50)

    # ── Detect analysis mode ─────────────────────────────────────────────────
    _cached_bytes: bytes | None = st.session_state.get("_cached_file_bytes")
    _cached_name: str = st.session_state.get("_cached_file_name", "")
    _cached_url: str = st.session_state.get("_cached_url", "")
    _in_analysis = (
        bool(_cached_bytes)
        or bool(_cached_url)
        or st.session_state.get("_demo_mode", False)
        or bool(st.session_state.get("_loaded_result"))
    )

    # ── Topnav (always rendered) ─────────────────────────────────────────────
    _logo_col, _lang_col = st.columns([7, 2])
    with _logo_col:
        st.markdown(
            '<div class="bs-topnav-logo">BookScope</div>',
            unsafe_allow_html=True,
        )
    with _lang_col:
        lang_options = ["en", "zh", "ja"]
        lang_display = {"en": "EN", "zh": "中", "ja": "日"}
        selected_lang = st.radio(
            "Language",
            options=lang_options,
            format_func=lambda x: lang_display[x],
            index=lang_options.index(ui_lang),
            horizontal=True,
            key="lang_radio",
            label_visibility="collapsed",
        )
        if selected_lang != ui_lang:
            set_lang(selected_lang)
            st.rerun()

    if _in_analysis:
        # Analysis mode: return cached values — welcome screen not shown
        _uploaded = (
            _CachedUpload(_cached_bytes, _cached_name) if _cached_bytes else None
        )
        return book_type, _uploaded, _cached_url, strategy, chunk_size, min_words

    # ── Welcome screen ────────────────────────────────────────────────────────
    st.divider()
    st.markdown(
        f"""
        <div class="bs-welcome">
            <h2>{T.get('welcome_title', 'Your book, decoded.')}</h2>
            <p>{T.get('welcome_body', 'Upload a book and get instant insight.')}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── Book type tiles (2 rows × 4) ─────────────────────────────────────────
    _type_icons = {
        "fiction": "📖", "biography": "👤", "short_stories": "📝", "poetry": "🎭",
        "academic": "🎓", "essay": "✍️", "technical": "⚙️", "self_help": "💡",
    }
    _type_row1 = ["fiction", "biography", "short_stories", "poetry"]
    _type_row2 = ["academic", "essay", "technical", "self_help"]
    for _row in (_type_row1, _type_row2):
        _cols = st.columns(4)
        for i, _bt in enumerate(_row):
            with _cols[i]:
                _label = f"{_type_icons[_bt]} {T.get(f'type_{_bt}', _bt.replace('_', ' ').title())}"
                if st.button(
                    _label,
                    key=f"_bt_{_bt}",
                    use_container_width=True,
                    type="primary" if book_type == _bt else "secondary",
                ):
                    st.session_state["book_type"] = _bt
                    st.rerun()

    st.write("")

    # ── File uploader ─────────────────────────────────────────────────────────
    uploaded = st.file_uploader(
        T.get("upload_label", "Upload a book"),
        type=["txt", "epub", "pdf"],
        help=T.get("upload_types", "Supports .txt, .epub, .pdf"),
        label_visibility="visible",
    )
    if uploaded is not None:
        st.session_state["_cached_file_bytes"] = uploaded.getvalue()
        st.session_state["_cached_file_name"] = uploaded.name
        st.session_state.pop("_cached_url", None)
        st.rerun()

    # ── URL row ──────────────────────────────────────────────────────────────
    _url_col, _go_col = st.columns([5, 1])
    with _url_col:
        _url_val = st.text_input(
            T.get("url_label", "Or paste a URL"),
            placeholder=T.get("url_placeholder", "https://…"),
            label_visibility="collapsed",
        )
    with _go_col:
        if st.button(
            T.get("analyze_btn", "Analyze →"),
            use_container_width=True,
            type="primary",
            disabled=not _url_val,
        ):
            st.session_state["_cached_url"] = _url_val
            st.session_state.pop("_cached_file_bytes", None)
            st.session_state.pop("_cached_file_name", None)
            st.rerun()

    # ── Demo button ───────────────────────────────────────────────────────────
    _, _demo_col, _ = st.columns([2, 1, 2])
    if _demo_col.button(T.get("try_demo", "Try a demo book"), use_container_width=True):
        st.session_state["_demo_mode"] = True
        st.rerun()

    # ── Advanced settings ─────────────────────────────────────────────────────
    with st.expander(f"⚙️ {T.get('advanced_label', 'Advanced')}"):
        _strategy = st.radio(
            T["strategy_label"],
            options=["paragraph", "fixed"],
            format_func=lambda x: (
                T["strategy_paragraph"] if x == "paragraph" else T["strategy_fixed"]
            ),
            index=0,
            key="strategy",
        )
        st.session_state["_adv_strategy"] = _strategy

        _chunk_size = st.slider(
            T["chunk_size_label"],
            100, 1000, 300, step=50,
            disabled=(_strategy != "fixed"),
            key="chunk_size",
        )
        st.session_state["_adv_chunk_size"] = _chunk_size

        _min_words = st.slider(
            T["min_words_label"], 10, 200, 50, step=10, key="min_words"
        )
        st.session_state["_adv_min_words"] = _min_words

        st.divider()

        _has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
        if not _has_key:
            try:
                _has_key = bool(st.secrets.get("ANTHROPIC_API_KEY", ""))
            except Exception:
                pass
        if not _has_key:
            st.caption("⚠️ AI insights unavailable — add ANTHROPIC_API_KEY")

        model_opts = ["claude-haiku-4-5", "claude-sonnet-4-6"]
        model_labels = {
            "claude-haiku-4-5": T["ai_model_haiku"],
            "claude-sonnet-4-6": T["ai_model_sonnet"],
        }
        current_model = st.session_state.get("llm_model", "claude-haiku-4-5")
        selected_model = st.radio(
            T["ai_model_label"],
            options=model_opts,
            format_func=lambda x: model_labels[x],
            index=model_opts.index(current_model) if current_model in model_opts else 0,
            key="llm_model_radio",
        )
        st.session_state["llm_model"] = selected_model

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
                    for _k in ["_cached_file_bytes", "_cached_file_name", "_cached_url"]:
                        st.session_state.pop(_k, None)
                    st.rerun()
                if col3.button("🗑", key=f"del_{p.name}", help="Delete"):
                    repo.delete(p)
                    st.session_state.pop("_loaded_result", None)
                    st.rerun()
        else:
            st.caption(T["no_saved"])

    # Welcome screen complete — no file/URL triggered (those do st.rerun above)
    return book_type, None, "", strategy, chunk_size, min_words


def render_sidebar_detected_lang(detected_lang: str, T: dict) -> None:
    """No-op in Option C (sidebar is hidden)."""
    pass
