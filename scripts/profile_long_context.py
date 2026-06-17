"""WP-agent-token-budget · 验长上下文钉稳定上下文路的命中率 + 越问越省。

同一本书钉进 system 稳定前缀，背靠背问 N 题（session_id=None 关 L2、每题真打
DeepSeek），逐题量 prompt_cache_hit/miss——验"第 2 问起命中 ≥90%"和"累计成本
随问题数追上并反超 RAG"（深读场景）。

书路径 + key 只走运行时 env（BOOKSCOPE_SMOKE_EPUB / DEEPSEEK_API_KEY），不硬编。
"""

from __future__ import annotations

import datetime
import json
import os
import time
from pathlib import Path

# RAG 模式每题的 miss 基准（profile-token-budget 实测 3 题均 ~32k miss/题）
RAG_MISS_PER_Q = 32244


def main() -> int:
    from bookscope.agent.backends.r0_assembler import R0BookAssembler
    from bookscope.agent.long_context import run_long_context
    from scripts.smoke_test_r1 import (  # type: ignore[import-not-found]
        _build_adapter_and_model,
        _load_book_session,
    )

    provider = os.environ.setdefault("BOOKSCOPE_SMOKE_PROVIDER", "deepseek")
    adapter, model = _build_adapter_and_model(provider)
    print(f"[lc] provider={provider} model={model}")
    print("[lc] 加载书 + 装配（含 ingest）...")
    book, chunks, kg, vector_store = _load_book_session()
    assembler = R0BookAssembler(
        book_text=book,
        chunks=chunks,
        knowledge_graph=kg,
        session_vector_store=vector_store,
    )

    full_text = assembler._book_text.raw_text  # noqa: SLF001 — 同生产 _long_context_inputs
    chunk_to_chapter = assembler._compute_chunk_to_chapter_map()  # noqa: SLF001
    chunk_dicts = [
        {
            "chunk_id": f"r0-chunk-{c.index}",
            "chapter": chunk_to_chapter.get(c.index, 0),
            "text": c.text,
        }
        for c in assembler._chunks  # noqa: SLF001
    ]
    print(f"[lc] 全书 {len(full_text)} 字符、{len(chunk_dicts)} chunks")

    questions = [
        "这本书对安史之乱的核心论点是什么？",
        "安禄山起兵的直接导火索，书里怎么说？",
        "书里怎么描述灵宝之战、潼关失守的经过？",
        "作者怎么看'安史之乱是民族矛盾'这种说法？",
        "唐玄宗在安史之乱里的应对，书里怎么评价？",
        "书名里的'宣传与神话'指的是什么？",
    ]

    per_q: list[dict] = []
    cum_lc_miss = 0
    for i, q in enumerate(questions, start=1):
        t0 = time.monotonic()
        res = run_long_context(
            q,
            full_text=full_text,
            chunks=chunk_dicts,
            llm_client=adapter,
            model=model,
        )
        dt = time.monotonic() - t0
        if res is None:
            print(f"[lc] q{i} {dt:.0f}s -> None（回退 RAG）")
            per_q.append({"q": i, "outcome": "fallback_none", "duration_s": round(dt, 1)})
            continue
        tr = res.trace
        denom = tr.cache_hit_tokens + tr.cache_miss_tokens
        hit_rate = tr.cache_hit_tokens / denom * 100 if denom else 0.0
        cum_lc_miss += tr.cache_miss_tokens
        cum_rag_miss = RAG_MISS_PER_Q * i
        per_q.append(
            {
                "q": i,
                "duration_s": round(dt, 1),
                "outcome": tr.outcome,
                "cache_hit_tokens": tr.cache_hit_tokens,
                "cache_miss_tokens": tr.cache_miss_tokens,
                "hit_rate_pct": round(hit_rate, 1),
                "cum_lc_miss": cum_lc_miss,
                "cum_rag_miss_equiv": cum_rag_miss,
            }
        )
        print(
            f"[lc] q{i} {dt:.0f}s hit={tr.cache_hit_tokens} miss={tr.cache_miss_tokens} "
            f"命中率={hit_rate:.1f}%  累计lc_miss={cum_lc_miss} vs RAG≈{cum_rag_miss}"
        )

    ok = [r for r in per_q if "hit_rate_pct" in r]
    if len(ok) >= 2:
        steady = sum(r["hit_rate_pct"] for r in ok[1:]) / len(ok[1:])
        print(f"\n=== 第 2 问起稳态命中率均值 = {steady:.1f}%（目标 ≥90%）===")
        cross = next((r["q"] for r in ok if r["cum_lc_miss"] <= r["cum_rag_miss_equiv"]), None)
        print(f"累计成本反超 RAG 的问题数（lc 累计 miss ≤ RAG 累计）：{cross or '>本批'}")

    stamp = datetime.datetime.now()
    out = {
        "schema": "bookscope-longctx-profile/v1",
        "timestamp": stamp.isoformat(timespec="seconds"),
        "model": model,
        "book_chars": len(full_text),
        "rag_miss_per_q_baseline": RAG_MISS_PER_Q,
        "per_question": per_q,
    }
    out_path = (
        Path("docs/internal/experiments/data")
        / f"profile-long-context-{stamp:%Y%m%d-%H%M%S}.json"
    )
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[lc] 写出 {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
