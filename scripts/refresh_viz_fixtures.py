"""把 spine 派生的 viz demo fixture(叙事曲线/节奏/叙事流)刷成当前全量——化石那批带帽(40章/27章)
看着像"太少",其实产品走章脉已覆盖全书。spine + name_map 缓存命中(0 LLM)。

跑完打印条数 = 顺带验证产品真没被帽(三国应 ~120 章)。然后重截图给 README。
arc(人物弧线)是老路径不在这,单独处理。

用法: python -X utf8 scripts/refresh_viz_fixtures.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from bookscope.agent._internal.chapter_spine_cache import get_or_build_spine
from bookscope.agent.chapter_spine_canon import build_spine_name_map
from bookscope.agent.chapter_spine_evidence import evidence_for_pair
from bookscope.agent.chapter_spine_views import (
    narrative_curve_from_spine,
    narrative_flow_from_spine,
    pacing_from_spine,
)
from bookscope.api.dependencies import build_llm_client_from_params, default_model_for
from bookscope.ingest.book_chunker import chunk_book_with_stats
from bookscope.ingest.loader import load_text

FIXTURE = Path("web/src/demo/captured-fixtures.json")


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
    name_map = build_spine_name_map(spine=spine, llm_client=client, model=model)

    narrative = narrative_curve_from_spine(spine)
    pacing = pacing_from_spine(spine)
    flow = narrative_flow_from_spine(spine, name_map=name_map)
    # 给叙事流的同场对填真原文(纯检索),demo 点开也看得到证据
    for ch in flow:
        for pr in ch["pairs"]:
            pr["evidence"] = evidence_for_pair(ch_text.get(ch["chapter"], ""), pr["a"], pr["b"])

    chars = sum(len(c.get("present", [])) for c in flow)
    base_trace = {"input_tokens": 0, "output_tokens": 0, "chars": sum(len(c["text"]) for c in chunks),
                  "duration_ms": 0}

    fx = json.loads(FIXTURE.read_text(encoding="utf-8"))
    fx["json"]["POST /api/agent/narrative-curve"] = {
        "chapters": narrative, "scanned": True, "book_session_id": "demo-sanguo", "trace": base_trace}
    fx["json"]["POST /api/agent/pacing-curve"] = {
        "points": pacing, "book_session_id": "demo-sanguo", "trace": base_trace}
    fx["json"]["POST /api/agent/character-flow"] = {
        "chapters": flow, "scanned": True, "book_session_id": "demo-sanguo", "trace": base_trace}
    FIXTURE.write_text(json.dumps(fx, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"叙事曲线: {len(narrative)} 章   节奏: {len(pacing)} 章   叙事流: {len(flow)} 章")
    print(f"叙事流全书出场人次合计: {chars}")
    print("(三国 ~120 回——若这里是 100+ 章,证明产品走章脉没被帽,化石那 40 章是旧 demo 数据)")


if __name__ == "__main__":
    main()
