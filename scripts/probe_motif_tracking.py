"""主题母题追踪 可行性 probe（WP-motif-tracking）。

正例：长上下文回溯真母题的复现处，每条 verify——引用真实性 ≥90% + 非空。
命根子伪负例：书里没有的母题（赛博朋克/星际旅行）→ 返空、不编复现（假阳性 ≤20% 硬门槛）。
3 次取众数。书/key 走运行时 env。
"""

from __future__ import annotations

import datetime
import json
import os
from collections import defaultdict
from pathlib import Path

_SYS = (
    "你是 BookScope 的母题追踪助手。下面 === 全书原文 === 之后是一本书全文。用户给一个"
    "主题/母题，回溯它在全书的复现——每处在哪章、怎么体现这个母题，按章节先后。只据原文、不编。\n"
    '严格 JSON：{"occurrences": [{"order": 序号整数, "chapter": 章号整数, '
    '"manifestation": "这处怎么体现该母题", "snippet": "原文逐字片段"}]}\n'
    'snippet 必须原文逐字出现。**书里没有这个母题就返回 {"occurrences": []}，绝不编造复现。**'
)
_DELIM = "\n\n=== 全书原文 ===\n"
_POSITIVE = ["宣传", "正统"]
_NEGATIVE = ["赛博朋克", "星际旅行"]
_RUNS = 3


def _track_once(motif, *, full_text, evidence, client, model):
    from bookscope.agent._internal.llm_cache import invoke_client_cached
    from bookscope.agent.citation_check import verify_citations

    system = _SYS + _DELIM + full_text
    try:
        resp = invoke_client_cached(
            client, model=model, system=system, tools=[],
            messages=[{"role": "user", "content": motif}],
            max_tokens=8000, cache_enabled=False,
        )
        txt = client.extract_final_text(resp)
        obj = json.loads(txt[txt.index("{"): txt.rindex("}") + 1])
        occ = obj.get("occurrences", [])
        if not isinstance(occ, list):
            occ = []
    except Exception as e:  # noqa: BLE001
        print(f"    （{motif} 解析失败 {type(e).__name__}）")
        return 0, 0
    cits = [
        {"snippet": o.get("snippet", "")}
        for o in occ
        if isinstance(o, dict) and o.get("snippet")
    ]
    verify_citations(cits, evidence)
    return len(occ), sum(1 for c in cits if c.get("verified"))


def main() -> int:
    from bookscope.agent.backends.r0_assembler import R0BookAssembler
    from scripts.smoke_test_r1 import (  # type: ignore[import-not-found]
        _build_adapter_and_model,
        _load_book_session,
    )

    provider = os.environ.setdefault("BOOKSCOPE_SMOKE_PROVIDER", "deepseek")
    client, model = _build_adapter_and_model(provider)
    print(f"[probe] {provider}/{model}")
    book, chunks, kg, vs = _load_book_session()
    asm = R0BookAssembler(
        book_text=book, chunks=chunks, knowledge_graph=kg, session_vector_store=vs
    )
    full = asm._book_text.raw_text  # noqa: SLF001
    c2ch = asm._compute_chunk_to_chapter_map()  # noqa: SLF001
    evidence = {
        f"r0-chunk-{c.index}": {"chapter": c2ch.get(c.index, 0), "text": c.text}
        for c in asm._chunks  # noqa: SLF001
    }
    print(f"[probe] 全书 {len(full)} 字符\n")

    results: dict[str, list] = defaultdict(list)
    for label, ms in (("正例", _POSITIVE), ("伪负例", _NEGATIVE)):
        for m in ms:
            for r in range(1, _RUNS + 1):
                total, ver = _track_once(
                    m, full_text=full, evidence=evidence, client=client, model=model
                )
                results[m].append({"total": total, "verified": ver})
                print(f"[{label}] {m} run{r}: {total} 处、{ver} 核验")

    pos_v = sum(run["verified"] for m in _POSITIVE for run in results[m])
    pos_t = sum(run["total"] for m in _POSITIVE for run in results[m])
    neg_runs = [run for m in _NEGATIVE for run in results[m]]
    fp = sum(1 for run in neg_runs if run["total"] > 0)
    fp_rate = fp / len(neg_runs) * 100 if neg_runs else 0.0
    pos_rate = pos_v / pos_t * 100 if pos_t else 0.0

    print("\n=== 判定 ===")
    print(f"正例 引用真实性：{pos_v}/{pos_t} = {pos_rate:.1f}%")
    print(f"伪负例 假阳性率：{fp}/{len(neg_runs)} = {fp_rate:.1f}%（≤20% 硬门槛）")
    verdict = "GO" if fp_rate <= 20 and pos_rate >= 90 and pos_t > 0 else "NO-GO"
    print(f"==> {verdict}")

    stamp = datetime.datetime.now()
    out = {
        "schema": "bookscope-motif-probe/v1", "timestamp": stamp.isoformat(timespec="seconds"),
        "model": model, "pos_citation_truth_pct": round(pos_rate, 1),
        "fp_rate_pct": round(fp_rate, 1), "verdict": verdict,
    }
    p = Path("docs/internal/experiments/data") / f"probe-motif-tracking-{stamp:%Y%m%d-%H%M%S}.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[probe] 写出 {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
