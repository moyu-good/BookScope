"""BookScope — Book Comparison page.

Compare two books side-by-side:
  • Overlaid emotion timeline
  • Side-by-side style radar
  • Arc pattern comparison
"""

from bookscope.utils import ensure_nltk_data

ensure_nltk_data()

import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from bookscope.nlp import ArcClassifier, LexiconAnalyzer, StyleAnalyzer  # noqa: E402
from bookscope.viz import (  # noqa: E402
    ChartDataAdapter,
    StyleRadarRenderer,
)

st.set_page_config(
    page_title="BookScope — Compare",
    page_icon="📖",
    layout="wide",
    initial_sidebar_state="expanded",
)

_EMOTION_FIELDS = (
    "anger", "anticipation", "disgust", "fear",
    "joy", "sadness", "surprise", "trust",
)


# ---------------------------------------------------------------------------
# Analysis helper (cached per uploaded file)
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def _analyse(file_bytes: bytes, filename: str, strategy: str, chunk_size: int, min_words: int):
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

    chunks = chunk(book, strategy=strategy, word_limit=chunk_size, min_words=min_words)
    emotion_scores = LexiconAnalyzer().analyze_book(chunks)
    style_scores = StyleAnalyzer().analyze_book(chunks)
    return chunks, emotion_scores, style_scores


# ---------------------------------------------------------------------------
# Sidebar — shared chunking options
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("BookScope — Compare")
    st.caption("Upload two books to compare their emotion arcs and style")

    st.divider()
    st.subheader("Chunking options")
    strategy = st.radio("Strategy", ["paragraph", "fixed"], index=0)
    chunk_size = st.slider(
        "Fixed chunk size (words)", 100, 1000, 300, step=50,
        disabled=(strategy != "fixed"),
    )
    min_words = st.slider("Min words per chunk", 10, 200, 50, step=10)

# ---------------------------------------------------------------------------
# Main — two upload columns
# ---------------------------------------------------------------------------

st.title("Book Comparison")
st.caption("Upload two plain-text or EPUB books to compare side by side.")

col_a, col_b = st.columns(2)

with col_a:
    st.subheader("Book A")
    uploaded_a = st.file_uploader(
        "Upload Book A", type=["txt", "epub"], key="upload_a",
        label_visibility="collapsed",
    )

with col_b:
    st.subheader("Book B")
    uploaded_b = st.file_uploader(
        "Upload Book B", type=["txt", "epub"], key="upload_b",
        label_visibility="collapsed",
    )

if uploaded_a is None and uploaded_b is None:
    st.info("Upload at least one book above to begin. Upload both for a full comparison.")
    st.stop()

# ---------------------------------------------------------------------------
# Run analysis for whichever books are uploaded
# ---------------------------------------------------------------------------

results: dict[str, tuple] = {}

for label, uploaded in [("A", uploaded_a), ("B", uploaded_b)]:
    if uploaded is None:
        continue
    spinner_msg = f"Analysing Book {label}…"
    with st.spinner(spinner_msg):
        file_bytes = uploaded.read()
        chunks, emotion_scores, style_scores = _analyse(
            file_bytes, uploaded.name, strategy, chunk_size, min_words,
        )
    if not chunks:
        st.warning(f"Book {label}: no chunks produced. Try lowering the minimum word count.")
    else:
        results[label] = (uploaded.name, chunks, emotion_scores, style_scores)

if not results:
    st.stop()

arc_classifier = ArcClassifier()

# Map label → (title, arc, emotion_scores, style_scores, chunks)
analyses: dict[str, dict] = {}
for label, (name, chunks, emotion_scores, style_scores) in results.items():
    arc = arc_classifier.classify(emotion_scores)
    analyses[label] = {
        "title": name.removesuffix(".txt").removesuffix(".epub"),
        "arc": arc,
        "emotion_scores": emotion_scores,
        "style_scores": style_scores,
        "chunks": chunks,
    }

# ---------------------------------------------------------------------------
# Summary metrics
# ---------------------------------------------------------------------------

st.divider()
st.subheader("Summary")

metric_cols = st.columns(len(analyses) * 3)
col_idx = 0
for label, info in analyses.items():
    total_words = sum(c.word_count for c in info["chunks"])
    metric_cols[col_idx].metric(f"Book {label} — chunks", len(info["chunks"]))
    metric_cols[col_idx + 1].metric("Total words", f"{total_words:,}")
    metric_cols[col_idx + 2].metric("Arc", info["arc"].value)
    col_idx += 3

# ---------------------------------------------------------------------------
# Emotion Timeline — overlaid
# ---------------------------------------------------------------------------

st.divider()
st.subheader("Emotion Timeline Comparison")

selected_emotions = st.multiselect(
    "Emotions to display",
    options=list(_EMOTION_FIELDS),
    default=["joy", "sadness", "fear", "trust"],
    format_func=str.capitalize,
    key="compare_emotions",
)

if not selected_emotions:
    st.info("Select at least one emotion above.")
else:
    # Build one figure with traces from both books; use distinct line styles
    LINE_STYLES = ["solid", "dash"]
    COLOUR_MAP = {
        "anger": "#e74c3c",
        "anticipation": "#e67e22",
        "disgust": "#8e44ad",
        "fear": "#2c3e50",
        "joy": "#f1c40f",
        "sadness": "#3498db",
        "surprise": "#1abc9c",
        "trust": "#27ae60",
    }

    fig = go.Figure()
    for book_idx, (label, info) in enumerate(analyses.items()):
        dash = LINE_STYLES[book_idx % len(LINE_STYLES)]
        emotion_scores = info["emotion_scores"]

        for emotion in selected_emotions:
            x = [s.chunk_index for s in emotion_scores]
            y = [getattr(s, emotion) for s in emotion_scores]
            fig.add_trace(go.Scatter(
                x=x, y=y,
                mode="lines",
                name=f"{emotion.capitalize()} [{info['title'][:20]}]",
                line=dict(color=COLOUR_MAP.get(emotion, "#888"), dash=dash, width=2),
                legendgroup=emotion,
            ))

    fig.update_layout(
        paper_bgcolor="#0f1117",
        plot_bgcolor="#0f1117",
        font=dict(color="#fafafa"),
        xaxis=dict(title="Chunk index", gridcolor="#333"),
        yaxis=dict(title="Emotion score", range=[0, 1], gridcolor="#333"),
        legend=dict(bgcolor="#0f1117", bordercolor="#444"),
        hovermode="x unified",
        height=450,
        margin=dict(l=20, r=20, t=20, b=40),
    )
    st.plotly_chart(fig, use_container_width=True)
    if len(analyses) == 2:
        labels = list(analyses.keys())
        st.caption(
            f"Solid lines = Book {labels[0]} ({analyses[labels[0]]['title'][:30]}), "
            f"dashed lines = Book {labels[1]} ({analyses[labels[1]]['title'][:30]})"
        )

# ---------------------------------------------------------------------------
# Valence arcs — one per book
# ---------------------------------------------------------------------------

st.divider()
st.subheader("Valence Arc Comparison")
st.caption("(joy + anticipation + trust) − (anger + fear + sadness + disgust)")

if any(len(info["emotion_scores"]) >= 6 for info in analyses.values()):
    valence_fig = go.Figure()
    for label, info in analyses.items():
        if len(info["emotion_scores"]) < 6:
            continue
        valences = arc_classifier.valence_series(info["emotion_scores"])
        valence_fig.add_trace(go.Scatter(
            x=list(range(len(valences))),
            y=valences,
            mode="lines",
            name=f"{info['title'][:25]} (arc: {info['arc'].value})",
            line=dict(width=2),
        ))

    valence_fig.update_layout(
        paper_bgcolor="#0f1117",
        plot_bgcolor="#0f1117",
        font=dict(color="#fafafa"),
        xaxis=dict(title="Chunk index", gridcolor="#333"),
        yaxis=dict(title="Valence", gridcolor="#333"),
        legend=dict(bgcolor="#0f1117", bordercolor="#444"),
        hovermode="x unified",
        height=350,
        margin=dict(l=20, r=20, t=20, b=40),
    )
    st.plotly_chart(valence_fig, use_container_width=True)
else:
    st.info("Need ≥ 6 chunks per book for valence arc display.")

# ---------------------------------------------------------------------------
# Style Radar — side by side
# ---------------------------------------------------------------------------

st.divider()
st.subheader("Style Fingerprint")

radar_cols = st.columns(len(analyses))
for col, (label, info) in zip(radar_cols, analyses.items()):
    with col:
        st.markdown(f"**Book {label} — {info['title'][:30]}**")
        if info["style_scores"]:
            radar_data = ChartDataAdapter.style_radar(info["style_scores"])
            st.plotly_chart(
                StyleRadarRenderer().render(radar_data),
                use_container_width=True,
                key=f"radar_{label}",
            )
        else:
            st.info("No style data.")

# ---------------------------------------------------------------------------
# Style metrics table — both books together
# ---------------------------------------------------------------------------

if len(analyses) == 2:
    labels = list(analyses.keys())
    info_a = analyses[labels[0]]
    info_b = analyses[labels[1]]

    if info_a["style_scores"] and info_b["style_scores"]:
        st.subheader("Style metrics comparison")

        radar_a = ChartDataAdapter.style_radar(info_a["style_scores"])
        radar_b = ChartDataAdapter.style_radar(info_b["style_scores"])

        import pandas as pd

        rows = []
        for metric in radar_a.raw_means:
            val_a = radar_a.raw_means[metric]
            val_b = radar_b.raw_means[metric]
            delta = val_b - val_a
            rows.append({
                "Metric": metric.replace("_", " ").title(),
                f"Book {labels[0]} ({info_a['title'][:20]})": f"{val_a:.3f}",
                f"Book {labels[1]} ({info_b['title'][:20]})": f"{val_b:.3f}",
                "Δ (B − A)": f"{delta:+.3f}",
            })

        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
# Vocabulary comparison — Jaccard similarity
# ---------------------------------------------------------------------------

if len(analyses) == 2:
    labels = list(analyses.keys())
    info_a = analyses[labels[0]]
    info_b = analyses[labels[1]]

    st.divider()
    st.subheader("Vocabulary Overlap")
    st.caption("Jaccard = |A ∩ B| / |A ∪ B|  —  0 = no shared words, 1 = identical vocabularies")

    import re

    def _tokenize(chunks) -> set[str]:
        words: set[str] = set()
        for c in chunks:
            words.update(re.findall(r"\b[a-zA-Z]{3,}\b", c.text.lower()))
        return words

    vocab_a = _tokenize(info_a["chunks"])
    vocab_b = _tokenize(info_b["chunks"])

    intersection = vocab_a & vocab_b
    union = vocab_a | vocab_b
    jaccard = len(intersection) / len(union) if union else 0.0

    j_col1, j_col2, j_col3, j_col4 = st.columns(4)
    j_col1.metric(f"Book {labels[0]} vocab", f"{len(vocab_a):,} words")
    j_col2.metric(f"Book {labels[1]} vocab", f"{len(vocab_b):,} words")
    j_col3.metric("Shared words", f"{len(intersection):,}")
    j_col4.metric("Jaccard similarity", f"{jaccard:.3f}")

    st.progress(jaccard, text=f"Vocabulary overlap: {jaccard:.1%}")

    with st.expander("Top shared words", expanded=False):
        # Show words in intersection sorted by combined frequency-ish (just alphabetic for now)
        shared_sorted = sorted(intersection)
        st.write(", ".join(shared_sorted[:200]) + (" …" if len(shared_sorted) > 200 else ""))

    with st.expander(f"Words unique to Book {labels[0]} ({info_a['title'][:20]})", expanded=False):
        unique_a = sorted(vocab_a - vocab_b)
        st.write(", ".join(unique_a[:200]) + (" …" if len(unique_a) > 200 else ""))

    with st.expander(f"Words unique to Book {labels[1]} ({info_b['title'][:20]})", expanded=False):
        unique_b = sorted(vocab_b - vocab_a)
        st.write(", ".join(unique_b[:200]) + (" …" if len(unique_b) > 200 else ""))
