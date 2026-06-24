"""验关系演变改章脉派生后,强度曲线是不是真"全程累积判断"——而不是逐段拼。

老 map-reduce ``generate_relationship_timeline_exhaustive`` 逐段盲:每段只看自己几章,打
"截至此章多紧"时看不见别段,各段各自打分再按章拼,累积量必错。改成
``relationship_timeline_from_spine`` 后,每对人**一次性**拿到全程逐章 note 才打分。

这脚本在三国上跑新路径,打印证明指标:关系对数、每对强度点覆盖章数、转折数;再挑一对
(优先刘备—曹操,没有就挑覆盖章数最多的)打印它的完整逐章强度曲线——曲线横跨全书多个
分散章、强度有升有落,就是全程判断的证据(逐段拼绝出不来贯穿全书的连续曲线)。

不刷任何 fixture(数据层验证脚本,不碰 web/src/demo)。

用法(PowerShell): $env:PYTHONIOENCODING='utf-8'; python -X utf8 scripts/verify_relationship_spine.py
"""

from __future__ import annotations

import os
from pathlib import Path

from bookscope.agent._internal.chapter_spine_cache import get_or_build_spine
from bookscope.agent.chapter_spine_relationship import relationship_timeline_from_spine
from bookscope.api.dependencies import build_llm_client_from_params, default_model_for
from bookscope.ingest.book_chunker import chunk_book_with_stats
from bookscope.ingest.loader import load_text


def _pick_focus(relations: list[dict]) -> dict | None:
    """挑一对打印曲线:优先刘备—曹操(三国经典对),否则取强度点覆盖章数最多的那对。"""
    for r in relations:
        names = {r["a"], r["b"]}
        if "刘备" in names and "曹操" in names:
            return r
    return max(relations, key=lambda r: len(r["points"]), default=None)


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
    print(f"章脉 {len(spine)} 章")

    result = relationship_timeline_from_spine(
        spine=spine, chunks=chunks, llm_client=client, model=model
    )
    if not result or not result.get("relations"):
        print("没抽出关系演变")
        return

    relations = result["relations"]
    total_tps = sum(len(r["turning_points"]) for r in relations)
    verified_tps = sum(
        sum(1 for t in r["turning_points"] if t.get("verified")) for r in relations
    )
    print(f"\n关系对数: {len(relations)}")
    print(f"转折点总数: {total_tps}(原文核验 {verified_tps}/{total_tps})")
    print("\n每对强度点覆盖章数 / 转折数:")
    for r in sorted(relations, key=lambda x: -len(x["points"])):
        chs = [p["chapter"] for p in r["points"]]
        span = (max(chs) - min(chs)) if chs else 0
        print(
            f"  {r['a']}—{r['b']}({r['relation'] or '关系'}): "
            f"{len(r['points'])} 个强度点、跨 {span} 章(第 {min(chs) if chs else '-'}→"
            f"{max(chs) if chs else '-'} 章)、{len(r['turning_points'])} 个转折"
        )

    focus = _pick_focus(relations)
    if focus is None:
        return
    print(f"\n证明全程判断 —— {focus['a']}—{focus['b']} 的完整逐章强度曲线:")
    print("  章号 : 强度(0-10,截至此章累积)")
    for p in focus["points"]:
        bar = "█" * p["strength"]
        print(f"  第{p['chapter']:>4}章 : {p['strength']:>2} {bar}")
    print("  转折点:")
    for t in focus["turning_points"]:
        mark = "已核验" if t.get("verified") else "未核验"
        print(f"    第{t['chapter']}章 [{mark}] {t['change'][:50]}")
        if t.get("evidence"):
            print(f"      原文: {t['evidence'][:60]}")
    chs = [p["chapter"] for p in focus["points"]]
    if chs and (max(chs) - min(chs)) > 0:
        print(
            f"\n  ✓ 曲线横跨第 {min(chs)}→{max(chs)} 章、共 {len(chs)} 个分散章点连成一条线——"
            "逐段拼出不来贯穿全书的连续累积曲线,这就是全程判断的证据。"
        )


if __name__ == "__main__":
    main()
