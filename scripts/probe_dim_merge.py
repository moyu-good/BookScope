"""章脉分维合并 probe(exp028):人物维 + 情节维**两趟**读全书 vs **合并一趟**,验 input 砍半
的同时截断 / 质量守不守得住。依托研究笔记 012 §4.A + §6.1(ReadAgent 每页只 gist 一次 → 合并一趟)。

**问题**:章脉现在分人物维 + 情节维两趟扫全书(``chapter_spine.py`` ``dims=[char, plot]``),
input ≈ 2× 书。ReadAgent 的经验是每页只 gist 一次 → 该合并成一趟。当初分两趟只因 8000 输出会
截断;现在 max_tokens 已抬到 16000,合并很可能装得下。拿三国真书量清楚:合并一趟 @16000 到底
① input 省多少 ② 截断率涨不涨 ③ 每章字段完整度掉不掉。

**为什么 n=1 够下结论**:A 的卖点是 **input token**,而 input token 是**确定性**的(段切好就
定,不受 API 抖动影响),截断率 / 完整度也基本确定。方差大的只有墙钟——但墙钟不是 A 的卖点
(A 卖 token 省、不卖快),所以本 probe **不下墙钟倍数结论**,只报 input / 截断 / 完整度。

**控制变量**:两条件用**完全相同**的机器(``mapreduce_per_chapter``,char_budget=120000 /
max_chapters=12 / max_tokens=16000,continue_fn=None,sweep=True,同 ``_correct_by_evidence``),
只差两趟 vs 一趟。截断丢的章由 sweep 单章重抽补回,补抽的调用 / input 都算进 tracker——所以
"合并输出更大 → 更容易截断 → 补抽更多 → 吃掉省下的 input" 这条风险,数字上跑得出来。缓存全局关。

**观测不改产品**:monkeypatch ``exhaustive`` 命名空间的 ``invoke_client_cached`` 成计数 wrapper,
逐调用记 finish_reason / prompt_tokens / completion_tokens。不动产品文件一个字节。

四项核验:
1. input 省:合并 input_tokens vs 两趟(char + plot)之和——期望 ~砍半。
2. 截断:合并 finish_reason=length 率 vs 两趟——合并输出更大,这是主要威胁,得低。
3. 完整度:合并每章 present / relations / char_states / events / foreshadow / pov 非空率 + 均条数
   ≥ 两趟(不掉质量)。
4. 覆盖:掉章率两边都低。

go/no-go:input 明显省(接近半)+ 截断不显著恶化 + 完整度不掉 → GO,把章脉改回一趟。
公开书三国,flash,key 从 .env,不 commit、不动生产。

用法:
  python -X utf8 scripts/probe_dim_merge.py               # 完整跑(两趟 + 合并 @16000)
  python -X utf8 scripts/probe_dim_merge.py --mt=32000    # 合并给 32000 输出预算(两趟仍 16000)
  python -X utf8 scripts/probe_dim_merge.py --mt=32000 --merged-only  # 只重跑合并、两趟复用最近存档
书关键字走位置参数(默认三国);cp932 控制台别在命令行传中文,用默认即可。
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

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import bookscope.agent._internal.exhaustive as _exhaustive_mod  # noqa: E402
from bookscope.agent._internal.exhaustive import mapreduce_per_chapter  # noqa: E402
from bookscope.agent._internal.llm_cache import (  # noqa: E402
    invoke_client_cached as _real_invoke,
)
from bookscope.agent._internal.loop_shared import (  # noqa: E402
    read_openai_finish_reason,
    read_openai_usage,
)
from bookscope.agent.chapter_spine import (  # noqa: E402
    _INSTR_CHAR,
    _INSTR_PLOT,
    _USER_MSG,
    _clamp_int,
    _coerce_relations,
    _correct_by_evidence,
    _make_parser,
    _merge_dimensions,
)
from bookscope.agent.utils.json_parsing import (  # noqa: E402
    extract_first_json_object as _extract_first_json_object,
)
from bookscope.agent.utils.json_parsing import salvage_closed_objects  # noqa: E402
from bookscope.agent.utils.json_parsing import strip_code_fence as _strip_code_fence  # noqa: E402
from bookscope.api.dependencies import (  # noqa: E402
    build_llm_client_from_params,
    default_model_for,
)
from bookscope.ingest.book_chunker import chunk_book_with_stats  # noqa: E402
from bookscope.ingest.loader import load_text  # noqa: E402

OUT_DIR = _ROOT / "docs" / "internal" / "experiments" / "runs"

# 与现产品章脉 sweet spot 一致(chapter_spine.py):大段 12 万字 / 12 章 + 16000 token。
_CHAR_BUDGET = 120000
_MAX_CHAPTERS = 12
_MAX_TOKENS = 16000
_MAX_WORKERS = 6

# ── 合并一趟的指令:人物维 + 情节维所有字段,一次抽完(= _INSTR_CHAR ∪ _INSTR_PLOT) ──
_INSTR_MERGED = (
    "你在给一本书做逐章精读(人物和情节一起看)。只针对下面这段原文,逐章抽,只抽本段出现的章,"
    "不臆测、不编造。\n"
    "每章给:\n"
    "1. present:这章在场(有戏份)的人物名数组。\n"
    "2. relations:这章有互动的人物对数组,每条 {pair:[甲,乙], note:这章他俩之间发生了什么, "
    "type:关系类型(从这个封闭集里选一个最贴的——亲族/君臣/同僚/师徒/结义/结盟/敌对/情谊/利用/其他), "
    "valence:这章他俩的敌友倾向整数,-5(死敌)到 +5(至交),中立 0}。\n"
    "3. char_states:这章里主要人物的处境数组,每条 {name:人物, state:他这章处于什么境况}。\n"
    "4. events:这章的关键事件数组,每条一句话。\n"
    "5. tension:张力 0-10 整数,铺垫/过场低、高潮/冲突高。\n"
    "6. sentiment:情感方向 -5 到 5 整数,往上走(喜胜聚)正、往下沉(悲败散)负、平稳 0。\n"
    "7. pov:主导视角人物名;无单一视角(全景)填\"群像\"。\n"
    "8. mainline:推进主线 true,岔开支线/闲笔 false。\n"
    "9. foreshadow:这章的伏笔候选数组,每条 {type:\"埋\"或\"收\", hook:埋/收的是什么}。\n"
    "10. evidence:这章里最能代表上面判定的一句原文逐字片段(原样摘录、不改写)。\n"
    "严格输出 JSON(别的话别说、别加 markdown 围栏):\n"
    '{"chapters":[{"chapter":章号整数,"present":[],"relations":[],"char_states":[],'
    '"events":[],"tension":0,"sentiment":0,"pov":"","mainline":true,"foreshadow":[],"evidence":""}]}'
)


def _coerce_merged(item: Any) -> dict[str, Any] | None:
    """把合并抽的一条章节 dict 归一成全字段;chapter 缺/非整数 → 丢。同 chapter_spine 的口径。"""
    if not isinstance(item, dict):
        return None
    ch = item.get("chapter")
    if not isinstance(ch, int):
        return None
    pov = item.get("pov")
    ml = item.get("mainline")

    def _list(k: str) -> list:
        v = item.get(k)
        return v if isinstance(v, list) else []

    return {
        "chapter": ch,
        "present": _list("present"),
        "relations": _coerce_relations(item.get("relations")),
        "char_states": _list("char_states"),
        "events": _list("events"),
        "tension": _clamp_int(item.get("tension"), 0, 10, 0),
        "sentiment": _clamp_int(item.get("sentiment"), -5, 5, 0),
        "pov": (pov.strip() if isinstance(pov, str) else "") or "群像",
        "mainline": ml if isinstance(ml, bool) else True,
        "foreshadow": _list("foreshadow"),
        "evidence": str(item.get("evidence", "")).strip(),
    }


def _make_merged_parser():  # noqa: ANN202
    """合并维的 parse_fn:strip 围栏 → json.loads → 抠首个 obj → 截断抢救 → 全字段归一。"""

    def _coerce_list(raw: Any) -> list[dict[str, Any]]:
        if not isinstance(raw, list):
            return []
        out: list[dict[str, Any]] = []
        seen: set[int] = set()
        for it in raw:
            c = _coerce_merged(it)
            if c is None or c["chapter"] in seen:
                continue
            seen.add(c["chapter"])
            out.append(c)
        return out

    def _parse(text: str) -> list[dict[str, Any]] | None:
        raw = (text or "").strip()
        if not raw:
            return None
        candidate = _strip_code_fence(raw)
        obj: Any = None
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            sliced = _extract_first_json_object(candidate)
            if sliced is not None:
                try:
                    obj = json.loads(sliced)
                except json.JSONDecodeError:
                    obj = None
        if isinstance(obj, dict):
            chs = _coerce_list(obj.get("chapters"))
            if chs:
                return chs
        salvaged = _coerce_list(salvage_closed_objects(candidate, '"chapters"') or [])
        return salvaged or None

    return _parse


class _Tracker:
    """线程安全:wrap invoke_client_cached,逐调用记 finish_reason / prompt(input) / completion。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.n_calls = 0
        self.n_length = 0
        self.prompt_tokens: list[int] = []
        self.completion_tokens: list[int] = []
        self.finish: dict[str, int] = {}

    def wrapped(self, client: Any, **kwargs: Any) -> Any:
        resp = _real_invoke(client, **kwargs)
        fr = read_openai_finish_reason(resp) or "unknown"
        prompt, completion = read_openai_usage(resp)
        with self._lock:
            self.n_calls += 1
            self.finish[fr] = self.finish.get(fr, 0) + 1
            if fr == "length":
                self.n_length += 1
            if prompt:
                self.prompt_tokens.append(int(prompt))
            if completion:
                self.completion_tokens.append(int(completion))
        return resp

    def snap(self) -> dict[str, Any]:
        with self._lock:
            return {
                "n_calls": self.n_calls,
                "n_length": self.n_length,
                "trunc_rate": round(self.n_length / self.n_calls, 3) if self.n_calls else 0.0,
                "input_tokens": sum(self.prompt_tokens),
                "output_tokens": sum(self.completion_tokens),
                "finish_reasons": dict(self.finish),
            }


def _completeness(spine: list[dict[str, Any]]) -> dict[str, Any]:
    """各字段非空率 + 均条数 + pov 非群像率 + verified 率。放大后掉质量这里会变稀。"""
    n = len(spine)
    if n == 0:
        return {"n_chapters": 0}

    def _ne(k: str) -> float:
        return round(sum(1 for r in spine if isinstance(r.get(k), list) and r[k]) / n, 3)

    def _avg(k: str) -> float:
        cs = [len(r[k]) for r in spine if isinstance(r.get(k), list)]
        return round(sum(cs) / len(cs), 2) if cs else 0.0

    pov_named = sum(1 for r in spine if str(r.get("pov", "")).strip() not in ("", "群像"))
    ev_ne = sum(1 for r in spine if str(r.get("evidence", "")).strip())
    verified = sum(1 for r in spine if r.get("verified") is True)
    return {
        "n_chapters": n,
        "present_ne": _ne("present"),
        "relations_ne": _ne("relations"),
        "char_states_ne": _ne("char_states"),
        "events_ne": _ne("events"),
        "foreshadow_ne": _ne("foreshadow"),
        "present_per_ch": _avg("present"),
        "relations_per_ch": _avg("relations"),
        "events_per_ch": _avg("events"),
        "pov_named_rate": round(pov_named / n, 3),
        "evidence_ne_rate": round(ev_ne / n, 3),
        "verified_rate": round(verified / n, 3),
    }


def _run_pass(
    *,
    instruction: str,
    parse_fn: Any,
    chunks: list[dict[str, Any]],
    client: Any,
    model: str,
    max_tokens: int = _MAX_TOKENS,
) -> tuple[list[dict[str, Any]], dict[str, Any], float]:
    """跑一趟 map-reduce(monkeypatch tracker 计数),返 (逐章记录, tracker快照, 墙钟秒)。"""
    tracker = _Tracker()
    _orig = _exhaustive_mod.invoke_client_cached
    _exhaustive_mod.invoke_client_cached = tracker.wrapped
    try:
        t0 = time.monotonic()
        recs = mapreduce_per_chapter(
            chunks=chunks,
            instruction=instruction,
            user_msg=_USER_MSG,
            parse_fn=parse_fn,
            llm_client=client,
            model=model,
            max_tokens=max_tokens,
            char_budget=_CHAR_BUDGET,
            max_chapters=_MAX_CHAPTERS,
            max_workers=_MAX_WORKERS,
            correct_fn=_correct_by_evidence,
            continue_fn=None,  # 两条件对称:都不续抽,截断丢章交给 sweep 单章重抽
            sweep_missing_chapters=True,
        )
        wall = time.monotonic() - t0
    finally:
        _exhaustive_mod.invoke_client_cached = _orig
    return recs, tracker.snap(), round(wall, 1)


def _latest_baseline(kw: str) -> tuple[dict[str, Any] | None, str | None]:
    """读 runs/ 最新 probe_dim_merge_<kw>_*.json 的 baseline_2pass 块(给 --merged-only 复用)。

    两趟 baseline 是稳定的(同书同段同 prompt),不必每次重跑陪着烧钱;--merged-only 只重跑
    合并那一趟、拿它跟存档的两趟比。找不到存档 → 返 (None, None),调用方退回完整跑。
    """
    hits = sorted(glob.glob(str(OUT_DIR / f"probe_dim_merge_{kw}_*.json")))
    for p in reversed(hits):
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        base = data.get("baseline_2pass")
        if base:
            return base, Path(p).name
    return None, None


def main() -> int:
    # 参数:位置1=书关键字(默认三国),位置2=合并 max_tokens(默认 16000);--merged-only=只重跑
    # 合并那一趟、两趟 baseline 从最近的存档读(baseline 稳定,不必陪着烧钱)。
    argv = sys.argv[1:]
    merged_only = "--merged-only" in argv
    merged_mt = _MAX_TOKENS
    for _a in argv:
        if _a.startswith("--mt="):
            merged_mt = int(_a.split("=", 1)[1])
    pos = [a for a in argv if not a.startswith("--")]
    kw = pos[0] if pos else "三国"

    matches = glob.glob(str(_ROOT / "tests" / "file" / f"*{kw}*"))
    if not matches:
        print(f"没找到含「{kw}」的测试书", file=sys.stderr)
        return 1
    path = matches[0]

    os.environ["BOOKSCOPE_LLM_CACHE_DISABLED"] = "1"  # 每趟真跑,别命中缓存
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        print("DEEPSEEK_API_KEY 没加载到(应由 import bookscope 从 .env 读入)", file=sys.stderr)
        return 1

    book = load_text(path, title=kw)
    chunk_res, _ = chunk_book_with_stats(book)
    chunks = [
        {"chunk_id": f"r0-chunk-{c.index}", "chapter": c.chapter, "text": c.text}
        for c in chunk_res
    ]
    true_chapters = {
        c["chapter"] for c in chunks if isinstance(c["chapter"], int) and c["chapter"] >= 1
    }
    total_chars = sum(len(c["text"]) for c in chunks)
    client = build_llm_client_from_params(provider="deepseek", api_key=key)
    model = default_model_for("deepseek")

    print(f"[book] {Path(path).name}")
    print(
        f"[ingest] {len(chunks)} chunk / 真章 {len(true_chapters)} / {total_chars} 字符 / "
        f"缓存关 / 段 {_CHAR_BUDGET}字·{_MAX_CHAPTERS}章 / 合并 max_tokens={merged_mt}"
    )
    print(f"[model] {model}\n")

    def _drop(recs: list[dict[str, Any]]) -> float:
        have = {r["chapter"] for r in recs if isinstance(r.get("chapter"), int)}
        return round(len(true_chapters - have) / len(true_chapters), 3) if true_chapters else 0.0

    # ── 现状:两趟(fresh 跑,或 --merged-only 从存档复用)──
    base_char: dict[str, Any] | None = None
    base_plot: dict[str, Any] | None = None
    if merged_only:
        base, src = _latest_baseline(kw)
        if not base:
            print("--merged-only 但没找到历史 baseline;先跑一次完整 probe", file=sys.stderr)
            return 1
        base_input = base["input_tokens"]
        base_output = base["output_tokens"]
        base_calls = base["n_calls"]
        base_trunc = base["n_length"]
        base_drop = base["drop_rate"]
        base_comp = base["completeness"]
        base_wall = base.get("wall_seconds", 0.0)
        print(f"[现状·两趟] 复用存档 {src}(input={base_input},不重跑)\n")
    else:
        print("[现状·两趟] 人物维 map-reduce…")
        char_recs, base_char, char_wall = _run_pass(
            instruction=_INSTR_CHAR, parse_fn=_make_parser("char"),
            chunks=chunks, client=client, model=model,
        )
        print(
            f"  人物维: {char_wall}s | 调用{base_char['n_calls']} 截断{base_char['n_length']} | "
            f"input={base_char['input_tokens']} output={base_char['output_tokens']}"
        )
        print("[现状·两趟] 情节维 map-reduce…")
        plot_recs, base_plot, plot_wall = _run_pass(
            instruction=_INSTR_PLOT, parse_fn=_make_parser("plot"),
            chunks=chunks, client=client, model=model,
        )
        print(
            f"  情节维: {plot_wall}s | 调用{base_plot['n_calls']} 截断{base_plot['n_length']} | "
            f"input={base_plot['input_tokens']} output={base_plot['output_tokens']}"
        )
        base_spine = _merge_dimensions([char_recs, plot_recs])
        base_input = base_char["input_tokens"] + base_plot["input_tokens"]
        base_output = base_char["output_tokens"] + base_plot["output_tokens"]
        base_calls = base_char["n_calls"] + base_plot["n_calls"]
        base_trunc = base_char["n_length"] + base_plot["n_length"]
        base_drop = _drop(base_spine)
        base_comp = _completeness(base_spine)
        base_wall = round(char_wall + plot_wall, 1)

    # ── 候选:合并一趟 @ merged_mt ──
    print(f"\n[候选·一趟] 合并维 map-reduce @{merged_mt}…")
    merged_recs, merged_stat, merged_wall = _run_pass(
        instruction=_INSTR_MERGED, parse_fn=_make_merged_parser(),
        chunks=chunks, client=client, model=model, max_tokens=merged_mt,
    )
    merged_spine = _merge_dimensions([merged_recs])
    merged_comp = _completeness(merged_spine)
    merged_drop = _drop(merged_spine)
    print(
        f"  合并维: {merged_wall}s | 调用{merged_stat['n_calls']} 截断{merged_stat['n_length']} | "
        f"input={merged_stat['input_tokens']} output={merged_stat['output_tokens']}"
    )

    # ── 四项核验 ──
    m_input = merged_stat["input_tokens"]
    saved = round((1 - m_input / base_input) * 100, 1) if base_input else 0.0
    base_tr = round(base_trunc / base_calls, 3) if base_calls else 0.0
    m_calls = merged_stat["n_calls"]
    m_len = merged_stat["n_length"]
    m_tr = merged_stat["trunc_rate"]
    print("\n" + "=" * 70)
    print(f"四项核验(两趟 vs 一趟 @{merged_mt}):")
    print(f"1 input 省:两趟合计 {base_input} → 合并 {m_input}(省 {saved}%,期望接近 50%)")
    print(
        f"2 截断率:两趟 {base_trunc}/{base_calls}={base_tr*100:.0f}% → "
        f"合并 {m_len}/{m_calls}={m_tr*100:.0f}%"
    )
    print(f"3 掉章率:两趟 {base_drop*100:.0f}% → 合并 {merged_drop*100:.0f}%")
    print("4 完整度(非空率·均条数):")
    for k in ("present_ne", "relations_ne", "char_states_ne", "events_ne", "foreshadow_ne",
              "present_per_ch", "relations_per_ch", "events_per_ch", "pov_named_rate",
              "verified_rate"):
        print(f"    {k:>16}: 两趟 {base_comp.get(k)}  →  合并 {merged_comp.get(k)}")
    print("=" * 70)
    print(
        f"[输出对比] 两趟 output {base_output} / 合并 output {merged_stat['output_tokens']}  "
        f"| 墙钟 两趟{base_wall:.0f}s / 合并{merged_wall:.0f}s(墙钟方差大,不下倍数结论)"
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = OUT_DIR / f"probe_dim_merge_{kw}_{ts}.json"
    baseline_block: dict[str, Any] = {
        "input_tokens": base_input, "output_tokens": base_output,
        "n_calls": base_calls, "n_length": base_trunc,
        "drop_rate": base_drop, "completeness": base_comp, "wall_seconds": base_wall,
    }
    if base_char is not None:
        baseline_block["char"] = base_char
        baseline_block["plot"] = base_plot
    else:
        baseline_block["reused_from_archive"] = True
    out.write_text(
        json.dumps(
            {
                "probe": "exp028-dim-merge",
                "book": Path(path).name,
                "model": model,
                "n_chunks": len(chunks),
                "chapters_expected": len(true_chapters),
                "total_chars": total_chars,
                "seg": {"char_budget": _CHAR_BUDGET, "max_chapters": _MAX_CHAPTERS,
                        "max_tokens": _MAX_TOKENS},
                "merged_max_tokens": merged_mt,
                "baseline_2pass": baseline_block,
                "merged_1pass": {
                    "stat": merged_stat, "drop_rate": merged_drop,
                    "completeness": merged_comp, "wall_seconds": merged_wall,
                },
                "input_saved_pct": saved,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n[存档] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
