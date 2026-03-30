"""BookScope — i18n string dictionaries and arc display names."""

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
        # AI Narrative
        "qi_ai_narrative_label": "AI NARRATIVE",
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
        # AI Narrative
        "qi_ai_narrative_label": "AI 叙述",
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
        # AI Narrative
        "qi_ai_narrative_label": "AI ナレーション",
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
