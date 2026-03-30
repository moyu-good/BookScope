"""BookScope — global CSS injection."""

import streamlit as st

_CSS = """
<style>
/* ── Hero card ── */
.bs-hero {
    background: linear-gradient(135deg, #1a0b3d 0%, #0d1b2a 100%);
    border: 1px solid #4c1d95;
    border-radius: 16px;
    padding: 1.75rem 2rem;
    margin-bottom: 1.5rem;
    animation: bs-card-reveal .5s cubic-bezier(.22,1,.36,1) both;
}
.bs-hero-title {
    font-size: 1.7rem;
    font-weight: 700;
    color: #f8fafc;
    margin: 0 0 0.6rem 0;
    line-height: 1.3;
}
.bs-hero-sentence {
    font-size: 1.05rem;
    color: #cbd5e1;
    margin: 0 0 1.4rem 0;
    line-height: 1.7;
}
.bs-metrics {
    display: flex;
    gap: 0.75rem;
    flex-wrap: wrap;
}
.bs-metric {
    background: rgba(255,255,255,0.07);
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 12px;
    padding: 0.65rem 1.1rem;
    min-width: 110px;
    flex: 1 1 110px;
    max-width: 180px;
}
.bs-metric-label {
    font-size: 0.7rem;
    color: #94a3b8;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 0.3rem;
}
.bs-metric-value {
    font-size: 1.15rem;
    font-weight: 700;
    color: #f1f5f9;
    line-height: 1.2;
}
/* ── Tab description helper text ── */
.bs-desc {
    color: #94a3b8;
    font-size: 0.88rem;
    margin-bottom: 1rem;
    line-height: 1.5;
}
/* ── Welcome screen ── */
.bs-welcome {
    text-align: center;
    padding: 3rem 1rem 2rem;
}
.bs-welcome h2 {
    font-size: 2rem;
    font-weight: 700;
    color: #f1f5f9;
    margin-bottom: 0.75rem;
}
.bs-welcome p {
    font-size: 1.1rem;
    color: #94a3b8;
    max-width: 480px;
    margin: 0 auto;
    line-height: 1.7;
}
/* ── Quick Insight: headline card ── */
.bs-insight-headline {
    border-radius: 14px;
    padding: 1.5rem 1.75rem;
    margin-bottom: 1rem;
    border-top: 1px solid rgba(255,255,255,0.08);
    border-right: 1px solid rgba(255,255,255,0.08);
    border-bottom: 1px solid rgba(255,255,255,0.08);
    background: rgba(255,255,255,0.04);
}
.bs-insight-headline-label {
    font-size: .7rem;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: .1em;
    color: #64748b;
    margin-bottom: .5rem;
}
.bs-insight-headline-text {
    font-size: 1.3rem;
    color: #e6edf3;
    line-height: 1.55;
}
.bs-insight-headline-text-animate {
    animation: bs-typewriter 1.2s steps(40,end) both;
}
/* ── Quick Insight: 3-col grid ── */
.bs-insight-grid {
    display: grid;
    grid-template-columns: repeat(3,1fr);
    gap: .75rem;
    margin-bottom: 1rem;
}
.bs-insight-card {
    border-radius: 12px;
    padding: 1.1rem 1.25rem;
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.08);
    position: relative;
    overflow: hidden;
    min-height: 160px;
}
.bs-insight-card::before {
    content:'';
    position:absolute;
    top:0; left:0;
    width:100%; height:2px;
    background: var(--bs-type-color, #7c3aed);
    opacity:.6;
}
.bs-insight-card-animate {
    animation: bs-card-reveal .4s cubic-bezier(.22,1,.36,1) both;
}
.bs-insight-card-animate:nth-child(2) { animation-delay:.07s; }
.bs-insight-card-animate:nth-child(3) { animation-delay:.14s; }
.bs-no-animate { animation: none !important; }
.bs-insight-card-label {
    font-size:.68rem;
    font-weight:500;
    text-transform:uppercase;
    letter-spacing:.1em;
    color:#64748b;
    margin-bottom:.4rem;
}
.bs-insight-card-value {
    font-size:1.05rem;
    color:#e6edf3;
    line-height:1.4;
    margin-bottom:.3rem;
}
.bs-insight-card-sub {
    font-size:.8rem;
    color:#94a3b8;
    line-height:1.4;
}
/* ── Tags ── */
.bs-tag-row { display:flex; flex-wrap:wrap; gap:.35rem; margin-top:.4rem; }
.bs-tag {
    padding:.2rem .65rem;
    border-radius:999px;
    font-size:.75rem;
    font-weight:500;
    background:rgba(255,255,255,0.07);
    border:1px solid rgba(255,255,255,0.12);
    color:#94a3b8;
}
/* ── For-you recommendation card ── */
.bs-for-you {
    border-radius:12px;
    padding:1rem 1.25rem;
    margin-top:.5rem;
    background:linear-gradient(90deg,rgba(124,58,237,.12) 0%,rgba(255,255,255,.03) 100%);
    border:1px solid rgba(124,58,237,.25);
    display:flex;
    align-items:flex-start;
    gap:.75rem;
}
.bs-for-you-icon { font-size:1.3rem; flex-shrink:0; margin-top:.1rem; }
.bs-for-you-text { font-size:.9rem; color:#cbd5e1; line-height:1.6; }
.bs-for-you-text strong { color:#a78bfa; }
/* ── Animations ── */
@keyframes bs-card-reveal {
    from { opacity:0; transform:translateY(10px); }
    to   { opacity:1; transform:translateY(0); }
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
