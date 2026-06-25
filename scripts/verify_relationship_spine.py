"""验关系演变 1.5.1 重做后的「关系编年」——总判尖不尖、编年密不密、每幕挂不挂得上原文。

1.5.1 把关系演变从"压成一根不可信亲疏线"改成 ``relationship_timeline_from_spine`` 出
**总判(评点 + 不对称) + 逐幕编年(场景/关系表述/为何变/敌友色温/原文)**。这脚本在三国上跑新路径,
挑刘备—曹操打印完整产出,看:
  - verdict 的 essence / arc / 不对称两边 / sharp_point 是不是真站在全书高度的判断(不是废话);
  - beats 够不够密(明显多于旧版零星几个)、关系表述对不对、"为何变"因果顺不顺;
  - 每幕原文挂得上、核得过(verified)。

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


def _load_dotenv() -> None:
    """脚本自带的 .env 加载:把 KEY=VALUE 灌进 os.environ(已存在的不覆盖)。本地验证脚本用。"""
    p = Path(".env")
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _pick_focus(relations: list[dict]) -> dict | None:
    """挑一对打印编年:优先刘备—曹操(三国经典对),否则取幕数最多的那对。"""
    for r in relations:
        if {"刘备", "曹操"} <= {r["a"], r["b"]}:
            return r
    return max(relations, key=lambda r: len(r["beats"]), default=None)


def _print_verdict(v: dict) -> None:
    print(f"  本质 : {v.get('essence') or '-'}")
    print(f"  走向 : {v.get('arc') or '-'}")
    if v.get("asymmetric"):
        print(f"  不对称 · A看B : {v.get('view_a_on_b') or '-'}")
        print(f"  不对称 · B看A : {v.get('view_b_on_a') or '-'}")
    else:
        print("  不对称 : 否(对称关系)")
    print(f"  最尖锐一笔 : {v.get('sharp_point') or '-'}(挂第 {v.get('pivot_chapter')} 章)")


def main() -> None:
    _load_dotenv()
    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("需要 DEEPSEEK_API_KEY（环境变量或 .env）才能实跑，未找到。")
        return
    book_key = os.environ.get("VERIFY_BOOK", "三国")  # tests/file/ 里文件名的子串,默认三国
    path = next(p for p in Path("tests/file").glob("*") if book_key in p.name)
    book = load_text(str(path), title=path.stem)
    print(f"书:{path.name}")
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
        spine=spine, chunks=chunks, llm_client=client, model=model,
        max_pairs=int(os.environ.get("VERIFY_MAX_PAIRS", "30")),
    )
    if not result or not result.get("relations"):
        print("没抽出关系演变(可能这本书没有成戏的人物对)")
        return

    relations = result["relations"]
    total_beats = sum(len(r["beats"]) for r in relations)
    verified = sum(sum(1 for b in r["beats"] if b.get("verified")) for r in relations)
    asym = sum(1 for r in relations if r["verdict"].get("asymmetric"))
    print(f"\n关系对数: {len(relations)}　总幕数: {total_beats}"
          f"(原文核验 {verified}/{total_beats})　不对称的对: {asym}")
    print("\n每对幕数 / 跨章 / 不对称:")
    for r in sorted(relations, key=lambda x: -len(x["beats"])):
        chs = [b["chapter"] for b in r["beats"]]
        span = (max(chs) - min(chs)) if chs else 0
        flag = "不对称" if r["verdict"].get("asymmetric") else "对称"
        print(f"  {r['a']}—{r['b']}: {len(r['beats'])} 幕、跨 {span} 章"
              f"(第 {min(chs) if chs else '-'}→{max(chs) if chs else '-'})、{flag}")

    focus = _pick_focus(relations)
    if focus is None:
        return
    print(f"\n{'='*60}\n{focus['a']}—{focus['b']} 的完整关系编年:\n{'='*60}")
    print("\n【总判】")
    _print_verdict(focus["verdict"])
    print(f"\n【编年】共 {len(focus['beats'])} 幕:")
    for b in focus["beats"]:
        mark = "✓" if b.get("verified") else "·"
        print(f"\n  第{b['chapter']}章 [{mark}] 敌友{b['valence']:+d} | {b.get('state') or '-'}")
        print(f"    场景: {b.get('scene') or '-'}")
        if b.get("change"):
            print(f"    为何变: {b['change']}")
        if b.get("evidence"):
            print(f"    原文: {b['evidence'][:64]}")
    chs = [b["chapter"] for b in focus["beats"]]
    if chs and (max(chs) - min(chs)) > 0:
        print(f"\n  ✓ 编年横跨第 {min(chs)}→{max(chs)} 章、共 {len(chs)} 幕——"
              "总判站在全程之上、每幕钉原文,这才是关系编年。")


if __name__ == "__main__":
    main()
