"""Smoke tests for render_quick_insight().

These tests verify that the function can be called for all three book types
without raising any exception — catching import/wiring regressions early.

Streamlit is mocked so the tests run without a live Streamlit server.
LLM calls are mocked to return immediately without hitting the API.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from bookscope.models import EmotionScore, StyleScore
from bookscope.store import AnalysisResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_emotion_score(chunk_index: int, **kwargs) -> EmotionScore:
    return EmotionScore(chunk_index=chunk_index, **kwargs)


def _make_style_score(chunk_index: int) -> StyleScore:
    return StyleScore(
        chunk_index=chunk_index,
        ttr=0.55,
        avg_sentence_length=15.0,
        noun_ratio=0.25,
        verb_ratio=0.18,
        adj_ratio=0.10,
        adv_ratio=0.05,
    )


def _make_chunks(n: int = 5) -> list:
    return [
        SimpleNamespace(text=f"Chunk {i} content about things and events.", index=i)
        for i in range(n)
    ]


def _make_result(book_type: str = "fiction") -> AnalysisResult:
    scores = [_make_emotion_score(i, joy=0.5, trust=0.3) for i in range(5)]
    styles = [_make_style_score(i) for i in range(5)]
    return AnalysisResult.create(
        book_title="Test Book",
        chunk_strategy="paragraph",
        total_chunks=5,
        total_words=1200,
        arc_pattern="Cinderella",
        detected_lang="en",
        emotion_scores=scores,
        style_scores=styles,
    )


def _make_T() -> dict:
    """Minimal strings dict matching EN keys in app/strings.py."""
    return {
        # Quick Insight — fiction
        "qi_ai_narrative_label": "AI NARRATIVE",
        "qi_fi_headline_label": "STORY PROFILE",
        "qi_fi_chars_label": "KEY CHARACTERS",
        "qi_fi_chars_en_only": "Character detection: English only",
        "qi_fi_shape_label": "STORY SHAPE",
        "qi_fi_style_label": "WRITING STYLE",
        "qi_fi_top_emotions_fallback": "Top emotions",
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
        # Shared
        "qi_for_you_label": "Who it's for",
        # Recommendations
        "qi_recs_label": "[Experimental] You might also like",
        "qi_recs_disclaimer": "AI suggestions — quality varies.",
        "qi_recs_unavailable": "Recommendations unavailable.",
        # Readability labels (used as dict keys in quick_insight.py academic section)
        "readable_accessible": "Accessible",
        "readable_moderate": "Moderate",
        "readable_dense": "Dense",
        "readable_specialist": "Specialist",
        # Emotion names
        "emotion_names": {
            "joy": "Joy", "trust": "Trust", "anticipation": "Anticipation",
            "fear": "Fear", "sadness": "Sadness", "anger": "Anger",
            "disgust": "Disgust", "surprise": "Surprise",
        },
    }


# ---------------------------------------------------------------------------
# Smoke tests
# ---------------------------------------------------------------------------

class _FakeSessionState(dict):
    """dict subclass that supports attribute-style .get() for Streamlit compatibility."""
    pass


def _run_smoke(book_type: str) -> None:
    """Run render_quick_insight for the given book_type with all ST calls mocked."""
    chunks = _make_chunks(5)
    emotion_scores = [_make_emotion_score(i, joy=0.5, trust=0.3) for i in range(5)]
    style_scores = [_make_style_score(i) for i in range(5)]
    valence_series = [0.2, 0.4, 0.6, 0.5, 0.3]
    result = _make_result(book_type)
    T = _make_T()

    fake_ss = _FakeSessionState()
    spinner_cm = MagicMock()
    spinner_cm.__enter__ = MagicMock(return_value=None)
    spinner_cm.__exit__ = MagicMock(return_value=False)

    with (
        patch("app.tabs.quick_insight.st") as mock_st,
        patch(
            "app.tabs.quick_insight.generate_narrative_insight",
            return_value="A great read.",
        ),
        patch(
            "app.tabs.quick_insight.extract_nonfiction_concepts",
            return_value=(["concept1", "concept2"], "Strong argument."),
        ),
        patch(
            "app.tabs.quick_insight.extract_essay_voice",
            return_value="Reflective voice.",
        ),
        patch("app.tabs.quick_insight.call_llm", return_value=""),
    ):
        mock_st.session_state = fake_ss
        mock_st.spinner.return_value = spinner_cm
        mock_st.columns.return_value = [MagicMock(), MagicMock(), MagicMock()]
        mock_st.markdown = MagicMock()
        mock_st.info = MagicMock()

        from app.tabs.quick_insight import render_quick_insight

        render_quick_insight(
            book_type=book_type,
            book_title="Test Book",
            arc_value="Cinderella",
            arc_display_name="Cinderella",
            top_emotion_key="joy",
            top_emotion_name="Joy",
            top_emotion_color="#22c55e",
            total_words=1200,
            chunks=chunks,
            emotion_scores=emotion_scores,
            style_scores=style_scores,
            valence_series=valence_series,
            detected_lang="en",
            ui_lang="en",
            T=T,
            analysis_result=result,
        )


class TestQuickInsightSmoke:
    def test_fiction_no_exception(self):
        """render_quick_insight('fiction', ...) must not raise."""
        _run_smoke("fiction")

    def test_academic_no_exception(self):
        """render_quick_insight('academic', ...) must not raise."""
        _run_smoke("academic")

    def test_essay_no_exception(self):
        """render_quick_insight('essay', ...) must not raise."""
        _run_smoke("essay")

    def test_fiction_empty_chunks_no_exception(self):
        """Empty chunks list must not cause a crash (graceful degradation)."""
        T = _make_T()
        fake_ss = _FakeSessionState()
        spinner_cm = MagicMock()
        spinner_cm.__enter__ = MagicMock(return_value=None)
        spinner_cm.__exit__ = MagicMock(return_value=False)

        with (
            patch("app.tabs.quick_insight.st") as mock_st,
            patch("app.tabs.quick_insight.generate_narrative_insight", return_value=""),
            patch("app.tabs.quick_insight.call_llm", return_value=""),
        ):
            mock_st.session_state = fake_ss
            mock_st.spinner.return_value = spinner_cm
            mock_st.columns.return_value = [MagicMock(), MagicMock(), MagicMock()]
            mock_st.markdown = MagicMock()
            mock_st.info = MagicMock()

            from app.tabs.quick_insight import render_quick_insight

            render_quick_insight(
                book_type="fiction",
                book_title="Empty Book",
                arc_value="Unknown",
                arc_display_name="Unknown",
                top_emotion_key="joy",
                top_emotion_name="Joy",
                top_emotion_color="#22c55e",
                total_words=0,
                chunks=[],
                emotion_scores=[],
                style_scores=[],
                valence_series=[],
                detected_lang="en",
                ui_lang="en",
                T=T,
                analysis_result=None,
            )

    def test_cjk_detected_lang_no_exception(self):
        """CJK detected_lang ('zh') must not raise (character extraction returns [])."""
        chunks = _make_chunks(3)
        emotion_scores = [_make_emotion_score(i, joy=0.5) for i in range(3)]
        style_scores = [_make_style_score(i) for i in range(3)]
        result = _make_result("fiction")
        T = _make_T()
        fake_ss = _FakeSessionState()
        spinner_cm = MagicMock()
        spinner_cm.__enter__ = MagicMock(return_value=None)
        spinner_cm.__exit__ = MagicMock(return_value=False)

        with (
            patch("app.tabs.quick_insight.st") as mock_st,
            patch("app.tabs.quick_insight.generate_narrative_insight", return_value=""),
            patch("app.tabs.quick_insight.call_llm", return_value=""),
        ):
            mock_st.session_state = fake_ss
            mock_st.spinner.return_value = spinner_cm
            mock_st.columns.return_value = [MagicMock(), MagicMock(), MagicMock()]
            mock_st.markdown = MagicMock()
            mock_st.info = MagicMock()

            from app.tabs.quick_insight import render_quick_insight

            render_quick_insight(
                book_type="fiction",
                book_title="Chinese Book",
                arc_value="Cinderella",
                arc_display_name="Cinderella",
                top_emotion_key="joy",
                top_emotion_name="Joy",
                top_emotion_color="#22c55e",
                total_words=800,
                chunks=chunks,
                emotion_scores=emotion_scores,
                style_scores=style_scores,
                valence_series=[0.3, 0.5, 0.4],
                detected_lang="zh",
                ui_lang="zh",
                T=T,
                analysis_result=result,
            )

    def test_all_book_types_call_markdown(self):
        """All three book types should produce at least one st.markdown call."""
        for book_type in ("fiction", "academic", "essay"):
            chunks = _make_chunks(5)
            emotion_scores = [_make_emotion_score(i, joy=0.5) for i in range(5)]
            style_scores = [_make_style_score(i) for i in range(5)]
            result = _make_result(book_type)
            T = _make_T()
            fake_ss = _FakeSessionState()
            spinner_cm = MagicMock()
            spinner_cm.__enter__ = MagicMock(return_value=None)
            spinner_cm.__exit__ = MagicMock(return_value=False)

            with (
                patch("app.tabs.quick_insight.st") as mock_st,
                patch(
                    "app.tabs.quick_insight.generate_narrative_insight",
                    return_value="Insight text.",
                ),
                patch(
                    "app.tabs.quick_insight.extract_nonfiction_concepts",
                    return_value=(["c1"], "Arg."),
                ),
                patch(
                    "app.tabs.quick_insight.extract_essay_voice",
                    return_value="Voice.",
                ),
                patch("app.tabs.quick_insight.call_llm", return_value=""),
            ):
                mock_st.session_state = fake_ss
                mock_st.spinner.return_value = spinner_cm
                mock_st.columns.return_value = [MagicMock(), MagicMock(), MagicMock()]
                mock_st.markdown = MagicMock()
                mock_st.info = MagicMock()

                from app.tabs.quick_insight import render_quick_insight

                render_quick_insight(
                    book_type=book_type,
                    book_title="Test",
                    arc_value="Cinderella",
                    arc_display_name="Cinderella",
                    top_emotion_key="joy",
                    top_emotion_name="Joy",
                    top_emotion_color="#22c55e",
                    total_words=1000,
                    chunks=chunks,
                    emotion_scores=emotion_scores,
                    style_scores=style_scores,
                    valence_series=[0.3, 0.5, 0.6, 0.4, 0.3],
                    detected_lang="en",
                    ui_lang="en",
                    T=T,
                    analysis_result=result,
                )

                assert mock_st.markdown.called, f"markdown not called for {book_type}"
