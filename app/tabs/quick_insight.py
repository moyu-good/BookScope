"""Quick Insight tab — book-type-aware insight cards."""

import hashlib
import html as _html
import os
from concurrent.futures import ThreadPoolExecutor

import streamlit as st

from bookscope.insights import (
    build_reader_verdict,
    compute_readability,
    compute_sparkline_points,
    extract_character_names,
    extract_key_themes,
    first_person_density,
)
from bookscope.nlp.arc_classifier import ArcClassifier as _ArcClassifier
from bookscope.nlp.genre_analyzer import (
    extract_concept_relations,
    extract_essay_phrases,
    extract_essay_voice,
    extract_nonfiction_concepts,
)
from bookscope.nlp.llm_analyzer import (
    call_llm,
    generate_narrative_insight,
    generate_narrative_insight_stream,
)

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
    "fiction":  "#C8781A",  # amber
    "academic": "#2A5A8A",  # steel blue
    "essay":    "#2A7A5A",  # forest green
}

_EMOTION_FIELDS = (
    "anger", "anticipation", "disgust", "fear",
    "joy", "sadness", "surprise", "trust",
)

# Edge color palette for concept relation graphs (nonfiction)
_CONCEPT_EDGE_PALETTE: dict[str, str] = {
    "supports": "#2A7A5A",
    "contradicts": "#C0392B",
    "extends": "#2A5A8A",
    "defines": "#8C4E08",
}


def _sparkline_svg(points: str, color: str = "#C8781A", width: int = 200, height: int = 40) -> str:
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg" style="display:block;margin-top:.4rem">'
        f'<defs><linearGradient id="spark-grad" x1="0" y1="0" x2="1" y2="0">'
        f'<stop offset="0%" stop-color="#2A7A5A"/>'
        f'<stop offset="100%" stop-color="#C0392B"/>'
        f'</linearGradient></defs>'
        f'<polyline points="{_html.escape(points)}" '
        f'fill="none" stroke="url(#spark-grad)" stroke-width="2" stroke-linejoin="round"/>'
        f'</svg>'
    )


def _render_verdict_card(verdict, T: dict, ui_lang: str) -> None:
    """Render the Reader Verdict card above all book-type branches.

    Called once at the top of render_quick_insight(), before any if/elif
    book_type branching, so the verdict always appears first.
    """
    label = _html.escape(T.get("verdict_label", "READER VERDICT"))
    for_you_prefix = _html.escape(T.get("verdict_for_you", "Great for"))
    not_for_you_prefix = _html.escape(T.get("verdict_not_for_you", "Skip if"))
    sentence = _html.escape(verdict.sentence)
    for_you = _html.escape(verdict.for_you)
    not_for_you = _html.escape(verdict.not_for_you)

    disclaimer_html = ""
    if verdict.confidence < 0.3:
        low_conf = _html.escape(T.get("verdict_low_confidence", "Limited data — rough guide only"))
        _icon = (
            '<span class="material-symbols-rounded"'
            ' style="font-size:12px;vertical-align:middle;">info</span>'
        )
        disclaimer_html = (
            f'<div class="bs-verdict-sub" style="margin-top:.6rem;">'
            f'{_icon} {low_conf}</div>'
        )

    st.markdown(
        f'<div class="bs-verdict-card">'
        f'<div style="font-size:10px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;'
        f'color:#C8781A;margin-bottom:.5rem;">{label}</div>'
        f'<div class="bs-verdict-for-you">{for_you_prefix}: {for_you}</div>'
        f'<div class="bs-verdict-sentence">{sentence}</div>'
        f'<div class="bs-verdict-not-for-you">{not_for_you_prefix}: {not_for_you}</div>'
        f'{disclaimer_html}'
        f'</div>',
        unsafe_allow_html=True,
    )


def _render_book_recommendations(
    book_title: str,
    arc_value: str,
    top_emotion_key: str,
    top_emotion_name: str,
    book_type: str,
    ai_narrative: str,
    ui_lang: str,
    T: dict,
) -> None:
    """Render the '[Experimental] You might also like' recommendations card.

    Gated by ENABLE_BOOK_RECS=true env var. Uses call_llm() which is
    thread-safe and does not read session_state.
    Results are cached per book+emotion+arc in session_state.
    """
    if os.environ.get("ENABLE_BOOK_RECS", "").lower() not in ("true", "1", "yes"):
        return

    lang_name = {"en": "English", "zh": "Chinese", "ja": "Japanese"}.get(ui_lang, "English")
    genre_label_map = {
        "fiction": "fiction",
        "academic": "non-fiction / academic",
        "essay": "essay / memoir",
    }
    genre_label = genre_label_map.get(book_type, book_type)

    # Cache key: md5(book_title + top_emotion + arc_value)
    ck_src = f"{book_title}_{top_emotion_key}_{arc_value}"
    ck = "book_recs_" + hashlib.md5(ck_src.encode()).hexdigest()[:8]

    recs_text: str | None = st.session_state.get(ck)

    if recs_text is None:
        prompt = (
            f"This book has a {arc_value} narrative arc, dominant emotion: {top_emotion_name}, "
            f"genre: {genre_label}.\n"
        )
        if ai_narrative:
            prompt += f"The reading experience: {ai_narrative}\n"
        prompt += (
            f"Recommend 3 specific books (title + author) that readers who enjoyed this "
            f"would likely also enjoy. Format: numbered list. Respond in {lang_name}."
        )
        recs_text = call_llm(prompt, max_tokens=300)
        st.session_state[ck] = recs_text or ""

    label = T.get("qi_recs_label", "[Experimental] You might also like")
    disclaimer = T.get(
        "qi_recs_disclaimer", "AI suggestions — quality varies. Trust your own taste."
    )

    if not recs_text:
        unavailable = T.get(
            "qi_recs_unavailable",
            "Recommendations unavailable. Check LLM configuration.",
        )
        st.markdown(
            f'<div class="bs-for-you" style="opacity:0.5;">'
            f'<div class="bs-for-you-icon">📚</div>'
            f'<div class="bs-for-you-text">{_html.escape(unavailable)}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        return

    st.markdown(
        '<div class="bs-insight-headline"'
        ' style="border-left:4px solid #7A6A5A;margin-top:.75rem;">'
        f'<div class="bs-insight-headline-label">📚 {_html.escape(label)}</div>'
        f'<div style="white-space:pre-line;color:#3A2A1A;font-size:.9rem;line-height:1.6;">'
        f'{_html.escape(recs_text)}</div>'
        f'<div style="font-size:.72rem;color:#B8A898;margin-top:.5rem;">'
        f'{_html.escape(disclaimer)}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def _render_book_club_pack(
    book_title: str,
    arc_value: str,
    arc_display_name: str,
    top_emotion_name: str,
    book_type: str,
    style_scores,
    emotion_scores,
    ai_narrative: str,
    ui_lang: str,
    T: dict,
) -> None:
    """Render a Book Club Pack button + LLM-generated discussion guide.

    Cached in session_state per book so re-renders don't re-call the LLM.
    """
    btn_label = T.get("qi_book_club_btn", "📚 Book Club Pack")
    ck = "book_club_" + hashlib.md5(
        f"{book_title}_{arc_value}_{top_emotion_name}_{ui_lang}".encode()
    ).hexdigest()[:8]

    pack_text: str | None = st.session_state.get(ck)

    col_btn = st.columns([1, 3])[0]
    generate = col_btn.button(btn_label, key=f"bc_btn_{ck}")

    if generate and not pack_text:
        lang_name = {"en": "English", "zh": "Chinese", "ja": "Japanese"}.get(
            ui_lang, "English"
        )
        type_label = {
            "fiction": "fiction", "academic": "non-fiction", "essay": "essay/memoir"
        }.get(book_type, book_type)
        prompt = (
            f"You are preparing a book club discussion guide for '{book_title}', "
            f"a {type_label} with a {arc_value} emotional arc, "
            f"primarily driven by {top_emotion_name}.\n"
        )
        if ai_narrative:
            prompt += f"About the book: {ai_narrative}\n"
        prompt += (
            f"\nIn {lang_name}, provide:\n"
            f"1. A 2-3 sentence description of the reading experience (not plot summary)\n"
            f"2. 8 discussion questions that go beyond plot to explore themes, "
            f"emotions, and personal reflection\n"
            f"3. One sentence about who this book is most for\n\n"
            f"Format with clear numbered sections."
        )
        spinner_msg = T.get("qi_book_club_spinner", "Generating discussion guide…")
        with st.spinner(spinner_msg):
            pack_text = call_llm(prompt, max_tokens=600) or ""
        if not pack_text:
            st.warning(T.get(
                "qi_book_club_error",
                "Could not generate discussion guide — check your API key.",
            ))
        st.session_state[ck] = pack_text

    if pack_text:
        label = _html.escape(T.get("qi_book_club_label", "BOOK CLUB PACK"))
        st.markdown(
            f'<div class="bs-insight-headline" '
            f'style="border-left:4px solid #2A7A5A;margin-top:.75rem;">'
            f'<div class="bs-insight-headline-label">📚 {label}</div>'
            f'<div style="white-space:pre-line;color:#3A2A1A;'
            f'font-size:.9rem;line-height:1.7;">'
            f'{_html.escape(pack_text)}</div>'
            f'</div>',
            unsafe_allow_html=True,
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
    show_verdict: bool = True,
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

    # ── LLM pre-computation (parallelized for academic/essay) ─────────────────
    # Model pre-fetched in main Streamlit thread — worker threads must not call
    # st.session_state; they receive model as an explicit argument.
    # Fiction: no batch pre-computation — streaming handles BOOK DNA inline.
    _ai_text = ""
    _llm_concepts: list[str] = []
    _llm_argument = ""
    _llm_voice = ""
    _llm_concept_graph = None
    _llm_essay_phrases: list[str] = []
    _llm_model = st.session_state.get("llm_model", "claude-haiku-4-5")

    if analysis_result is not None:
        if book_type in ("academic", "nonfiction") and chunks is not None:
            # Parallel: AI narrative + nonfiction concepts + concept relation graph
            with st.spinner(""):
                with ThreadPoolExecutor(max_workers=3) as _ex:
                    _f_ai = _ex.submit(
                        generate_narrative_insight, analysis_result, ui_lang, book_type
                    )
                    _f_concepts = _ex.submit(
                        extract_nonfiction_concepts, chunks, ui_lang, book_title, _llm_model
                    )
                    _f_concept_graph = _ex.submit(
                        extract_concept_relations, chunks, ui_lang, book_title, _llm_model
                    )
                try:
                    _ai_text = _f_ai.result(timeout=30)
                except Exception:
                    _ai_text = ""
                try:
                    _llm_concepts, _llm_argument = _f_concepts.result(timeout=30)
                except Exception:
                    _llm_concepts, _llm_argument = [], ""
                try:
                    _llm_concept_graph = _f_concept_graph.result(timeout=30)
                except Exception:
                    _llm_concept_graph = None

        elif book_type == "essay" and chunks is not None:
            # Parallel: AI narrative + essay voice + essay phrases for timeline
            with st.spinner(""):
                with ThreadPoolExecutor(max_workers=3) as _ex:
                    _f_ai = _ex.submit(
                        generate_narrative_insight, analysis_result, ui_lang, book_type
                    )
                    _f_voice = _ex.submit(
                        extract_essay_voice, chunks, ui_lang, book_title, _llm_model
                    )
                    _f_phrases = _ex.submit(
                        extract_essay_phrases, chunks, ui_lang, book_title, _llm_model
                    )
                try:
                    _ai_text = _f_ai.result(timeout=30)
                except Exception:
                    _ai_text = ""
                try:
                    _llm_voice = _f_voice.result(timeout=30)
                except Exception:
                    _llm_voice = ""
                try:
                    _llm_essay_phrases = _f_phrases.result(timeout=30)
                except Exception:
                    _llm_essay_phrases = []

        # Fiction: no pre-computation — BOOK DNA rendered via streaming inline

    # ── Reader Verdict (rendered before any book_type branch) ────────────────
    if show_verdict:
        _verdict = build_reader_verdict(
            arc_value=arc_value,
            top_emotion_key=top_emotion_key,
            style_scores=style_scores or [],
            book_type=book_type,
            ui_lang=ui_lang,
        )
        _render_verdict_card(_verdict, T, ui_lang)

    def _render_ai_card() -> None:
        """Render Book DNA card — LLM narrative as primary insight, shown first."""
        if not _ai_text:
            return
        _label = _html.escape(T.get("qi_ai_narrative_label", "BOOK DNA"))
        st.markdown(
            f'<div class="bs-insight-headline" style="border-left:4px solid #C8781A;'
            f'margin-top:.25rem;margin-bottom:.75rem;">'
            f'<div class="bs-insight-headline-label">🧬 {_label}</div>'
            f'<div style="font-size:1rem;color:#3A2A1A;line-height:1.65;">'
            f'{_html.escape(_ai_text)}</div>'
            f'</div>',
            unsafe_allow_html=True,
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
        else:
            headline_text = f"{_html.escape(genre_label)} — {_html.escape(arc_display_name)}"

        # Book DNA card — streaming (Streamlit native, no HTML div wrapper)
        if analysis_result is not None:
            _dna_label = _html.escape(T.get("qi_ai_narrative_label", "BOOK DNA"))
            st.markdown(
                f'<div class="bs-insight-headline-label" '
                f'style="color:#C8781A;margin-bottom:.25rem;">🧬 {_dna_label}</div>',
                unsafe_allow_html=True,
            )
            st.write_stream(
                generate_narrative_insight_stream(analysis_result, ui_lang, "fiction")
            )

        st.markdown(
            f'<div class="bs-insight-headline" style="border-left:4px solid {type_color};">'
            f'<div class="bs-insight-headline-label">'
            f'{_html.escape(T["qi_fi_headline_label"])}</div>'
            f'<div class="{headline_cls}">{headline_text}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # Emotional Intensity indicator (avg emotion_density across chunks)
        if emotion_scores:
            _avg_density = sum(s.emotion_density for s in emotion_scores) / len(emotion_scores)
            if _avg_density >= 0.20:
                _intensity_label = T.get("intensity_high", "High emotional intensity")
                _intensity_color = "#f97316"
            elif _avg_density >= 0.08:
                _intensity_label = T.get("intensity_moderate", "Moderate emotional intensity")
                _intensity_color = "#A8600E"
            else:
                _intensity_label = T.get("intensity_low", "Low emotional intensity")
                _intensity_color = "#B8A898"
            st.markdown(
                f'<div style="font-size:.72rem;color:{_intensity_color};'
                f'margin-bottom:.5rem;">⚡ {_html.escape(_intensity_label)}</div>',
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
                n_scores = len(emotion_scores)
                top_emotions = sorted(
                    [
                        (
                            e,
                            sum(getattr(s, e) for s in emotion_scores) / n_scores
                            if n_scores else 0.0,
                        )
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

        # Card 2: Story Shape (sparkline) + arc confidence badge
        spark_pts = compute_sparkline_points(valence_series)
        spark_svg = _sparkline_svg(spark_pts)
        shape_sub = _html.escape(arc_display_name)

        # Compute arc confidence via distance_to_arc (Reagan et al.)
        _arc_conf_html = ""
        if emotion_scores and len(emotion_scores) >= 6:
            _, _arc_confidence = _ArcClassifier().classify_with_confidence(emotion_scores)
            if _arc_confidence >= 0.85:
                _conf_label = T.get("arc_conf_high", "High confidence")
                _conf_color = "#2A7A5A"
            elif _arc_confidence >= 0.70:
                _conf_label = T.get("arc_conf_moderate", "Moderate")
                _conf_color = "#A8600E"
            else:
                _conf_label = T.get("arc_conf_low", "Low — arc is ambiguous")
                _conf_color = "#B8A898"
            _arc_conf_html = (
                f'<div style="margin-top:.35rem;font-size:.68rem;color:{_conf_color};">'
                f'◉ {_html.escape(_conf_label)}</div>'
            )

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

        # Single-column card stack
        st.markdown(
            f'<div class="bs-insight-grid" style="--bs-type-color:{type_color};">'
            # Card 1: Key Characters
            f'<div class="{card_cls}">'
            f'<div class="bs-insight-card-label">{_html.escape(T["qi_fi_chars_label"])}</div>'
            f'<div class="bs-insight-card-value">{chars_html}</div>'
            f'{"<div class=bs-insight-card-sub>" + chars_sub + "</div>" if chars_sub else ""}'
            f'</div>'
            # Card 2: Story Shape — arc name + full-width sparkline side by side
            f'<div class="{card_cls}">'
            f'<div class="bs-insight-card-label">{_html.escape(T["qi_fi_shape_label"])}</div>'
            f'<div style="display:flex;align-items:center;gap:1.5rem;">'
            f'<div style="flex:0 0 auto;">'
            f'<div class="bs-insight-card-value">{shape_sub}</div>'
            f'{_arc_conf_html}'
            f'</div>'
            f'<div style="flex:1 1 auto;">{spark_svg}</div>'
            f'</div>'
            f'</div>'
            # Card 3: Writing Style
            f'<div class="{card_cls}">'
            f'<div class="bs-insight-card-label">{_html.escape(T["qi_fi_style_label"])}</div>'
            f'<div class="bs-insight-card-value">{style_val}</div>'
            f'<div class="bs-insight-card-sub">{style_sub}</div>'
            f'</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # Character relation graph (fiction + EN/ZH/JA books)
        if detected_lang in ("en", "zh", "ja") and chunks is not None:
            _rel_api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not _rel_api_key:
                try:
                    _rel_api_key = st.secrets.get("ANTHROPIC_API_KEY", None)
                except Exception:
                    pass
            if _rel_api_key:
                from bookscope.nlp.relation_extractor import extract_character_relations
                from bookscope.viz.relation_graph_renderer import render_relation_graph

                _spinner_text = T.get(
                    "qi_rel_graph_spinner", "Mapping character relationships\u2026"
                )
                with st.spinner(_spinner_text):
                    _rel_graph = extract_character_relations(
                        chunks,
                        lang=detected_lang,
                        api_key=_rel_api_key,
                        model=_llm_model,
                    )
                _rel_fig = render_relation_graph(_rel_graph)
                if _rel_fig is None and len(_rel_graph.characters) < 2:
                    _empty_msgs = {
                        "en": "Character graph requires at least 2 identifiable characters.",
                        "zh": "人物关系图需要至少 2 位可识别角色。",
                        "ja": "人物関係図には少なくとも 2 人の認識可能なキャラクターが必要です。",
                    }
                    st.info(_empty_msgs.get(ui_lang, _empty_msgs["en"]))
                if _rel_fig is not None:
                    _rel_label = _html.escape(
                        T.get("qi_rel_graph_label", "CHARACTER RELATIONSHIPS")
                    )
                    n_chunks_used = min(5, len(chunks))
                    _rel_caption = _html.escape(
                        T.get(
                            "qi_rel_graph_caption",
                            "Based on first {n} chapter(s)",
                        ).format(n=n_chunks_used)
                    )
                    st.markdown(
                        f'<div class="bs-insight-headline" '
                        f'style="border-left:4px solid #2A5A8A;margin-top:.75rem;">'
                        f'<div class="bs-insight-headline-label">👥 {_rel_label}</div>'
                        f'<div style="font-size:.8rem;color:#B8A898;">{_rel_caption}</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                    st.plotly_chart(_rel_fig, use_container_width=True)

    # ── ACADEMIC ─────────────────────────────────────────────────────────────
    elif book_type == "academic":
        _, readability_label, confidence = compute_readability(style_scores, ui_lang)
        reading_min = max(1, total_words // 238)
        read_time_str = T["qi_ac_read_time"].format(min=reading_min)

        headline_text = (
            f"{_html.escape(readability_label)} · {_html.escape(read_time_str)}"
        )

        _render_ai_card()
        st.markdown(
            f'<div class="bs-insight-headline" style="border-left:4px solid {type_color};">'
            f'<div class="bs-insight-headline-label">'
            f'{_html.escape(T["qi_ac_headline_label"])}</div>'
            f'<div class="{headline_cls}">{headline_text}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # Card 1: Core Concepts — LLM extraction first (pre-computed above), heuristic fallback
        llm_concepts, llm_argument = _llm_concepts, _llm_argument
        if llm_concepts:
            themes_html = (
                '<div class="bs-tag-row">'
                + "".join(
                    f'<span class="bs-tag">{_html.escape(c)}</span>' for c in llm_concepts
                )
                + "</div>"
            )
            themes_sub = _html.escape(llm_argument) if llm_argument else ""
        else:
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
            themes_sub = ""

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
            f'{"<div class=bs-insight-card-sub>" + themes_sub + "</div>" if themes_sub else ""}'
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

        # Concept relation graph (nonfiction / academic)
        if _llm_concept_graph is not None:
            from bookscope.viz.relation_graph_renderer import render_relation_graph

            if len(_llm_concept_graph.characters) >= 2:
                _concept_fig = render_relation_graph(
                    _llm_concept_graph, edge_palette=_CONCEPT_EDGE_PALETTE
                )
                if _concept_fig is not None:
                    _cg_label = _html.escape(T.get("qi_concept_graph_label", "CONCEPT MAP"))
                    st.markdown(
                        f'<div class="bs-insight-headline" '
                        f'style="border-left:4px solid #2A5A8A;margin-top:.75rem;">'
                        f'<div class="bs-insight-headline-label">🔗 {_cg_label}</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                    st.plotly_chart(_concept_fig, use_container_width=True)
            else:
                _cg_empty = {
                    "en": "Concept graph requires at least 2 extractable concepts.",
                    "zh": "概念图需要至少 2 个可识别概念。",
                    "ja": "概念図には少なくとも 2 つの概念が必要です。",
                }
                st.info(_cg_empty.get(ui_lang, _cg_empty["en"]))

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

        _render_ai_card()
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
        spark_svg = _sparkline_svg(spark_pts, color="#2A7A5A")
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

        # Card 2: Voice Fingerprint — LLM description enriches heuristic label (pre-computed above)
        llm_voice = _llm_voice
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
        voice_sub = _html.escape(llm_voice) if llm_voice else ""

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
            f'{"<div class=bs-insight-card-sub>" + voice_sub + "</div>" if voice_sub else ""}'
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

        # Essay idea timeline (silently absent if phrases extraction failed)
        if _llm_essay_phrases:
            from bookscope.viz.essay_graph_renderer import render_essay_timeline

            _timeline_fig = render_essay_timeline(_llm_essay_phrases, emotion_scores)
            if _timeline_fig is not None:
                _tl_label = _html.escape(T.get("qi_essay_timeline_label", "IDEA TIMELINE"))
                st.markdown(
                    f'<div class="bs-insight-headline-label" '
                    f'style="color:#2A7A5A;margin-top:.75rem;">📍 {_tl_label}</div>',
                    unsafe_allow_html=True,
                )
                st.plotly_chart(_timeline_fig, use_container_width=True)

    # ── BOOK RECOMMENDATIONS (all types, gated by ENABLE_BOOK_RECS env var) ──
    _render_book_recommendations(
        book_title=book_title,
        arc_value=arc_value,
        top_emotion_key=top_emotion_key,
        top_emotion_name=top_emotion_name,
        book_type=book_type,
        ai_narrative=_ai_text,
        ui_lang=ui_lang,
        T=T,
    )

    # ── BOOK CLUB PACK ────────────────────────────────────────────────────────
    st.divider()
    _render_book_club_pack(
        book_title=book_title,
        arc_value=arc_value,
        arc_display_name=arc_display_name,
        top_emotion_name=top_emotion_name,
        book_type=book_type,
        style_scores=style_scores,
        emotion_scores=emotion_scores,
        ai_narrative=_ai_text,
        ui_lang=ui_lang,
        T=T,
    )

