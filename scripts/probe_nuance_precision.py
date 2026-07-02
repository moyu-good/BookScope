"""#41 §九 弦外之音准确率 probe —— 验 NUANCE_MARKERS 的假阳性率(cry-wolf)。

WP-redhead-substance-vs-slogan §九落实。验的**不是**串匹配准不准(deterministic 恒真),
是 `redhead_codebook.NUANCE_MARKERS`(18 条 marker→meaning)在真公文语境里**这个映射成不成立**:
命中一个 marker,点它那条弦外之意,在这句话的上下文里到底站不站得住,还是误报(cry-wolf)。

盯三类假阳性高发靶(§9.2):
  ① 中性用法(「深入研究市场规律」的"研究"是实义,不是"研究研究＝不办")
  ② 上下文取消(「原则上不批,特殊情况报核准」——口子被下文说死)
  ③ 叠词/固定搭配套话

**纯串匹配、不调 LLM、免费。** 脚本只负责采集(每条命中带前后上下文),假阳性判定是人工核
(deterministic 匹配没有"3 次取众数",改人工标注 + 一致性说明,见 018 实验笔记)。

用法: python -X utf8 scripts/probe_nuance_precision.py [每文种份数=12] [文种=意见,通知,批复]
免费(不需 API key)。产出 stdout 逐条命中清单 + 写 JSON 到 docs/internal/experiments/data/。
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import sys
from collections import defaultdict
from pathlib import Path

from bookscope.agent.redhead_codebook import NUANCE_MARKERS

CORPUS = Path("tests/file/redhead_corpus")
OUT_DIR = Path("docs/internal/experiments/data")
# 意见=方针部署最密(121份116份层级式)、通知=量最大、批复="原则同意"高发。三类 marker 最密。
DEFAULT_TYPES = ["意见", "通知", "批复"]
CONTEXT_CHARS = 40  # 命中处前后各取 ~40 字上下文,供人工判语境


def strip_meta_header(text: str) -> str:
    """剥掉 .txt 开头连续的 # 采集元信息行 + 随后空行,返回真公文正文(同 doc_spine probe)。"""
    lines = text.split("\n")
    i = 0
    while i < len(lines) and (lines[i].startswith("#") or lines[i].strip() == ""):
        i += 1
    return "\n".join(lines[i:])


def pick_samples(n_per: int, types: list[str]) -> list[dict]:
    """按文种挑样本:每文种取字数中位附近的 n_per 份(避开极端短/长,看典型表现)。"""
    rows = list(csv.DictReader(open(CORPUS / "_index.csv", encoding="utf-8")))
    by_type: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_type[r["doc_type"]].append(r)
    picked: list[dict] = []
    for t in types:
        items = by_type.get(t, [])
        if not items:
            continue
        items = sorted(items, key=lambda r: int(r.get("word_count") or 0))
        mid = len(items) // 2
        lo = max(0, mid - n_per // 2)
        picked.extend(items[lo : lo + n_per])
    return picked


def collect_marker_hits(body: str, marker: str) -> list[dict]:
    """在正文里找 marker 的**所有**出现位置(不是 detect_nuances 的去重结果),每处带前后上下文。

    detect_nuances 按含义去重、每义只留一条;假阳性判定要看**每一处**语境,所以这里抓全部位置。
    上下文取原文一段连续文字(去掉换行),让人工能判"这个 marker 在这句里是不是真释放信号"。
    """
    hits: list[dict] = []
    start = 0
    while True:
        idx = body.find(marker, start)
        if idx < 0:
            break
        lo = max(0, idx - CONTEXT_CHARS)
        hi = min(len(body), idx + len(marker) + CONTEXT_CHARS)
        ctx = body[lo:hi].replace("\n", " ").strip()
        hits.append({"pos": idx, "context": ctx})
        start = idx + len(marker)
    return hits


def run_one(row: dict) -> dict:
    """对一份公文正文跑全 marker 采集,返回每 marker 的所有命中(带上下文)。"""
    p = CORPUS / row["filename"]
    raw = p.read_text(encoding="utf-8", errors="replace")
    body = strip_meta_header(raw)
    marker_hits: list[dict] = []
    for marker, meaning in NUANCE_MARKERS:
        for h in collect_marker_hits(body, marker):
            marker_hits.append({
                "marker": marker,
                "meaning": meaning,
                "pos": h["pos"],
                "context": h["context"],
            })
    marker_hits.sort(key=lambda x: x["pos"])
    return {
        "filename": row["filename"],
        "title": row["title"][:60],
        "doc_type": row["doc_type"],
        "word_count": int(row.get("word_count") or 0),
        "body_chars": len(body),
        "hits": marker_hits,
    }


def main() -> None:
    n_per = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    types = sys.argv[2].split(",") if len(sys.argv) > 2 else DEFAULT_TYPES

    samples = pick_samples(n_per, types)
    print(f"[语料] {CORPUS}  挑 {len(samples)} 份  文种={types}  每文种{n_per}份")
    print(f"[marker] {len(NUANCE_MARKERS)} 条  上下文各 {CONTEXT_CHARS} 字  纯串匹配、不调 LLM\n")

    results: list[dict] = []
    total_hits = 0
    per_marker: dict[str, int] = defaultdict(int)
    per_type_hits: dict[str, int] = defaultdict(int)
    for row in samples:
        r = run_one(row)
        results.append(r)
        n = len(r["hits"])
        total_hits += n
        per_type_hits[r["doc_type"]] += n
        for h in r["hits"]:
            per_marker[h["marker"]] += 1
        print(f"=== [{r['doc_type']}] {r['title'][:44]}  {r['body_chars']}字  命中 {n} 处 ===")
        for i, h in enumerate(r["hits"], 1):
            print(f"  {i:>2}. 「{h['marker']}」→ {h['meaning']}")
            print(f"      …{h['context']}…")
        print()

    print("=" * 70)
    print(f"[汇总] {len(samples)} 份公文,共命中 {total_hits} 处")
    print("\n每 marker 命中数(降序):")
    for m, c in sorted(per_marker.items(), key=lambda x: -x[1]):
        print(f"  {m:<8} {c:>4}")
    print("\n每文种命中数:")
    for t, c in per_type_hits.items():
        print(f"  {t:<6} {c:>4}")
    print(f"\n下一步:人工逐条核 {total_hits} 处命中——判 meaning 在语境里成不成立(假阳性归三类靶)。")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = OUT_DIR / f"exp018-nuance-precision-hits-{ts}.json"
    out.write_text(
        json.dumps(
            {
                "probe": "exp018-nuance-precision",
                "corpus": str(CORPUS),
                "n_docs": len(samples),
                "types": types,
                "n_per_type": n_per,
                "context_chars": CONTEXT_CHARS,
                "n_markers": len(NUANCE_MARKERS),
                "total_hits": total_hits,
                "per_marker": dict(sorted(per_marker.items(), key=lambda x: -x[1])),
                "per_type_hits": dict(per_type_hits),
                "results": results,
            },
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n[存档] {out}")


if __name__ == "__main__":
    main()
