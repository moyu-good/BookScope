"""Pluggable analyzer interface.

Any backend must satisfy this Protocol.
Swapping backends requires zero changes to the pipeline or viz layer.

Production backend:
    LexiconAnalyzer  (nrclex, fast, CPU-only, no GPU required)
"""

from typing import Protocol, runtime_checkable

from bookscope.models import ChunkResult, EmotionScore


@runtime_checkable
class AnalyzerProtocol(Protocol):
    """Minimum interface every emotion analyzer must implement."""

    def analyze_chunk(self, chunk: ChunkResult) -> EmotionScore:
        """Compute an 8-dimensional emotion score for one chunk.

        Args:
            chunk: A ChunkResult with .text and .index.

        Returns:
            EmotionScore with chunk_index matching chunk.index.
        """
        ...

    def analyze_book(self, chunks: list[ChunkResult]) -> list[EmotionScore]:
        """Analyze all chunks of a book.

        Default implementation calls analyze_chunk sequentially.
        Override for batched / GPU-accelerated backends.
        """
        ...
