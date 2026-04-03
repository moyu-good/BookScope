"""BookScope — Streamlit entry point (v0.6: modular app structure).

Run with:
    streamlit run app/main.py
"""

# Bootstrap NLTK corpora before any NLP imports (safe no-op if already present)
from bookscope.utils import ensure_nltk_data

ensure_nltk_data()

# Load .env if present (local dev only — never required in production)
import pathlib as _pl  # noqa: E402

if _pl.Path(".env").exists():
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

# Fix langdetect non-determinism before first import
from langdetect import DetectorFactory  # noqa: E402

DetectorFactory.seed = 0

import html as _html  # noqa: E402
from collections import Counter  # noqa: E402

import streamlit as st  # noqa: E402

from app.analysis_flow import resolve_analysis_state, run_preview  # noqa: E402
from app.css import inject_css  # noqa: E402
from app.sidebar import render_sidebar_detected_lang, render_sidebar_inputs  # noqa: E402
from app.strings import _ARC_DISPLAY, _STRINGS  # noqa: E402
from app.tabs.arc_pattern import render_arc_pattern  # noqa: E402
from app.tabs.chat import render_chat_tab  # noqa: E402
from app.tabs.chunks import render_chunks  # noqa: E402
from app.tabs.export_tab import render_export  # noqa: E402
from app.tabs.heatmap import render_heatmap  # noqa: E402
from app.tabs.library import render_library_tab  # noqa: E402
from app.tabs.overview import render_overview  # noqa: E402
from app.tabs.quick_insight import _render_verdict_card, render_quick_insight  # noqa: E402
from app.tabs.share import render_share_view  # noqa: E402
from app.tabs.style import render_style  # noqa: E402
from app.tabs.timeline import render_timeline  # noqa: E402
from app.ui_constants import _EMOTION_COLORS, _EMOTION_FIELDS, _EMOTION_ICONS  # noqa: E402
from bookscope.app_utils import get_lang, inject_fonts  # noqa: E402
from bookscope.insights import build_reader_verdict, compute_readability  # noqa: E402
from bookscope.nlp import ArcClassifier  # noqa: E402
from bookscope.nlp.llm_analyzer import call_llm as _call_llm_preview  # noqa: E402
from bookscope.store import AnalysisResult, Repository  # noqa: E402

# ---------------------------------------------------------------------------
# Page config (must be the very first Streamlit call)
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="BookScope",
    page_icon="📖",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# Language / mode / fonts / CSS
# ---------------------------------------------------------------------------

ui_lang = get_lang()
inject_fonts(ui_lang)
inject_css()
T = _STRINGS[ui_lang]

# ---------------------------------------------------------------------------
# Share view gate — renders before anything else and halts normal UI
# ---------------------------------------------------------------------------

_share_slug = st.query_params.get("share")
if _share_slug:
    render_share_view(_share_slug, T, ui_lang)
    st.stop()

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

(
    book_type, uploaded, url_input, strategy, chunk_size, min_words
) = render_sidebar_inputs(ui_lang, T)

# Keep T in sync after sidebar re-render
T = _STRINGS[ui_lang]

# If new file or URL is provided, clear any previously loaded/demo result
_loaded_result = st.session_state.get("_loaded_result")
_demo_mode = st.session_state.get("_demo_mode", False)
if uploaded is not None or url_input:
    st.session_state.pop("_loaded_result", None)
    st.session_state["_demo_mode"] = False
    _loaded_result = None
    _demo_mode = False

# ---------------------------------------------------------------------------
# Welcome gate — welcome screen is rendered inside render_sidebar_inputs
# ---------------------------------------------------------------------------

if uploaded is None and not url_input and _loaded_result is None and not _demo_mode:
    st.stop()

# ---------------------------------------------------------------------------
# Quick Preview gate (upload path only; URL auto-analyses)
# ---------------------------------------------------------------------------

if uploaded is not None and not url_input and _loaded_result is None and not _demo_mode:
    # Scope session keys to this specific file so they reset on new upload
    import hashlib as _hl
    _fkey = _hl.md5(uploaded.name.encode()).hexdigest()[:8]
    _preview_done_key = f"_preview_done_{_fkey}"
    _wants_full_key = f"_wants_full_{_fkey}"
    _preview_text_key = f"_preview_text_{_fkey}"

    _preview_done = st.session_state.get(_preview_done_key, False)
    _wants_full = st.session_state.get(_wants_full_key, False)

    # Determine API key availability for the preview button
    import os as _os_prev
    _prev_api_ok = bool(_os_prev.environ.get("ANTHROPIC_API_KEY"))
    if not _prev_api_ok:
        try:
            _prev_api_ok = bool(st.secrets.get("ANTHROPIC_API_KEY", ""))
        except Exception:
            pass

    if not _wants_full and not _preview_done:
        # Neither chosen — show two-column buttons
        col_full, col_prev = st.columns(2)
        if col_full.button(
            T.get("btn_full_analysis", "📊 Analyze (Full)"),
            use_container_width=True,
        ):
            st.session_state[_wants_full_key] = True
            st.rerun()
        if col_prev.button(
            T.get("btn_quick_preview", "👁 Quick Preview"),
            disabled=not _prev_api_ok,
            help=(
                T.get("btn_preview_needs_key", "Add ANTHROPIC_API_KEY to enable")
                if not _prev_api_ok
                else None
            ),
            use_container_width=True,
        ):
            st.session_state[_preview_done_key] = True
            st.rerun()
        st.stop()

    if _preview_done:
        # Run partial pipeline (load + chunk only) — cached
        with st.spinner(T.get("btn_quick_preview", "Quick Preview") + "…"):
            _prev_chunks = run_preview(
                uploaded.getvalue(), uploaded.name, strategy, chunk_size, min_words
            )
        # Generate or retrieve LLM preview text
        _prev_text: str = st.session_state.get(_preview_text_key, "")
        if not _prev_text and _prev_api_ok and _prev_chunks:
            _lang_name = {
                "en": "English", "zh": "Chinese", "ja": "Japanese"
            }.get(ui_lang, "English")
            _sample = "\n\n".join(
                c.text[:800] for c in _prev_chunks[:5]
            )
            _prev_prompt = (
                f"Based on these opening passages of a book:\n\n{_sample}\n\n"
                f"Answer in 3 sentences, in {_lang_name}:\n"
                f"1. What is this book about?\n"
                f"2. How does it feel to read?\n"
                f"3. Who is it for?"
            )
            _prev_text = _call_llm_preview(_prev_prompt, max_tokens=300) or ""
            st.session_state[_preview_text_key] = _prev_text

        with st.expander(
            T.get("preview_panel_label", "👁 Quick Preview"),
            expanded=not _wants_full,
        ):
            if _prev_text:
                st.markdown(_prev_text)
            else:
                st.info(T.get(
                    "preview_unavailable",
                    "Preview unavailable — add ANTHROPIC_API_KEY.",
                ))

        if not _wants_full:
            if st.button(
                T.get("btn_full_analysis", "📊 Analyze (Full)"),
                use_container_width=False,
            ):
                st.session_state[_wants_full_key] = True
                st.rerun()
            st.stop()

# ---------------------------------------------------------------------------
# Resolve analysis data
# ---------------------------------------------------------------------------

(
    chunks, emotion_scores, style_scores, detected_lang,
    book_title, n_chunks, total_words, _from_saved,
) = resolve_analysis_state(
    uploaded, url_input, _loaded_result, _demo_mode,
    strategy, chunk_size, min_words, T,
)

# Show detected language in sidebar
render_sidebar_detected_lang(detected_lang, T)

# ---------------------------------------------------------------------------
# Arc classification + dominant emotion
# ---------------------------------------------------------------------------

arc_classifier = ArcClassifier()
arc = arc_classifier.classify(emotion_scores)
arc_display_name = _ARC_DISPLAY[ui_lang].get(arc.value, arc.value)

dominants = Counter(s.dominant_emotion for s in emotion_scores) if emotion_scores else Counter()
top_emotion_key = dominants.most_common(1)[0][0] if dominants else "joy"
top_emotion_name = T["emotion_names"].get(top_emotion_key, top_emotion_key.capitalize())
top_emotion_color = _EMOTION_COLORS.get(top_emotion_key, "#7c3aed")
top_emotion_icon = _EMOTION_ICONS.get(top_emotion_key, "✨")

# ---------------------------------------------------------------------------
# Hero card
# ---------------------------------------------------------------------------

safe_title = _html.escape(book_title)
safe_emotion_name = _html.escape(top_emotion_name)
safe_arc_display = _html.escape(arc_display_name)

# Reading time estimate
_WPM = {"fiction": 250, "academic": 200, "essay": 220}
_reading_time_str = ""
if 100 <= total_words <= 200 * 60 * 250:
    _readability_score, _readability_label, _read_confidence = compute_readability(
        style_scores, ui_lang
    )
    _readability_factor = {"Accessible": 0.2, "Moderate": 0.5, "Dense": 0.75, "Specialist": 1.0}
    _rf = _readability_factor.get(_readability_label, 0.5)
    _base_minutes = total_words / _WPM.get(book_type, 238)
    _adj_minutes = _base_minutes * (0.8 + _rf * 0.4)
    _total_minutes = int(_adj_minutes)
    if _total_minutes >= 90:
        _hours = _total_minutes // 60
        _mins = _total_minutes % 60
        _reading_time_str = T.get("hero_reading_time_hr", "~{h}h {m}min").format(
            h=_hours, m=_mins
        )
    else:
        _reading_time_str = T.get("hero_reading_time_min", "~{m} min").format(
            m=max(1, _total_minutes)
        )

# ---------------------------------------------------------------------------
# Identity Bar — slim title strip (replaces hero card)
# ---------------------------------------------------------------------------

_meta_parts = [f"{total_words:,} {T.get('hero_words', 'words')}"]
if _reading_time_str:
    _meta_parts.append(_html.escape(_reading_time_str))
_meta_parts.append(f"{top_emotion_icon} {safe_emotion_name}")
_meta_parts.append(safe_arc_display)
_meta_str = " · ".join(_meta_parts)

_id_col, _new_col = st.columns([5, 1])
with _id_col:
    st.markdown(
        f'<div class="bs-identity-bar">'
        f'<div class="bs-identity-title">📖 {safe_title}</div>'
        f'<div class="bs-identity-meta">{_meta_str}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )
with _new_col:
    if st.button(
        T.get("new_analysis_btn", "↩ New"),
        key="_new_analysis_btn",
        use_container_width=True,
        help=T.get("new_analysis_help", "Start a new analysis"),
    ):
        for _k in [
            "_cached_file_bytes", "_cached_file_name", "_cached_url",
            "_loaded_result", "_demo_mode",
        ]:
            st.session_state.pop(_k, None)
        st.rerun()

# Demo badge
if _demo_mode and not _from_saved:
    st.info(T["demo_badge"])

# Loaded badge
if _from_saved:
    st.info(T["loaded_badge"])

# ---------------------------------------------------------------------------
# Verdict Band — always visible, above tab bar
# ---------------------------------------------------------------------------

_verdict = build_reader_verdict(
    arc_value=arc.value,
    top_emotion_key=top_emotion_key,
    style_scores=style_scores or [],
    book_type=book_type,
    ui_lang=ui_lang,
)
_render_verdict_card(_verdict, T, ui_lang)

# ---------------------------------------------------------------------------
# Prepare shared data for all tabs
# ---------------------------------------------------------------------------

valence_series = (
    arc_classifier.valence_series(emotion_scores) if len(emotion_scores) >= 2 else []
)
_qi_result = AnalysisResult.create(
    book_title=book_title,
    chunk_strategy=strategy,
    total_chunks=n_chunks,
    total_words=total_words,
    arc_pattern=arc.value,
    detected_lang=detected_lang,
    emotion_scores=emotion_scores,
    style_scores=style_scores,
)

# ---------------------------------------------------------------------------
# v2.0: Chapter preview helper
# ---------------------------------------------------------------------------

def _render_chapter_cards(chunks: list, emotion_scores_list: list, T: dict) -> None:
    """Compact section previews — first 60 chars + dominant emotion per chunk."""
    _label = T.get("chapter_cards_label", "SECTIONS")
    _icons = {
        "joy": "😊", "sadness": "😢", "anger": "😠", "fear": "😨",
        "anticipation": "⏳", "trust": "🤝", "surprise": "😲", "disgust": "🤢",
    }
    rows = ""
    display_chunks = chunks[:20]
    for i, chunk in enumerate(display_chunks):
        text = getattr(chunk, "text", "")
        preview = text[:60].strip().replace("\n", " ")
        if len(text) > 60:
            preview += "…"
        icon = (
            _icons.get(emotion_scores_list[i].dominant_emotion, "")
            if i < len(emotion_scores_list) else ""
        )
        rows += (
            f'<div style="display:flex;gap:.5rem;align-items:baseline;'
            f'font-size:.8rem;color:#5A4A3A;padding:.25rem 0;'
            f'border-bottom:1px solid #E8E4DC;">'
            f'<span style="color:#B8A898;flex-shrink:0;width:1.6em;text-align:right;">'
            f'{i + 1}</span>'
            f'<span style="flex:1;line-height:1.4;">{_html.escape(preview)}</span>'
            f'<span style="flex-shrink:0;">{icon}</span>'
            f'</div>'
        )
    more_html = ""
    if len(chunks) > 20:
        more_html = (
            f'<div style="font-size:.72rem;color:#B8A898;padding:.3rem 0;">'
            f'… {len(chunks) - 20} more</div>'
        )
    st.markdown(
        f'<div class="bs-insight-headline" '
        f'style="border-left:4px solid #B8A898;margin-top:.75rem;">'
        f'<div class="bs-insight-headline-label">📄 {_html.escape(_label)}</div>'
        f'{rows}{more_html}'
        f'</div>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# v2.0: Dual-column layout — left (insight cards) + right (chat)
# ---------------------------------------------------------------------------

_left_col, _right_col = st.columns([3, 2])

with _left_col:
    render_quick_insight(
        book_type=book_type,
        book_title=book_title,
        arc_value=arc.value,
        arc_display_name=arc_display_name,
        top_emotion_key=top_emotion_key,
        top_emotion_name=top_emotion_name,
        top_emotion_color=top_emotion_color,
        total_words=total_words,
        chunks=chunks,
        emotion_scores=emotion_scores,
        style_scores=style_scores,
        valence_series=valence_series,
        detected_lang=detected_lang,
        ui_lang=ui_lang,
        T=T,
        analysis_result=_qi_result,
        show_verdict=False,
    )
    if chunks:
        _render_chapter_cards(chunks, emotion_scores, T)

with _right_col:
    render_chat_tab(chunks, ui_lang, T, book_type=book_type)

# ── Library ───────────────────────────────────────────────────────────────
with st.expander(T.get("tab_library", "📚 Library"), expanded=False):
    render_library_tab(T, ui_lang)

# ── Deep Analysis ─────────────────────────────────────────────────────────
with st.expander(T.get("deep_analysis_expander", "📊 Deep Analysis"), expanded=False):
    render_overview(emotion_scores, T, _EMOTION_FIELDS)
    st.divider()
    render_heatmap(emotion_scores, chunks, T)
    st.divider()
    render_timeline(emotion_scores, T, _EMOTION_FIELDS)
    st.divider()
    render_style(style_scores, T)
    st.divider()
    render_arc_pattern(emotion_scores, arc, arc_display_name, arc_classifier, T)

# ── Export ────────────────────────────────────────────────────────────────
with st.expander(T.get("tab_export", "📦 Export"), expanded=False):
    if not _from_saved:
        repo = Repository()
        author_input = st.text_input(
            T.get("author_label", "Author name (optional)"),
            placeholder=T.get("author_placeholder", "e.g. Jane Austen"),
            key="_author_input",
            label_visibility="visible",
        )
        save_col, share_col, _ = st.columns([1, 1, 4])
        if save_col.button(T["save_btn"]):
            result = AnalysisResult.create(
                book_title=book_title,
                chunk_strategy=strategy,
                total_chunks=n_chunks,
                total_words=total_words,
                arc_pattern=arc.value,
                detected_lang=detected_lang,
                author=author_input.strip(),
                emotion_scores=emotion_scores,
                style_scores=style_scores,
            )
            repo.save(result)
            save_col.success(T["saved_ok"])

        from bookscope.store.supabase_repository import SupabaseRepository as _SupabaseRepo
        _supabase_repo = _SupabaseRepo()
        if share_col.button(
            T.get("share_btn", "🔗 Share analysis"),
            disabled=not _supabase_repo.available,
            help=(
                None if _supabase_repo.available
                else T.get("share_btn_disabled", "Share requires Supabase configuration")
            ),
        ):
            st.session_state["_share_confirm_pending"] = True

        if st.session_state.get("_share_confirm_pending"):
            st.warning(T.get(
                "share_confirm_warning",
                "Once shared, this link is permanent.",
            ))
            confirm_col, cancel_col, _ = st.columns([1, 1, 4])
            if confirm_col.button(T.get("share_confirm_btn", "Yes, share publicly")):
                _share_result = AnalysisResult.create(
                    book_title=book_title,
                    chunk_strategy=strategy,
                    total_chunks=n_chunks,
                    total_words=total_words,
                    arc_pattern=arc.value,
                    detected_lang=detected_lang,
                    author=author_input.strip(),
                    emotion_scores=emotion_scores,
                    style_scores=style_scores,
                )
                _slug = _supabase_repo.publish(_share_result, book_type=book_type)
                st.session_state.pop("_share_confirm_pending", None)
                if _slug:
                    st.success(T.get("share_success", "✅ Shared! Add this to your app URL:"))
                    st.code(f"?share={_slug}")
                else:
                    st.error(T.get("share_error", "Failed to share."))
            if cancel_col.button(T.get("share_cancel", "Cancel")):
                st.session_state.pop("_share_confirm_pending", None)
                st.rerun()

        st.divider()

    render_export(
        book_title, strategy, n_chunks, total_words,
        arc, detected_lang, emotion_scores, style_scores, T,
        book_type=book_type,
        top_emotion_name=top_emotion_name,
        ui_lang=ui_lang,
    )
    st.divider()
    with st.expander(T.get("tab_chunks", "📄 Raw Chunks"), expanded=False):
        render_chunks(chunks, emotion_scores, style_scores, T)
