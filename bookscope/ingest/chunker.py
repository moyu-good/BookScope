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

    if strategy == "paragraph":
        return _chunk_by_paragraph(text, min_words)
    elif strategy == "fixed":
        return _chunk_fixed(text, word_limit)
    else:
        raise ValueError(f"Unknown chunking strategy: {strategy!r}. Use 'paragraph' or 'fixed'.")


def _chunk_by_paragraph(text: str, min_words: int) -> list[ChunkResult]:
    paragraphs = re.split(r"\n\n+", text) if "\n\n" in text else [text]
    results = []
    for i, para in enumerate(paragraphs):
        para = para.strip()
        if len(para.split()) >= min_words:
            results.append(ChunkResult(index=len(results), text=para))
    return results


def _chunk_fixed(text: str, word_limit: int) -> list[ChunkResult]:
    words = text.split()
    if not words:
        return []

    step = max(1, word_limit // 2)
    results = []
    pos = 0
    while pos < len(words):
        window = words[pos : pos + word_limit]
        results.append(ChunkResult(index=len(results), text=" ".join(window)))
        pos += step

    return results


