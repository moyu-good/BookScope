"""exp-016 probe：数值刻度档内精度 / 重测信度（anshi，长上下文）。

补研究笔记 005 §3.1 的唯一实质缺口：书侧数值刻度（tension 0-10 / sentiment -5..+5
等）以前只验过**方向**对不对（情感往上/往下判对 83%），从没验过**档内精度**——
同一章多次跑，张力到底 6 分还是 7 分能不能稳定复现。

方法学 = 重测信度（test-retest）：输入完全固定（同一批章 + 整本上下文 + 逐字复刻
产品的刻度定义），只让 temperature=1.0 的随机性起作用，重复跑 N 次，看同一章的分
散多大。思路对齐 feedback_baseline_variance_first（对 baseline 多跑求 std）。

刻度定义逐字复刻产品 bookscope/agent/narrative_curve.py 的 _SYSTEM_INSTRUCTION 里
tension/sentiment 两维（不改产品，只把档位描述搬进 probe），测的是产品真实语境。

锁定 5 个指定章（见 docs/internal/experiments/016-scale-precision-probe.md §6），
每章 N 次（默认 3）。flash、key 从 .env、**L2 必须关**（否则命中缓存返回同一份、
方差假性为 0）。DeepSeek 服务端前缀缓存可开（缓 KV 不影响输出随机性）。
不 commit、不动生产、不动 web。
"""

from __future__ import annotations

import json
import os
import re
import statistics
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import bookscope  # noqa: E402, F401 —— 触发 .env 自动加载

_MODEL = os.environ.get("BOOKSCOPE_SMOKE_MODEL", "deepseek-v4-flash")
_DS_BASE = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
_RUNS = int(os.environ.get("PROBE_RUNS", "3"))
_BOOK_PAT = "tests/file/test安史之乱*.epub"

# 锁定打分的 5 个章（设计 §6）。用章号点名定位；先验供人工对照，不喂给模型。
_TARGET_CHAPTERS = [2, 3, 14, 9, 17]
_PRIOR = {
    2: "铺垫(exp012判最松)·tension低",
    3: "铺垫(exp012判最松)·tension低",
    14: "中段(中间地带·精度试金石)·tension中",
    9: "灵宝之战大败(高潮)·tension高·sentiment负",
    17: "香积寺大捷(高潮)·tension高·sentiment正",
}

# tension/sentiment 两维定义逐字取自 bookscope/agent/narrative_curve.py _SYSTEM_INSTRUCTION。
_SCALE_DEF = (
    "tension（张力，0-10 整数）：这章剧情绷得紧不紧。铺垫/过场章低，高潮/冲突章高。\n"
    "sentiment（情感方向，-5 到 +5 整数）：这章整体往上走（喜、胜、聚，正数）"
    "还是往下沉（悲、败、散，负数）；基本平稳填 0。"
)

_CH_LIST_CN = "、".join(f"第{n}章" for n in _TARGET_CHAPTERS)
_INSTRUCTION = (
    f"只针对下面这 {len(_TARGET_CHAPTERS)} 章打分：{_CH_LIST_CN}。\n"
    "对每一章判定两个维度：\n"
    f"{_SCALE_DEF}\n"
    "只依据原文，不臆测、不编造。每章给一条最能支撑你这章判定的原文逐字片段当证据。\n"
    "严格输出 JSON（不要别的话、不要 markdown 代码围栏）：\n"
    '{"chapters": [{"chapter": 章号整数, "tension": 0-10整数, '
    '"sentiment": -5到5整数, "evidence": "支撑这章判定的原文逐字片段，原样摘录不改写"}]}\n'
    f"只输出这 {len(_TARGET_CHAPTERS)} 章，按章号从小到大排列。"
)


def _resolve_book() -> str | None:
    found = sorted(_ROOT.glob(_BOOK_PAT))
    return str(found[0]) if found else None


def _usage_dict(usage) -> dict:
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    try:
        return dict(usage)
    except Exception:  # noqa: BLE001
        return {k: getattr(usage, k) for k in dir(usage) if not k.startswith("_")}


def _clamp_int(value, lo: int, hi: int):
    """把模型给的数值钳到 [lo, hi] 整数；非数 / 缺失退 None（不塞默认值污染方差）。"""
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    return max(lo, min(hi, n))


def _parse_scores(text: str) -> dict[int, dict]:
    """解析模型输出，返回 {章号: {tension, sentiment, evidence}}。

    宽松解析：先剥 code fence、抓第一个 {...} JSON；解析不出就返空 dict（该次记为
    parse 失败，不编数）。只保留在 _TARGET_CHAPTERS 里的章。
    """
    raw = (text or "").strip()
    if not raw:
        return {}
    # 剥 markdown 代码围栏
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", raw, re.DOTALL)
    if fence:
        raw = fence.group(1).strip()
    obj = None
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                obj = json.loads(m.group(0))
            except json.JSONDecodeError:
                obj = None
    if not isinstance(obj, dict):
        return {}
    chapters = obj.get("chapters")
    if not isinstance(chapters, list):
        return {}
    out: dict[int, dict] = {}
    targets = set(_TARGET_CHAPTERS)
    for item in chapters:
        if not isinstance(item, dict):
            continue
        ch = item.get("chapter")
        if not isinstance(ch, int) or ch not in targets:
            continue
        out[ch] = {
            "tension": _clamp_int(item.get("tension"), 0, 10),
            "sentiment": _clamp_int(item.get("sentiment"), -5, 5),
            "evidence": str(item.get("evidence", "")).strip()[:200],
        }
    return out


def run_probe(full_text: str) -> list[dict]:
    """整本进 system 固定段，跑 _RUNS 次，每次让模型对固定 5 章打分。"""
    from openai import OpenAI  # noqa: PLC0415

    client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"], base_url=_DS_BASE)
    system = (
        "你是严谨的长文本分析助手。下面给你一本书的全文。"
        "只根据这本书的原文回答，原文里找不到依据的不要编。\n\n=== 全书原文 ===\n"
        + full_text
    )
    runs = []
    for run in range(1, _RUNS + 1):
        t0 = time.monotonic()
        try:
            resp = client.chat.completions.create(
                model=_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": _INSTRUCTION},
                ],
                temperature=1.0,
                max_tokens=4000,
            )
            dt = time.monotonic() - t0
            ud = _usage_dict(resp.usage)
            ans = resp.choices[0].message.content or ""
            scores = _parse_scores(ans)
            rec = {
                "run": run,
                "latency_s": round(dt, 1),
                "scores": scores,
                "parsed_chapters": sorted(scores.keys()),
                "completion_tokens": ud.get("completion_tokens"),
                "cache_hit": ud.get("prompt_cache_hit_tokens"),
                "cache_miss": ud.get("prompt_cache_miss_tokens"),
                "finish_reason": resp.choices[0].finish_reason,
                "_raw_text": ans,
            }
            got = {c: (scores[c]["tension"], scores[c]["sentiment"]) for c in rec["parsed_chapters"]}
            print(f"[run{run}] {dt:5.1f}s parsed={rec['parsed_chapters']} "
                  f"finish={rec['finish_reason']} scores(t,s)={got}")
        except Exception as e:  # noqa: BLE001
            rec = {"run": run, "error": repr(e)}
            print(f"[run{run}] ERROR {e!r}", file=sys.stderr)
        runs.append(rec)
    return runs


def _std_range(values: list) -> dict:
    """一组分数的 n / mean / std / 极差 / 原始值。std 用样本标准差（n<2 返 None）。"""
    vals = [v for v in values if v is not None]
    if not vals:
        return {"n": 0, "values": []}
    d = {
        "n": len(vals),
        "values": vals,
        "mean": round(statistics.fmean(vals), 2),
        "min": min(vals),
        "max": max(vals),
        "range": max(vals) - min(vals),
    }
    d["std"] = round(statistics.stdev(vals), 3) if len(vals) >= 2 else None
    return d


def _summarize(runs: list[dict]) -> dict:
    """按章聚合每次分数，算 tension / sentiment 的 std / 极差 + 全书汇总。"""
    per_chapter: dict[str, dict] = {}
    tension_stds: list[float] = []
    tension_ranges: list[int] = []
    sentiment_stds: list[float] = []
    sentiment_ranges: list[int] = []
    for ch in _TARGET_CHAPTERS:
        t_vals = [r["scores"].get(ch, {}).get("tension") for r in runs if "scores" in r and ch in r["scores"]]
        s_vals = [r["scores"].get(ch, {}).get("sentiment") for r in runs if "scores" in r and ch in r["scores"]]
        t_stat = _std_range(t_vals)
        s_stat = _std_range(s_vals)
        per_chapter[str(ch)] = {
            "prior": _PRIOR.get(ch, ""),
            "tension": t_stat,
            "sentiment": s_stat,
        }
        if t_stat.get("std") is not None:
            tension_stds.append(t_stat["std"])
            tension_ranges.append(t_stat["range"])
        if s_stat.get("std") is not None:
            sentiment_stds.append(s_stat["std"])
            sentiment_ranges.append(s_stat["range"])
    summary = {
        "target_chapters": _TARGET_CHAPTERS,
        "runs_attempted": len(runs),
        "runs_ok": sum(1 for r in runs if "scores" in r),
        "tension_mean_std": round(statistics.fmean(tension_stds), 3) if tension_stds else None,
        "tension_max_range": max(tension_ranges) if tension_ranges else None,
        "sentiment_mean_std": round(statistics.fmean(sentiment_stds), 3) if sentiment_stds else None,
        "sentiment_max_range": max(sentiment_ranges) if sentiment_ranges else None,
    }
    return {"summary": summary, "per_chapter": per_chapter}


def main() -> int:
    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("[probe] DEEPSEEK_API_KEY 未设置（应从 .env 读）", file=sys.stderr)
        return 1
    epub = _resolve_book()
    if not epub:
        print(f"[probe] anshi epub 没找到（{_BOOK_PAT}）", file=sys.stderr)
        return 1
    os.environ["BOOKSCOPE_LLM_CACHE_DISABLED"] = "1"  # 关 L2，否则方差假性为 0

    from bookscope.ingest.loader import load_text  # noqa: PLC0415

    full_text = load_text(epub).raw_text
    print(f"[probe] anshi 全文 {len(full_text)} 字符；固定 {len(_TARGET_CHAPTERS)} 章 "
          f"{_TARGET_CHAPTERS} × {_RUNS} 次；模型 {_MODEL}；L2 关\n")

    out_path = _ROOT / "docs" / "internal" / "experiments" / "data" / "exp016-scale-precision-anshi.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    runs = run_probe(full_text)
    agg = _summarize(runs)

    s = agg["summary"]
    print("\n" + "=" * 64)
    print(f"{s['runs_ok']}/{s['runs_attempted']} 次成功解析")
    print(f"tension  平均档内 std = {s['tension_mean_std']}  最大极差 = {s['tension_max_range']} 档")
    print(f"sentiment 平均档内 std = {s['sentiment_mean_std']}  最大极差 = {s['sentiment_max_range']} 档")
    print("判定见 016 §4 表：<0.5 可信 / 0.5-1 粗档 / >=1 只信相对形状")
    print("=" * 64)
    for ch in _TARGET_CHAPTERS:
        pc = agg["per_chapter"][str(ch)]
        t, se = pc["tension"], pc["sentiment"]
        print(f"  ch{ch:>2} [{pc['prior']}]")
        print(f"       tension  {t.get('values')}  std={t.get('std')} range={t.get('range')}")
        print(f"       sentiment {se.get('values')}  std={se.get('std')} range={se.get('range')}")

    out_path.write_text(json.dumps({
        "probe": "exp016-scale-precision",
        "book": "anshi",
        "model": _MODEL,
        "scale_source": "bookscope/agent/narrative_curve.py _SYSTEM_INSTRUCTION (tension 0-10, sentiment -5..+5)",
        "l2_cache_disabled": True,
        "runs_per_chapter": _RUNS,
        "summary": agg["summary"],
        "per_chapter": agg["per_chapter"],
        "runs": runs,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[probe] 写入 {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
