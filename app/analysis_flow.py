"""BookScope — analysis pipeline and state resolution."""

import pathlib

import streamlit as st

from bookscope.nlp import LexiconAnalyzer, StyleAnalyzer, detect_language


def _run_pipeline(book, strategy: str, chunk_size: int, min_words: int):
    """Language detection → chunking → emotion + style analysis."""
    from bookscope.ingest import chunk

    lang = detect_language(book.raw_text)
    book = book.model_copy(update={"language": lang})
    chunks = chunk(book, strategy=strategy, word_limit=chunk_size, min_words=min_words)
    emotion_scores = LexiconAnalyzer(language=lang).analyze_book(chunks)
    style_scores = StyleAnalyzer(language=lang).analyze_book(chunks)
    return chunks, emotion_scores, style_scores, lang


@st.cache_data(show_spinner=False)
def run_preview(
    file_bytes: bytes,
    filename: str,
    strategy: str,
    chunk_size: int,
    min_words: int,
) -> list:
    """Load and chunk only — no emotion or style analysis.

    Returns list[ChunkResult]. Callers take the first 5 chunks for a
    quick LLM-generated preview without running the full pipeline.
    Uses @st.cache_data so a subsequent run_analysis() call with the
    same arguments benefits from the OS page cache on the tmp file.
    """
    import os
    import tempfile

    from bookscope.ingest import chunk
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

    lang = detect_language(book.raw_text)
    book = book.model_copy(update={"language": lang})
    chunks = chunk(book, strategy=strategy, word_limit=chunk_size, min_words=min_words)
    return chunks


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


def resolve_analysis_state(
    uploaded,
    url_input: str,
    loaded_result,
    demo_mode: bool,
    strategy: str,
    chunk_size: int,
    min_words: int,
    T: dict,
) -> tuple:
    """Resolve analysis data from demo / saved / upload / URL input.

    Returns:
        (chunks, emotion_scores, style_scores, detected_lang,
         book_title, n_chunks, total_words, from_saved)
    """
    _demo_path = pathlib.Path(__file__).parent / "demo_book.txt"
    from_saved = False
    chunks = None

    if demo_mode and uploaded is None and not url_input and loaded_result is None:
        _demo_bytes = _demo_path.read_bytes()
        with st.spinner(T["analysing"]):
            chunks, emotion_scores, style_scores, detected_lang = run_analysis(
                _demo_bytes,
                "The_Lighthouse_Keepers_Last_Storm.txt",
                strategy,
                chunk_size,
                min_words,
            )
        if not chunks:
            st.warning(T["no_chunks_warning"])
            st.stop()
        book_title = "The Lighthouse Keeper's Last Storm"
        n_chunks = len(chunks)
        total_words = sum(c.word_count for c in chunks)

    elif loaded_result is not None and uploaded is None and not url_input:
        emotion_scores = loaded_result.emotion_scores
        style_scores = loaded_result.style_scores
        book_title = loaded_result.book_title
        detected_lang = loaded_result.detected_lang
        n_chunks = loaded_result.total_chunks
        total_words = loaded_result.total_words
        from_saved = True

    else:
        with st.spinner(T["analysing"]):
            if uploaded is not None:
                file_bytes = uploaded.getvalue()
                chunks, emotion_scores, style_scores, detected_lang = run_analysis(
                    file_bytes, uploaded.name, strategy, chunk_size, min_words,
                )
                book_title = uploaded.name
                for ext in (".txt", ".epub", ".pdf"):
                    book_title = book_title.removesuffix(ext)
            else:
                try:
                    (
                        chunks, emotion_scores, style_scores,
                        detected_lang, book_title,
                    ) = run_analysis_url(url_input, strategy, chunk_size, min_words)
                except Exception as exc:
                    st.error(T["url_error"].format(exc))
                    st.stop()

        if not chunks:
            st.warning(T["no_chunks_warning"])
            st.stop()

        n_chunks = len(chunks)
        total_words = sum(c.word_count for c in chunks)

    return (
        chunks, emotion_scores, style_scores, detected_lang,
        book_title, n_chunks, total_words, from_saved,
    )
