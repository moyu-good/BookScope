"""检索质量评估：用 golden set 给 SessionVectorStore.search 算 recall@k / MRR。

WP2 主体第一步。把"检索失败"和"生成失败"拆开归因的第一份测量工具：
golden set（docs/internal/experiments/data/golden-retrieval-{book}.json）是人工通读
chunk 后标注的 ground truth，本脚本 ingest 同一本书、跑同一套 chunker，
逐条 query 调 store.search，按 expected_chunk_indices 命中算分。

前置条件:
- 对应 epub 在 repo 根目录（文件名映射见 _BOOKS）
- golden set 已标注且 chunker 行为与标注时一致（脚本会校验 chunk 总数，
  对不上直接拒跑——index 漂移时分数没有意义）
- 装了 SILICONFLOW_API_KEY 就走 hybrid，没装自然退 BM25-only，
  两种模式都照常跑，输出里标明 retrieval_mode

用法::

    python scripts/eval_retrieval.py --book anshi
    python scripts/eval_retrieval.py --book mingchao --top-k 10

指标定义:
- recall@k：单条 query 的 expected 集合里有多少出现在 top-k，对 query 取平均
- MRR：第一个命中 expected 的结果的 1/rank（1-based），无命中记 0，取平均
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_DATA_DIR = _PROJECT_ROOT / "docs" / "experiments" / "data"

_BOOKS = {
    "mingchao": "test明朝那些事儿.epub",
    "anshi": "test安史之乱  历史、宣传与神话 (张诗坪, 胡可奇).epub",
    "zhinei": (
        "test制内市场：中国国家主导型政治经济学（中国问题专家、高层智库郑永年权威解读，"
        "中国经济2020年如何实现超预期增长，突破百万亿元大关） (郑永... "
        "(z-library.sk, 1lib.sk, z-lib.sk).epub"
    ),
    "kuicheng": "test亏成首富从游戏开始 (青衫取醉) (z-library.sk, 1lib.sk, z-lib.sk).epub",
}


def _evaluate_query(
    retrieved_indices: list[int], expected: list[int], top_k: int,
) -> dict:
    """单条 query 的 recall@5 / recall@k / MRR 分量。"""
    expected_set = set(expected)
    hits_at_5 = expected_set & set(retrieved_indices[:5])
    hits_at_k = expected_set & set(retrieved_indices[:top_k])
    rr = 0.0
    for rank, idx in enumerate(retrieved_indices[:top_k], start=1):
        if idx in expected_set:
            rr = 1.0 / rank
            break
    return {
        "recall_at_5": len(hits_at_5) / len(expected_set),
        f"recall_at_{top_k}": len(hits_at_k) / len(expected_set),
        "reciprocal_rank": rr,
        "hit_indices": sorted(hits_at_k),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="按 golden set 评估 SessionVectorStore 检索质量",
    )
    parser.add_argument(
        "--book", required=True, choices=sorted(_BOOKS),
        help="书的短名（定位 epub 和 golden-retrieval-{book}.json）",
    )
    parser.add_argument(
        "--top-k", type=int, default=10, help="检索返回条数（默认 10）",
    )
    args = parser.parse_args()

    golden_path = _DATA_DIR / f"golden-retrieval-{args.book}.json"
    if not golden_path.is_file():
        print(f"golden set 不存在：{golden_path}", file=sys.stderr)
        return 1
    golden = json.loads(golden_path.read_text(encoding="utf-8"))

    epub_path = _PROJECT_ROOT / _BOOKS[args.book]
    if not epub_path.is_file():
        print(f"epub 不存在：{epub_path}", file=sys.stderr)
        return 1

    from bookscope.ingest.book_chunker import chunk_book
    from bookscope.ingest.loader import load_text
    from bookscope.store.vector_store import SessionVectorStore

    print(f"[eval] book={args.book} top_k={args.top_k}")
    t0 = time.monotonic()
    book = load_text(epub_path)
    book.language = "zh"  # 与 API ingest 行为一致（books.py:446）
    chunks = chunk_book(book)
    print(f"[eval] ingest+chunk {time.monotonic() - t0:.1f}s · {len(chunks)} chunks")

    if len(chunks) != golden["n_chunks"]:
        print(
            f"[eval] 拒跑：当前 chunker 产出 {len(chunks)} chunks，"
            f"golden set 标注时是 {golden['n_chunks']}。"
            "chunk index 已漂移，先重标 golden set。",
            file=sys.stderr,
        )
        return 2

    t0 = time.monotonic()
    store = SessionVectorStore(chunks)
    mode = store.retrieval_mode
    print(f"[eval] index built {time.monotonic() - t0:.1f}s · retrieval_mode={mode}")
    print("=" * 72)

    per_query: list[dict] = []
    for q in golden["queries"]:
        results = store.search(q["query"], top_k=args.top_k)
        retrieved = [chunk.index for chunk, _score in results]
        scores = _evaluate_query(retrieved, q["expected_chunk_indices"], args.top_k)
        per_query.append({
            "query": q["query"],
            "query_type": q["query_type"],
            "expected_chunk_indices": q["expected_chunk_indices"],
            "retrieved_indices": retrieved,
            **scores,
        })
        flag = "·" if scores["reciprocal_rank"] > 0 else "✗"
        print(
            f"{flag} [{q['query_type'][:4]}] r@5={scores['recall_at_5']:.2f} "
            f"rr={scores['reciprocal_rank']:.2f} | {q['query'][:36]}"
        )

    # --- 汇总：整体 + 按 query_type ---
    def _avg(rows: list[dict], key: str) -> float:
        return sum(r[key] for r in rows) / len(rows) if rows else 0.0

    rk = f"recall_at_{args.top_k}"
    summary = {
        "n_queries": len(per_query),
        "recall_at_5": round(_avg(per_query, "recall_at_5"), 4),
        rk: round(_avg(per_query, rk), 4),
        "mrr": round(_avg(per_query, "reciprocal_rank"), 4),
        "by_type": {},
    }
    for qtype in ("semantic", "positional", "character"):
        rows = [r for r in per_query if r["query_type"] == qtype]
        if rows:
            summary["by_type"][qtype] = {
                "n": len(rows),
                "recall_at_5": round(_avg(rows, "recall_at_5"), 4),
                rk: round(_avg(rows, rk), 4),
                "mrr": round(_avg(rows, "reciprocal_rank"), 4),
            }

    print("=" * 72)
    print(
        f"[eval] {args.book} mode={mode} n={summary['n_queries']} | "
        f"recall@5={summary['recall_at_5']:.3f} "
        f"recall@{args.top_k}={summary[rk]:.3f} MRR={summary['mrr']:.3f}"
    )
    for qtype, s in summary["by_type"].items():
        print(
            f"    {qtype:<10} n={s['n']:>2} recall@5={s['recall_at_5']:.3f} "
            f"recall@{args.top_k}={s[rk]:.3f} MRR={s['mrr']:.3f}"
        )

    date = time.strftime("%Y-%m-%d")
    out_path = _DATA_DIR / f"retrieval-eval-{args.book}-{mode}-{date}.json"
    payload = {
        "book": args.book,
        "retrieval_mode": mode,
        "top_k": args.top_k,
        "date": date,
        "golden_set": golden_path.name,
        "golden_annotated_at_commit": golden.get("annotated_at_commit"),
        "n_chunks": len(chunks),
        "summary": summary,
        "per_query": per_query,
    }
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(f"[eval] 结果已写入 {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
