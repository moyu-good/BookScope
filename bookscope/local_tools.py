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
    """零配置本地检索：jieba 词重叠打分，返回最相关原文片段。"""
    import jieba

    query_tokens = set(jieba.lcut(question))
    scored: list[tuple[float, int]] = []
    for i, c in enumerate(chunks):
        text = str(c.get("text", ""))
        toks = set(jieba.lcut(text))
        overlap = len(query_tokens & toks)
        if overlap > 0:
            scored.append((float(overlap), i))
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


def default_data_dir() -> Path:
    return Path(os.environ.get("BOOKSCOPE_DATA_DIR", "data/sessions"))
