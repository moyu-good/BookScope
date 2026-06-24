"""验声口跨章采样修——三国上跑一个出场多的角色，看是不是只喂相关章、不再整本截断。

老的声口分析整本进 context（三国 73 万字已可能截断、几百万字网文必截）。改成用章脉
``present`` 字段定位角色出场章、只把这些章原文喂进去。这脚本在三国上跑刘备（出场极多），
打印：定位到的出场章数、采样文本规模 vs 整本、声口分析结果——证明只喂相关章、没整本截断。

用法（PowerShell）:
    $env:PYTHONIOENCODING='utf-8'; python -X utf8 scripts/verify_voice_spine.py
环境变量 DEEPSEEK_API_KEY 必须设好。
"""

from __future__ import annotations

import os
from pathlib import Path

from bookscope.agent._internal.chapter_spine_cache import get_or_build_spine
from bookscope.agent.chapter_spine_canon import build_spine_name_map
from bookscope.agent.character_voice import (
    DEFAULT_VOICE_SAMPLE_CHAR_BUDGET,
    _character_aliases,
    _sample_text_by_spine,
    generate_character_voice,
)
from bookscope.api.dependencies import build_llm_client_from_params, default_model_for
from bookscope.ingest.book_chunker import chunk_book_with_stats
from bookscope.ingest.loader import load_text

CHARACTER = "刘备"  # 三国出场极多的主角，最能体现"出场章很多→只喂戏份重的前若干章"


def main() -> None:
    path = next(p for p in Path("tests/file").glob("*三国*"))
    book = load_text(str(path), title="三国演义")
    chunk_res, _ = chunk_book_with_stats(book)
    chunks = [
        {"chunk_id": f"r0-chunk-{c.index}", "chapter": c.chapter, "text": c.text}
        for c in chunk_res
    ]
    full_chars = sum(len(c["text"]) for c in chunks)
    n_chapters = len({c["chapter"] for c in chunks if isinstance(c["chapter"], int)})
    print(f"三国：{len(chunks)} chunk、{n_chapters} 章、整本约 {full_chars} 字")

    client = build_llm_client_from_params(
        provider="deepseek", api_key=os.environ["DEEPSEEK_API_KEY"]
    )
    model = default_model_for("deepseek")

    spine = get_or_build_spine(chunks=chunks, llm_client=client, model=model)
    print(f"章脉：{len(spine)} 章")
    name_map = build_spine_name_map(spine=spine, llm_client=client, model=model)
    aliases = _character_aliases(CHARACTER, name_map)
    print(f"「{CHARACTER}」的别名集：{sorted(aliases)}")

    # ── 采样指标（直接调 helper，看定位+不截断，不烧 LLM）─────────────────
    sampled, kept, present_count = _sample_text_by_spine(
        aliases=aliases,
        spine=spine,
        chunks=chunks,
        char_budget=DEFAULT_VOICE_SAMPLE_CHAR_BUDGET,
    )
    print("\n=== 跨章采样指标 ===")
    print(f"定位到出场章：{present_count} 章")
    print(f"实际喂进 context：{len(kept)} 章，{len(sampled)} 字")
    if full_chars:
        print(f"采样 / 整本 = {len(sampled) / full_chars:.0%}（只喂相关章，不再整本进）")
    print(f"喂进的章号（前 30）：{kept[:30]}{' …' if len(kept) > 30 else ''}")
    longctx_max = int(os.environ.get("BOOKSCOPE_LONGCTX_MAX_TOKENS", "600000"))
    est_tokens = len(sampled) * 0.68
    print(f"采样估 token ≈ {est_tokens:.0f}，长上下文上限 {longctx_max} → "
          f"{'不截断' if est_tokens <= longctx_max else '仍超限'}")

    if not sampled:
        print("！没定位到出场章，采样为空——请检查章脉 present 或别名匹配")
        return

    # ── 真跑声口分析（喂采样文本）─────────────────────────────────────────
    print("\n=== 声口分析（喂跨章采样文本）===")
    result = generate_character_voice(
        character=CHARACTER,
        full_text=book.raw_text,  # 退回整本时才用；有 spine 走采样路径不碰它
        chunks=chunks,
        llm_client=client,
        model=model,
        spine=spine,
        name_map=name_map,
    )
    if result is None:
        print("声口分析返 None（解析/调用失败）")
        return
    print(f"sample_too_small={result['sample_too_small']}")
    print(f"语言特征 {len(result['features'])} 条：")
    for f in result["features"]:
        mark = "✓" if f.get("verified") else "·"
        print(f"  [{mark}] {f['trait']} —— {f.get('evidence', '')[:40]}")
    print(f"声口漂移 {len(result['drift_items'])} 条（已 verify-filter）：")
    for d in result["drift_items"]:
        print(f"  第{d['chapter']}章：{d['quote'][:40]} —— {d.get('reason', '')[:30]}")


if __name__ == "__main__":
    main()
