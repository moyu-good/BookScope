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

from app.analysis_flow import resolve_analysis_state  # noqa: E402
from app.css import inject_css  # noqa: E402
from app.sidebar import render_sidebar_detected_lang, render_sidebar_inputs  # noqa: E402
from app.strings import _ARC_DISPLAY, _STRINGS  # noqa: E402
from app.tabs.arc_pattern import render_arc_pattern  # noqa: E402
from app.tabs.chunks import render_chunks  # noqa: E402
from app.tabs.export_tab import render_export  # noqa: E402
from app.tabs.heatmap import render_heatmap  # noqa: E402
from app.tabs.overview import render_overview  # noqa: E402
from app.tabs.quick_insight import render_quick_insight  # noqa: E402
from app.tabs.style import render_style  # noqa: E402
from app.tabs.timeline import render_timeline  # noqa: E402
from app.ui_constants import _EMOTION_COLORS, _EMOTION_FIELDS, _EMOTION_ICONS  # noqa: E402
from bookscope.app_utils import get_lang, get_mode, inject_fonts, set_mode  # noqa: E402
from bookscope.nlp import ArcClassifier  # noqa: E402
from bookscope.store import AnalysisResult, Repository  # noqa: E402

# ---------------------------------------------------------------------------
# Page config (must be the very first Streamlit call)
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="BookScope",
    page_icon="📖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Language / mode / fonts / CSS
# ---------------------------------------------------------------------------

ui_lang = get_lang()
ui_mode = get_mode()
inject_fonts(ui_lang)
inject_css()
T = _STRINGS[ui_lang]

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

book_type, uploaded, url_input, strategy, chunk_size, min_words = render_sidebar_inputs(
    ui_lang, T
)

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
# Welcome screen (no input yet and nothing loaded)
# ---------------------------------------------------------------------------

if uploaded is None and not url_input and _loaded_result is None and not _demo_mode:
    st.markdown(
        f"""
        <div class="bs-welcome">
            <h2>📖 {_html.escape(T['welcome_title'])}</h2>
            <p>{T['welcome_body']}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    _, center_col, _ = st.columns([2, 1, 2])
    if center_col.button(T["try_demo"], use_container_width=True):
        st.session_state["_demo_mode"] = True
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

_arc_article = "an" if arc_display_name[:1].lower() in "aeiou" else "a"
hero_sentence = T["hero_sentence"].format(
    emotion=safe_emotion_name,
    arc=safe_arc_display,
    chunks=n_chunks,
    article=_arc_article,
)

st.markdown(
    f"""
    <div class="bs-hero">
        <div class="bs-hero-title">📖 {safe_title}</div>
        <div class="bs-hero-sentence">{hero_sentence}</div>
        <div class="bs-metrics">
            <div class="bs-metric">
                <div class="bs-metric-label">{T['hero_dominant']}</div>
                <div class="bs-metric-value" style="color:{top_emotion_color};">
                    {top_emotion_icon} {safe_emotion_name}
                </div>
            </div>
            <div class="bs-metric">
                <div class="bs-metric-label">{T['hero_arc']}</div>
                <div class="bs-metric-value" style="color:#a78bfa;">{safe_arc_display}</div>
            </div>
            <div class="bs-metric">
                <div class="bs-metric-label">{T['hero_words']}</div>
                <div class="bs-metric-value">{total_words:,}</div>
            </div>
            <div class="bs-metric">
                <div class="bs-metric-label">{T['hero_chunks']}</div>
                <div class="bs-metric-value">{n_chunks}</div>
            </div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Demo badge + clear button
if _demo_mode and not _from_saved:
    badge_col, clear_col, _ = st.columns([3, 1, 2])
    badge_col.info(T["demo_badge"])
    if clear_col.button(T["loaded_clear"]):
        st.session_state["_demo_mode"] = False
        st.rerun()

# Loaded badge + clear button
if _from_saved:
    badge_col, clear_col, _ = st.columns([2, 1, 3])
    badge_col.info(T["loaded_badge"])
    if clear_col.button(T["loaded_clear"]):
        st.session_state.pop("_loaded_result", None)
        st.rerun()

# Save button (hidden when viewing a saved result)
if not _from_saved:
    repo = Repository()
    save_col, _ = st.columns([1, 5])
    if save_col.button(T["save_btn"]):
        result = AnalysisResult.create(
            book_title=book_title,
            chunk_strategy=strategy,
            total_chunks=n_chunks,
            total_words=total_words,
            arc_pattern=arc.value,
            detected_lang=detected_lang,
            emotion_scores=emotion_scores,
            style_scores=style_scores,
        )
        repo.save(result)
        save_col.success(T["saved_ok"])

# ---------------------------------------------------------------------------
# Mode toggle: Quick Insight | Full Analysis
# ---------------------------------------------------------------------------

view_mode = st.radio(
    "",
    options=["quick", "full"],
    format_func=lambda x: T["mode_quick"] if x == "quick" else T["mode_full"],
    horizontal=True,
    key="view_mode_radio",
    index=0 if ui_mode == "quick" else 1,
)
if view_mode != ui_mode:
    set_mode(view_mode)

# ---------------------------------------------------------------------------
# Quick Insight mode
# ---------------------------------------------------------------------------

if view_mode == "quick":
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
    )

# ---------------------------------------------------------------------------
# Full Analysis mode — 7 tabs
# ---------------------------------------------------------------------------

else:
    (
        tab_overview, tab_heatmap, tab_timeline, tab_style,
        tab_arc, tab_export, tab_chunks,
    ) = st.tabs([
        T["tab_overview"], T["tab_heatmap"], T["tab_timeline"], T["tab_style"],
        T["tab_arc"], T["tab_export"], T["tab_chunks"],
    ])

    with tab_overview:
        render_overview(emotion_scores, T, _EMOTION_FIELDS)

    with tab_heatmap:
        render_heatmap(emotion_scores, chunks, T)

    with tab_timeline:
        render_timeline(emotion_scores, T, _EMOTION_FIELDS)

    with tab_style:
        render_style(style_scores, T)

    with tab_arc:
        render_arc_pattern(emotion_scores, arc, arc_display_name, arc_classifier, T)

    with tab_export:
        render_export(
            book_title, strategy, n_chunks, total_words,
            arc, detected_lang, emotion_scores, style_scores, T,
        )

    with tab_chunks:
        render_chunks(chunks, emotion_scores, style_scores, T)
