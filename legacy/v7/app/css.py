"""BookScope — global CSS injection (v2.0 "Paper & Ink" theme)."""

import streamlit as st

_CSS = """
<style>
@import url('https://fonts.loli.net/css2?family=Playfair+Display:wght@400;600;700;800&family=Source+Serif+4:ital,wght@0,300;0,400;0,600;1,300;1,400&display=swap');

/* ================================================================
   BookScope  ·  "Paper & Ink"  v2.0
   ─────────────────────────────────────────────────────────────────
   #FAF7F2  cream background
   #FFFFFF  card surface
   #1C1208  warm ink (primary text)
   #C8781A  amber accent
   #7A6A5A  text muted
   #B8A898  text dim (labels)
   #F4F0E8  secondary surface / sidebar
   #E8E0D4  border / divider
================================================================ */

/* ── Option C: Hide sidebar & toggle ────────────────────────── */
[data-testid="stSidebar"],
[data-testid="collapsedControl"],
[data-testid="baseButton-headerNoPadding"],
[data-testid="stExpandSidebarButton"] {
    display: none !important;
}

/* ── Topnav language radio — no-wrap ────────────────────────── */
.bs-topnav-lang [role="radiogroup"],
.stRadio [role="radiogroup"] {
    flex-wrap: nowrap !important;
    gap: .25rem !important;
}
.stRadio [role="radiogroup"] label {
    white-space: nowrap !important;
}

/* ── App shell ──────────────────────────────────────────────── */
.stApp,
[data-testid="stAppViewContainer"],
[data-testid="stAppViewBlockContainer"] {
    background: #FAF7F2 !important;
    font-family: 'Source Serif 4', Georgia, serif !important;
}
.block-container {
    background: #FAF7F2 !important;
    padding-top: 1.25rem !important;
    max-width: 1100px !important;
}

/* ── Topnav logo ─────────────────────────────────────────────── */
.bs-topnav-logo {
    font-family: 'Source Serif 4', Georgia, serif;
    font-size: 0.75rem;
    font-weight: 700;
    color: #B8A898;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    padding: .35rem 0;
    display: block;
}

/* ── Global text ────────────────────────────────────────────── */
p, .stMarkdown p {
    color: #7A6A5A !important;
    font-family: 'Source Serif 4', Georgia, serif !important;
}
h1, h2, h3 {
    color: #1C1208 !important;
    font-family: 'Playfair Display', Georgia, serif !important;
    letter-spacing: -.02em;
}
code {
    background: rgba(200,120,26,.08) !important;
    color: #C8781A !important;
    border-radius: 3px !important;
    font-family: 'Courier New', monospace !important;
}
label, .stMarkdown {
    color: #7A6A5A !important;
    font-family: 'Source Serif 4', Georgia, serif !important;
}

/* ── Sidebar ────────────────────────────────────────────────── */
[data-testid="stSidebar"],
section[data-testid="stSidebar"],
[data-testid="stSidebar"] > div:first-child {
    background: #F4F0E8 !important;
    border-right: 1px solid #E8E0D4 !important;
}
[data-testid="stSidebar"] .stMarkdown,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] .stRadio label span,
[data-testid="stSidebar"] .stSelectbox label {
    color: #7A6A5A !important;
}

/* ── Tabs ───────────────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {
    background: transparent !important;
    border-bottom: 1px solid #E8E0D4 !important;
    gap: 0 !important;
}
.stTabs [data-baseweb="tab"] {
    background: transparent !important;
    color: #B8A898 !important;
    border: none !important;
    padding: .6rem 1.1rem !important;
    font-size: .82rem !important;
    font-weight: 600 !important;
    letter-spacing: .02em !important;
    font-family: 'Source Serif 4', Georgia, serif !important;
}
.stTabs [aria-selected="true"] {
    color: #C8781A !important;
    border-bottom: 2px solid #C8781A !important;
}
.stTabs [data-baseweb="tab"]:hover {
    color: #1C1208 !important;
    background: rgba(200,120,26,.05) !important;
}
.stTabs [data-baseweb="tab-panel"] {
    background: transparent !important;
    padding-top: 1.25rem !important;
}
.stTabs [data-baseweb="tab-highlight"] {
    display: none !important;
}

/* ── Buttons ────────────────────────────────────────────────── */
.stButton > button {
    background: rgba(200,120,26,.07) !important;
    border: 1px solid rgba(200,120,26,.3) !important;
    color: #C8781A !important;
    border-radius: 6px !important;
    font-weight: 600 !important;
    font-family: 'Source Serif 4', Georgia, serif !important;
    transition: all .15s !important;
}
.stButton > button:hover {
    background: rgba(200,120,26,.14) !important;
    border-color: rgba(200,120,26,.5) !important;
    color: #8C4E08 !important;
}
.stButton > button[kind="primary"] {
    background: #C8781A !important;
    border-color: #C8781A !important;
    color: #fff !important;
}
.stButton > button[kind="primary"]:hover {
    background: #A8600E !important;
}

/* ── Radio / mode toggle ────────────────────────────────────── */
.stRadio [data-testid="stWidgetLabel"] p {
    color: #B8A898 !important;
    font-size: .75rem !important;
    text-transform: uppercase !important;
    letter-spacing: .1em !important;
}
.stRadio label span { color: #7A6A5A !important; font-size: .88rem !important; }
.stRadio label:has(input:checked) span { color: #C8781A !important; }

/* ── Text inputs ────────────────────────────────────────────── */
.stTextInput input {
    background: #FFFFFF !important;
    border: 1px solid #E8E0D4 !important;
    color: #1C1208 !important;
    border-radius: 6px !important;
    font-family: 'Source Serif 4', Georgia, serif !important;
}
.stTextInput input:focus {
    border-color: rgba(200,120,26,.5) !important;
    box-shadow: 0 0 0 3px rgba(200,120,26,.1) !important;
}
.stTextInput label { color: #7A6A5A !important; font-size: .82rem !important; }

/* ── Selectbox ──────────────────────────────────────────────── */
.stSelectbox [data-baseweb="select"] > div:first-child {
    background: #FFFFFF !important;
    border: 1px solid #E8E0D4 !important;
    color: #1C1208 !important;
    border-radius: 6px !important;
}

/* ── Expander ───────────────────────────────────────────────── */
.streamlit-expanderHeader {
    background: #FFFFFF !important;
    border: 1px solid #E8E0D4 !important;
    border-radius: 6px !important;
    color: #7A6A5A !important;
}
.streamlit-expanderContent {
    border: 1px solid #E8E0D4 !important;
    border-top: none !important;
    background: #FDFBF8 !important;
}

/* ── Plotly charts — match bg ───────────────────────────────── */
.js-plotly-plot .plotly,
.stPlotlyChart {
    background: transparent !important;
}

/* ── Dataframe / table ──────────────────────────────────────── */
[data-testid="stDataFrame"] {
    border: 1px solid #E8E0D4 !important;
    border-radius: 6px !important;
    overflow: hidden !important;
}

/* ── Info / success / error alerts ─────────────────────────── */
[data-testid="stAlert"] {
    border-radius: 6px !important;
    border: 1px solid #E8E0D4 !important;
}

/* ── Divider ────────────────────────────────────────────────── */
hr {
    border-color: #E8E0D4 !important;
}

/* ─────────────────────────────────────────────────────────────
   BookScope custom components
───────────────────────────────────────────────────────────── */

/* ── Hero card ───────────────────────────────────────────────── */
.bs-hero {
    background: #FFFFFF;
    border: 1px solid #E8E0D4;
    border-radius: 10px;
    padding: 1.75rem 2rem 2rem;
    margin-bottom: 1.5rem;
    box-shadow: 0 2px 12px rgba(28,18,8,.07), 0 1px 3px rgba(28,18,8,.05);
}
.bs-hero-title {
    font-family: 'Playfair Display', Georgia, serif;
    font-size: 1.75rem;
    font-weight: 700;
    color: #1C1208;
    margin: 0 0 .4rem 0;
    line-height: 1.2;
    letter-spacing: -.025em;
}
.bs-hero-sentence {
    font-family: 'Source Serif 4', Georgia, serif;
    font-size: .97rem;
    color: #7A6A5A;
    margin: 0 0 1.5rem 0;
    line-height: 1.75;
    padding-bottom: 1.25rem;
    border-bottom: 1px solid #E8E0D4;
}
.bs-metrics {
    display: flex;
    gap: 0;
    flex-wrap: wrap;
    align-items: flex-end;
}
.bs-metric {
    border-right: 1px solid #E8E0D4;
    padding: 0 1.25rem 0 0;
    margin-right: 1.25rem;
    min-width: 80px;
    flex: 0 0 auto;
}
.bs-metric:last-child { border-right: none; margin-right: 0; }
.bs-metric-label {
    font-size: .6rem;
    color: #B8A898;
    text-transform: uppercase;
    letter-spacing: .14em;
    margin-bottom: .25rem;
    font-weight: 700;
    font-family: 'Source Serif 4', Georgia, serif;
}
.bs-metric-value {
    font-family: 'Playfair Display', Georgia, serif;
    font-size: 1.3rem;
    font-weight: 700;
    color: #1C1208;
    line-height: 1;
    letter-spacing: -.02em;
}

/* ── Tab description ────────────────────────────────────────── */
.bs-desc {
    color: #7A6A5A;
    font-size: .87rem;
    margin-bottom: 1rem;
    line-height: 1.55;
    font-family: 'Source Serif 4', Georgia, serif;
}

/* ── Welcome screen ─────────────────────────────────────────── */
.bs-welcome { text-align: center; padding: 4rem 1rem 2.5rem; }
.bs-welcome h2 {
    font-family: 'Playfair Display', Georgia, serif;
    font-size: 2.1rem; font-weight: 800; color: #1C1208;
    margin-bottom: .75rem; letter-spacing: -.03em; line-height: 1.1;
}
.bs-welcome p {
    font-family: 'Source Serif 4', Georgia, serif;
    font-size: 1.05rem; color: #7A6A5A;
    max-width: 440px; margin: 0 auto; line-height: 1.75;
}

/* ── Quick Insight: headline card ───────────────────────────── */
.bs-insight-headline {
    border-radius: 8px;
    padding: 1.2rem 1.5rem;
    margin-bottom: .75rem;
    background: #FFFFFF;
    border: 1px solid #E8E0D4;
    border-left: 3px solid var(--bs-type-color, #C8781A);
    box-shadow: 0 1px 4px rgba(28,18,8,.05);
}
.bs-insight-headline-label {
    font-size: .6rem; font-weight: 700;
    text-transform: uppercase; letter-spacing: .14em;
    color: #B8A898; margin-bottom: .5rem;
    font-family: 'Source Serif 4', Georgia, serif;
}
.bs-insight-headline-text {
    font-family: 'Playfair Display', Georgia, serif;
    font-size: 1.15rem; color: #1C1208; line-height: 1.6; font-weight: 600;
}
.bs-insight-headline-text-animate { animation: bs-typewriter 1.5s steps(50, end) both; }

/* ── Quick Insight: card grid ───────────────────────────────── */
.bs-insight-grid {
    display: grid; grid-template-columns: 1fr;
    gap: .6rem; margin-bottom: .75rem;
}
.bs-insight-card {
    border-radius: 8px; padding: 1rem 1.25rem;
    background: #FFFFFF; border: 1px solid #E8E0D4;
    box-shadow: 0 1px 4px rgba(28,18,8,.04);
    position: relative; overflow: hidden;
}
.bs-insight-card::before {
    content: ''; position: absolute; top: 0; left: 0;
    width: 100%; height: 2px;
    background: var(--bs-type-color, #C8781A); opacity: .6;
}
.bs-insight-card-animate { animation: bs-card-reveal .4s cubic-bezier(.22,1,.36,1) both; }
.bs-insight-card-animate:nth-child(2) { animation-delay: .07s; }
.bs-insight-card-animate:nth-child(3) { animation-delay: .14s; }
.bs-no-animate { animation: none !important; }
.bs-insight-card-label {
    font-size: .6rem; font-weight: 700;
    text-transform: uppercase; letter-spacing: .14em;
    color: #B8A898; margin-bottom: .45rem;
    font-family: 'Source Serif 4', Georgia, serif;
}
.bs-insight-card-value {
    font-family: 'Playfair Display', Georgia, serif;
    font-size: 1.1rem; color: #1C1208;
    line-height: 1.4; margin-bottom: .3rem; font-weight: 600;
}
.bs-insight-card-sub {
    font-family: 'Source Serif 4', Georgia, serif;
    font-size: .82rem; color: #7A6A5A; line-height: 1.5;
}

/* ── Tags ───────────────────────────────────────────────────── */
.bs-tag-row { display: flex; flex-wrap: wrap; gap: .3rem; margin-top: .45rem; }
.bs-tag {
    padding: .2rem .65rem; border-radius: 3px;
    font-size: .7rem; font-weight: 600; letter-spacing: .03em;
    background: rgba(200,120,26,.06);
    border: 1px solid rgba(200,120,26,.2);
    color: #7A6A5A;
    font-family: 'Source Serif 4', Georgia, serif;
}

/* ── For-you card ───────────────────────────────────────────── */
.bs-for-you {
    border-radius: 8px; padding: .9rem 1.2rem; margin-top: .5rem;
    background: rgba(200,120,26,.05);
    border: 1px solid rgba(200,120,26,.2);
    display: flex; align-items: flex-start; gap: .75rem;
}
.bs-for-you-icon { font-size: 1.2rem; flex-shrink: 0; margin-top: .05rem; }
.bs-for-you-text {
    font-family: 'Source Serif 4', Georgia, serif;
    font-size: .87rem; color: #5A4A3A; line-height: 1.65;
}
.bs-for-you-text strong { color: #C8781A; font-weight: 700; }

/* ── Animations ─────────────────────────────────────────────── */
@keyframes bs-card-reveal {
    from { opacity: 0; transform: translateY(6px); }
    to   { opacity: 1; transform: translateY(0); }
}
@keyframes bs-typewriter {
    from { clip-path: inset(0 100% 0 0); }
    to   { clip-path: inset(0 0% 0 0); }
}

/* ── Typography scale (5 layers) ──────────────────────────────── */
/* L1 — book title */
.bs-hero-title { font-size: 24px; font-weight: 700; line-height: 1.2; }
/* L2 — section labels */
.bs-insight-headline-label {
    font-size: 11px; font-weight: 700;
    letter-spacing: 0.1em; text-transform: uppercase;
}
/* L3 — core content (verdict sentence) */
.bs-verdict-sentence {
    font-family: 'Source Serif 4', Georgia, serif;
    font-size: 15px; font-weight: 400; line-height: 1.7; color: #3A2A1A;
}
/* L3.5 — card body data */
.bs-card-body {
    font-family: 'Source Serif 4', Georgia, serif;
    font-size: 14px; font-weight: 400; line-height: 1.5;
}
/* L4 — auxiliary notes */
.bs-verdict-sub {
    font-family: 'Source Serif 4', Georgia, serif;
    font-size: 11px; color: #B8A898; line-height: 1.4;
}

/* ── Identity Bar (slim title header replacing hero card) ───────── */
.bs-identity-bar {
    padding: 1.25rem 0 1rem;
    border-bottom: 1px solid #E8E0D4;
    margin-bottom: 1.25rem;
}
.bs-identity-title {
    font-family: 'Playfair Display', Georgia, serif;
    font-size: 22px;
    font-weight: 700;
    color: #1C1208;
    line-height: 1.2;
    margin-bottom: .3rem;
}
.bs-identity-meta {
    font-family: 'Source Serif 4', Georgia, serif;
    font-size: 13px;
    color: #B8A898;
    letter-spacing: .01em;
}

/* ── Reader Verdict card ────────────────────────────────────────── */
.bs-verdict-card {
    border-left: 4px solid #C8781A;
    background: rgba(200,120,26,.05);
    border-radius: 0 8px 8px 0;
    padding: 1.1rem 1.4rem;
    margin-bottom: 1.25rem;
    box-shadow: 0 1px 4px rgba(28,18,8,.05);
}
.bs-verdict-for-you {
    font-family: 'Playfair Display', Georgia, serif;
    font-size: 15px;
    font-weight: 600;
    color: #8C4E08;
    margin-bottom: 0.35rem;
}
.bs-verdict-not-for-you {
    font-family: 'Source Serif 4', Georgia, serif;
    font-size: 13px;
    color: #B8A898;
    margin-top: 0.4rem;
}
</style>
"""


def inject_css() -> None:
    """Inject BookScope global CSS into the Streamlit page."""
    st.markdown(_CSS, unsafe_allow_html=True)
