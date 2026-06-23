"""真跑一次分析(live LLM)并把全量结果存成可查的 log——不靠 demo 化石,看真实输出。

默认在三国上跑叙事曲线(穷尽化,覆盖全书每一章),把每章的 章号/张力/情感/视角/主支线/是否核验/
原文 全存进 docs/internal/experiments/runs/ 下的 JSON + 可读 .md 表。顺带抽查"卖草鞋(应回1)/
负天下人(应回4)"的章号对不对——证明产品的章号是对的(demo 那份是化石,见
memory project_demo_fixtures_stale)。

用法: python -X utf8 scripts/run_analysis_log.py [书名关键字，默认 三国]
需 DEEPSEEK_API_KEY(import bookscope 时从 .env 自动加载)。会真花 DeepSeek。
"""

from __future__ import annotations

import datetime as dt
import glob
import json
import os
import sys
import time
from pathlib import Path

from bookscope.agent.narrative_curve import generate_narrative_curve_exhaustive
from bookscope.api.dependencies import build_llm_client_from_params, default_model_for
from bookscope.ingest.book_chunker import chunk_book_with_stats
from bookscope.ingest.loader import load_text

OUT_DIR = Path("docs/internal/experiments/runs")


def _band(t: int) -> str:
    if t >= 8:
        return "高潮"
    if t >= 6:
        return "紧张"
    if t >= 4:
        return "起伏"
    return "平缓"


def main() -> None:
    kw = sys.argv[1] if len(sys.argv) > 1 else "三国"
    matches = glob.glob(f"tests/file/*{kw}*")
    if not matches:
        print(f"没找到含「{kw}」的测试书")
        return
    path = matches[0]
    print(f"[book] {path}")
    book = load_text(path, title=kw)
    chunk_res, stats = chunk_book_with_stats(book)
    chunks = [
        {"chunk_id": f"r0-chunk-{c.index}", "chapter": c.chapter, "text": c.text}
        for c in chunk_res
    ]
    print(f"[ingest] {len(chunks)} chunk, 检出 {stats.chapters_detected} 章")

    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        print("DEEPSEEK_API_KEY 没加载到")
        return
    client = build_llm_client_from_params(provider="deepseek", api_key=key)
    model = default_model_for("deepseek")
    print(f"[model] {model} —— 真跑叙事曲线(穷尽化、全章),稍候…")

    t0 = time.monotonic()
    chapters = generate_narrative_curve_exhaustive(chunks=chunks, llm_client=client, model=model)
    dt_s = time.monotonic() - t0
    if not chapters:
        print(f"[结果] 没抽出来(用时 {dt_s:.0f}s)")
        return
    print(f"[结果] {len(chapters)} 章,用时 {dt_s:.0f}s")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    stem = f"narrative_{kw}_{ts}"
    (OUT_DIR / f"{stem}.json").write_text(
        json.dumps({"book": path, "model": model, "elapsed_s": round(dt_s, 1),
                    "chapters": chapters}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    # 可读 .md 表
    lines = [
        f"# 叙事曲线 live 跑 · {kw} · {ts}",
        f"- 书: `{path}`  模型: `{model}`  用时: {dt_s:.0f}s  覆盖: {len(chapters)} 章",
        "",
        "| 章 | 张力 | 档 | 情感 | 视角 | 主/支 | 核验 | 原文(截断) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for c in chapters:
        ev = (c.get("evidence") or "").replace("|", "｜")[:42]
        lines.append(
            f"| {c.get('chapter')} | {c.get('tension')} | {_band(int(c.get('tension', 0)))} "
            f"| {c.get('sentiment')} | {c.get('pov')} | {'主' if c.get('mainline') else '支'} "
            f"| {'✓' if c.get('verified') else '×'} | {ev} |"
        )
    (OUT_DIR / f"{stem}.md").write_text("\n".join(lines), encoding="utf-8")

    # 抽查作者的两个例子
    def _probe(label: str, keys: list[str]) -> None:
        hit = [c for c in chapters if any(k in (c.get("evidence") or "") for k in keys)]
        if hit:
            chs_hit = [h.get("chapter") for h in hit]
            print(f"  [抽查] {label}: chapter {chs_hit} | {hit[0].get('evidence', '')[:40]!r}")
        else:
            print(f"  [抽查] {label}: 这次抽到的章里没命中(可能这段没被选为代表证据)")

    print("抽查(看产品章号对不对):")
    _probe("卖草鞋(应回1)", ["草鞋", "织席", "贩屦"])
    _probe("负天下人(应回4)", ["负天下人"])
    chs = [c.get("chapter") for c in chapters]
    print(f"[章号] 范围 {min(chs)}..{max(chs)},共 {len(chs)} 章")
    print(f"\n[存档] {OUT_DIR / (stem + '.md')}\n[存档] {OUT_DIR / (stem + '.json')}")


if __name__ == "__main__":
    main()
