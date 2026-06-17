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

from bookscope.api.book_sessions import BookSessionNotFound, BookSessionStore
from bookscope.api.dependencies import get_book_session_store
from bookscope.api.schemas import SessionListResponse, SessionMetadata
from bookscope.api.session_storage import SessionStorageCorrupted

logger = logging.getLogger(__name__)

sessions_router = APIRouter(tags=["sessions"])


@sessions_router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    store: BookSessionStore = Depends(get_book_session_store),
) -> SessionListResponse:
    """列出全部 session 的元数据。

    空列表也是合法返回（200 OK + ``{"sessions": []}``）。
    单个 session 的 metadata 读失败（比如磁盘文件损坏）会被静默跳过——
    一条坏数据不应该让整个列表挂掉。
    """
    metadatas: list[SessionMetadata] = []
    for session_id in store.list_sessions():
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
) -> SessionMetadata:
    """获取单个 session 的元数据。

    session 不存在 → 404 + envelope。
    """
    if not store.has(session_id):
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


@sessions_router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_session(
    session_id: str,
    store: BookSessionStore = Depends(get_book_session_store),
) -> None:
    """删除 session（内存 + storage 两处都删）。

    成功 → 204 No Content。
    session 不存在 → 404 + envelope（与 GET 行为对齐，不静默成功）。
    """
    if not store.has(session_id):
        _raise_not_found(session_id)
    store.delete(session_id)
    return None


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


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
        created_at=str(data.get("created_at", "")),
        last_accessed_at=str(data.get("last_accessed_at", "")),
    )


__all__ = ["sessions_router"]
