"""验概念关系图改章脉派生后,跨章的概念勾连是不是真抽出来了。

老路径走 ``extract_character_graph_exhaustive``——按字符预算切段、每段单独抽段内概念关系再合并;
跨段的概念关联(一个概念在某章提出、在另一章才和别的概念勾连)系统性漏报。改成
``concept_graph_from_spine``(章脉全书主张一次全局推理)后,概念关系应该能跨章。

概念维只在理论书的 theory-genre 章脉里有,所以这脚本在**理论书**(制内市场)上跑、且
``get_or_build_spine(..., genre="theory")`` 才拿得到 claims。打印:claims 覆盖章数、概念节点数、
概念关系边数、几条跨章概念关系举例。

用法(PowerShell):
    $env:PYTHONIOENCODING='utf-8'; python -X utf8 scripts/verify_concept_graph_spine.py
"""

from __future__ import annotations

import os
from pathlib import Path

from bookscope.agent._internal.chapter_spine_cache import get_or_build_spine
from bookscope.agent.chapter_spine_concept_graph import concept_graph_from_spine
from bookscope.api.dependencies import build_llm_client_from_params, default_model_for
from bookscope.ingest.book_chunker import chunk_book_with_stats
from bookscope.ingest.loader import load_text


def main() -> None:
    # 理论书:制内市场(zhinei,中国国家主导型政治经济学)。概念维是理论书功能,必须在理论书上验。
    path = next(p for p in Path("tests/file").glob("*制内市场*"))
    book = load_text(str(path), title="制内市场")
    chunk_res, _ = chunk_book_with_stats(book)
    chunks = [
        {"chunk_id": f"r0-chunk-{c.index}", "chapter": c.chapter, "text": c.text}
        for c in chunk_res
    ]
    client = build_llm_client_from_params(
        provider="deepseek", api_key=os.environ["DEEPSEEK_API_KEY"]
    )
    model = default_model_for("deepseek")

    # genre="theory" 才抽 claims(概念维)——这是概念图的底座。
    spine = get_or_build_spine(
        chunks=chunks, llm_client=client, model=model, genre="theory"
    )
    claim_chs = [r["chapter"] for r in spine if isinstance(r.get("claims"), list) and r["claims"]]
    print(f"章脉 {len(spine)} 章;有 claims(概念维)的章 {len(claim_chs)} 个")
    if not claim_chs:
        print("理论书章脉里没抽到 claims——概念图没底座,如实报告,别硬凑。")
        return

    graph = concept_graph_from_spine(spine=spine, llm_client=client, model=model)
    if not graph:
        print("没推出概念关系图(claims 不够支撑 / 调用或解析失败)")
        return

    nodes = graph["nodes"]
    edges = graph["edges"]
    verified = sum(1 for e in edges if e.get("verified"))
    print(f"概念节点 {len(nodes)} 个;概念关系边 {len(edges)} 条({verified} 条锚到真实章带证据)")

    print("\n概念节点(前 20):")
    print("  " + "、".join(nodes[:20]))

    # 跨章概念关系:同一概念出现在多条边、且这些边锚的章不同——说明这概念在不同章里和别的概念勾连。
    by_concept_chs: dict[str, set[int]] = {}
    for e in edges:
        ch = e.get("chapter") or 0
        if ch:
            by_concept_chs.setdefault(e["source"], set()).add(ch)
            by_concept_chs.setdefault(e["target"], set()).add(ch)
    cross = sorted(
        ((c, chs) for c, chs in by_concept_chs.items() if len(chs) >= 2),
        key=lambda x: -len(x[1]),
    )
    print(f"\n跨多章勾连的概念 {len(cross)} 个(同一概念在 ≥2 个不同章和别的概念连边):")
    for c, chs in cross[:6]:
        print(f"  「{c}」出现在第 {sorted(chs)} 章的概念关系里")

    print("\n几条概念关系边(按 strength 降序):")
    for e in edges[:10]:
        snip = (e.get("evidence") or "")[:38]
        print(
            f"  {e['source']} —[{e['relation']}, 强度{e['strength']}]→ {e['target']}"
            f"  (第{e['chapter']}章, verified={e['verified']})"
        )
        if snip:
            print(f"      证据: {snip}")


if __name__ == "__main__":
    main()
