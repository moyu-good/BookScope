"""Three-layer book chunker for long-form novels.

Designed for Chinese novels (50万字+) where paragraph-level chunking
produces 25K+ tiny fragments.  Implements a hierarchical approach:

    Layer 1 — Chapter detection (regex on 第X章/回/节)
    Layer 2 — Merge consecutive paragraphs into ~1500-char semantic chunks
    Layer 3 — Contextual headers prepended to each chunk

Result: 25K paragraphs → ~200-400 chunks, each with rich context.

References:
    - NVIDIA 2024 Benchmark: analytical questions need 1024+ tokens
    - Vectara NAACL 2025: context cliff at ~2500 tokens
    - Anthropic Contextual Retrieval: chunk headers reduce retrieval failure 67%
"""

from __future__ import annotations

import re

from bookscope.ingest.cleaner import clean
from bookscope.models import BookText, ChunkResult

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CHUNK_CHAR_TARGET = 1500   # target chars per chunk (~800 tokens for Chinese)
CHUNK_CHAR_MIN = 300       # don't emit chunks shorter than this
CHUNK_CHAR_MAX = 3000      # hard cap (~1500 tokens, below context cliff)
OVERLAP_CHARS = 150        # ~10% overlap for continuity

# Chinese chapter heading patterns
_CHAPTER_RE = re.compile(
    r"^(?:"
    r"第[一二三四五六七八九十百千零\d]+[章回节篇卷部]"  # 第X章/回/节/篇/卷/部
    r"|Chapter\s+\d+"                                    # Chapter N
    r"|CHAPTER\s+\d+"                                    # CHAPTER N
    r"|卷[一二三四五六七八九十\d]+"                       # 卷X
    r"|[（(]\d+[)）]"                                    # (1) or （1）
    r")",
    re.MULTILINE,
)

# Chinese sentence-ending punctuation for splitting
_CN_SENT_END = re.compile(r"(?<=[。！？；\n])")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def chunk_book(
    book: BookText,
    chunk_target: int = CHUNK_CHAR_TARGET,
    chunk_min: int = CHUNK_CHAR_MIN,
    overlap: int = OVERLAP_CHARS,
) -> list[ChunkResult]:
    """Split a book into semantically coherent chunks with chapter context.

    Returns a list of ``ChunkResult`` with contextual headers.
    """
    text = clean(book.raw_text)
    lang = getattr(book, "language", "en")
    title = book.title

    # Layer 1: detect chapters
    chapters = _detect_chapters(text)

    # Layer 2+3: merge paragraphs within chapters + add headers
    results: list[ChunkResult] = []
    for ch_num, ch_title, ch_text in chapters:
        header = _build_header(title, ch_num, ch_title)
        chunks = _merge_paragraphs(ch_text, chunk_target, chunk_min, overlap, lang)
        for chunk_text in chunks:
            full_text = f"{header}\n{chunk_text}" if header else chunk_text
            wc = _char_count(full_text, lang)
            results.append(ChunkResult(
                index=len(results),
                text=full_text,
                word_count=wc,
            ))

    return results


# ---------------------------------------------------------------------------
# Layer 1: Chapter detection
# ---------------------------------------------------------------------------

_MAX_HEADING_LINE_LEN = 60  # chapter heading lines should be short


def _detect_chapters(text: str) -> list[tuple[int, str, str]]:
    """Split text into (chapter_number, chapter_title, chapter_body) tuples.

    If no chapter headings are found, returns the entire text as one chapter.
    Only lines shorter than ``_MAX_HEADING_LINE_LEN`` are treated as headings
    to avoid matching "第X章" inside regular paragraph text.
    """
    matches: list[re.Match] = []
    for m in _CHAPTER_RE.finditer(text):
        line_end = text.find("\n", m.start())
        if line_end == -1:
            line_end = len(text)
        line_len = line_end - m.start()
        if line_len <= _MAX_HEADING_LINE_LEN:
            matches.append(m)

    if not matches:
        return [(1, "", text)]

    chapters: list[tuple[int, str, str]] = []

    for i, match in enumerate(matches):
        line_end = text.find("\n", match.start())
        if line_end == -1:
            line_end = len(text)
        ch_title_line = text[match.start():line_end].strip()

        body_start = line_end + 1
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()

        chapters.append((i + 1, ch_title_line, body))

    # Include any text before the first chapter heading as "prologue"
    prologue = text[:matches[0].start()].strip()
    if prologue and len(prologue) > CHUNK_CHAR_MIN:
        chapters.insert(0, (0, "序", prologue))

    return chapters


# ---------------------------------------------------------------------------
# Layer 2: Paragraph merging
# ---------------------------------------------------------------------------

def _merge_paragraphs(
    text: str,
    target: int,
    minimum: int,
    overlap: int,
    lang: str,
) -> list[str]:
    """Merge consecutive paragraphs/sentences into chunks of ~target chars."""
    if not text.strip():
        return []

    # Split into paragraphs first
    paragraphs = re.split(r"\n\n+", text)
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    if not paragraphs:
        return []

    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        # If a single paragraph exceeds max, split it by sentences
        if len(para) > CHUNK_CHAR_MAX:
            # Flush current buffer
            if current.strip():
                chunks.append(current.strip())
                current = ""
            # Split long paragraph by sentence boundaries
            chunks.extend(_split_long_text(para, target, minimum, lang))
            continue

        # Try adding paragraph to current chunk
        candidate = f"{current}\n{para}" if current else para
        if len(candidate) > CHUNK_CHAR_MAX:
            # Current chunk is full, emit it
            if current.strip():
                chunks.append(current.strip())
            # Start new chunk with overlap
            if overlap > 0 and current:
                tail = current[-overlap:]
                current = f"{tail}\n{para}"
            else:
                current = para
        elif len(candidate) >= target:
            # Hit target, emit
            chunks.append(candidate.strip())
            # Overlap for next chunk
            if overlap > 0:
                current = para[-overlap:] if len(para) > overlap else para
            else:
                current = ""
        else:
            current = candidate

    # Flush remainder
    if current.strip():
        if chunks and len(current.strip()) < minimum:
            # Too short — append to last chunk
            chunks[-1] = f"{chunks[-1]}\n{current.strip()}"
        else:
            chunks.append(current.strip())

    return chunks


def _split_long_text(
    text: str,
    target: int,
    minimum: int,
    lang: str,
) -> list[str]:
    """Split a very long paragraph by sentence boundaries."""
    if lang in ("zh", "ja"):
        sentences = _CN_SENT_END.split(text)
    else:
        sentences = re.split(r"(?<=[.!?])\s+", text)

    sentences = [s.strip() for s in sentences if s.strip()]

    chunks: list[str] = []
    current = ""
    for sent in sentences:
        candidate = f"{current}{sent}" if current else sent
        if len(candidate) >= target:
            if current.strip():
                chunks.append(current.strip())
            current = sent
        else:
            current = candidate

    if current.strip():
        if chunks and len(current.strip()) < minimum:
            chunks[-1] += current.strip()
        else:
            chunks.append(current.strip())

    return chunks


# ---------------------------------------------------------------------------
# Layer 3: Contextual headers
# ---------------------------------------------------------------------------

def _build_header(book_title: str, chapter_num: int, chapter_title: str) -> str:
    """Build a contextual header for a chunk."""
    if chapter_num == 0:
        return f"[《{book_title}》序章]"
    if chapter_title:
        return f"[《{book_title}》{chapter_title}]"
    return f"[《{book_title}》第{chapter_num}章]"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _char_count(text: str, lang: str) -> int:
    """Language-aware character/word count."""
    if lang in ("zh", "ja"):
        return len(text.replace(" ", "").replace("\n", "").replace("\t", ""))
    return len(text.split())
