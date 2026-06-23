"""章脉(ADR-010)live 冒烟:在一本书的前几段真建一次章脉,看 parse+纠偏+跨维 union 跑没跑通。

只取前 N 段(省钱),打印每章抽到的维度 + 字段覆盖,确认真 LLM 输出能解析、能合并。
迁移计划第 6 步的全本回归是另一回事,这里只做集成冒烟。

用法: python -X utf8 scripts/smoke_chapter_spine.py [书关键字，默认 三国] [取前几段，默认 2]
需 DEEPSEEK_API_KEY(.env 自动加载)。会真花一点 DeepSeek(段数 × 2 维)。
"""

from __future__ import annotations

import glob
import os
import sys
import time

from bookscope.agent._internal.exhaustive import segment_chunks
from bookscope.agent.chapter_spine import build_chapter_spine
from bookscope.api.dependencies import build_llm_client_from_params, default_model_for
from bookscope.ingest.book_chunker import chunk_book_with_stats
from bookscope.ingest.loader import load_text


def main() -> None:
    kw = sys.argv[1] if len(sys.argv) > 1 else "三国"
    n_seg = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    matches = glob.glob(f"tests/file/*{kw}*")
    if not matches:
        print(f"没找到含「{kw}」的测试书")
        return
    path = matches[0]
    book = load_text(path, title=kw)
    chunk_res, stats = chunk_book_with_stats(book)
    chunks = [
        {"chunk_id": f"r0-chunk-{c.index}", "chapter": c.chapter, "text": c.text}
        for c in chunk_res
    ]
    # 只取前 N 段的 chunk(省钱冒烟)
    segs = segment_chunks(chunks)
    slice_chunks = [c for seg in segs[:n_seg] for c in seg]
    print(f"[book] {path} · {len(chunks)} chunk / {stats.chapters_detected} 章, "
          f"冒烟取前 {n_seg} 段 = {len(slice_chunks)} chunk")

    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        print("DEEPSEEK_API_KEY 没加载到")
        return
    client = build_llm_client_from_params(provider="deepseek", api_key=key)
    model = default_model_for("deepseek")

    t0 = time.monotonic()
    spine = build_chapter_spine(chunks=slice_chunks, llm_client=client, model=model)
    dt_s = time.monotonic() - t0
    print(f"[章脉] {len(spine)} 章, 用时 {dt_s:.0f}s\n")

    for rec in spine[:8]:
        dims = []
        if rec.get("present"):
            dims.append(f"在场{len(rec['present'])}")
        if rec.get("relations"):
            dims.append(f"关系{len(rec['relations'])}")
        if rec.get("events"):
            dims.append(f"事件{len(rec['events'])}")
        if "tension" in rec:
            dims.append(f"张力{rec['tension']}")
        if rec.get("foreshadow"):
            dims.append(f"伏笔{len(rec['foreshadow'])}")
        ev = (rec.get("evidence") or "")[:30]
        print(f"  章{rec['chapter']:>3} [{'✓' if rec.get('verified') else '×'}] "
              f"{' '.join(dims)} | {ev}")

    # 字段覆盖自检:有多少章同时拿到人物维(present)和情节维(tension)
    both = sum(1 for r in spine if r.get("present") is not None and "tension" in r)
    print(f"\n[自检] {both}/{len(spine)} 章同时有人物维+情节维(跨维 union 成功)")


if __name__ == "__main__":
    main()
