"""WP-character-graph 验收真跑：anshi 上跑生产 extract_character_graph。

验结构化 JSON 路径端到端（unit test 是 mock、exp-013 是 freeform，都没测真模型
按本功能的 JSON 格式吐 + 解析 + 边校验）。复用 smoke 装书 + _long_context_inputs +
生产 extract_character_graph，等价于端点干的事。flash、key 从 .env。不动生产、不 commit 数据。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

_ROOT = Path(__file__).resolve().parent.parent
for p in (_ROOT, _ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import bookscope  # noqa: E402, F401 —— 触发 .env 加载


_BOOK_GLOB = {"anshi": "test安史之乱*.epub", "zhinei": "test制内市场*.epub"}


def main() -> int:
    import argparse  # noqa: PLC0415
    parser = argparse.ArgumentParser(description="人物/概念关系图验收真跑")
    parser.add_argument("--unit", default="person", choices=["person", "concept"])
    parser.add_argument("--book", default="anshi", choices=sorted(_BOOK_GLOB))
    args = parser.parse_args()

    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("[run] DEEPSEEK_API_KEY 未设置", file=sys.stderr)
        return 1
    found = sorted(_ROOT.glob(_BOOK_GLOB[args.book]))
    if not found:
        print(f"[run] {args.book} epub 没找到", file=sys.stderr)
        return 1
    os.environ["BOOKSCOPE_SMOKE_EPUB"] = str(found[0])

    from smoke_test_r1 import _build_adapter_and_model, _load_book_session  # noqa: PLC0415

    from bookscope.agent.backends.r0_assembler import R0BookAssembler  # noqa: PLC0415
    from bookscope.agent.character_graph import extract_character_graph  # noqa: PLC0415
    from bookscope.api.routes.agent import _long_context_inputs  # noqa: PLC0415

    book, chunks, kg, vs = _load_book_session()
    assembler = R0BookAssembler(
        book_text=book, chunks=chunks, knowledge_graph=kg, session_vector_store=vs,
    )
    adapter, model = _build_adapter_and_model("deepseek")
    full_text, chunk_dicts = _long_context_inputs(assembler)
    print(f"[run] {args.book} 全文 {len(full_text)} 字符、{len(chunk_dicts)} chunks；"
          f"unit={args.unit}；model {model}\n")

    result = extract_character_graph(
        full_text=full_text, chunks=chunk_dicts, llm_client=adapter, model=model,
        unit=args.unit,
    )
    if result is None:
        print("[run] 抽取返回 None（解析失败或调用出错）", file=sys.stderr)
        return 1

    verified = sum(1 for e in result.edges if e.get("verified"))
    print(f"[run] 节点 {len(result.nodes)} 个、边 {len(result.edges)} 条、"
          f"已核验 {verified} 条（{verified}/{len(result.edges)}）")
    print(f"[run] tokens in={result.input_tokens} out={result.output_tokens} "
          f"耗时 {result.duration_ms}ms\n")
    print("[run] 节点：", "、".join(result.nodes[:30]))
    print("\n[run] 抽样边（前 12 条）：")
    for e in result.edges[:12]:
        flag = f"✓ch{e['chapter']}" if e["verified"] else "✗未核验"
        print(f"  {e['source']} --[{e['relation']}]--> {e['target']}  [{flag}]")
        print(f"      证据：{e['evidence'][:60]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
