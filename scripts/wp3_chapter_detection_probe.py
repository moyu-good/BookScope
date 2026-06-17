"""WP3 章节检测质量实测脚本（零 LLM，纯本地 ingest）。

对 repo 根的四本 test*.epub 各跑一次 loader + chunk_book_with_stats，
打印 ChapterDetectionStats 实测数据。产出落档到
``docs/internal/case-study/test-book-templates.md``。

用法::

    python scripts/wp3_chapter_detection_probe.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from bookscope.ingest.book_chunker import (
    _CHAPTER_RE,
    _MAX_HEADING_LINE_LEN,
    chinese_numeral_to_int,
    chunk_book_with_stats,
)
from bookscope.ingest.cleaner import clean
from bookscope.ingest.loader import load_text

REPO_ROOT = Path(__file__).resolve().parents[1]


def _report_breaks(raw_text: str, limit: int = 6) -> None:
    """打印真章号序列的倒跳点——解释 parse_inconsistent 是哪来的。"""
    text = clean(raw_text)
    heads: list[tuple[int | None, str]] = []
    for m in _CHAPTER_RE.finditer(text):
        if m.group("zh_chapter") is None and m.group("en_chapter") is None:
            continue
        line_end = text.find("\n", m.start())
        line_end = len(text) if line_end == -1 else line_end
        if line_end - m.start() > _MAX_HEADING_LINE_LEN:
            continue
        token = m.group("zh_chapter_num") or m.group("en_chapter_num")
        heads.append((chinese_numeral_to_int(token), text[m.start():line_end][:24]))

    breaks = [
        (i, heads[i - 1], heads[i])
        for i in range(1, len(heads))
        if heads[i][0] is None or heads[i - 1][0] is None or heads[i][0] <= heads[i - 1][0]
    ]
    print(f"  monotonic_breaks: {len(breaks)}")
    for idx, prev, cur in breaks[:limit]:
        print(f"    #{idx}: {prev[1]!r}({prev[0]}) -> {cur[1]!r}({cur[0]})")


def main() -> None:
    # Windows 控制台默认 codepage 吃不下书名里的汉字，强制 UTF-8
    sys.stdout.reconfigure(encoding="utf-8")
    epubs = sorted(REPO_ROOT.glob("test*.epub"))
    if not epubs:
        print("repo 根没找到 test*.epub")
        return

    for path in epubs:
        t0 = time.perf_counter()
        try:
            book = load_text(path)
            chunks, stats = chunk_book_with_stats(book)
        except Exception as exc:  # noqa: BLE001 — 单本失败不挡其余三本
            print(f"\n=== {path.name}\n  失败：{type(exc).__name__}: {exc}")
            continue
        elapsed = time.perf_counter() - t0

        print(f"\n=== {path.name}")
        print(f"  title           : {book.title}")
        print(f"  raw_chars       : {len(book.raw_text)}")
        print(f"  chunks          : {len(chunks)}")
        print(f"  ingest_seconds  : {elapsed:.2f}")
        payload = stats.to_dict()
        payload["avg_chapter_chars"] = round(payload["avg_chapter_chars"], 1)
        payload["parse_success_rate"] = round(payload["parse_success_rate"], 4)
        print("  stats           : " + json.dumps(payload, ensure_ascii=False))
        if "parse_inconsistent" in stats.warnings:
            _report_breaks(book.raw_text)


if __name__ == "__main__":
    main()
