"""BookScope — Streamlit entry point.

Run with:
    streamlit run app/main.py
"""

# Bootstrap NLTK corpora before any NLP imports (safe no-op if already present)
from bookscope.utils import ensure_nltk_data

ensure_nltk_data()

import streamlit as st  # noqa: E402

from bookscope.models import EmotionScore  # noqa: E402
from bookscope.nlp import ArcClassifier, LexiconAnalyzer, StyleAnalyzer, detect_language  # noqa: E402
from bookscope.store import AnalysisResult, Repository  # noqa: E402
from bookscope.viz import (  # noqa: E402
    ChartDataAdapter,
    EmotionHeatmapRenderer,
    EmotionTimelineRenderer,
    StyleRadarRenderer,
)

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="BookScope",
    page_icon="📖",
    layout="wide",
    initial_sidebar_state="expanded",
)

_EMOTION_FIELDS = (
    "anger", "anticipation", "disgust", "fear",
    "joy", "sadness", "surprise", "trust",
)

# ---------------------------------------------------------------------------
# Analysis pipeline
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def run_analysis(
    file_bytes: bytes,
    filename: str,
    strategy: str,
    chunk_size: int,
    min_words: int,
):
    """Load → clean → chunk → emotion + style analysis."""
    import os
    import tempfile

    from bookscope.ingest import chunk
    from bookscope.ingest.loader import load_text

    suffix = "." + filename.rsplit(".", 1)[-1] if "." in filename else ".txt"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        book = load_text(tmp_path, title=filename.removesuffix(".txt").removesuffix(".epub"))
    finally:
        os.unlink(tmp_path)

    # Detect language and attach to book
    lang = detect_language(book.raw_text)
    book = book.model_copy(update={"language": lang})

    chunks = chunk(book, strategy=strategy, word_limit=chunk_size, min_words=min_words)

    emotion_scores = LexiconAnalyzer(language=lang).analyze_book(chunks)
    style_scores = StyleAnalyzer(language=lang).analyze_book(chunks)

    return chunks, emotion_scores, style_scores, lang


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("BookScope")
    st.caption("Emotion arc & style analysis for long-form text")

    uploaded = st.file_uploader("Upload a .txt or .epub file", type=["txt", "epub"])

    st.divider()
    st.subheader("Chunking options")
    strategy = st.radio("Strategy", ["paragraph", "fixed"], index=0)
    chunk_size = st.slider(
        "Fixed chunk size (words)", 100, 1000, 300, step=50,
        disabled=(strategy != "fixed"),
    )
    min_words = st.slider("Min words per chunk", 10, 200, 50, step=10)

    st.divider()
    st.subheader("Saved analyses")
    repo = Repository()
    saved = repo.list_results()
    if saved:
        for p in saved[:5]:
            col1, col2 = st.columns([3, 1])
            col1.caption(p.stem)
            if col2.button("🗑", key=f"del_{p.name}", help="Delete"):
                repo.delete(p)
                st.rerun()
    else:
        st.caption("No saved analyses yet.")

# ---------------------------------------------------------------------------
# Main area
# ---------------------------------------------------------------------------

st.title("BookScope")

if uploaded is None:
    st.info("Upload a .txt or .epub book file using the sidebar to get started.")
    st.stop()

with st.spinner("Analysing…"):
    file_bytes = uploaded.read()
    chunks, emotion_scores, style_scores, detected_lang = run_analysis(
        file_bytes, uploaded.name, strategy, chunk_size, min_words,
    )

if not chunks:
    st.warning("No chunks were produced. Try lowering the minimum word count.")
    st.stop()

# Show detected language in sidebar
_LANG_LABELS = {"en": "🇬🇧 English", "zh": "🇨🇳 Chinese", "ja": "🇯🇵 Japanese"}
with st.sidebar:
    st.divider()
    st.caption(f"Detected language: **{_LANG_LABELS.get(detected_lang, detected_lang)}**")

# Arc classification (fast — no caching needed)
arc_classifier = ArcClassifier()
arc = arc_classifier.classify(emotion_scores)

# ---------------------------------------------------------------------------
# Save button (top right)
# ---------------------------------------------------------------------------

save_col, _ = st.columns([1, 4])
if save_col.button("💾 Save analysis"):
    total_words = sum(c.word_count for c in chunks)
    result = AnalysisResult.create(
        book_title=uploaded.name.removesuffix(".txt"),
        chunk_strategy=strategy,
        total_chunks=len(chunks),
        total_words=total_words,
        arc_pattern=arc.value,
        emotion_scores=emotion_scores,
        style_scores=style_scores,
    )
    saved_path = repo.save(result)
    st.success(f"Saved to `{saved_path.name}`")

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

tab_overview, tab_heatmap, tab_timeline, tab_style, tab_arc, tab_export, tab_chunks = st.tabs(
    ["Overview", "Heatmap", "Emotion Timeline", "Style", "Arc Pattern", "Export", "Chunks"]
)

# --- Overview ---------------------------------------------------------------
with tab_overview:
    total_words = sum(c.word_count for c in chunks)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Chunks", len(chunks))
    c2.metric("Total words", f"{total_words:,}")
    c3.metric("Avg words/chunk", f"{total_words // max(len(chunks), 1):,}")
    c4.metric("Arc pattern", arc.value)

    if emotion_scores:
        from collections import Counter

        dominants = Counter(s.dominant_emotion for s in emotion_scores)
        top_emotion, top_count = dominants.most_common(1)[0]
        st.markdown(
            f"**Dominant emotion:** `{top_emotion.capitalize()}` "
            f"({top_count} / {len(emotion_scores)} chunks)"
        )

        avg_data = {
            e: round(sum(getattr(s, e) for s in emotion_scores) / len(emotion_scores), 4)
            for e in _EMOTION_FIELDS
        }
        st.subheader("Average emotion scores")
        st.bar_chart(dict(sorted(avg_data.items(), key=lambda kv: kv[1], reverse=True)))

# --- Heatmap ----------------------------------------------------------------
with tab_heatmap:
    st.subheader("Emotion intensity across chunks")
    heatmap_data = ChartDataAdapter.emotion_heatmap(emotion_scores, chunks=chunks)
    fig_heatmap = EmotionHeatmapRenderer().render(heatmap_data)
    st.plotly_chart(fig_heatmap, use_container_width=True)
    st.caption("Color: score intensity 0 (cool/green) → 1 (warm/red)")

# --- Emotion Timeline -------------------------------------------------------
with tab_timeline:
    st.subheader("Emotion arc across chunks")

    selected = st.multiselect(
        "Emotions to display",
        options=list(_EMOTION_FIELDS),
        default=list(_EMOTION_FIELDS),
        format_func=str.capitalize,
        key="timeline_emotions",
    )

    if selected:
        filtered = [
            EmotionScore(chunk_index=s.chunk_index, **{e: getattr(s, e) for e in selected})
            for s in emotion_scores
        ]
        timeline_data = ChartDataAdapter.emotion_timeline(filtered)
        timeline_data.emotions = {k: v for k, v in timeline_data.emotions.items() if k in selected}
        st.plotly_chart(EmotionTimelineRenderer().render(timeline_data), use_container_width=True)
    else:
        st.info("Select at least one emotion above.")

# --- Style ------------------------------------------------------------------
with tab_style:
    st.subheader("Style fingerprint")

    if style_scores:
        radar_data = ChartDataAdapter.style_radar(style_scores)
        st.plotly_chart(StyleRadarRenderer().render(radar_data), use_container_width=True)

        st.subheader("Raw averages")
        cols = st.columns(3)
        for i, (metric, val) in enumerate(radar_data.raw_means.items()):
            cols[i % 3].metric(metric.replace("_", " ").title(), f"{val:.3f}")

        st.subheader("Metric over time")
        style_field = st.selectbox(
            "Metric",
            options=list(radar_data.raw_means.keys()),
            format_func=lambda k: k.replace("_", " ").title(),
        )
        st.line_chart({s.chunk_index: getattr(s, style_field) for s in style_scores})
    else:
        st.info("No style data available.")

# --- Arc Pattern ------------------------------------------------------------
with tab_arc:
    st.subheader("Emotional arc pattern")

    if len(emotion_scores) >= 6:
        arc_descriptions = {
            "Rags to Riches": "Sustained emotional rise — builds toward positivity.",
            "Riches to Rags": "Sustained emotional fall — increasing tension and negativity.",
            "Man in a Hole": "Fall then recovery — protagonist hits bottom and rebounds.",
            "Icarus": "Rise then fall — success followed by tragedy.",
            "Cinderella": "Rise → fall → rise — hope, setback, and ultimate redemption.",
            "Oedipus": "Fall → rise → fall — brief hope sandwiched between tragedy.",
            "Unknown": "Not enough data to classify the arc.",
        }

        st.metric("Detected pattern", arc.value)
        st.write(arc_descriptions.get(arc.value, ""))

        valences = arc_classifier.valence_series(emotion_scores)
        st.subheader("Valence over time")
        st.caption("(joy + anticipation + trust) − (anger + fear + sadness + disgust)")
        st.line_chart({i: v for i, v in enumerate(valences)})
    else:
        st.info("Upload a longer text for arc classification (need ≥ 6 chunks).")

# --- Export -----------------------------------------------------------------
with tab_export:
    st.subheader("Download analysis results")

    total_words = sum(c.word_count for c in chunks)
    result = AnalysisResult.create(
        book_title=uploaded.name.removesuffix(".txt"),
        chunk_strategy=strategy,
        total_chunks=len(chunks),
        total_words=total_words,
        arc_pattern=arc.value,
        emotion_scores=emotion_scores,
        style_scores=style_scores,
    )

    col_e, col_s, col_j, col_md = st.columns(4)

    col_e.download_button(
        label="📥 Emotion scores (.csv)",
        data=result.to_csv_emotion(),
        file_name=f"{result.book_title}_emotions.csv",
        mime="text/csv",
    )

    col_s.download_button(
        label="📥 Style scores (.csv)",
        data=result.to_csv_style(),
        file_name=f"{result.book_title}_style.csv",
        mime="text/csv",
    )

    col_j.download_button(
        label="📥 Full analysis (.json)",
        data=result.model_dump_json(indent=2),
        file_name=f"{result.book_title}_analysis.json",
        mime="application/json",
    )

    col_md.download_button(
        label="📥 Report (.md)",
        data=result.to_markdown_report(),
        file_name=f"{result.book_title}_report.md",
        mime="text/markdown",
    )

# --- Chunks -----------------------------------------------------------------
with tab_chunks:
    st.subheader("Chunk explorer")

    if not emotion_scores:
        st.info("No scores to display.")
    else:
        chunk_idx = st.slider("Chunk index", 0, len(chunks) - 1, 0)
        sel_chunk = chunks[chunk_idx]
        sel_emotion = next((s for s in emotion_scores if s.chunk_index == chunk_idx), None)
        sel_style = next((s for s in style_scores if s.chunk_index == chunk_idx), None)

        st.markdown(f"**Chunk {chunk_idx}** — {sel_chunk.word_count} words")

        col_e, col_s = st.columns(2)

        with col_e:
            st.markdown("**Emotion scores**")
            if sel_emotion:
                score_dict = {k: v for k, v in sel_emotion.to_dict().items() if v > 0}
                if score_dict:
                    sorted_scores = dict(
                        sorted(score_dict.items(), key=lambda kv: kv[1], reverse=True)
                    )
                    st.bar_chart(sorted_scores)
                else:
                    st.caption("No NRC-matched words.")

        with col_s:
            st.markdown("**Style metrics**")
            if sel_style:
                st.table({
                    k.replace("_", " ").title(): [f"{v:.3f}"]
                    for k, v in sel_style.to_dict().items()
                })

        with st.expander("Text", expanded=False):
            st.write(sel_chunk.text[:2000] + ("…" if len(sel_chunk.text) > 2000 else ""))
