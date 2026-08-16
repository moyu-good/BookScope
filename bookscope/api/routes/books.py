"""books 路由 —— POST /api/books/upload 端点（ADR-004 方案 B）。

一次 upload 的生命周期：

  1. 验证 multipart 参数（文件扩展名、api_key 非空）。
  2. 写入临时文件，交给 :mod:`bookscope.ingest` 三件套：
     ``loader.load_text`` → ``cleaner`` → ``book_chunker.chunk_book``。
  3. 按 provider + api_key 构造 :class:`LLMClient` adapter。
  4. 调 :class:`MinimalKGExtractor` 从 chunks 抽出角色清单，拼装
     :class:`BookKnowledgeGraph`。
  5. 生成 session_id，装配 :class:`R0BookAssembler`，注册到
     :class:`BookSessionStore`（若已配置 storage 则自动持久化）。
  6. 返回 :class:`BookUploadResponse`。

### 错误翻译

- 文件扩展名不支持 / 文件空 / 文件读失败 → HTTP 400
- ingest 空文本 / 解析失败 → HTTP 422
- adapter SDK 未安装 → HTTP 400
- KG 提取 LLM 返回格式异常（LLMFormatError）→ HTTP 502
- Provider 层失败（认证 / 限流 / 不可达）→ HTTP 502 / 429

### vector_store 装配

从 Sprint 5 起 upload 真正构造 :class:`SessionVectorStore` 注入 assembler
（之前 ADR-005 留白的过时 workaround 已修：vector_store.py 早就有
``save_to_dir`` / ``load_from_dir``）。``SessionVectorStore(chunks)`` 只要
传 chunks 就能建 BM25 索引；FAISS vector 是可选的，embedding provider 不
可用时自动 fallback 到 BM25-only（详见 vector_store._build_faiss_index 的
try/except）。这样 BookScope 开箱即可用——不依赖任何 embedding key。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import threading
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse

from bookscope.agent.backends.minimal_kg_extractor import MinimalKGExtractor
from bookscope.agent.backends.r0_assembler import R0BookAssembler
from bookscope.agent.errors import (
    LLMFormatError,
    ProviderError,
    ProviderUnavailable,
    RateLimited,
)
from bookscope.agent.events import IngestEvent
from bookscope.api.book_sessions import BookSessionStore
from bookscope.api.dependencies import (
    build_llm_client_from_params,
    default_model_for,
    get_book_session_store,
)
from bookscope.api.deployment import is_hosted, record_ownership, require_user
from bookscope.api.schemas import (
    BookUploadResponse,
    ImportFolderRequest,
    ImportFolderResponse,
    ImportFolderStatusResponse,
)
from bookscope.ingest.book_chunker import ChapterDetectionStats, chunk_book_with_stats
from bookscope.ingest.loader import EmptyTextError, load_text, normalize_book_title
from bookscope.agent._internal.chapter_spine_cache import get_or_build_spine
from bookscope.models import BookKnowledgeGraph
from bookscope.store.vector_store import SessionVectorStore

logger = logging.getLogger(__name__)

books_router = APIRouter(tags=["books"])

_SUPPORTED_EXTENSIONS = {".epub", ".txt", ".pdf", ".docx", ".md", ".markdown"}
"""upload 支持的文件扩展名,与 ingest.loader.load_text 的分发保持一致(它支持这 6 种)。
其它格式直接 400 拒掉。公文常是 Word(.docx)、md/markdown 也常见——早先门只开 epub/txt/pdf,
loader 扩了 docx/md 这里没同步、把它们挡门外了(本次补齐)。"""


@books_router.post("/books/upload", response_model=BookUploadResponse)
async def upload_book(
    file: UploadFile = File(..., description="epub / txt / pdf 文件内容"),
    book_title: str = Form(..., min_length=1, description="书名"),
    language: str = Form("zh", description="书籍语种；默认 zh"),
    provider: Literal["deepseek", "anthropic"] = Form(
        "deepseek",
        description=(
            "LLM provider：'deepseek' / 'anthropic'。BYOK 原则，服务端不落盘。"
        ),
    ),
    api_key: str = Form(..., min_length=8, description="BYOK API key"),
    model: str | None = Form(None, description="覆盖默认 model（可选）"),
    base_url: str | None = Form(
        None,
        description=(
            "OpenAI 兼容 endpoint 覆盖（可选）。deepseek 走代理 / 其他 OpenAI "
            "兼容 endpoint 时可覆盖；anthropic 忽略。"
        ),
    ),
    store: BookSessionStore = Depends(get_book_session_store),
    user=Depends(require_user),
) -> BookUploadResponse:
    """上传一本书并完成 ingest + KG 抽取 + 装配 + 持久化。

    返回的 ``session_id`` 可直接用于 POST /api/agent/ask。
    """
    # 1. 验证扩展名
    filename = file.filename or ""
    suffix = Path(filename).suffix.lower()
    if suffix not in _SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "UnsupportedFileType",
                "message": (
                    f"不支持的文件扩展名 {suffix!r}；"
                    f"当前支持 {sorted(_SUPPORTED_EXTENSIONS)}。"
                ),
                "details": {"filename": filename, "suffix": suffix},
            },
        )

    # 2. 读取文件到临时路径（避免整个文件吃进内存）
    content = await file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "EmptyFile",
                "message": "上传的文件内容为空。",
                "details": {"filename": filename},
            },
        )

    # 3. 走 ingest 管线（form 传的 book_title 也归一一下半角→全角标点，
    #    保持与 epub 元数据兜底路径一致——用户填 `安史之乱：xxx` 或
    #    `安史之乱 : xxx` 落库都是同一个出版物形态）
    book_title = normalize_book_title(book_title)
    book_text, chunks, chapter_stats = _run_ingest_or_raise(
        content, suffix, book_title, language,
    )

    # 4. 构造 adapter + MinimalKGExtractor
    client = _build_client_or_raise(
        provider=provider, api_key=api_key, base_url=base_url,
    )
    extractor_model = model or default_model_for(provider)
    extractor = MinimalKGExtractor(client=client, model=extractor_model)

    # 5. 提取 KG（LLM 调用，最花时间的一步）
    kg = _extract_kg_or_raise(extractor, chunks=chunks, book_title=book_title, language=language)

    # 6. 装配 SessionVectorStore（BM25 总能建；FAISS vector 可选，
    #    embedding provider 不可用时 SessionVectorStore 内部自动 fallback
    #    到 BM25-only，不阻断上传流程）
    vector_store = SessionVectorStore(chunks=chunks, enable_vector=True)

    # 7. 装配 R0BookAssembler 注入 vector_store
    assembler = R0BookAssembler(
        book_text=book_text,
        chunks=chunks,
        knowledge_graph=kg,
        session_vector_store=vector_store,
    )

    # 7. 生成 session_id，注册（会触发持久化）。章节检测指标挂在
    #    assembler 上随 register 落进 session 元数据（WP3 Phase A）。
    assembler.chapter_detection_stats = chapter_stats.to_dict()
    session_id = uuid.uuid4().hex[:16]
    store.register(session_id, assembler)
    # hosted:把这本书记到当前用户名下(local 是 no-op)。
    record_ownership(user, session_id, book_text.title)

    return BookUploadResponse(
        session_id=session_id,
        book_title=book_text.title,
        language=getattr(book_text, "language", language),
        chunk_count=len(chunks),
        character_count=len(kg.characters),
        chapter_detection=chapter_stats.to_dict(),
    )


@books_router.post("/books/upload/stream")
async def upload_book_stream(
    file: UploadFile = File(..., description="epub / txt / pdf 文件内容"),
    book_title: str = Form(..., min_length=1, description="书名"),
    language: str = Form("zh", description="书籍语种；默认 zh"),
    provider: Literal["deepseek", "anthropic"] = Form(
        "deepseek",
        description=(
            "LLM provider：'deepseek' / 'anthropic'。BYOK 原则，服务端不落盘。"
        ),
    ),
    api_key: str = Form(..., min_length=8, description="BYOK API key"),
    model: str | None = Form(None, description="覆盖默认 model（可选）"),
    base_url: str | None = Form(
        None,
        description=(
            "OpenAI 兼容 endpoint 覆盖（可选）。deepseek 走代理 / 其他 OpenAI "
            "兼容 endpoint 时可覆盖；anthropic 忽略。"
        ),
    ),
    store: BookSessionStore = Depends(get_book_session_store),
    user=Depends(require_user),
) -> StreamingResponse:
    """同 ``/books/upload``，但以 SSE 流推送 KG ingest 进度事件。

    事件序列（典型）::

        event: ingest_started
        data: {"event_type":"ingest_started","total_batches":5,...}

        event: kg_batch_started
        data: {"event_type":"kg_batch_started","batch_index":0,...}

        event: kg_batch_completed
        data: {"event_type":"kg_batch_completed","batch_index":0,...}

        ... (重复每 batch)

        event: ingest_done
        data: {"event_type":"ingest_done","book_session_id":"...",...}

        event: upload_complete
        data: {"session_id":"...","book_title":"...","chunk_count":N,...}

    Setup-time 错误（文件格式不支持 / SDK 缺 / 文件空）仍走 HTTPException
    翻译——SSE 头未发，客户端能收到正常 4xx 状态码。一旦流开始（ingest
    阶段），KG 抽取错误会以 ``ingest_error`` 事件推到客户端再关流，HTTP
    状态仍是 200（SSE 协议约定流内携带错误）。

    末尾追加一帧 ``upload_complete`` 让 FE 拿到 session_id / chunk_count
    等元数据——等价于 sync upload 的 BookUploadResponse 内容。
    """
    # 1-2. 同 sync upload —— 验证文件扩展名 / 读 bytes
    filename = file.filename or ""
    suffix = Path(filename).suffix.lower()
    if suffix not in _SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "UnsupportedFileType",
                "message": (
                    f"不支持的文件扩展名 {suffix!r}；"
                    f"当前支持 {sorted(_SUPPORTED_EXTENSIONS)}。"
                ),
                "details": {"filename": filename, "suffix": suffix},
            },
        )

    content = await file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "EmptyFile",
                "message": "上传的文件内容为空。",
                "details": {"filename": filename},
            },
        )

    # 3. ingest 管线（同 sync upload）
    book_title = normalize_book_title(book_title)
    book_text, chunks, chapter_stats = _run_ingest_or_raise(
        content, suffix, book_title, language,
    )

    # 4. adapter 构造
    client = _build_client_or_raise(
        provider=provider, api_key=api_key, base_url=base_url,
    )
    extractor_model = model or default_model_for(provider)

    # session_id 提前生成——传给 IngestEvent 让 FE 关联日志
    session_id = uuid.uuid4().hex[:16]

    # ---- SSE 流装配 ----
    queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=200)
    done_sentinel = object()
    asyncio_loop = asyncio.get_running_loop()

    def _safe_put(item: Any) -> None:
        try:
            queue.put_nowait(item)
        except asyncio.QueueFull:
            # FE 慢消费——丢老的保 ingest 主流程
            logger.warning("ingest SSE queue full; dropping event")

    def on_ingest_event(event: IngestEvent) -> None:
        # extractor 跑在 worker thread；call_soon_threadsafe 跨线程入队
        asyncio_loop.call_soon_threadsafe(_safe_put, event)

    extractor = MinimalKGExtractor(
        client=client,
        model=extractor_model,
        on_ingest_event=on_ingest_event,
        book_session_id=session_id,
    )

    def run_in_thread_target() -> tuple[BookUploadResponse | None, Exception | None]:
        """跑 KG 抽取 + 装配 + 注册；返 (response, exc) 让外层翻译错误。"""
        try:
            kg = extractor.extract(
                chunks=chunks, book_title=book_title, language=language,
            )
        except Exception as exc:  # noqa: BLE001
            # ingest_error 事件已由 extractor 内部 emit；这里把异常带出去
            # 让外层算 setup error 还是 stream-internal error。
            return None, exc

        vector_store = SessionVectorStore(chunks=chunks, enable_vector=True)
        assembler = R0BookAssembler(
            book_text=book_text,
            chunks=chunks,
            knowledge_graph=kg,
            session_vector_store=vector_store,
        )
        # 同 sync upload：章节检测指标随 register 落进 session 元数据
        assembler.chapter_detection_stats = chapter_stats.to_dict()
        store.register(session_id, assembler)
        # hosted:把这本书记到当前用户名下(local 是 no-op)。
        record_ownership(user, session_id, book_text.title)
        resp = BookUploadResponse(
            session_id=session_id,
            book_title=book_text.title,
            language=getattr(book_text, "language", language),
            chunk_count=len(chunks),
            character_count=len(kg.characters),
            chapter_detection=chapter_stats.to_dict(),
        )
        return resp, None

    response_holder: dict[str, Any] = {"resp": None, "exc": None}

    async def run_ingest_in_thread() -> None:
        try:
            resp, exc = await asyncio.to_thread(run_in_thread_target)
            response_holder["resp"] = resp
            response_holder["exc"] = exc
        finally:
            asyncio_loop.call_soon_threadsafe(_safe_put, done_sentinel)

    task = asyncio.create_task(run_ingest_in_thread())

    async def event_generator() -> Any:
        try:
            while True:
                item = await queue.get()
                if item is done_sentinel:
                    break
                yield _format_ingest_sse(item)
            # 流末尾追加 upload_complete / upload_error 帧
            resp = response_holder.get("resp")
            exc = response_holder.get("exc")
            if resp is not None:
                payload = resp.model_dump()
                yield (
                    "event: upload_complete\n"
                    f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                )
            elif exc is not None:
                # ingest_error 已 emit；这里再补一帧带 HTTP-翻译过的错误类型
                err_type, err_msg = _classify_kg_error(exc)
                payload = {
                    "error_type": err_type,
                    "message": err_msg,
                    "timestamp": time.time(),
                }
                yield (
                    "event: upload_error\n"
                    f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                )
        finally:
            if not task.done():
                # task 自然跑完（extractor 同步、跑在 thread 里没 cancel
                # 钩子）；不 await 让响应 close 不阻塞
                pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _format_ingest_sse(event: IngestEvent) -> str:
    """把 IngestEvent 编码成一帧 SSE。

    格式：``event: <event_type>\\ndata: <json>\\n\\n``。``event_type`` 字
    段直接当 SSE event 名，与 ``/agent/ask/stream`` 用 ``LoopEvent.type``
    做事件名同口径。
    """
    payload = json.dumps(asdict(event), ensure_ascii=False)
    return f"event: {event.event_type}\ndata: {payload}\n\n"


def _classify_kg_error(exc: Exception) -> tuple[str, str]:
    """把 KG 抽取异常翻译成 (error_type, message)，给 ``upload_error`` 帧用。

    跟 sync ``_extract_kg_or_raise`` 同口径——LLMFormatError / RateLimited
    / ProviderUnavailable / ProviderError / 其它 各分类。SSE 流里走 200
    OK，错误类型由 ``upload_error`` event 内 ``error_type`` 字段携带。
    """
    if isinstance(exc, LLMFormatError):
        return "LLMFormatError", str(exc)
    if isinstance(exc, RateLimited):
        return "RateLimited", str(exc)
    if isinstance(exc, ProviderUnavailable):
        return "ProviderUnavailable", str(exc)
    if isinstance(exc, ProviderError):
        return type(exc).__name__, str(exc)
    return type(exc).__name__, f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------
# 内部工具：保持 handler 主体扁平
# ---------------------------------------------------------------------------


def _run_ingest_or_raise(
    content: bytes,
    suffix: str,
    book_title: str,
    language: str,
) -> tuple[object, list, ChapterDetectionStats]:
    """把上传 bytes 写到 tmp 文件，走 r0 ingest 管线得到 BookText + chunks。

    第三个返回值是章节检测质量指标（WP3 Phase A），upload 响应与 session
    元数据都从这里拿。

    失败翻译：
    - 文件解析失败（loader 抛 ``ValueError`` 等）→ 400
    - 文件空或空白（EmptyTextError）→ 422
    - chunk 管线异常 → 422
    """
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    try:
        try:
            book_text = load_text(tmp_path, title=book_title)
        except EmptyTextError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error_type": "EmptyBookText",
                    "message": str(exc),
                    "details": None,
                },
            ) from exc
        except (ValueError, FileNotFoundError, ImportError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error_type": "IngestLoadFailed",
                    "message": f"{type(exc).__name__}: {exc}",
                    "details": None,
                },
            ) from exc

        # 补 language：loader 默认给 "unknown"，这里按 form 参数覆盖
        if getattr(book_text, "language", "unknown") in ("unknown", ""):
            book_text.language = language

        try:
            chunks, chapter_stats = chunk_book_with_stats(book_text)
        except Exception as exc:  # noqa: BLE001 — chunker 内部异常
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error_type": "IngestChunkFailed",
                    "message": f"{type(exc).__name__}: {exc}",
                    "details": None,
                },
            ) from exc
        return book_text, chunks, chapter_stats
    finally:
        # 清理 tmp 文件；失败不影响响应
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:  # pragma: no cover
            logger.debug("failed to delete tmp file %s", tmp_path)


def _build_client_or_raise(
    *, provider: str, api_key: str, base_url: str | None = None,
):
    """构造 LLM client；SDK 未装 / 参数非法一律翻译为 HTTP 400。"""
    try:
        return build_llm_client_from_params(
            provider=provider, api_key=api_key, base_url=base_url,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "ProviderSdkMissing",
                "message": str(exc),
                "details": {"provider": provider},
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_type": "UnsupportedProvider",
                "message": str(exc),
                "details": {"provider": provider},
            },
        ) from exc


def _extract_kg_or_raise(
    extractor: MinimalKGExtractor,
    *,
    chunks,
    book_title: str,
    language: str,
):
    """调 extractor.extract；按错误分层翻译 HTTP 状态。"""
    try:
        return extractor.extract(chunks=chunks, book_title=book_title, language=language)
    except LLMFormatError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error_type": "LLMFormatError",
                "message": str(exc),
                "details": None,
            },
        ) from exc
    except ProviderUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error_type": "ProviderUnavailable",
                "message": str(exc),
                "details": None,
            },
        ) from exc
    except RateLimited as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error_type": "RateLimited",
                "message": str(exc),
                "details": None,
            },
        ) from exc
    except ProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error_type": type(exc).__name__,
                "message": str(exc),
                "details": None,
            },
        ) from exc


__all__ = ["books_router"]


# ---------------------------------------------------------------------------
# 本地书库批量导入（渐进可用：解析+分章秒级入库，跳过 KG，章脉后台补）
# ---------------------------------------------------------------------------

_IMPORT_JOBS: dict[str, dict] = {}
_IMPORT_LOCK = threading.Lock()
_IMPORT_EXECUTOR = None  # 懒建线程池


def _import_executor():
    global _IMPORT_EXECUTOR
    if _IMPORT_EXECUTOR is None:
        from concurrent.futures import ThreadPoolExecutor
        _IMPORT_EXECUTOR = ThreadPoolExecutor(max_workers=1)
    return _IMPORT_EXECUTOR


_PREWARM_WORKERS = 2  # 导入后自动建章脉的并发上限（避免打爆 API / 占满磁盘 IO）


def _run_folder_import(
    *,
    job_id: str,
    files: list[Path],
    store: BookSessionStore,
    client: Any = None,
    model: str | None = None,
) -> None:
    """后台逐个导入：load_text → chunk → 空 KG → register。跳过 KG（秒级）。

    全部入库后，若给了 client，自动后台预建章脉（限量并发，渐进交付）——
    用户打开书时可能已建好，不用干等首次分析。
    """
    imported: list[tuple[str, list]] = []  # (session_id, chunks)
    for i, path in enumerate(files):
        with _IMPORT_LOCK:
            state = _IMPORT_JOBS.get(job_id)
            if state is None:
                return
            state["current"] = path.name
        try:
            book_text = load_text(path)
            if getattr(book_text, "language", "unknown") in ("unknown", ""):
                book_text.language = "zh"
            chunks, chapter_stats = chunk_book_with_stats(book_text)
            kg = BookKnowledgeGraph(book_title=book_text.title, language=book_text.language)
            vector_store = SessionVectorStore(chunks=chunks, enable_vector=True)
            assembler = R0BookAssembler(
                book_text=book_text,
                chunks=chunks,
                knowledge_graph=kg,
                session_vector_store=vector_store,
            )
            assembler.chapter_detection_stats = chapter_stats.to_dict()
            session_id = uuid.uuid4().hex[:16]
            store.register(session_id, assembler)
            imported.append((session_id, chunks))
            result = {
                "file": path.name,
                "session_id": session_id,
                "book_title": book_text.title,
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001 — 单本失败不阻断批量
            result = {
                "file": path.name,
                "session_id": None,
                "book_title": None,
                "error": f"{type(exc).__name__}: {exc}",
            }
        with _IMPORT_LOCK:
            state = _IMPORT_JOBS.get(job_id)
            if state is None:
                return
            state["results"].append(result)
            state["done"] = i + 1
    with _IMPORT_LOCK:
        state = _IMPORT_JOBS.get(job_id)
        if state is not None:
            state["status"] = "done"
            state["current"] = None

    # 自动预建章脉（限量并发；失败静默——用户打开书时 prewarm 会再试）
    if client is not None and imported:
        from concurrent.futures import ThreadPoolExecutor
        resolved_model = model or "deepseek-v4-flash"

        def _build_one(item: tuple[str, list]) -> None:
            sid, chunks = item
            try:
                get_or_build_spine(chunks=chunks, llm_client=client, model=resolved_model, genre="fiction")
            except Exception:  # noqa: BLE001 — 预建失败不影响导入结果
                pass

        with ThreadPoolExecutor(max_workers=_PREWARM_WORKERS) as pool:
            list(pool.map(_build_one, imported))


@books_router.post("/books/import-folder", response_model=ImportFolderResponse)
def import_folder(
    request: ImportFolderRequest,
    store: BookSessionStore = Depends(get_book_session_store),
) -> ImportFolderResponse:
    """批量导入本地文件夹（仅 local 模式；hosted 不允许读服务器任意路径）。

    只解析+分章+注册（空 KG），秒级入库；章脉由 prewarm 后台渐进补。
    """
    if is_hosted():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error_type": "HostedOnly", "message": "批量导入本地文件夹仅本地模式可用"},
        )
    folder = Path(request.folder_path)
    if not folder.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_type": "FolderNotFound", "message": f"文件夹不存在：{request.folder_path}"},
        )
    files = sorted(
        p for p in folder.rglob("*")
        if p.is_file() and p.suffix.lower() in _SUPPORTED_EXTENSIONS
    )
    if not files:
        return ImportFolderResponse(job_id="", total=0, skipped=[])

    job_id = uuid.uuid4().hex[:16]
    with _IMPORT_LOCK:
        _IMPORT_JOBS[job_id] = {
            "status": "running",
            "done": 0,
            "total": len(files),
            "current": None,
            "results": [],
            "error": None,
        }
    # 构造 client 用于导入后自动预建章脉；client 失败不阻断导入（跳过预建）
    client = None
    try:
        client = build_llm_client_from_params(
            provider=request.provider,
            api_key=request.api_key,
            base_url=request.base_url,
        )
    except Exception:  # noqa: BLE001 — 导入仍可用，只是不自动预建
        client = None
    _import_executor().submit(
        _run_folder_import, job_id=job_id, files=files, store=store,
        client=client, model=request.model,
    )
    return ImportFolderResponse(job_id=job_id, total=len(files), skipped=[])


@books_router.get("/books/import-folder/status", response_model=ImportFolderStatusResponse)
def import_folder_status(job_id: str) -> ImportFolderStatusResponse:
    """轮询批量导入进度。"""
    with _IMPORT_LOCK:
        state = _IMPORT_JOBS.get(job_id)
        if state is None:
            return ImportFolderStatusResponse(
                status="idle", done=0, total=0, current=None, results=[], error=None
            )
        return ImportFolderStatusResponse(
            status=state["status"],
            done=state["done"],
            total=state["total"],
            current=state["current"],
            results=list(state["results"]),
            error=state.get("error"),
        )
