"""Quick Insight tab — book-type-aware insight cards."""

import html as _html

import streamlit as st

from bookscope.insights import (
    compute_readability,
    compute_sparkline_points,
    extract_character_names,
    extract_key_themes,
    first_person_density,
)
from bookscope.nlp.llm_analyzer import generate_narrative_insight

# ── Emotional genre mapping (fiction, EN only) ────────────────────────────────
# (arc.value, top_emotion_key) → (label_en, label_zh, label_ja, for_you_en)
_EMOTIONAL_GENRE: dict[tuple, tuple] = {
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
_DEFAULT_GENRE = (
    "Emotional Fiction", "情感小说", "感情的小説",
    "For readers who enjoy character-driven emotional journeys.",
)

# Book type accent colors
_TYPE_COLOR = {
    "fiction":  "#f97316",  # orange
    "academic": "#3b82f6",  # blue
    "essay":    "#22c55e",  # green
}

_EMOTION_FIELDS = (
    "anger", "anticipation", "disgust", "fear",
    "joy", "sadness", "surprise", "trust",
)


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
    valence_series: list,
    detected_lang: str,
    ui_lang: str,
    T: dict,
    analysis_result=None,
) -> None:
    """Render Quick Insight cards for the given book type."""
    type_color = _TYPE_COLOR.get(book_type, "#7c3aed")

    # Session-keyed animation (first render per book+type gets animation)
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
        genre_tuple = _EMOTIONAL_GENRE.get((arc_value, top_emotion_key), _DEFAULT_GENRE)
        lang_idx = {"en": 0, "zh": 1, "ja": 2}.get(ui_lang, 0)
        genre_label = genre_tuple[lang_idx]

        if ui_lang == "en":
            headline_text = (
                f"{_html.escape(genre_label)} — "
                f"{_html.escape(top_emotion_name)}-driven {_html.escape(arc_display_name)} arc"
            )
            for_you_text = genre_tuple[3]
        else:
            headline_text = f"{_html.escape(genre_label)} — {_html.escape(arc_display_name)}"
            for_you_text = ""

        # Headline card
        st.markdown(
            f'<div class="bs-insight-headline" style="border-left:4px solid {type_color};">'
            f'<div class="bs-insight-headline-label">'
            f'{_html.escape(T["qi_fi_headline_label"])}</div>'
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
                    + "".join(
                        f'<span class="bs-tag">{_html.escape(c)}</span>' for c in chars
                    )
                    + "</div>"
                )
                chars_sub = ""
            else:
                # Fallback: show top emotion words
                top_emotions = sorted(
                    [
                        (e, sum(getattr(s, e) for s in emotion_scores) / len(emotion_scores))
                        for e in _EMOTION_FIELDS
                    ],
                    key=lambda x: -x[1],
                )[:3]
                chars_html = (
                    '<div class="bs-tag-row">'
                    + "".join(
                        f'<span class="bs-tag">'
                        f'{_html.escape(T["emotion_names"].get(e, e))}</span>'
                        for e, _ in top_emotions
                    )
                    + "</div>"
                )
                chars_sub = _html.escape(T.get("qi_fi_top_emotions_fallback", "Top emotions"))
        else:
            chars_html = (
                f'<div class="bs-insight-card-sub">'
                f'{_html.escape(T["qi_fi_chars_en_only"])}</div>'
            )
            chars_sub = ""

        # Card 2: Story Shape (sparkline)
        spark_pts = compute_sparkline_points(valence_series)
        spark_svg = _sparkline_svg(spark_pts)
        shape_sub = _html.escape(arc_display_name)

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
            style_val = _html.escape(vocab_desc)
            style_sub = _html.escape(sent_desc)
        else:
            style_val = "—"
            style_sub = ""

        # 3-col grid
        st.markdown(
            f'<div class="bs-insight-grid" style="--bs-type-color:{type_color};">'
            f'<div class="{card_cls}">'
            f'<div class="bs-insight-card-label">{_html.escape(T["qi_fi_chars_label"])}</div>'
            f'<div class="bs-insight-card-value">{chars_html}</div>'
            f'{"<div class=bs-insight-card-sub>" + chars_sub + "</div>" if chars_sub else ""}'
            f'</div>'
            f'<div class="{card_cls}">'
            f'<div class="bs-insight-card-label">{_html.escape(T["qi_fi_shape_label"])}</div>'
            f'<div class="bs-insight-card-value">{shape_sub}</div>'
            f'{spark_svg}'
            f'</div>'
            f'<div class="{card_cls}">'
            f'<div class="bs-insight-card-label">{_html.escape(T["qi_fi_style_label"])}</div>'
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
                f'<div class="bs-for-you-text">'
                f'<strong>{_html.escape(T["qi_for_you_label"])}:</strong> '
                f'{_html.escape(for_you_text)}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    # ── ACADEMIC ─────────────────────────────────────────────────────────────
    elif book_type == "academic":
        _, readability_label, confidence = compute_readability(style_scores, ui_lang)
        reading_min = max(1, total_words // 238)
        read_time_str = T["qi_ac_read_time"].format(min=reading_min)

        headline_text = (
            f"{_html.escape(readability_label)} · {_html.escape(read_time_str)}"
        )

        st.markdown(
            f'<div class="bs-insight-headline" style="border-left:4px solid {type_color};">'
            f'<div class="bs-insight-headline-label">'
            f'{_html.escape(T["qi_ac_headline_label"])}</div>'
            f'<div class="{headline_cls}">{headline_text}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # Card 1: Core Concepts
        themes = (
            extract_key_themes(chunks, style_scores)
            if (chunks is not None and style_scores)
            else []
        )
        if themes:
            themes_html = (
                '<div class="bs-tag-row">'
                + "".join(
                    f'<span class="bs-tag">{_html.escape(t)}</span>' for t in themes
                )
                + "</div>"
            )
        else:
            themes_html = (
                f'<div class="bs-insight-card-sub">'
                f'{_html.escape(T["qi_ac_no_themes"])}</div>'
            )

        # Card 2: Reading Strategy (anticipation front-loaded?)
        if emotion_scores:
            n = len(emotion_scores)
            first_half_ant = (
                sum(s.anticipation for s in emotion_scores[: n // 2]) / max(n // 2, 1)
            )
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
            f'<div class="bs-insight-card-label">'
            f'{_html.escape(T["qi_ac_themes_label"])}</div>'
            f'<div class="bs-insight-card-value">{themes_html}</div>'
            f'</div>'
            f'<div class="{card_cls}">'
            f'<div class="bs-insight-card-label">'
            f'{_html.escape(T["qi_ac_strategy_label"])}</div>'
            f'<div class="bs-insight-card-value">{_html.escape(strategy_val)}</div>'
            f'</div>'
            f'<div class="{card_cls}">'
            f'<div class="bs-insight-card-label">'
            f'{_html.escape(T["qi_ac_stance_label"])}</div>'
            f'<div class="bs-insight-card-value">{_html.escape(stance)}</div>'
            f'</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # For-you card
        audience_map = {
            T["readable_accessible"]: (
                "general readers new to the topic" if ui_lang == "en" else
                "初学者和对该主题感兴趣的普通读者" if ui_lang == "zh" else
                "このテーマに初めて触れる一般読者"
            ),
            T["readable_moderate"]: (
                "informed readers with some background" if ui_lang == "en" else
                "有一定背景知识的读者" if ui_lang == "zh" else
                "基礎知識を持つ読者"
            ),
            T["readable_dense"]: (
                "subject-matter experts" if ui_lang == "en" else
                "具备专业背景的读者" if ui_lang == "zh" else
                "専門知識を持つ読者"
            ),
            T["readable_specialist"]: (
                "domain specialists and researchers" if ui_lang == "en" else
                "领域专家和研究人员" if ui_lang == "zh" else
                "専門家および研究者"
            ),
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
                f'<div class="bs-for-you-text">'
                f'<strong>{_html.escape(T["qi_for_you_label"])}:</strong> '
                f'{_html.escape(for_you_body)}</div>'
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
                voice_type = (
                    "Sensory" if ui_lang == "en" else
                    "感官型" if ui_lang == "zh" else "感覚的"
                )
            elif fp > 0.08:
                voice_type = (
                    "Intimate" if ui_lang == "en" else
                    "亲密型" if ui_lang == "zh" else "親密"
                )
            else:
                voice_type = (
                    "Observational" if ui_lang == "en" else
                    "观察型" if ui_lang == "zh" else "観察的"
                )
        else:
            voice_type = (
                "Personal" if ui_lang == "en" else
                "个人型" if ui_lang == "zh" else "個人的"
            )

        headline_text = f"{_html.escape(voice_type)} · {_html.escape(arc_display_name)}"

        st.markdown(
            f'<div class="bs-insight-headline" style="border-left:4px solid {type_color};">'
            f'<div class="bs-insight-headline-label">'
            f'{_html.escape(T["qi_es_headline_label"])}</div>'
            f'<div class="{headline_cls}">{headline_text}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # Card 1: Author Journey (sparkline)
        spark_pts = compute_sparkline_points(valence_series)
        spark_svg = _sparkline_svg(spark_pts, color="#22c55e")
        arc_as_journey = {
            "Rags to Riches": ("from darkness into light", "从黑暗走向光明", "暗闇から光へ"),
            "Riches to Rags": ("a descent into difficulty", "走向困境的历程", "困難への下降"),
            "Man in a Hole":  ("a fall and comeback", "跌落后的重新站起", "転落と回復"),
            "Icarus":         ("early hope, late struggle", "先有希望后有挣扎", "希望の後に試練"),
            "Cinderella":     ("resilience through hardship", "坚韧穿越艰难",  # noqa: E501
                               "困難を乗り越えた強さ"),
            "Oedipus":        ("hope between two struggles", "两段挣扎之间的希望",  # noqa: E501
                               "二つの困難の間の希望"),
            "Unknown":        ("a complex personal journey", "复杂的个人旅程", "複雑な旅路"),
        }
        lang_idx = {"en": 0, "zh": 1, "ja": 2}.get(ui_lang, 0)
        journey_desc = arc_as_journey.get(
            arc_value, ("a personal journey", "个人旅程", "個人的旅")
        )[lang_idx]

        # Card 2: Voice Fingerprint
        if style_scores:
            avg_adj_r = sum(s.adj_ratio for s in style_scores) / len(style_scores)
            avg_adv_r = sum(s.adv_ratio for s in style_scores) / len(style_scores)
            avg_vrb_r = sum(s.verb_ratio for s in style_scores) / len(style_scores)
            if avg_adj_r > avg_adv_r and avg_adj_r > avg_vrb_r:
                dominant_voice = (
                    "Descriptive" if ui_lang == "en" else
                    "描述型" if ui_lang == "zh" else "描写的"
                )
            elif avg_adv_r > avg_vrb_r:
                dominant_voice = (
                    "Assertive" if ui_lang == "en" else
                    "论断型" if ui_lang == "zh" else "断定的"
                )
            else:
                dominant_voice = (
                    "Narrative" if ui_lang == "en" else
                    "叙述型" if ui_lang == "zh" else "物語的"
                )
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
            intimacy_sub = (
                "高度个人化叙述" if fp > 0.10 else
                "个人视角与观察并重" if fp > 0.04 else
                "相对客观的叙事视角"
            )
        else:
            intimacy_val = f"{fp_pct}% 一人称"
            intimacy_sub = (
                "高度に個人的な語り" if fp > 0.10 else
                "個人と観察のバランス" if fp > 0.04 else
                "やや客観的な語り口"
            )

        st.markdown(
            f'<div class="bs-insight-grid" style="--bs-type-color:{type_color};">'
            f'<div class="{card_cls}">'
            f'<div class="bs-insight-card-label">'
            f'{_html.escape(T["qi_es_journey_label"])}</div>'
            f'<div class="bs-insight-card-value">{_html.escape(journey_desc)}</div>'
            f'{spark_svg}'
            f'</div>'
            f'<div class="{card_cls}">'
            f'<div class="bs-insight-card-label">'
            f'{_html.escape(T["qi_es_voice_label"])}</div>'
            f'<div class="bs-insight-card-value">{_html.escape(dominant_voice)}</div>'
            f'</div>'
            f'<div class="{card_cls}">'
            f'<div class="bs-insight-card-label">'
            f'{_html.escape(T["qi_es_intimacy_label"])}</div>'
            f'<div class="bs-insight-card-value">{_html.escape(intimacy_val)}</div>'
            f'<div class="bs-insight-card-sub">{_html.escape(intimacy_sub)}</div>'
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
                "For readers who appreciate thoughtful, essay-style observation."
                if ui_lang == "en" else
                "适合喜爱沉思式、散文风格写作的读者。" if ui_lang == "zh" else
                "思索的なエッセイスタイルの文章を好む読者に。"
            )
        st.markdown(
            f'<div class="bs-for-you">'
            f'<div class="bs-for-you-icon">✍️</div>'
            f'<div class="bs-for-you-text">'
            f'<strong>{_html.escape(T["qi_for_you_label"])}:</strong> '
            f'{_html.escape(for_you_body)}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # ── AI NARRATIVE CARD (all book types, shown only when API key is present) ─
    # Map UI book_type directly — llm_analyzer accepts "academic" as alias for
    # "nonfiction", so no translation is needed here.
    if analysis_result is not None:
        with st.spinner(""):
            ai_text = generate_narrative_insight(
                analysis_result, ui_lang, genre_type=book_type
            )
        if ai_text:
            label = _html.escape(T.get("qi_ai_narrative_label", "AI NARRATIVE"))
            st.markdown(
                f'<div class="bs-insight-headline" style="border-left:4px solid #7c3aed;'
                f'margin-top:.75rem;">'
                f'<div class="bs-insight-headline-label">✨ {label}</div>'
                f'<div class="bs-insight-headline-text bs-no-animate">'
                f'{_html.escape(ai_text)}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
