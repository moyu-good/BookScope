"""WP-agent-token-budget Phase 1 profile · 按 tool 聚合 miss 构成。

跑一小批问题，把每条 tool 结果灌进上下文的体量（result_tokens_est）按 tool 聚合，
回答"miss token 主要花在 search_chunks 还是 get_chapter_range"。戴明：先量再砍。

书路径 + key **只走运行时 env**（BOOKSCOPE_SMOKE_EPUB / DEEPSEEK_API_KEY），
绝不硬编进本文件——书文件名带版权源 / 真名，不进任何提交产物。

用法（bash）：先把 DEEPSEEK_API_KEY 从 memory 文件读进 env（别落命令行），
再设 BOOKSCOPE_SMOKE_EPUB 指向书，最后 ``python scripts/profile_token_budget.py``。
"""

from __future__ import annotations

import datetime
import json
import os
import time
from collections import defaultdict
from pathlib import Path


def main() -> int:
    from bookscope.agent import AgentLoop
    from bookscope.agent.backends.r0_assembler import R0BookAssembler
    from scripts.smoke_test_r1 import (  # type: ignore[import-not-found]
        _build_adapter_and_model,
        _load_book_session,
    )

    provider = os.environ.setdefault("BOOKSCOPE_SMOKE_PROVIDER", "deepseek")
    adapter, model = _build_adapter_and_model(provider)
    print(f"[profile] provider={provider} model={model}")
    print("[profile] 加载书 + 装配 backends（含 ingest，约 1-2 分钟）...")
    book, chunks, kg, vector_store = _load_book_session()
    assembler = R0BookAssembler(
        book_text=book,
        chunks=chunks,
        knowledge_graph=kg,
        session_vector_store=vector_store,
    )
    backends = assembler.build_all()
    if backends["search"] is None:
        raise RuntimeError("vector store 装配失败")

    loop = AgentLoop(
        client=adapter,
        search_chunks_backend=backends["search"],
        chapter_range_backend=backends["chapter_range"],
        list_characters_backend=backends["list_characters"],
        model=model,
        timeout_seconds=float(os.environ.get("BOOKSCOPE_SMOKE_TIMEOUT", "600")),
    )

    # 3 题混合：全局论点 / 具体事件 / 章节性描述——尽量同时触发 search 与拉章
    questions = [
        {"id": "g1", "q": "这本书对安史之乱的核心论点是什么？"},
        {"id": "s1", "q": "安禄山起兵的直接导火索，书里怎么说？"},
        {"id": "c1", "q": "书里怎么描述灵宝之战、潼关失守的经过？"},
    ]

    per_q: list[dict] = []
    agg_tokens: dict[str, int] = defaultdict(int)
    agg_calls: dict[str, int] = defaultdict(int)

    for item in questions:
        t0 = time.monotonic()
        res = loop.query(item["q"])
        dt = time.monotonic() - t0
        tr = res.trace
        by_tool: dict[str, int] = defaultdict(int)
        calls: dict[str, int] = defaultdict(int)
        for tc in tr.tool_calls:
            name = tc.get("tool_name", "?")
            est = int(tc.get("result_tokens_est", 0) or 0)
            by_tool[name] += est
            calls[name] += 1
            agg_tokens[name] += est
            agg_calls[name] += 1
        per_q.append(
            {
                "id": item["id"],
                "duration_s": round(dt, 1),
                "outcome": tr.outcome,
                "iterations": tr.iterations,
                "total_input_tokens": tr.total_input_tokens,
                "cache_hit_tokens": tr.cache_hit_tokens,
                "cache_miss_tokens": tr.cache_miss_tokens,
                "tool_result_tokens_est_by_tool": dict(by_tool),
                "tool_calls_by_tool": dict(calls),
            }
        )
        print(
            f"[profile] {item['id']} {dt:.0f}s outcome={tr.outcome} "
            f"miss={tr.cache_miss_tokens} hit={tr.cache_hit_tokens} "
            f"by_tool={dict(by_tool)}"
        )

    total_est = sum(agg_tokens.values()) or 1
    print("\n=== miss 构成（per-tool result_tokens_est 聚合，3 题）===")
    for name, tok in sorted(agg_tokens.items(), key=lambda x: -x[1]):
        pct = tok / total_est * 100
        print(f"  {name:24s} {tok:9d} est-tok  {pct:5.1f}%  calls={agg_calls[name]}")

    real_miss = sum(r["cache_miss_tokens"] for r in per_q)
    real_hit = sum(r["cache_hit_tokens"] for r in per_q)
    denom = real_hit + real_miss
    if denom:
        print(
            f"\n真实 API usage：miss={real_miss} hit={real_hit} "
            f"命中率={real_hit / denom * 100:.1f}%（3 题，每问现检索情形）"
        )

    stamp = datetime.datetime.now()
    out = {
        "schema": "bookscope-token-profile/v1",
        "timestamp": stamp.isoformat(timespec="seconds"),
        "model": model,
        "questions": len(questions),
        "per_question": per_q,
        "agg_result_tokens_est_by_tool": dict(agg_tokens),
        "agg_tool_calls_by_tool": dict(agg_calls),
        "real_cache_miss_tokens": real_miss,
        "real_cache_hit_tokens": real_hit,
    }
    out_path = (
        Path("docs/internal/experiments/data")
        / f"profile-token-budget-{stamp:%Y%m%d-%H%M%S}.json"
    )
    out_path.write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n[profile] 写出 {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
