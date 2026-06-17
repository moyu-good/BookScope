"""跨章概念演进对照 可行性 probe（WP-concept-evolution）。

正例：长上下文回溯真概念的演进阶段，每条 verify——引用真实性 ≥90% + stages 非空。
命根子伪负例：书里没有的概念（量子纠缠/区块链）→ 返空、不编演进（假阳性 ≤20% 硬门槛）。
3 次取众数。书/key 走运行时 env。
"""

from __future__ import annotations

import datetime
import json
import os
from collections import defaultdict
from pathlib import Path

_SYS = (
    "你是 BookScope 的概念演进助手。下面 === 全书原文 === 之后是一本书全文。用户给一个"
    "概念，回溯它在全书怎么一步步发展——每个阶段在哪章、概念被怎么用/深化/转义，按章节"
    "先后。只据原文、不编。\n"
    '严格 JSON：{"stages": [{"order": 序号整数, "chapter": 章号整数, '
    '"development": "这一处概念怎么发展", "snippet": "原文逐字片段"}]}\n'
    'snippet 必须原文逐字出现。**书里没有这个概念就返回 {"stages": []}，绝不编造演进。**'
)
_DELIM = "\n\n=== 全书原文 ===\n"
_POSITIVE = ["制内市场", "国家"]
_NEGATIVE = ["量子纠缠", "区块链"]
_RUNS = 3


def _evolve_once(concept, *, full_text, evidence, client, model):
    from bookscope.agent._internal.llm_cache import invoke_client_cached
    from bookscope.agent.citation_check import verify_citations

    system = _SYS + _DELIM + full_text
    try:
        resp = invoke_client_cached(
            client, model=model, system=system, tools=[],
            messages=[{"role": "user", "content": concept}],
            max_tokens=8000, cache_enabled=False,
        )
        txt = client.extract_final_text(resp)
        obj = json.loads(txt[txt.index("{"): txt.rindex("}") + 1])
        stages = obj.get("stages", [])
        if not isinstance(stages, list):
            stages = []
    except Exception as e:  # noqa: BLE001
        print(f"    （{concept} 解析失败 {type(e).__name__}）")
        return 0, 0
    cits = [
        {"snippet": s.get("snippet", "")}
        for s in stages
        if isinstance(s, dict) and s.get("snippet")
    ]
    verify_citations(cits, evidence)
    return len(stages), sum(1 for c in cits if c.get("verified"))


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
    for label, cs in (("正例", _POSITIVE), ("伪负例", _NEGATIVE)):
        for c in cs:
            for r in range(1, _RUNS + 1):
                total, ver = _evolve_once(
                    c, full_text=full, evidence=evidence, client=client, model=model
                )
                results[c].append({"total": total, "verified": ver})
                print(f"[{label}] {c} run{r}: {total} 阶段、{ver} 核验")

    pos_v = sum(run["verified"] for c in _POSITIVE for run in results[c])
    pos_t = sum(run["total"] for c in _POSITIVE for run in results[c])
    neg_runs = [run for c in _NEGATIVE for run in results[c]]
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
        "schema": "bookscope-concept-evolution-probe/v1",
        "timestamp": stamp.isoformat(timespec="seconds"), "model": model,
        "pos_citation_truth_pct": round(pos_rate, 1), "fp_rate_pct": round(fp_rate, 1),
        "verdict": verdict,
    }
    p = Path("docs/internal/experiments/data") / f"probe-concept-evolution-{stamp:%Y%m%d-%H%M%S}.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[probe] 写出 {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
