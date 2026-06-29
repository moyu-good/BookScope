"""sessions 路由 —— 暴露 session 列表 / 查询 / 删除给前端。

三个端点（前缀由 :mod:`bookscope.api.app` 统一加 ``/api``）：

  - ``GET    /sessions``               列出全部 session 元数据
  - ``GET    /sessions/{session_id}``  获取单个 session 元数据
  - ``DELETE /sessions/{session_id}``  删除 session

设计要点：

  - **永远不暴露内部资产**。响应只含 :class:`SessionMetadata` 五个字段
    （session_id / book_title / language / created_at / last_accessed_at），
    chunks 数 / vector_index 路径 / 角色数等留给 ``/books/upload`` 与
    ``/agent/ask`` 自己的响应体。
  - 错误统一翻译为 envelope ``{"error_type", "message", "details"}``，与
    books / agent 路由保持一致。
  - 元数据来自 :meth:`BookSessionStore.get_metadata`，本质上是从
    :class:`JSONFileSessionStorage` 的 ``metadata.json`` 读出，避免在路由层
    硬编码文件路径。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from bookscope.agent.backends.r0_assembler import R0BookAssembler
from bookscope.api.book_sessions import BookSessionNotFound, BookSessionStore
from bookscope.api.dependencies import get_book_session_store
from bookscope.api.deployment import (
    forget_ownership,
    owned_session_ids,
    require_user,
    user_owns_session,
)
from bookscope.api.schemas import (
    BookTocResponse,
    ChapterTextResponse,
    SessionListResponse,
    SessionMetadata,
    TocChapter,
)
from bookscope.api.session_storage import SessionStorageCorrupted

logger = logging.getLogger(__name__)

sessions_router = APIRouter(tags=["sessions"])


@sessions_router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    store: BookSessionStore = Depends(get_book_session_store),
    user=Depends(require_user),
) -> SessionListResponse:
    """列出 session 的元数据。

    空列表也是合法返回（200 OK + ``{"sessions": []}``）。
    单个 session 的 metadata 读失败（比如磁盘文件损坏）会被静默跳过——
    一条坏数据不应该让整个列表挂掉。

    hosted 模式只列当前用户自己的书（隔离）；local 模式列全部、行为不变。
    """
    owned = owned_session_ids(user)  # hosted:本人 session 集;local:None=不过滤
    metadatas: list[SessionMetadata] = []
    for session_id in store.list_sessions():
        if owned is not None and session_id not in owned:
            continue
        try:
            meta_dict = store.get_metadata(session_id)
        except (BookSessionNotFound, SessionStorageCorrupted) as exc:
            # 列表场景下的 best-effort：跳过坏的 session 并记日志，
            # 不让一条脏数据把整个列表请求拉崩。
            logger.warning(
                "skip session %s in list response: %s", session_id, exc,
            )
            continue
        metadatas.append(_dict_to_metadata(meta_dict))
    return SessionListResponse(sessions=metadatas)


@sessions_router.get(
    "/sessions/{session_id}",
    response_model=SessionMetadata,
)
async def get_session(
    session_id: str,
    store: BookSessionStore = Depends(get_book_session_store),
    user=Depends(require_user),
) -> SessionMetadata:
    """获取单个 session 的元数据。

    session 不存在 → 404 + envelope。hosted 模式下不是你的也 404（当不存在,
    不泄露存在性）。
    """
    if not store.has(session_id):
        _raise_not_found(session_id)
    if not user_owns_session(user, session_id):
        _raise_not_found(session_id)

    try:
        meta_dict = store.get_metadata(session_id)
    except BookSessionNotFound:
        _raise_not_found(session_id)
    except SessionStorageCorrupted as exc:
        # 文件损坏算服务端异常——存在但读不出来；不要假装 404 误导前端。
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error_type": "SessionStorageCorrupted",
                "message": str(exc),
                "details": {"session_id": session_id},
            },
        ) from exc

    return _dict_to_metadata(meta_dict)


@sessions_router.get(
    "/sessions/{session_id}/toc",
    response_model=BookTocResponse,
)
async def get_book_toc(
    session_id: str,
    store: BookSessionStore = Depends(get_book_session_store),
    user=Depends(require_user),
) -> BookTocResponse:
    """精读阅读器的目录：章号 + 标题 + 字数，不带正文（目录要小、要秒回）。

    纯数据、不调 LLM。章节由已修根的 ``detect_chapters`` 现场解析
    （脏书边界见 WP-robust-chapter-detection）；章号是标准化序号、不保证
    等于真回数。空书 → ``total_chapters=0`` + 空列表（不是错误）。
    hosted 模式下不是你的书 → 404。
    """
    if not user_owns_session(user, session_id):
        _raise_not_found(session_id)
    assembler = _resolve_assembler(store, session_id)
    records = assembler._compute_chapter_records()  # noqa: SLF001 — 同 agent 路由既有取数惯例
    title = str(getattr(assembler._book_text, "title", ""))  # noqa: SLF001
    chapters = [
        TocChapter(chapter=r.chapter, title=r.title, word_count=r.word_count)
        for r in records
    ]
    return BookTocResponse(
        book_title=title,
        total_chapters=len(chapters),
        chapters=chapters,
    )


@sessions_router.get(
    "/sessions/{session_id}/chapters/{chapter}",
    response_model=ChapterTextResponse,
)
async def get_book_chapter(
    session_id: str,
    chapter: int,
    store: BookSessionStore = Depends(get_book_session_store),
    user=Depends(require_user),
) -> ChapterTextResponse:
    """单章正文，阅读器读到哪取哪。纯数据、不调 LLM。

    章号不存在 / 越界 → 404（ChapterNotFound），FE 兜底"这章取不到"。
    hosted 模式下不是你的书 → 404。
    """
    if not user_owns_session(user, session_id):
        _raise_not_found(session_id)
    assembler = _resolve_assembler(store, session_id)
    records = assembler._compute_chapter_records()  # noqa: SLF001
    for r in records:
        if r.chapter == chapter:
            return ChapterTextResponse(
                chapter=r.chapter,
                title=r.title,
                text=r.full_text,
                word_count=r.word_count,
            )
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "error_type": "ChapterNotFound",
            "message": (
                f"chapter {chapter} not found in book session {session_id!r}."
            ),
            "details": {"session_id": session_id, "chapter": chapter},
        },
    )


@sessions_router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_session(
    session_id: str,
    store: BookSessionStore = Depends(get_book_session_store),
    user=Depends(require_user),
):
    """删除 session（内存 + storage 两处都删）。

    成功 → 204 No Content。
    session 不存在 → 404 + envelope（与 GET 行为对齐，不静默成功）。
    hosted 模式下不是你的 → 404（删不动别人的）；删自己的会连带删归属记录。
    """
    if not store.has(session_id):
        _raise_not_found(session_id)
    if not user_owns_session(user, session_id):
        _raise_not_found(session_id)
    store.delete(session_id)
    # hosted:连带删归属记录(彻底删除权);local no-op。
    forget_ownership(user, session_id)
    return None


@sessions_router.post("/cache/clear")
async def clear_analysis_cache() -> dict:
    """清空分析缓存（LLM 响应 / 章脉 / 文脉 / 知识图谱）——结果像旧的、或重抓后想强制重算时用。

    不删 session 本身（书还在、不用重新上传），只清派生分析的缓存;下次跑分析重新现算
    （会重新花 token）。设置面板「清缓存」按钮调它。
    """
    # 局部 import：清缓存是低频维护操作,没必要在模块顶层拉一堆 _internal 缓存模块。
    from bookscope.agent._internal.chapter_spine_cache import clear_spine_cache
    from bookscope.agent._internal.doc_spine_cache import clear_doc_spine_cache
    from bookscope.agent._internal.kg_book_cache import clear_book_kg_cache
    from bookscope.agent._internal.kg_cache import clear_kg_cache
    from bookscope.agent._internal.llm_cache import clear_llm_cache

    clear_llm_cache()
    clear_doc_spine_cache()
    clear_spine_cache()
    clear_kg_cache()
    clear_book_kg_cache()
    return {"cleared": True, "message": "分析缓存已清空,下次分析重新现算。"}


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


def _resolve_assembler(
    store: BookSessionStore, session_id: str
) -> R0BookAssembler:
    """从 store 取 assembler（精读阅读器取章节正文用）；找不到翻译成 404。"""
    try:
        return store.get(session_id)
    except BookSessionNotFound:
        _raise_not_found(session_id)
        raise  # _raise_not_found 必抛；这行只为类型收敛（不会执行到）


def _raise_not_found(session_id: str) -> None:
    """统一的 404 翻译。"""
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "error_type": "BookSessionNotFound",
            "message": f"book session {session_id!r} not found.",
            "details": {"session_id": session_id},
        },
    )


def _dict_to_metadata(data: dict[str, str]) -> SessionMetadata:
    """把 storage 返回的原始 dict 收敛成 :class:`SessionMetadata`。

    缺字段时填默认值——磁盘上历史遗留的 metadata.json 可能缺
    ``language`` 或时间戳，本函数兜底而不是 500。
    """
    return SessionMetadata(
        session_id=str(data.get("session_id", "")),
        book_title=str(data.get("book_title", "")),
        language=str(data.get("language", "unknown")),
        genre=str(data.get("genre", "")),
        created_at=str(data.get("created_at", "")),
        last_accessed_at=str(data.get("last_accessed_at", "")),
    )


__all__ = ["sessions_router"]
