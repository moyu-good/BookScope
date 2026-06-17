"""文体级毛病检测 可行性 probe（WP-style-issues）。

正例（保守性 / 不 cry wolf）：扫 anshi（已编辑出版）的文体毛病，报的数不爆炸 + 每条
snippet 原文核验过。命根子伪负例：要它确认不存在的文体毛病（如某外书词"反复出现"），
看它编不编（假阳性 ≤20% 硬门槛）。3 次取众数。书/key 走运行时 env。
"""

from __future__ import annotations

import datetime
import json
import os
from pathlib import Path

_SCAN_SYS = (
    "你是 BookScope 的文体审稿助手。下面 === 全书原文 === 之后是一本书全文。"
    "扫文体级毛病：用词重复（某词/短语成口头禅）、视角越界（限知视角写了视角人物不该"
    "知道的内心/事）、支线失踪（埋的支线/人物后文没交代）。**保守，只报清楚的、宁缺毋滥。**\n"
    '严格 JSON：{"issues": [{"type": "repetition|pov|dropped_thread", '
    '"what": "问题描述", "snippet": "原文逐字片段", "chapter": 章号整数}]}\n'
    "snippet 必须原文逐字出现。没有清楚的毛病就返回 {\"issues\": []}，绝不凑数。"
)
_FALSE_SYS = (
    "下面 === 全书原文 === 之后是一本书全文。用户会问某个文体毛病是否存在。"
    "只据原文判断。\n"
    '严格 JSON：{"is_problem": true 或 false, "snippet": "证据原文逐字片段或空串"}\n'
    "**不存在就 is_problem=false、snippet=\"\"，绝不编造。**"
)
_DELIM = "\n\n=== 全书原文 ===\n"
_FALSE_QS = [
    "「区块链」这个词在书里是不是反复出现、成了作者的口头禅？",
    "书里是不是有个叫「小明」的现代人物贯穿全书？",
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
    scan_sys = _SCAN_SYS + _DELIM + full
    false_sys = _FALSE_SYS + _DELIM + full

    pos_v = pos_t = 0
    counts = []
    for r in range(1, _RUNS + 1):
        obj = _call(scan_sys, "请扫这本书的文体毛病。", client=client, model=model)
        issues = obj.get("issues", []) if isinstance(obj, dict) else []
        cits = [
            {"snippet": x.get("snippet", "")}
            for x in issues
            if isinstance(x, dict) and x.get("snippet")
        ]
        verify_citations(cits, evidence)
        ver = sum(1 for c in cits if c.get("verified"))
        pos_v += ver
        pos_t += len(cits)
        counts.append(len(issues))
        print(f"[正例] run{r}: 报 {len(issues)} 条毛病、{ver}/{len(cits)} 原文核验过")

    fp = tot = 0
    for q in _FALSE_QS:
        for r in range(1, _RUNS + 1):
            obj = _call(false_sys, q, client=client, model=model)
            is_prob = bool(obj.get("is_problem")) if isinstance(obj, dict) else False
            snip = obj.get("snippet", "") if isinstance(obj, dict) else ""
            bad = is_prob and bool(snip)
            fp += 1 if bad else 0
            tot += 1
            print(f"[伪负例] {q[:12]}… run{r}: is_problem={is_prob} {'← 假阳性' if bad else 'OK'}")

    pos_rate = pos_v / pos_t * 100 if pos_t else 0.0
    fp_rate = fp / tot * 100 if tot else 0.0
    avg_issues = sum(counts) / len(counts) if counts else 0
    print("\n=== 判定 ===")
    print(f"正例 原文核验率：{pos_v}/{pos_t} = {pos_rate:.1f}%；平均报 {avg_issues:.1f} 条/次")
    print(f"伪负例 假阳性率：{fp}/{tot} = {fp_rate:.1f}%（≤20% 硬门槛）")
    verdict = "GO" if fp_rate <= 20 and pos_rate >= 90 and pos_t > 0 else "NO-GO"
    print(f"==> {verdict}")

    stamp = datetime.datetime.now()
    out = {
        "schema": "bookscope-style-probe/v1", "timestamp": stamp.isoformat(timespec="seconds"),
        "model": model, "pos_verify_pct": round(pos_rate, 1),
        "avg_issues": round(avg_issues, 1), "fp_rate_pct": round(fp_rate, 1), "verdict": verdict,
    }
    p = Path("docs/internal/experiments/data") / f"probe-style-issues-{stamp:%Y%m%d-%H%M%S}.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[probe] 写出 {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
