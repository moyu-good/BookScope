"""Export tab — CSV / JSON / Markdown / PNG share card download buttons."""

import streamlit as st

from bookscope.store import AnalysisResult
from bookscope.viz import generate_share_card


def render_export(
    book_title: str,
    strategy: str,
    n_chunks: int,
    total_words: int,
    arc,
    detected_lang: str,
    emotion_scores,
    style_scores,
    T: dict,
    book_type: str = "fiction",
    top_emotion_name: str = "",
    ai_narrative: str = "",
    ui_lang: str = "en",
) -> None:
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

    col_e, col_s, col_j, col_md, col_card = st.columns(5)
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
    card_png = generate_share_card(
        book_title=result.book_title,
        arc_pattern=result.arc_pattern,
        detected_lang=result.detected_lang,
        total_words=result.total_words,
        n_chunks=result.total_chunks,
        emotion_scores=result.emotion_scores,
    )
    col_card.download_button(
        label=T["export_card"],
        data=card_png,
        file_name=f"{result.book_title}_card.png",
        mime="image/png",
    )

    # ── Book Club Pack PNG ─────────────────────────────────────────────────────
    st.divider()
    bc_btn_label = T.get("export_book_club_pack", "📚 Generate Book Club Pack PNG")
    bc_ck = f"bc_export_{book_title}_{arc.value}_{book_type}_{ui_lang}"
    bc_pack = st.session_state.get(bc_ck)

    if st.button(bc_btn_label, key=f"bc_export_btn_{bc_ck}"):
        from bookscope.nlp.llm_analyzer import generate_book_club_pack_structured

        with st.spinner(T.get("export_book_club_spinner", "Generating Book Club Pack…")):
            bc_pack = generate_book_club_pack_structured(
                book_title=book_title,
                arc_value=arc.value,
                top_emotion_name=top_emotion_name or "joy",
                book_type=book_type,
                ai_narrative=ai_narrative,
                lang=ui_lang,
            )
        if bc_pack is None:
            st.warning(T.get(
                "export_book_club_error",
                "Could not generate Book Club Pack — check your API key.",
            ))
        else:
            st.session_state[bc_ck] = bc_pack

    if bc_pack is not None:
        from bookscope.viz.card_renderer import render_book_club_card

        bc_png = render_book_club_card(bc_pack)
        st.download_button(
            label=T.get("export_book_club_download", "⬇️ Download Book Club Pack PNG"),
            data=bc_png,
            file_name=f"{book_title}_book_club_pack.png",
            mime="image/png",
        )
