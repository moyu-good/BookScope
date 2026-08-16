"""BookScope 命令行入口——把复杂功能变成一条命令。

当前提供两个最常用的快捷操作：

- ``bookscope report <文件>``：零 LLM 秒出结构版书鉴 HTML（可分享/存档）
- ``bookscope serve``：启动本地 Web 服务（等价于 uvicorn）

后续可继续加 ``import`` / ``cross`` / ``ask`` 等子命令，让终端、脚本、CI
都能直接调用 BookScope 的能力。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from bookscope.ingest.book_chunker import chunk_book_with_stats
from bookscope.ingest.loader import load_text
from bookscope.report.builders import build_structure_report
from bookscope.report.service import render_report

DEFAULT_OUT = "bookscope-report.html"


def _chunks_to_dicts(results: list) -> list[dict]:
    """把 ingest 的 ChunkResult 转成报告契约需要的 dict 列表。"""
    return [
        {
            "chunk_id": f"c{idx}",
            "chapter": getattr(c, "chapter", None),
            "text": getattr(c, "text", ""),
        }
        for idx, c in enumerate(results)
    ]


def cmd_report(args: argparse.Namespace) -> int:
    path = Path(args.path)
    if not path.exists():
        print(f"文件不存在: {path}", file=sys.stderr)
        return 1
    title = args.title or path.stem
    print(f"正在读取 {path} …")
    book = load_text(path, title=title)
    print("正在分章/切块 …")
    results, stats = chunk_book_with_stats(book)
    chunks = _chunks_to_dicts(results)
    meta = {
        "title": f"《{title}》书鉴报告（结构版）",
        "subtitle": f"{len(chunks)} 个片段 · {stats.chapters_detected if hasattr(stats, 'chapters_detected') else '?'} 章 · 零 LLM 秒出",
        "seal": "书 鉴",
        "nav_title": "书鉴 · 报告导航",
        "unit_label": "章",
        "generated_by": "书鉴 BookScope CLI",
    }
    inp = build_structure_report(chunks, meta)
    html = render_report(inp)
    out = Path(args.out)
    out.write_text(html, encoding="utf-8")
    print(f"已生成: {out.resolve()} ({len(html)} bytes)")
    if getattr(args, "open", False):
        import webbrowser

        webbrowser.open(out.resolve().as_uri())
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    host = args.host
    port = args.port
    print(f"BookScope 服务已启动: http://{host}:{port}")
    uvicorn.run("bookscope.api.app:create_app", factory=True, host=host, port=port, reload=args.reload)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bookscope",
        description="书鉴 BookScope —— 把长文档变成可核验、可交互、可追问的书鉴。",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_report = sub.add_parser("report", help="把一本书秒出结构版 HTML 报告")
    p_report.add_argument("path", help="书文件路径（txt / epub / pdf / docx / md）")
    p_report.add_argument("--out", default=DEFAULT_OUT, help=f"输出 HTML 路径（默认 {DEFAULT_OUT}）")
    p_report.add_argument("--title", default=None, help="书名（默认取文件名）")
    p_report.add_argument("--open", action="store_true", help="生成后自动在浏览器打开")
    p_report.set_defaults(func=cmd_report)

    p_serve = sub.add_parser("serve", help="启动本地 Web 服务")
    p_serve.add_argument("--host", default="127.0.0.1", help="监听地址（默认 127.0.0.1）")
    p_serve.add_argument("--port", type=int, default=8000, help="端口（默认 8000）")
    p_serve.add_argument("--reload", action="store_true", help="开发模式自动重载")
    p_serve.set_defaults(func=cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
