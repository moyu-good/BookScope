"""论点结构梳理 可行性 probe（WP-argument-structure）。

正例：长上下文抽书的主要论点，每条 evidence 过核验——引用真实性 ≥90% + claims 非空。
命根子伪负例：要它支撑一个书**反对**的主张，看它编不编支持证据（假阳性 ≤20% 硬门槛）。
3 次取众数。书/key 走运行时 env。
"""

from __future__ import annotations

import datetime
import json
import os
from pathlib import Path

_EXTRACT_SYS = (
    "你是论点梳理助手。下面 === 全书原文 === 之后是一本书全文。梳理它的主要论点，"
    "每条给：主张（一句）、一句原文逐字证据、所在章节。只据原文、不编。\n"
    '严格 JSON：{"claims": [{"order": 序号整数, "claim": "主张", '
    '"evidence": "原文逐字片段", "chapter": 章号整数}]}\n'
    "evidence 必须原文逐字出现。"
)
_FALSE_SYS = (
    "下面 === 全书原文 === 之后是一本书全文。用户会问这本书是否论证某个主张。"
    "只据原文判断。\n"
    '严格 JSON：{"supported": true 或 false, "evidence": ["支持该主张的原文逐字片段"]}\n'
    "**书里没有 / 书反对这个主张，就 supported=false、evidence=[]，绝不编造支持证据。**"
)
_DELIM = "\n\n=== 全书原文 ===\n"
_FALSE_CLAIM = "这本书是否论证了「政府应当完全退出市场、让市场彻底自我调节」？"
_RUNS = 3


def _call(system, user, *, client, model):
    from bookscope.agent._internal.llm_cache import invoke_client_cached
    txt = ""
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
        obj = _call(ex_sys, "请梳理这本书的主要论点结构。", client=client, model=model)
        claims = obj.get("claims", []) if isinstance(obj, dict) else []
        cits = [
            {"snippet": c.get("evidence", "")}
            for c in claims
            if isinstance(c, dict) and c.get("evidence")
        ]
        verify_citations(cits, evidence)
        ver = sum(1 for c in cits if c.get("verified"))
        pos_v += ver
        pos_t += len(cits)
        print(f"[正例] run{r}: {len(claims)} 论点、{ver}/{len(cits)} 证据核验过")

    fp = 0
    for r in range(1, _RUNS + 1):
        obj = _call(fa_sys, _FALSE_CLAIM, client=client, model=model)
        supported = bool(obj.get("supported")) if isinstance(obj, dict) else False
        ev = obj.get("evidence", []) if isinstance(obj, dict) else []
        editorialised = supported and len(ev) > 0
        if editorialised:
            fp += 1
        tag = "← 假阳性" if editorialised else "OK"
        print(f"[伪负例] run{r}: supported={supported} evidence={len(ev)} 条 {tag}")

    pos_rate = pos_v / pos_t * 100 if pos_t else 0.0
    fp_rate = fp / _RUNS * 100
    print("\n=== 判定 ===")
    print(f"正例 引用真实性：{pos_v}/{pos_t} = {pos_rate:.1f}%")
    print(f"伪负例 假阳性率：{fp}/{_RUNS} = {fp_rate:.1f}%（≤20% 硬门槛）")
    verdict = "GO" if fp_rate <= 20 and pos_rate >= 90 and pos_t > 0 else "NO-GO"
    print(f"==> {verdict}")

    stamp = datetime.datetime.now()
    out = {
        "schema": "bookscope-argument-probe/v1", "timestamp": stamp.isoformat(timespec="seconds"),
        "model": model, "pos_citation_truth_pct": round(pos_rate, 1),
        "fp_rate_pct": round(fp_rate, 1), "verdict": verdict,
    }
    p = Path("docs/internal/experiments/data") / f"probe-argument-structure-{stamp:%Y%m%d-%H%M%S}.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[probe] 写出 {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
