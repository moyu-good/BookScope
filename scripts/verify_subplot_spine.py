"""验证 subplot 交汇的章脉派生版(``subplot_weave_from_spine``)抓得到跨段交汇。

老 ``generate_subplot_weave_exhaustive`` 是 map-reduce 逐段跑的——支线 A 在前段、支线 B 在
后段,它们在某章交汇时没有哪一段同时看见两条线,这交汇就漏了。新版从章脉全书梗概一次全局
推理,跨段交汇也能配上。

本脚本在三国上同时跑两版,打印证明指标:
  · 各版支线条数、交汇条数(对比旧 demo 约 23 个交汇);
  · 新版的**跨段交汇举例**——两条支线最早活跃章隔得远(setup 段 vs payoff 段),却在某章
    交汇的那些;这正是 map-reduce 看不见、章脉能抓到的。

用法(PowerShell):
    $env:PYTHONIOENCODING='utf-8'; python -X utf8 scripts/verify_subplot_spine.py
``DEEPSEEK_API_KEY`` 在环境变量。
"""

from __future__ import annotations

import os
from pathlib import Path

from bookscope.agent.chapter_spine import build_chapter_spine
from bookscope.agent.chapter_spine_subplot import subplot_weave_from_spine
from bookscope.agent.subplot_weave import generate_subplot_weave_exhaustive
from bookscope.api.dependencies import build_llm_client_from_params, default_model_for
from bookscope.ingest.book_chunker import chunk_book_with_stats
from bookscope.ingest.loader import load_text

# 跨段交汇判定:两条支线最早活跃章相差到这么多章,就当它们"分处前后段"。
_FAR_SETUP_GAP = 10


def _earliest_active(weave: dict, name: str) -> int | None:
    for sp in weave.get("subplots", []):
        if sp["name"] == name:
            ac = sp.get("active_chapters") or []
            return ac[0] if ac else None
    return None


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

    print("=== 建章脉(整本一次精读,L2 多半已命中)===")
    spine = build_chapter_spine(chunks=chunks, llm_client=client, model=model)
    print(f"章脉:{len(spine)} 章")

    print("\n=== 新版:subplot_weave_from_spine(全局一次推理)===")
    new = subplot_weave_from_spine(spine=spine, llm_client=client, model=model)
    if not new or not new.get("subplots"):
        print("章脉派生版没抽出支线 —— 结果不可用,如实报告")
        return
    new_sp = new["subplots"]
    new_it = new["intersections"]
    print(f"支线 {len(new_sp)} 条、交汇 {len(new_it)} 处")

    print("\n=== 旧版:generate_subplot_weave_exhaustive(map-reduce 逐段)===")
    old = generate_subplot_weave_exhaustive(chunks=chunks, llm_client=client, model=model)
    old_sp = (old or {}).get("subplots", [])
    old_it = (old or {}).get("intersections", [])
    print(f"支线 {len(old_sp)} 条、交汇 {len(old_it)} 处")

    print("\n=== 证明指标 ===")
    print(f"交汇数  新(章脉) {len(new_it)}  vs  旧(map-reduce) {len(old_it)}  "
          f"(旧 demo 约 23 个交汇)")

    print("\n=== 跨段交汇举例(两条支线最早活跃章相差 ≥"
          f"{_FAR_SETUP_GAP} 章 → map-reduce 不可能同段看见)===")
    far = []
    for it in new_it:
        a, b = it["subplots"][0], it["subplots"][1]
        ea, eb = _earliest_active(new, a), _earliest_active(new, b)
        if ea is None or eb is None:
            continue
        gap = abs(ea - eb)
        if gap >= _FAR_SETUP_GAP:
            far.append((gap, it["chapter"], a, ea, b, eb))
    far.sort(reverse=True)
    if not far:
        print("(本次没出现 setup 段隔得远的交汇)")
    for gap, ch, a, ea, b, eb in far[:12]:
        print(f"  第 {ch} 章交汇:「{a}」(最早活跃 第{ea}章) × 「{b}」(最早活跃 第{eb}章) "
              f"—— 两线起点隔 {gap} 章")

    print("\n=== 新版支线一览 ===")
    for sp in new_sp[:12]:
        ac = sp["active_chapters"]
        rng = f"第{ac[0]}–{ac[-1]}章" if ac else "—"
        flag = "" if sp.get("verified") else "(证据未核验)"
        print(f"  {sp['name']}: 活跃 {len(ac)} 章 [{rng}] {flag}")


if __name__ == "__main__":
    main()
