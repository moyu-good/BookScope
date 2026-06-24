"""验 + 刷新穷尽化 list-viz 的 demo fixture(时间线/关系演变/伏笔/支线/论点)——查"一眼数量不足"。

这几个 demo 条数顶着或近"最多约 N"的帽(时间线30/论点20/伏笔25/支线9/关系演变5),疑跟 narrative/
arc 同病:化石 demo 是穷尽化之前的单次帽数据,产品穷尽化(map-reduce 逐段抽+合并)应累加更多。
真后端在三国跑一遍(三国段在 DeepSeek 前缀缓存里热、input 多半命中),打印条数 = 验证产品没被帽,
顺带刷新 demo。

用法: python -X utf8 scripts/refresh_list_fixtures.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from bookscope.agent.argument_structure import generate_argument_structure_exhaustive
from bookscope.agent.foreshadow_arcs import generate_foreshadow_arcs_exhaustive
from bookscope.agent.relationship_timeline import generate_relationship_timeline_exhaustive
from bookscope.agent.subplot_weave import generate_subplot_weave_exhaustive
from bookscope.agent.timeline import generate_timeline_exhaustive
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
    client = build_llm_client_from_params(
        provider="deepseek", api_key=os.environ["DEEPSEEK_API_KEY"]
    )
    model = default_model_for("deepseek")

    def run(fn):  # noqa: ANN001, ANN202
        return fn(chunks=chunks, llm_client=client, model=model) or []

    # (fixture key, 内层字段, generate 函数, 旧 demo 条数)
    jobs = [
        ("POST /api/agent/timeline", "events", generate_timeline_exhaustive, 30),
        ("POST /api/agent/relationship-timeline", "relations", generate_relationship_timeline_exhaustive, 5),
        ("POST /api/agent/foreshadow-arcs", "arcs", generate_foreshadow_arcs_exhaustive, 25),
        ("POST /api/agent/subplot-weave", "subplots", generate_subplot_weave_exhaustive, 9),
        ("POST /api/agent/argument-structure", "claims", generate_argument_structure_exhaustive, 20),
    ]

    fx = json.loads(FIXTURE.read_text(encoding="utf-8"))
    base_trace = {"input_tokens": 0, "output_tokens": 0,
                  "chars": sum(len(c["text"]) for c in chunks), "duration_ms": 0}
    for key, field, fn, old in jobs:
        items = run(fn)
        fx["json"][key] = {field: items, "scanned": True,
                           "book_session_id": "demo-sanguo", "trace": base_trace}
        FIXTURE.write_text(json.dumps(fx, ensure_ascii=False, indent=2), encoding="utf-8")  # 增量落盘
        flag = "← 化石带帽,产品更多" if len(items) > old * 1.5 else ("← 跟旧相近,可能真帽" if items else "← 抽空了")
        print(f"{field:10} 旧 {old:>3} → 现 {len(items):>4}  {flag}")


if __name__ == "__main__":
    main()
