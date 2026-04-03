"""BookScope v3 — FastAPI backend.

Endpoints:
    POST /api/upload    — Upload a text file, returns session_id
    POST /api/extract   — Trigger knowledge extraction (SSE progress stream)
    POST /api/chat/stream — Chat with the book (SSE streaming)

Run:
    uvicorn bookscope.api.main:app --reload --port 8000
"""

import json
import os
import tempfile
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from bookscope.ingest import chunk_book, clean, load_text
from bookscope.models import BookKnowledgeGraph
from bookscope.nlp.knowledge_extractor import extract_knowledge_graph
from bookscope.nlp.lang_detect import detect_language
from bookscope.nlp.llm_analyzer import call_llm

try:
    from bookscope.store.vector_store import SessionVectorStore
except ImportError:
    SessionVectorStore = None  # type: ignore[assignment,misc]

app = FastAPI(title="BookScope API", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory session store (single worker)
_sessions: dict[str, dict] = {}


def _get_api_key() -> str | None:
    return os.environ.get("ANTHROPIC_API_KEY")


# ---------------------------------------------------------------------------
# POST /api/upload
# ---------------------------------------------------------------------------

class UploadResponse(BaseModel):
    session_id: str
    title: str
    language: str
    total_chunks: int


@app.post("/api/upload", response_model=UploadResponse)
async def upload_file(file: UploadFile = File(...)):
    """Upload a text file and prepare chunks for analysis."""
    content = await file.read()
    title = Path(file.filename or "untitled").stem
    suffix = Path(file.filename or "file.txt").suffix.lower() or ".txt"

    # Save to temp file so load_text can handle .txt/.epub/.pdf
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        book = load_text(tmp_path, title=title)
    finally:
        tmp_path.unlink(missing_ok=True)

    cleaned_text = clean(book.raw_text)
    lang = detect_language(cleaned_text)
    book.language = lang

    chunks = chunk_book(book)

    # Build FAISS vector index for RAG (graceful fallback if deps missing)
    vector_store = None
    if SessionVectorStore is not None:
        try:
            vector_store = SessionVectorStore(chunks)
        except Exception:
            pass  # degrade to KG-only chat

    session_id = uuid.uuid4().hex[:12]
    _sessions[session_id] = {
        "title": title,
        "book": book,
        "chunks": chunks,
        "knowledge_graph": None,
        "vector_store": vector_store,
    }

    return UploadResponse(
        session_id=session_id,
        title=title,
        language=lang,
        total_chunks=len(chunks),
    )


# ---------------------------------------------------------------------------
# POST /api/extract
# ---------------------------------------------------------------------------

class ExtractRequest(BaseModel):
    session_id: str
    model: str = "claude-haiku-4-5"


@app.post("/api/extract")
async def extract(req: ExtractRequest):
    """Extract knowledge graph from uploaded book. Returns SSE progress stream."""
    session = _sessions.get(req.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    api_key = _get_api_key()
    if not api_key:
        raise HTTPException(
            status_code=422,
            detail="请设置环境变量 ANTHROPIC_API_KEY 后重启后端",
        )

    chunks = session["chunks"]
    book = session["book"]

    def event_stream():
        progress_events: list[str] = []

        def collect_progress(current: int, total: int):
            progress_events.append(
                f"data: {json.dumps({'type': 'progress', 'current': current, 'total': total})}\n\n"
            )

        graph = extract_knowledge_graph(
            chunks=chunks,
            book_title=book.title,
            language=book.language,
            api_key=api_key,
            model=req.model,
            progress_callback=collect_progress,
        )
        session["knowledge_graph"] = graph

        # Yield all collected progress events
        yield from progress_events

        # Final result
        result_data = json.dumps({"type": "done", "graph": graph.model_dump()})
        yield f"data: {result_data}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# RAG context builder
# ---------------------------------------------------------------------------

_CHUNK_CHAR_LIMIT = 600
_RAG_TOP_K = 5


def _build_chat_context(book, graph, vector_store, message: str) -> str:
    """Build hybrid context: RAG-retrieved chunks + condensed knowledge graph."""
    parts = [f"书名: {book.title}", f"语言: {book.language}"]

    # Layer 1: Knowledge graph summary (condensed)
    if graph:
        if graph.overall_summary:
            parts.append(f"\n--- 书籍概要 ---\n{graph.overall_summary}")
        chars_desc = []
        for c in graph.characters[:4]:
            line = c.name
            if c.description:
                line += f" — {c.description[:80]}"
            chars_desc.append(line)
        if chars_desc:
            parts.append("主要人物: " + "; ".join(chars_desc))

    # Layer 2: RAG-retrieved chunks (primary evidence)
    if vector_store is not None:
        retrieved = vector_store.search(message, top_k=_RAG_TOP_K)
        if retrieved:
            parts.append("\n--- 相关段落 ---")
            for chunk_result, score in retrieved:
                text = chunk_result.text[:_CHUNK_CHAR_LIMIT]
                parts.append(f"[段落 {chunk_result.index + 1} (相关度: {score:.2f})]\n{text}")
    elif graph:
        # Fallback: chapter summaries when no vector store
        for ch in graph.chapter_summaries[:10]:
            if ch.summary:
                parts.append(f"段落{ch.chunk_index}: {ch.summary}")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# POST /api/chat/stream
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    session_id: str
    message: str
    model: str = "claude-haiku-4-5"


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    """Chat about the book using extracted knowledge. Returns SSE stream."""
    session = _sessions.get(req.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    api_key = _get_api_key()
    if not api_key:
        raise HTTPException(
            status_code=422,
            detail="请设置环境变量 ANTHROPIC_API_KEY 后重启后端",
        )

    graph: BookKnowledgeGraph | None = session.get("knowledge_graph")
    book = session["book"]
    vector_store = session.get("vector_store")

    context = _build_chat_context(book, graph, vector_store, req.message)

    prompt = (
        f"你是一个书籍分析助手。根据以下书籍信息和相关段落回答用户问题。\n"
        f"如果信息不足以回答，请如实说明。\n\n"
        f"{context}\n\n"
        f"用户问题: {req.message}"
    )

    def event_stream():
        # For now, single-shot response (streaming will be added with Anthropic streaming API)
        response = call_llm(prompt, api_key=api_key, model=req.model, max_tokens=800) or ""
        data = json.dumps({"type": "message", "content": response})
        yield f"data: {data}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# GET /api/health
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "3.0.0"}
