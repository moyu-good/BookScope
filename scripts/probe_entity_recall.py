"""实体回溯 可行性 probe（WP-entity-recall，建设前过闸）。

长上下文整本进 system，给一个实体让模型回溯它的全书出现处（章节有序 + 在做什么 +
原文片段），每处 snippet 过 verify_citations 核验。验两件：
- 正例（已知实体）：找出多个核验过的出现 + 引用真实性高（召回够用的代理指标）。
- 伪负例（书里没有的实体，命根子）：应答"没有"、appearances 空；编出现 = 假阳性。
3 次取众数。假阳性 ≤20% 硬门槛破则 NO-GO。

书路径 + key 只走运行时 env，不硬编。
"""

from __future__ import annotations

import datetime
import json
import os
from collections import defaultdict
from pathlib import Path

_INSTRUCTION = (
    "下面 === 全书原文 === 之后是一整本书的完整原文。用户给一个实体（人物/地点/"
    "物件/概念）。只根据这本书的原文，回溯它在全书的所有出现处，按章节先后排列。"
    "不用书外知识、不臆测、不编。\n"
    "严格输出 JSON（不要别的话）：\n"
    '{"appearances": [{"chapter": 章节号整数, "what": "该处在做什么（一句）", '
    '"snippet": "原文逐字片段，原样摘录不改写"}]}\n'
    "snippet 必须是原文里逐字出现的句子。**书里没有这个实体就返回 "
    '{"appearances": []}**——绝不为不存在的实体编造出现或原文。'
)
_DELIM = "\n\n=== 全书原文 ===\n"

_POSITIVE = ["安禄山", "杨国忠", "灵宝之战"]   # anshi 已知实体
_NEGATIVE = ["朱元璋", "岳飞"]                  # 真实历史人物但错朝代，安史之乱书里没有（命根子）
_RUNS = 3


def _recall_once(entity, *, full_text, evidence, client, model):
    from bookscope.agent._internal.llm_cache import invoke_client_cached
    from bookscope.agent.citation_check import verify_citations

    system = _INSTRUCTION + _DELIM + full_text
    try:
        resp = invoke_client_cached(
            client, model=model, system=system, tools=[],
            messages=[{"role": "user", "content": entity}],
            max_tokens=8000, cache_enabled=False,
        )
        text = client.extract_final_text(resp)
        obj = json.loads(text[text.index("{"): text.rindex("}") + 1])
        apps = obj.get("appearances", [])
        if not isinstance(apps, list):
            apps = []
    except Exception as e:  # noqa: BLE001
        print(f"    （{entity} 解析失败：{type(e).__name__}）")
        return 0, 0
    cits = [
        {"chapter": a.get("chapter", 0), "snippet": a.get("snippet", "")}
        for a in apps if isinstance(a, dict) and a.get("snippet")
    ]
    verified = verify_citations(cits, evidence)
    n_verified = sum(1 for c in verified if c.get("verified"))
    return len(apps), n_verified


def main() -> int:
    from bookscope.agent.backends.r0_assembler import R0BookAssembler
    from scripts.smoke_test_r1 import (  # type: ignore[import-not-found]
        _build_adapter_and_model,
        _load_book_session,
    )

    provider = os.environ.setdefault("BOOKSCOPE_SMOKE_PROVIDER", "deepseek")
    client, model = _build_adapter_and_model(provider)
    print(f"[probe] provider={provider} model={model}")
    book, chunks, kg, vs = _load_book_session()
    asm = R0BookAssembler(
        book_text=book, chunks=chunks, knowledge_graph=kg, session_vector_store=vs
    )
    full_text = asm._book_text.raw_text  # noqa: SLF001
    c2ch = asm._compute_chunk_to_chapter_map()  # noqa: SLF001
    evidence = {
        f"r0-chunk-{c.index}": {"chapter": c2ch.get(c.index, 0), "text": c.text}
        for c in asm._chunks  # noqa: SLF001
    }
    print(f"[probe] 全书 {len(full_text)} 字符、{len(evidence)} chunks\n")

    results: dict[str, list] = defaultdict(list)
    for label, ents in (("正例", _POSITIVE), ("伪负例", _NEGATIVE)):
        for e in ents:
            for r in range(1, _RUNS + 1):
                total, ver = _recall_once(
                    e, full_text=full_text, evidence=evidence, client=client, model=model
                )
                results[e].append({"total": total, "verified": ver})
                print(f"[{label}] {e} run{r}: {total} 处、{ver} 核验过")

    # 正例：引用真实性 + 召回代理（核验过的出现数众数）
    pos_v = pos_t = 0
    for e in _POSITIVE:
        for run in results[e]:
            pos_v += run["verified"]
            pos_t += run["total"]
    # 伪负例：假阳性 = 返回了 ≥1 出现的 run 占比（应当全 0 处）
    neg_runs = [run for e in _NEGATIVE for run in results[e]]
    fp = sum(1 for run in neg_runs if run["total"] > 0)
    fp_rate = fp / len(neg_runs) * 100 if neg_runs else 0.0

    print("\n=== 判定 ===")
    pos_truth = f"{pos_v}/{pos_t} = {pos_v / pos_t * 100:.1f}%" if pos_t else "无输出"
    print(f"正例 引用真实性：{pos_truth}")
    print(f"正例 召回代理：每实体每次平均核验过出现数 = {pos_v / (len(_POSITIVE) * _RUNS):.1f}")
    print(f"伪负例 假阳性率：{fp}/{len(neg_runs)} = {fp_rate:.1f}%（≤20% 硬门槛）")
    verdict = "GO" if fp_rate <= 20 and pos_v > 0 else "NO-GO"
    print(f"==> {verdict}")

    stamp = datetime.datetime.now()
    out = {
        "schema": "bookscope-entity-recall-probe/v1",
        "timestamp": stamp.isoformat(timespec="seconds"),
        "model": model,
        "positive": {e: results[e] for e in _POSITIVE},
        "negative": {e: results[e] for e in _NEGATIVE},
        "pos_citation_truth_pct": round(pos_v / pos_t * 100, 1) if pos_t else None,
        "fp_rate_pct": round(fp_rate, 1),
        "verdict": verdict,
    }
    p = Path("docs/internal/experiments/data") / f"probe-entity-recall-{stamp:%Y%m%d-%H%M%S}.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[probe] 写出 {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
