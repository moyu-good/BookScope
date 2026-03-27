"""Split a BookText into analysis-unit chunks.

Two strategies:
  - "paragraph": split on blank lines (natural narrative boundaries)
  - "fixed":     split into fixed word-count windows with 50% overlap

Data flow:
    BookText.raw_text
        │
        ├─[paragraph]─→ split on \\n\\n  → filter short paragraphs
        │
        └─[fixed]─────→ sliding window (word_limit words, step=word_limit//2)
        │
        ▼
    list[ChunkResult]
"""

import re

from bookscope.ingest.cleaner import clean
from bookscope.models import BookText, ChunkResult

DEFAULT_MIN_WORDS = 20
DEFAULT_WORD_LIMIT = 200


def chunk(
    book: BookText,
    strategy: str = "paragraph",
    word_limit: int = DEFAULT_WORD_LIMIT,
    min_words: int = DEFAULT_MIN_WORDS,
) -> list[ChunkResult]:
    """Split BookText into ChunkResult list.

    Args:
        book: Source BookText.
        strategy: "paragraph" or "fixed".
        word_limit: Words per window for the "fixed" strategy.
        min_words: Minimum words for a paragraph to be kept (paragraph strategy).

    Returns:
        List of ChunkResult objects (may be empty for very short texts).

    Raises:
        ValueError: If strategy is not "paragraph" or "fixed".
    """
    text = clean(book.raw_text)
    lang = getattr(book, "language", "en")

    if strategy == "paragraph":
        return _chunk_by_paragraph(text, min_words, lang)
    elif strategy == "fixed":
        return _chunk_fixed(text, word_limit, lang)
    else:
        raise ValueError(f"Unknown chunking strategy: {strategy!r}. Use 'paragraph' or 'fixed'.")


def _word_count(text: str, lang: str) -> int:
    """Language-aware word count for filtering short chunks."""
    if lang in ("zh", "ja"):
        # CJK: count non-whitespace characters as a proxy for word count
        return len(text.replace(" ", "").replace("\n", "").replace("\t", ""))
    return len(text.split())


def _tokenize_for_fixed(text: str, lang: str) -> list[str]:
    """Return a token list for the fixed-window chunker."""
    if lang == "zh":
        try:
            import jieba  # type: ignore[import]
            return list(jieba.cut(text))
        except ImportError:
            pass
    elif lang == "ja":
        try:
            from janome.tokenizer import Tokenizer  # type: ignore[import]
            return [tok.surface for tok in Tokenizer().tokenize(text)]
        except ImportError:
            pass
    return text.split()


def _chunk_by_paragraph(text: str, min_words: int, lang: str) -> list[ChunkResult]:
    paragraphs = re.split(r"\n\n+", text) if "\n\n" in text else [text]
    results = []
    for para in paragraphs:
        para = para.strip()
        wc = _word_count(para, lang)
        if wc >= min_words:
            results.append(ChunkResult(index=len(results), text=para, word_count=wc))
    return results


def _chunk_fixed(text: str, word_limit: int, lang: str) -> list[ChunkResult]:
    tokens = _tokenize_for_fixed(text, lang)
    if not tokens:
        return []

    sep = "" if lang in ("zh", "ja") else " "
    step = max(1, word_limit // 2)
    results = []
    pos = 0
    while pos < len(tokens):
        window = tokens[pos : pos + word_limit]
        chunk_text = sep.join(window)
        results.append(ChunkResult(index=len(results), text=chunk_text, word_count=_word_count(chunk_text, lang)))
        pos += step

    return results


