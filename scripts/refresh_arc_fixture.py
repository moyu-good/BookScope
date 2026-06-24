"""刷新 arc(人物弧线/花鸟)demo fixture——化石那版只 3 角色(花鸟太疏)。arc 不是 spine 派生
(fortune 处境数值章脉没有),走自己的 generate_character_arc_exhaustive 重抽;三国段在 DeepSeek
前缀缓存里热,只多发 arc 指令、便宜。HuaniaoArc 显前 MAX_BRANCHES=6 枝,数据有 ≥6 就显 6。

用法: python -X utf8 scripts/refresh_arc_fixture.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from bookscope.agent.character_arc import generate_character_arc_exhaustive
from bookscope.api.dependencies import build_llm_client_from_params, default_model_for
from bookscope.ingest.book_chunker import chunk_book_with_stats
from bookscope.ingest.loader import load_text

FIXTURE = Path("web/src/demo/captured-fixtures.json")
KEY = "POST /api/agent/character-arc"


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

    characters = generate_character_arc_exhaustive(chunks=chunks, llm_client=client, model=model)
    if not characters:
        print("没抽出角色")
        return

    fx = json.loads(FIXTURE.read_text(encoding="utf-8"))
    fx["json"][KEY] = {
        "characters": characters,
        "scanned": True,
        "book_session_id": "demo-sanguo",
        "trace": {"input_tokens": 0, "output_tokens": 0,
                  "chars": sum(len(c["text"]) for c in chunks), "duration_ms": 0},
    }
    FIXTURE.write_text(json.dumps(fx, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"arc fixture 刷新:{len(characters)} 个角色")
    for c in characters[:10]:
        print(f"  {c['name']}: {len(c.get('points', []))} 点")


if __name__ == "__main__":
    main()
