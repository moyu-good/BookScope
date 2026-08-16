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

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from bookscope.api.book_sessions import BookSessionStore
from bookscope.api.dependencies import get_book_session_store
from bookscope.local_tools import local_search

tools_router = APIRouter(prefix="/tools", tags=["tools"])

_IMPORT_EXTS = {".txt", ".epub", ".pdf", ".docx", ".md", ".markdown"}


class ReportRequest(BaseModel):
    path: str = Field(..., description="本地文件绝对路径")
    title: str | None = Field(default=None)


class ImportRequest(BaseModel):
    path: str = Field(..., description="本地文件或文件夹绝对路径")
    title: str | None = Field(default=None)


class AskLocalRequest(BaseModel):
    session_id: str = Field(..., description="书库 session_id")
    question: str = Field(..., min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)


class CatalogRequest(BaseModel):
    path: str = Field(..., description="书库文件夹绝对路径")
    out: str = Field(default="bookscope-catalog", description="输出目录（默认 bookscope-catalog）")


class SearchRequest(BaseModel):
    path: str = Field(..., description="书库文件夹绝对路径")
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=3, ge=1, le=20)


class StatsRequest(BaseModel):
    path: str = Field(..., description="书库文件夹绝对路径")


class InvokeRequest(BaseModel):
    tool: str = Field(..., description="工具名，如 bookscope_import / bookscope_ask")
    arguments: dict = Field(default_factory=dict, description="工具参数")


def _chunks_to_dicts(results) -> list[dict]:
    return [
        {
            "chunk_id": f"c{idx}",
            "chapter": getattr(c, "chapter", None),
            "text": getattr(c, "text", ""),
        }
        for idx, c in enumerate(results)
    ]


@tools_router.post("/upload")
async def tools_upload(
    file: UploadFile = File(...),
    book_title: str = Form(..., min_length=1),
    language: str = Form("zh"),
) -> dict:
    """零配置单文件上传：不做 LLM KG，直接 ingest + BM25 入库。"""
    filename = file.filename or ""
    suffix = Path(filename).suffix.lower()
    if suffix not in _IMPORT_EXTS:
        raise HTTPException(status_code=400, detail=f"不支持的文件扩展名 {suffix!r}")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件内容为空")

    from bookscope.agent.backends.r0_assembler import R0BookAssembler
    from bookscope.api.book_sessions import BookSessionStore
    from bookscope.api.routes.books import _run_ingest_or_raise
    from bookscope.api.session_storage import JSONFileSessionStorage
    from bookscope.models.schemas import BookKnowledgeGraph
    from bookscope.store.vector_store import SessionVectorStore

    book_text, chunks, chapter_stats = _run_ingest_or_raise(
        content, suffix, book_title, language,
    )
    kg = BookKnowledgeGraph(
        book_title=book_text.title,
        language=getattr(book_text, "language", language),
        characters=[],
    )
    vector_store = SessionVectorStore(chunks=chunks, enable_vector=True)
    assembler = R0BookAssembler(
        book_text=book_text,
        chunks=chunks,
        knowledge_graph=kg,
        session_vector_store=vector_store,
    )
    assembler.chapter_detection_stats = chapter_stats.to_dict()
    data_dir = Path(os.environ.get("BOOKSCOPE_DATA_DIR", "data/sessions"))
    session_id = f"api-{uuid.uuid4().hex[:12]}"
    storage = JSONFileSessionStorage(root=data_dir)
    store = BookSessionStore(storage=storage)
    store.register(session_id, assembler)
    return {
        "session_id": session_id,
        "book_title": book_text.title,
        "language": getattr(book_text, "language", language),
        "chunk_count": len(chunks),
        "character_count": len(getattr(book_text, "raw_text", "") or ""),
        "message": "零配置导入完成（未做 LLM KG，深度分析需配置 key 后重新生成）",
    }


@tools_router.post("/ask-local")
def tools_ask_local(
    req: AskLocalRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> dict:
    """零配置本地问答：对已导入 session 做本地检索，返回相关原文。"""
    try:
        assembler = store.get(req.session_id)
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=f"book session 不存在: {req.session_id}")
    chunks = []
    for i, c in enumerate(assembler._chunks):  # noqa: SLF001
        chunks.append({
            "chunk_id": f"c{i}",
            "chapter": getattr(c, "chapter", None),
            "text": getattr(c, "text", ""),
        })
    results = local_search(req.question, chunks, top_k=req.top_k)
    return {"mode": "local", "results": results}


@tools_router.get("/manifest")
def tools_manifest() -> dict:
    """返回 AI 助手可用的工具清单（function calling schema）。"""
    import json
    from pathlib import Path as _P

    manifest_path = _P(__file__).resolve().parents[2] / "tools_manifest.json"
    return json.loads(manifest_path.read_text(encoding="utf-8"))


@tools_router.post("/invoke")
def tools_invoke(req: InvokeRequest) -> dict:
    """AI 助手工具调用入口：按 tool 名 + 参数执行本地零配置能力。"""
    from bookscope.local_tools import (
        analyze_file,
        cluster_files,
        cross_files,
        generate_catalog,
        import_file,
        local_search,
        search_folder,
        spine_progress,
        stats_folder,
        structure_report_html,
        verify_quote,
    )

    args = req.arguments or {}
    data_dir = Path(os.environ.get("BOOKSCOPE_DATA_DIR", "data/sessions"))
    try:
        if req.tool == "bookscope_import":
            path = Path(args["path"])
            sid = import_file(path, data_dir, title=args.get("title"))
            return {"session_id": sid, "book_title": args.get("title") or path.stem}
        if req.tool == "bookscope_report":
            path = Path(args["path"])
            return {"html": structure_report_html(path, title=args.get("title"))}
        if req.tool == "bookscope_ask":
            # 零配置：先按 session 取 chunks 做本地检索；如需 LLM 由上层再接 /api/agent/ask
            from bookscope.api.book_sessions import BookSessionStore
            from bookscope.api.session_storage import JSONFileSessionStorage

            store = BookSessionStore(storage=JSONFileSessionStorage(root=data_dir))
            assembler = store.get(args["session_id"])
            chunks = []
            for i, c in enumerate(assembler._chunks):  # noqa: SLF001
                chunks.append({"chunk_id": f"c{i}", "chapter": getattr(c, "chapter", None), "text": getattr(c, "text", "")})
            return {"mode": "local", "results": local_search(args["question"], chunks)}
        if req.tool == "bookscope_search":
            return {"results": search_folder(Path(args["path"]), args["query"], top_k=int(args.get("top_k", 3)))}
        if req.tool == "bookscope_progress":
            return spine_progress(
                Path(args["path"]),
                model=args.get("model", "deepseek-v4-flash"),
                genre=args.get("genre", "fiction"),
            )
        if req.tool == "bookscope_visualize":
            from bookscope.report.visual_report import render_visual_report

            if args.get("data"):
                return {"html": render_visual_report(args["data"]), "mode": "precomputed"}

            import os as _os

            api_key = args.get("api_key") or _os.environ.get("DEEPSEEK_API_KEY") or _os.environ.get("OPENAI_API_KEY") or ""
            if not api_key:
                raise ValueError("可视化分析需要 AI 助手提供 LLM 能力（api_key 或环境变量）")
            from bookscope.api.book_sessions import BookSessionStore
            from bookscope.api.routes import agent as agent_routes
            from bookscope.api.schemas import (
                ArgumentStructureRequest,
                CharacterArcRequest,
                CharacterGraphRequest,
                ConsistencyScanRequest,
                ForeshadowArcsRequest,
                MotifTrackingRequest,
                NarrativeCurveRequest,
                NarrativePhasesRequest,
                RecapRequest,
                RelationshipTimelineRequest,
                TimelineRequest,
                WritingTechniqueRequest,
            )
            from bookscope.api.session_storage import JSONFileSessionStorage

            sid = args.get("session_id")
            if not sid:
                sid = import_file(Path(args["path"]), data_dir, title=args.get("title"))
            store = BookSessionStore(storage=JSONFileSessionStorage(root=data_dir))
            provider = args.get("provider", "deepseek")
            model = args.get("model", "deepseek-v4-flash")
            base_url = args.get("base_url")
            full_mode = args.get("mode", "full") == "full"

            def _mk(cls, **extra):
                return cls(
                    book_session_id=sid,
                    provider=provider,
                    api_key=api_key,
                    model=model,
                    base_url=base_url,
                    **extra,
                )

            data: dict = {}
            errors: dict[str, str] = {}
            try:
                data["narrative_curve"] = agent_routes.agent_narrative_curve(
                    _mk(NarrativeCurveRequest), store
                ).model_dump()
            except Exception as exc:  # noqa: BLE001
                errors["narrative_curve"] = f"{type(exc).__name__}: {exc}"
            if full_mode:
                try:
                    data["narrative_phases"] = agent_routes.agent_narrative_phases(
                        _mk(NarrativePhasesRequest), store
                    ).model_dump()
                except Exception as exc:  # noqa: BLE001
                    errors["narrative_phases"] = f"{type(exc).__name__}: {exc}"
            try:
                data["character_graph"] = agent_routes.agent_character_graph(
                    _mk(CharacterGraphRequest, unit=args.get("unit", "person")), store
                ).model_dump()
            except Exception as exc:  # noqa: BLE001
                errors["character_graph"] = f"{type(exc).__name__}: {exc}"
            if full_mode:
                try:
                    data["character_arc"] = agent_routes.agent_character_arc(
                        _mk(CharacterArcRequest), store
                    ).model_dump()
                except Exception as exc:  # noqa: BLE001
                    errors["character_arc"] = f"{type(exc).__name__}: {exc}"
                try:
                    data["relationship_timeline"] = agent_routes.agent_relationship_timeline(
                        _mk(RelationshipTimelineRequest), store
                    ).model_dump()
                except Exception as exc:  # noqa: BLE001
                    errors["relationship_timeline"] = f"{type(exc).__name__}: {exc}"
            try:
                data["timeline"] = agent_routes.agent_timeline(
                    _mk(TimelineRequest), store
                ).model_dump()
            except Exception as exc:  # noqa: BLE001
                errors["timeline"] = f"{type(exc).__name__}: {exc}"
            try:
                chapters = data.get("narrative_curve", {}).get("chapters", [])
                up_to = max([c.get("chapter", 1) for c in chapters] or [1])
                data["recap"] = agent_routes.agent_recap(
                    _mk(RecapRequest, up_to_chapter=up_to), store
                ).model_dump()
            except Exception as exc:  # noqa: BLE001
                errors["recap"] = f"{type(exc).__name__}: {exc}"
            concept = args.get("concept")
            if concept:
                try:
                    from bookscope.api.schemas import ConceptEvolutionRequest

                    data["concept_evolution"] = agent_routes.agent_concept_evolution(
                        _mk(ConceptEvolutionRequest, concept=concept), store
                    ).model_dump()
                except Exception as exc:  # noqa: BLE001
                    errors["concept_evolution"] = f"{type(exc).__name__}: {exc}"
            if full_mode:
                try:
                    data["argument_structure"] = agent_routes.agent_argument_structure(
                        _mk(ArgumentStructureRequest), store
                    ).model_dump()
                except Exception as exc:  # noqa: BLE001
                    errors["argument_structure"] = f"{type(exc).__name__}: {exc}"
            if full_mode:
                try:
                    data["writing_technique"] = agent_routes.agent_writing_technique(
                        _mk(WritingTechniqueRequest), store
                    ).model_dump()
                except Exception as exc:  # noqa: BLE001
                    errors["writing_technique"] = f"{type(exc).__name__}: {exc}"
            motif = args.get("motif") or concept
            if motif and full_mode:
                try:
                    data["motif_tracking"] = agent_routes.agent_motif_tracking(
                        _mk(MotifTrackingRequest, motif=motif), store
                    ).model_dump()
                except Exception as exc:  # noqa: BLE001
                    errors["motif_tracking"] = f"{type(exc).__name__}: {exc}"
            if full_mode:
                try:
                    data["foreshadow_arcs"] = agent_routes.agent_foreshadow_arcs(
                        _mk(ForeshadowArcsRequest), store
                    ).model_dump()
                except Exception as exc:  # noqa: BLE001
                    errors["foreshadow_arcs"] = f"{type(exc).__name__}: {exc}"
            if full_mode:
                try:
                    data["consistency_scan"] = agent_routes.agent_consistency_scan(
                        _mk(ConsistencyScanRequest), store
                    ).model_dump()
                except Exception as exc:  # noqa: BLE001
                    errors["consistency_scan"] = f"{type(exc).__name__}: {exc}"

            meta = {"book": args.get("title") or Path(args.get("path", "")).stem or sid, "title": args.get("title") or "长文档逻辑梳理"}
            data["meta"] = meta
            html = render_visual_report(data)
            return {"html": html, "session_id": sid, "mode": "live", "errors": errors}

        if req.tool == "bookscope_deep_report":
            import os as _os

            from bookscope.local_tools import load_chunks

            path = Path(args["path"])
            model = args.get("model", "deepseek-v4-flash")
            sid = import_file(path, data_dir, title=args.get("title"))
            name, _book, _results, chunks = load_chunks(path, args.get("title"))
            progress = spine_progress(path, model=model, genre="fiction")
            api_key = args.get("api_key") or _os.environ.get("DEEPSEEK_API_KEY") or _os.environ.get("OPENAI_API_KEY") or ""
            if progress["ready"]:
                from bookscope.agent._internal.chapter_spine_cache import peek_spine_cache
                from bookscope.report.builders import build_book_report
                from bookscope.report.service import render_report

                spine = peek_spine_cache(chunks=chunks, model=model, genre="fiction")
                if spine:
                    meta = {
                        "title": f"《{name}》书鉴报告",
                        "subtitle": f"已覆盖 {progress['built']}/{progress['total']} 章 · 深度章脉就绪",
                        "seal": "书 鉴",
                        "nav_title": "书鉴 · 报告导航",
                        "unit_label": "章",
                        "generated_by": f"书鉴 BookScope · 《{name}》",
                    }
                    html = render_report(build_book_report(spine, meta))
                    return {"html": html, "coverage": "full", "session_id": sid, "progress": progress}
            html = structure_report_html(path, title=args.get("title"))
            result = {
                "html": html,
                "coverage": "structure",
                "session_id": sid,
                "progress": progress,
            }
            if api_key:
                from bookscope.api.book_sessions import BookSessionStore
                from bookscope.api.routes.agent import (
                    _build_prewarm_client,
                    _start_prewarm_for_session,
                )
                from bookscope.api.session_storage import JSONFileSessionStorage

                store = BookSessionStore(storage=JSONFileSessionStorage(root=data_dir))
                client = _build_prewarm_client(
                    provider=args.get("provider", "deepseek"),
                    api_key=api_key,
                    base_url=args.get("base_url"),
                )
                status = _start_prewarm_for_session(
                    store=store,
                    book_session_id=sid,
                    client=client,
                    model=model,
                )
                result["prewarm_status"] = status
            return result
        if req.tool == "bookscope_verify":
            return verify_quote(
                Path(args["path"]),
                args["quote"],
                context_chars=int(args.get("context_chars", 120)),
            )
        if req.tool == "bookscope_analyze":
            import os as _os

            api_key = args.get("api_key") or _os.environ.get("DEEPSEEK_API_KEY") or _os.environ.get("OPENAI_API_KEY") or ""
            result = analyze_file(
                Path(args["path"]),
                data_dir=data_dir,
                title=args.get("title"),
                question=args.get("question"),
                top_k=int(args.get("top_k", 5)),
                model=args.get("model", "deepseek-v4-flash"),
            )
            if api_key:
                from bookscope.api.book_sessions import BookSessionStore
                from bookscope.api.routes.agent import (
                    _build_prewarm_client,
                    _start_prewarm_for_session,
                )
                from bookscope.api.session_storage import JSONFileSessionStorage

                store = BookSessionStore(storage=JSONFileSessionStorage(root=data_dir))
                client = _build_prewarm_client(
                    provider=args.get("provider", "deepseek"),
                    api_key=api_key,
                    base_url=args.get("base_url"),
                )
                model = args.get("model", "deepseek-v4-flash")
                status = _start_prewarm_for_session(
                    store=store,
                    book_session_id=result["session_id"],
                    client=client,
                    model=model,
                )
                result["prewarm_status"] = status
            return result
        if req.tool == "bookscope_prewarm":
            import os as _os

            api_key = args.get("api_key") or _os.environ.get("DEEPSEEK_API_KEY") or _os.environ.get("OPENAI_API_KEY") or ""
            if not api_key:
                raise ValueError("预建章脉需要 LLM key（api_key 或环境变量）")
            from bookscope.api.book_sessions import BookSessionStore
            from bookscope.api.routes.agent import _build_prewarm_client, _start_prewarm_for_session
            from bookscope.api.session_storage import JSONFileSessionStorage

            store = BookSessionStore(storage=JSONFileSessionStorage(root=data_dir))
            client = _build_prewarm_client(
                provider=args.get("provider", "deepseek"),
                api_key=api_key,
                base_url=args.get("base_url"),
            )
            model = args.get("model") or "deepseek-v4-flash"
            status = _start_prewarm_for_session(
                store=store,
                book_session_id=args["session_id"],
                client=client,
                model=model,
            )
            return {"status": status, "book_session_id": args["session_id"], "model": model}
        if req.tool == "bookscope_stats":
            return stats_folder(Path(args["path"]))
        if req.tool == "bookscope_catalog":
            index_path, entries = generate_catalog(Path(args["path"]), Path(args.get("out", "bookscope-catalog")))
            return {"index": str(index_path.resolve()), "count": len(entries), "entries": entries}
        if req.tool == "bookscope_cross":
            import os as _os

            api_key = args.get("api_key") or _os.environ.get("DEEPSEEK_API_KEY") or _os.environ.get("OPENAI_API_KEY") or ""
            if not api_key:
                raise ValueError("跨文本对照需要 LLM key（api_key 或环境变量）")
            html = cross_files(
                Path(args["file1"]),
                Path(args["file2"]),
                api_key=api_key,
                provider=args.get("provider", "deepseek"),
                model=args.get("model", "deepseek-v4-flash"),
                base_url=args.get("base_url"),
            )
            return {"html": html}
        if req.tool == "bookscope_cluster":
            import os as _os

            api_key = args.get("api_key") or _os.environ.get("DEEPSEEK_API_KEY") or _os.environ.get("OPENAI_API_KEY") or ""
            if not api_key:
                raise ValueError("簇关系发现需要 LLM key（api_key 或环境变量）")
            files = [Path(x) for x in args["files"]]
            html = cluster_files(
                files,
                api_key=api_key,
                name=args.get("name", "文档簇"),
                provider=args.get("provider", "deepseek"),
                model=args.get("model", "deepseek-v4-flash"),
                base_url=args.get("base_url"),
            )
            return {"html": html}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"{req.tool} 调用失败: {exc}")
    raise HTTPException(status_code=400, detail=f"未知工具: {req.tool}")


@tools_router.post("/stats")
def tools_stats(req: StatsRequest) -> dict:
    """零配置：统计书库规模。"""
    from bookscope.local_tools import stats_folder

    try:
        return stats_folder(Path(req.path))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc))


@tools_router.post("/search")
def tools_search(req: SearchRequest) -> dict:
    """零配置：在文件夹里跨书本地检索关键词。"""
    from bookscope.local_tools import search_folder

    try:
        results = search_folder(Path(req.path), req.query, top_k=req.top_k)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc))
    return {"query": req.query, "results": results, "count": len(results)}


@tools_router.post("/catalog")
def tools_catalog(req: CatalogRequest) -> dict:
    """零配置生成 HTML 书库目录。"""
    from bookscope.local_tools import generate_catalog

    try:
        index_path, entries = generate_catalog(Path(req.path), Path(req.out))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "index": str(index_path.resolve()),
        "count": len(entries),
        "entries": entries,
    }


@tools_router.post("/report")
def tools_report(req: ReportRequest) -> Response:
    path = Path(req.path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"文件不存在: {path}")
    from bookscope.local_tools import structure_report_html

    html = structure_report_html(path, title=req.title)
    return Response(content=html, media_type="text/html; charset=utf-8", headers={"X-Report-Coverage": "structure"})


def _import_one(path: Path, data_dir: Path, title: str | None = None) -> str:
    from bookscope.local_tools import import_file

    return import_file(path, data_dir, title=title)


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
