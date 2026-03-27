"""BookScope — Streamlit entry point (v2: modern dark + i18n).

Run with:
    streamlit run app/main.py
"""

# Bootstrap NLTK corpora before any NLP imports (safe no-op if already present)
from bookscope.utils import ensure_nltk_data

ensure_nltk_data()

import streamlit as st  # noqa: E402

from bookscope.models import EmotionScore  # noqa: E402
from bookscope.nlp import (  # noqa: E402
    ArcClassifier,
    LexiconAnalyzer,
    StyleAnalyzer,
    detect_language,
)
from bookscope.store import AnalysisResult, Repository  # noqa: E402
from bookscope.viz import (  # noqa: E402
    ChartDataAdapter,
    EmotionHeatmapRenderer,
    EmotionTimelineRenderer,
    StyleRadarRenderer,
)

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
# i18n — all UI strings in three languages
# ---------------------------------------------------------------------------

_STRINGS: dict[str, dict] = {
    "en": {
        "page_title": "BookScope",
        "tagline": "Discover the emotional soul of any book",
        "sidebar_header": "BookScope",
        "sidebar_tagline": "Emotion arc & style analysis",
        "upload_label": "Upload a file",
        "upload_types": "Supports .txt · .epub · .pdf",
        "url_label": "Or paste a URL",
        "url_placeholder": "https://…",
        "chunking_header": "Reading options",
        "strategy_label": "Split by",
        "strategy_paragraph": "Paragraph",
        "strategy_fixed": "Fixed size",
        "chunk_size_label": "Words per block",
        "min_words_label": "Skip blocks shorter than",
        "saved_header": "Saved analyses",
        "no_saved": "No saved analyses yet.",
        "welcome_title": "What story hides in your book?",
        "welcome_body": (
            "Upload a **.txt**, **.epub**, or **.pdf** file — or paste a URL — "
            "to reveal the emotional journey hidden inside."
        ),
        "analysing": "Reading your book…",
        "no_chunks_warning": "No text blocks produced. Try lowering the minimum word count.",
        "url_error": "Could not fetch URL: {}",
        "detected_lang": "Detected language",
        "save_btn": "💾 Save analysis",
        "saved_ok": "Saved!",
        # Hero card
        "hero_sentence": (
            "This story is primarily driven by **{emotion}**,"
            " following a **{arc}** arc across {chunks} blocks."
        ),
        "hero_dominant": "Dominant emotion",
        "hero_arc": "Story arc",
        "hero_words": "Total words",
        "hero_chunks": "Text blocks",
        # Tab names
        "tab_overview": "📊 Overview",
        "tab_heatmap": "🌡 Heatmap",
        "tab_timeline": "📈 Timeline",
        "tab_style": "🎨 Style",
        "tab_arc": "🌀 Arc Pattern",
        "tab_export": "📥 Export",
        "tab_chunks": "🔍 Chunks",
        # Overview
        "overview_avg_emotions": "Average emotion scores",
        "overview_avg_desc": (
            "How strongly each emotion appears on average across the whole book "
            "(0 = absent · 1 = very strong)"
        ),
        # Heatmap
        "heatmap_title": "Emotion intensity across the book",
        "heatmap_desc": (
            "Each column is one block of text; each row is an emotion. "
            "Darker red = stronger emotion."
        ),
        # Timeline
        "timeline_title": "Emotional journey",
        "timeline_desc": (
            "Watch how the emotional tone rises and falls as the story progresses. "
            "Each point is one block of text."
        ),
        "timeline_select": "Emotions to show",
        "timeline_empty": "Select at least one emotion above.",
        # Style
        "style_title": "Writing style fingerprint",
        "style_desc": (
            "A radar chart of the author's stylistic traits — "
            "vocabulary richness, sentence length, and parts of speech."
        ),
        "style_over_time": "How a metric changes through the book",
        "style_pick": "Choose a metric",
        "style_no_data": "No style data available.",
        # Arc
        "arc_title": "Story shape",
        "arc_desc": (
            "Kurt Vonnegut proposed that every story follows one of a few emotional shapes. "
            "BookScope detects which one fits your book."
        ),
        "arc_valence_title": "Emotional tone over time",
        "arc_valence_caption": (
            "Positive = joy + anticipation + trust · "
            "Negative = anger + fear + sadness + disgust"
        ),
        "arc_short": "Upload a longer text for arc detection (need at least 6 blocks).",
        # Export
        "export_title": "Download your results",
        "export_emotions_csv": "📥 Emotion scores (.csv)",
        "export_style_csv": "📥 Style scores (.csv)",
        "export_json": "📥 Full analysis (.json)",
        "export_md": "📥 Report (.md)",
        # Chunks
        "chunks_title": "Block explorer",
        "chunks_slider": "Block number",
        "chunks_header": "Block {} — {} words",
        "chunks_emotion_header": "Emotion scores",
        "chunks_style_header": "Style metrics",
        "chunks_no_match": "No emotion words found in this block.",
        "chunks_show_text": "Show text",
        # Arc descriptions
        "arc_descriptions": {
            "Rags to Riches": "A sustained rise — the story builds toward hope and positivity.",
            "Riches to Rags": "A sustained fall — tension and darkness grow throughout.",
            "Man in a Hole": "Fall then rise — the protagonist hits rock bottom and climbs back.",
            "Icarus": "Rise then fall — early success gives way to tragedy.",
            "Cinderella": "Rise → fall → rise — hope, setback, then ultimate triumph.",
            "Oedipus": "Fall → rise → fall — a brief glimmer of hope between two tragedies.",
            "Unknown": "Not enough data to detect the arc pattern.",
        },
        "lang_labels": {"en": "🇬🇧 English", "zh": "🇨🇳 Chinese", "ja": "🇯🇵 Japanese"},
        "emotion_names": {
            "anger": "Anger", "anticipation": "Anticipation", "disgust": "Disgust",
            "fear": "Fear", "joy": "Joy", "sadness": "Sadness",
            "surprise": "Surprise", "trust": "Trust",
        },
        "style_metric_names": {
            "ttr": "Vocabulary richness",
            "avg_sentence_length": "Avg sentence length",
            "noun_ratio": "Noun ratio",
            "verb_ratio": "Verb ratio",
            "adj_ratio": "Adjective ratio",
            "adv_ratio": "Adverb ratio",
        },
        "style_metric_help": {
            "ttr": "Ratio of unique words to total words — higher means more varied language",
            "avg_sentence_length": "Average number of words per sentence",
            "noun_ratio": "Fraction of words that are nouns",
            "verb_ratio": "Fraction of words that are verbs",
            "adj_ratio": "Fraction of words that are adjectives",
            "adv_ratio": "Fraction of words that are adverbs",
        },
    },
    "zh": {
        "page_title": "BookScope",
        "tagline": "探索任何书籍的情感灵魂",
        "sidebar_header": "BookScope",
        "sidebar_tagline": "情感弧线 & 文体分析",
        "upload_label": "上传文件",
        "upload_types": "支持 .txt · .epub · .pdf",
        "url_label": "或输入网址",
        "url_placeholder": "https://…",
        "chunking_header": "阅读设置",
        "strategy_label": "分割方式",
        "strategy_paragraph": "按段落",
        "strategy_fixed": "固定大小",
        "chunk_size_label": "每块字数",
        "min_words_label": "忽略短于以下字数的块",
        "saved_header": "已保存的分析",
        "no_saved": "暂无保存记录。",
        "welcome_title": "你的书里藏着什么故事？",
        "welcome_body": (
            "上传 **.txt**、**.epub** 或 **.pdf** 文件，或粘贴网址，"
            "即可揭示书中隐藏的情感之旅。"
        ),
        "analysing": "正在阅读你的书籍……",
        "no_chunks_warning": "未生成任何文本块，请尝试降低最小字数。",
        "url_error": "无法获取网址内容：{}",
        "detected_lang": "检测到的语言",
        "save_btn": "💾 保存分析",
        "saved_ok": "已保存！",
        # Hero card
        "hero_sentence": (
            "这本书的主导情感是 **{emotion}**，"
            "故事走向为 **{arc}**，共分析了 {chunks} 个文本块。"
        ),
        "hero_dominant": "主导情感",
        "hero_arc": "故事走向",
        "hero_words": "总字数",
        "hero_chunks": "文本块数",
        # Tab names
        "tab_overview": "📊 概览",
        "tab_heatmap": "🌡 热力图",
        "tab_timeline": "📈 情感时间线",
        "tab_style": "🎨 文体",
        "tab_arc": "🌀 情节弧",
        "tab_export": "📥 导出",
        "tab_chunks": "🔍 分块浏览",
        # Overview
        "overview_avg_emotions": "平均情感分数",
        "overview_avg_desc": "整本书中每种情感的平均强度（0 = 无 · 1 = 非常强烈）",
        # Heatmap
        "heatmap_title": "情感强度分布",
        "heatmap_desc": "每一列是一个文本块，每一行是一种情感。颜色越深红，强度越高。",
        # Timeline
        "timeline_title": "情感之旅",
        "timeline_desc": "随着故事发展，情感基调如何起伏变化。每个点代表一个文本块。",
        "timeline_select": "选择要显示的情感",
        "timeline_empty": "请至少选择一种情感。",
        # Style
        "style_title": "写作风格指纹",
        "style_desc": "雷达图展示作者的文体特征——词汇丰富度、句子长度及词性比例。",
        "style_over_time": "某项指标在全书中的变化",
        "style_pick": "选择指标",
        "style_no_data": "暂无文体数据。",
        # Arc
        "arc_title": "故事形状",
        "arc_desc": (
            "冯内古特认为所有故事都遵循几种情感走向之一。"
            "BookScope 自动识别你的书属于哪种。"
        ),
        "arc_valence_title": "情感基调随时间变化",
        "arc_valence_caption": "正值 = 喜悦 + 期待 + 信任 · 负值 = 愤怒 + 恐惧 + 悲伤 + 厌恶",
        "arc_short": "请上传更长的文本以进行情节弧识别（至少需要 6 个文本块）。",
        # Export
        "export_title": "下载分析结果",
        "export_emotions_csv": "📥 情感分数 (.csv)",
        "export_style_csv": "📥 文体分数 (.csv)",
        "export_json": "📥 完整分析 (.json)",
        "export_md": "📥 报告 (.md)",
        # Chunks
        "chunks_title": "文本块浏览器",
        "chunks_slider": "块编号",
        "chunks_header": "第 {} 块 — {} 字",
        "chunks_emotion_header": "情感分数",
        "chunks_style_header": "文体指标",
        "chunks_no_match": "本块未找到情感词汇。",
        "chunks_show_text": "显示原文",
        # Arc descriptions (Chinese — idiomatic names)
        "arc_descriptions": {
            "Rags to Riches": "白手起家 — 情感持续上升，充满希望与正能量。",
            "Riches to Rags": "盛极而衰 — 情感持续下降，紧张与黑暗逐渐加深。",
            "Man in a Hole": "跌入谷底 — 主角跌至谷底后重新崛起。",
            "Icarus": "乐极生悲 — 先是高涨的喜悦，随后急转直下走向悲剧。",
            "Cinderella": "好事多磨 — 希望升起，遭遇挫折，最终迎来胜利。",
            "Oedipus": "回光返照 — 在两段悲剧之间，短暂地燃起希望。",
            "Unknown": "数据不足，无法识别情节弧类型。",
        },
        "lang_labels": {"en": "🇬🇧 英语", "zh": "🇨🇳 中文", "ja": "🇯🇵 日语"},
        "emotion_names": {
            "anger": "愤怒", "anticipation": "期待", "disgust": "厌恶",
            "fear": "恐惧", "joy": "喜悦", "sadness": "悲伤",
            "surprise": "惊讶", "trust": "信任",
        },
        "style_metric_names": {
            "ttr": "词汇丰富度",
            "avg_sentence_length": "平均句长",
            "noun_ratio": "名词比例",
            "verb_ratio": "动词比例",
            "adj_ratio": "形容词比例",
            "adv_ratio": "副词比例",
        },
        "style_metric_help": {
            "ttr": "不同词语占总词数的比例（越高表示语言越多样）",
            "avg_sentence_length": "平均每句话的词数",
            "noun_ratio": "名词占总词数的比例",
            "verb_ratio": "动词占总词数的比例",
            "adj_ratio": "形容词占总词数的比例",
            "adv_ratio": "副词占总词数的比例",
        },
    },
    "ja": {
        "page_title": "BookScope",
        "tagline": "あらゆる本の感情的な魂を発見する",
        "sidebar_header": "BookScope",
        "sidebar_tagline": "感情弧・文体分析",
        "upload_label": "ファイルをアップロード",
        "upload_types": ".txt · .epub · .pdf に対応",
        "url_label": "またはURLを入力",
        "url_placeholder": "https://…",
        "chunking_header": "読み取り設定",
        "strategy_label": "分割方法",
        "strategy_paragraph": "段落ごと",
        "strategy_fixed": "固定サイズ",
        "chunk_size_label": "ブロックあたりの語数",
        "min_words_label": "以下の語数のブロックをスキップ",
        "saved_header": "保存済み分析",
        "no_saved": "保存された分析はありません。",
        "welcome_title": "あなたの本に隠された物語は？",
        "welcome_body": (
            "**.txt** · **.epub** · **.pdf** ファイルをアップロードするか、"
            "URLを貼り付けると、感情の旅を可視化します。"
        ),
        "analysing": "本を読み込んでいます…",
        "no_chunks_warning": "テキストブロックが生成されませんでした。最小語数を下げてください。",
        "url_error": "URLの取得に失敗しました：{}",
        "detected_lang": "検出された言語",
        "save_btn": "💾 保存",
        "saved_ok": "保存しました！",
        # Hero card
        "hero_sentence": (
            "この本の主要感情は **{emotion}** で、"
            "**{arc}** の弧パターンが {chunks} ブロックにわたって検出されました。"
        ),
        "hero_dominant": "主要感情",
        "hero_arc": "物語の弧",
        "hero_words": "総語数",
        "hero_chunks": "チャンク数",
        # Tab names
        "tab_overview": "📊 概要",
        "tab_heatmap": "🌡 ヒートマップ",
        "tab_timeline": "📈 感情タイムライン",
        "tab_style": "🎨 文体",
        "tab_arc": "🌀 感情弧",
        "tab_export": "📥 エクスポート",
        "tab_chunks": "🔍 チャンク",
        # Overview
        "overview_avg_emotions": "感情の平均スコア",
        "overview_avg_desc": (
            "本全体で各感情がどの程度強く現れるか（0 = なし · 1 = 非常に強い）"
        ),
        # Heatmap
        "heatmap_title": "本全体の感情強度",
        "heatmap_desc": (
            "各列はテキストブロック、各行は感情です。濃い赤ほど強い感情を示します。"
        ),
        # Timeline
        "timeline_title": "感情の旅",
        "timeline_desc": "物語が進むにつれて感情がどう変化するか。各点は1ブロックです。",
        "timeline_select": "表示する感情を選択",
        "timeline_empty": "少なくとも1つの感情を選択してください。",
        # Style
        "style_title": "文体の指紋",
        "style_desc": (
            "著者の文体的特徴を示すレーダーチャート — "
            "語彙の豊かさ、文の長さ、品詞の比率。"
        ),
        "style_over_time": "指標の本全体での変化",
        "style_pick": "指標を選択",
        "style_no_data": "文体データがありません。",
        # Arc
        "arc_title": "物語の形",
        "arc_desc": (
            "ヴォネガットは、すべての物語はいくつかの感情的な形に当てはまると提唱しました。"
            "BookScope がどれか検出します。"
        ),
        "arc_valence_title": "感情的トーンの時間変化",
        "arc_valence_caption": "正 = 喜び・期待・信頼 · 負 = 怒り・恐怖・悲しみ・嫌悪",
        "arc_short": "弧パターン検出には長いテキストが必要です（最低6ブロック）。",
        # Export
        "export_title": "結果をダウンロード",
        "export_emotions_csv": "📥 感情スコア (.csv)",
        "export_style_csv": "📥 文体スコア (.csv)",
        "export_json": "📥 完全分析 (.json)",
        "export_md": "📥 レポート (.md)",
        # Chunks
        "chunks_title": "ブロックエクスプローラー",
        "chunks_slider": "ブロック番号",
        "chunks_header": "ブロック {} — {} 語",
        "chunks_emotion_header": "感情スコア",
        "chunks_style_header": "文体指標",
        "chunks_no_match": "このブロックに感情語は見つかりませんでした。",
        "chunks_show_text": "テキストを表示",
        # Arc descriptions (Japanese)
        "arc_descriptions": {
            "Rags to Riches": "どん底からの成功 — 感情が上昇し、希望と前向きさが高まります。",
            "Riches to Rags": "栄光からの転落 — 感情が持続的に低下し、緊張と暗さが増していきます。",
            "Man in a Hole": "穴に落ちた男 — 主人公は底まで落ちた後、再び這い上がります。",
            "Icarus": "イカロス — 最初の成功の後、悲劇へと転落します。",
            "Cinderella": "シンデレラ — 希望・挫折・そして最終的な勝利。",
            "Oedipus": "オイディプス — ふたつの悲劇の間に、ほんの一瞬の希望が輝きます。",
            "Unknown": "弧パターンを検出するのに十分なデータがありません。",
        },
        "lang_labels": {"en": "🇬🇧 英語", "zh": "🇨🇳 中国語", "ja": "🇯🇵 日本語"},
        "emotion_names": {
            "anger": "怒り", "anticipation": "期待", "disgust": "嫌悪",
            "fear": "恐怖", "joy": "喜び", "sadness": "悲しみ",
            "surprise": "驚き", "trust": "信頼",
        },
        "style_metric_names": {
            "ttr": "語彙の豊かさ",
            "avg_sentence_length": "平均文長",
            "noun_ratio": "名詞比率",
            "verb_ratio": "動詞比率",
            "adj_ratio": "形容詞比率",
            "adv_ratio": "副詞比率",
        },
        "style_metric_help": {
            "ttr": "ユニークな単語の割合（高いほど多様な表現）",
            "avg_sentence_length": "1文あたりの平均語数",
            "noun_ratio": "名詞の割合",
            "verb_ratio": "動詞の割合",
            "adj_ratio": "形容詞の割合",
            "adv_ratio": "副詞の割合",
        },
    },
}

# Internal arc key → localized display name
_ARC_DISPLAY: dict[str, dict[str, str]] = {
    "en": {
        "Rags to Riches": "Rags to Riches ↗",
        "Riches to Rags": "Riches to Rags ↘",
        "Man in a Hole": "Man in a Hole ↘↗",
        "Icarus": "Icarus ↗↘",
        "Cinderella": "Cinderella ↗↘↗",
        "Oedipus": "Oedipus ↘↗↘",
        "Unknown": "Unknown",
    },
    "zh": {
        "Rags to Riches": "白手起家 ↗",
        "Riches to Rags": "盛极而衰 ↘",
        "Man in a Hole": "跌入谷底 ↘↗",
        "Icarus": "乐极生悲 ↗↘",
        "Cinderella": "好事多磨 ↗↘↗",
        "Oedipus": "回光返照 ↘↗↘",
        "Unknown": "未知",
    },
    "ja": {
        "Rags to Riches": "どん底からの成功 ↗",
        "Riches to Rags": "栄光からの転落 ↘",
        "Man in a Hole": "穴に落ちた男 ↘↗",
        "Icarus": "イカロス ↗↘",
        "Cinderella": "シンデレラ ↗↘↗",
        "Oedipus": "オイディプス ↘↗↘",
        "Unknown": "不明",
    },
}

_EMOTION_COLORS: dict[str, str] = {
    "anger": "#ef4444",
    "anticipation": "#f97316",
    "disgust": "#a855f7",
    "fear": "#6b7280",
    "joy": "#eab308",
    "sadness": "#3b82f6",
    "surprise": "#06b6d4",
    "trust": "#22c55e",
}

_EMOTION_ICONS: dict[str, str] = {
    "anger": "😠", "anticipation": "🤩", "disgust": "🤢",
    "fear": "😨", "joy": "😊", "sadness": "😢",
    "surprise": "😲", "trust": "🤝",
}

_EMOTION_FIELDS = (
    "anger", "anticipation", "disgust", "fear",
    "joy", "sadness", "surprise", "trust",
)

# ---------------------------------------------------------------------------
# Language selection — resolve before rendering anything else
# ---------------------------------------------------------------------------

if "ui_lang" not in st.session_state:
    st.session_state["ui_lang"] = "en"

# ---------------------------------------------------------------------------
# Custom CSS injection
# ---------------------------------------------------------------------------

st.markdown("""
<style>
/* Hero card */
.bs-hero {
    background: linear-gradient(135deg, #1a0b3d 0%, #0d1b2a 100%);
    border: 1px solid #4c1d95;
    border-radius: 16px;
    padding: 1.75rem 2rem;
    margin-bottom: 1.5rem;
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
/* Tab description helper text */
.bs-desc {
    color: #94a3b8;
    font-size: 0.88rem;
    margin-bottom: 1rem;
    line-height: 1.5;
}
/* Welcome screen */
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
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Analysis pipeline
# ---------------------------------------------------------------------------


def _run_pipeline(book, strategy, chunk_size, min_words):
    """Shared analysis pipeline — language detection → chunk → NLP."""
    from bookscope.ingest import chunk

    lang = detect_language(book.raw_text)
    book = book.model_copy(update={"language": lang})
    chunks = chunk(book, strategy=strategy, word_limit=chunk_size, min_words=min_words)
    emotion_scores = LexiconAnalyzer(language=lang).analyze_book(chunks)
    style_scores = StyleAnalyzer(language=lang).analyze_book(chunks)
    return chunks, emotion_scores, style_scores, lang


@st.cache_data(show_spinner=False)
def run_analysis(
    file_bytes: bytes,
    filename: str,
    strategy: str,
    chunk_size: int,
    min_words: int,
):
    """Load → clean → chunk → emotion + style analysis (file upload path)."""
    import os
    import tempfile

    from bookscope.ingest.loader import load_text

    suffix = "." + filename.rsplit(".", 1)[-1] if "." in filename else ".txt"
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

    return _run_pipeline(book, strategy, chunk_size, min_words)


@st.cache_data(show_spinner=False)
def run_analysis_url(
    url: str,
    strategy: str,
    chunk_size: int,
    min_words: int,
):
    """Fetch URL → clean → chunk → emotion + style analysis."""
    from bookscope.ingest.loader import load_url

    book = load_url(url)
    chunks, emotion_scores, style_scores, lang = _run_pipeline(
        book, strategy, chunk_size, min_words
    )
    return chunks, emotion_scores, style_scores, lang, book.title


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    # Language selector — top of sidebar
    lang_options = ["en", "zh", "ja"]
    lang_display = {"en": "🇬🇧 English", "zh": "🇨🇳 中文", "ja": "🇯🇵 日本語"}
    selected_lang = st.radio(
        "Language / 语言 / 言語",
        options=lang_options,
        format_func=lambda x: lang_display[x],
        index=lang_options.index(st.session_state["ui_lang"]),
        horizontal=True,
        key="lang_radio",
    )
    st.session_state["ui_lang"] = selected_lang
    T = _STRINGS[selected_lang]

    st.divider()

    st.markdown(f"### {T['sidebar_header']}")
    st.caption(T["sidebar_tagline"])

    uploaded = st.file_uploader(
        T["upload_label"],
        type=["txt", "epub", "pdf"],
        help=T["upload_types"],
    )
    url_input = st.text_input(T["url_label"], placeholder=T["url_placeholder"])

    st.divider()
    st.subheader(T["chunking_header"])
    strategy = st.radio(
        T["strategy_label"],
        options=["paragraph", "fixed"],
        format_func=lambda x: T["strategy_paragraph"] if x == "paragraph" else T["strategy_fixed"],
        index=0,
        key="strategy",
    )
    chunk_size = st.slider(
        T["chunk_size_label"], 100, 1000, 300, step=50,
        disabled=(strategy != "fixed"),
        key="chunk_size",
    )
    min_words = st.slider(
        T["min_words_label"], 10, 200, 50, step=10,
        key="min_words",
    )

    st.divider()
    st.subheader(T["saved_header"])
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
        st.caption(T["no_saved"])

# Keep T in sync if sidebar wasn't rendered yet (first run edge case)
T = _STRINGS[st.session_state["ui_lang"]]

# ---------------------------------------------------------------------------
# Welcome screen (no input yet)
# ---------------------------------------------------------------------------

if uploaded is None and not url_input:
    st.markdown(
        f"""
        <div class="bs-welcome">
            <h2>📖 {T['welcome_title']}</h2>
            <p>{T['welcome_body']}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.stop()

# ---------------------------------------------------------------------------
# Run analysis
# ---------------------------------------------------------------------------

with st.spinner(T["analysing"]):
    if uploaded is not None:
        file_bytes = uploaded.read()
        chunks, emotion_scores, style_scores, detected_lang = run_analysis(
            file_bytes, uploaded.name, strategy, chunk_size, min_words,
        )
        book_title = uploaded.name
        for ext in (".txt", ".epub", ".pdf"):
            book_title = book_title.removesuffix(ext)
    else:
        try:
            chunks, emotion_scores, style_scores, detected_lang, book_title = run_analysis_url(
                url_input, strategy, chunk_size, min_words,
            )
        except Exception as exc:
            st.error(T["url_error"].format(exc))
            st.stop()

if not chunks:
    st.warning(T["no_chunks_warning"])
    st.stop()

# Show detected language in sidebar
with st.sidebar:
    st.divider()
    lang_label = T["lang_labels"].get(detected_lang, detected_lang)
    st.caption(f"{T['detected_lang']}: **{lang_label}**")

# Arc classification
arc_classifier = ArcClassifier()
arc = arc_classifier.classify(emotion_scores)
arc_display_name = _ARC_DISPLAY[selected_lang].get(arc.value, arc.value)

# Compute aggregates
total_words = sum(c.word_count for c in chunks)
from collections import Counter  # noqa: E402

dominants = Counter(s.dominant_emotion for s in emotion_scores) if emotion_scores else Counter()
top_emotion_key = dominants.most_common(1)[0][0] if dominants else "joy"
top_emotion_name = T["emotion_names"].get(top_emotion_key, top_emotion_key.capitalize())
top_emotion_color = _EMOTION_COLORS.get(top_emotion_key, "#7c3aed")
top_emotion_icon = _EMOTION_ICONS.get(top_emotion_key, "✨")

# ---------------------------------------------------------------------------
# Hero card
# ---------------------------------------------------------------------------

hero_sentence = T["hero_sentence"].format(
    emotion=top_emotion_name,
    arc=arc_display_name,
    chunks=len(chunks),
)

st.markdown(
    f"""
    <div class="bs-hero">
        <div class="bs-hero-title">📖 {book_title}</div>
        <div class="bs-hero-sentence">{hero_sentence}</div>
        <div class="bs-metrics">
            <div class="bs-metric">
                <div class="bs-metric-label">{T['hero_dominant']}</div>
                <div class="bs-metric-value" style="color:{top_emotion_color};">
                    {top_emotion_icon} {top_emotion_name}
                </div>
            </div>
            <div class="bs-metric">
                <div class="bs-metric-label">{T['hero_arc']}</div>
                <div class="bs-metric-value" style="color:#a78bfa;">{arc_display_name}</div>
            </div>
            <div class="bs-metric">
                <div class="bs-metric-label">{T['hero_words']}</div>
                <div class="bs-metric-value">{total_words:,}</div>
            </div>
            <div class="bs-metric">
                <div class="bs-metric-label">{T['hero_chunks']}</div>
                <div class="bs-metric-value">{len(chunks)}</div>
            </div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Save button
save_col, _ = st.columns([1, 5])
if save_col.button(T["save_btn"]):
    result = AnalysisResult.create(
        book_title=book_title,
        chunk_strategy=strategy,
        total_chunks=len(chunks),
        total_words=total_words,
        arc_pattern=arc.value,
        emotion_scores=emotion_scores,
        style_scores=style_scores,
    )
    repo.save(result)
    save_col.success(T["saved_ok"])

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

tab_overview, tab_heatmap, tab_timeline, tab_style, tab_arc, tab_export, tab_chunks = st.tabs(
    [
        T["tab_overview"], T["tab_heatmap"], T["tab_timeline"], T["tab_style"],
        T["tab_arc"], T["tab_export"], T["tab_chunks"],
    ]
)

# --- Overview ---------------------------------------------------------------
with tab_overview:
    st.markdown(f"<p class='bs-desc'>{T['overview_avg_desc']}</p>", unsafe_allow_html=True)

    if emotion_scores:
        avg_data_raw = {
            e: sum(getattr(s, e) for s in emotion_scores) / len(emotion_scores)
            for e in _EMOTION_FIELDS
        }
        # Sort descending and translate labels
        sorted_emotions = sorted(avg_data_raw.items(), key=lambda kv: kv[1], reverse=True)
        avg_data_translated = {
            T["emotion_names"].get(k, k.capitalize()): round(v, 4)
            for k, v in sorted_emotions
        }
        st.subheader(T["overview_avg_emotions"])
        st.bar_chart(avg_data_translated)

# --- Heatmap ----------------------------------------------------------------
with tab_heatmap:
    st.markdown(f"<p class='bs-desc'>{T['heatmap_desc']}</p>", unsafe_allow_html=True)
    heatmap_data = ChartDataAdapter.emotion_heatmap(emotion_scores, chunks=chunks)
    fig_heatmap = EmotionHeatmapRenderer().render(heatmap_data)
    st.plotly_chart(fig_heatmap, use_container_width=True)

# --- Emotion Timeline -------------------------------------------------------
with tab_timeline:
    st.markdown(f"<p class='bs-desc'>{T['timeline_desc']}</p>", unsafe_allow_html=True)

    emotion_display = {T["emotion_names"].get(e, e.capitalize()): e for e in _EMOTION_FIELDS}
    selected_labels = st.multiselect(
        T["timeline_select"],
        options=list(emotion_display.keys()),
        default=list(emotion_display.keys()),
        key="timeline_emotions",
    )
    selected_keys = [emotion_display[lbl] for lbl in selected_labels]

    if selected_keys:
        filtered = [
            EmotionScore(
                chunk_index=s.chunk_index,
                **{e: getattr(s, e) for e in selected_keys},
            )
            for s in emotion_scores
        ]
        timeline_data = ChartDataAdapter.emotion_timeline(filtered)
        timeline_data.emotions = {
            k: v for k, v in timeline_data.emotions.items() if k in selected_keys
        }
        st.plotly_chart(EmotionTimelineRenderer().render(timeline_data), use_container_width=True)
    else:
        st.info(T["timeline_empty"])

# --- Style ------------------------------------------------------------------
with tab_style:
    st.markdown(f"<p class='bs-desc'>{T['style_desc']}</p>", unsafe_allow_html=True)

    if style_scores:
        radar_data = ChartDataAdapter.style_radar(style_scores)
        st.plotly_chart(StyleRadarRenderer().render(radar_data), use_container_width=True)

        st.subheader(T["style_over_time"])
        metric_keys = list(radar_data.raw_means.keys())
        metric_labels = {
            T["style_metric_names"].get(k, k.replace("_", " ").title()): k
            for k in metric_keys
        }
        selected_metric_label = st.selectbox(
            T["style_pick"],
            options=list(metric_labels.keys()),
            key="style_metric",
        )
        selected_metric_key = metric_labels[selected_metric_label]
        help_text = T["style_metric_help"].get(selected_metric_key, "")
        if help_text:
            st.markdown(f"<p class='bs-desc'>{help_text}</p>", unsafe_allow_html=True)
        st.line_chart({s.chunk_index: getattr(s, selected_metric_key) for s in style_scores})
    else:
        st.info(T["style_no_data"])

# --- Arc Pattern ------------------------------------------------------------
with tab_arc:
    st.markdown(f"<p class='bs-desc'>{T['arc_desc']}</p>", unsafe_allow_html=True)

    if len(emotion_scores) >= 6:
        arc_desc_text = T["arc_descriptions"].get(arc.value, "")
        st.markdown(
            f"""
            <div style="background:rgba(124,58,237,0.15);border:1px solid #7c3aed;
                        border-radius:12px;padding:1rem 1.25rem;margin-bottom:1rem;">
                <div style="font-size:1.4rem;font-weight:700;color:#a78bfa;
                            margin-bottom:0.4rem;">{arc_display_name}</div>
                <div style="color:#cbd5e1;font-size:0.95rem;">{arc_desc_text}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        valences = arc_classifier.valence_series(emotion_scores)
        st.subheader(T["arc_valence_title"])
        st.markdown(f"<p class='bs-desc'>{T['arc_valence_caption']}</p>", unsafe_allow_html=True)
        st.line_chart({i: v for i, v in enumerate(valences)})
    else:
        st.info(T["arc_short"])

# --- Export -----------------------------------------------------------------
with tab_export:
    st.subheader(T["export_title"])

    result = AnalysisResult.create(
        book_title=book_title,
        chunk_strategy=strategy,
        total_chunks=len(chunks),
        total_words=total_words,
        arc_pattern=arc.value,
        emotion_scores=emotion_scores,
        style_scores=style_scores,
    )

    col_e, col_s, col_j, col_md = st.columns(4)
    col_e.download_button(
        label=T["export_emotions_csv"],
        data=result.to_csv_emotion(),
        file_name=f"{result.book_title}_emotions.csv",
        mime="text/csv",
    )
    col_s.download_button(
        label=T["export_style_csv"],
        data=result.to_csv_style(),
        file_name=f"{result.book_title}_style.csv",
        mime="text/csv",
    )
    col_j.download_button(
        label=T["export_json"],
        data=result.model_dump_json(indent=2),
        file_name=f"{result.book_title}_analysis.json",
        mime="application/json",
    )
    col_md.download_button(
        label=T["export_md"],
        data=result.to_markdown_report(),
        file_name=f"{result.book_title}_report.md",
        mime="text/markdown",
    )

# --- Chunks -----------------------------------------------------------------
with tab_chunks:
    st.subheader(T["chunks_title"])

    if not emotion_scores:
        st.info(T["chunks_no_match"])
    else:
        chunk_idx = st.slider(T["chunks_slider"], 0, len(chunks) - 1, 0, key="chunk_slider")
        sel_chunk = chunks[chunk_idx]
        sel_emotion = next((s for s in emotion_scores if s.chunk_index == chunk_idx), None)
        sel_style = next((s for s in style_scores if s.chunk_index == chunk_idx), None)

        st.markdown(
            f"**{T['chunks_header'].format(chunk_idx, sel_chunk.word_count)}**"
        )

        col_e, col_s = st.columns(2)

        with col_e:
            st.markdown(f"**{T['chunks_emotion_header']}**")
            if sel_emotion:
                score_dict = {k: v for k, v in sel_emotion.to_dict().items() if v > 0}
                if score_dict:
                    translated = {
                        T["emotion_names"].get(k, k.capitalize()): v
                        for k, v in sorted(score_dict.items(), key=lambda kv: kv[1], reverse=True)
                    }
                    st.bar_chart(translated)
                else:
                    st.caption(T["chunks_no_match"])

        with col_s:
            st.markdown(f"**{T['chunks_style_header']}**")
            if sel_style:
                st.table({
                    T["style_metric_names"].get(k, k.replace("_", " ").title()): [f"{v:.3f}"]
                    for k, v in sel_style.to_dict().items()
                })

        with st.expander(T["chunks_show_text"], expanded=False):
            st.write(sel_chunk.text[:2000] + ("…" if len(sel_chunk.text) > 2000 else ""))
