"""Shared UI utilities for BookScope pages.

Language and mode persistence via st.query_params + session_state.
Google Fonts injection to override OS system fonts.

Import with:
    from bookscope.app_utils import get_lang, set_lang, get_mode, set_mode, inject_fonts
"""

import streamlit as st

SUPPORTED_LANGS = ("en", "zh", "ja")
SUPPORTED_MODES = ("quick", "full")
SUPPORTED_TYPES = ("fiction", "academic", "essay")


def get_lang() -> str:
    """URL ?lang=xx → session_state → default 'en'."""
    raw = st.query_params.get("lang", "")
    if raw in SUPPORTED_LANGS:
        st.session_state["ui_lang"] = raw
        return raw
    return st.session_state.get("ui_lang", "en")


def set_lang(lang: str) -> None:
    st.session_state["ui_lang"] = lang
    st.query_params["lang"] = lang


def get_mode() -> str:
    """URL ?mode=xx → session_state → default 'quick'."""
    raw = st.query_params.get("mode", "")
    if raw in SUPPORTED_MODES:
        st.session_state["ui_mode"] = raw
        return raw
    return st.session_state.get("ui_mode", "quick")


def set_mode(mode: str) -> None:
    st.session_state["ui_mode"] = mode
    st.query_params["mode"] = mode


# ── Font configuration ───────────────────────────────────────────────────────

_IMPORT = {
    "en": "Instrument+Serif:wght@400;700&family=Inter:wght@400;500;600;700",
    "zh": "Noto+Serif+SC:wght@400;700&family=Noto+Sans+SC:wght@400;500;700",
    "ja": "Noto+Serif+JP:wght@400;700&family=Noto+Sans+JP:wght@400;500;700",
}
_HEADING = {
    "en": "'Instrument Serif', Georgia, 'Times New Roman', serif",
    "zh": "'Noto Serif SC', 'STSong', 'SimSun', serif",
    "ja": "'Noto Serif JP', 'Hiragino Mincho Pro', 'Yu Mincho', serif",
}
_BODY = {
    "en": "'Inter', -apple-system, 'Segoe UI', sans-serif",
    "zh": "'Noto Sans SC', 'PingFang SC', 'Microsoft YaHei', sans-serif",
    "ja": "'Noto Sans JP', 'Hiragino Kaku Gothic ProN', 'Meiryo', sans-serif",
}


def inject_fonts(lang: str) -> None:
    """Inject language-specific Google Fonts, overriding OS system fonts."""
    url = (
        "https://fonts.googleapis.com/css2?family="
        + _IMPORT.get(lang, _IMPORT["en"])
        + "&display=swap"
    )
    hf = _HEADING.get(lang, _HEADING["en"])
    bf = _BODY.get(lang, _BODY["en"])
    st.markdown(
        f"""<style>
@import url('{url}');
html, body, .stApp, .stApp * {{ font-family: {bf} !important; }}
.stApp h1, .stApp h2, .stApp h3,
.stApp .bs-hero-title, .stApp .bs-insight-headline-text {{
    font-family: {hf} !important;
}}
/* Restore Material Symbols Rounded for Streamlit icon spans.
   Streamlit renders icons as text ligatures (e.g. "keyboard_arrow_right")
   inside spans with font-family "Material Symbols Rounded".
   The wildcard rule above overrides that font, breaking icon rendering.
   The static emotion class ejhh0er0 identifies these icon spans. */
.stApp .ejhh0er0 {{
    font-family: "Material Symbols Rounded" !important;
    font-variation-settings: 'FILL' 0, 'wght' 400, 'GRAD' 0, 'opsz' 24 !important;
}}
</style>""",
        unsafe_allow_html=True,
    )
