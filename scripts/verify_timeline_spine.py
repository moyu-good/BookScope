"""验 timeline_from_spine——章脉派生的时间线是不是按**故事时序**排,不是死按章号排。

老 ``generate_timeline_exhaustive`` map-reduce 逐段抽 + ``sort(key=chapter)``,排出来就是叙述
(阅读)顺序,根本没还原故事时序,命根子(倒叙还原)废了。改成 timeline_from_spine:从章脉收全书
事件流、一次全局推理判每个事件的故事时序。这脚本在三国上跑新路径,打印证明指标。

三国基本线性,故事序 ≈ 叙述序属正常——关键看**机制**是按故事时序判而非死按章号排:看 LLM 给的
story_order 和叙述章号是否单调(若发现某个晚叙述的往事被移到靠前的真实时间点,举例)。

用法(PowerShell):
  $env:PYTHONIOENCODING='utf-8'; python -X utf8 scripts/verify_timeline_spine.py
DEEPSEEK_API_KEY 需在环境变量里。
"""

from __future__ import annotations

import os
from pathlib import Path

from bookscope.agent._internal.chapter_spine_cache import get_or_build_spine
from bookscope.agent.chapter_spine_timeline import timeline_from_spine
from bookscope.api.dependencies import build_llm_client_from_params, default_model_for
from bookscope.ingest.book_chunker import chunk_book_with_stats
from bookscope.ingest.loader import load_text


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
    events = timeline_from_spine(spine=spine, llm_client=client, model=model)
    if not events:
        print("没排出时间线(timeline_from_spine 返 None)")
        return

    chapters = sorted({e["chapter"] for e in events})
    with_time = [e for e in events if e["time"]]
    # 证明机制按故事时序判而非死按章号排:统计"故事序里相邻两条、后一条的叙述章号反而更小"的次数。
    # 死按章号排永远是 0(章号单调不减);出现 >0 说明 LLM 真把某些晚叙述的往事移到了靠前的时间点。
    inversions = []
    for prev, cur in zip(events, events[1:], strict=False):
        if cur["chapter"] < prev["chapter"]:
            inversions.append((prev, cur))

    print(f"事件总数 {len(events)}、覆盖章数 {len(chapters)}(第{chapters[0]}–{chapters[-1]}章)")
    print(f"带故事时间描述(time 非空)的事件 {len(with_time)} 条")
    print(
        f"故事时序 vs 叙述章号的逆序点 {len(inversions)} 个"
        "(死按章号排恒为 0;>0 = 机制确实按故事时序重排了倒叙/插叙)"
    )

    print("\n按故事时序排的前 15 个事件:")
    for e in events[:15]:
        t = f"[{e['time']}] " if e["time"] else ""
        print(f"  #{e['order']:>3} (叙述第{e['chapter']}章) {t}{e['event'][:48]}")

    if inversions:
        print("\n倒叙还原举例(后一条在故事时序上排到了更早、但叙述章号更靠后的位置):")
        for prev, cur in inversions[:5]:
            print(
                f"  故事序 #{prev['order']}(叙述第{prev['chapter']}章) → "
                f"#{cur['order']}(叙述第{cur['chapter']}章):{cur['event'][:42]}"
            )
    else:
        print(
            "\n本书未检出逆序点:三国基本线性,故事序≈叙述序属正常。"
            "关键是机制走的是一次全局故事时序推理,不是 sort(key=chapter)。"
        )


if __name__ == "__main__":
    main()
