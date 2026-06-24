"""验别名合并修复的量级:三国上,章脉派生人物图 合并别名前 vs 后 的节点/边数。

spine 已缓存(免费命中);只花 KG 抽取(也有 book 级缓存)。证 _kg_name_map 把 702 噪声节点
(别名碎裂)收到真实人数量级、边的完整度保留。

用法: python -X utf8 scripts/verify_graph_canonical.py [书关键字，默认 三国]
"""

from __future__ import annotations

import glob
import os
import sys

from bookscope.agent._internal.chapter_spine_cache import get_or_build_spine
from bookscope.agent.backends.minimal_kg_extractor import MinimalKGExtractor
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
    client = build_llm_client_from_params(provider="deepseek", api_key=os.environ["DEEPSEEK_API_KEY"])
    model = default_model_for("deepseek")

    spine = get_or_build_spine(chunks=chunks, llm_client=client, model=model)  # 缓存命中

    # 合并前
    before = relationship_graph_from_spine(spine)
    # 建 KG → name_map → 合并后
    kg = MinimalKGExtractor(client=client, model=model).extract(chunk_res, kw)
    name_map: dict[str, str] = {}
    for c in kg.characters:
        canon = str(c.name).strip()
        if canon:
            name_map[canon] = canon
            for a in c.aliases or []:
                if str(a).strip():
                    name_map[str(a).strip()] = canon
    after = relationship_graph_from_spine(spine, name_map=name_map)
    topn = relationship_graph_from_spine(spine, name_map=name_map, top_n=40)

    print(f"[book] {path}")
    print(f"[KG] canonical 人物 {len(kg.characters)} 个,别名表 {len(name_map)} 条")
    print(f"[合并前]   节点 {len(before['nodes'])} · 边 {len(before['edges'])}")
    print(f"[合并后]   节点 {len(after['nodes'])} · 边 {len(after['edges'])}")
    print(f"[top_n=40] 节点 {len(topn['nodes'])} · 边 {len(topn['edges'])}  ← 关系图实际显示主干")
    tigers = {"关羽", "张飞", "赵云", "马超", "黄忠"}
    tn_names = {n["name"] for n in topn["nodes"]}
    print(f"[五虎将] top_n 后还在吗: {sorted(tigers & tn_names)}")
    print(f"[主干节点] {sorted(tn_names)}")


if __name__ == "__main__":
    main()
