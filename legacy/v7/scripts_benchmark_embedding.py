#!/usr/bin/env python3
"""Benchmark embedding providers using the P3 evaluation pipeline.

Usage:
    # BM25-only baseline (no API key needed)
    python scripts/benchmark_embedding.py

    # SiliconFlow API
    SILICONFLOW_API_KEY=xxx python scripts/benchmark_embedding.py

    # Specific provider
    BOOKSCOPE_EMBEDDING_PROVIDER=local-bge-m3 python scripts/benchmark_embedding.py

The script uses inline Chinese QA samples and measures Recall@5, MRR@5,
NDCG@5, and Hit Rate@5.
"""

from __future__ import annotations

import os
import sys
import time

import numpy as np

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bookscope.eval.retrieval_metrics import (
    hit_rate_at_k,
    mrr_at_k,
    ndcg_at_k,
    recall_at_k,
)
from bookscope.models.schemas import ChunkResult
from bookscope.store.embedding_provider import get_embedding_provider

# ---------------------------------------------------------------------------
# Inline test data (Ming Dynasty themed)
# ---------------------------------------------------------------------------

CHUNKS = [
    ChunkResult(index=0, text="朱元璋原名朱重八，出身于濠州钟离的一个贫苦农家。"),
    ChunkResult(index=1, text="陈友谅拥兵百万，是朱元璋争夺天下的主要对手。"),
    ChunkResult(index=2, text="刘伯温精通天文兵法，辅佐朱元璋建立了大明王朝。"),
    ChunkResult(index=3, text="徐达是明朝开国第一名将，北伐中原收复大都。"),
    ChunkResult(index=4, text="刘伯温向朱元璋献计，建议先灭陈友谅再取张士诚。"),
    ChunkResult(index=5, text="朱元璋于1368年在南京称帝，国号大明，年号洪武。"),
    ChunkResult(index=6, text="鄱阳湖大战是朱元璋与陈友谅的生死决战，朱元璋以少胜多。"),
    ChunkResult(index=7, text="李白是唐朝最伟大的浪漫主义诗人，号青莲居士。"),
    ChunkResult(index=8, text="朱元璋建立锦衣卫，加强中央集权和对官员的监控。"),
    ChunkResult(index=9, text="明朝实行科举制度，八股取士成为选拔官员的主要方式。"),
]

EVAL_SAMPLES = [
    {"question": "朱元璋是谁", "relevant": [0, 5]},
    {"question": "刘伯温的贡献", "relevant": [2, 4]},
    {"question": "鄱阳湖大战", "relevant": [6, 1]},
    {"question": "徐达北伐", "relevant": [3]},
    {"question": "明朝制度", "relevant": [8, 9]},
]

K = 5


def evaluate(store, label: str) -> dict[str, float]:
    """Run evaluation and print results."""
    recalls, mrrs, ndcgs, hits = [], [], [], []
    for sample in EVAL_SAMPLES:
        results = store.search(sample["question"], top_k=K, enable_rerank=False)
        retrieved = [c.index for c, _ in results]
        relevant = set(sample["relevant"])
        recalls.append(recall_at_k(retrieved, relevant, K))
        mrrs.append(mrr_at_k(retrieved, relevant, K))
        ndcgs.append(ndcg_at_k(retrieved, relevant, K))
        hits.append(hit_rate_at_k(retrieved, relevant, K))

    scores = {
        f"Recall@{K}": float(np.mean(recalls)),
        f"MRR@{K}": float(np.mean(mrrs)),
        f"NDCG@{K}": float(np.mean(ndcgs)),
        f"HitRate@{K}": float(np.mean(hits)),
    }
    print(f"\n{'=' * 50}")
    print(f"  {label}")
    print(f"{'=' * 50}")
    for metric, val in scores.items():
        print(f"  {metric:12s}: {val:.4f}")
    return scores


def main():
    from bookscope.store.vector_store import SessionVectorStore

    print("BookScope Embedding Benchmark")
    print(f"Chunks: {len(CHUNKS)}, Queries: {len(EVAL_SAMPLES)}, K={K}")

    # Strategy 1: BM25-only (always works)
    print("\nBuilding BM25 index...")
    t0 = time.time()
    store_bm25 = SessionVectorStore(CHUNKS, enable_vector=False)
    print(f"  BM25 index built in {time.time() - t0:.2f}s")
    evaluate(store_bm25, "BM25-only (baseline)")

    # Strategy 2: Hybrid (BM25 + embedding provider)
    provider = get_embedding_provider()
    if provider is None:
        print("\nNo embedding provider available. Set SILICONFLOW_API_KEY or")
        print("BOOKSCOPE_EMBEDDING_PROVIDER to enable vector search.")
        print("Skipping hybrid benchmark.")
        return

    print(f"\nEmbedding provider: {provider.name}")
    print("Building hybrid index (BM25 + vector)...")
    t0 = time.time()
    store_hybrid = SessionVectorStore(CHUNKS, enable_vector=True)
    print(f"  Hybrid index built in {time.time() - t0:.2f}s")
    evaluate(store_hybrid, f"Hybrid (BM25 + {provider.name})")

    # Strategy 3: Hybrid + reranker (if available)
    try:
        print("\nTesting hybrid + reranker...")
        results = store_hybrid.search("朱元璋", top_k=K, enable_rerank=True)
        if results:
            # Re-evaluate with reranker
            recalls, mrrs, ndcgs, hits = [], [], [], []
            for sample in EVAL_SAMPLES:
                results = store_hybrid.search(
                    sample["question"], top_k=K, enable_rerank=True,
                )
                retrieved = [c.index for c, _ in results]
                relevant = set(sample["relevant"])
                recalls.append(recall_at_k(retrieved, relevant, K))
                mrrs.append(mrr_at_k(retrieved, relevant, K))
                ndcgs.append(ndcg_at_k(retrieved, relevant, K))
                hits.append(hit_rate_at_k(retrieved, relevant, K))

            reranker_name = os.environ.get(
                "BOOKSCOPE_RERANKER_MODEL", "BAAI/bge-reranker-v2-m3",
            )
            print(f"\n{'=' * 50}")
            print(f"  Hybrid + Reranker ({reranker_name})")
            print(f"{'=' * 50}")
            for metric, val in zip(
                [f"Recall@{K}", f"MRR@{K}", f"NDCG@{K}", f"HitRate@{K}"],
                [np.mean(recalls), np.mean(mrrs), np.mean(ndcgs), np.mean(hits)],
            ):
                print(f"  {metric:12s}: {val:.4f}")
    except Exception as e:
        print(f"  Reranker unavailable: {e}")

    print("\nDone.")


if __name__ == "__main__":
    main()
