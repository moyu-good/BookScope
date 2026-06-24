"""专修 subplot-weave 的 demo fixture。

refresh_list_fixtures.py 把 subplot 当 list 数错了——它返回 dict(``{subplots, intersections}``),
被整个塞进 fixture 的 subplots 键里(嵌套坏)。这里正确取 ``weave["subplots"]`` / ``["intersections"]``
按 FE(SubplotWeave.tsx 读 data.subplots / data.intersections)的真形态写,并打印真实条数。

用法: python -X utf8 scripts/refresh_subplot_fixture.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from bookscope.agent.subplot_weave import generate_subplot_weave_exhaustive
from bookscope.api.dependencies import build_llm_client_from_params, default_model_for
from bookscope.ingest.book_chunker import chunk_book_with_stats
from bookscope.ingest.loader import load_text

FIXTURE = Path("web/src/demo/captured-fixtures.json")
KEY = "POST /api/agent/subplot-weave"


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

    weave = generate_subplot_weave_exhaustive(chunks=chunks, llm_client=client, model=model)
    if not weave or not weave.get("subplots"):
        print("没抽出支线")
        return

    fx = json.loads(FIXTURE.read_text(encoding="utf-8"))
    fx["json"][KEY] = {
        "subplots": weave["subplots"],
        "intersections": weave.get("intersections", []),
        "scanned": True,
        "book_session_id": "demo-sanguo",
        "trace": {"input_tokens": 0, "output_tokens": 0,
                  "chars": sum(len(c["text"]) for c in chunks), "duration_ms": 0},
    }
    FIXTURE.write_text(json.dumps(fx, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"subplot fixture 刷新:{len(weave['subplots'])} 条支线 + "
          f"{len(weave.get('intersections', []))} 个交汇(旧 demo 9 条)")
    for s in weave["subplots"][:12]:
        print(f"  {s.get('name')}: 活跃 {len(s.get('active_chapters', []))} 章")


if __name__ == "__main__":
    main()
