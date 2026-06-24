"""一次性刷新 5 个新章脉派生功能的 demo fixture(timeline/subplot/consistency/concept/relationship)。

三国上建一次 spine,跑 5 个 *_from_spine,写各自 fixture key,打印条数 = 验证接线 + 看去帽后
的真实丰富度(subplot 去 10 帽后应 >8、relationship 提到 30 对)。

用法: python -X utf8 scripts/refresh_spine_viz_fixtures.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from bookscope.agent._internal.chapter_spine_cache import get_or_build_spine
from bookscope.agent.chapter_spine_canon import build_spine_name_map
from bookscope.agent.chapter_spine_concept import concept_evolution_from_spine
from bookscope.agent.chapter_spine_consistency import consistency_scan_from_spine
from bookscope.agent.chapter_spine_relationship import relationship_timeline_from_spine
from bookscope.agent.chapter_spine_subplot import subplot_weave_from_spine
from bookscope.agent.chapter_spine_timeline import timeline_from_spine
from bookscope.api.dependencies import build_llm_client_from_params, default_model_for
from bookscope.ingest.book_chunker import chunk_book_with_stats
from bookscope.ingest.loader import load_text

FIXTURE = Path("web/src/demo/captured-fixtures.json")
CONCEPT = "天下大势"  # 沿用现有 demo 的概念词


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
    name_map = build_spine_name_map(spine=spine, llm_client=client, model=model)

    base_trace = {"input_tokens": 0, "output_tokens": 0,
                  "chars": sum(len(c["text"]) for c in chunks), "duration_ms": 0}
    meta = {"scanned": True, "book_session_id": "demo-sanguo", "trace": base_trace}

    events = timeline_from_spine(spine=spine, llm_client=client, model=model) or []
    weave = subplot_weave_from_spine(spine=spine, llm_client=client, model=model) or {}
    contradictions = consistency_scan_from_spine(spine=spine, llm_client=client, model=model) or []
    stages = concept_evolution_from_spine(
        concept=CONCEPT, spine=spine, llm_client=client, model=model) or []
    rel = relationship_timeline_from_spine(
        spine=spine, chunks=chunks, llm_client=client, model=model, name_map=name_map) or {}

    fx = json.loads(FIXTURE.read_text(encoding="utf-8"))
    j = fx["json"]
    j["POST /api/agent/timeline"] = {"events": events, **meta}
    j["POST /api/agent/subplot-weave"] = {
        "subplots": weave.get("subplots", []),
        "intersections": weave.get("intersections", []), **meta}
    j["POST /api/agent/consistency-scan"] = {"contradictions": contradictions, **meta}
    j["POST /api/agent/concept-evolution"] = {"concept": CONCEPT, "stages": stages, **meta}
    j["POST /api/agent/relationship-timeline"] = {"relations": rel.get("relations", []), **meta}
    FIXTURE.write_text(json.dumps(fx, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"timeline      事件 {len(events)}")
    nsub = len(weave.get("subplots", []))
    nx = len(weave.get("intersections", []))
    print(f"subplot       支线 {nsub} / 交汇 {nx}（去 10 帽前 8）")
    print(f"consistency   矛盾 {len(contradictions)}")
    print(f"concept       「{CONCEPT}」阶段 {len(stages)}")
    print(f"relationship  关系对 {len(rel.get('relations', []))}（14→30 帽前 14）")
    print("fixture 已刷新")


if __name__ == "__main__":
    main()
