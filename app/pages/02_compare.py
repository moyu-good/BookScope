"""BookScope — Book Comparison page (v0.4.0.0: full i18n + PDF + language sync).

Compare two books side-by-side:
  • Overlaid emotion timeline
  • Side-by-side style radar
  • Arc pattern comparison
  • Vocabulary Jaccard similarity
"""

from bookscope.utils import ensure_nltk_data

ensure_nltk_data()

# Fix langdetect non-determinism
from langdetect import DetectorFactory  # noqa: E402

DetectorFactory.seed = 0

import hashlib  # noqa: E402
import html as _html  # noqa: E402

import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from bookscope.app_utils import get_lang, inject_fonts  # noqa: E402
from bookscope.nlp import (  # noqa: E402
    ArcClassifier,
    LexiconAnalyzer,
    StyleAnalyzer,
    detect_language,
)
from bookscope.viz import ChartDataAdapter, StyleRadarRenderer  # noqa: E402

st.set_page_config(
    page_title="BookScope — Compare",
    page_icon="📖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# i18n
# ---------------------------------------------------------------------------

_COMPARE_STRINGS: dict[str, dict] = {
    "en": {
        "page_title": "Book Comparison",
        "page_caption": "Upload two books to compare their emotion arcs and writing style.",
        "sidebar_header": "BookScope — Compare",
        "sidebar_caption": "Side-by-side book analysis",
        "chunking_header": "Chunking options",
        "strategy_label": "Strategy",
        "strategy_paragraph": "Paragraph",
        "strategy_fixed": "Fixed size",
        "chunk_size_label": "Fixed chunk size (words)",
        "min_words_label": "Min words per chunk",
        "upload_a": "Book A",
        "upload_b": "Book B",
        "upload_hint": "Upload at least one book above to begin. Upload both for a full comparison.",  # noqa: E501
        "analysing": "Analysing Book {}…",
        "no_chunks_warning": "Book {}: no chunks produced. Try lowering the minimum word count.",
        "summary_header": "Summary",
        "metric_chunks": "Book {} — chunks",
        "metric_words": "Total words",
        "metric_arc": "Arc",
        "timeline_header": "Emotion Timeline Comparison",
        "timeline_select": "Emotions to display",
        "timeline_empty": "Select at least one emotion above.",
        "timeline_caption": "Solid lines = Book {} ({}), dashed lines = Book {} ({})",
        "valence_header": "Valence Arc Comparison",
        "valence_caption": "(joy + anticipation + trust) − (anger + fear + sadness + disgust)",
        "valence_short": "Need ≥ 6 chunks per book for valence arc display.",
        "radar_header": "Style Fingerprint",
        "metrics_header": "Style metrics comparison",
        "metric_col": "Metric",
        "vocab_header": "Vocabulary Overlap",
        "vocab_caption": "Jaccard = |A ∩ B| / |A ∪ B|  —  0 = no shared words, 1 = identical vocabularies",  # noqa: E501
        "vocab_a": "Book {} vocab",
        "vocab_b": "Book {} vocab",
        "vocab_shared": "Shared words",
        "vocab_jaccard": "Jaccard similarity",
        "vocab_progress": "Vocabulary overlap: {:.1%}",
        "shared_expander": "Top shared words",
        "unique_a_expander": "Words unique to Book {} ({})",
        "unique_b_expander": "Words unique to Book {} ({})",
        "lang_labels": {"en": "🇬🇧 English", "zh": "🇨🇳 Chinese", "ja": "🇯🇵 Japanese"},
        "detected_lang": "Detected language",
        "no_style_data": "No style data available.",
        "same_book_warning": (
            "Both slots contain the same book. "
            "Upload two different books for a meaningful comparison."
        ),
        "one_book_note": "Upload a second book to enable the comparison sections below.",
    },
    "zh": {
        "page_title": "书籍对比",
        "page_caption": "上传两本书，并排比较情感弧线和写作风格。",
        "sidebar_header": "BookScope — 对比",
        "sidebar_caption": "书籍并排分析",
        "chunking_header": "分块设置",
        "strategy_label": "分割方式",
        "strategy_paragraph": "按段落",
        "strategy_fixed": "固定大小",
        "chunk_size_label": "固定块大小（字数）",
        "min_words_label": "每块最小字数",
        "upload_a": "书籍 A",
        "upload_b": "书籍 B",
        "upload_hint": "至少上传一本书开始分析，上传两本可进行完整对比。",
        "analysing": "正在分析书籍 {}……",
        "no_chunks_warning": "书籍 {}：未生成文本块，请降低最小字数设置。",
        "summary_header": "摘要",
        "metric_chunks": "书籍 {} — 文本块数",
        "metric_words": "总字数",
        "metric_arc": "情节弧",
        "timeline_header": "情感时间线对比",
        "timeline_select": "选择要显示的情感",
        "timeline_empty": "请至少选择一种情感。",
        "timeline_caption": "实线 = 书籍 {}（{}），虚线 = 书籍 {}（{}）",
        "valence_header": "情感基调弧对比",
        "valence_caption": "（喜悦 + 期待 + 信任）−（愤怒 + 恐惧 + 悲伤 + 厌恶）",
        "valence_short": "每本书需至少 6 个文本块才能显示情感弧。",
        "radar_header": "风格指纹",
        "metrics_header": "文体指标对比",
        "metric_col": "指标",
        "vocab_header": "词汇重叠度",
        "vocab_caption": "Jaccard = |A ∩ B| / |A ∪ B|  —  0 = 无共同词汇，1 = 词汇完全相同",
        "vocab_a": "书籍 {} 词汇量",
        "vocab_b": "书籍 {} 词汇量",
        "vocab_shared": "共有词汇",
        "vocab_jaccard": "Jaccard 相似度",
        "vocab_progress": "词汇重叠度：{:.1%}",
        "shared_expander": "共同高频词",
        "unique_a_expander": "书籍 {} 独有词汇（{}）",
        "unique_b_expander": "书籍 {} 独有词汇（{}）",
        "lang_labels": {"en": "🇬🇧 英语", "zh": "🇨🇳 中文", "ja": "🇯🇵 日语"},
        "detected_lang": "检测到的语言",
        "no_style_data": "暂无文体数据。",
        "same_book_warning": (
            "两个槽位上传了同一本书，"
            "请上传两本不同的书以进行有意义的对比。"
        ),
        "one_book_note": "上传第二本书以启用下方的对比功能。",
    },
    "ja": {
        "page_title": "書籍比較",
        "page_caption": "2冊をアップロードして感情弧と文体を並べて比較します。",
        "sidebar_header": "BookScope — 比較",
        "sidebar_caption": "書籍の並列分析",
        "chunking_header": "チャンク設定",
        "strategy_label": "分割方法",
        "strategy_paragraph": "段落ごと",
        "strategy_fixed": "固定サイズ",
        "chunk_size_label": "固定チャンクサイズ（語数）",
        "min_words_label": "チャンクの最小語数",
        "upload_a": "本 A",
        "upload_b": "本 B",
        "upload_hint": "少なくとも1冊アップロードして開始。2冊で完全比較が可能です。",
        "analysing": "本 {} を分析中…",
        "no_chunks_warning": "本 {}: チャンクが生成されませんでした。最小語数を下げてください。",
        "summary_header": "サマリー",
        "metric_chunks": "本 {} — チャンク数",
        "metric_words": "総語数",
        "metric_arc": "感情弧",
        "timeline_header": "感情タイムライン比較",
        "timeline_select": "表示する感情",
        "timeline_empty": "少なくとも1つの感情を選択してください。",
        "timeline_caption": "実線 = 本 {}（{}）、破線 = 本 {}（{}）",
        "valence_header": "感情的バランス弧の比較",
        "valence_caption": "（喜び・期待・信頼）−（怒り・恐怖・悲しみ・嫌悪）",
        "valence_short": "感情弧の表示には各本6チャンク以上必要です。",
        "radar_header": "文体フィンガープリント",
        "metrics_header": "文体指標の比較",
        "metric_col": "指標",
        "vocab_header": "語彙の重複",
        "vocab_caption": "Jaccard = |A ∩ B| / |A ∪ B|  —  0 = 共通語なし、1 = 語彙完全一致",
        "vocab_a": "本 {} 語彙数",
        "vocab_b": "本 {} 語彙数",
        "vocab_shared": "共通語数",
        "vocab_jaccard": "Jaccard 類似度",
        "vocab_progress": "語彙の重複: {:.1%}",
        "shared_expander": "共通頻出語",
        "unique_a_expander": "本 {} のみの語彙（{}）",
        "unique_b_expander": "本 {} のみの語彙（{}）",
        "lang_labels": {"en": "🇬🇧 英語", "zh": "🇨🇳 中国語", "ja": "🇯🇵 日本語"},
        "detected_lang": "検出された言語",
        "no_style_data": "文体データがありません。",
        "same_book_warning": (
            "両スロットに同じ本がアップロードされています。"
            "比較には2冊の異なる本をアップロードしてください。"
        ),
        "one_book_note": "比較セクションを有効にするには2冊目をアップロードしてください。",
    },
}

_EMOTION_FIELDS = (
    "anger", "anticipation", "disgust", "fear",
    "joy", "sadness", "surprise", "trust",
)

# ---------------------------------------------------------------------------
# Language sync (reads query_params written by main.py)
# ---------------------------------------------------------------------------

ui_lang = get_lang()
T = _COMPARE_STRINGS.get(ui_lang, _COMPARE_STRINGS["en"])
inject_fonts(ui_lang)

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

    # Strip all supported extensions (AF-5)
    stem = filename
    for ext in (".txt", ".epub", ".pdf"):
        stem = stem.removesuffix(ext)

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        book = load_text(tmp_path, title=stem)
    finally:
        os.unlink(tmp_path)

    lang = detect_language(book.raw_text)
    book = book.model_copy(update={"language": lang})
    chunks = chunk(book, strategy=strategy, word_limit=chunk_size, min_words=min_words)
    emotion_scores = LexiconAnalyzer(language=lang).analyze_book(chunks)
    style_scores = StyleAnalyzer(language=lang).analyze_book(chunks)
    return chunks, emotion_scores, style_scores, lang


def _content_fingerprint(file_bytes: bytes) -> str:
    """MD5 of the first 8 KB of file bytes — fast duplicate-book detection."""
    return hashlib.md5(file_bytes[:8192]).hexdigest()


# ---------------------------------------------------------------------------
# Sidebar — shared chunking options
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header(T["sidebar_header"])
    st.caption(T["sidebar_caption"])

    st.divider()
    st.subheader(T["chunking_header"])
    strategy = st.radio(
        T["strategy_label"],
        options=["paragraph", "fixed"],
        format_func=lambda x: T["strategy_paragraph"] if x == "paragraph" else T["strategy_fixed"],
        index=0,
    )
    chunk_size = st.slider(
        T["chunk_size_label"], 100, 1000, 300, step=50,
        disabled=(strategy != "fixed"),
    )
    min_words = st.slider(T["min_words_label"], 10, 200, 50, step=10)

# ---------------------------------------------------------------------------
# Main — two upload columns
# ---------------------------------------------------------------------------

st.title(T["page_title"])
st.caption(T["page_caption"])

col_a, col_b = st.columns(2)

with col_a:
    st.subheader(T["upload_a"])
    uploaded_a = st.file_uploader(
        T["upload_a"], type=["txt", "epub", "pdf"], key="upload_a",
        label_visibility="collapsed",
    )

with col_b:
    st.subheader(T["upload_b"])
    uploaded_b = st.file_uploader(
        T["upload_b"], type=["txt", "epub", "pdf"], key="upload_b",
        label_visibility="collapsed",
    )

if uploaded_a is None and uploaded_b is None:
    st.info(T["upload_hint"])
    st.stop()

# ---------------------------------------------------------------------------
# Run analysis for whichever books are uploaded
# ---------------------------------------------------------------------------

results: dict[str, tuple] = {}
_fingerprints: dict[str, str] = {}

for label, uploaded in [("A", uploaded_a), ("B", uploaded_b)]:
    if uploaded is None:
        continue
    with st.spinner(T["analysing"].format(label)):
        file_bytes = uploaded.read()
        _fingerprints[label] = _content_fingerprint(file_bytes)
        chunks, emotion_scores, style_scores, detected_lang = _analyse(
            file_bytes, uploaded.name, strategy, chunk_size, min_words,
        )
    if not chunks:
        st.warning(T["no_chunks_warning"].format(label))
    else:
        results[label] = (uploaded.name, chunks, emotion_scores, style_scores, detected_lang)

if not results:
    st.stop()

# Same-book guard
if (
    len(_fingerprints) == 2
    and _fingerprints.get("A") == _fingerprints.get("B")
):
    st.warning(T["same_book_warning"])
    st.stop()

arc_classifier = ArcClassifier()

# Single-book note — user uploaded only one book
if len(results) == 1:
    st.info(T["one_book_note"])

# Map label → analysis dict
analyses: dict[str, dict] = {}
for label, (name, chunks, emotion_scores, style_scores, detected_lang) in results.items():
    arc = arc_classifier.classify(emotion_scores)
    stem = name
    for ext in (".txt", ".epub", ".pdf"):
        stem = stem.removesuffix(ext)
    analyses[label] = {
        "title": stem,
        "arc": arc,
        "emotion_scores": emotion_scores,
        "style_scores": style_scores,
        "chunks": chunks,
        "detected_lang": detected_lang,
    }

# ---------------------------------------------------------------------------
# Summary metrics
# ---------------------------------------------------------------------------

st.divider()
st.subheader(T["summary_header"])

metric_cols = st.columns(len(analyses) * 3)
col_idx = 0
for label, info in analyses.items():
    total_words = sum(c.word_count for c in info["chunks"])
    metric_cols[col_idx].metric(T["metric_chunks"].format(label), len(info["chunks"]))
    metric_cols[col_idx + 1].metric(T["metric_words"], f"{total_words:,}")
    lang_label = T["lang_labels"].get(info["detected_lang"], info["detected_lang"])
    metric_cols[col_idx + 2].metric(T["metric_arc"], info["arc"].value)
    col_idx += 3

# ---------------------------------------------------------------------------
# Emotion Timeline — overlaid
# ---------------------------------------------------------------------------

st.divider()
st.subheader(T["timeline_header"])

selected_emotions = st.multiselect(
    T["timeline_select"],
    options=list(_EMOTION_FIELDS),
    default=["joy", "sadness", "fear", "trust"],
    format_func=str.capitalize,
    key="compare_emotions",
)

if not selected_emotions:
    st.info(T["timeline_empty"])
else:
    LINE_STYLES = ["solid", "dash"]
    COLOUR_MAP = {
        "anger": "#e74c3c", "anticipation": "#e67e22", "disgust": "#8e44ad",
        "fear": "#2c3e50", "joy": "#f1c40f", "sadness": "#3498db",
        "surprise": "#1abc9c", "trust": "#27ae60",
    }

    fig = go.Figure()
    for book_idx, (label, info) in enumerate(analyses.items()):
        dash = LINE_STYLES[book_idx % len(LINE_STYLES)]
        for emotion in selected_emotions:
            x = [s.chunk_index for s in info["emotion_scores"]]
            y = [getattr(s, emotion) for s in info["emotion_scores"]]
            fig.add_trace(go.Scatter(
                x=x, y=y, mode="lines",
                name=f"{emotion.capitalize()} [{info['title'][:20]}]",
                line=dict(color=COLOUR_MAP.get(emotion, "#888"), dash=dash, width=2),
                legendgroup=emotion,
            ))

    fig.update_layout(
        paper_bgcolor="#0f1117", plot_bgcolor="#0f1117",
        font=dict(color="#fafafa"),
        xaxis=dict(title="Chunk index", gridcolor="#333"),
        yaxis=dict(title="Emotion score", range=[0, 1], gridcolor="#333"),
        legend=dict(bgcolor="#0f1117", bordercolor="#444"),
        hovermode="x unified", height=450,
        margin=dict(l=20, r=20, t=20, b=40),
    )
    st.plotly_chart(fig, use_container_width=True)
    if len(analyses) == 2:
        labels = list(analyses.keys())
        st.caption(T["timeline_caption"].format(
            labels[0], analyses[labels[0]]["title"][:30],
            labels[1], analyses[labels[1]]["title"][:30],
        ))

# ---------------------------------------------------------------------------
# Valence arcs — one per book
# ---------------------------------------------------------------------------

st.divider()
st.subheader(T["valence_header"])
st.caption(T["valence_caption"])

if any(len(info["emotion_scores"]) >= 6 for info in analyses.values()):
    valence_fig = go.Figure()
    for label, info in analyses.items():
        if len(info["emotion_scores"]) < 6:
            continue
        valences = arc_classifier.valence_series(info["emotion_scores"])
        valence_fig.add_trace(go.Scatter(
            x=list(range(len(valences))), y=valences, mode="lines",
            name=f"{info['title'][:25]} (arc: {info['arc'].value})",
            line=dict(width=2),
        ))

    valence_fig.update_layout(
        paper_bgcolor="#0f1117", plot_bgcolor="#0f1117",
        font=dict(color="#fafafa"),
        xaxis=dict(title="Chunk index", gridcolor="#333"),
        yaxis=dict(title="Valence", gridcolor="#333"),
        legend=dict(bgcolor="#0f1117", bordercolor="#444"),
        hovermode="x unified", height=350,
        margin=dict(l=20, r=20, t=20, b=40),
    )
    st.plotly_chart(valence_fig, use_container_width=True)
else:
    st.info(T["valence_short"])

# ---------------------------------------------------------------------------
# Style Radar — side by side
# ---------------------------------------------------------------------------

st.divider()
st.subheader(T["radar_header"])

radar_cols = st.columns(len(analyses))
for col, (label, info) in zip(radar_cols, analyses.items()):
    with col:
        st.markdown(f"**{_html.escape(info['title'][:30])}**")
        if info["style_scores"]:
            radar_data = ChartDataAdapter.style_radar(info["style_scores"])
            st.plotly_chart(
                StyleRadarRenderer().render(radar_data),
                use_container_width=True,
                key=f"radar_{label}",
            )
        else:
            st.info(T["no_style_data"])

# ---------------------------------------------------------------------------
# Style metrics table — both books together
# ---------------------------------------------------------------------------

if len(analyses) == 2:
    labels = list(analyses.keys())
    info_a = analyses[labels[0]]
    info_b = analyses[labels[1]]

    if info_a["style_scores"] and info_b["style_scores"]:
        st.subheader(T["metrics_header"])

        radar_a = ChartDataAdapter.style_radar(info_a["style_scores"])
        radar_b = ChartDataAdapter.style_radar(info_b["style_scores"])

        import pandas as pd

        rows = []
        for metric in radar_a.raw_means:
            val_a = radar_a.raw_means[metric]
            val_b = radar_b.raw_means[metric]
            delta = val_b - val_a
            rows.append({
                T["metric_col"]: metric.replace("_", " ").title(),
                f"{T['upload_a']} ({info_a['title'][:20]})": f"{val_a:.3f}",
                f"{T['upload_b']} ({info_b['title'][:20]})": f"{val_b:.3f}",
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
    st.subheader(T["vocab_header"])
    st.caption(T["vocab_caption"])

    import re

    def _tokenize(chunks_list) -> set[str]:
        words: set[str] = set()
        for c in chunks_list:
            words.update(re.findall(r"\b[a-zA-Z]{3,}\b", c.text.lower()))
        return words

    vocab_a = _tokenize(info_a["chunks"])
    vocab_b = _tokenize(info_b["chunks"])

    intersection = vocab_a & vocab_b
    union = vocab_a | vocab_b
    jaccard = len(intersection) / len(union) if union else 0.0

    j_col1, j_col2, j_col3, j_col4 = st.columns(4)
    j_col1.metric(T["vocab_a"].format(labels[0]), f"{len(vocab_a):,}")
    j_col2.metric(T["vocab_b"].format(labels[1]), f"{len(vocab_b):,}")
    j_col3.metric(T["vocab_shared"], f"{len(intersection):,}")
    j_col4.metric(T["vocab_jaccard"], f"{jaccard:.3f}")

    st.progress(jaccard, text=T["vocab_progress"].format(jaccard))

    with st.expander(T["shared_expander"], expanded=False):
        shared_sorted = sorted(intersection)
        st.write(", ".join(shared_sorted[:200]) + (" …" if len(shared_sorted) > 200 else ""))

    label_a = T["unique_a_expander"].format(labels[0], info_a["title"][:20])
    with st.expander(label_a, expanded=False):
        unique_a = sorted(vocab_a - vocab_b)
        st.write(", ".join(unique_a[:200]) + (" …" if len(unique_a) > 200 else ""))

    label_b = T["unique_b_expander"].format(labels[1], info_b["title"][:20])
    with st.expander(label_b, expanded=False):
        unique_b = sorted(vocab_b - vocab_a)
        st.write(", ".join(unique_b[:200]) + (" …" if len(unique_b) > 200 else ""))
