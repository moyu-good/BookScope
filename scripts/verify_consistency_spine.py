"""验设定一致性章脉派生:三国上跑 consistency_scan_from_spine,证明不截断、扫到全书。

老 ``generate_consistency_scan`` 整本一次进 context,大书(三国 73 万字起)可能截断——
被截掉那半本里的矛盾看不见。新 ``consistency_scan_from_spine`` 从章脉全书摘要找跨章矛盾,
章脉覆盖全 119 章,扫描视野=整本。

打印**证明指标**:章脉覆盖章数(证明不截断、视野是整本)、产出矛盾条数、矛盾涉及的章跨度。
顺带对比老单次版扫到几条 / 涉及哪些章。

用法: $env:PYTHONIOENCODING='utf-8'; python -X utf8 scripts/verify_consistency_spine.py
"""

from __future__ import annotations

import os
from pathlib import Path

from bookscope.agent._internal.chapter_spine_cache import get_or_build_spine
from bookscope.agent.chapter_spine_consistency import consistency_scan_from_spine
from bookscope.api.dependencies import build_llm_client_from_params, default_model_for
from bookscope.ingest.book_chunker import chunk_book_with_stats
from bookscope.ingest.loader import load_text


def main() -> None:
    path = next(p for p in Path("tests/file").glob("*三国*"))
    book = load_text(str(path), title="三国演义")
    chunk_res, _ = chunk_book_with_stats(book)
    chunks = [
        {"chunk_id": f"r0-chunk-{c.index}", "chapter": c.chapter, "text": c.text}
        for c in chunk_res
    ]
    total_chars = sum(len(c["text"]) for c in chunks)
    client = build_llm_client_from_params(
        provider="deepseek", api_key=os.environ["DEEPSEEK_API_KEY"]
    )
    model = default_model_for("deepseek")

    spine = get_or_build_spine(chunks=chunks, llm_client=client, model=model)
    spine_chs = sorted(r.get("chapter") for r in spine if isinstance(r.get("chapter"), int))
    print(f"全书字数: {total_chars}")
    print(f"章脉覆盖: {len(spine_chs)} 章, 章号 {spine_chs[0]}..{spine_chs[-1]}")
    print("=> 派生版扫描视野 = 整本 119 章(章脉是全书一次精读, 不截断)\n")

    cons = consistency_scan_from_spine(spine=spine, llm_client=client, model=model)
    if cons is None:
        print("派生版: 扫描失败(返 None)")
        return
    print(f"派生版找出矛盾: {len(cons)} 条")
    chapters_touched: set[int] = set()
    for c in cons:
        a, b = c["a"]["chapter"], c["b"]["chapter"]
        chapters_touched.update((a, b))
        print(f"  [第{a}章 vs 第{b}章, 跨度{abs(b - a)}] {c['topic']}: {c['conflict'][:50]}")
    if chapters_touched:
        print(
            f"\n矛盾涉及章范围: 第{min(chapters_touched)}章..第{max(chapters_touched)}章"
            f"(证明扫到了书的不同段落, 不是只看前半本)"
        )
    else:
        print("\n自洽书 / 无跨章矛盾(空数组也是成功结果)")


if __name__ == "__main__":
    main()
