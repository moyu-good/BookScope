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
    """读取一本书并切成报告/章脉需要的 dict chunks（复用 local_tools）。"""
    from bookscope.local_tools import load_chunks as _load

    name, _book, _results, chunks = _load(path, title)
    return name, chunks


def _build_client(provider: str, api_key: str, base_url: str | None, model: str):
    from bookscope.api.dependencies import build_llm_client_from_params

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
        print(f"正在构建《{title}》章脉（首次较慢，之后走缓存）…", file=sys.stderr)
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


def _dedupe_edges(edges: list[dict]) -> list[dict]:
    seen: set[tuple[str, str, str]] = set()
    out: list[dict] = []
    for e in edges:
        key = (str(e.get("from", "")), str(e.get("to", "")), str(e.get("relation", "")))
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


def _merge_concepts(items: list[dict]) -> list[dict]:
    merged: dict[str, list[dict]] = {}
    for item in items:
        name = str(item.get("concept", "")).strip()
        if not name:
            continue
        stages = merged.setdefault(name, [])
        existing = {(str(x.get("paper", "")), str(x.get("stage", ""))) for x in stages}
        for st in item.get("stages", []):
            key = (str(st.get("paper", "")), str(st.get("stage", "")))
            if key not in existing:
                stages.append(st)
                existing.add(key)
    arr = [{"concept": k, "stages": v} for k, v in merged.items()]
    arr.sort(key=lambda x: len(x["stages"]), reverse=True)
    return arr[:5]


def _merge_disputes(items: list[dict]) -> list[dict]:
    merged: dict[str, list[dict]] = {}
    for item in items:
        q = str(item.get("question", "")).strip()
        if not q:
            continue
        sides = merged.setdefault(q, [])
        existing = {(str(x.get("paper", "")), str(x.get("stance", ""))) for x in sides}
        for sd in item.get("sides", []):
            key = (str(sd.get("paper", "")), str(sd.get("stance", "")))
            if key not in existing:
                sides.append(sd)
                existing.add(key)
    arr = [{"question": k, "sides": v} for k, v in merged.items()]
    arr.sort(key=lambda x: len(x["sides"]), reverse=True)
    return arr[:5]


def cmd_cluster(args: argparse.Namespace) -> int:
    """多个文件直接出簇关系网 HTML 报告（两两对照聚合）。"""
    api_key = args.api_key or os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("需要 LLM key：--api-key 或环境变量 DEEPSEEK_API_KEY / OPENAI_API_KEY", file=sys.stderr)
        return 2
    files = [Path(x) for x in args.files]
    if len(files) < 2:
        print("至少需要 2 个文件", file=sys.stderr)
        return 2
    if len(files) > 8:
        print("一次最多 8 个文件（两两对照成本高），请分批", file=sys.stderr)
        return 2
    provider = args.provider or "deepseek"
    model = args.model or "deepseek-v4-flash"
    try:
        client = _build_client(provider, api_key, args.base_url, model)
    except Exception as exc:  # noqa: BLE001
        print(f"LLM client 构建失败: {exc}", file=sys.stderr)
        return 2

    from itertools import combinations

    from bookscope.agent._internal.chapter_spine_cache import get_or_build_spine
    from bookscope.agent.book_cross import (
        build_book_perspective,
        cross_book_reason,
    )
    from bookscope.report.service import render_report

    perspectives = []
    for idx, path in enumerate(files):
        if not path.exists():
            print(f"文件不存在: {path}", file=sys.stderr)
            return 1
        title, chunks = _load_chunks(path, getattr(args, f"title{idx + 1}", None))
        print(f"正在构建《{title}》章脉（首次较慢，之后走缓存）…", file=sys.stderr)
        spine = get_or_build_spine(chunks=chunks, llm_client=client, model=model, genre="fiction")
        perspectives.append(build_book_perspective(
            spine=spine, book_title=title, slug=f"b{idx}",
            llm_client=client, model=model,
        ))

    nodes: list[dict] = []
    seen_slugs: set[str] = set()
    edges: list[dict] = []
    concepts: list[dict] = []
    disputes: list[dict] = []
    pair_count = 0
    for a, b in combinations(perspectives, 2):
        reason = cross_book_reason(perspectives=[a, b], llm_client=client, model=model)
        for n in reason.get("nodes", []):
            slug = n.get("slug")
            if slug and slug not in seen_slugs:
                seen_slugs.add(slug)
                nodes.append(n)
        edges.extend(reason.get("edges", []))
        concepts.extend(reason.get("concept_evolution", []))
        disputes.extend(reason.get("disagreements", []))
        pair_count += 1

    if not nodes:
        nodes = [
            {"slug": p.get("slug", ""), "label": p.get("title", ""), "stance": p.get("stance", "")}
            for p in perspectives if p.get("slug")
        ]
    edges = _dedupe_edges(edges)
    concepts = _merge_concepts(concepts)
    disputes = _merge_disputes(disputes)

    cluster_name = args.name or "文档簇"
    narrative = (
        f"《{cluster_name}》共 {len(nodes)} 本，两两对照 {pair_count} 对，"
        f"发现 {len(edges)} 条关系（继承/反驳/补充/落地/检验）。关系为 LLM 研判。"
    )
    inp = {
        "layout": "crossdoc",
        "meta": {
            "title": f"簇关系网 · {cluster_name}",
            "subtitle": f"{len(nodes)} 本 · {len(edges)} 条关系（{pair_count} 对两两对照）· 关系为研判",
            "seal": "书 鉴",
            "nav_title": "簇关系 · 导航",
            "unit_label": "本",
            "generated_by": "书鉴 BookScope CLI",
        },
        "nodes": nodes,
        "edges": edges,
        "concept_evolution": concepts,
        "disagreements": disputes,
        "narrative": narrative,
        "spines": {
            p.get("slug", f"b{i}"): {
                "_title": p.get("title", ""),
                "_slug": p.get("slug", f"b{i}"),
                "core_thesis": p.get("summary", ""),
                "theoretical_stance": {"label": p.get("stance", ""), "inference": True},
                "method": "",
                "key_citations": [
                    {"quote": c.get("claim", ""), "role": f"第{c.get('chapter','?')}章"}
                    for c in p.get("claims", [])[:5] if c.get("claim")
                ],
            }
            for i, p in enumerate(perspectives)
        },
        "e1": {
            p.get("slug", f"b{i}"): {
                "quotes": [{"quote": c.get("claim", ""), "verified": False} for c in p.get("claims", [])[:5] if c.get("claim")]
            }
            for i, p in enumerate(perspectives)
        },
        "quality": {"e2_mean": 0, "e3": None},
    }
    html = render_report(inp)
    out = Path(args.out)
    out.write_text(html, encoding="utf-8")
    print(f"已生成: {out.resolve()} ({len(html)} bytes)")
    if getattr(args, "open", False):
        import webbrowser

        webbrowser.open(out.resolve().as_uri())
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """列出书库里已导入的书。"""
    import json

    from bookscope.api.session_storage import JSONFileSessionStorage

    storage = JSONFileSessionStorage(root=Path(args.data_dir))
    ids = storage.list_all()
    books = []
    for sid in sorted(ids):
        meta_path = Path(args.data_dir) / sid / "metadata.json"
        title = sid
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                title = meta.get("book_title", sid)
            except Exception:  # noqa: BLE001
                pass
        books.append({"session_id": sid, "book_title": title})
    if getattr(args, "json", False):
        print(json.dumps({"books": books, "count": len(books)}, ensure_ascii=False, indent=2))
    else:
        if not books:
            print("书库为空")
        else:
            for b in books:
                print(f"{b['session_id']}	{b['book_title']}")
    return 0


_IMPORT_EXTS = {".txt", ".epub", ".pdf", ".docx", ".md", ".markdown"}


def _import_one(path: Path, data_dir: Path, title: str | None = None) -> str:
    """导入单个文件，返回 session_id（复用 local_tools）。"""
    from bookscope.local_tools import import_file

    return import_file(path, data_dir, title=title)


def cmd_import(args: argparse.Namespace) -> int:
    """把本地文件/文件夹导入书库（Web 直接可见），支持多个路径。"""
    import json

    files: list[Path] = []
    for raw in args.paths:
        path = Path(raw)
        if not path.exists():
            print(f"路径不存在: {path}", file=sys.stderr)
            continue
        if path.is_dir():
            found = [p for p in path.rglob("*") if p.is_file() and p.suffix.lower() in _IMPORT_EXTS]
            if not found:
                print(f"文件夹里没有支持的文件: {path}", file=sys.stderr)
            files.extend(found)
        else:
            files.append(path)
    if not files:
        return 1

    data_dir = Path(args.data_dir)
    imported = []
    for f in sorted(files):
        try:
            session_id = _import_one(f, data_dir, title=args.title if len(files) == 1 else None)
        except Exception as exc:  # noqa: BLE001
            imported.append({"file": str(f), "session_id": None, "error": str(exc)})
            continue
        imported.append({"file": str(f), "session_id": session_id, "book_title": f.stem})
    count = sum(1 for x in imported if x["session_id"])
    if getattr(args, "json", False):
        print(json.dumps({"imported": imported, "count": count, "total": len(files), "data_dir": str(data_dir.resolve())}, ensure_ascii=False, indent=2))
    else:
        for x in imported:
            if x["session_id"]:
                print(f"  已导入书库：{x['session_id']} · 《{x['book_title']}》（{Path(x['file']).name}）")
            else:
                print(f"  导入失败: {x['error']}")
        print(f"完成：成功 {count}/{len(files)} 本")
        print(f"  数据目录：{data_dir.resolve()}")
    return 0 if count else 1



def _local_ask(question: str, chunks: list[dict], json_out: bool) -> int:
    """零配置本地检索问答：没有 LLM key 时返回最相关原文片段。"""
    import json

    from bookscope.local_tools import local_search

    results = local_search(question, chunks, top_k=5)
    if not results:
        print("本地检索没有找到相关片段（可配置 LLM key 获得智能回答）")
        return 1
    if json_out:
        print(json.dumps({"mode": "local", "results": results}, ensure_ascii=False, indent=2))
    else:
        print("本地检索结果（未配置 LLM key，仅返回相关原文）")
        for r in results:
            print(f"\n[第{r['chapter']}章 · 命中 {int(r['score'])} 个词]")
            print(r["text"])
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    """对一本书直接提问，输出带原文引用的答案；没 key 时自动降级为本地检索。"""
    api_key = args.api_key or os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
    path = Path(args.path)
    if not path.exists():
        print(f"文件不存在: {path}", file=sys.stderr)
        return 1
    provider = args.provider or "deepseek"
    model = args.model or "deepseek-v4-flash"
    try:
        client = _build_client(provider, api_key, args.base_url, model)
    except Exception as exc:  # noqa: BLE001
        print(f"LLM client 构建失败: {exc}", file=sys.stderr)
        return 2

    from bookscope.agent.long_context import run_long_context

    title, chunks = _load_chunks(path, args.title)
    if not api_key:
        print(f"未配置 LLM key，使用本地检索问答《{title}》…")
        return _local_ask(args.question, chunks, args.json)
    book = load_text(path, title=title)
    print(f"正在问《{title}》：{args.question}")
    result = run_long_context(
        args.question,
        full_text=book.raw_text,
        chunks=chunks,
        llm_client=client,
        model=model,
        session_id=path.stem,
    )
    if result is None:
        print("回答失败：long_context 返回空（书太大或模型暂不可用）", file=sys.stderr)
        return 1

    if args.json:
        import json

        print(json.dumps({
            "answer": result.answer,
            "citations": result.citations,
        }, ensure_ascii=False, indent=2))
    else:
        print("\n" + result.answer)
        if result.citations:
            print("\n引用：")
            for c in result.citations:
                ch = c.get("chapter", "?")
                snippet = c.get("snippet", "")
                verified = c.get("verified", False)
                mark = "鉴" if verified else "研判"
                print(f"  [{mark}] 第{ch}章：{snippet}")
    return 0


def cmd_prewarm(args: argparse.Namespace) -> int:
    """预建一本书的章脉缓存（后续 report/cross/ask 命中秒出）。"""
    api_key = args.api_key or os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("需要 LLM key：--api-key 或环境变量 DEEPSEEK_API_KEY / OPENAI_API_KEY", file=sys.stderr)
        return 2
    path = Path(args.path)
    if not path.exists():
        print(f"文件不存在: {path}", file=sys.stderr)
        return 1
    provider = args.provider or "deepseek"
    model = args.model or "deepseek-v4-flash"
    try:
        client = _build_client(provider, api_key, args.base_url, model)
    except Exception as exc:  # noqa: BLE001
        print(f"LLM client 构建失败: {exc}", file=sys.stderr)
        return 2

    from bookscope.agent._internal.chapter_spine_cache import get_or_build_spine

    title, chunks = _load_chunks(path, args.title)
    print(f"正在预建《{title}》章脉（首次较慢，之后走缓存）…")
    spine = get_or_build_spine(chunks=chunks, llm_client=client, model=model, genre="fiction")
    print(f"章脉就绪：{len(spine)} 章")
    return 0


def cmd_version(args: argparse.Namespace) -> int:
    import bookscope

    print(bookscope.__version__)
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """检查本地环境：Python/Node/key/前端依赖/缓存目录。"""
    import json
    import shutil
    import sys

    ok = True
    checks: list[dict] = []

    def check(name: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        checks.append({"name": name, "ok": bool(passed), "detail": detail})
        if not passed:
            ok = False

    def warn(name: str, detail: str = "") -> None:
        checks.append({"name": name, "ok": True, "optional": True, "detail": detail})

    check("Python >= 3.12", sys.version_info >= (3, 12), sys.version.split()[0])
    check("Node.js", shutil.which("node") is not None, shutil.which("node") or "未找到")
    check("npm", shutil.which("npm") is not None, shutil.which("npm") or "未找到")
    warn("LLM key（可选）", "未配置也不影响基础功能；深度分析/问答需要时才配置")
    web_node_modules = Path("web/node_modules")
    check("web/node_modules", web_node_modules.exists(), "已安装" if web_node_modules.exists() else "请先 make install")
    cache_dir = Path(".bookscope_cache")
    cache_ok = cache_dir.exists() or cache_dir.mkdir(parents=True, exist_ok=True) is None
    check(".bookscope_cache", cache_ok, "可写" if cache_ok else "无法创建")

    if getattr(args, "json", False):
        print(json.dumps({"ok": ok, "checks": checks}, ensure_ascii=False, indent=2))
    else:
        print("BookScope 环境自检")
        for c in checks:
            if c.get("optional"):
                print(f"  ○ {c['name']} — {c['detail']}")
            else:
                mark = "✓" if c["ok"] else "✗"
                print(f"  {mark} {c['name']}" + (f" — {c['detail']}" if c["detail"] else ""))
        print("基础环境就绪；LLM 深度功能为可选项。")
    return 0 if ok else 1


def cmd_summary(args: argparse.Namespace) -> int:
    """零配置：在终端打印书的结构/章节摘要。"""
    import json

    path = Path(args.path)
    if not path.exists():
        print(f"文件不存在: {path}", file=sys.stderr)
        return 1
    title = args.title or path.stem
    _name, chunks = _load_chunks(path, title)
    groups: dict[int, list[dict]] = {}
    for c in chunks:
        ch = c.get("chapter") or 0
        groups.setdefault(ch, []).append(c)
    chapters = []
    for ch in sorted(groups):
        text = " ".join(str(c.get("text", "")) for c in groups[ch])
        excerpt = " ".join(text.split())[:80]
        chapters.append({"chapter": ch, "excerpt": excerpt})
    if getattr(args, "json", False):
        print(json.dumps({"title": title, "chapter_count": len(groups), "chapters": chapters}, ensure_ascii=False, indent=2))
    else:
        print(f"《{title}》 · {len(groups)} 章")
        for ch in chapters:
            print(f"  第{ch['chapter']}章：{ch['excerpt']}")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    """零配置：统计书库规模（本数/章数/字数）。"""
    import json

    from bookscope.local_tools import stats_folder

    folder = Path(args.path)
    try:
        stats = stats_folder(folder)
    except Exception as exc:  # noqa: BLE001
        print(f"统计失败: {exc}", file=sys.stderr)
        return 1
    if getattr(args, "json", False):
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    else:
        print(f"书库：{stats['books']} 本 · {stats['chapters']} 章 · {stats['chars']} 字")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    """零配置：在一个文件夹里跨书本地检索关键词。"""
    import json

    from bookscope.local_tools import search_folder

    folder = Path(args.path)
    try:
        results = search_folder(folder, args.query, top_k=args.top)
    except Exception as exc:  # noqa: BLE001
        print(f"检索失败: {exc}", file=sys.stderr)
        return 1
    if getattr(args, "json", False):
        print(json.dumps({"query": args.query, "results": results, "count": len(results)}, ensure_ascii=False, indent=2))
    else:
        if not results:
            print("没有找到匹配")
        else:
            for r in results:
                print(f"[{r['book']} · 第{r['chapter']}章] {r['text']}")
    return 0


def cmd_catalog(args: argparse.Namespace) -> int:
    """零配置：把一个文件夹生成可浏览的 HTML 书库目录。"""
    import json

    from bookscope.local_tools import generate_catalog

    folder = Path(args.path)
    out_dir = Path(args.out)
    try:
        index_path, entries = generate_catalog(folder, out_dir)
    except Exception as exc:  # noqa: BLE001
        print(f"生成失败: {exc}", file=sys.stderr)
        return 1
    if getattr(args, "json", False):
        print(json.dumps({"index": str(index_path.resolve()), "count": len(entries), "entries": entries}, ensure_ascii=False, indent=2))
    else:
        print(f"已生成书库目录: {index_path.resolve()} ({len(entries)} 本)")
    return 0


def cmd_self_test(args: argparse.Namespace) -> int:
    """零配置核心链路自检：读文件 → 结构报告 → 导入 → 本地问答。"""
    import tempfile

    from bookscope.local_tools import import_file, load_chunks, local_search, structure_report_html

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        book = root / "sample.txt"
        book.write_text("第一章 开端\n这是关于经济改革的讨论。\n第二章 发展\n这里提到市场与政府的关系。\n", encoding="utf-8")

        # 1. 结构报告
        html = structure_report_html(book, title="自检书")
        assert "<!DOCTYPE html>" in html
        print("  ✓ 结构报告")

        # 2. 导入
        data_dir = root / "sessions"
        session_id = import_file(book, data_dir, title="自检书")
        assert session_id.startswith("api-")
        print(f"  ✓ 导入书库 {session_id}")

        # 3. 本地问答
        _name, _b, _results, chunks = load_chunks(book, title="自检书")
        results = local_search("市场与政府", chunks)
        assert results
        print(f"  ✓ 本地问答（{len(results)} 条相关）")

    print("零配置核心链路自检通过")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    path = Path(args.path)
    if not path.exists():
        print(f"文件不存在: {path}", file=sys.stderr)
        return 1
    title = args.title or path.stem
    print(f"正在读取 {path} …", file=sys.stderr)
    book = load_text(path, title=title)
    print("正在分章/切块 …", file=sys.stderr)
    results, stats = chunk_book_with_stats(book)
    chunks = _chunks_to_dicts(results)

    if getattr(args, "deep", False):
        api_key = args.api_key or os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            print("深度报告需要 LLM key：--api-key 或环境变量 DEEPSEEK_API_KEY / OPENAI_API_KEY", file=sys.stderr)
            return 2
        provider = args.provider or "deepseek"
        model = args.model or "deepseek-v4-flash"
        try:
            client = _build_client(provider, api_key, args.base_url, model)
        except Exception as exc:  # noqa: BLE001
            print(f"LLM client 构建失败: {exc}", file=sys.stderr)
            return 2
        from bookscope.agent._internal.chapter_spine_cache import get_or_build_spine
        from bookscope.report.builders import build_book_report

        print(f"正在构建《{title}》章脉（首次较慢，之后走缓存）…", file=sys.stderr)
        spine = get_or_build_spine(chunks=chunks, llm_client=client, model=model, genre="fiction")
        meta = {
            "title": f"《{title}》书鉴报告",
            "subtitle": f"{len(spine)} 章 · 深度版",
            "seal": "书 鉴",
            "nav_title": "书鉴 · 报告导航",
            "unit_label": "章",
            "generated_by": "书鉴 BookScope CLI",
        }
        inp = build_book_report(spine, meta)
    else:
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
    if getattr(args, "stdout", False):
        sys.stdout.write(html)
        return 0
    out = Path(args.out)
    out.write_text(html, encoding="utf-8")
    if getattr(args, "json", False):
        import json

        print(json.dumps({
            "out": str(out.resolve()),
            "bytes": len(html),
            "mode": "deep" if getattr(args, "deep", False) else "structure",
            "title": title,
        }, ensure_ascii=False, indent=2))
    else:
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

    p_version = sub.add_parser("version", help="显示版本号")
    p_version.set_defaults(func=cmd_version)

    p_doctor = sub.add_parser("doctor", help="检查本地环境")
    p_doctor.add_argument("--json", action="store_true", help="以 JSON 输出检查结果")
    p_doctor.set_defaults(func=cmd_doctor)

    p_summary = sub.add_parser("summary", help="零配置：在终端打印书的结构/章节摘要")
    p_summary.add_argument("path", help="书文件路径（txt / epub / pdf / docx / md）")
    p_summary.add_argument("--title", default=None, help="书名（默认取文件名）")
    p_summary.add_argument("--json", action="store_true", help="以 JSON 输出章节摘要")
    p_summary.set_defaults(func=cmd_summary)

    p_stats = sub.add_parser("stats", help="零配置：统计书库规模（本数/章数/字数）")
    p_stats.add_argument("path", help="书库文件夹路径")
    p_stats.add_argument("--json", action="store_true", help="以 JSON 输出统计")
    p_stats.set_defaults(func=cmd_stats)

    p_search = sub.add_parser("search", help="零配置：在文件夹里跨书本地检索关键词")
    p_search.add_argument("path", help="书库文件夹路径")
    p_search.add_argument("query", help="关键词")
    p_search.add_argument("--top", type=int, default=3, help="每本书返回条数（默认 3）")
    p_search.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    p_search.set_defaults(func=cmd_search)

    p_catalog = sub.add_parser("catalog", help="把一个文件夹生成可浏览的 HTML 书库目录")
    p_catalog.add_argument("path", help="书库文件夹路径")
    p_catalog.add_argument("--out", default="bookscope-catalog", help="输出目录（默认 bookscope-catalog）")
    p_catalog.add_argument("--json", action="store_true", help="以 JSON 输出目录结果")
    p_catalog.set_defaults(func=cmd_catalog)

    p_self_test = sub.add_parser("self-test", help="零配置核心链路自检")
    p_self_test.set_defaults(func=cmd_self_test)

    p_report = sub.add_parser("report", help="把一本书秒出结构版 HTML 报告")
    p_report.add_argument("path", help="书文件路径（txt / epub / pdf / docx / md）")
    p_report.add_argument("--out", default=DEFAULT_OUT, help=f"输出 HTML 路径（默认 {DEFAULT_OUT}）")
    p_report.add_argument("--title", default=None, help="书名（默认取文件名）")
    p_report.add_argument("--deep", action="store_true", help="生成深度版（需要 LLM key，首次较慢）")
    p_report.add_argument("--provider", default="deepseek", help="LLM 厂商（默认 deepseek）")
    p_report.add_argument("--api-key", default=None, help="LLM API key（默认读 DEEPSEEK_API_KEY / OPENAI_API_KEY）")
    p_report.add_argument("--model", default=None, help="模型名（默认 deepseek-v4-flash）")
    p_report.add_argument("--base-url", default=None, help="OpenAI 兼容 base_url")
    p_report.add_argument("--open", action="store_true", help="生成后自动在浏览器打开")
    p_report.add_argument("--json", action="store_true", help="以 JSON 输出生成结果元数据")
    p_report.add_argument("--stdout", action="store_true", help="把 HTML 输出到 stdout（不写文件）")
    p_report.set_defaults(func=cmd_report)

    p_prewarm = sub.add_parser("prewarm", help="预建一本书的章脉缓存（后续操作秒出）")
    p_prewarm.add_argument("path", help="书文件路径（txt / epub / pdf / docx / md）")
    p_prewarm.add_argument("--title", default=None, help="书名（默认取文件名）")
    p_prewarm.add_argument("--provider", default="deepseek", help="LLM 厂商（默认 deepseek）")
    p_prewarm.add_argument("--api-key", default=None, help="LLM API key（默认读 DEEPSEEK_API_KEY / OPENAI_API_KEY）")
    p_prewarm.add_argument("--model", default=None, help="模型名（默认 deepseek-v4-flash）")
    p_prewarm.add_argument("--base-url", default=None, help="OpenAI 兼容 base_url")
    p_prewarm.set_defaults(func=cmd_prewarm)

    p_cluster = sub.add_parser("cluster", help="多个文件直接出簇关系网 HTML 报告（两两对照聚合）")
    p_cluster.add_argument("files", nargs="+", help="2-8 个书/文档路径")
    p_cluster.add_argument("--name", default=None, help="簇/组名（默认 文档簇）")
    p_cluster.add_argument("--out", default="bookscope-cluster.html", help="输出 HTML 路径（默认 bookscope-cluster.html）")
    p_cluster.add_argument("--provider", default="deepseek", help="LLM 厂商（默认 deepseek）")
    p_cluster.add_argument("--api-key", default=None, help="LLM API key（默认读 DEEPSEEK_API_KEY / OPENAI_API_KEY）")
    p_cluster.add_argument("--model", default=None, help="模型名（默认 deepseek-v4-flash）")
    p_cluster.add_argument("--base-url", default=None, help="OpenAI 兼容 base_url")
    p_cluster.add_argument("--open", action="store_true", help="生成后自动在浏览器打开")
    p_cluster.set_defaults(func=cmd_cluster)

    p_list = sub.add_parser("list", help="列出书库里已导入的书")
    p_list.add_argument("--data-dir", default="data/sessions", help="书库数据目录（默认 data/sessions）")
    p_list.add_argument("--json", action="store_true", help="以 JSON 输出书库列表")
    p_list.set_defaults(func=cmd_list)

    p_import = sub.add_parser("import", help="把本地文件导入书库（Web 直接可见）")
    p_import.add_argument("paths", nargs="+", help="一个或多个文件/文件夹路径（txt / epub / pdf / docx / md）")
    p_import.add_argument("--title", default=None, help="书名（默认取文件名）")
    p_import.add_argument("--data-dir", default="data/sessions", help="书库数据目录（默认 data/sessions）")
    p_import.add_argument("--json", action="store_true", help="以 JSON 输出导入结果")
    p_import.set_defaults(func=cmd_import)

    p_ask = sub.add_parser("ask", help="对一本书直接提问，输出带原文引用的答案")
    p_ask.add_argument("path", help="书文件路径（txt / epub / pdf / docx / md）")
    p_ask.add_argument("question", help="要问的问题")
    p_ask.add_argument("--title", default=None, help="书名（默认取文件名）")
    p_ask.add_argument("--provider", default="deepseek", help="LLM 厂商（默认 deepseek）")
    p_ask.add_argument("--api-key", default=None, help="LLM API key（默认读 DEEPSEEK_API_KEY / OPENAI_API_KEY）")
    p_ask.add_argument("--model", default=None, help="模型名（默认 deepseek-v4-flash）")
    p_ask.add_argument("--base-url", default=None, help="OpenAI 兼容 base_url")
    p_ask.add_argument("--json", action="store_true", help="以 JSON 输出 answer + citations")
    p_ask.set_defaults(func=cmd_ask)

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
