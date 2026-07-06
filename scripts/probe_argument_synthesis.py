"""论点综括化 evidence-first 命门 probe（exp-019，验 #47 ② 的 claim 综括改动）。

#47 ② 把论点结构的 claim 从「复述原句」改成「用自己的话综括」（commit 66a7fd2:
_SYSTEM_INSTRUCTION 综括化 + _dedup_near_claims 近似去重）。放开 claim 表达 = 有编造
风险——模型可能综括出书里根本没主张的论点。这个 probe 验这条命门。

**构念 + 门槛**（同 WP-argument-structure-refine §5）：
- 假阳性 = claim 综括出了 evidence / 原文里**没有**的论点（无中生有）。
- **假阳性率 ≤ 20% 是硬门槛**（命根子，同大白话「解释 vs 编造」边界）。
- 次要：综括率（claim 不再照抄 evidence 原句）、条数（跟改前 14+ 比治没治杂）。

**做法**：
- 靶子：理论书（默认 test制内市场，genre=理论/theory）。argument-structure 只对 theory 跑。
- 跑现在生产在用的 `generate_argument_structure_exhaustive`（新 prompt）+ 同书同参数跑一遍
  改前 prompt 当 baseline 对照（feedback_baseline_variance_first：别拿单次当 ground truth）。
- **关 L2 缓存**（BOOKSCOPE_LLM_CACHE_DISABLED=1）保证跑的是新 prompt、不吃旧缓存。
- 每条 evidence 过 verify_citations（evidence-first：evidence 必须逐字锚原文）。
- 把每条 claim/evidence/verified/章号 + 归一化后 claim==evidence 的判定 dump 成 JSON，
  供人工逐条核假阳性（claim 有没有 evidence 撑不了的论点）。

跑法::

    export DEEPSEEK_API_KEY=sk-xxx   # 或写进 .env
    BOOKSCOPE_LLM_CACHE_DISABLED=1 \
    BOOKSCOPE_SMOKE_EPUB="tests/file/test制内市场：中国国家主导型政治经济学).epub" \
    python scripts/probe_argument_synthesis.py

本脚本只跑 + dump 数据，不改产品代码。假阳性由分析员对 dump 出的 JSON 逐条人工判。
"""

from __future__ import annotations

import datetime
import json
import os
import sys
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass


# 改前 prompt（commit 66a7fd2^ 的 _SYSTEM_INSTRUCTION，逐字复刻）——只作 baseline 对照，
# 不进产品。改后 prompt 直接从 argument_structure 模块读现役 _SYSTEM_INSTRUCTION。
_OLD_INSTRUCTION = (
    "你是 BookScope 的论点梳理助手。"
    "请梳理这本书的主要论点结构——作者主张了什么、靠什么撑。按论证推进顺序排，"
    "每条给：主张（一句）、所在章节、一句原文逐字证据。只据原文、不编。\n"
    "严格输出 JSON（不要别的话、不要 markdown 代码围栏）：\n"
    '{"claims": [{"order": 序号整数, "claim": "主张一句", '
    '"chapter": 章号整数, "evidence": "原文逐字片段"}]}\n'
    "order 从 1 起递增。只列书里真有的主要论点（最多约 20 条），"
    "evidence 必须是原文里逐字出现的句子。"
)

_RUNS = 3
_USER_MSG = "请梳理下面这段原文里出现的主要论点（只列本段的）。"


def _load_dotenv() -> None:
    """把仓库根 .env 里的 KEY=VAL 读进 os.environ（不覆盖已存在的）。"""
    env_path = _PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def _run_variant(
    *,
    instruction: str,
    apply_dedup: bool,
    chunks: list[dict[str, Any]],
    client: Any,
    model: str,
) -> list[dict[str, Any]] | None:
    """跑一遍 map-reduce 抽论点（复刻 generate_argument_structure_exhaustive 的流程，
    但显式传 instruction + 可切 dedup，好做改前/改后对照）。返回带 verified 的 claims。
    """
    from bookscope.agent._internal.exhaustive import merge_by_key, run_segments
    from bookscope.agent.argument_structure import (
        _dedup_near_claims,  # noqa: PLC0415
        _parse_claims,  # noqa: PLC0415
        _verify_claims,  # noqa: PLC0415
    )

    # cache_enabled=False 双保险：env BOOKSCOPE_LLM_CACHE_DISABLED=1 是全局开关，
    # 这里再显式关一道（run_segments 默认开缓存，对照 baseline 必须关）。
    outs = run_segments(
        chunks=chunks,
        instruction=instruction,
        user_msg=_USER_MSG,
        parse_fn=_parse_claims,
        llm_client=client,
        model=model,
        max_tokens=8000,
        cache_enabled=False,
    )
    merged = merge_by_key(outs, key_fn=lambda c: c.get("claim"))
    if not merged:
        return None
    if apply_dedup:
        merged = _dedup_near_claims(merged)
    merged.sort(key=lambda c: c["chapter"])
    for i, c in enumerate(merged, 1):
        c["order"] = i
    _verify_claims(merged, chunks)
    return merged


def _echoes_evidence(claim: str, evidence: str) -> bool:
    """claim 归一化后是否约等于 evidence（复读判定，用 argument_structure 那套 _norm_claim）。"""
    from bookscope.agent.argument_structure import _norm_claim  # noqa: PLC0415

    nc = _norm_claim(claim)
    ne = _norm_claim(evidence)
    if not nc or not ne:
        return False
    return nc == ne or (min(len(nc), len(ne)) >= 8 and (nc in ne or ne in nc))


def _summarize(claims: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(claims)
    verified = sum(1 for c in claims if c.get("verified"))
    echoed = sum(1 for c in claims if _echoes_evidence(c.get("claim", ""), c.get("evidence", "")))
    return {
        "count": n,
        "verified": verified,
        "verified_pct": round(verified / n * 100, 1) if n else 0.0,
        "echoed_evidence": echoed,
        "synthesis_pct": round((n - echoed) / n * 100, 1) if n else 0.0,
    }


def main() -> int:
    _load_dotenv()
    from scripts.smoke_test_r1 import (  # type: ignore[import-not-found]  # noqa: PLC0415
        _build_adapter_and_model,
        _load_book_session,
    )

    provider = os.environ.setdefault("BOOKSCOPE_SMOKE_PROVIDER", "deepseek")
    if os.environ.get("BOOKSCOPE_LLM_CACHE_DISABLED") != "1":
        print("[probe] 警告：BOOKSCOPE_LLM_CACHE_DISABLED != 1，可能吃旧缓存。已在脚本内强制关。")
        os.environ["BOOKSCOPE_LLM_CACHE_DISABLED"] = "1"

    client, model = _build_adapter_and_model(provider)
    print(f"[probe] provider={provider} model={model}  L2 缓存=关")

    book, chunks_obj, _kg, _vs = _load_book_session()
    from bookscope.agent.backends.r0_assembler import R0BookAssembler  # noqa: PLC0415

    asm = R0BookAssembler(
        book_text=book, chunks=chunks_obj, knowledge_graph=_kg, session_vector_store=_vs
    )
    full = asm._book_text.raw_text  # noqa: SLF001
    c2ch = asm._compute_chunk_to_chapter_map()  # noqa: SLF001
    chunks = [
        {"chunk_id": f"r0-chunk-{c.index}", "chapter": c2ch.get(c.index, 0), "text": c.text}
        for c in asm._chunks  # noqa: SLF001
    ]
    print(f"[probe] 书名={book.title}  全书 {len(full)} 字符  chunk {len(chunks)} 段")

    # 题材门控：确认它是 theory（argument-structure 只对 theory 跑）。
    from bookscope.agent.genre_detect import detect_genre, genre_to_argument_axis  # noqa: PLC0415

    toc_titles: list[str] = []
    try:
        toc_titles = [
            (c.text.split("\n", 1)[0] or "").strip()
            for c in asm._chunks[:40]  # noqa: SLF001
        ]
    except Exception:  # noqa: BLE001
        pass
    genre = detect_genre(
        title=book.title,
        toc_titles=[t for t in toc_titles if t][:30],
        sample_text=full[:2000],
        llm_client=client,
        model=model,
    )
    axis = genre_to_argument_axis(genre or None)
    print(f"[probe] 检测题材={genre!r} → argument 轴={axis!r}")
    if axis != "theory":
        print(f"[probe] 警告：非 theory 轴（{axis!r}），argument 会退场；仍继续跑做记录。")

    from bookscope.agent.argument_structure import _SYSTEM_INSTRUCTION  # noqa: PLC0415

    stamp = datetime.datetime.now()
    variants = [
        ("new", _SYSTEM_INSTRUCTION, True),   # 改后（现役）prompt + 近似去重
        ("old", _OLD_INSTRUCTION, False),     # 改前 prompt（baseline 对照）
    ]
    all_runs: list[dict[str, Any]] = []
    agg: dict[str, list[dict[str, Any]]] = {"new": [], "old": []}

    for name, instr, dedup in variants:
        print(f"\n=== 变体 {name}（dedup={dedup}）===")
        for r in range(1, _RUNS + 1):
            claims = _run_variant(
                instruction=instr, apply_dedup=dedup, chunks=chunks, client=client, model=model
            ) or []
            summ = _summarize(claims)
            agg[name].append(summ)
            print(
                f"[{name}] run{r}: {summ['count']} 条  "
                f"综括率 {summ['synthesis_pct']}%（照抄 {summ['echoed_evidence']} 条）  "
                f"evidence 核验 {summ['verified']}/{summ['count']} = {summ['verified_pct']}%"
            )
            all_runs.append({
                "variant": name,
                "run": r,
                "summary": summ,
                "claims": [
                    {
                        "order": c.get("order"),
                        "chapter": c.get("chapter"),
                        "claim": c.get("claim", ""),
                        "evidence": c.get("evidence", ""),
                        "verified": bool(c.get("verified", False)),
                        "echoes_evidence": _echoes_evidence(
                            c.get("claim", ""), c.get("evidence", "")
                        ),
                    }
                    for c in claims
                ],
            })

    def _avg(rows: list[dict[str, Any]], key: str) -> float:
        return round(sum(x[key] for x in rows) / len(rows), 1) if rows else 0.0

    print("\n=== 改前 / 改后对照（3 次均值）===")
    for name in ("old", "new"):
        rows = agg[name]
        print(
            f"[{name}] 均条数 {_avg(rows, 'count')}  "
            f"均综括率 {_avg(rows, 'synthesis_pct')}%  "
            f"均 evidence 核验率 {_avg(rows, 'verified_pct')}%"
        )

    out = {
        "schema": "bookscope-argument-synthesis-probe/v1",
        "exp": "exp-019",
        "timestamp": stamp.isoformat(timespec="seconds"),
        "provider": provider,
        "model": model,
        "book_title": book.title,
        "book_chars": len(full),
        "n_chunks": len(chunks),
        "genre_detected": genre,
        "argument_axis": axis,
        "cache_disabled": True,
        "runs_per_variant": _RUNS,
        "note": (
            "假阳性（claim 综括出 evidence/原文没有的论点）由分析员对本文件里各 claim 逐条人工判，"
            "不在脚本内自动算——脚本只出 evidence 核验率 + 综括率 + 条数当客观量。"
        ),
        "aggregate": {
            name: {
                "avg_count": _avg(agg[name], "count"),
                "avg_synthesis_pct": _avg(agg[name], "synthesis_pct"),
                "avg_verified_pct": _avg(agg[name], "verified_pct"),
                "per_run": agg[name],
            }
            for name in ("old", "new")
        },
        "runs": all_runs,
    }
    data_dir = _PROJECT_ROOT / "docs" / "internal" / "experiments" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    p = data_dir / f"exp019-argument-synthesis-{stamp:%Y%m%d-%H%M%S}.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[probe] 写出原始数据 → {p}")
    print("[probe] 假阳性逐条人工核：读该 JSON 的 runs[].claims，对照 evidence 判编造。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
