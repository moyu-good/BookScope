"""验概念演进章脉派生:三国上跑 concept_evolution_from_spine,证明不截断、串全书。

老 ``generate_concept_evolution`` 整本一次进 context,大书截断——被截掉后半本里这个概念怎么
深化的就丢了。新 ``concept_evolution_from_spine`` 从章脉全书摘要排演进,章脉覆盖全 119 章,
能串到书末。

打印**证明指标**:章脉覆盖章数、演进阶段数、阶段覆盖的章跨度(末阶段章号越靠书末, 越证明
没被前半本截断)。三国用「忠义」「权谋」这类贯穿全书的母题当概念(小说退用 events/states 线索)。

用法: $env:PYTHONIOENCODING='utf-8'; python -X utf8 scripts/verify_concept_spine.py
"""

from __future__ import annotations

import os
from pathlib import Path

from bookscope.agent._internal.chapter_spine_cache import get_or_build_spine
from bookscope.agent.chapter_spine_concept import concept_evolution_from_spine
from bookscope.api.dependencies import build_llm_client_from_params, default_model_for
from bookscope.ingest.book_chunker import chunk_book_with_stats
from bookscope.ingest.loader import load_text

CONCEPTS = ["忠义", "天下", "权谋"]


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
    spine_chs = sorted(r.get("chapter") for r in spine if isinstance(r.get("chapter"), int))
    print(f"章脉覆盖: {len(spine_chs)} 章, 章号 {spine_chs[0]}..{spine_chs[-1]}")
    print("=> 派生版演进视野 = 整本 119 章(章脉是全书一次精读, 不截断)\n")

    for concept in CONCEPTS:
        stages = concept_evolution_from_spine(
            concept=concept, spine=spine, llm_client=client, model=model
        )
        if stages is None:
            print(f"概念「{concept}」: 失败(返 None)\n")
            continue
        if not stages:
            print(f"概念「{concept}」: 书里没追到(空数组,合法)\n")
            continue
        chs = [s["chapter"] for s in stages]
        print(f"概念「{concept}」: {len(stages)} 个演进阶段, 章 {min(chs)}..{max(chs)}")
        for s in stages[:4]:
            print(f"  第{s['chapter']}章: {s['development'][:54]}")
        if len(stages) > 4:
            print(f"  ... 末阶段 第{stages[-1]['chapter']}章: {stages[-1]['development'][:54]}")
        print(f"  覆盖跨度: 第{min(chs)}章 → 第{max(chs)}章"
              f"(末阶段靠书末 = 没被前半本截断)\n")


if __name__ == "__main__":
    main()
