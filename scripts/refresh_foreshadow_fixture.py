"""验 + 刷新伏笔回收的 demo fixture——改章脉派生后看 span 是不是真跨章了。

老 map-reduce 逐段盲,114 条里 58 条 span=0(埋点回收同章假伏笔)。改成 foreshadow_from_spine
(章脉全书"埋/收"一次全局配对)后,真伏笔应该有真实的跨章 span。这脚本在三国上跑新路径,
打印 span 分布 = 验证修好没,顺带刷新 fixture。

用法: python -X utf8 scripts/refresh_foreshadow_fixture.py
"""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path

from bookscope.agent._internal.chapter_spine_cache import get_or_build_spine
from bookscope.agent.chapter_spine_foreshadow import foreshadow_from_spine
from bookscope.api.dependencies import build_llm_client_from_params, default_model_for
from bookscope.ingest.book_chunker import chunk_book_with_stats
from bookscope.ingest.loader import load_text

FIXTURE = Path("web/src/demo/captured-fixtures.json")
KEY = "POST /api/agent/foreshadow-arcs"


def main() -> None:
    path = next(p for p in Path("tests/file").glob("*三国*"))
    book = load_text(str(path), title="三国演义")
    chunk_res, _ = chunk_book_with_stats(book)
    chunks = [
        {"chunk_id": f"r0-chunk-{c.index}", "chapter": c.chapter, "text": c.text}
        for c in chunk_res
    ]
    client = build_llm_client_from_params(
        provider="deepseek", api_key=os.environ["DEEPSEEK_API_KEY"]
    )
    model = default_model_for("deepseek")

    spine = get_or_build_spine(chunks=chunks, llm_client=client, model=model)
    arcs = foreshadow_from_spine(spine=spine, llm_client=client, model=model)
    if not arcs:
        print("没配出伏笔弧")
        return

    spans = []
    for a in arcs:
        p = a.get("payoff_chapter")
        spans.append("断弧" if p is None else (p - a["setup_chapter"]))
    resolved = [s for s in spans if s != "断弧"]
    c = Counter(s for s in resolved if isinstance(s, int))
    print(f"伏笔弧 {len(arcs)} 条:{len(resolved)} 已回收、{spans.count('断弧')} 断弧")
    print(f"已回收跨度分布: {dict(sorted(c.items()))}")
    if resolved:
        print(f"跨度中位 {sorted(resolved)[len(resolved)//2]}、最大 {max(resolved)}（老版中位=0、最大=8）")
    print("几个长跨度伏笔:")
    for a in sorted(arcs, key=lambda x: -((x.get("payoff_chapter") or x["setup_chapter"]) - x["setup_chapter"]))[:6]:
        p = a.get("payoff_chapter")
        print(f"  第{a['setup_chapter']}章 → {'第'+str(p)+'章' if p else '断弧'}: {a['description'][:46]}")

    fx = json.loads(FIXTURE.read_text(encoding="utf-8"))
    fx["json"][KEY] = {
        "arcs": arcs,
        "scanned": True,
        "book_session_id": "demo-sanguo",
        "trace": {"input_tokens": 0, "output_tokens": 0,
                  "chars": sum(len(c2["text"]) for c2 in chunks), "duration_ms": 0},
    }
    FIXTURE.write_text(json.dumps(fx, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nfixture 刷新:{len(arcs)} 条")


if __name__ == "__main__":
    main()
