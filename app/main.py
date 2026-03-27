"""BookScope — Streamlit entry point (v0.4.0.0: Quick Insight + Full Analysis).

Run with:
    streamlit run app/main.py
"""

# Bootstrap NLTK corpora before any NLP imports (safe no-op if already present)
from bookscope.utils import ensure_nltk_data

ensure_nltk_data()

# Fix langdetect non-determinism before first import
from langdetect import DetectorFactory  # noqa: E402

DetectorFactory.seed = 0

import html as _html  # noqa: E402

import streamlit as st  # noqa: E402

from bookscope.app_utils import (  # noqa: E402  # noqa: E402
    get_lang,
    get_mode,
    inject_fonts,
    set_lang,
    set_mode,
)
from bookscope.insights import (  # noqa: E402
    compute_readability,
    compute_sparkline_points,
    extract_character_names,
    extract_key_themes,
    first_person_density,
)
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
        "load_btn": "▶ Load",
        "loaded_badge": "📂 Viewing saved analysis",
        "loaded_clear": "× New analysis",
        "chunks_unavailable": "Block text is not available for saved analyses.",
        "welcome_title": "What story hides in your book?",
        "welcome_body": (
            "Upload a **.txt**, **.epub**, or **.pdf** file — or paste a URL — "
            "to reveal the emotional journey hidden inside."
        ),
        "try_demo": "📖 Try with a demo book",
        "demo_badge": "🎭 Viewing demo: The Lighthouse Keeper's Last Storm",
        "analysing": "Reading your book…",
        "no_chunks_warning": "No text blocks produced. Try lowering the minimum word count.",
        "url_error": "Could not fetch URL: {}",
        "detected_lang": "Detected language",
        "save_btn": "💾 Save analysis",
        "saved_ok": "Saved!",
        # Hero card
        "hero_sentence": (
            "This story is primarily driven by <strong>{emotion}</strong>,"
            " following {article} <strong>{arc}</strong> arc across {chunks} blocks."
        ),
        "hero_dominant": "Dominant emotion",
        "hero_arc": "Story arc",
        "hero_words": "Total words",
        "hero_chunks": "Text blocks",
        # Mode toggle
        "mode_quick": "Quick Insight",
        "mode_full": "Full Analysis",
        # Book type
        "book_type_label": "Book type",
        "type_fiction": "📚 Fiction",
        "type_academic": "🎓 Academic",
        "type_essay": "✍️ Essay/Memoir",
        # Quick Insight — fiction
        "qi_fi_headline_label": "STORY PROFILE",
        "qi_fi_chars_label": "KEY CHARACTERS",
        "qi_fi_chars_en_only": "Character detection: English only",
        "qi_fi_shape_label": "STORY SHAPE",
        "qi_fi_style_label": "WRITING STYLE",
        # Quick Insight — academic
        "qi_ac_headline_label": "READING PROFILE",
        "qi_ac_read_time": "~{min} min read",
        "qi_ac_themes_label": "CORE CONCEPTS",
        "qi_ac_no_themes": "Not enough text for theme extraction",
        "qi_ac_strategy_label": "READING STRATEGY",
        "qi_ac_linear": "Linear reading recommended",
        "qi_ac_skimmable": "Can skim — key ideas front-loaded",
        "qi_ac_stance_label": "AUTHOR STANCE",
        "qi_ac_polemical": "Polemical",
        "qi_ac_constructive": "Constructive",
        "qi_ac_cautionary": "Cautionary",
        "qi_ac_informative": "Informative",
        # Quick Insight — essay
        "qi_es_headline_label": "VOICE PROFILE",
        "qi_es_journey_label": "AUTHOR JOURNEY",
        "qi_es_voice_label": "VOICE FINGERPRINT",
        "qi_es_intimacy_label": "INTIMACY",
        # Who it's for
        "qi_for_you_label": "Who it's for",
        # Readability labels
        "readable_accessible": "Accessible",
        "readable_moderate": "Moderate",
        "readable_dense": "Dense",
        "readable_specialist": "Specialist",
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
        "load_btn": "▶ 加载",
        "loaded_badge": "📂 正在查看已保存的分析",
        "loaded_clear": "× 新建分析",
        "chunks_unavailable": "保存的分析不包含原始文本块。",
        "try_demo": "📖 用示例书籍体验",
        "demo_badge": "🎭 演示模式：《灯塔守望者的最后一夜》",
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
            "这本书的主导情感是 <strong>{emotion}</strong>，"
            "故事走向为 <strong>{arc}</strong>，共分析了 {chunks} 个文本块。"
        ),
        "hero_dominant": "主导情感",
        "hero_arc": "故事走向",
        "hero_words": "总字数",
        "hero_chunks": "文本块数",
        # Mode toggle
        "mode_quick": "快速洞察",
        "mode_full": "完整分析",
        # Book type
        "book_type_label": "书籍类型",
        "type_fiction": "📚 小说",
        "type_academic": "🎓 学术 · 非虚构",
        "type_essay": "✍️ 随笔 · 回忆录",
        # Quick Insight — fiction
        "qi_fi_headline_label": "故事画像",
        "qi_fi_chars_label": "主要人物",
        "qi_fi_chars_en_only": "人物检测仅支持英文书籍",
        "qi_fi_shape_label": "故事形状",
        "qi_fi_style_label": "写作风格",
        # Quick Insight — academic
        "qi_ac_headline_label": "阅读画像",
        "qi_ac_read_time": "约 {min} 分钟",
        "qi_ac_themes_label": "核心概念",
        "qi_ac_no_themes": "文本量不足，无法提取主题",
        "qi_ac_strategy_label": "阅读策略",
        "qi_ac_linear": "建议线性阅读",
        "qi_ac_skimmable": "可跳读，核心论点在前",
        "qi_ac_stance_label": "作者立场",
        "qi_ac_polemical": "论战型",
        "qi_ac_constructive": "建设型",
        "qi_ac_cautionary": "警示型",
        "qi_ac_informative": "陈述型",
        # Quick Insight — essay
        "qi_es_headline_label": "声音画像",
        "qi_es_journey_label": "作者历程",
        "qi_es_voice_label": "声音指纹",
        "qi_es_intimacy_label": "亲密度",
        # Who it's for
        "qi_for_you_label": "适合谁读",
        # Readability labels
        "readable_accessible": "通俗易读",
        "readable_moderate": "一般难度",
        "readable_dense": "较有难度",
        "readable_specialist": "专业级",
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
        # Arc descriptions
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
        "load_btn": "▶ 読み込む",
        "loaded_badge": "📂 保存済み分析を表示中",
        "loaded_clear": "× 新規分析",
        "chunks_unavailable": "保存済み分析にはブロックテキストが含まれません。",
        "try_demo": "📖 デモ本を試す",
        "demo_badge": "🎭 デモ表示中：「灯台守の最後の嵐」",
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
            "この本の主要感情は <strong>{emotion}</strong> で、"
            "<strong>{arc}</strong> の弧パターンが {chunks} ブロックにわたって検出されました。"
        ),
        "hero_dominant": "主要感情",
        "hero_arc": "物語の弧",
        "hero_words": "総語数",
        "hero_chunks": "チャンク数",
        # Mode toggle
        "mode_quick": "クイック洞察",
        "mode_full": "詳細分析",
        # Book type
        "book_type_label": "書籍タイプ",
        "type_fiction": "📚 小説",
        "type_academic": "🎓 学術・ノンフィクション",
        "type_essay": "✍️ エッセイ・回想録",
        # Quick Insight — fiction
        "qi_fi_headline_label": "ストーリープロフィール",
        "qi_fi_chars_label": "主要人物",
        "qi_fi_chars_en_only": "人物検出は英語のみ対応",
        "qi_fi_shape_label": "ストーリーシェイプ",
        "qi_fi_style_label": "文体スタイル",
        # Quick Insight — academic
        "qi_ac_headline_label": "読書プロフィール",
        "qi_ac_read_time": "約 {min} 分",
        "qi_ac_themes_label": "コアコンセプト",
        "qi_ac_no_themes": "テーマ抽出に十分なテキスト量がありません",
        "qi_ac_strategy_label": "読み方戦略",
        "qi_ac_linear": "通読を推奨",
        "qi_ac_skimmable": "流し読み可 — 要点は前半に集中",
        "qi_ac_stance_label": "著者のスタンス",
        "qi_ac_polemical": "論争的",
        "qi_ac_constructive": "建設的",
        "qi_ac_cautionary": "警告的",
        "qi_ac_informative": "情報提供型",
        # Quick Insight — essay
        "qi_es_headline_label": "ボイスプロフィール",
        "qi_es_journey_label": "著者の旅",
        "qi_es_voice_label": "声紋",
        "qi_es_intimacy_label": "親密度",
        # Who it's for
        "qi_for_you_label": "こんな人に",
        # Readability labels
        "readable_accessible": "読みやすい",
        "readable_moderate": "普通",
        "readable_dense": "難しい",
        "readable_specialist": "専門的",
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
        # Arc descriptions
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
    "disgust": "#84cc16",
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

# ── Emotional genre mapping (fiction, EN only) ───────────────────────────────
# (arc.value, top_emotion_key) → (label_en, label_zh, label_ja, for_you_en)
_EMOTIONAL_GENRE: dict[tuple[str, str], tuple[str, str, str, str]] = {
    ("Icarus",         "fear"):    ("Psychological Thriller", "心理悬疑", "心理スリラー",
                                   "For readers who can handle dark, relentless tension."),
    ("Icarus",         "sadness"): ("Tragic Drama", "悲情剧", "悲劇",
                                   "For readers drawn to emotional depth and catharsis."),
    ("Icarus",         "anger"):   ("Dark Satire", "黑色讽刺", "ダークサタイア",
                                   "For readers who appreciate biting social commentary."),
    ("Cinderella",     "joy"):     ("Feel-Good Story", "励志故事", "ハートウォーミング",
                                   "For readers who love comeback stories with hopeful endings."),
    ("Rags to Riches", "joy"):     ("Coming-of-Age", "成长故事", "成長物語",
                                   "For readers who find joy in watching characters grow."),
    ("Rags to Riches", "trust"):   ("Inspiring Journey", "励志旅程", "インスピレーション",
                                   "For readers looking for stories of perseverance."),
    ("Man in a Hole",  "fear"):    ("Survival Thriller", "生存悬疑", "サバイバル",
                                   "For readers who thrive on high-stakes suspense."),
    ("Man in a Hole",  "sadness"): ("Redemption Story", "救赎故事", "救済物語",
                                   "For readers moved by stories of recovery and second chances."),
    ("Oedipus",        "sadness"): ("Literary Tragedy", "文学悲剧", "文学的悲劇",
                                   "For readers who value emotional truth over happy endings."),
    ("Riches to Rags", "anger"):   ("Social Critique", "社会批判", "社会批評",
                                   "For readers interested in power, justice, and society."),
    ("Riches to Rags", "sadness"): ("Fall from Grace", "英雄末路", "転落の物語",
                                   "For readers fascinated by the fragility of success."),
}
_DEFAULT_GENRE = ("Emotional Fiction", "情感小说", "感情的小説",
                  "For readers who enjoy character-driven emotional journeys.")

# ── Book type accent colors ──────────────────────────────────────────────────
_TYPE_COLOR = {
    "fiction":  "#f97316",  # orange
    "academic": "#3b82f6",  # blue
    "essay":    "#22c55e",  # green
}

# ---------------------------------------------------------------------------
# CSS injection
# ---------------------------------------------------------------------------

st.markdown("""
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
# Quick Insight renderer
# ---------------------------------------------------------------------------


def _sparkline_svg(points: str, color: str = "#a78bfa", width: int = 200, height: int = 40) -> str:
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg" style="display:block;margin-top:.4rem">'
        f'<defs><linearGradient id="spark-grad" x1="0" y1="0" x2="1" y2="0">'
        f'<stop offset="0%" stop-color="#22c55e"/>'
        f'<stop offset="100%" stop-color="#ef4444"/>'
        f'</linearGradient></defs>'
        f'<polyline points="{_html.escape(points)}" '
        f'fill="none" stroke="url(#spark-grad)" stroke-width="2" stroke-linejoin="round"/>'
        f'</svg>'
    )


def render_quick_insight(
    book_type: str,
    book_title: str,
    arc_value: str,
    arc_display_name: str,
    top_emotion_key: str,
    top_emotion_name: str,
    top_emotion_color: str,
    total_words: int,
    chunks,
    emotion_scores,
    style_scores,
    valence_series: list[float],
    detected_lang: str,
    ui_lang: str,
    T: dict,
) -> None:
    """Render Quick Insight cards for the given book type."""
    import html as h

    type_color = _TYPE_COLOR.get(book_type, "#7c3aed")

    # Session-keyed animation (AF-10, AF-13)
    anim_key = f"{book_title}_{book_type}"
    is_first = st.session_state.get("_insight_rendered_for") != anim_key
    if is_first:
        st.session_state["_insight_rendered_for"] = anim_key
    card_cls = (
        "bs-insight-card bs-insight-card-animate" if is_first
        else "bs-insight-card bs-no-animate"
    )
    headline_cls = (
        "bs-insight-headline-text bs-insight-headline-text-animate" if is_first
        else "bs-insight-headline-text bs-no-animate"
    )

    # ── FICTION ──────────────────────────────────────────────────────────────
    if book_type == "fiction":
        # Genre label (EN only, TD-4)
        if ui_lang == "en":
            genre_tuple = _EMOTIONAL_GENRE.get(
                (arc_value, top_emotion_key), _DEFAULT_GENRE
            )
            genre_label = genre_tuple[0]
            headline_text = (
                f"{h.escape(genre_label)} — "
                f"{h.escape(top_emotion_name)}-driven {h.escape(arc_display_name)} arc"
            )
            for_you_text = genre_tuple[3]
        else:
            lang_idx = {"zh": 1, "ja": 2}.get(ui_lang, 0)
            headline_text = f"{h.escape(arc_display_name)} — {h.escape(top_emotion_name)}"
            for_you_text = ""

        # Headline card
        st.markdown(
            f'<div class="bs-insight-headline" style="border-left:4px solid {type_color};">'
            f'<div class="bs-insight-headline-label">{h.escape(T["qi_fi_headline_label"])}</div>'
            f'<div class="{headline_cls}">{headline_text}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # Card 1: Key Characters
        chars = extract_character_names(chunks, lang=detected_lang) if chunks is not None else []
        if detected_lang not in ("zh", "ja", "ko"):
            if chars:
                chars_html = (
                    '<div class="bs-tag-row">'
                    + "".join(f'<span class="bs-tag">{h.escape(c)}</span>' for c in chars)
                    + "</div>"
                )
                chars_sub = ""
            else:
                # Fallback: show top emotion words
                top_emotions = sorted(
                    [(e, sum(getattr(s, e) for s in emotion_scores) / len(emotion_scores))
                     for e in _EMOTION_FIELDS],
                    key=lambda x: -x[1]
                )[:3]
                chars_html = '<div class="bs-tag-row">' + "".join(
                    f'<span class="bs-tag">{h.escape(T["emotion_names"].get(e, e))}</span>'
                    for e, _ in top_emotions
                ) + "</div>"
                chars_sub = h.escape(T.get("qi_fi_top_emotions_fallback", "Top emotions"))
        else:
            chars_html = f'<div class="bs-insight-card-sub">{h.escape(T["qi_fi_chars_en_only"])}</div>'  # noqa: E501
            chars_sub = ""

        # Card 2: Story Shape (sparkline)
        spark_pts = compute_sparkline_points(valence_series)
        spark_svg = _sparkline_svg(spark_pts)
        shape_sub = h.escape(arc_display_name)

        # Card 3: Writing Style
        if style_scores:
            avg_ttr = sum(s.ttr for s in style_scores) / len(style_scores)
            avg_sent = sum(s.avg_sentence_length for s in style_scores) / len(style_scores)
            if avg_ttr > 0.65:
                vocab_desc = "Rich vocabulary"
            elif avg_ttr > 0.45:
                vocab_desc = "Moderate vocabulary"
            else:
                vocab_desc = "Focused vocabulary"
            if avg_sent > 20:
                sent_desc = "long, complex sentences"
            elif avg_sent > 12:
                sent_desc = "balanced sentence length"
            else:
                sent_desc = "short, punchy sentences"
            style_val = h.escape(vocab_desc)
            style_sub = h.escape(sent_desc)
        else:
            style_val = "—"
            style_sub = ""

        # 3-col grid
        st.markdown(
            f'<div class="bs-insight-grid" style="--bs-type-color:{type_color};">'
            # Card 1
            f'<div class="{card_cls}">'
            f'<div class="bs-insight-card-label">{h.escape(T["qi_fi_chars_label"])}</div>'
            f'<div class="bs-insight-card-value">{chars_html}</div>'
            f'{"<div class=bs-insight-card-sub>" + chars_sub + "</div>" if chars_sub else ""}'
            f'</div>'
            # Card 2
            f'<div class="{card_cls}">'
            f'<div class="bs-insight-card-label">{h.escape(T["qi_fi_shape_label"])}</div>'
            f'<div class="bs-insight-card-value">{shape_sub}</div>'
            f'{spark_svg}'
            f'</div>'
            # Card 3
            f'<div class="{card_cls}">'
            f'<div class="bs-insight-card-label">{h.escape(T["qi_fi_style_label"])}</div>'
            f'<div class="bs-insight-card-value">{style_val}</div>'
            f'<div class="bs-insight-card-sub">{style_sub}</div>'
            f'</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # For-you card
        if for_you_text:
            st.markdown(
                f'<div class="bs-for-you">'
                f'<div class="bs-for-you-icon">📖</div>'
                f'<div class="bs-for-you-text"><strong>{h.escape(T["qi_for_you_label"])}:</strong> '
                f'{h.escape(for_you_text)}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    # ── ACADEMIC ─────────────────────────────────────────────────────────────
    elif book_type == "academic":
        _, readability_label, confidence = compute_readability(style_scores, ui_lang)
        reading_min = max(1, total_words // 238)
        read_time_str = T["qi_ac_read_time"].format(min=reading_min)

        headline_text = f"{h.escape(readability_label)} · {h.escape(read_time_str)}"

        st.markdown(
            f'<div class="bs-insight-headline" style="border-left:4px solid {type_color};">'
            f'<div class="bs-insight-headline-label">{h.escape(T["qi_ac_headline_label"])}</div>'
            f'<div class="{headline_cls}">{headline_text}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # Card 1: Core Concepts
        themes = (
            extract_key_themes(chunks, style_scores)
            if (chunks is not None and style_scores) else []
        )
        if themes:
            themes_html = (
                '<div class="bs-tag-row">'
                + "".join(f'<span class="bs-tag">{h.escape(t)}</span>' for t in themes)
                + "</div>"
            )
        else:
            themes_html = f'<div class="bs-insight-card-sub">{h.escape(T["qi_ac_no_themes"])}</div>'

        # Card 2: Reading Strategy (anticipation front-loaded?)
        if emotion_scores:
            n = len(emotion_scores)
            first_half_ant = sum(s.anticipation for s in emotion_scores[: n // 2]) / max(n // 2, 1)
            second_half_ant = (
                sum(s.anticipation for s in emotion_scores[n // 2 :]) / max(n - n // 2, 1)
            )
            strategy_val = (
                T["qi_ac_skimmable"] if first_half_ant >= second_half_ant
                else T["qi_ac_linear"]
            )
        else:
            strategy_val = T["qi_ac_linear"]

        # Card 3: Author Stance
        if emotion_scores:
            avg_anger  = sum(s.anger   for s in emotion_scores) / len(emotion_scores)
            avg_disgust = sum(s.disgust for s in emotion_scores) / len(emotion_scores)
            avg_trust  = sum(s.trust   for s in emotion_scores) / len(emotion_scores)
            avg_ant    = sum(s.anticipation for s in emotion_scores) / len(emotion_scores)
            if avg_anger + avg_disgust > 0.35:
                stance = T["qi_ac_polemical"]
            elif avg_trust + avg_ant > 0.45:
                stance = T["qi_ac_constructive"]
            elif avg_anger > 0.20:
                stance = T["qi_ac_cautionary"]
            else:
                stance = T["qi_ac_informative"]
        else:
            stance = T["qi_ac_informative"]

        st.markdown(
            f'<div class="bs-insight-grid" style="--bs-type-color:{type_color};">'
            f'<div class="{card_cls}">'
            f'<div class="bs-insight-card-label">{h.escape(T["qi_ac_themes_label"])}</div>'
            f'<div class="bs-insight-card-value">{themes_html}</div>'
            f'</div>'
            f'<div class="{card_cls}">'
            f'<div class="bs-insight-card-label">{h.escape(T["qi_ac_strategy_label"])}</div>'
            f'<div class="bs-insight-card-value">{h.escape(strategy_val)}</div>'
            f'</div>'
            f'<div class="{card_cls}">'
            f'<div class="bs-insight-card-label">{h.escape(T["qi_ac_stance_label"])}</div>'
            f'<div class="bs-insight-card-value">{h.escape(stance)}</div>'
            f'</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # For-you card
        audience_map = {
            T["readable_accessible"]: ("general readers new to the topic"
                                       if ui_lang == "en" else
                                       "初学者和对该主题感兴趣的普通读者" if ui_lang == "zh" else
                                       "このテーマに初めて触れる一般読者"),
            T["readable_moderate"]:   ("informed readers with some background"
                                       if ui_lang == "en" else
                                       "有一定背景知识的读者" if ui_lang == "zh" else
                                       "基礎知識を持つ読者"),
            T["readable_dense"]:      ("subject-matter experts"
                                       if ui_lang == "en" else
                                       "具备专业背景的读者" if ui_lang == "zh" else
                                       "専門知識を持つ読者"),
            T["readable_specialist"]: ("domain specialists and researchers"
                                       if ui_lang == "en" else
                                       "领域专家和研究人员" if ui_lang == "zh" else
                                       "専門家および研究者"),
        }
        audience = audience_map.get(readability_label, "")
        if audience and confidence >= 0.3:
            for_you_body = (
                f"For {audience}." if ui_lang == "en" else
                f"适合{audience}。" if ui_lang == "zh" else
                f"{audience}向け。"
            )
            st.markdown(
                f'<div class="bs-for-you">'
                f'<div class="bs-for-you-icon">📚</div>'
                f'<div class="bs-for-you-text"><strong>{h.escape(T["qi_for_you_label"])}:</strong> '
                f'{h.escape(for_you_body)}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    # ── ESSAY / MEMOIR ────────────────────────────────────────────────────────
    else:
        fp = first_person_density(chunks, detected_lang) if chunks is not None else 0.0
        fp_pct = int(fp * 100)

        # Headline
        if style_scores:
            avg_adj = sum(s.adj_ratio for s in style_scores) / len(style_scores)
            if avg_adj > 0.08:
                voice_type = ("Sensory" if ui_lang == "en" else
                              "感官型" if ui_lang == "zh" else "感覚的")
            elif fp > 0.08:
                voice_type = ("Intimate" if ui_lang == "en" else
                              "亲密型" if ui_lang == "zh" else "親密")
            else:
                voice_type = ("Observational" if ui_lang == "en" else
                              "观察型" if ui_lang == "zh" else "観察的")
        else:
            voice_type = ("Personal" if ui_lang == "en" else
                          "个人型" if ui_lang == "zh" else "個人的")

        headline_text = f"{h.escape(voice_type)} · {h.escape(arc_display_name)}"

        st.markdown(
            f'<div class="bs-insight-headline" style="border-left:4px solid {type_color};">'
            f'<div class="bs-insight-headline-label">{h.escape(T["qi_es_headline_label"])}</div>'
            f'<div class="{headline_cls}">{headline_text}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # Card 1: Author Journey (sparkline + arc as personal journey)
        spark_pts = compute_sparkline_points(valence_series)
        spark_svg = _sparkline_svg(spark_pts, color="#22c55e")
        arc_as_journey = {
            "Rags to Riches": ("from darkness into light", "从黑暗走向光明", "暗闇から光へ"),
            "Riches to Rags": ("a descent into difficulty", "走向困境的历程", "困難への下降"),
            "Man in a Hole":  ("a fall and comeback", "跌落后的重新站起", "転落と回復"),
            "Icarus":         ("early hope, late struggle", "先有希望后有挣扎", "希望の後に試練"),
            "Cinderella":     ("resilience through hardship", "坚韧穿越艰难", "困難を乗り越えた強さ"),  # noqa: E501
            "Oedipus":        ("hope between two struggles", "两段挣扎之间的希望", "二つの困難の間の希望"),  # noqa: E501
            "Unknown":        ("a complex personal journey", "复杂的个人旅程", "複雑な旅路"),
        }
        lang_idx = {"en": 0, "zh": 1, "ja": 2}.get(ui_lang, 0)
        journey_desc = arc_as_journey.get(  # noqa: E501
            arc_value, ("a personal journey", "个人旅程", "個人的旅")
        )[lang_idx]

        # Card 2: Voice Fingerprint
        if style_scores:
            avg_adj_r = sum(s.adj_ratio for s in style_scores) / len(style_scores)
            avg_adv_r = sum(s.adv_ratio for s in style_scores) / len(style_scores)
            avg_vrb_r = sum(s.verb_ratio for s in style_scores) / len(style_scores)
            if avg_adj_r > avg_adv_r and avg_adj_r > avg_vrb_r:
                dominant_voice = ("Descriptive" if ui_lang == "en" else
                                  "描述型" if ui_lang == "zh" else "描写的")
            elif avg_adv_r > avg_vrb_r:
                dominant_voice = ("Assertive" if ui_lang == "en" else
                                  "论断型" if ui_lang == "zh" else "断定的")
            else:
                dominant_voice = ("Narrative" if ui_lang == "en" else
                                  "叙述型" if ui_lang == "zh" else "物語的")
        else:
            dominant_voice = "—"

        # Card 3: Intimacy
        if ui_lang == "en":
            intimacy_val = f"{fp_pct}% first-person"
            if fp > 0.10:
                intimacy_sub = "Highly personal narration"
            elif fp > 0.04:
                intimacy_sub = "Balanced personal voice"
            else:
                intimacy_sub = "More distant, observational"
        elif ui_lang == "zh":
            intimacy_val = f"{fp_pct}% 第一人称"
            intimacy_sub = ("高度个人化叙述" if fp > 0.10 else
                            "个人视角与观察并重" if fp > 0.04 else
                            "相对客观的叙事视角")
        else:
            intimacy_val = f"{fp_pct}% 一人称"
            intimacy_sub = ("高度に個人的な語り" if fp > 0.10 else
                            "個人と観察のバランス" if fp > 0.04 else
                            "やや客観的な語り口")

        st.markdown(
            f'<div class="bs-insight-grid" style="--bs-type-color:{type_color};">'
            f'<div class="{card_cls}">'
            f'<div class="bs-insight-card-label">{h.escape(T["qi_es_journey_label"])}</div>'
            f'<div class="bs-insight-card-value">{h.escape(journey_desc)}</div>'
            f'{spark_svg}'
            f'</div>'
            f'<div class="{card_cls}">'
            f'<div class="bs-insight-card-label">{h.escape(T["qi_es_voice_label"])}</div>'
            f'<div class="bs-insight-card-value">{h.escape(dominant_voice)}</div>'
            f'</div>'
            f'<div class="{card_cls}">'
            f'<div class="bs-insight-card-label">{h.escape(T["qi_es_intimacy_label"])}</div>'
            f'<div class="bs-insight-card-value">{h.escape(intimacy_val)}</div>'
            f'<div class="bs-insight-card-sub">{h.escape(intimacy_sub)}</div>'
            f'</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # For-you card
        if fp > 0.10:
            for_you_body = (
                "For readers going through a similar personal transition." if ui_lang == "en" else
                "适合正在经历类似转变的读者。" if ui_lang == "zh" else
                "似たような人生の転換期にある読者に。"
            )
        elif fp > 0.04:
            for_you_body = (
                "For readers who value personal voice and reflection." if ui_lang == "en" else
                "适合欣赏个人视角与思考的读者。" if ui_lang == "zh" else
                "個人的な語り口と内省を大切にする読者に。"
            )
        else:
            for_you_body = (
                "For readers who appreciate thoughtful, essay-style observation." if ui_lang == "en" else  # noqa: E501
                "适合喜爱沉思式、散文风格写作的读者。" if ui_lang == "zh" else
                "思索的なエッセイスタイルの文章を好む読者に。"
            )
        st.markdown(
            f'<div class="bs-for-you">'
            f'<div class="bs-for-you-icon">✍️</div>'
            f'<div class="bs-for-you-text"><strong>{h.escape(T["qi_for_you_label"])}:</strong> '
            f'{h.escape(for_you_body)}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# Language + mode resolution (query_params persist across pages)
# ---------------------------------------------------------------------------

ui_lang = get_lang()
ui_mode = get_mode()
inject_fonts(ui_lang)
T = _STRINGS[ui_lang]

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
        index=lang_options.index(ui_lang),
        horizontal=True,
        key="lang_radio",
    )
    if selected_lang != ui_lang:
        set_lang(selected_lang)
        st.rerun()

    st.divider()
    st.markdown(f"### {T['sidebar_header']}")
    st.caption(T["sidebar_tagline"])

    # Book type selector (TD-1: before upload, in sidebar)
    book_type_opts = ["fiction", "academic", "essay"]
    book_type = st.radio(
        T["book_type_label"],
        options=book_type_opts,
        format_func=lambda x: T[f"type_{x}"],
        horizontal=True,
        key="book_type_radio",
    )

    st.divider()

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
            col1, col2, col3 = st.columns([3, 1, 1])
            col1.caption(p.stem)
            if col2.button(T["load_btn"], key=f"load_{p.name}"):
                st.session_state["_loaded_result"] = repo.load(p)
                st.rerun()
            if col3.button("🗑", key=f"del_{p.name}", help="Delete"):
                repo.delete(p)
                st.session_state.pop("_loaded_result", None)
                st.rerun()
    else:
        st.caption(T["no_saved"])

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
# Populate analysis data — from saved result OR from upload/URL
# ---------------------------------------------------------------------------

_from_saved = False
chunks = None  # may remain None when restoring from a saved result

# ── Demo mode branch ──────────────────────────────────────────────────────────
if _demo_mode and uploaded is None and not url_input and _loaded_result is None:
    import pathlib as _pl
    _demo_path = _pl.Path(__file__).parent / "demo_book.txt"
    _demo_bytes = _demo_path.read_bytes()
    with st.spinner(T["analysing"]):
        chunks, emotion_scores, style_scores, detected_lang = run_analysis(
            _demo_bytes, "The_Lighthouse_Keepers_Last_Storm.txt",
            strategy, chunk_size, min_words,
        )
    if not chunks:
        st.warning(T["no_chunks_warning"])
        st.stop()
    book_title = "The Lighthouse Keeper's Last Storm"
    n_chunks = len(chunks)
    total_words = sum(c.word_count for c in chunks)

elif _loaded_result is not None and uploaded is None and not url_input:
    emotion_scores = _loaded_result.emotion_scores
    style_scores = _loaded_result.style_scores
    book_title = _loaded_result.book_title
    detected_lang = _loaded_result.detected_lang
    n_chunks = _loaded_result.total_chunks
    total_words = _loaded_result.total_words
    _from_saved = True
else:
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

    n_chunks = len(chunks)
    total_words = sum(c.word_count for c in chunks)

# Show detected language in sidebar
with st.sidebar:
    st.divider()
    lang_label = T["lang_labels"].get(detected_lang, detected_lang)
    st.caption(f"{T['detected_lang']}: **{lang_label}**")

# Arc classification
arc_classifier = ArcClassifier()
arc = arc_classifier.classify(emotion_scores)
arc_display_name = _ARC_DISPLAY[ui_lang].get(arc.value, arc.value)

from collections import Counter  # noqa: E402

dominants = Counter(s.dominant_emotion for s in emotion_scores) if emotion_scores else Counter()
top_emotion_key = dominants.most_common(1)[0][0] if dominants else "joy"
top_emotion_name = T["emotion_names"].get(top_emotion_key, top_emotion_key.capitalize())
top_emotion_color = _EMOTION_COLORS.get(top_emotion_key, "#7c3aed")
top_emotion_icon = _EMOTION_ICONS.get(top_emotion_key, "✨")

# ---------------------------------------------------------------------------
# Hero card (XSS-safe via html.escape)
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

# Loaded badge + clear button (only shown when viewing a saved result)
if _from_saved:
    badge_col, clear_col, _ = st.columns([2, 1, 3])
    badge_col.info(T["loaded_badge"])
    if clear_col.button(T["loaded_clear"]):
        st.session_state.pop("_loaded_result", None)
        st.rerun()

# Save button (hidden when already viewing a saved result)
if not _from_saved:
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
    )

# ---------------------------------------------------------------------------
# Full Analysis mode — original 7 tabs (unchanged)
# ---------------------------------------------------------------------------

else:
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
            st.plotly_chart(
                EmotionTimelineRenderer().render(timeline_data), use_container_width=True
            )
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
            safe_arc_desc = _html.escape(arc_desc_text)
            st.markdown(
                f"""
                <div style="background:rgba(124,58,237,0.15);border:1px solid #7c3aed;
                            border-radius:12px;padding:1rem 1.25rem;margin-bottom:1rem;">
                    <div style="font-size:1.4rem;font-weight:700;color:#a78bfa;
                                margin-bottom:0.4rem;">{safe_arc_display}</div>
                    <div style="color:#cbd5e1;font-size:0.95rem;">{safe_arc_desc}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            valences = arc_classifier.valence_series(emotion_scores)
            st.subheader(T["arc_valence_title"])
            st.markdown(
                f"<p class='bs-desc'>{T['arc_valence_caption']}</p>", unsafe_allow_html=True
            )
            st.line_chart({i: v for i, v in enumerate(valences)})
        else:
            st.info(T["arc_short"])

    # --- Export -----------------------------------------------------------------
    with tab_export:
        st.subheader(T["export_title"])

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

        if chunks is None:
            st.info(T["chunks_unavailable"])
        elif not emotion_scores:
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
                        sorted_items = sorted(
                            score_dict.items(), key=lambda kv: kv[1], reverse=True
                        )
                        translated = {
                            T["emotion_names"].get(k, k.capitalize()): v
                            for k, v in sorted_items
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
