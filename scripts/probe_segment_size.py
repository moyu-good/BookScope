"""exp031 · 小段 + 高并发 vs 大段:并发免费后,段该切小还是切大(墙钟 + token,不动质量)。

**依托**:exp030 发现章层瓶颈不是并发波数(32 并发 0 429、余量大),是**每调用延迟 + 截断恢复
串行尾**。`段放大`(exp020,大段少往返)当初是**并发受限**时的最优;并发免费了,**小段**(每次
调用输出少 → 更快 + 更不易截断 → 少补抽尾)可能墙钟更低、甚至 token 更省(少了截断续抽 / sweep)。

**方法**:明朝,固定 workers=16(总并发 32),只改 `char_budget`:
- 小段 char_budget=40000(≈4 章/段,基本不截断)。
- 大段基线 char_budget=120000(现状)从 exp030 的 W=16 行读(不重跑,省一半钱)。
量:墙钟 / 掉章 / 截断次数(n_length)/ 调用 / input / 429。

**go/no-go**:小段墙钟明显低于大段 296s(奔砍半)且掉章 0、token 不明显涨 → 章脉改小段(质量无损
的提速,比合并强)。小段更慢或 token 涨太多 → 大段留着,提速只到 1.35×、2× 得回去谈合并。

公开书明朝,flash,key .env,不 commit、不动生产(probe 传 char_budget / max_workers)。
用法: python -X utf8 scripts/probe_segment_size.py
"""

from __future__ import annotations

import datetime as dt
import glob
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import bookscope.agent._internal.exhaustive as _exhaustive_mod  # noqa: E402
import bookscope.agent.chapter_spine as _spine_mod  # noqa: E402
from bookscope.agent.chapter_spine import build_chapter_spine  # noqa: E402
from bookscope.api.dependencies import (  # noqa: E402
    build_llm_client_from_params,
    default_model_for,
)
from bookscope.ingest.book_chunker import chunk_book_with_stats  # noqa: E402
from bookscope.ingest.loader import load_text  # noqa: E402
from scripts.probe_concurrency_scale import _Count429  # noqa: E402 — 复用 429 计数
from scripts.probe_dim_merge import _Tracker  # noqa: E402 — 复用调用 / token / 截断计数

OUT_DIR = _ROOT / "docs" / "internal" / "experiments" / "runs"
_SMALL_CHAR_BUDGET = 40000
_WORKERS = 16


def _big_seg_baseline() -> dict[str, Any] | None:
    """从最近的 exp030 JSON 取大段(char_budget=120k)W=16 那行当基线,不重跑。"""
    hits = sorted(glob.glob(str(OUT_DIR / "probe_concurrency_scale_明朝_*.json")))
    for p in reversed(hits):
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        for r in data.get("rows", []):
            if r.get("workers") == _WORKERS:
                return {"src": Path(p).name, **r}
    return None


def main() -> int:
    kw = "明朝"
    matches = glob.glob(str(_ROOT / "tests" / "file" / f"*{kw}*"))
    if not matches:
        print(f"没找到含「{kw}」的测试书", file=sys.stderr)
        return 1
    path = matches[0]
    os.environ["BOOKSCOPE_LLM_CACHE_DISABLED"] = "1"
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        print("DEEPSEEK_API_KEY 没加载到", file=sys.stderr)
        return 1

    book = load_text(path, title=kw)
    chunk_res, _ = chunk_book_with_stats(book)
    chunks = [
        {"chunk_id": f"r0-chunk-{c.index}", "chapter": c.chapter, "text": c.text}
        for c in chunk_res
    ]
    true_chapters = {
        c["chapter"] for c in chunks if isinstance(c["chapter"], int) and c["chapter"] >= 1
    }
    client = build_llm_client_from_params(provider="deepseek", api_key=key)
    model = default_model_for("deepseek")
    print(f"[book] {Path(path).name} / {len(chunks)} chunk / 真章 {len(true_chapters)}")
    print(f"[model] {model} / 缓存关 / workers={_WORKERS} 固定,char_budget 40k(小) vs 120k(大)\n")

    big = _big_seg_baseline()
    if big:
        print(
            f"[大段基线·exp030 {big['src']}] char_budget=120k @W16: {big['wall_seconds']}s | "
            f"掉{big['drop_rate']*100:.0f}% | 调用{big['n_calls']} | input={big['input_tokens']}"
        )
    else:
        print("[大段基线] 没找到 exp030 JSON;只跑小段、稍后手动对比")

    # ── 小段一趟 ──
    tracker = _Tracker()
    counter = _Count429()
    blogger = logging.getLogger("bookscope")
    blogger.addHandler(counter)
    _orig_spine = _spine_mod.invoke_client_cached
    _orig_exh = _exhaustive_mod.invoke_client_cached
    _spine_mod.invoke_client_cached = tracker.wrapped
    _exhaustive_mod.invoke_client_cached = tracker.wrapped
    try:
        t0 = time.monotonic()
        spine = build_chapter_spine(
            chunks=chunks, llm_client=client, model=model, genre="fiction",
            char_budget=_SMALL_CHAR_BUDGET, max_workers=_WORKERS,
        )
        wall = round(time.monotonic() - t0, 1)
    finally:
        _spine_mod.invoke_client_cached = _orig_spine
        _exhaustive_mod.invoke_client_cached = _orig_exh
        blogger.removeHandler(counter)

    have = {r["chapter"] for r in spine if isinstance(r.get("chapter"), int)}
    drop = round(len(true_chapters - have) / len(true_chapters), 3) if true_chapters else 0.0
    snap = tracker.snap()
    nc, nl, it = snap["n_calls"], snap["n_length"], snap["input_tokens"]
    print(f"\n[小段 40k@W16] {wall}s | 章{len(have)}/{len(true_chapters)}(掉{drop*100:.0f}%)")
    print(f"  调用{nc} | 截断{nl} | 429退避{counter.n} | input={it}")

    print("\n" + "=" * 60)
    if big:
        wr = big["wall_seconds"] / wall if wall else 0
        tr = it / big["input_tokens"] if big["input_tokens"] else 0
        print("小段 vs 大段(明朝 @W16;单次方差大,看趋势):")
        print(f"  墙钟 大段{big['wall_seconds']}s → 小段{wall}s({1/wr:.2f}×)")
        print(f"  input 大段{big['input_tokens']} → 小段{it}({tr:.2f}×)")
        print(f"  掉章 大段{big['drop_rate']*100:.0f}% / 小段{drop*100:.0f}% | 截断{nl}")
    print("=" * 60)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = OUT_DIR / f"probe_segment_size_{kw}_{ts}.json"
    out.write_text(
        json.dumps(
            {"probe": "exp031-segment-size", "book": Path(path).name, "model": model,
             "workers": _WORKERS, "small_char_budget": _SMALL_CHAR_BUDGET,
             "big_baseline": big,
             "small": {"wall_seconds": wall, "drop_rate": drop, "n_calls": snap["n_calls"],
                       "n_length": snap["n_length"], "n_429": counter.n,
                       "input_tokens": snap["input_tokens"], "output_tokens": snap["output_tokens"],
                       "chapters_out": len(have), "chapters_expected": len(true_chapters)}},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n[存档] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
