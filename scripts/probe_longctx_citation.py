"""引用真实性 A/B：长上下文路 vs RAG 路（exp-008 方法学，转默认前的质量护栏）。

同一批问题在能塞下的 anshi 上两条路都跑，逐题数 citation 的逐字核验命中率
（verified / total，match_type quote|paraphrase 算核验、none 不算）。长上下文路
verified 率不低于 RAG → 引用质量不掉，可放心把长上下文转"塞得下的书"默认。

书路径 + key 只走运行时 env（BOOKSCOPE_SMOKE_EPUB / DEEPSEEK_API_KEY），不硬编。
"""

from __future__ import annotations

import datetime
import json
import os
import time
from pathlib import Path


def _count_citations(citations: list) -> tuple[int, int]:
    """返回 (verified, total)：match_type quote|paraphrase 或 verified=True 算核验。"""
    total = len(citations)
    verified = 0
    for c in citations:
        mt = c.get("match_type") if isinstance(c, dict) else getattr(c, "match_type", None)
        v = c.get("verified") if isinstance(c, dict) else getattr(c, "verified", None)
        if mt in ("quote", "paraphrase") or v is True:
            verified += 1
    return verified, total


def main() -> int:
    from bookscope.agent import AgentLoop
    from bookscope.agent.backends.r0_assembler import R0BookAssembler
    from bookscope.agent.long_context import run_long_context
    from scripts.smoke_test_r1 import (  # type: ignore[import-not-found]
        _build_adapter_and_model,
        _load_book_session,
    )

    provider = os.environ.setdefault("BOOKSCOPE_SMOKE_PROVIDER", "deepseek")
    adapter, model = _build_adapter_and_model(provider)
    print(f"[cit] provider={provider} model={model}")
    print("[cit] 加载书 + 装配（含 ingest）...")
    book, chunks, kg, vector_store = _load_book_session()
    assembler = R0BookAssembler(
        book_text=book, chunks=chunks, knowledge_graph=kg, session_vector_store=vector_store
    )
    backends = assembler.build_all()
    loop = AgentLoop(
        client=adapter,
        search_chunks_backend=backends["search"],
        chapter_range_backend=backends["chapter_range"],
        list_characters_backend=backends["list_characters"],
        model=model,
        timeout_seconds=float(os.environ.get("BOOKSCOPE_SMOKE_TIMEOUT", "600")),
    )

    full_text = assembler._book_text.raw_text  # noqa: SLF001
    chunk_to_chapter = assembler._compute_chunk_to_chapter_map()  # noqa: SLF001
    lc_chunks = [
        {
            "chunk_id": f"r0-chunk-{c.index}",
            "chapter": chunk_to_chapter.get(c.index, 0),
            "text": c.text,
        }
        for c in assembler._chunks  # noqa: SLF001
    ]

    questions = [
        "这本书对安史之乱的核心论点是什么？",
        "安禄山起兵的直接导火索，书里怎么说？",
        "书里怎么描述灵宝之战、潼关失守的经过？",
        "作者怎么看'安史之乱是民族矛盾'这种说法？",
        "唐玄宗在安史之乱里的应对，书里怎么评价？",
        "书名里的'宣传与神话'指的是什么？",
    ]

    per_q: list[dict] = []
    lc_v = lc_t = rag_v = rag_t = 0
    for i, q in enumerate(questions, start=1):
        # 长上下文路
        t0 = time.monotonic()
        lc = run_long_context(
            q, full_text=full_text, chunks=lc_chunks, llm_client=adapter, model=model
        )
        lc_dt = time.monotonic() - t0
        if lc is not None:
            v, t = _count_citations(lc.citations)
            lc_v += v
            lc_t += t
            lc_rec = {
                "verified": v,
                "total": t,
                "answer_len": len(lc.answer),
                "outcome": lc.trace.outcome,
            }
        else:
            lc_rec = {"outcome": "fallback_none"}
        # RAG 路
        t0 = time.monotonic()
        rag = loop.query(q)
        rag_dt = time.monotonic() - t0
        rv, rt = _count_citations(rag.citations)
        rag_v += rv
        rag_t += rt
        per_q.append({
            "q": i,
            "lc": lc_rec,
            "lc_s": round(lc_dt, 1),
            "rag": {"verified": rv, "total": rt, "answer_len": len(rag.answer)},
            "rag_s": round(rag_dt, 1),
        })
        lc_str = f"{lc_rec.get('verified','-')}/{lc_rec.get('total','-')}"
        print(f"[cit] q{i}  长上下文 {lc_str}（{lc_dt:.0f}s）  RAG {rv}/{rt}（{rag_dt:.0f}s）")

    lc_rate = lc_v / lc_t * 100 if lc_t else 0.0
    rag_rate = rag_v / rag_t * 100 if rag_t else 0.0
    print("\n=== 引用真实性（逐字核验命中率）===")
    print(f"  长上下文：{lc_v}/{lc_t} = {lc_rate:.1f}%")
    print(f"  RAG     ：{rag_v}/{rag_t} = {rag_rate:.1f}%")
    verdict = "不掉（≥ RAG）" if lc_rate >= rag_rate - 1 else "掉了，需查"
    print(f"  判定：长上下文引用质量 {verdict}")

    stamp = datetime.datetime.now()
    out = {
        "schema": "bookscope-citation-ab/v1",
        "timestamp": stamp.isoformat(timespec="seconds"),
        "model": model,
        "per_question": per_q,
        "longctx_verified_rate_pct": round(lc_rate, 1),
        "rag_verified_rate_pct": round(rag_rate, 1),
        "longctx_verified_total": [lc_v, lc_t],
        "rag_verified_total": [rag_v, rag_t],
    }
    out_path = Path("docs/internal/experiments/data") / f"probe-longctx-citation-{stamp:%Y%m%d-%H%M%S}.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[cit] 写出 {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
