"""BookScope 本地工具 API（零配置、不需要 LLM key）。

给脚本/其他软件一个最轻的入口：
- ``POST /api/tools/report``：给一个本地文件路径，直接返回结构版 HTML 报告
- ``POST /api/tools/import``：给一个本地文件/文件夹路径，导入书库并返回 session_id

这些端点只用本地文件系统 + 零 LLM 能力，适合“工具自己就能用”的定位。
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from bookscope.ingest.book_chunker import chunk_book_with_stats
from bookscope.ingest.loader import load_text
from bookscope.report.builders import build_structure_report
from bookscope.report.service import render_report

tools_router = APIRouter(prefix="/tools", tags=["tools"])

_IMPORT_EXTS = {".txt", ".epub", ".pdf", ".docx", ".md", ".markdown"}


class ReportRequest(BaseModel):
    path: str = Field(..., description="本地文件绝对路径")
    title: str | None = Field(default=None)


class ImportRequest(BaseModel):
    path: str = Field(..., description="本地文件或文件夹绝对路径")
    title: str | None = Field(default=None)


def _chunks_to_dicts(results) -> list[dict]:
    return [
        {
            "chunk_id": f"c{idx}",
            "chapter": getattr(c, "chapter", None),
            "text": getattr(c, "text", ""),
        }
        for idx, c in enumerate(results)
    ]


@tools_router.post("/report")
def tools_report(req: ReportRequest) -> Response:
    path = Path(req.path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"文件不存在: {path}")
    title = req.title or path.stem
    book = load_text(path, title=title)
    results, stats = chunk_book_with_stats(book)
    chunks = _chunks_to_dicts(results)
    meta = {
        "title": f"《{title}》书鉴报告（结构版）",
        "subtitle": f"{len(chunks)} 个片段 · {stats.chapters_detected if hasattr(stats, 'chapters_detected') else '?'} 章 · 零 LLM 秒出",
        "seal": "书 鉴",
        "nav_title": "书鉴 · 报告导航",
        "unit_label": "章",
        "generated_by": "书鉴 BookScope Tools API",
    }
    html = render_report(build_structure_report(chunks, meta))
    return Response(content=html, media_type="text/html; charset=utf-8", headers={"X-Report-Coverage": "structure"})


def _import_one(path: Path, data_dir: Path, title: str | None = None) -> str:
    from bookscope.agent.backends.r0_assembler import R0BookAssembler
    from bookscope.api.book_sessions import BookSessionStore
    from bookscope.api.session_storage import JSONFileSessionStorage
    from bookscope.models.schemas import BookKnowledgeGraph

    name = title or path.stem
    book = load_text(path, title=name)
    results, _stats = chunk_book_with_stats(book)
    kg = BookKnowledgeGraph(book_title=name, language=getattr(book, "language", "zh"), characters=[])
    assembler = R0BookAssembler(
        book_text=book,
        chunks=results,
        knowledge_graph=kg,
        session_vector_store=None,
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


@tools_router.post("/import")
def tools_import(req: ImportRequest) -> dict:
    path = Path(req.path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"路径不存在: {path}")
    data_dir = Path(os.environ.get("BOOKSCOPE_DATA_DIR", "data/sessions"))
    if path.is_dir():
        files = [p for p in path.rglob("*") if p.is_file() and p.suffix.lower() in _IMPORT_EXTS]
        if not files:
            raise HTTPException(status_code=400, detail="文件夹里没有支持的文件")
        imported = []
        for f in sorted(files):
            try:
                sid = _import_one(f, data_dir)
                imported.append({"session_id": sid, "file": str(f), "book_title": f.stem})
            except Exception as exc:  # noqa: BLE001
                imported.append({"session_id": None, "file": str(f), "error": str(exc)})
        return {"imported": imported, "count": sum(1 for x in imported if x["session_id"])}
    sid = _import_one(path, data_dir, title=req.title)
    return {"session_id": sid, "book_title": req.title or path.stem}
