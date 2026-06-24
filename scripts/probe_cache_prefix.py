"""溯源 DeepSeek 前缀缓存命中:同一段原文,人物维(冷,第一次读)vs 情节维(同段、不同指令)。

作者看后台"输入未缓存命中"占八成。验:章脉是 map-reduce 分段,每段第一次读必 miss(固有成本),
book-first 让同段第二维重读命中前缀。拿一段没跑过的书(避开热缓存),关 L2(看 DeepSeek 自己的
前缀缓存),连发两维,打印各自 prompt_cache_hit_tokens / miss_tokens。

用法: python -X utf8 scripts/probe_cache_prefix.py [书关键字，默认 安史]
"""

from __future__ import annotations

import glob
import os
import sys

from bookscope.agent._internal.exhaustive import segment_chunks
from bookscope.agent._internal.llm_cache import invoke_client_cached
from bookscope.agent._internal.longctx_system import build_longctx_system
from bookscope.agent.chapter_spine import _INSTR_CHAR, _INSTR_PLOT
from bookscope.api.dependencies import build_llm_client_from_params, default_model_for
from bookscope.ingest.book_chunker import chunk_book_with_stats
from bookscope.ingest.loader import load_text

_USER = "请按上面的要求,只对这段原文逐章抽结构。"


def _call(client, model, seg_text, instr):  # noqa: ANN001, ANN202
    resp = invoke_client_cached(
        client, model=model, system=build_longctx_system(seg_text, instr),
        tools=[], messages=[{"role": "user", "content": _USER}],
        max_tokens=4000, cache_enabled=False,  # 关 L2,看 DeepSeek 前缀缓存
    )
    u = resp.get("usage", {}) if isinstance(resp, dict) else {}
    return (
        int(u.get("prompt_tokens", 0)),
        int(u.get("prompt_cache_hit_tokens", 0)),
        int(u.get("prompt_cache_miss_tokens", 0)),
    )


def main() -> None:
    kw = sys.argv[1] if len(sys.argv) > 1 else "安史"
    path = glob.glob(f"tests/file/*{kw}*")[0]
    book = load_text(path, title=kw)
    chunk_res, _ = chunk_book_with_stats(book)
    chunks = [{"chunk_id": f"c{c.index}", "chapter": c.chapter, "text": c.text} for c in chunk_res]
    seg = segment_chunks(chunks)[0]  # 取第一段(没跑过 = 冷)
    seg_text = "".join(str(c["text"]) for c in seg)
    print(f"[book] {path} · 段0 {len(seg_text)} 字")

    client = build_llm_client_from_params(provider="deepseek", api_key=os.environ["DEEPSEEK_API_KEY"])
    model = default_model_for("deepseek")

    p1, h1, m1 = _call(client, model, seg_text, _INSTR_CHAR)
    print(f"[人物维·冷] prompt={p1} 命中={h1} 未命中={m1}  命中率 {h1/max(1,p1):.0%}")
    p2, h2, m2 = _call(client, model, seg_text, _INSTR_PLOT)
    print(f"[情节维·同段重读] prompt={p2} 命中={h2} 未命中={m2}  命中率 {h2/max(1,p2):.0%}")
    print("\n结论:人物维(第一次读)未命中高=把书读一遍的固有成本;情节维同段命中高=book-first 前缀复用生效。")


if __name__ == "__main__":
    main()
