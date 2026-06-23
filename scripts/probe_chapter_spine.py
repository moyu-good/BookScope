"""ADR-010 D-3 probe:章脉抽取「全维一趟」vs「分维多趟」—— 量截断率 / 覆盖 / 质量。

对同样几段原文,跑两种抽取方式,每段记:finish_reason(length=被 max_tokens 截断)、
输出 token、解析出几章。质量:全维抽的张力/视角,拿分维(情节维)同章的值比,看挤进
8 维一趟会不会跟专注抽的分维背离。短章网文一段塞十几二十章、最容易爆,默认靶子《亏成首富》。

结论喂给 ADR-010 D-3:全维一趟够不够(截断率/质量可接受),还是必须分维多趟。

用法: python -X utf8 scripts/probe_chapter_spine.py [书关键字，默认 亏成首富] [段数，默认 4]
需 DEEPSEEK_API_KEY(import bookscope 从 .env 自动加载)。会真花 DeepSeek(段数 × 3 次调用)。
"""

from __future__ import annotations

import datetime as dt
import glob
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from bookscope.agent._internal.exhaustive import segment_chunks
from bookscope.agent._internal.longctx_system import build_longctx_system
from bookscope.agent._internal.llm_cache import invoke_client_cached
from bookscope.api.dependencies import build_llm_client_from_params, default_model_for
from bookscope.ingest.book_chunker import chunk_book_with_stats
from bookscope.ingest.loader import load_text

OUT_DIR = Path("docs/internal/experiments/runs")
MAX_TOKENS = 8000  # 跟现有穷尽化功能一致

# ── 全维一趟:8 维一次抽 ───────────────────────────────────────────────────
INSTR_ALL = (
    "你在给一本书做逐章结构化精读。只针对下面这段原文,逐章抽出结构,只抽本段出现的章。"
    "每章给:在场人物 present[]、关键事件 events[]、张力 tension(0-10 整数)、情感方向 "
    "sentiment(-5..5)、主导视角 pov、触及的人物关系对 relations[]([{pair:[a,b],note}])、"
    "伏笔候选 foreshadow[]([{type:埋|收,hook}])、人物处境 char_states[]([{name,state}])。"
    "每章挂一条最能代表本章的原文片段 evidence(逐字)。"
    '只输出 JSON:{"chapters":[{"chapter":int,"present":[],"events":[],"tension":int,'
    '"sentiment":int,"pov":"","relations":[],"foreshadow":[],"char_states":[],"evidence":""}]}'
)

# ── 分维:人物维 ───────────────────────────────────────────────────────────
INSTR_CHAR = (
    "你在给一本书做逐章人物精读。只针对下面这段原文,逐章抽,只抽本段出现的章。"
    "每章给:在场人物 present[]、触及的人物关系对 relations[]([{pair:[a,b],note}])、"
    "人物处境 char_states[]([{name,state}])。每章挂一条代表性原文片段 evidence(逐字)。"
    '只输出 JSON:{"chapters":[{"chapter":int,"present":[],"relations":[],"char_states":[],"evidence":""}]}'
)

# ── 分维:情节维 ───────────────────────────────────────────────────────────
INSTR_PLOT = (
    "你在给一本书做逐章情节精读。只针对下面这段原文,逐章抽,只抽本段出现的章。"
    "每章给:关键事件 events[]、张力 tension(0-10 整数)、情感方向 sentiment(-5..5)、"
    "主导视角 pov、伏笔候选 foreshadow[]([{type:埋|收,hook}])。"
    "每章挂一条代表性原文片段 evidence(逐字)。"
    '只输出 JSON:{"chapters":[{"chapter":int,"events":[],"tension":int,"sentiment":int,'
    '"pov":"","foreshadow":[],"evidence":""}]}'
)

USER_MSG = "请按上面的要求,只对这段原文逐章抽结构。"


def _parse_chapters(text: str) -> list[dict[str, Any]]:
    """宽容解析:截出第一个 { 到最后一个 },取 chapters 数组;失败返 []。"""
    if not text:
        return []
    s = text.find("{")
    e = text.rfind("}")
    if s < 0 or e <= s:
        return []
    try:
        obj = json.loads(text[s : e + 1])
        chs = obj.get("chapters", [])
        return [c for c in chs if isinstance(c, dict)]
    except Exception:
        return []


def _call(client: Any, model: str, seg_text: str, instruction: str) -> dict[str, Any]:
    """跑一段一种抽取,返 finish_reason / 输出 token / 解析出的章。关缓存看真实截断。"""
    system = build_longctx_system(seg_text, instruction)
    resp = invoke_client_cached(
        client, model=model, system=system, tools=[],
        messages=[{"role": "user", "content": USER_MSG}],
        max_tokens=MAX_TOKENS, cache_enabled=False,
    )
    text = client.extract_final_text(resp)
    _, completion = client.extract_usage_tokens(resp)
    finish = "stop"
    try:
        finish = resp["choices"][0].get("finish_reason", "stop")
    except Exception:
        pass
    chapters = _parse_chapters(text)
    return {"finish": finish, "out_tokens": completion, "n_chapters": len(chapters), "chapters": chapters}


def main() -> None:
    kw = sys.argv[1] if len(sys.argv) > 1 else "亏成首富"
    n_seg = int(sys.argv[2]) if len(sys.argv) > 2 else 4
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
    segments = segment_chunks(chunks)  # 默认 40000 字/段,跟生产一致
    print(f"[ingest] {len(chunks)} chunk, 检出 {stats.chapters_detected} 章, 切成 {len(segments)} 段")
    segments = segments[:n_seg]
    print(f"[probe] 取前 {len(segments)} 段做对照")

    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        print("DEEPSEEK_API_KEY 没加载到")
        return
    client = build_llm_client_from_params(provider="deepseek", api_key=key)
    model = default_model_for("deepseek")
    print(f"[model] {model}\n")

    rows = []
    for i, seg in enumerate(segments):
        seg_text = "".join(str(c.get("text", "")) for c in seg)
        seg_chars = len(seg_text)
        t0 = time.monotonic()
        a = _call(client, model, seg_text, INSTR_ALL)
        b_char = _call(client, model, seg_text, INSTR_CHAR)
        b_plot = _call(client, model, seg_text, INSTR_PLOT)
        dt_s = time.monotonic() - t0

        # 质量:全维 vs 情节维 同章张力差(分维更专注,当参照)
        a_t = {c.get("chapter"): c.get("tension") for c in a["chapters"] if isinstance(c.get("tension"), int)}
        p_t = {c.get("chapter"): c.get("tension") for c in b_plot["chapters"] if isinstance(c.get("tension"), int)}
        common = [ch for ch in a_t if ch in p_t]
        tens_diff = (sum(abs(a_t[ch] - p_t[ch]) for ch in common) / len(common)) if common else None

        row = {
            "seg": i, "seg_chars": seg_chars,
            "all": {"finish": a["finish"], "out_tokens": a["out_tokens"], "n_ch": a["n_chapters"]},
            "char_dim": {"finish": b_char["finish"], "out_tokens": b_char["out_tokens"], "n_ch": b_char["n_chapters"]},
            "plot_dim": {"finish": b_plot["finish"], "out_tokens": b_plot["out_tokens"], "n_ch": b_plot["n_chapters"]},
            "tension_mean_abs_diff": round(tens_diff, 2) if tens_diff is not None else None,
            "common_chapters": len(common),
            "_raw": {"all": a["chapters"], "char": b_char["chapters"], "plot": b_plot["chapters"]},
        }
        rows.append(row)
        print(
            f"段{i} ({seg_chars}字): "
            f"全维[{a['finish']:>6} out={a['out_tokens']:>4} {a['n_chapters']:>2}章] | "
            f"人物维[{b_char['finish']:>6} out={b_char['out_tokens']:>4} {b_char['n_chapters']:>2}章] | "
            f"情节维[{b_plot['finish']:>6} out={b_plot['out_tokens']:>4} {b_plot['n_chapters']:>2}章] | "
            f"张力均差={row['tension_mean_abs_diff']} (共{len(common)}章) | {dt_s:.0f}s"
        )

    # 汇总
    def _trunc_rate(key: str) -> str:
        n = sum(1 for r in rows if r[key]["finish"] == "length")
        return f"{n}/{len(rows)}"

    print("\n=== 汇总 ===")
    print(f"截断率(finish=length): 全维 {_trunc_rate('all')} · 人物维 {_trunc_rate('char_dim')} · 情节维 {_trunc_rate('plot_dim')}")
    all_ch = sum(r["all"]["n_ch"] for r in rows)
    plot_ch = sum(r["plot_dim"]["n_ch"] for r in rows)
    print(f"覆盖(总抽出章数): 全维 {all_ch} · 情节维 {plot_ch}")
    diffs = [r["tension_mean_abs_diff"] for r in rows if r["tension_mean_abs_diff"] is not None]
    if diffs:
        print(f"质量(全维 vs 情节维张力均差,越小越一致): {round(sum(diffs)/len(diffs), 2)} 平均")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = OUT_DIR / f"probe_chapter_spine_{kw}_{ts}.json"
    out.write_text(
        json.dumps({"book": path, "model": model, "max_tokens": MAX_TOKENS, "rows": rows},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n[存档] {out}")


if __name__ == "__main__":
    main()
