"""知识点卡片 可行性 probe（WP-study-cards）。

正例：长上下文据书出知识点卡片，每条 snippet 过核验——引用真实性 ≥90% + 非空。
命根子伪负例：问书里没教的知识点（量子计算/光合作用），看它编不编（假阳性 ≤20% 硬门槛）。
3 次取众数。书/key 走运行时 env。
"""

from __future__ import annotations

import datetime
import json
import os
from pathlib import Path

_EXTRACT_SYS = (
    "你是 BookScope 的学习卡片助手。下面 === 全书原文 === 之后是一本书全文。据书出知识点"
    "卡片，每张给：知识点名、解释、一道苏格拉底式自测题、一句原文逐字依据、章节。只据原文、不编。\n"
    '严格 JSON：{"cards": [{"order": 序号整数, "concept": "知识点名", "point": "解释", '
    '"question": "苏格拉底自测题", "snippet": "原文逐字依据", "chapter": 章号整数}]}\n'
    "snippet 必须原文逐字出现。"
)
_FALSE_SYS = (
    "下面 === 全书原文 === 之后是一本书全文。用户会问这本书是否讲解了某个知识点。"
    "只据原文判断。\n"
    '严格 JSON：{"taught": true 或 false, "evidence": ["讲解该知识点的原文逐字片段"]}\n'
    "**书里没讲就 taught=false、evidence=[]，绝不编造。**"
)
_DELIM = "\n\n=== 全书原文 ===\n"
_FALSE_QS = [
    "这本书是否讲解了「量子计算的基本原理」？",
    "这本书是否讲解了「光合作用的生化机制」？",
]
_RUNS = 3


def _call(system, user, *, client, model):
    from bookscope.agent._internal.llm_cache import invoke_client_cached
    try:
        resp = invoke_client_cached(
            client, model=model, system=system, tools=[],
            messages=[{"role": "user", "content": user}],
            max_tokens=8000, cache_enabled=False,
        )
        txt = client.extract_final_text(resp)
        return json.loads(txt[txt.index("{"): txt.rindex("}") + 1])
    except Exception as e:  # noqa: BLE001
        print(f"    (解析失败 {type(e).__name__})")
        return None


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
    full = asm._book_text.raw_text  # noqa: SLF001
    c2ch = asm._compute_chunk_to_chapter_map()  # noqa: SLF001
    evidence = {
        f"r0-chunk-{c.index}": {"chapter": c2ch.get(c.index, 0), "text": c.text}
        for c in asm._chunks  # noqa: SLF001
    }
    print(f"[probe] 全书 {len(full)} 字符\n")
    ex_sys = _EXTRACT_SYS + _DELIM + full
    fa_sys = _FALSE_SYS + _DELIM + full

    pos_v = pos_t = 0
    for r in range(1, _RUNS + 1):
        obj = _call(ex_sys, "请据这本书出知识点卡片。", client=client, model=model)
        cards = obj.get("cards", []) if isinstance(obj, dict) else []
        cits = [
            {"snippet": c.get("snippet", "")}
            for c in cards
            if isinstance(c, dict) and c.get("snippet")
        ]
        verify_citations(cits, evidence)
        ver = sum(1 for c in cits if c.get("verified"))
        pos_v += ver
        pos_t += len(cits)
        print(f"[正例] run{r}: {len(cards)} 卡、{ver}/{len(cits)} 依据核验过")

    fp = tot = 0
    for q in _FALSE_QS:
        for r in range(1, _RUNS + 1):
            obj = _call(fa_sys, q, client=client, model=model)
            taught = bool(obj.get("taught")) if isinstance(obj, dict) else False
            ev = obj.get("evidence", []) if isinstance(obj, dict) else []
            bad = taught and len(ev) > 0
            fp += 1 if bad else 0
            tot += 1
            print(f"[伪负例] {q[:14]}… run{r}: taught={taught} {'← 假阳性' if bad else 'OK'}")

    pos_rate = pos_v / pos_t * 100 if pos_t else 0.0
    fp_rate = fp / tot * 100 if tot else 0.0
    print("\n=== 判定 ===")
    print(f"正例 引用真实性：{pos_v}/{pos_t} = {pos_rate:.1f}%")
    print(f"伪负例 假阳性率：{fp}/{tot} = {fp_rate:.1f}%（≤20% 硬门槛）")
    verdict = "GO" if fp_rate <= 20 and pos_rate >= 90 and pos_t > 0 else "NO-GO"
    print(f"==> {verdict}")

    stamp = datetime.datetime.now()
    out = {
        "schema": "bookscope-study-cards-probe/v1",
        "timestamp": stamp.isoformat(timespec="seconds"), "model": model,
        "pos_citation_truth_pct": round(pos_rate, 1), "fp_rate_pct": round(fp_rate, 1),
        "verdict": verdict,
    }
    p = Path("docs/internal/experiments/data") / f"probe-study-cards-{stamp:%Y%m%d-%H%M%S}.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[probe] 写出 {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
