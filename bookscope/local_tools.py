"""BookScope 本地工具共享能力（CLI 与 Tools API 共用）。

集中放“零配置、不需要 LLM key”的基础操作：
- 读文件并切成 dict chunks
- 导入书库（跳过 LLM KG，只 ingest + BM25）
- 生成结构版 HTML 报告

CLI 和 /api/tools/* 都从这里取，避免两套逻辑漂移。
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from bookscope.ingest.book_chunker import chunk_book_with_stats
from bookscope.ingest.loader import load_text
from bookscope.report.builders import build_structure_report
from bookscope.report.service import render_report

IMPORT_EXTS = {".txt", ".epub", ".pdf", ".docx", ".md", ".markdown"}


def chunks_to_dicts(results) -> list[dict]:
    """把 ingest 的 ChunkResult 转成报告/章脉需要的 dict 列表。"""
    return [
        {
            "chunk_id": f"c{idx}",
            "chapter": getattr(c, "chapter", None),
            "text": getattr(c, "text", ""),
        }
        for idx, c in enumerate(results)
    ]


def load_chunks(path: Path, title: str | None = None) -> tuple[str, object, list, list[dict]]:
    """读取一本书，返回 (书名, BookText, ChunkResult列表, dict chunks)。"""
    book = load_text(path, title=title)
    results, _stats = chunk_book_with_stats(book)
    name = title or path.stem
    return name, book, results, chunks_to_dicts(results)


def structure_report_html(path: Path, title: str | None = None) -> str:
    """零配置生成结构版 HTML 报告。"""
    name, _book, results, chunks = load_chunks(path, title)
    meta = {
        "title": f"《{name}》书鉴报告（结构版）",
        "subtitle": f"{len(chunks)} 个片段 · 零 LLM 秒出",
        "seal": "书 鉴",
        "nav_title": "书鉴 · 报告导航",
        "unit_label": "章",
        "generated_by": "书鉴 BookScope",
    }
    return render_report(build_structure_report(chunks, meta))


def import_file(path: Path, data_dir: Path, title: str | None = None) -> str:
    """把单个文件导入书库（跳过 LLM KG，只 ingest + BM25）。返回 session_id。"""
    from bookscope.agent.backends.r0_assembler import R0BookAssembler
    from bookscope.api.book_sessions import BookSessionStore
    from bookscope.api.session_storage import JSONFileSessionStorage
    from bookscope.models.schemas import BookKnowledgeGraph
    from bookscope.store.vector_store import SessionVectorStore

    name, book, results, _chunks = load_chunks(path, title)
    kg = BookKnowledgeGraph(
        book_title=name,
        language=getattr(book, "language", "zh"),
        characters=[],
    )
    vector_store = SessionVectorStore(chunks=results, enable_vector=True)
    assembler = R0BookAssembler(
        book_text=book,
        chunks=results,
        knowledge_graph=kg,
        session_vector_store=vector_store,
    )
    try:
        assembler.source_folder = str(path.parent.resolve())
    except Exception:  # noqa: BLE001
        pass
    session_id = f"api-{uuid.uuid4().hex[:12]}"
    storage = JSONFileSessionStorage(root=data_dir)
    store = BookSessionStore(storage=storage)
    store.register(session_id, assembler)
    return session_id


def local_search(question: str, chunks: list[dict], top_k: int = 5) -> list[dict]:
    """零配置本地检索：jieba 分词 + 词频加权，返回最相关原文片段。"""
    import jieba

    query_tokens = [t for t in jieba.lcut(question) if t.strip()]
    scored: list[tuple[float, int]] = []
    for i, c in enumerate(chunks):
        text = str(c.get("text", ""))
        score = sum(text.count(t) for t in query_tokens)
        if score > 0:
            scored.append((float(score), i))
    scored.sort(key=lambda x: (-x[0], x[1]))
    results = []
    for score, i in scored[:top_k]:
        c = chunks[i]
        results.append({
            "chapter": c.get("chapter"),
            "text": str(c.get("text", ""))[:300],
            "score": score,
        })
    return results


def stats_folder(folder: Path) -> dict:
    """统计书库规模（本数/章数/字数）。"""
    if not folder.is_dir():
        raise ValueError(f"文件夹不存在: {folder}")
    files = [p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in IMPORT_EXTS]
    total_chapters = 0
    total_chars = 0
    per_book = []
    for f in sorted(files):
        try:
            _name, _book, _results, chunks = load_chunks(f, title=f.stem)
        except Exception:  # noqa: BLE001
            continue
        chapters = len({c.get("chapter") or 0 for c in chunks})
        chars = sum(len(str(c.get("text", ""))) for c in chunks)
        total_chapters += chapters
        total_chars += chars
        per_book.append({"book": f.stem, "chapters": chapters, "chars": chars})
    return {"books": len(per_book), "chapters": total_chapters, "chars": total_chars, "per_book": per_book}


def search_folder(folder: Path, query: str, top_k: int = 3) -> list[dict]:
    """在一个文件夹里跨书本地检索关键词。"""
    if not folder.is_dir():
        raise ValueError(f"文件夹不存在: {folder}")
    files = [p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in IMPORT_EXTS]
    results = []
    for f in sorted(files):
        try:
            _name, _book, _results, chunks = load_chunks(f, title=f.stem)
        except Exception:  # noqa: BLE001
            continue
        for hit in local_search(query, chunks, top_k=top_k):
            results.append({
                "file": str(f),
                "book": f.stem,
                "chapter": hit.get("chapter"),
                "text": hit.get("text", ""),
                "score": hit.get("score", 0),
            })
    return results


def generate_catalog(folder: Path, out_dir: Path) -> tuple[Path, list[dict]]:
    """把一个文件夹生成可浏览的 HTML 书库目录，返回 (index_path, entries)。"""
    import re

    if not folder.is_dir():
        raise ValueError(f"文件夹不存在: {folder}")
    files = [p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in IMPORT_EXTS]
    if not files:
        raise ValueError(f"文件夹里没有支持的文件: {folder}")
    out_dir.mkdir(parents=True, exist_ok=True)

    entries = []
    for f in sorted(files):
        safe = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]", "_", f.stem) or "book"
        rel = f"{safe}.html"
        try:
            html = structure_report_html(f, title=f.stem)
            (out_dir / rel).write_text(html, encoding="utf-8")
            entries.append({"file": str(f), "title": f.stem, "link": rel})
        except Exception as exc:  # noqa: BLE001
            entries.append({"file": str(f), "title": f.stem, "error": str(exc)})

    cards = "".join(
        f'<div style="border:1px solid #E4DCCB;border-radius:10px;padding:14px 16px;margin:10px 0;'
        f'background:#FFFCF5;box-shadow:0 1px 3px rgba(43,38,34,.06)">'
        f'<a href="{e["link"]}" style="font-size:16px;color:#B03A2E;text-decoration:none;font-weight:bold">{e["title"]}</a>'
        f'<div style="font-size:12px;color:#8A8278;margin-top:4px">{e.get("file","")}</div></div>'
        for e in entries if "link" in e
    )
    index = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="UTF-8">
<title>BookScope 书库目录</title></head>
<body style="max-width:760px;margin:40px auto;font-family:sans-serif;color:#2B2622">
<h1 style="color:#B03A2E">📚 BookScope 书库目录</h1>
<p style="color:#5A534C">{len([e for e in entries if 'link' in e])} 本 · {folder}</p>
{cards}
</body></html>"""
    index_path = out_dir / "index.html"
    index_path.write_text(index, encoding="utf-8")
    return index_path, entries


def cross_files(
    file1: Path,
    file2: Path,
    api_key: str,
    provider: str = "deepseek",
    model: str = "deepseek-v4-flash",
    base_url: str | None = None,
) -> str:
    """两个本地文件直接出跨文本对照 HTML 报告（需要 LLM key）。"""
    from bookscope.agent._internal.chapter_spine_cache import get_or_build_spine
    from bookscope.agent.book_cross import (
        build_book_perspective,
        build_cross_book_report_input,
        cross_book_reason,
    )
    from bookscope.api.dependencies import build_llm_client_from_params

    client = build_llm_client_from_params(provider=provider, api_key=api_key, base_url=base_url)
    perspectives = []
    for idx, path in enumerate([file1, file2]):
        name, _book, _results, chunks = load_chunks(path)
        spine = get_or_build_spine(chunks=chunks, llm_client=client, model=model, genre="fiction")
        perspectives.append(build_book_perspective(
            spine=spine, book_title=name, slug=f"b{idx}",
            llm_client=client, model=model,
        ))
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
            "generated_by": "书鉴 BookScope",
        },
    )
    return render_report(inp)


def list_sessions(data_dir: Path) -> list[dict]:
    """列出书库里已导入的书。"""
    import json

    from bookscope.api.session_storage import JSONFileSessionStorage

    storage = JSONFileSessionStorage(root=data_dir)
    books = []
    for sid in sorted(storage.list_all()):
        meta_path = data_dir / sid / "metadata.json"
        title = sid
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                title = meta.get("book_title", sid)
            except Exception:  # noqa: BLE001
                pass
        books.append({"session_id": sid, "book_title": title})
    return books


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


def cluster_files(
    files: list[Path],
    api_key: str,
    name: str = "文档簇",
    provider: str = "deepseek",
    model: str = "deepseek-v4-flash",
    base_url: str | None = None,
) -> str:
    """多个文件直接出簇关系网 HTML 报告（两两对照聚合，需要 LLM key）。"""
    from itertools import combinations

    from bookscope.agent._internal.chapter_spine_cache import get_or_build_spine
    from bookscope.agent.book_cross import (
        build_book_perspective,
        cross_book_reason,
    )
    from bookscope.api.dependencies import build_llm_client_from_params

    if len(files) < 2 or len(files) > 8:
        raise ValueError("簇关系需要 2-8 个文件")
    client = build_llm_client_from_params(provider=provider, api_key=api_key, base_url=base_url)
    perspectives = []
    for idx, path in enumerate(files):
        name_i, _book, _results, chunks = load_chunks(path)
        spine = get_or_build_spine(chunks=chunks, llm_client=client, model=model, genre="fiction")
        perspectives.append(build_book_perspective(
            spine=spine, book_title=name_i, slug=f"b{idx}",
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
    narrative = (
        f"《{name}》共 {len(nodes)} 本，两两对照 {pair_count} 对，"
        f"发现 {len(edges)} 条关系（继承/反驳/补充/落地/检验）。关系为 LLM 研判。"
    )
    inp = {
        "layout": "crossdoc",
        "meta": {
            "title": f"簇关系网 · {name}",
            "subtitle": f"{len(nodes)} 本 · {len(edges)} 条关系（{pair_count} 对两两对照）· 关系为研判",
            "seal": "书 鉴",
            "nav_title": "簇关系 · 导航",
            "unit_label": "本",
            "generated_by": "书鉴 BookScope",
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
    from bookscope.report.service import render_report

    return render_report(inp)


def default_data_dir() -> Path:
    return Path(os.environ.get("BOOKSCOPE_DATA_DIR", "data/sessions"))
