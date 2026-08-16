"""BookScope 命令行入口——把复杂功能变成一条命令。

当前提供两个最常用的快捷操作：

- ``bookscope report <文件>``：零 LLM 秒出结构版书鉴 HTML（可分享/存档）
- ``bookscope serve``：启动本地 Web 服务（等价于 uvicorn）

后续可继续加 ``import`` / ``cross`` / ``ask`` 等子命令，让终端、脚本、CI
都能直接调用 BookScope 的能力。
"""

from __future__ import annotations

import argparse
import os
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


def _load_chunks(path: Path, title: str | None = None) -> tuple[str, list[dict]]:
    """读取一本书并切成报告/章脉需要的 dict chunks。"""
    book = load_text(path, title=title)
    results, _stats = chunk_book_with_stats(book)
    name = title or path.stem
    return name, _chunks_to_dicts(results)


def _build_client(provider: str, api_key: str, base_url: str | None, model: str):
    from bookscope.agent import build_llm_client_from_params

    return build_llm_client_from_params(
        provider=provider,
        api_key=api_key,
        base_url=base_url,
    )


def cmd_cross(args: argparse.Namespace) -> int:
    """两个本地文件直接出跨文本对照 HTML 报告（需要 LLM key）。"""
    api_key = args.api_key or os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("需要 LLM key：--api-key 或环境变量 DEEPSEEK_API_KEY / OPENAI_API_KEY", file=sys.stderr)
        return 2
    provider = args.provider or "deepseek"
    model = args.model or "deepseek-v4-flash"
    base_url = args.base_url
    try:
        client = _build_client(provider, api_key, base_url, model)
    except Exception as exc:  # noqa: BLE001
        print(f"LLM client 构建失败: {exc}", file=sys.stderr)
        return 2

    from bookscope.agent._internal.chapter_spine_cache import get_or_build_spine
    from bookscope.agent.book_cross import (
        build_book_perspective,
        build_cross_book_report_input,
        cross_book_reason,
    )
    from bookscope.report.service import render_report

    paths = [Path(args.file1), Path(args.file2)]
    perspectives = []
    for idx, path in enumerate(paths):
        if not path.exists():
            print(f"文件不存在: {path}", file=sys.stderr)
            return 1
        title, chunks = _load_chunks(path, getattr(args, f"title{idx + 1}", None))
        print(f"正在构建《{title}》章脉（首次较慢，之后走缓存）…")
        spine = get_or_build_spine(chunks=chunks, llm_client=client, model=model, genre="fiction")
        slug = f"b{idx}"
        perspectives.append(build_book_perspective(
            spine=spine, book_title=title, slug=slug,
            llm_client=client, model=model,
        ))

    print("正在做跨文本对照推理…")
    reason = cross_book_reason(perspectives=perspectives, llm_client=client, model=model)
    titles = " × ".join(p.get("title", "") for p in perspectives)
    inp = build_cross_book_report_input(
        perspectives=perspectives, reason=reason,
        meta={
            "title": f"跨文本对照 · {titles}",
            "subtitle": f"{len(perspectives)} 份文档 · 跨文本逻辑对照 · 关系为研判",
            "seal": "书 鉴",
            "nav_title": "对照 · 报告导航",
            "unit_label": "份",
            "generated_by": "书鉴 BookScope CLI",
        },
    )
    html = render_report(inp)
    out = Path(args.out)
    out.write_text(html, encoding="utf-8")
    print(f"已生成: {out.resolve()} ({len(html)} bytes)")
    if getattr(args, "open", False):
        import webbrowser

        webbrowser.open(out.resolve().as_uri())
    return 0


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

    p_cross = sub.add_parser("cross", help="两个文件直接出跨文本对照 HTML 报告")
    p_cross.add_argument("file1", help="第一本书/文档路径")
    p_cross.add_argument("file2", help="第二本书/文档路径")
    p_cross.add_argument("--out", default="bookscope-cross.html", help="输出 HTML 路径（默认 bookscope-cross.html）")
    p_cross.add_argument("--title1", default=None, help="第一本书名（默认取文件名）")
    p_cross.add_argument("--title2", default=None, help="第二本书名（默认取文件名）")
    p_cross.add_argument("--provider", default="deepseek", help="LLM 厂商（默认 deepseek）")
    p_cross.add_argument("--api-key", default=None, help="LLM API key（默认读 DEEPSEEK_API_KEY / OPENAI_API_KEY）")
    p_cross.add_argument("--model", default=None, help="模型名（默认 deepseek-v4-flash）")
    p_cross.add_argument("--base-url", default=None, help="OpenAI 兼容 base_url")
    p_cross.add_argument("--open", action="store_true", help="生成后自动在浏览器打开")
    p_cross.set_defaults(func=cmd_cross)

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
