"""验隐患:章脉派生的人物关系图 vs 老的专门抽边(extract_character_graph_exhaustive),数边数。

作者疑「关系图怎么还是这么少 / 这次改动留隐患」。章脉的 relations 是人物维一趟顺带抽的,
老路径是专门盯着抽边(memory 记三国 217 边、五虎将出齐)。专门 vs 顺带完整度可能差一截。
这脚本拿同一本书真后端各跑一遍,直接比 节点数/边数/关键人物边,拿数据说话。

用法: python -X utf8 scripts/compare_graph_spine_vs_old.py [书关键字，默认 三国]
需 DEEPSEEK_API_KEY(.env)。会真花 DeepSeek(章脉 ~2 维×段 + 老图 ~段)。
"""

from __future__ import annotations

import glob
import os
import sys
import time

from bookscope.agent._internal.chapter_spine_cache import get_or_build_spine
from bookscope.agent.chapter_spine_views import relationship_graph_from_spine
from bookscope.agent.character_graph import extract_character_graph_exhaustive
from bookscope.api.dependencies import build_llm_client_from_params, default_model_for
from bookscope.ingest.book_chunker import chunk_book_with_stats
from bookscope.ingest.loader import load_text

_FIVE_TIGERS = {"关羽", "张飞", "赵云", "马超", "黄忠"}


def _edge_names(edges, src_key, tgt_key):  # noqa: ANN001, ANN202
    return {frozenset((str(e[src_key]), str(e[tgt_key]))) for e in edges}


def main() -> None:
    kw = sys.argv[1] if len(sys.argv) > 1 else "三国"
    path = glob.glob(f"tests/file/*{kw}*")[0]
    book = load_text(path, title=kw)
    chunk_res, stats = chunk_book_with_stats(book)
    chunks = [
        {"chunk_id": f"r0-chunk-{c.index}", "chapter": c.chapter, "text": c.text}
        for c in chunk_res
    ]
    print(f"[book] {path} · {len(chunks)} chunk / {stats.chapters_detected} 章")

    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        print("DEEPSEEK_API_KEY 没加载到")
        return
    client = build_llm_client_from_params(provider="deepseek", api_key=key)
    model = default_model_for("deepseek")

    # ── 章脉派生 ──────────────────────────────────────────────
    t0 = time.monotonic()
    spine = get_or_build_spine(chunks=chunks, llm_client=client, model=model)
    g = relationship_graph_from_spine(spine)
    dt_spine = time.monotonic() - t0
    sp_nodes = {n["name"] for n in g["nodes"]}
    sp_edges = _edge_names(g["edges"], "source", "target")
    print(f"\n[章脉派生] {dt_spine:.0f}s · 节点 {len(sp_nodes)} · 边 {len(sp_edges)}")
    print(f"  五虎将在节点里: {sorted(_FIVE_TIGERS & sp_nodes)}")

    # ── 老的专门抽边 ──────────────────────────────────────────
    t1 = time.monotonic()
    old = extract_character_graph_exhaustive(
        chunks=chunks, llm_client=client, model=model,
        known_characters=[], unit="person", cache_enabled=True,
    )
    dt_old = time.monotonic() - t1
    if old is None:
        print("\n[老专门抽边] 失败返 None")
        return
    old_nodes = set(old.nodes)
    old_edges = _edge_names(old.edges, "source", "target")
    print(f"\n[老专门抽边] {dt_old:.0f}s · 节点 {len(old_nodes)} · 边 {len(old_edges)}")
    print(f"  五虎将在节点里: {sorted(_FIVE_TIGERS & old_nodes)}")

    # ── 对照 ──────────────────────────────────────────────────
    print("\n=== 对照 ===")
    print(f"节点: 章脉 {len(sp_nodes)} vs 老 {len(old_nodes)}")
    print(f"边:   章脉 {len(sp_edges)} vs 老 {len(old_edges)}")
    only_old = old_edges - sp_edges
    print(f"老有、章脉漏的边: {len(only_old)} 条(示例)")
    for e in list(only_old)[:8]:
        print(f"    {' — '.join(sorted(e))}")


if __name__ == "__main__":
    main()
