"""验别名归并修复的量级:三国上,章脉派生人物图 合并别名前 vs 后 的节点/边数。

spine 已缓存(免费命中);别名表走一次 LLM 判同人(``build_spine_name_map``,只发人名清单、
也缓存)。证归并把碎裂别名(刘备/刘玄德、孔明/诸葛亮)收成一个节点、五虎将仍各自在、边的
完整度保留。

用法: python -X utf8 scripts/verify_graph_canonical.py [书关键字,默认 三国]
"""

from __future__ import annotations

import glob
import os
import sys

from bookscope.agent._internal.chapter_spine_cache import get_or_build_spine
from bookscope.agent.chapter_spine_canon import build_spine_name_map, collect_spine_names
from bookscope.agent.chapter_spine_views import relationship_graph_from_spine
from bookscope.api.dependencies import build_llm_client_from_params, default_model_for
from bookscope.ingest.book_chunker import chunk_book_with_stats
from bookscope.ingest.loader import load_text


def main() -> None:
    kw = sys.argv[1] if len(sys.argv) > 1 else "三国"
    path = glob.glob(f"tests/file/*{kw}*")[0]
    book = load_text(path, title=kw)
    chunk_res, _ = chunk_book_with_stats(book)
    chunks = [
        {"chunk_id": f"r0-chunk-{c.index}", "chapter": c.chapter, "text": c.text}
        for c in chunk_res
    ]
    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("DEEPSEEK_API_KEY 没加载到")
        return
    client = build_llm_client_from_params(
        provider="deepseek", api_key=os.environ["DEEPSEEK_API_KEY"]
    )
    model = default_model_for("deepseek")

    spine = get_or_build_spine(chunks=chunks, llm_client=client, model=model)  # 缓存命中

    # 合并前
    before = relationship_graph_from_spine(spine)
    # 章脉人名 → 一次 LLM 判同人 → 别名表 → 合并后
    raw_names = collect_spine_names(spine)
    name_map = build_spine_name_map(spine=spine, llm_client=client, model=model)
    merged_aliases = sum(1 for a, c in name_map.items() if a != c)
    after = relationship_graph_from_spine(spine, name_map=name_map)
    topn = relationship_graph_from_spine(spine, name_map=name_map, top_n=40)

    print(f"[book] {path}")
    print(
        f"[章脉人名] 去重 {len(raw_names)} 个;别名表 {len(name_map)} 条,"
        f"其中真合并 {merged_aliases} 条"
    )
    print(f"[合并前]   节点 {len(before['nodes'])} · 边 {len(before['edges'])}")
    print(f"[合并后]   节点 {len(after['nodes'])} · 边 {len(after['edges'])}")
    print(f"[top_n=40] 节点 {len(topn['nodes'])} · 边 {len(topn['edges'])}  ← 关系图实际显示主干")

    tn_names = {n["name"] for n in topn["nodes"]}
    # 三国别名碎裂的两个标志性例子:合并后两边应只剩 canonical 一个
    for canon_name, variants in (("刘备", {"刘玄德", "玄德", "先主"}),
                                 ("诸葛亮", {"孔明", "卧龙"})):
        leaked = sorted(variants & tn_names)
        flag = "✗ 还在碎裂" if leaked else "✓ 已合并"
        print(
            f"[{canon_name}] {flag};主干残留别名: {leaked or '无'};"
            f"canonical 在主干: {canon_name in tn_names}"
        )

    tigers = {"关羽", "张飞", "赵云", "马超", "黄忠"}
    print(f"[五虎将] top_n 后还在吗: {sorted(tigers & tn_names)}(应各自独立,没被错并)")
    print(f"[主干节点] {sorted(tn_names)}")


if __name__ == "__main__":
    main()
