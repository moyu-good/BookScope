"""把 demo 的关系图 fixture 刷成当前章脉派生(top_n=40)的干净图——化石那张 28 节点别再误导。

spine + KG 已缓存(免 LLM)。每条边用 evidence_for_pair 纯检索填真原文(demo 点开也看得到证据)。
只动 character-graph 这一个 fixture,别的不碰。跑完重截图给 README。

用法: python -X utf8 scripts/refresh_graph_fixture.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from bookscope.agent._internal.chapter_spine_cache import get_or_build_spine
from bookscope.agent.backends.minimal_kg_extractor import MinimalKGExtractor
from bookscope.agent.chapter_spine_evidence import evidence_for_pair
from bookscope.agent.chapter_spine_views import relationship_graph_from_spine
from bookscope.api.dependencies import build_llm_client_from_params, default_model_for
from bookscope.ingest.book_chunker import chunk_book_with_stats
from bookscope.ingest.loader import load_text

FIXTURE = Path("web/src/demo/captured-fixtures.json")
KEY = "POST /api/agent/character-graph"


def main() -> None:
    path = next(p for p in Path("tests/file").glob("*三国*"))
    book = load_text(str(path), title="三国演义")
    chunk_res, _ = chunk_book_with_stats(book)
    chunks = [
        {"chunk_id": f"r0-chunk-{c.index}", "chapter": c.chapter, "text": c.text}
        for c in chunk_res
    ]
    ch_text: dict[int, str] = {}
    for c in chunk_res:
        ch_text[c.chapter] = ch_text.get(c.chapter, "") + c.text

    client = build_llm_client_from_params(
        provider="deepseek", api_key=os.environ["DEEPSEEK_API_KEY"]
    )
    model = default_model_for("deepseek")
    spine = get_or_build_spine(chunks=chunks, llm_client=client, model=model)  # 缓存命中
    kg = MinimalKGExtractor(client=client, model=model).extract(chunk_res, "三国演义")
    name_map: dict[str, str] = {}
    for c in kg.characters:
        canon = str(c.name).strip()
        if canon:
            name_map[canon] = canon
            for a in c.aliases or []:
                if str(a).strip():
                    name_map[str(a).strip()] = canon

    g = relationship_graph_from_spine(spine, name_map=name_map, top_n=40)

    edges = []
    for e in g["edges"]:
        ch = e["chapters"][0] if e["chapters"] else 0
        ev = evidence_for_pair(ch_text.get(ch, ""), e["source"], e["target"])  # 纯检索取真原文
        edges.append({
            "source": e["source"],
            "target": e["target"],
            "relation": "、".join(e.get("notes", [])[:2]) or "同场",
            "strength": max(1, min(5, int(e.get("weight", 1)))),
            "evidence": ev,
            "verified": bool(ev),
            "chapter": ch,
            "match_score": 1.0 if ev else 0.0,
        })

    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    fixture["json"][KEY] = {
        "nodes": [n["name"] for n in g["nodes"]],
        "edges": edges,
        "book_session_id": "demo-sanguo",
        "trace": {
            "duration_ms": 0, "input_tokens": 0, "output_tokens": 0,
            "chars": sum(len(c["text"]) for c in chunks),
            "total_edges": len(edges),
            "verified_edges": sum(1 for e in edges if e["verified"]),
        },
    }
    FIXTURE.write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"刷新 {KEY}: 节点 {len(g['nodes'])} · 边 {len(edges)} · "
          f"带证据 {sum(1 for e in edges if e['evidence'])} 条")


if __name__ == "__main__":
    main()
