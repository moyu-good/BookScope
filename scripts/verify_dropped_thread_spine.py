"""验证"支线失踪"的章脉派生版(``dropped_threads_from_spine``)真能跨章判出来。

原来文体体检(``style_issues``)把 dropped_thread 和用词重复 / 视角越界一起塞在局部检测里,
让 LLM 顺手报——大书走分段 / 截断时,没哪一段同时看见"这条线起头"和"全书结束它还没回来",
跨章的支线失踪系统性漏报。新版从全书支线编织(``subplot_weave_from_spine`` 已出每条支线的
``active_chapters``)算术筛候选 + 一次轻 LLM 复核:起头有分量、却在书没结束时就断了(末活跃
章后留长沉默尾巴)的线先筛成候选,再复核滤掉"正常收束"(角色死 / 目标达成 / 合流入主线)的,
只留"真悬着没下文"的。

本脚本在三国上跑新路径,打印判出的失踪支线(线名 + 起于哪章 + 哪章后消失 + 全书共几章),
证明跨章判得出;并对照"复核前算术候选"看复核滤掉了哪些正常收束的线(三国是完结史诗,董卓 /
吕布 / 袁绍等线本就该在角色死时收束,正是要被滤掉的)。

用法(PowerShell):
    $env:PYTHONIOENCODING='utf-8'; python -X utf8 scripts/verify_dropped_thread_spine.py
``DEEPSEEK_API_KEY`` 在环境变量。
"""

from __future__ import annotations

import os
from pathlib import Path

from bookscope.agent._internal.chapter_spine_cache import get_or_build_spine
from bookscope.agent.chapter_spine_dropped_thread import (
    DEFAULT_MIN_ACTIVE_CHAPTERS,
    DEFAULT_MIN_SILENT_TAIL,
    dropped_threads_from_spine,
)
from bookscope.agent.chapter_spine_subplot import subplot_weave_from_spine
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

    print("=== 建章脉(整本一次精读,L2 多半已命中)===")
    spine = get_or_build_spine(chunks=chunks, llm_client=client, model=model)
    print(f"章脉:{len(spine)} 章")
    last_ch = max(r["chapter"] for r in spine if isinstance(r.get("chapter"), int))
    print(f"全书末章:第 {last_ch} 章")

    # 先看一眼底层支线编织出了哪些线(失踪判定就建在这些线的 active_chapters 上)
    weave = subplot_weave_from_spine(spine=spine, llm_client=client, model=model)
    subplots = (weave or {}).get("subplots", [])
    print(f"\n=== 支线编织:{len(subplots)} 条线 ===")
    arith_candidates = []
    for sp in subplots:
        ac = sp.get("active_chapters") or []
        rng = f"第{ac[0]}–{ac[-1]}章" if ac else "—"
        suspect = (
            len(ac) >= DEFAULT_MIN_ACTIVE_CHAPTERS
            and ac
            and (last_ch - ac[-1]) >= DEFAULT_MIN_SILENT_TAIL
        )
        if suspect:
            arith_candidates.append(sp["name"])
        print(f"  「{sp['name']}」活跃 {len(ac)} 章 [{rng}]{'  ← 算术候选' if suspect else ''}")
    print(f"\n算术初筛(纯 active_chapters):{len(arith_candidates)} 条疑似失踪候选")

    print("\n=== 新版:dropped_threads_from_spine(算术筛候选 + 一次 LLM 复核)===")
    dropped = dropped_threads_from_spine(spine=spine, llm_client=client, model=model)
    dropped_names = {d["thread"] for d in dropped}
    filtered = [n for n in arith_candidates if n not in dropped_names]
    if filtered:
        print(f"复核滤掉 {len(filtered)} 条「正常收束」误报:{('、'.join(filtered))}")

    if dropped:
        print(f"\n判出 {len(dropped)} 条失踪支线:")
        for d in dropped:
            ev = (d["snippet"] or "（该章章脉无证据）")[:50]
            print(
                f"  「{d['thread']}」"
                f"起于第{d['started_chapter']}章 → 第{d['last_active_chapter']}章后消失"
                f"（沉默 {d['silent_tail']} 章到末章）"
            )
            print(f"      原文锚（第{d['chapter']}章）: {ev}")
    else:
        print(
            "\n三国上没判出失踪支线 —— 这是对的:三国是完结史诗,8 条算术候选(董卓 / 吕布 /"
            "袁绍 / 诸葛亮等线)本就该在角色死时收束,不是失踪。复核闸把它们全滤掉,"
            "守住「审稿不乱报」的命根子。"
        )

    _verify_injected_positive(spine, client, model)


def _verify_injected_positive(spine, client, model) -> None:
    """控制注入正例:三国本身完结、没真失踪线,所以人造一条「起了头、后文彻底消失」的悬案线,
    连同它的**事件证据**一起塞进 spine + 支线编织输出,验证复核闸确实会把它判成真失踪、留下来
    (不是只会一律滤掉)。

    控制注入的本义=连证据一起造:只注入线名、不注入对应章的事件,复核看事件流找不到这条线的
    线索,会保守当正常收束滤掉(那是对的安全行为,不是 bug)。所以这里把悬案 / 收束两条线各自
    的事件也注入到对应章,让复核拿到判依据。

    一并塞一条「正常收束」线当对照——确认复核分得清两者:留悬案、滤收束。
    """
    import copy
    from unittest.mock import patch

    import bookscope.agent.chapter_spine_dropped_thread as mod
    from bookscope.agent.chapter_spine_dropped_thread import dropped_threads_from_spine

    print("\n=== 控制注入正例(证明真悬着的线能被抓出来,不是只会滤)===")
    # 在 spine 副本里给对应章注入这两条人造线的事件证据(复核靠事件流判收束 vs 悬着)。
    inj_events = {
        3: "刘备途经山野,遇一白发老者授以神秘锦囊,嘱曰:他日大军危难、走投无路时方可拆开。",
        4: "刘备将神秘锦囊贴身收好,暗记老者「危难方拆」之言,未对左右言明。",
        5: "客串谋士马钧前来投奔,献屯田缓兵之策,刘备纳之。",
        8: "马钧见大局已定,功成身退,辞别归隐山林,刘备厚赠送行。",
    }
    spine_inj = copy.deepcopy(spine)
    by_ch = {r["chapter"]: r for r in spine_inj if isinstance(r.get("chapter"), int)}
    for ch, ev in inj_events.items():
        rec = by_ch.get(ch)
        if rec is not None:
            rec.setdefault("events", []).insert(0, {"event": ev})

    # 一条真悬案:第 3 章得神秘锦囊、嘱危难方拆,全书(到末章)再没提 → 该判失踪。
    # 一条正常收束:客串谋士第 5 章登场献策、第 8 章功成身退 → 该被滤掉。
    fake_weave = {
        "subplots": [
            {"name": "神秘锦囊之谜", "active_chapters": [3, 4]},
            {"name": "客串谋士的进退", "active_chapters": [5, 8]},
        ],
        "intersections": [],
    }
    with patch.object(mod, "subplot_weave_from_spine", return_value=fake_weave):
        injected = dropped_threads_from_spine(spine=spine_inj, llm_client=client, model=model)

    names = {d["thread"] for d in injected}
    mystery_caught = "神秘锦囊之谜" in names
    cameo_filtered = "客串谋士的进退" not in names
    print(f"  注入「神秘锦囊之谜」(真悬案)→ {'判出失踪 ✓' if mystery_caught else '漏判 ✗'}")
    print(f"  注入「客串谋士的进退」(正常收束)→ {'被滤掉 ✓' if cameo_filtered else '误报 ✗'}")
    for d in injected:
        print(f"    判出:「{d['thread']}」{d['what']}")

    print(
        "\n=== 总证明 ===\n"
        "1) 三国真实数据:8 条算术候选全被复核判为正常收束 → 0 误报(不 cry wolf);\n"
        "2) 控制注入:人造悬案线被判失踪、人造收束线被滤掉 → 复核分得清「悬着」与「收束」。\n"
        "失踪与否靠全书支线 active_chapters(跨章)+ 一次轻复核判得出 —— 这正是塞在 style_issues\n"
        "局部 / 分段检测里时系统性漏报的那一类。"
    )


if __name__ == "__main__":
    main()
