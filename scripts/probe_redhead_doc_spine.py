"""task#1 probe:doc_spine 抽取算法在各文种真公文上的覆盖抽验(第二步)。

对 850 份语料按文种挑样本(默认每文种 3 份,可控),真跑 `build_doc_spine`(flash),
记每份:头要素抽到几项/文种抽的啥、条款维抽几条/几条 verified/截断没、看结构维效力层级。
纯 stdout 报告 + 写 JSON 持久化。**剥掉 .txt 开头的 # 采集元信息头**(发文字号/成文日期
都在头里,不剥就是测抄注释而非从正文抽;产品链路用户上传的公文没这个头)。

用法: python -X utf8 scripts/probe_redhead_doc_spine.py [每文种份数,默认3] [文种逗号列表,默认主要文种]
需 DEEPSEEK_API_KEY(import bookscope 从 .env 自动加载)。会真花 DeepSeek。
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from bookscope.agent.doc_spine import build_doc_spine
from bookscope.api.dependencies import build_llm_client_from_params, default_model_for
from bookscope.ingest.book_chunker import chunk_book_with_stats
from bookscope.ingest.loader import load_text

CORPUS = Path("tests/file/redhead_corpus")
OUT_DIR = Path("docs/internal/experiments/data")
# 主要文种(样本足够的):其他/请示/通告/报告样本太少或非公文,默认不抽,单独看
DEFAULT_TYPES = ["通知", "令", "意见", "决定", "批复", "公告", "函"]


def strip_meta_header(text: str) -> str:
    """剥掉 .txt 开头连续的 # 采集元信息行 + 随后的空行,返回真公文正文。"""
    lines = text.split("\n")
    i = 0
    while i < len(lines) and (lines[i].startswith("#") or lines[i].strip() == ""):
        i += 1
    return "\n".join(lines[i:])


def pick_samples(n_per: int, types: list[str]) -> dict[str, list[dict]]:
    """按文种挑样本:每文种取字数中位附近的 n_per 份(避开极端短/长,看典型表现)。"""
    rows = list(csv.DictReader(open(CORPUS / "_index.csv", encoding="utf-8")))
    by_type: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_type[r["doc_type"]].append(r)
    out: dict[str, list[dict]] = {}
    for t in types:
        items = by_type.get(t, [])
        if not items:
            continue
        # 按字数排序取中间段,避开最短/最长的极端
        items = sorted(items, key=lambda r: int(r.get("word_count") or 0))
        mid = len(items) // 2
        lo = max(0, mid - n_per // 2)
        out[t] = items[lo : lo + n_per]
    return out


def run_one(row: dict, client: Any, model: str) -> dict:
    """跑一份公文的 doc_spine,返回抽验指标。"""
    p = CORPUS / row["filename"]
    raw = p.read_text(encoding="utf-8", errors="replace")
    body = strip_meta_header(raw)
    # 走 load_text→chunker 同产品口径,但喂剥头后的正文
    book = load_text_from_str(body, title=row["title"][:40])
    chunk_res, stats = chunk_book_with_stats(book)
    chunks = [
        {"chunk_id": f"r0-chunk-{c.index}", "chapter": c.chapter, "text": c.text}
        for c in chunk_res
    ]
    t0 = time.monotonic()
    spine = build_doc_spine(
        chunks=chunks,
        llm_client=client,
        model=model,
        full_text=body,
        cache_enabled=False,  # 看真实抽取,不吃缓存
    )
    elapsed = time.monotonic() - t0

    head = spine.get("head") or []
    clauses = spine.get("clauses") or []
    sr = spine.get("structure_read")

    # 头要素:抽到值的项(present) / 确证无(absent_confirmed) / 待核(unverified)
    head_present = [h for h in head if str(h.get("value", "")).strip()]
    head_verified = [h for h in head_present if h.get("verified")]
    doc_type_el = next((h for h in head if h.get("field") == "文种"), {})
    issuer_el = next((h for h in head if h.get("field") == "发文机关"), {})

    # 条款维
    n_clauses = len(clauses)
    n_clause_verified = sum(1 for c in clauses if c.get("verified"))
    instr_dist: dict[str, int] = defaultdict(int)
    for c in clauses:
        instr_dist[c.get("instruction_type", "?")] += 1

    return {
        "title": row["title"][:50],
        "csv_doc_type": row["doc_type"],
        "csv_word_count": int(row.get("word_count") or 0),
        "body_chars": len(body),
        "n_chunks": len(chunks),
        "chapters_detected": stats.chapters_detected,
        "elapsed_s": round(elapsed, 1),
        "head": {
            "present": len(head_present),
            "verified": len(head_verified),
            "doc_type_抽": doc_type_el.get("value", ""),
            "doc_type_verified": doc_type_el.get("verified", False),
            "issuer_抽": issuer_el.get("value", ""),
        },
        "clauses": {
            "n": n_clauses,
            "verified": n_clause_verified,
            "instr_dist": dict(instr_dist),
        },
        "structure_read": {
            "level": (sr or {}).get("authority", {}).get("level") if sr else None,
            "agency_level": (sr or {}).get("authority", {}).get("agency_level") if sr else None,
            "n_signals": len((sr or {}).get("signals", [])) if sr else 0,
        } if sr else None,
    }


def load_text_from_str(body: str, title: str):
    """把剥头后的正文字符串包成 load_text 认的 Book(写临时文件走 load_text 同口径)。"""
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write(body)
        tmp = f.name
    try:
        return load_text(tmp, title=title)
    finally:
        os.unlink(tmp)


def main() -> None:
    n_per = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    types = sys.argv[2].split(",") if len(sys.argv) > 2 else DEFAULT_TYPES

    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        print("DEEPSEEK_API_KEY 没加载到")
        return
    client = build_llm_client_from_params(provider="deepseek", api_key=key)
    model = default_model_for("deepseek")
    print(f"[model] {model}  每文种 {n_per} 份  文种={types}\n")

    samples = pick_samples(n_per, types)
    results: dict[str, list[dict]] = {}
    n_calls = 0
    for t, rows in samples.items():
        print(f"=== 文种「{t}」({len(rows)} 份) ===")
        results[t] = []
        for row in rows:
            try:
                r = run_one(row, client, model)
            except Exception as exc:  # noqa: BLE001
                print(f"  [跑挂] {row['title'][:40]}: {type(exc).__name__}: {exc}")
                results[t].append({"title": row["title"][:50], "error": f"{type(exc).__name__}: {exc}"})
                continue
            n_calls += 1
            h = r["head"]
            c = r["clauses"]
            sr = r["structure_read"]
            print(
                f"  {r['title'][:38]:<38} {r['body_chars']:>6}字 "
                f"头[{h['present']}值/{h['verified']}核 文种={h['doc_type_抽'] or '空'}] "
                f"条款[{c['n']}条/{c['verified']}核] "
                f"层级={sr['level'] if sr else '无'} {r['elapsed_s']}s"
            )
            results[t].append(r)
        print()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = OUT_DIR / f"redhead_doc_spine_coverage_{ts}.json"
    out.write_text(
        json.dumps(
            {"model": model, "n_per_type": n_per, "types": types, "n_calls": n_calls, "results": results},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[存档] {out}  (共 {n_calls} 份跑成功)")


if __name__ == "__main__":
    main()
