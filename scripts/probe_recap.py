"""无剧透情节回顾 可行性 probe（WP-recap）。

只把第 1..X 章拼进 context（后文物理上不喂），回顾前情。验：① 正例引用真实性 ≥90% +
**所有 cited chapter ≤ X（零后文泄漏）**；② 命根子——问"结局如何"看它老实说没读到、不编。
书/key 走运行时 env。
"""

from __future__ import annotations

import datetime
import json
import os
from pathlib import Path

_RECAP_SYS = (
    "你是 BookScope 的前情回顾助手。下面 === 读到此处的原文 === 之后是一本书"
    "**读到第 {X} 章为止**的原文（后文没有给你）。回顾到此为止的关键人物、事件、线索。"
    "只据给出的原文、不臆测、不编。\n"
    '严格 JSON：{{"points": [{{"order": 序号整数, "point": "前情要点一句", '
    '"chapter": 章号整数, "snippet": "原文逐字片段"}}]}}\n'
    "snippet 必须是给出原文里逐字出现的句子。"
)
_DELIM = "\n\n=== 读到此处的原文 ===\n"
_SPOILER_Q = "这本书最后的结局是什么？后半段还发生了哪些大事？"
_RUNS = 3


def _call(system, user, *, client, model):
    from bookscope.agent._internal.llm_cache import invoke_client_cached
    try:
        resp = invoke_client_cached(
            client, model=model, system=system, tools=[],
            messages=[{"role": "user", "content": user}],
            max_tokens=8000, cache_enabled=False,
        )
        return client.extract_final_text(resp)
    except Exception as e:  # noqa: BLE001
        print(f"    (调用失败 {type(e).__name__})")
        return ""


def main() -> int:
    from bookscope.agent.backends.r0_assembler import R0BookAssembler
    from bookscope.agent.citation_check import verify_citations
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
    c2ch = asm._compute_chunk_to_chapter_map()  # noqa: SLF001
    all_chunks = list(asm._chunks)  # noqa: SLF001
    max_ch = max((c2ch.get(c.index, 0) for c in all_chunks), default=0)
    X = max(1, max_ch // 2)
    print(f"[probe] 全书最大章 {max_ch}，截到第 {X} 章")

    # 只取 1..X 章的 chunk 拼上下文 + 当 evidence（后文不喂）
    partial = [c for c in all_chunks if 1 <= c2ch.get(c.index, 0) <= X]
    partial_text = "".join(c.text for c in partial)
    evidence = {
        f"r0-chunk-{c.index}": {"chapter": c2ch.get(c.index, 0), "text": c.text}
        for c in partial
    }
    print(f"[probe] ≤{X} 章：{len(partial)} chunk、{len(partial_text)} 字符\n")

    recap_sys = _RECAP_SYS.format(X=X) + _DELIM + partial_text

    pos_v = pos_t = leaks = 0
    for r in range(1, _RUNS + 1):
        txt = _call(recap_sys, "请回顾到目前为止的前情。", client=client, model=model)
        try:
            obj = json.loads(txt[txt.index("{"): txt.rindex("}") + 1])
            points = obj.get("points", [])
        except Exception:  # noqa: BLE001
            points = []
        cits = [
            {"chapter": p.get("chapter", 0), "snippet": p.get("snippet", "")}
            for p in points if isinstance(p, dict) and p.get("snippet")
        ]
        verify_citations(cits, evidence)
        ver = sum(1 for c in cits if c.get("verified"))
        # 泄漏：verified 的 citation 命中的真章号 > X（后文泄漏；构造上应为 0）
        leak = sum(1 for c in cits if c.get("verified") and c.get("chapter", 0) > X)
        pos_v += ver
        pos_t += len(cits)
        leaks += leak
        print(f"[正例] run{r}: {len(points)} 要点、{ver}/{len(cits)} 核验、后文泄漏 {leak}")

    # 命根子：问结局（后文）——只喂 ≤X，应老实说没读到
    print("\n[命根子] 问结局（只喂 ≤X 上下文）：")
    spoiler_ans = _call(recap_sys, _SPOILER_Q, client=client, model=model)
    print("  模型答：", spoiler_ans[:140].replace("\n", " "))

    pos_rate = pos_v / pos_t * 100 if pos_t else 0.0
    print("\n=== 判定 ===")
    print(f"正例 引用真实性：{pos_v}/{pos_t} = {pos_rate:.1f}%")
    print(f"后文泄漏（cited chapter > X 的 verified 数）：{leaks}（应为 0）")
    verdict = "GO" if pos_rate >= 90 and leaks == 0 and pos_t > 0 else "NO-GO"
    print(f"==> {verdict}")

    stamp = datetime.datetime.now()
    out = {
        "schema": "bookscope-recap-probe/v1", "timestamp": stamp.isoformat(timespec="seconds"),
        "model": model, "up_to_chapter": X, "max_chapter": max_ch,
        "pos_citation_truth_pct": round(pos_rate, 1), "spoiler_leaks": leaks,
        "spoiler_answer_head": spoiler_ans[:300], "verdict": verdict,
    }
    p = Path("docs/internal/experiments/data") / f"probe-recap-{stamp:%Y%m%d-%H%M%S}.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[probe] 写出 {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
