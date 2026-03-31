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
        # AI options
        "ai_options_header": "AI options",
        "ai_model_label": "Narrative model",
        "ai_model_haiku": "Haiku — Fast",
        "ai_model_sonnet": "Sonnet — Quality",
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
        "hero_reading_time": "Reading time",
        "hero_reading_time_hr": "~{h}h {m}min",
        "hero_reading_time_min": "~{m} min",
        # Mode toggle
        "mode_quick": "Quick Insight",
        "mode_full": "Full Analysis",
        # Book type
        "book_type_label": "Book type",
        "type_fiction": "📚 Fiction",
        "type_academic": "🎓 Academic",
        "type_essay": "✍️ Essay/Memoir",
        # Quick Preview
        "btn_full_analysis": "📊 Analyze (Full)",
        "btn_quick_preview": "👁 Quick Preview",
        "btn_preview_needs_key": "Add ANTHROPIC_API_KEY to enable",
        "preview_panel_label": "👁 Quick Preview",
        "preview_unavailable": "Preview unavailable — add ANTHROPIC_API_KEY.",
        # Chat Tab
        "tab_chat": "💬 Chat",
        "chat_no_chunks": (
            "Chat requires re-analyzing the book. Raw text is not stored in saved analyses."
        ),
        "chat_no_key": "Chat requires an LLM key. Add ANTHROPIC_API_KEY to enable this tab.",
        "chat_input_label": "Ask a question about this book",
        "chat_input_placeholder": "What themes appear most often?",
        "chat_send_btn": "Send",
        "chat_error": "Sorry, I couldn't generate a response. Try again.",
        "chat_clear_btn": "Clear conversation",
        "chat_search_label": "Search in book",
        "chat_search_placeholder": "Enter keyword to search...",
        "chat_search_btn": "Search",
        "chat_search_results": "Found {n} match(es) for \"{kw}\"",
        "chat_search_no_results": "No matches found for \"{kw}\"",
        "chat_search_chunk": "Chunk {idx}",
        # Library Tab
        "tab_library": "📚 Library",
        "library_empty": "No analyses saved yet. Analyze a book to add it to your library.",
        "library_all_corrupted": "All saved analyses appear corrupted.",
        "library_title": "Your Book Library",
        "library_compare_title": "Compare Two Books",
        "library_compare_a": "Book A",
        "library_compare_b": "Book B",
        "library_compare_same": "Select two different books to compare.",
        "library_compare_no_data": "One of the selected books has no emotion data.",
        "library_notes_label": "📝 Notes",
        "library_notes_mood": "Mood rating (1 = difficult, 5 = loved it)",
        "library_notes_quote": "Most memorable quote",
        "library_notes_quote_placeholder": "A sentence that stayed with you...",
        "library_notes_save": "Save notes",
        "library_notes_saved": "Notes saved.",
        # Author / cross-book comparison
        "author_label": "Author name (optional)",
        "author_placeholder": "e.g. Jane Austen",
        "library_author_filter": "Filter by author",
        "library_author_all": "All authors",
        "library_author_unknown": "Unknown",
        "library_author_compare_title": "Author Cross-Book Comparison",
        "library_author_select": "Select author to compare",
        "library_author_compare_need_more": "Need at least 2 books by this author to compare.",
        "library_author_compare_no_data": "No emotion data available for this author's books.",
        # Writer mode / draft diagnosis
        "writer_mode_label": "✍️ Writer mode",
        "writer_mode_help": "Analyze your draft's emotional arc against classic story patterns.",
        "draft_diag_label": "DRAFT ARC DIAGNOSIS",
        "draft_diag_desc": "How your draft compares to the 6 classic emotional arc patterns.",
        "draft_diag_too_short": "Need at least 6 text blocks for arc diagnosis.",
        "draft_diag_closest": "Closest match: {pattern} ({score:.0%})",
        "draft_diag_tip_refine": (
            "Your arc is original — doesn't closely follow any classic pattern. "
            "Ask yourself: does the emotional journey match your intent?"
        ),
        "draft_diag_tip_rtr": (
            "Rising arc. Make early struggles vivid — the rise needs contrast to feel earned."
        ),
        "draft_diag_tip_r2r": (
            "Falling arc. Brief moments of hope prevent emotional numbness in readers."
        ),
        "draft_diag_tip_mih": (
            "Recovery arc. The lowest point must be unmistakable — "
            "readers need to feel the depth before the climb."
        ),
        "draft_diag_tip_icarus": (
            "Rise-fall arc. The turning point is everything — "
            "make the fall feel inevitable, not arbitrary."
        ),
        "draft_diag_tip_cinderella": (
            "Three-phase arc. Each phase shift should come from "
            "character choice, not plot convenience."
        ),
        "draft_diag_tip_oedipus": (
            "Complex arc. Use the middle rise as emotional breathing room — "
            "readers need relief before the final fall."
        ),
        # Share / publish
        "share_btn": "🔗 Share analysis",
        "share_btn_disabled": "Supabase not configured",
        "share_confirm_warning": (
            "Once shared, this link is permanent (revocation coming in v2.0)."
        ),
        "share_confirm_btn": "Yes, share publicly",
        "share_cancel": "Cancel",
        "share_success": "✅ Shared! Add this to your app URL:",
        "share_error": "Failed to share. Check your Supabase configuration.",
        "share_view_not_found": (
            "This analysis doesn't exist or hasn't been shared publicly."
        ),
        "share_view_footer": "Generated by BookScope",
        # Book Recommendations
        "qi_recs_label": "[Experimental] You might also like",
        "qi_recs_disclaimer": "AI suggestions — quality varies. Trust your own taste.",
        "qi_recs_unavailable": "Recommendations unavailable. Check LLM configuration.",
        # Fallback for character detection
        "qi_fi_top_emotions_fallback": "Top emotions",
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
        "export_card": "🖼️ Share card (.png)",
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
        # AI options
        "ai_options_header": "AI 选项",
        "ai_model_label": "叙述模型",
        "ai_model_haiku": "Haiku — 快速",
        "ai_model_sonnet": "Sonnet — 高质量",
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
        "hero_reading_time": "阅读时间",
        "hero_reading_time_hr": "约 {h} 小时 {m} 分钟",
        "hero_reading_time_min": "约 {m} 分钟",
        # Mode toggle
        "mode_quick": "快速洞察",
        "mode_full": "完整分析",
        # Book type
        "book_type_label": "书籍类型",
        "type_fiction": "📚 小说",
        "type_academic": "🎓 学术 · 非虚构",
        "type_essay": "✍️ 随笔 · 回忆录",
        # Quick Preview
        "btn_full_analysis": "📊 完整分析",
        "btn_quick_preview": "👁 快速预览",
        "btn_preview_needs_key": "添加 ANTHROPIC_API_KEY 以启用",
        "preview_panel_label": "👁 快速预览",
        "preview_unavailable": "预览不可用 — 请添加 ANTHROPIC_API_KEY。",
        # Chat Tab
        "tab_chat": "💬 对话",
        "chat_no_chunks": "对话功能需要重新分析本书。已保存的分析不包含原始文本。",
        "chat_no_key": "对话功能需要 LLM 密钥。请添加 ANTHROPIC_API_KEY。",
        "chat_input_label": "向这本书提问",
        "chat_input_placeholder": "这本书的主要主题是什么？",
        "chat_send_btn": "发送",
        "chat_error": "抱歉，无法生成回复，请重试。",
        "chat_clear_btn": "清除对话",
        "chat_search_label": "在书中搜索",
        "chat_search_placeholder": "输入关键词搜索...",
        "chat_search_btn": "搜索",
        "chat_search_results": "找到 {n} 处匹配「{kw}」",
        "chat_search_no_results": "未找到「{kw}」的匹配内容",
        "chat_search_chunk": "第 {idx} 块",
        # Library Tab
        "tab_library": "📚 书库",
        "library_empty": "还没有保存的分析。分析一本书后即可加入书库。",
        "library_all_corrupted": "所有已保存的分析文件均已损坏。",
        "library_title": "我的书库",
        "library_compare_title": "对比两本书",
        "library_compare_a": "书目 A",
        "library_compare_b": "书目 B",
        "library_compare_same": "请选择两本不同的书进行对比。",
        "library_compare_no_data": "所选书目之一没有情感数据。",
        "library_notes_label": "📝 读书笔记",
        "library_notes_mood": "心情评分（1 = 晦涩，5 = 爱不释手）",
        "library_notes_quote": "最难忘的一句话",
        "library_notes_quote_placeholder": "书中让你印象最深的句子...",
        "library_notes_save": "保存笔记",
        "library_notes_saved": "笔记已保存。",
        # Author / cross-book comparison
        "author_label": "作者名（可选）",
        "author_placeholder": "例如：鲁迅",
        "library_author_filter": "按作者筛选",
        "library_author_all": "全部作者",
        "library_author_unknown": "未知",
        "library_author_compare_title": "作者跨书对比",
        "library_author_select": "选择作者进行对比",
        "library_author_compare_need_more": "至少需要该作者的 2 本书才能对比。",
        "library_author_compare_no_data": "该作者的书籍暂无情感数据。",
        # Writer mode / draft diagnosis
        "writer_mode_label": "✍️ 作者模式",
        "writer_mode_help": "将你草稿的情感弧与六种经典故事模板对比分析。",
        "draft_diag_label": "草稿弧型诊断",
        "draft_diag_desc": "你的草稿情感弧与六种经典故事弧型的对比。",
        "draft_diag_too_short": "至少需要 6 个文本块才能进行弧型诊断。",
        "draft_diag_closest": "最接近：{pattern}（{score:.0%}）",
        "draft_diag_tip_refine": (
            "你的弧型很独特，与任何经典模式都不太相符。"
            "请思考：这条情感曲线是否符合你的创作意图？"
        ),
        "draft_diag_tip_rtr": (
            "上升弧。把早期的挣扎写得更鲜明——上升需要对比才能显得真实。"
        ),
        "draft_diag_tip_r2r": (
            "下降弧。短暂的希望时刻可以防止读者情感麻木。"
        ),
        "draft_diag_tip_mih": (
            "复苏弧。最低谷必须清晰可辨——读者需要感受到深度，才能感受到攀升。"
        ),
        "draft_diag_tip_icarus": (
            "先升后降弧。转折点至关重要——让下落显得不可避免，而非突兀。"
        ),
        "draft_diag_tip_cinderella": (
            "三段式弧型。每次转折都应源于人物选择，而非情节便利。"
        ),
        "draft_diag_tip_oedipus": (
            "复杂弧型。中段上升是读者的情感喘息空间——"
            "在最终跌落前给他们一些缓冲。"
        ),
        # Share / publish
        "share_btn": "🔗 生成分享链接",
        "share_btn_disabled": "未配置 Supabase",
        "share_confirm_warning": "一旦分享，链接永久有效（v2.0 支持撤回）。",
        "share_confirm_btn": "确认公开分享",
        "share_cancel": "取消",
        "share_success": "✅ 已分享！请将以下参数添加到应用网址：",
        "share_error": "分享失败，请检查 Supabase 配置。",
        "share_view_not_found": "此分析不存在或尚未公开分享。",
        "share_view_footer": "由 BookScope 生成",
        # Book Recommendations
        "qi_recs_label": "【实验功能】你可能也喜欢",
        "qi_recs_disclaimer": "AI 推荐，质量不一，请凭自己的判断。",
        "qi_recs_unavailable": "推荐功能不可用。请检查 LLM 配置。",
        # Fallback for character detection
        "qi_fi_top_emotions_fallback": "主要情感",
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
        "export_card": "🖼️ 分享卡片 (.png)",
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
        # AI options
        "ai_options_header": "AI オプション",
        "ai_model_label": "ナレーションモデル",
        "ai_model_haiku": "Haiku — 高速",
        "ai_model_sonnet": "Sonnet — 高品質",
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
        "hero_reading_time": "読書時間",
        "hero_reading_time_hr": "約{h}時間{m}分",
        "hero_reading_time_min": "約{m}分",
        # Mode toggle
        "mode_quick": "クイック洞察",
        "mode_full": "詳細分析",
        # Book type
        "book_type_label": "書籍タイプ",
        "type_fiction": "📚 小説",
        "type_academic": "🎓 学術・ノンフィクション",
        "type_essay": "✍️ エッセイ・回想録",
        # Quick Preview
        "btn_full_analysis": "📊 全文分析",
        "btn_quick_preview": "👁 クイックプレビュー",
        "btn_preview_needs_key": "ANTHROPIC_API_KEY を追加して有効化",
        "preview_panel_label": "👁 クイックプレビュー",
        "preview_unavailable": "プレビュー不可 — ANTHROPIC_API_KEY を追加してください。",
        # Chat Tab
        "tab_chat": "💬 チャット",
        "chat_no_chunks": (
            "チャットには本の再分析が必要です。保存済み分析には生テキストが含まれません。"
        ),
        "chat_no_key": "チャットには LLM キーが必要です。ANTHROPIC_API_KEY を追加してください。",
        "chat_input_label": "この本について質問する",
        "chat_input_placeholder": "最もよく登場するテーマは何ですか？",
        "chat_send_btn": "送信",
        "chat_error": "応答を生成できませんでした。もう一度お試しください。",
        "chat_clear_btn": "会話をクリア",
        "chat_search_label": "本文を検索",
        "chat_search_placeholder": "キーワードを入力...",
        "chat_search_btn": "検索",
        "chat_search_results": "「{kw}」が {n} か所見つかりました",
        "chat_search_no_results": "「{kw}」は見つかりませんでした",
        "chat_search_chunk": "チャンク {idx}",
        # Library Tab
        "tab_library": "📚 ライブラリ",
        "library_empty": "まだ保存された分析がありません。本を分析してライブラリに追加しましょう。",
        "library_all_corrupted": "保存済みの分析ファイルがすべて破損しています。",
        "library_title": "マイライブラリ",
        "library_compare_title": "2冊を比較",
        "library_compare_a": "本 A",
        "library_compare_b": "本 B",
        "library_compare_same": "比較するには2冊の異なる本を選んでください。",
        "library_compare_no_data": "選択した本の一方に感情データがありません。",
        "library_notes_label": "📝 読書メモ",
        "library_notes_mood": "気分スコア（1 = 難解、5 = 大好き）",
        "library_notes_quote": "最も印象的なフレーズ",
        "library_notes_quote_placeholder": "心に残った一文...",
        "library_notes_save": "メモを保存",
        "library_notes_saved": "メモを保存しました。",
        # Author / cross-book comparison
        "author_label": "作者名（任意）",
        "author_placeholder": "例：夏目漱石",
        "library_author_filter": "作者で絞り込む",
        "library_author_all": "すべての作者",
        "library_author_unknown": "不明",
        "library_author_compare_title": "作者の作品比較",
        "library_author_select": "比較する作者を選択",
        "library_author_compare_need_more": "比較するには同じ作者の本が2冊以上必要です。",
        "library_author_compare_no_data": "この作者の作品に感情データがありません。",
        # Writer mode / draft diagnosis
        "writer_mode_label": "✍️ ライターモード",
        "writer_mode_help": "草稿の感情弧を6つのクラシックストーリーパターンと比較します。",
        "draft_diag_label": "草稿弧型診断",
        "draft_diag_desc": "あなたの草稿の感情弧を6つのクラシックパターンと比較します。",
        "draft_diag_too_short": "弧型診断には少なくとも6つのテキストブロックが必要です。",
        "draft_diag_closest": "最も近いパターン：{pattern}（{score:.0%}）",
        "draft_diag_tip_refine": (
            "あなたの弧型は独自性があり、どのクラシックパターンにも近くありません。"
            "この感情の流れは、あなたの意図に合っているか確認してみてください。"
        ),
        "draft_diag_tip_rtr": (
            "上昇弧。序盤の苦境を鮮明に描くことで、上昇がより説得力を持ちます。"
        ),
        "draft_diag_tip_r2r": (
            "下降弧。希望の瞬間を挟むことで、読者の感情的な麻痺を防げます。"
        ),
        "draft_diag_tip_mih": (
            "回復弧。最低点を明確に描くことが重要です——"
            "深さを感じてこそ、上昇が意味を持ちます。"
        ),
        "draft_diag_tip_icarus": (
            "上昇→下降弧。転換点が鍵です——"
            "下降は必然的に感じられる必要があります。"
        ),
        "draft_diag_tip_cinderella": (
            "三段階弧。各転換はプロットの都合ではなく、"
            "キャラクターの選択から生まれるべきです。"
        ),
        "draft_diag_tip_oedipus": (
            "複雑な弧型。中盤の上昇は読者の感情的な休憩として機能します——"
            "最後の下降の前に、息継ぎの時間を与えましょう。"
        ),
        # Share / publish
        "share_btn": "🔗 共有リンクを生成",
        "share_btn_disabled": "Supabase未設定",
        "share_confirm_warning": "共有後、リンクは永久に有効になります（v2.0で取り消し対応予定）。",
        "share_confirm_btn": "公開共有を確認",
        "share_cancel": "キャンセル",
        "share_success": "✅ 共有しました！アプリURLに以下を追加してください：",
        "share_error": "共有に失敗しました。Supabase設定を確認してください。",
        "share_view_not_found": "この分析は存在しないか、公開共有されていません。",
        "share_view_footer": "BookScopeが生成",
        # Book Recommendations
        "qi_recs_label": "【実験的機能】こんな本もおすすめ",
        "qi_recs_disclaimer": (
            "AI によるおすすめ — 品質はさまざまです。ご自身の判断を優先してください。"
        ),
        "qi_recs_unavailable": "おすすめ機能は利用できません。LLM の設定を確認してください。",
        # Fallback for character detection
        "qi_fi_top_emotions_fallback": "主要感情",
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
        "export_card": "🖼️ シェアカード (.png)",
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
