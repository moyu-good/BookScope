"""exp029 · 卷层路由 probe:全局功能从"喂整本书"改成"卷层定位相关卷 → 只喂相关卷原文",
recall 掉不掉、token 省多少。样板 = 母题追踪(motif,现在整本进 context 且关缓存,是最贵的一类)。

**依托**:研究笔记 012(RAPTOR 层级检索)+ 013(prior-art:借 RAPTOR 分层、按结构不按 embedding、
轻量)+ `chapter_arcs.py`(卷层已建、exp021 GO 切得准、全局 input 省 6.4×)。

**设计洞(读码得出,写进 WP 卷层 B)**:evidence-first 功能要逐字原文,卷层(只有骨架、无原文)
**不能"代替读原文",只能"路由"**——用卷的 title/theme/key_events 判哪几卷跟母题相关,只把那几卷
成员章的原文喂进去,不喂整本。这是卷层对"整本重读一遍"这类功能(母题 / 一致性 / 实体回溯 / 时间线)
的真价值。

**方法(三国,≥40 章才有卷层)**:
- 建章脉(`get_or_build_spine`,缓存开、一次性)→ 建卷层(`build_arc_layer`)。
- 每个母题两条臂:
  A 基线(现状):`generate_motif_tracking` 全书原文进 context。
  B 卷层路由:一次小调用让 LLM 据卷摘要选"相关卷"(召回优先、宁多勿漏)→ 收集这些卷跨度内的章
    原文 → 只把这个子集喂给**同一个**母题抽取。
- 比:① recall(A 找到复现的章集合,B 覆盖了多少)② input token(A 全本 vs B 路由+子集)。

**go/no-go**:B 省大量 input 且 recall 不明显掉(找回 A 绝大多数复现章)→ 卷层路由对全局功能成立,
去把"整本重读"类功能改成卷层路由。掉太多 = 卷摘要不够路由,记根因。

公开书三国,flash,key 从 .env,不 commit、不动生产。
用法: python -X utf8 scripts/probe_arc_routing.py
"""

from __future__ import annotations

import datetime as dt
import glob
import json
import os
import sys
from pathlib import Path
from typing import Any

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import bookscope.agent.chapter_arcs as _arc_mod  # noqa: E402
import bookscope.agent.motif_tracking as _motif_mod  # noqa: E402
from bookscope.agent._internal.chapter_spine_cache import get_or_build_spine  # noqa: E402
from bookscope.agent.chapter_arcs import build_arc_layer  # noqa: E402
from bookscope.agent.motif_tracking import generate_motif_tracking  # noqa: E402
from bookscope.agent.utils.json_parsing import (  # noqa: E402
    extract_first_json_object as _extract_first_json_object,
)
from bookscope.agent.utils.json_parsing import strip_code_fence as _strip_code_fence  # noqa: E402
from bookscope.api.dependencies import (  # noqa: E402
    build_llm_client_from_params,
    default_model_for,
)
from bookscope.ingest.book_chunker import chunk_book_with_stats  # noqa: E402
from bookscope.ingest.loader import load_text  # noqa: E402
from scripts.probe_dim_merge import _Tracker  # noqa: E402 — 复用 input/output token 计数器

OUT_DIR = _ROOT / "docs" / "internal" / "experiments" / "runs"

# 三国上明确复现、且分布在不同段落的母题(测路由能不能把散在各卷的复现都圈到)。
_MOTIFS = ["火攻", "忠义"]

_ROUTE_INSTR = (
    "下面是一本书的**分卷摘要**(每卷:卷号 / 章跨度 / 卷名 / 主题 / 关键事件)。"
    "用户要追一个母题在全书的复现。请判断**哪几个卷可能含这个母题**(据卷的主题 / 事件),"
    "返回这些卷的卷号。**召回优先:宁可多选一两卷,别漏**(漏了那卷的复现就永远找不回)。\n"
    '严格输出 JSON(别的话别说、别加围栏):{"volumes":[卷号整数,...]}'
)


def _arc_summary_text(arcs: list[dict[str, Any]]) -> str:
    """把卷层压成给路由用的分卷摘要(卷号 + 跨度 + 名 + 主题 + 事件,无原文)。"""
    lines: list[str] = []
    for i, v in enumerate(arcs, start=1):
        span = v.get("chapter_span") or [0, 0]
        events = "；".join(str(e) for e in (v.get("key_events") or [])[:4])
        lines.append(
            f"卷{i} [第{span[0]}-{span[1]}章] {v.get('title', '')} | "
            f"主题:{v.get('theme', '')} | 事件:{events}"
        )
    return "\n".join(lines)


def _parse_selected(text: str, n_arcs: int) -> list[int]:
    """从路由输出抠 {"volumes":[...]},返 1-based 卷号里的合法项(去重升序)。"""
    raw = _strip_code_fence((text or "").strip())
    obj: Any = None
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        sliced = _extract_first_json_object(raw)
        if sliced:
            try:
                obj = json.loads(sliced)
            except json.JSONDecodeError:
                obj = None
    if not isinstance(obj, dict):
        return []
    vols = obj.get("volumes")
    if not isinstance(vols, list):
        return []
    return sorted({v for v in vols if isinstance(v, int) and 1 <= v <= n_arcs})


def _chapters_of(arcs: list[dict[str, Any]], selected: list[int]) -> set[int]:
    """选中卷号(1-based)→ 覆盖的章号集合。"""
    chs: set[int] = set()
    for i in selected:
        span = arcs[i - 1].get("chapter_span") or []
        if len(span) == 2 and isinstance(span[0], int) and isinstance(span[1], int):
            chs.update(range(span[0], span[1] + 1))
    return chs


def _occ_chapters(occ: list[dict[str, Any]] | None) -> set[int]:
    """一组母题复现 → 命中的章集合(0/非整数章号忽略)。"""
    if not occ:
        return set()
    return {o["chapter"] for o in occ if isinstance(o.get("chapter"), int) and o["chapter"] > 0}


def main() -> int:
    kw = "三国"
    matches = glob.glob(str(_ROOT / "tests" / "file" / f"*{kw}*"))
    if not matches:
        print(f"没找到含「{kw}」的测试书", file=sys.stderr)
        return 1
    path = matches[0]
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        print("DEEPSEEK_API_KEY 没加载到", file=sys.stderr)
        return 1

    book = load_text(path, title=kw)
    chunk_res, _ = chunk_book_with_stats(book)
    chunks = [
        {"chunk_id": f"r0-chunk-{c.index}", "chapter": c.chapter, "text": c.text}
        for c in chunk_res
    ]
    full_text = "".join(c["text"] for c in chunks)
    client = build_llm_client_from_params(provider="deepseek", api_key=key)
    model = default_model_for("deepseek")
    print(f"[book] {Path(path).name} / {len(chunks)} chunk / {len(full_text)} 字符")
    print(f"[model] {model}\n")

    # ── 一次性:建章脉(缓存开,后续 probe 复用)→ 建卷层 ──
    _orig_motif_invoke = _motif_mod._invoke_client
    _orig_arc_invoke = _arc_mod.invoke_client_cached
    print("[setup] 建 / 取章脉(缓存开)…")
    spine = get_or_build_spine(chunks=chunks, llm_client=client, model=model, genre="fiction")
    print(f"[setup] 章脉 {len(spine)} 章;建卷层…")
    arc_tracker = _Tracker()
    _arc_mod.invoke_client_cached = arc_tracker.wrapped
    try:
        arcs = build_arc_layer(spine=spine, llm_client=client, model=model)
    finally:
        _arc_mod.invoke_client_cached = _orig_arc_invoke
    if not arcs:
        print("[setup] 卷层返 None(短书?),本 probe 需要 ≥40 章的书", file=sys.stderr)
        return 1
    arc_build = arc_tracker.snap()
    print(
        f"[setup] 卷层 {len(arcs)} 卷(一次性建卷 input={arc_build['input_tokens']} "
        f"output={arc_build['output_tokens']}),各卷:"
    )
    for i, v in enumerate(arcs, start=1):
        span = v.get("chapter_span") or [0, 0]
        print(f"  卷{i} [第{span[0]}-{span[1]}章] {v.get('title', '')}")
    arc_text = _arc_summary_text(arcs)

    recs: list[dict[str, Any]] = []
    for motif in _MOTIFS:
        print(f"\n=== 母题「{motif}」===")

        # A 基线:整本进 context
        ta = _Tracker()
        _motif_mod._invoke_client = ta.wrapped
        try:
            occ_a = generate_motif_tracking(
                motif=motif, full_text=full_text, chunks=chunks, llm_client=client, model=model
            )
        finally:
            _motif_mod._invoke_client = _orig_motif_invoke
        ca = ta.snap()
        chs_a = _occ_chapters(occ_a)
        print(
            f"[A 整本] 复现{len(occ_a or [])}处 / 命中章{sorted(chs_a)} | "
            f"input={ca['input_tokens']}"
        )

        # B 卷层路由:选相关卷 → 只喂子集
        tb = _Tracker()
        _motif_mod._invoke_client = tb.wrapped
        try:
            resp = tb.wrapped(
                client, model=model,
                system=_ROUTE_INSTR + "\n\n=== 分卷摘要 ===\n" + arc_text,
                tools=[], messages=[{"role": "user", "content": f"母题「{motif}」相关的是哪几卷?"}],
                max_tokens=1000, cache_enabled=False,
            )
            selected = _parse_selected(client.extract_final_text(resp), len(arcs))
            sel_chapters = _chapters_of(arcs, selected)
            sub_chunks = [c for c in chunks if c["chapter"] in sel_chapters]
            sub_text = "".join(c["text"] for c in sub_chunks)
            occ_b = generate_motif_tracking(
                motif=motif, full_text=sub_text, chunks=sub_chunks, llm_client=client, model=model
            )
        finally:
            _motif_mod._invoke_client = _orig_motif_invoke
        cb = tb.snap()
        chs_b = _occ_chapters(occ_b)
        recall = round(len(chs_a & chs_b) / len(chs_a), 3) if chs_a else 1.0
        ia, ib = ca["input_tokens"], cb["input_tokens"]
        saved = round((1 - ib / ia) * 100, 1) if ia else 0.0
        print(
            f"[B 路由] 选卷{selected}(={len(sel_chapters)}章 / 全书{len(chunks)}chunk)→ "
            f"复现{len(occ_b or [])}处 / 命中章{sorted(chs_b)}"
        )
        print(f"[比] recall={recall} | input {ia}→{ib}(省 {saved}%) | 漏章={sorted(chs_a - chs_b)}")
        recs.append({
            "motif": motif, "selected_volumes": selected,
            "A_occ": len(occ_a or []), "B_occ": len(occ_b or []),
            "A_chapters": sorted(chs_a), "B_chapters": sorted(chs_b),
            "recall": recall, "input_A": ca["input_tokens"], "input_B": cb["input_tokens"],
            "input_saved_pct": saved, "missed_chapters": sorted(chs_a - chs_b),
        })

    print("\n" + "=" * 66)
    print("卷层路由核验(母题样板):")
    for r in recs:
        print(
            f"  「{r['motif']}」recall={r['recall']} 省input={r['input_saved_pct']}% "
            f"漏{len(r['missed_chapters'])}章"
        )
    print("=" * 66)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = OUT_DIR / f"probe_arc_routing_{kw}_{ts}.json"
    out.write_text(
        json.dumps(
            {
                "probe": "exp029-arc-routing", "book": Path(path).name, "model": model,
                "n_chunks": len(chunks), "n_arcs": len(arcs),
                "arc_build_input": arc_build["input_tokens"], "records": recs,
            },
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n[存档] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
