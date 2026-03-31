"""BookScope — global CSS injection (v1.0 "Obsidian Minimal" theme)."""

import streamlit as st

_CSS = """
<style>
/* ================================================================
   BookScope  ·  "Obsidian Minimal"  v1.0
   ─────────────────────────────────────────────────────────────────
   #09080d  void background
   #13111f  card surface
   #a78bfa  violet hi (readable)
   #7c3aed  violet lo (borders/indicators)
   #f0ecff  text (faint lavender-white)
   #7a7595  text muted
   #3d3950  text dim (labels)
================================================================ */

/* ── App shell ──────────────────────────────────────────────── */
.stApp,
[data-testid="stAppViewContainer"],
[data-testid="stAppViewBlockContainer"] {
    background: #09080d !important;
}
.block-container {
    background: #09080d !important;
    padding-top: 2rem !important;
}

/* ── Sidebar ────────────────────────────────────────────────── */
[data-testid="stSidebar"],
section[data-testid="stSidebar"],
[data-testid="stSidebar"] > div:first-child {
    background: #0d0b16 !important;
    border-right: 1px solid rgba(255,255,255,.05) !important;
}
[data-testid="stSidebar"] .stMarkdown,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] .stRadio label span,
[data-testid="stSidebar"] .stSelectbox label {
    color: #7a7595 !important;
}

/* ── Tabs ───────────────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {
    background: transparent !important;
    border-bottom: 1px solid rgba(255,255,255,.07) !important;
    gap: 0 !important;
}
.stTabs [data-baseweb="tab"] {
    background: transparent !important;
    color: #3d3950 !important;
    border: none !important;
    padding: .6rem 1.1rem !important;
    font-size: .82rem !important;
    font-weight: 600 !important;
    letter-spacing: .02em !important;
}
.stTabs [aria-selected="true"] {
    color: #a78bfa !important;
    border-bottom: 2px solid #7c3aed !important;
}
.stTabs [data-baseweb="tab"]:hover {
    color: #f0ecff !important;
    background: rgba(167,139,250,.05) !important;
}
.stTabs [data-baseweb="tab-panel"] {
    background: transparent !important;
    padding-top: 1.25rem !important;
}
/* Hide the sliding underline Streamlit draws — we do it ourselves */
.stTabs [data-baseweb="tab-highlight"] {
    display: none !important;
}

/* ── Buttons ────────────────────────────────────────────────── */
.stButton > button {
    background: rgba(124,58,237,.12) !important;
    border: 1px solid rgba(167,139,250,.25) !important;
    color: #a78bfa !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    transition: all .15s !important;
}
.stButton > button:hover {
    background: rgba(124,58,237,.22) !important;
    border-color: rgba(167,139,250,.45) !important;
    color: #f0ecff !important;
}
.stButton > button[kind="primary"] {
    background: #7c3aed !important;
    border-color: #7c3aed !important;
    color: #fff !important;
}
.stButton > button[kind="primary"]:hover {
    background: #6d28d9 !important;
}

/* ── Radio / mode toggle ────────────────────────────────────── */
.stRadio [data-testid="stWidgetLabel"] p {
    color: #3d3950 !important;
    font-size: .75rem !important;
    text-transform: uppercase !important;
    letter-spacing: .1em !important;
}
.stRadio label span { color: #7a7595 !important; font-size: .88rem !important; }
.stRadio label:has(input:checked) span { color: #a78bfa !important; }

/* ── Text inputs ────────────────────────────────────────────── */
.stTextInput input {
    background: #13111f !important;
    border: 1px solid rgba(255,255,255,.08) !important;
    color: #f0ecff !important;
    border-radius: 8px !important;
}
.stTextInput input:focus {
    border-color: rgba(167,139,250,.4) !important;
    box-shadow: 0 0 0 3px rgba(124,58,237,.1) !important;
}
.stTextInput label { color: #7a7595 !important; font-size: .82rem !important; }

/* ── Selectbox ──────────────────────────────────────────────── */
.stSelectbox [data-baseweb="select"] > div:first-child {
    background: #13111f !important;
    border: 1px solid rgba(255,255,255,.08) !important;
    color: #f0ecff !important;
    border-radius: 8px !important;
}

/* ── Expander ───────────────────────────────────────────────── */
.streamlit-expanderHeader {
    background: #13111f !important;
    border: 1px solid rgba(255,255,255,.06) !important;
    border-radius: 8px !important;
    color: #7a7595 !important;
}
.streamlit-expanderContent {
    border: 1px solid rgba(255,255,255,.06) !important;
    border-top: none !important;
    background: #0f0d1b !important;
}

/* ── Plotly charts — match bg ───────────────────────────────── */
.js-plotly-plot .plotly,
.stPlotlyChart {
    background: transparent !important;
}

/* ── Dataframe / table ──────────────────────────────────────── */
[data-testid="stDataFrame"] {
    border: 1px solid rgba(255,255,255,.06) !important;
    border-radius: 8px !important;
    overflow: hidden !important;
}

/* ── Info / success / error alerts ─────────────────────────── */
[data-testid="stAlert"] {
    border-radius: 8px !important;
    border: 1px solid rgba(255,255,255,.07) !important;
}

/* ── Global text ────────────────────────────────────────────── */
p, .stMarkdown p { color: #7a7595; }
h1, h2, h3 { color: #f0ecff !important; letter-spacing: -.02em; }
code {
    background: rgba(167,139,250,.1) !important;
    color: #a78bfa !important;
    border-radius: 4px !important;
}

/* ─────────────────────────────────────────────────────────────
   BookScope custom components
───────────────────────────────────────────────────────────── */

/* ── Hero card ───────────────────────────────────────────────── */
.bs-hero {
    background: #13111f;
    border: 1px solid rgba(255,255,255,.06);
    border-radius: 12px;
    padding: 1.75rem 2rem 2rem;
    margin-bottom: 1.5rem;
    box-shadow:
        0 0 0 1px rgba(0,0,0,.5),
        0 20px 48px rgba(0,0,0,.45);
    animation: bs-card-reveal .5s cubic-bezier(.22,1,.36,1) both;
}
.bs-hero-title {
    font-size: 1.75rem;
    font-weight: 800;
    color: #f0ecff;
    margin: 0 0 .4rem 0;
    line-height: 1.2;
    letter-spacing: -.025em;
}
.bs-hero-sentence {
    font-size: .97rem;
    color: #7a7595;
    margin: 0 0 1.5rem 0;
    line-height: 1.75;
    padding-bottom: 1.25rem;
    border-bottom: 1px solid rgba(255,255,255,.05);
}
.bs-metrics {
    display: flex;
    gap: 0;
    flex-wrap: wrap;
    align-items: flex-end;
}
.bs-metric {
    border-right: 1px solid rgba(255,255,255,.06);
    padding: 0 1.25rem 0 0;
    margin-right: 1.25rem;
    min-width: 80px;
    flex: 0 0 auto;
}
.bs-metric:last-child { border-right: none; margin-right: 0; }
.bs-metric-label {
    font-size: .6rem;
    color: #3d3950;
    text-transform: uppercase;
    letter-spacing: .14em;
    margin-bottom: .25rem;
    font-weight: 700;
}
.bs-metric-value {
    font-size: 1.3rem;
    font-weight: 800;
    color: #f0ecff;
    line-height: 1;
    letter-spacing: -.02em;
}

/* ── Tab description ────────────────────────────────────────── */
.bs-desc { color: #7a7595; font-size: .87rem; margin-bottom: 1rem; line-height: 1.55; }

/* ── Welcome screen ─────────────────────────────────────────── */
.bs-welcome { text-align: center; padding: 4rem 1rem 2.5rem; }
.bs-welcome h2 {
    font-size: 2.1rem; font-weight: 800; color: #f0ecff;
    margin-bottom: .75rem; letter-spacing: -.03em; line-height: 1.1;
}
.bs-welcome p {
    font-size: 1.05rem; color: #7a7595;
    max-width: 440px; margin: 0 auto; line-height: 1.75;
}

/* ── Quick Insight: headline card ───────────────────────────── */
.bs-insight-headline {
    border-radius: 10px;
    padding: 1.4rem 1.6rem;
    margin-bottom: .75rem;
    background: #13111f;
    border: 1px solid rgba(255,255,255,.06);
    border-left: 2px solid var(--bs-type-color, #7c3aed);
}
.bs-insight-headline-label {
    font-size: .6rem; font-weight: 700;
    text-transform: uppercase; letter-spacing: .14em;
    color: #3d3950; margin-bottom: .5rem;
}
.bs-insight-headline-text {
    font-size: 1.2rem; color: #f0ecff; line-height: 1.6; font-weight: 500;
}
.bs-insight-headline-text-animate { animation: bs-typewriter 1.5s steps(50, end) both; }

/* ── Quick Insight: 3-col grid ──────────────────────────────── */
.bs-insight-grid {
    display: grid; grid-template-columns: repeat(3, 1fr);
    gap: .5rem; margin-bottom: .75rem;
}
.bs-insight-card {
    border-radius: 10px; padding: 1.1rem 1.2rem;
    background: #13111f; border: 1px solid rgba(255,255,255,.06);
    position: relative; overflow: hidden; min-height: 160px;
}
.bs-insight-card::before {
    content: ''; position: absolute; top: 0; left: 0;
    width: 100%; height: 2px;
    background: var(--bs-type-color, #7c3aed); opacity: .7;
}
.bs-insight-card-animate { animation: bs-card-reveal .4s cubic-bezier(.22,1,.36,1) both; }
.bs-insight-card-animate:nth-child(2) { animation-delay: .07s; }
.bs-insight-card-animate:nth-child(3) { animation-delay: .14s; }
.bs-no-animate { animation: none !important; }
.bs-insight-card-label {
    font-size: .6rem; font-weight: 700;
    text-transform: uppercase; letter-spacing: .14em;
    color: #3d3950; margin-bottom: .45rem;
}
.bs-insight-card-value {
    font-size: 1.05rem; color: #f0ecff;
    line-height: 1.4; margin-bottom: .3rem; font-weight: 600;
}
.bs-insight-card-sub { font-size: .78rem; color: #7a7595; line-height: 1.45; }

/* ── Tags ───────────────────────────────────────────────────── */
.bs-tag-row { display: flex; flex-wrap: wrap; gap: .3rem; margin-top: .45rem; }
.bs-tag {
    padding: .18rem .6rem; border-radius: 3px;
    font-size: .7rem; font-weight: 600; letter-spacing: .04em;
    background: rgba(167,139,250,.07);
    border: 1px solid rgba(167,139,250,.15);
    color: #7a7595;
}

/* ── For-you card ───────────────────────────────────────────── */
.bs-for-you {
    border-radius: 10px; padding: .9rem 1.2rem; margin-top: .5rem;
    background: rgba(124,58,237,.07);
    border: 1px solid rgba(167,139,250,.15);
    display: flex; align-items: flex-start; gap: .75rem;
}
.bs-for-you-icon { font-size: 1.2rem; flex-shrink: 0; margin-top: .05rem; }
.bs-for-you-text { font-size: .87rem; color: #b0a8c8; line-height: 1.65; }
.bs-for-you-text strong { color: #a78bfa; font-weight: 700; }

/* ── Animations ─────────────────────────────────────────────── */
@keyframes bs-card-reveal {
    from { opacity: 0; transform: translateY(8px); }
    to   { opacity: 1; transform: translateY(0); }
}
@keyframes bs-typewriter {
    from { clip-path: inset(0 100% 0 0); }
    to   { clip-path: inset(0 0% 0 0); }
}
</style>
"""


def inject_css() -> None:
    """Inject BookScope global CSS into the Streamlit page."""
    st.markdown(_CSS, unsafe_allow_html=True)
