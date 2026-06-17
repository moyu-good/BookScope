"""exp-007：contextual chunk header 对 BM25 检索质量的影响（自含实验脚本）。

设计契约见 docs/internal/experiments/007-contextual-chunk-header.md。单变量纪律：
chunker、golden set、BM25 实现、检索打分逻辑全部与基线
（scripts/eval_retrieval.py + SessionVectorStore.search_bm25）逐字对齐，
唯一变量是实验组 chunk 文本前是否拼一行 LLM 生成的 header
（"《书名》第 N 章：本段讲了什么"）。

不改任何产品代码，不碰 SessionVectorStore——BM25 索引在脚本内自建
（同款 jieba.cut + BM25Okapi + argsort 降序 + score>0 过滤）。

用法::

    DEEPSEEK_API_KEY=... python scripts/exp007_contextual_header.py --book anshi
    # 或者 key 不进命令行 / 环境（避免泄漏进 shell 历史与权限白名单）：
    python scripts/exp007_contextual_header.py --book anshi --key-file <含key的文件>

产出:
- docs/internal/experiments/data/exp007-headers-{book}.json   header 全量（可断点续跑）
- docs/internal/experiments/data/exp007-eval-{book}.json      对照组 / 实验组指标
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_DATA_DIR = _PROJECT_ROOT / "docs" / "experiments" / "data"

# 与 scripts/eval_retrieval.py 的 _BOOKS 一致
_BOOKS = {
    "anshi": "test安史之乱  历史、宣传与神话 (张诗坪, 胡可奇).epub",
    "kuicheng": "test亏成首富从游戏开始 (青衫取醉) (z-library.sk, 1lib.sk, z-lib.sk).epub",
}

_MODEL = "deepseek-chat"
_CONCURRENCY = 10
_PREV_TAIL_CHARS = 200

_SYSTEM_PROMPT = (
    "你是图书索引助手。给定一本书的一个文本块，你为它写一行中文索引头，"
    "格式：《书名》第N章：这段讲了什么。一句话概括本块的情节或论点，"
    "整行不超过60字。只输出这一行，不要解释，不要加引号或代码块。"
)

_USER_PROMPT_TEMPLATE = (
    "书名：{title}\n"
    "章号：{chapter_label}\n"
    "前一块结尾（仅供衔接参考）：\n{prev_tail}\n\n"
    "本块全文：\n{chunk_text}\n\n"
    "请输出索引头一行，格式「《{title}》{chapter_label}：本段讲了什么」，"
    "整行不超过60字。"
)


# ---------------------------------------------------------------------------
# Header 生成
# ---------------------------------------------------------------------------


def _chapter_label(chapter: int | None) -> str:
    if chapter is None:
        return "章节不详"
    if chapter == 0:
        return "序章"
    return f"第{chapter}章"


def _sanitize_header(raw: str) -> str:
    """取第一行非空文本，剥掉模型爱加的引号 / 代码块记号。"""
    for line in raw.strip().splitlines():
        line = line.strip().strip("`").strip('"').strip("「」").strip()
        if line:
            return line
    return ""


def _generate_one_header(
    client,  # openai.OpenAI，线程安全，全局共享
    *,
    title: str,
    chapter_label: str,
    prev_tail: str,
    chunk_text: str,
) -> str:
    """调 deepseek-chat 生成一条 header；失败重试 1 次，仍失败抛异常。"""
    user_prompt = _USER_PROMPT_TEMPLATE.format(
        title=title,
        chapter_label=chapter_label,
        prev_tail=prev_tail if prev_tail else "（本块是全书第一块，无前文）",
        chunk_text=chunk_text,
    )
    last_exc: Exception | None = None
    for _attempt in range(2):
        try:
            resp = client.chat.completions.create(
                model=_MODEL,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=200,
                temperature=0.0,
            )
            header = _sanitize_header(resp.choices[0].message.content or "")
            if header:
                return header
            last_exc = ValueError("模型返回空 header")
        except Exception as exc:  # noqa: BLE001 — 网络 / API 异常统一重试
            last_exc = exc
            time.sleep(1.0)
    raise RuntimeError(f"header 生成两次均失败: {last_exc}")


def _load_or_generate_headers(
    book_key: str, title: str, chunks: list,
) -> tuple[list[str], int]:
    """全量 header（按 chunk index 对位）。已有同 n_chunks 的产出文件则直接复用。

    返回 (headers, n_failed)。失败的 chunk 用降级 header "《书名》第N章"。
    """
    out_path = _DATA_DIR / f"exp007-headers-{book_key}.json"
    partial: dict[int, str] = {}
    partial_failed: set[int] = set()
    if out_path.is_file():
        cached = json.loads(out_path.read_text(encoding="utf-8"))
        if cached.get("n_chunks") != len(chunks):
            print(
                f"[exp007] 已有 header 文件 n_chunks={cached.get('n_chunks')} "
                f"与当前 {len(chunks)} 不一致，重新生成"
            )
        elif cached.get("complete", True):
            print(f"[exp007] 复用已有 header 文件 {out_path.name}")
            headers = [h["header"] for h in cached["headers"]]
            return headers, cached.get("n_failed", 0)
        else:
            partial = {
                h["index"]: h["header"]
                for h in cached["headers"]
                if h.get("header")
            }
            partial_failed = set(cached.get("failed_indices", []))
            print(
                f"[exp007] 接着上次 checkpoint 跑："
                f"已有 {len(partial)}/{len(chunks)} 条 header"
            )

    import openai

    client = openai.OpenAI(
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url="https://api.deepseek.com",
        timeout=60.0,
        max_retries=0,  # 重试逻辑自己控
    )

    headers: list[str | None] = [None] * len(chunks)
    failed: set[int] = set(partial_failed)
    for i, h in partial.items():
        headers[i] = h
    todo = [i for i in range(len(chunks)) if headers[i] is None]
    done_count = 0
    lock = threading.Lock()
    t0 = time.monotonic()

    def _write_file(*, complete: bool) -> None:
        payload = {
            "experiment": "exp007-contextual-chunk-header",
            "book": book_key,
            "title": title,
            "date": time.strftime("%Y-%m-%d"),
            "model": _MODEL,
            "concurrency": _CONCURRENCY,
            "system_prompt": _SYSTEM_PROMPT,
            "user_prompt_template": _USER_PROMPT_TEMPLATE,
            "n_chunks": len(chunks),
            "complete": complete,
            "n_failed": len(failed),
            "failed_indices": sorted(failed),
            "headers": [
                {"index": i, "chapter": chunks[i].chapter, "header": headers[i]}
                for i in range(len(chunks))
                if headers[i] is not None
            ],
        }
        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _task(i: int) -> None:
        nonlocal done_count
        label = _chapter_label(chunks[i].chapter)
        prev_tail = chunks[i - 1].text[-_PREV_TAIL_CHARS:] if i > 0 else ""
        try:
            header = _generate_one_header(
                client,
                title=title,
                chapter_label=label,
                prev_tail=prev_tail,
                chunk_text=chunks[i].text,
            )
        except Exception as exc:  # noqa: BLE001 — 降级不挡全场
            header = f"《{title}》{label}"
            with lock:
                failed.add(i)
            print(f"[exp007] chunk {i} 降级 header（{type(exc).__name__}）")
        with lock:
            headers[i] = header
            done_count += 1
            if done_count % 100 == 0 or done_count == len(todo):
                elapsed = time.monotonic() - t0
                print(
                    f"[exp007] header {done_count}/{len(todo)} "
                    f"({elapsed:.0f}s, 失败 {len(failed)})",
                    flush=True,
                )
            if done_count % 500 == 0:
                _write_file(complete=False)  # checkpoint：超时重跑可续

    print(
        f"[exp007] 生成 header：{len(todo)}/{len(chunks)} chunks · "
        f"{_MODEL} · 并发 {_CONCURRENCY}"
    )
    with ThreadPoolExecutor(max_workers=_CONCURRENCY) as ex:
        futures = [ex.submit(_task, i) for i in todo]
        for f in as_completed(futures):
            f.result()  # 任务内部已兜底，这里只为冒出真正的编程错误

    _write_file(complete=True)
    print(f"[exp007] headers 已写入 {out_path}（失败 {len(failed)}）")
    return [h or "" for h in headers], len(failed)


# ---------------------------------------------------------------------------
# BM25 检索 + 指标（逐字对齐 SessionVectorStore.search_bm25 / eval_retrieval.py）
# ---------------------------------------------------------------------------


def _build_bm25(texts: list[str]):
    import jieba
    from rank_bm25 import BM25Okapi

    tokenized = [list(jieba.cut(t)) for t in texts]
    return BM25Okapi(tokenized)


def _search_bm25(bm25, query: str, top_k: int) -> list[int]:
    """与 SessionVectorStore.search_bm25 同款：argsort 降序 + score>0 过滤。"""
    import jieba
    import numpy as np

    tokens = list(jieba.cut(query))
    scores = bm25.get_scores(tokens)
    top_indices = np.argsort(scores)[::-1][:top_k]
    return [int(idx) for idx in top_indices if scores[idx] > 0]


def _evaluate_query(
    retrieved_indices: list[int], expected: list[int], top_k: int,
) -> dict:
    """单条 query 的 recall@5 / recall@k / MRR 分量（同 eval_retrieval.py）。"""
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


def _run_eval(bm25, golden: dict, top_k: int, group_name: str) -> dict:
    per_query: list[dict] = []
    for q in golden["queries"]:
        retrieved = _search_bm25(bm25, q["query"], top_k)
        scores = _evaluate_query(retrieved, q["expected_chunk_indices"], top_k)
        per_query.append({
            "query": q["query"],
            "query_type": q["query_type"],
            "expected_chunk_indices": q["expected_chunk_indices"],
            "retrieved_indices": retrieved,
            **scores,
        })

    def _avg(rows: list[dict], key: str) -> float:
        return sum(r[key] for r in rows) / len(rows) if rows else 0.0

    rk = f"recall_at_{top_k}"
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

    print(
        f"[exp007] {group_name}: recall@5={summary['recall_at_5']:.3f} "
        f"recall@{top_k}={summary[rk]:.3f} MRR={summary['mrr']:.3f}"
    )
    for qtype, s in summary["by_type"].items():
        print(
            f"    {qtype:<10} n={s['n']:>2} recall@5={s['recall_at_5']:.3f} "
            f"recall@{top_k}={s[rk]:.3f} MRR={s['mrr']:.3f}"
        )
    return {"summary": summary, "per_query": per_query}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="exp-007：contextual chunk header BM25 检索 A/B",
    )
    parser.add_argument("--book", required=True, choices=sorted(_BOOKS))
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument(
        "--key-file", default=None,
        help="含 DeepSeek key 的本地文件（从中提取 sk- 开头的 key；"
             "替代环境变量，key 不进命令行）",
    )
    args = parser.parse_args()

    if args.key_file:
        import re

        key_text = Path(args.key_file).read_text(encoding="utf-8")
        m = re.search(r"sk-[A-Za-z0-9]+", key_text)
        if not m:
            print(f"--key-file 里没找到 sk- 开头的 key：{args.key_file}",
                  file=sys.stderr)
            return 1
        os.environ["DEEPSEEK_API_KEY"] = m.group(0)
    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("DEEPSEEK_API_KEY 未设置（或用 --key-file）", file=sys.stderr)
        return 1

    golden_path = _DATA_DIR / f"golden-retrieval-{args.book}.json"
    if not golden_path.is_file():
        print(f"golden set 不存在：{golden_path}", file=sys.stderr)
        return 1
    golden = json.loads(golden_path.read_text(encoding="utf-8"))

    epub_path = _PROJECT_ROOT / _BOOKS[args.book]
    if not epub_path.is_file():
        print(f"epub 不存在：{epub_path}", file=sys.stderr)
        return 1

    from bookscope.ingest.book_chunker import chunk_book_with_stats
    from bookscope.ingest.loader import load_text

    print(f"[exp007] book={args.book} top_k={args.top_k}")
    t0 = time.monotonic()
    book = load_text(epub_path)
    book.language = "zh"  # 与 API ingest 行为一致（books.py:446）
    chunks, _stats = chunk_book_with_stats(book)
    print(
        f"[exp007] ingest+chunk {time.monotonic() - t0:.1f}s · "
        f"{len(chunks)} chunks"
    )

    if len(chunks) != golden["n_chunks"]:
        print(
            f"[exp007] 拒跑：当前 chunker 产出 {len(chunks)} chunks，"
            f"golden set 标注时是 {golden['n_chunks']}。"
            "chunk index 已漂移，先重标 golden set。",
            file=sys.stderr,
        )
        return 2

    title = golden["title"]
    headers, n_failed = _load_or_generate_headers(args.book, title, chunks)

    print("=" * 72)
    t0 = time.monotonic()
    bm25_control = _build_bm25([c.text for c in chunks])
    bm25_treatment = _build_bm25(
        [f"{headers[i]}\n{chunks[i].text}" for i in range(len(chunks))]
    )
    print(f"[exp007] 两组 BM25 索引建完 {time.monotonic() - t0:.1f}s")

    control = _run_eval(bm25_control, golden, args.top_k, "对照组(原文)")
    print("-" * 72)
    treatment = _run_eval(
        bm25_treatment, golden, args.top_k, "实验组(header+原文)",
    )

    rk = f"recall_at_{args.top_k}"
    delta = {
        key: round(treatment["summary"][key] - control["summary"][key], 4)
        for key in ("recall_at_5", rk, "mrr")
    }
    print("=" * 72)
    print(
        f"[exp007] Δ(实验组-对照组): recall@5={delta['recall_at_5']:+.3f} "
        f"recall@{args.top_k}={delta[rk]:+.3f} MRR={delta['mrr']:+.3f}"
    )

    out_path = _DATA_DIR / f"exp007-eval-{args.book}.json"
    payload = {
        "experiment": "exp007-contextual-chunk-header",
        "book": args.book,
        "date": time.strftime("%Y-%m-%d"),
        "top_k": args.top_k,
        "golden_set": golden_path.name,
        "golden_annotated_at_commit": golden.get("annotated_at_commit"),
        "n_chunks": len(chunks),
        "header_model": _MODEL,
        "header_file": f"exp007-headers-{args.book}.json",
        "n_header_failed": n_failed,
        "delta": delta,
        "control": control,
        "treatment": treatment,
    }
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(f"[exp007] 结果已写入 {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
