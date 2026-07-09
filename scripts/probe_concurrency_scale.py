"""exp030 · 章层加并发提速:每维 workers 6→16,墙钟砍不砍半、掉不掉章、429 多不多。

**依托**:研究笔记 013 第五节(langextract 默认 max_workers=20、DeepSeek 并发无硬上限、
429 才是过载信号)。**前提**:`exhaustive.py` 段调用已加 429 指数退避(过载重试、不丢章)。

**为什么明朝**:159 章、~13 段/维,段多才看得出并发效果;安史 30 章 ~3-4 段本来就全并行、
加并发无用(它的提速已由单飞拿到)。三国作者点名不用。

**方法**:同一本书冷建两次(缓存关),只改 `build_chapter_spine(max_workers=W)`:
- W=6(现状 `DEFAULT_WORKERS`)vs W=16。总并发 = 2 维 × W(6→12、16→32 并发)。
量:① 墙钟 ② 掉章率(退避在,应 0)③ 429 退避次数(看 16 会不会把 DeepSeek 打到频繁限流)
④ LLM 调用数 + input token(两档应基本一致,并发不改工作量、只改墙钟)。

**go/no-go**:W=16 墙钟明显降(奔着砍半)+ 掉章 0 + 429 不频繁到把提速吃回去 → 把章脉并发调高。
429 频繁 = 16 太激进,回退找 sweet spot(如 12)。纯墙钟 lever,不省 token。

公开书明朝,flash,key 从 .env,不 commit、不动生产默认(probe 传 max_workers)。
用法: python -X utf8 scripts/probe_concurrency_scale.py
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
from scripts.probe_dim_merge import _Tracker  # noqa: E402 — 复用调用/token 计数器

OUT_DIR = _ROOT / "docs" / "internal" / "experiments" / "runs"
_WORKER_LEVELS = [6, 16]


class _Count429(logging.Handler):
    """数 exhaustive 打的"被限流(429)"退避日志——反映这档并发把 provider 打限流多少次。"""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.n = 0

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001
            return
        if "限流" in msg or "429" in msg:
            self.n += 1


def _run_level(
    *, workers: int, chunks: list[dict[str, Any]], client: Any, model: str,
    true_chapters: set[int],
) -> dict[str, Any]:
    """一档并发冷建一次章脉,量墙钟 / 掉章 / 429 / 调用 / token。"""
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
            max_workers=workers,
        )
        wall = time.monotonic() - t0
    finally:
        _spine_mod.invoke_client_cached = _orig_spine
        _exhaustive_mod.invoke_client_cached = _orig_exh
        blogger.removeHandler(counter)

    have = {r["chapter"] for r in spine if isinstance(r.get("chapter"), int)}
    drop = round(len(true_chapters - have) / len(true_chapters), 3) if true_chapters else 0.0
    snap = tracker.snap()
    row = {
        "workers": workers, "concurrency": 2 * workers, "wall_seconds": round(wall, 1),
        "chapters_out": len(have), "chapters_expected": len(true_chapters), "drop_rate": drop,
        "n_calls": snap["n_calls"], "n_429_backoff": counter.n,
        "input_tokens": snap["input_tokens"], "output_tokens": snap["output_tokens"],
    }
    print(
        f"[W={workers:>2}(并发{2*workers})] {wall:>5.0f}s | 章{len(have)}/{len(true_chapters)}"
        f"(掉{drop*100:.0f}%) | 调用{snap['n_calls']} | 429退避{counter.n} | "
        f"input={snap['input_tokens']}"
    )
    return row


def main() -> int:
    kw = "明朝"
    matches = glob.glob(str(_ROOT / "tests" / "file" / f"*{kw}*"))
    if not matches:
        print(f"没找到含「{kw}」的测试书", file=sys.stderr)
        return 1
    path = matches[0]
    os.environ["BOOKSCOPE_LLM_CACHE_DISABLED"] = "1"  # 每档真跑
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
    total_chars = sum(len(c["text"]) for c in chunks)
    client = build_llm_client_from_params(provider="deepseek", api_key=key)
    model = default_model_for("deepseek")
    print(
        f"[book] {Path(path).name} / {len(chunks)} chunk / "
        f"真章 {len(true_chapters)} / {total_chars} 字符"
    )
    print(f"[model] {model} / 缓存关 / 每维 workers {_WORKER_LEVELS}(总并发 = 2×)\n")

    rows = [
        _run_level(
            workers=w, chunks=chunks, client=client, model=model,
            true_chapters=true_chapters,
        )
        for w in _WORKER_LEVELS
    ]

    print("\n" + "=" * 60)
    print("并发提速核验(墙钟方差大,单次不下倍数,只报原始 + 掉章 / 429):")
    for r in rows:
        print(
            f"  W={r['workers']:>2}: {r['wall_seconds']:>5.0f}s | 掉章{r['drop_rate']*100:.0f}% | "
            f"429退避{r['n_429_backoff']}"
        )
    if len(rows) == 2 and rows[0]["wall_seconds"]:
        ratio = rows[0]["wall_seconds"] / rows[1]["wall_seconds"] if rows[1]["wall_seconds"] else 0
        print(f"  6→16 墙钟比 ≈ {ratio:.2f}×(单次,方差大,趋势参考)")
    print("=" * 60)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = OUT_DIR / f"probe_concurrency_scale_{kw}_{ts}.json"
    out.write_text(
        json.dumps(
            {"probe": "exp030-concurrency-scale", "book": Path(path).name, "model": model,
             "n_chunks": len(chunks), "chapters_expected": len(true_chapters),
             "total_chars": total_chars, "rows": rows},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n[存档] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
