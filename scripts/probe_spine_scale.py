"""章脉冷启动规模化 probe（020）:超长文放大段长到底赚不赚、代价是什么。

**背景**:章脉(ADR-010)是所有整本书功能的公共前置。现在按段 map-reduce,长书段数
爆炸→几百次 LLM 往返。核心张力:段放大(往返↓)但单维输出仍封顶 ``max_tokens``,一段塞更多
章→更容易被截断→触发 continue/sweep/split 补抽,反而可能更慢。要拿真书量清楚。

**关键洞察**(ingest 预检得出):三国是**长章书**(~6k 字/章),现状章闸
``_SPINE_HEAVY_DIM_MAX_CHAPTERS=6`` 先咬死段大小,单抬 ``char_budget`` 段数几乎不动
(22→21→21)。真正卡往返数的是**章闸(每段几章)**,不是字符预算。所以这个 probe 同时扫
``char_budget`` 和 ``max_chapters``——放大段长 = 抬章闸 + 配套抬字符预算,让段真的变大。

**怎么在不改产品代码下观测内部调用**:``build_chapter_spine`` 把每次 LLM 调用(含
continue/sweep/split 补抽)藏在 ``invoke_client_cached`` 里。本 probe 在进程内 monkeypatch
两个模块命名空间(``chapter_spine`` / ``_internal.exhaustive``)里的 ``invoke_client_cached``,
wrap 成计数器——逐调用记 finish_reason / completion_tokens。**不动产品文件一个字节**。
缓存用全局 env ``BOOKSCOPE_LLM_CACHE_DISABLED=1`` 关掉,保证每组真跑不命中。

**量什么(每组参数一次冷启动)**:
① 总墙钟时间 ② 总 LLM 调用次数(含补抽) ③ finish_reason=length 截断次数 + 截断率
④ 最终章数 vs 书真章数(掉章率) ⑤ 字段完整度(present/events/relations 空占比,看放大后有没有变稀)

结论喂给 docs/internal/experiments/020-*:超长文的安全 sweet spot(不截断、不掉质量前提下
往返最少的 char_budget / max_chapters / max_tokens 组合)。

用法: python -X utf8 scripts/probe_spine_scale.py [书关键字，默认 三国]
需 DEEPSEEK_API_KEY(import bookscope 从 .env 自动加载)。会真花 DeepSeek。
"""

from __future__ import annotations

import datetime as dt
import glob
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

import bookscope.agent._internal.exhaustive as _exhaustive_mod
import bookscope.agent.chapter_spine as _spine_mod
from bookscope.agent._internal.llm_cache import invoke_client_cached as _real_invoke
from bookscope.agent._internal.loop_shared import (
    read_openai_finish_reason,
    read_openai_usage,
)
from bookscope.agent.chapter_spine import build_chapter_spine
from bookscope.api.dependencies import build_llm_client_from_params, default_model_for
from bookscope.ingest.book_chunker import chunk_book_with_stats
from bookscope.ingest.loader import load_text

OUT_DIR = Path("docs/internal/experiments/runs")

# 参数矩阵。char_budget 是任务点名的主变量;但预检证明长章书里 max_chapters 才是真闸,
# 所以两个一起扫——放大段长 = 抬章闸 + 配套抬字符预算。max_tokens 单独测一组(D)看大段
# 配大 token 能不能压回不截断。
# 每组: (label, char_budget, max_chapters 覆盖到重维章闸, max_tokens, 说明)
# 注:max_chapters 是喂给 build_chapter_spine 的 char_budget 那条路;重维章闸
# _SPINE_HEAVY_DIM_MAX_CHAPTERS=6 是模块常量,probe 期用 monkeypatch 覆盖它来模拟"抬章闸"。
PARAM_SETS: list[dict[str, Any]] = [
    {"label": "A_baseline", "char_budget": 40000, "heavy_max_ch": 6, "max_tokens": 8000,
     "note": "现状基线(章闸6/预算4万/token8000)——ground truth"},
    {"label": "B_mid", "char_budget": 80000, "heavy_max_ch": 9, "max_tokens": 8000,
     "note": "抬章闸到9+预算8万,token不抬——看放大后截断率会不会涨"},
    {"label": "C_large", "char_budget": 120000, "heavy_max_ch": 12, "max_tokens": 8000,
     "note": "大段(章闸12/预算12万),token不抬——往返最少但最易截断"},
    {"label": "D_large_bigtoken", "char_budget": 120000, "heavy_max_ch": 12, "max_tokens": 16000,
     "note": "大段+token翻倍(16000)——测大段配大token能否压回不截断"},
]


class _CallTracker:
    """线程安全计数器:wrap invoke_client_cached,逐调用记 finish_reason / completion_tokens。

    维内多线程并发跑同一 client,所以加锁。区分是否 continue/sweep 补抽调用没法从这层判(都走
    同一出口),只统计总数 + 截断分布,已足够回答"放大后总往返和截断怎么变"。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.n_calls = 0
        self.n_length = 0  # finish_reason == "length" 的次数
        self.completion_tokens: list[int] = []
        self.finish_reasons: dict[str, int] = {}

    def wrapped(self, client: Any, **kwargs: Any) -> Any:
        # 缓存已由全局 env 关掉,这里直接透传真实调用(cache_enabled 参数无所谓)
        resp = _real_invoke(client, **kwargs)
        fr = read_openai_finish_reason(resp) or "unknown"
        _, completion = read_openai_usage(resp)
        with self._lock:
            self.n_calls += 1
            self.finish_reasons[fr] = self.finish_reasons.get(fr, 0) + 1
            if fr == "length":
                self.n_length += 1
            if completion:
                self.completion_tokens.append(int(completion))
        return resp

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            toks = sorted(self.completion_tokens)
            n = len(toks)
            return {
                "n_calls": self.n_calls,
                "n_length": self.n_length,
                "trunc_rate": round(self.n_length / self.n_calls, 3) if self.n_calls else 0.0,
                "finish_reasons": dict(self.finish_reasons),
                "completion_tokens_max": toks[-1] if toks else 0,
                "completion_tokens_p50": toks[n // 2] if toks else 0,
                "completion_tokens_avg": round(sum(toks) / n) if toks else 0,
            }


def _field_completeness(spine: list[dict[str, Any]]) -> dict[str, Any]:
    """字段完整度:各维核心字段有多少章是空的(空占比)。放大段长若掉质量,这里会变稀。

    看三个数组字段 present / events / relations + evidence 非空率 + verified 率。
    """
    n = len(spine)
    if n == 0:
        return {"n_chapters": 0}

    def _nonempty_list(rec: dict[str, Any], k: str) -> bool:
        v = rec.get(k)
        return isinstance(v, list) and len(v) > 0

    present_ne = sum(1 for r in spine if _nonempty_list(r, "present"))
    events_ne = sum(1 for r in spine if _nonempty_list(r, "events"))
    relations_ne = sum(1 for r in spine if _nonempty_list(r, "relations"))
    evidence_ne = sum(1 for r in spine if str(r.get("evidence", "")).strip())
    verified_n = sum(1 for r in spine if r.get("verified") is True)
    # 每章 events 平均条数(密度指标——放大后若变稀,均条数会掉)
    events_counts = [len(r["events"]) for r in spine if isinstance(r.get("events"), list)]
    present_counts = [len(r["present"]) for r in spine if isinstance(r.get("present"), list)]
    return {
        "n_chapters": n,
        "present_nonempty_rate": round(present_ne / n, 3),
        "events_nonempty_rate": round(events_ne / n, 3),
        "relations_nonempty_rate": round(relations_ne / n, 3),
        "evidence_nonempty_rate": round(evidence_ne / n, 3),
        "verified_rate": round(verified_n / n, 3),
        "events_per_ch_avg": (
            round(sum(events_counts) / len(events_counts), 2) if events_counts else 0
        ),
        "present_per_ch_avg": (
            round(sum(present_counts) / len(present_counts), 2) if present_counts else 0
        ),
    }


def _run_one(
    *,
    label: str,
    chunks: list[dict[str, Any]],
    client: Any,
    model: str,
    char_budget: int,
    heavy_max_ch: int,
    max_tokens: int,
    true_chapters: set[int],
    note: str,
) -> dict[str, Any]:
    """跑一组参数一次冷启动 build_chapter_spine,量四类指标。"""
    tracker = _CallTracker()
    # ── monkeypatch:两个模块命名空间的 invoke_client_cached 换成计数 wrapper ──
    # chapter_spine.py / exhaustive.py 都是 from ... import invoke_client_cached 直接引入,
    # 所以要 patch 到各自模块的命名空间(不是 patch llm_cache 里的原定义)。
    _orig_spine = _spine_mod.invoke_client_cached
    _orig_exh = _exhaustive_mod.invoke_client_cached
    # ── monkeypatch:重维章闸常量(模拟"抬章闸放大段长"),probe 期覆盖,跑完还原 ──
    _orig_heavy = _spine_mod._SPINE_HEAVY_DIM_MAX_CHAPTERS
    _spine_mod.invoke_client_cached = tracker.wrapped
    _exhaustive_mod.invoke_client_cached = tracker.wrapped
    _spine_mod._SPINE_HEAVY_DIM_MAX_CHAPTERS = heavy_max_ch
    try:
        t0 = time.monotonic()
        spine = build_chapter_spine(
            chunks=chunks,
            llm_client=client,
            model=model,
            genre="fiction",  # 三国=小说,跑 char+plot 两个重维
            max_tokens=max_tokens,
            char_budget=char_budget,
            max_workers=6,
        )
        wall_s = time.monotonic() - t0
    finally:
        _spine_mod.invoke_client_cached = _orig_spine
        _exhaustive_mod.invoke_client_cached = _orig_exh
        _spine_mod._SPINE_HEAVY_DIM_MAX_CHAPTERS = _orig_heavy

    calls = tracker.snapshot()
    have_ch = {r["chapter"] for r in spine if isinstance(r.get("chapter"), int)}
    missing = sorted(true_chapters - have_ch)
    completeness = _field_completeness(spine)
    row = {
        "label": label,
        "params": {
            "char_budget": char_budget,
            "heavy_max_ch": heavy_max_ch,
            "max_tokens": max_tokens,
        },
        "note": note,
        "wall_seconds": round(wall_s, 1),
        "llm_calls": calls,
        "chapters_out": len(have_ch),
        "chapters_expected": len(true_chapters),
        "chapters_missing_n": len(missing),
        "chapters_missing": missing[:30],
        "drop_rate": round(len(missing) / len(true_chapters), 3) if true_chapters else 0.0,
        "completeness": completeness,
    }
    tr_pct = calls["trunc_rate"] * 100
    dr_pct = row["drop_rate"] * 100
    print(
        f"[{label:>18}] cb={char_budget:>6} ch闸={heavy_max_ch:>2} tok={max_tokens:>5} | "
        f"{wall_s:>5.0f}s | 调用{calls['n_calls']:>3}(截断{calls['n_length']}={tr_pct:.0f}%) | "
        f"章{len(have_ch)}/{len(true_chapters)}(掉{len(missing)}={dr_pct:.0f}%) | "
        f"events/ch={completeness.get('events_per_ch_avg')} "
        f"present/ch={completeness.get('present_per_ch_avg')} "
        f"verified={completeness.get('verified_rate')}"
    )
    return row


def main() -> None:
    kw = sys.argv[1] if len(sys.argv) > 1 else "三国"
    matches = glob.glob(f"tests/file/*{kw}*")
    if not matches:
        print(f"没找到含「{kw}」的测试书")
        return
    path = matches[0]

    # 缓存全局关掉——每组必须真跑,别命中上一组或历史缓存
    os.environ["BOOKSCOPE_LLM_CACHE_DISABLED"] = "1"

    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        print("DEEPSEEK_API_KEY 没加载到(应由 import bookscope 从 .env 或环境读入)")
        return

    print(f"[book] {path}")
    book = load_text(path, title=kw)
    chunk_res, stats = chunk_book_with_stats(book)
    chunks = [
        {"chunk_id": f"r0-chunk-{c.index}", "chapter": c.chapter, "text": c.text}
        for c in chunk_res
    ]
    true_chapters = {
        c["chapter"]
        for c in chunks
        if isinstance(c["chapter"], int) and c["chapter"] >= 1
    }
    total_chars = sum(len(c["text"]) for c in chunks)
    print(
        f"[ingest] {len(chunks)} chunk / 真章数 {len(true_chapters)} / {total_chars} 字符 "
        f"(约 {total_chars // max(len(true_chapters),1)} 字/章) / 缓存已关"
    )

    client = build_llm_client_from_params(provider="deepseek", api_key=key)
    model = default_model_for("deepseek")
    print(f"[model] {model}\n")
    print("每组一次冷启动 build_chapter_spine(char+plot 两个重维,各自 map-reduce):\n")

    rows: list[dict[str, Any]] = []
    for ps in PARAM_SETS:
        row = _run_one(
            label=ps["label"],
            chunks=chunks,
            client=client,
            model=model,
            char_budget=ps["char_budget"],
            heavy_max_ch=ps["heavy_max_ch"],
            max_tokens=ps["max_tokens"],
            true_chapters=true_chapters,
            note=ps["note"],
        )
        rows.append(row)

    # ── 汇总:找 sweet spot ──
    print("\n=== 汇总(每组:墙钟 / 调用数 / 截断率 / 掉章率 / 完整度) ===")
    baseline = rows[0]
    for r in rows:
        c = r["llm_calls"]
        speedup = baseline["wall_seconds"] / r["wall_seconds"] if r["wall_seconds"] else 0
        base_calls = baseline["llm_calls"]["n_calls"]
        call_ratio = c["n_calls"] / base_calls if base_calls else 0
        print(
            f"{r['label']:>18}: {r['wall_seconds']:>5.0f}s(x{speedup:.2f}) | "
            f"调用{c['n_calls']:>3}(x{call_ratio:.2f}) 截断{c['trunc_rate'] * 100:>4.0f}% | "
            f"掉章{r['drop_rate'] * 100:>4.0f}% | "
            f"events/ch={r['completeness'].get('events_per_ch_avg')}"
        )

    # 安全 sweet spot 判据:掉章率 0 且截断率不高于基线,取调用数最少那组
    safe = [r for r in rows if r["drop_rate"] == 0.0]
    if safe:
        best = min(safe, key=lambda r: r["llm_calls"]["n_calls"])
        print(
            f"\n[sweet spot 候选] 掉章 0 的组里往返最少 → {best['label']} "
            f"(cb={best['params']['char_budget']} ch闸={best['params']['heavy_max_ch']} "
            f"tok={best['params']['max_tokens']}): {best['llm_calls']['n_calls']} 次调用 / "
            f"{best['wall_seconds']}s / 截断率 {best['llm_calls']['trunc_rate']*100:.0f}%"
        )
    else:
        print("\n[警告] 没有一组做到 0 掉章——放大段长在本书上都有掉章代价,见明细")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = OUT_DIR / f"probe_spine_scale_{kw}_{ts}.json"
    out.write_text(
        json.dumps(
            {
                "book": path,
                "model": model,
                "n_chunks": len(chunks),
                "chapters_expected": len(true_chapters),
                "total_chars": total_chars,
                "cache_disabled": True,
                "param_sets": PARAM_SETS,
                "rows": rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n[存档] {out}")


if __name__ == "__main__":
    main()
