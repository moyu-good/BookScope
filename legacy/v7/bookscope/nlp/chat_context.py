"""Build hybrid RAG + KG context for chat endpoints.

Extracted from bookscope/api/main.py (_build_chat_context).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bookscope.models.schemas import BookKnowledgeGraph, BookText
    from bookscope.store.vector_store import SessionVectorStore

RAG_TOP_K = 5
CHUNK_CHAR_LIMIT = 600


def build_chat_context(
    book: BookText,
    graph: BookKnowledgeGraph | None,
    vector_store: SessionVectorStore | None,
    message: str,
    *,
    rag_top_k: int = RAG_TOP_K,
    chunk_char_limit: int = CHUNK_CHAR_LIMIT,
) -> str:
    """Build hybrid context: RAG-retrieved chunks + condensed knowledge graph."""
    parts = [f"Book: {book.title}", f"Language: {book.language}"]

    if graph:
        if graph.overall_summary:
            parts.append(f"\n--- Book Summary ---\n{graph.overall_summary}")
        chars_desc = []
        for c in graph.characters[:4]:
            line = c.name
            if c.description:
                line += f" — {c.description[:80]}"
            chars_desc.append(line)
        if chars_desc:
            parts.append("Main characters: " + "; ".join(chars_desc))

    if vector_store is not None:
        retrieved = vector_store.search(message, top_k=rag_top_k)
        if retrieved:
            parts.append("\n--- Relevant passages ---")
            for chunk_result, score in retrieved:
                text = chunk_result.text[:chunk_char_limit]
                parts.append(
                    f"[Passage {chunk_result.index + 1} (relevance: {score:.2f})]\n{text}"
                )
    elif graph:
        for ch in graph.chapter_summaries[:10]:
            if ch.summary:
                parts.append(f"Section {ch.chunk_index}: {ch.summary}")

    return "\n".join(parts)
