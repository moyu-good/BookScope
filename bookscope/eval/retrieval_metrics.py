"""BookScope — Retrieval evaluation metrics.

Pure math functions for evaluating ranked retrieval quality.
Only dependency: numpy (already in project deps).

All functions accept:
    retrieved: ordered list of chunk indices (from search results)
    relevant:  set of gold-relevant chunk indices
    k:         cutoff depth
"""

from __future__ import annotations

import numpy as np


def recall_at_k(retrieved: list[int], relevant: set[int], k: int) -> float:
    """Fraction of relevant documents found in the top-K retrieved results."""
    if not relevant:
        return 0.0
    top_k = set(retrieved[:k])
    return len(top_k & relevant) / len(relevant)


def mrr_at_k(retrieved: list[int], relevant: set[int], k: int) -> float:
    """Reciprocal rank of the first relevant document in top-K."""
    if not relevant:
        return 0.0
    for rank, doc_id in enumerate(retrieved[:k]):
        if doc_id in relevant:
            return 1.0 / (rank + 1)
    return 0.0


def ndcg_at_k(retrieved: list[int], relevant: set[int], k: int) -> float:
    """Normalized Discounted Cumulative Gain at K (binary relevance)."""
    if not relevant:
        return 0.0
    top_k = retrieved[:k]
    # DCG: sum rel(i) / log2(i + 2)  (1-indexed rank in denominator)
    dcg = sum(
        1.0 / np.log2(i + 2) for i, doc_id in enumerate(top_k) if doc_id in relevant
    )
    # Ideal DCG: all relevant at top positions
    ideal_hits = min(k, len(relevant))
    idcg = sum(1.0 / np.log2(i + 2) for i in range(ideal_hits))
    if idcg == 0.0:
        return 0.0
    return dcg / idcg


def hit_rate_at_k(retrieved: list[int], relevant: set[int], k: int) -> float:
    """1.0 if any relevant document appears in top-K, else 0.0."""
    if not relevant:
        return 0.0
    top_k = set(retrieved[:k])
    return 1.0 if top_k & relevant else 0.0
