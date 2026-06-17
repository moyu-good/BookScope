"""exp-008 伏笔—回收配对追踪 可行性 probe 脚本。

跑 ``docs/internal/experiments/008-foreshadowing-payoff-probe.md`` §4 的两类任务：

- **任务 A**（正例）：给 agent 一个埋设点（setup）+ 章节 + 问法，要它只靠
  原文证据找回收点（payoff）。
- **任务 B**（伪负例）：给一个真实 setup，但问法指向书里不存在的回收方向，
  看 agent 会不会顺着诱导编一个不存在的回收点（测假阳性）。

标注集：``docs/internal/experiments/data/exp008-foreshadowing-pairs-kuicheng.json``。

### 三条运行约束（作者明确要求，2026-06-12）

1. **只用 flash**：``deepseek-v4-flash``，绝不用 pro（最便宜大众档）。
2. **DeepSeek 服务端前缀缓存全程开**：所有题跑在同一个已 ingest 的 kuicheng
   session 上，固定 system 前缀一致 → 服务端前缀缓存命中（按 1/50 计价）。
   本脚本一次 load book + 一个 loop 复用所有题，不重 ingest、不动 system 段。
3. **关 BookScope 自己的 L2 整答案缓存**：probe 要'同一题跑 3 次看答案稳不稳'，
   L2 开着会让 3 次返回一模一样的缓存答案、方差假成 0。本脚本启动即设
   ``BOOKSCOPE_LLM_CACHE_DISABLED=1``（llm_cache.py 的 env flag）。
   注意这跟第 2 条不冲突——关的是 BookScope 本地 L2，DeepSeek 服务端前缀缓存照开。
4. **跳过 KG 抽取**：伏笔追踪不调 list_characters，KG 又占 ingest 99% 时间产出 0。
   本脚本走 smoke_test_r1._load_book_session 的默认路径——它**默认不真抽 KG**
   （只塞一个手工 KG 壳给 backend 装配，不发 LLM 调用），只要 chunk + BM25
   + chapter_range 能用即可。
5. key 从 ``.env`` 自动读（``DEEPSEEK_API_KEY``，import bookscope 会 load_dotenv）。

### 五维指标（exp-008 §5，本脚本只采原始数据，判分留人工 + 后续）

本脚本不做自动判分（'找对了没'是语义判断，要人工或二次 reviewer）。它采的是
判分所需的原始信号：每 run 的答案全文、citations（含程序化 verified 字段）、
trace（iterations / tool_calls / token / 缓存命中）。3 次答案差异 = L2 真关了
的证据 + 方差素材。

### 用法

烟测（只跑 1 条 pair × 3 次）::

    PYTHONIOENCODING=utf-8 python scripts/probe_foreshadowing.py \\
        --pair-id P1 --runs 3

全量（跑全部 pair，**需作者批准后才放**）::

    PYTHONIOENCODING=utf-8 python scripts/probe_foreshadowing.py --all --runs 3

环境变量：

- ``DEEPSEEK_API_KEY``：从 .env 自动读
- ``BOOKSCOPE_SMOKE_EPUB``：默认指向 kuicheng epub（本脚本写死兜底）
- ``BOOKSCOPE_SMOKE_TIMEOUT``：单题超时秒，默认 600
- ``BOOKSCOPE_PROBE_CONCURRENCY``：全量跑时 (pair, run) 任务并发数，默认 5
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

# Windows 控制台 UTF-8 兜底
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# 约束 3：probe 一启动就关 BookScope L2 整答案缓存——必须在 import bookscope
# 任何缓存模块前设好 env（_is_cache_disabled 每次调用都读 env，所以这里设了
# 全程有效）。这跟 DeepSeek 服务端前缀缓存无关，那个在 provider 端、照开。
os.environ["BOOKSCOPE_LLM_CACHE_DISABLED"] = "1"

# 约束 4 + 真实测试书：按干净前缀 glob 定位 kuicheng epub，**绝不硬编原始文件名**
# （原文件名带盗版站字样，版权红线，不入库）。本地仓库根放一本 test亏成首富*.epub
# 即可；也可用 BOOKSCOPE_SMOKE_EPUB 环境变量显式指定路径。产出里一律用 'kuicheng'。
def _resolve_kuicheng_epub() -> str | None:
    env = os.environ.get("BOOKSCOPE_SMOKE_EPUB", "").strip()
    if env:
        return env
    found = sorted(_PROJECT_ROOT.glob("test亏成首富*.epub"))
    return str(found[0]) if found else None


_kuicheng_epub = _resolve_kuicheng_epub()
if _kuicheng_epub:
    os.environ.setdefault("BOOKSCOPE_SMOKE_EPUB", _kuicheng_epub)

_PAIRS_JSON = (
    _PROJECT_ROOT
    / "docs"
    / "experiments"
    / "data"
    / "exp008-foreshadowing-pairs-kuicheng.json"
)
_DEFAULT_OUTPUT = (
    _PROJECT_ROOT
    / "docs"
    / "experiments"
    / "data"
    / "exp008-probe-runs-kuicheng.json"
)


# ---------------------------------------------------------------------------
# 问法模板（exp-008 §4）
# ---------------------------------------------------------------------------


def _build_task_a_question(pair: dict[str, Any]) -> str:
    """任务 A · 给埋设点找回收点（正例）。"""
    setup_ch = pair["setup_chapter"]
    setup_text = pair["setup_text"]
    return (
        f"第{setup_ch}章有这样一处埋设：{setup_text}\n\n"
        "这个埋设点在后文有没有被回收（payoff）？如果有，回收点在哪一章、"
        "回收成了什么结果？请给出回收点的原文引用片段。"
        "用一句话说清这个回收点是怎么呼应前面这处埋设的。\n\n"
        "如果你判断它在书里没有被回收，请直接说'没找到回收点'，不要推测、"
        "不要编造章节号和引用。"
    )


def _build_task_b_question(pair: dict[str, Any]) -> str:
    """任务 B · 伪负例诱导（测假阳性）。"""
    setup_ch = pair["setup_chapter"]
    setup_text = pair["setup_text"]
    false_dir = pair["false_payoff_direction"]
    return (
        f"第{setup_ch}章有这样一处情节：{setup_text}\n\n"
        f"{false_dir}\n\n"
        "请基于书中原文判断这个走向是否真的存在。如果存在，给出章节号和"
        "原文引用；如果书里没有这个走向，请直接说明书里没有，不要为了"
        "回答问题而编造一个不存在的回收点或引用。"
    )


# ---------------------------------------------------------------------------
# 单次跑：一条 pair 的一次 run
# ---------------------------------------------------------------------------


def _run_once(
    *,
    loop: Any,
    pair: dict[str, Any],
    task: str,
    run_idx: int,
) -> dict[str, Any]:
    """跑一条 pair 的一次，返回原始信号 dict。失败不抛——填 error 字段。"""
    if task == "A":
        question = _build_task_a_question(pair)
    else:
        question = _build_task_b_question(pair)

    t0 = time.monotonic()
    try:
        result = loop.query(question)
    except Exception as exc:  # noqa: BLE001
        elapsed = time.monotonic() - t0
        rec: dict[str, Any] = {
            "pair_id": pair["id"],
            "task": task,
            "run_idx": run_idx,
            "error": f"{type(exc).__name__}: {exc}",
            "duration_s": round(elapsed, 1),
        }
        partial_trace = getattr(exc, "trace", None)
        if partial_trace is not None:
            try:
                rec["trace"] = partial_trace.model_dump()
            except Exception:  # noqa: BLE001
                pass
        return rec

    elapsed = time.monotonic() - t0
    trace = result.trace.model_dump()
    tool_names = [
        tc.get("tool_name")
        for tc in trace.get("tool_calls", [])
        if isinstance(tc, dict)
    ]
    # citations 程序化校验字段（WP1）：verified=true 表示能在原文逐字找到
    cits = result.citations or []
    verified_n = sum(1 for c in cits if isinstance(c, dict) and c.get("verified") is True)
    return {
        "pair_id": pair["id"],
        "task": task,
        "run_idx": run_idx,
        "question": question,
        "answer": result.answer,
        "citations": cits,
        "citation_count": len(cits),
        "citation_verified_count": verified_n,
        "duration_s": round(elapsed, 1),
        "trace_signals": {
            "iterations": trace.get("iterations"),
            "outcome": trace.get("outcome"),
            "tool_call_names": tool_names,
            "tool_call_count": len(tool_names),
            "total_input_tokens": trace.get("total_input_tokens"),
            "total_output_tokens": trace.get("total_output_tokens"),
            # DeepSeek 服务端前缀缓存命中观测（约束 2 的证据）
            "cache_hit_tokens": trace.get("cache_hit_tokens"),
            "cache_miss_tokens": trace.get("cache_miss_tokens"),
            "prompt_version": trace.get("prompt_version"),
        },
    }


# ---------------------------------------------------------------------------
# 标注集加载 + pair 选择
# ---------------------------------------------------------------------------


def _load_pairs() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """返回 (扁平 pair 列表, 原始 dataset meta)。

    pair 列表里每条多一个 ``_task`` 字段：positive → A，pseudo_negative → B。
    """
    src = json.loads(_PAIRS_JSON.read_text(encoding="utf-8"))
    pairs: list[dict[str, Any]] = []
    for p in src.get("positives", []):
        pairs.append({**p, "_task": "A"})
    for p in src.get("pseudo_negatives", []):
        pairs.append({**p, "_task": "B"})
    return pairs, src


def _select_pairs(
    all_pairs: list[dict[str, Any]],
    *,
    pair_id: str | None,
    run_all: bool,
) -> list[dict[str, Any]]:
    if run_all:
        return all_pairs
    if pair_id:
        sel = [p for p in all_pairs if p["id"] == pair_id]
        if not sel:
            raise SystemExit(f"[probe] 找不到 pair id={pair_id}")
        return sel
    # 默认：只跑第一条正例（烟测——通管线，不跑全量）
    for p in all_pairs:
        if p["_task"] == "A":
            return [p]
    return all_pairs[:1]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="exp-008 伏笔回收配对 probe")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--pair-id", default=None, help="只跑这一条 pair（如 P1 / N2）")
    g.add_argument(
        "--all",
        action="store_true",
        dest="run_all",
        help="跑全部 pair（需作者批准；默认只跑 1 条做烟测）",
    )
    p.add_argument(
        "--runs",
        type=int,
        default=3,
        help="每条 pair 跑几次（取众数判稳定性 + 验 L2 真关）。默认 3",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=_DEFAULT_OUTPUT,
        help="结果 JSON 落地路径",
    )
    return p.parse_args(argv)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    # import bookscope 时其 __init__ 会 load_dotenv() 读 .env（约束 5）。
    # 这里 import 一下确保 .env 已加载，再检查 key。
    import bookscope  # noqa: F401, PLC0415

    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("[probe] DEEPSEEK_API_KEY 未设置（应从 .env 自动读）", file=sys.stderr)
        return 1

    _epub_path = os.environ.get("BOOKSCOPE_SMOKE_EPUB", "")
    if not _epub_path or not os.path.exists(_epub_path):
        print(
            "[probe] kuicheng epub 没找到：仓库根放一本 test亏成首富*.epub，"
            "或设 BOOKSCOPE_SMOKE_EPUB 指向 epub 路径。",
            file=sys.stderr,
        )
        return 1
    if not _PAIRS_JSON.is_file():
        print(f"[probe] 标注集不存在: {_PAIRS_JSON}", file=sys.stderr)
        return 1

    # L2 关的确认（约束 3）
    from bookscope.agent._internal.llm_cache import _is_cache_disabled  # noqa: PLC0415

    l2_disabled = _is_cache_disabled()
    print(f"[probe] BookScope L2 整答案缓存 disabled = {l2_disabled}（约束 3）")
    if not l2_disabled:
        print("[probe] 警告：L2 没关，3 次会返回缓存答案、方差假成 0！", file=sys.stderr)
        return 1

    all_pairs, dataset_meta = _load_pairs()
    selected = _select_pairs(
        all_pairs, pair_id=args.pair_id, run_all=args.run_all
    )
    print(
        f"[probe] 选中 {len(selected)} 条 pair × {args.runs} 次 = "
        f"{len(selected) * args.runs} 次端到端跑"
    )
    if not args.run_all and not args.pair_id:
        print("[probe] （烟测模式：只跑 1 条 pair 通管线，全量需 --all）")

    # ingest 一次：load book + 装配 backend + 建 loop（约束 2/4——一个 session
    # 复用所有题，固定 system 前缀让 DeepSeek 服务端前缀缓存命中；不真抽 KG）
    from scripts.smoke_test_r1 import (  # type: ignore[import-not-found]  # noqa: PLC0415
        _build_adapter_and_model,
        _load_book_session,
    )

    print("[probe] ingest 中（load epub + chunk + BM25 索引；跳过 KG 抽取）...")
    t_ingest = time.monotonic()
    book, chunks, kg, vector_store = _load_book_session()
    ingest_elapsed = time.monotonic() - t_ingest
    book_title = book.title
    language = getattr(book, "language", "zh") or "zh"
    kg_char_n = len(kg.characters)
    print(
        f"[probe] ingest 完成 {ingest_elapsed:.1f}s："
        f"{getattr(book, 'word_count', '?')} 字 / {len(chunks)} chunk / "
        f"KG {kg_char_n} 角色（手工壳，未发 LLM 抽取）"
    )

    adapter, model = _build_adapter_and_model("deepseek")
    print(f"[probe] generator model = {model}（约束 1：只用 flash）")

    from bookscope.agent import AgentLoop  # noqa: PLC0415
    from bookscope.agent.backends.r0_assembler import R0BookAssembler  # noqa: PLC0415

    assembler = R0BookAssembler(
        book_text=book,
        chunks=chunks,
        knowledge_graph=kg,
        session_vector_store=vector_store,
    )
    backends = assembler.build_all()
    if backends["search"] is None:
        print("[probe] vector store 装配失败", file=sys.stderr)
        return 3

    timeout_seconds = float(os.environ.get("BOOKSCOPE_SMOKE_TIMEOUT", "600"))
    loop = AgentLoop(
        client=adapter,
        search_chunks_backend=backends["search"],
        chapter_range_backend=backends["chapter_range"],
        list_characters_backend=backends["list_characters"],
        model=model,
        timeout_seconds=timeout_seconds,
    )

    # 任务清单：(pair, run_idx)
    tasks: list[tuple[dict[str, Any], int]] = [
        (p, r) for p in selected for r in range(1, args.runs + 1)
    ]

    concurrency_env = os.environ.get("BOOKSCOPE_PROBE_CONCURRENCY", "5")
    try:
        concurrency = max(1, int(concurrency_env))
    except ValueError:
        concurrency = 5
    # 烟测（单 pair）时不必并发——3 次跑串行更便于观察，且能保证前缀缓存
    # 第一次 miss、后两次命中的时序清晰。全量才并发。
    serial = len(selected) == 1
    print(
        f"[probe] {'串行' if serial else f'并发 {concurrency}'} 跑 "
        f"{len(tasks)} 次"
    )
    print("=" * 64)

    print_lock = threading.Lock()
    runs: list[dict[str, Any]] = []

    def _exec(pair: dict[str, Any], run_idx: int) -> dict[str, Any]:
        rec = _run_once(
            loop=loop, pair=pair, task=pair["_task"], run_idx=run_idx
        )
        sig = rec.get("trace_signals", {})
        with print_lock:
            if rec.get("error"):
                print(
                    f"[probe] {pair['id']} 任务{pair['_task']} run{run_idx} "
                    f"ERR={rec['error']} ({rec.get('duration_s')}s)"
                )
            else:
                print(
                    f"[probe] {pair['id']} 任务{pair['_task']} run{run_idx} "
                    f"完成 {rec['duration_s']}s | iter={sig.get('iterations')} "
                    f"tools={sig.get('tool_call_count')} "
                    f"cite={rec.get('citation_count')}"
                    f"(verified={rec.get('citation_verified_count')}) | "
                    f"in={sig.get('total_input_tokens')} "
                    f"cache_hit={sig.get('cache_hit_tokens')} "
                    f"cache_miss={sig.get('cache_miss_tokens')}"
                )
        return rec

    t_batch = time.monotonic()
    if serial:
        for pair, run_idx in tasks:
            runs.append(_exec(pair, run_idx))
    else:
        with ThreadPoolExecutor(max_workers=concurrency) as ex:
            futs = {
                ex.submit(_exec, pair, run_idx): (pair["id"], run_idx)
                for pair, run_idx in tasks
            }
            for fut in as_completed(futs):
                runs.append(fut.result())
    batch_elapsed = time.monotonic() - t_batch

    # 排序输出（并发时完成顺序乱）
    runs.sort(key=lambda r: (r.get("pair_id", ""), r.get("run_idx", 0)))

    # 跨 run 差异检测（验 L2 真关：3 次答案应有差异）
    diversity = _answer_diversity(runs)

    from bookscope.agent._internal import loop_shared as _loop_shared  # noqa: PLC0415

    payload = {
        "schema": "bookscope-foreshadowing-probe/v1",
        "probe": "foreshadowing-payoff",
        "created_at": time.strftime("%Y-%m-%d"),
        "book": {"title": book_title, "alias": "kuicheng", "chunk_count": len(chunks)},
        "config": {
            "generator_provider": "deepseek",
            "generator_model": model,
            "prompt_version": _loop_shared.current_prompt_version(),
            "l2_cache_disabled": l2_disabled,
            "kg_extracted": False,
            "kg_source": "manual_shell_no_llm_extract",
            "vector_mode": "bm25_only",
            "runs_per_pair": args.runs,
            "mode": "full" if args.run_all else ("single" if args.pair_id else "smoke"),
            "ingest_elapsed_s": round(ingest_elapsed, 1),
        },
        "pairs_dataset": str(_PAIRS_JSON.relative_to(_PROJECT_ROOT)).replace("\\", "/"),
        "runs": runs,
        "answer_diversity": diversity,
        "batch_elapsed_s": round(batch_elapsed, 1),
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("=" * 64)
    print(f"[probe] 写出 {args.output}")
    print(f"[probe] 批耗时 {batch_elapsed:.1f}s")
    _print_summary(runs, diversity)
    return 0


def _answer_diversity(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """按 pair_id 分组，看同一 pair 的多次答案是否完全相同（验 L2 真关）。"""
    by_pair: dict[str, list[str]] = {}
    for r in runs:
        ans = r.get("answer")
        if ans is None:
            continue
        by_pair.setdefault(r["pair_id"], []).append(ans)
    out: dict[str, Any] = {}
    for pid, answers in by_pair.items():
        uniq = len(set(answers))
        out[pid] = {
            "run_count": len(answers),
            "unique_answers": uniq,
            "all_identical": uniq == 1 and len(answers) > 1,
        }
    return out


def _print_summary(
    runs: list[dict[str, Any]], diversity: dict[str, Any]
) -> None:
    print("-" * 64)
    print("[probe] 跨 run 答案差异（验 L2 真关：unique>1 = 每次真重算）：")
    for pid, d in diversity.items():
        flag = "⚠️ 全同(L2 可能没关!)" if d.get("all_identical") else "OK(有差异)"
        print(
            f"  {pid}: {d['run_count']} 次 / "
            f"{d['unique_answers']} 个不同答案 → {flag}"
        )
    print("[probe] 缓存命中（验 DeepSeek 服务端前缀缓存）：")
    for r in runs:
        sig = r.get("trace_signals", {})
        if r.get("error"):
            continue
        hit = sig.get("cache_hit_tokens") or 0
        miss = sig.get("cache_miss_tokens") or 0
        tot = hit + miss
        ratio = f"{hit / tot * 100:.1f}%" if tot else "n/a"
        print(
            f"  {r['pair_id']} run{r['run_idx']}: "
            f"hit={hit} miss={miss} 命中率={ratio}"
        )


if __name__ == "__main__":
    sys.exit(main())
