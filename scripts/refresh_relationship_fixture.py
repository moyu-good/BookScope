"""重抓 demo 的关系编年 fixture(1.5.1 新结构):全员对清单 + top-N 对的关系编年。

关系演变端点 1.5.1 改成两种返法(见 chapter_spine_relationship / agent.py):
- 不传 pair → 全员对清单 {relations:[], pairs:[{a,b,chapters,first,last,count}]}
- 传 pair_a/pair_b → 这对的关系编年 {relations:[{a,b,verdict,beats}], pairs:[]}

demo 拦截器只按"METHOD 路径"匹配、不看 body,所以这里写两个 key,拦截器按请求体 pair 分支取:
- "POST /api/agent/relationship-timeline" = 全员清单响应
- "POST /api/agent/relationship-timeline#chronicles" = {pairKey(sorted a|b): 单对编年响应}

全员清单不调 LLM;单对编年命中 L2 缓存(同书同 prompt)基本免费。不动后端逻辑。

用法(PowerShell): $env:PYTHONIOENCODING='utf-8'; python -X utf8 scripts/refresh_relationship_fixture.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from bookscope.agent._internal.chapter_spine_cache import get_or_build_spine
from bookscope.agent.chapter_spine_canon import build_spine_name_map
from bookscope.agent.chapter_spine_relationship import (
    relationship_chronicle_for_pair,
    relationship_pairs_index,
)
from bookscope.api.dependencies import build_llm_client_from_params, default_model_for
from bookscope.ingest.book_chunker import chunk_book_with_stats
from bookscope.ingest.loader import load_text

FIXTURES = Path("web/src/demo/captured-fixtures.json")
KEY = "POST /api/agent/relationship-timeline"
TOP_N = 8  # demo 预生成戏份最重的前 N 对编年,其余对前端选了再现取(demo 下没数据就显空态)


def _load_dotenv() -> None:
    p = Path(".env")
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _pair_key(a: str, b: str) -> str:
    return "|".join(sorted([a, b]))


def main() -> None:
    _load_dotenv()
    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("需要 DEEPSEEK_API_KEY（环境变量或 .env）。")
        return
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

    index = relationship_pairs_index(spine, name_map)
    base_trace = {"input_tokens": 0, "output_tokens": 0, "chars": 0, "duration_ms": 0}
    index_resp = {
        "relations": [],
        "pairs": index,
        "scanned": bool(index),
        "book_session_id": "demo",
        "trace": base_trace,
    }

    chronicles: dict[str, dict] = {}
    for p in index[:TOP_N]:
        rel = relationship_chronicle_for_pair(
            a=p["a"], b=p["b"], spine=spine, chunks=chunks,
            llm_client=client, model=model, name_map=name_map,
        )
        if rel:
            chronicles[_pair_key(p["a"], p["b"])] = {
                "relations": [rel],
                "pairs": [],
                "scanned": True,
                "book_session_id": "demo",
                "trace": base_trace,
            }
    print(f"全员清单 {len(index)} 对、预生成编年 {len(chronicles)} 条")

    data = json.loads(FIXTURES.read_text(encoding="utf-8"))
    data["json"][KEY] = index_resp
    data["json"][KEY + "#chronicles"] = chronicles
    FIXTURES.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"写入 {FIXTURES}")


if __name__ == "__main__":
    main()
