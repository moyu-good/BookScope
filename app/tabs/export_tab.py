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
