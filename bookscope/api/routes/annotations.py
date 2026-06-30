"""阅读标注路由(WP-reading-workspace Phase C · 只 hosted 挂)。

托管版把用户标注落进账号 DB(``annotations`` 表,跟 ``documents`` 平级)。
**只有 hosted 模式 ``create_app`` 才挂这个 router**;local 根本不 import 本模块,
标注全走前端 localStorage(``LocalAnnotationStore``),一个请求都不发 → local 逐字节
零变化(对齐 1.6.2 最硬验收标准)。

两条命门:

1. **数据隔离焊在 SQL 的 WHERE 层**——取 / 改 / 删一律带 ``owner_user_id``,不是本人的
   标注当不存在(404),绝不先取别人的再判断(照 ``accounts.py`` 文档归属那套)。
2. **key 绝不掺**——这条链是纯 CRUD,根本不调 LLM、不传 key;令牌只装 user_id
   (1.6.2 ``installAuthFetch``)。红线在这里是免费守住的。

加 / 列一本书的标注还要再过一道"这本书是不是你的"(``user_owns_session``),免得给
不属于自己的书加标注。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from bookscope.api.annotation_schemas import (
    AnchorModel,
    AnnotationCreateRequest,
    AnnotationListResponse,
    AnnotationResponse,
    AnnotationUpdateRequest,
)
from bookscope.api.deployment import (
    get_accounts_store,
    require_user,
    user_owns_session,
)
from bookscope.store.accounts import Annotation, User

annotations_router = APIRouter(tags=["annotations"])


def _to_response(anno: Annotation) -> AnnotationResponse:
    """DB 行 → 对外视图。**不外泄 owner_user_id**(归属是内部隔离字段)。"""
    return AnnotationResponse(
        id=anno.id,
        book_session_id=anno.book_session_id,
        kind=anno.kind,  # type: ignore[arg-type]
        anchor=AnchorModel.model_validate(anno.anchor),
        note_text=anno.note_text,
        color=anno.color,  # type: ignore[arg-type]
        created_at=anno.created_at,
        updated_at=anno.updated_at,
    )


def _ensure_owns_book(user: User, book_session_id: str) -> None:
    """这本书不是你的就 404——不能给别人的书加 / 列标注。"""
    if not user_owns_session(user, book_session_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="书不存在"
        )


@annotations_router.get("/annotations", response_model=AnnotationListResponse)
async def list_annotations(
    book_session_id: str = Query(..., min_length=1, description="列哪本书的标注。"),
    user: User = Depends(require_user),
) -> AnnotationListResponse:
    """列这本书我的标注(过 owner 隔离 + 书归属校验)。"""
    _ensure_owns_book(user, book_session_id)
    rows = get_accounts_store().list_annotations_by_user(
        user.id, book_session_id=book_session_id
    )
    return AnnotationListResponse(annotations=[_to_response(a) for a in rows])


@annotations_router.get("/annotations/mine", response_model=AnnotationListResponse)
async def list_my_annotations(
    user: User = Depends(require_user),
) -> AnnotationListResponse:
    """跨书汇总我的所有标注(我的案头用),按时间倒序。只列自己的。"""
    rows = get_accounts_store().list_annotations_by_user(user.id)
    return AnnotationListResponse(annotations=[_to_response(a) for a in rows])


@annotations_router.post(
    "/annotations",
    response_model=AnnotationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_annotation(
    req: AnnotationCreateRequest,
    user: User = Depends(require_user),
) -> AnnotationResponse:
    """加一条标注。先校验这本书是你的,再落库(归属钉死在 owner_user_id)。"""
    _ensure_owns_book(user, req.book_session_id)
    anno = get_accounts_store().add_annotation(
        owner_user_id=user.id,
        book_session_id=req.book_session_id,
        kind=req.kind,
        anchor=req.anchor.model_dump(),
        note_text=req.note_text,
        color=req.color,
    )
    return _to_response(anno)


@annotations_router.patch(
    "/annotations/{annotation_id}", response_model=AnnotationResponse
)
async def update_annotation(
    annotation_id: str,
    req: AnnotationUpdateRequest,
    user: User = Depends(require_user),
) -> AnnotationResponse:
    """改一条标注(笔记 / 颜色 / 锚点 / 类型)。不是本人的当不存在,返 404。"""
    fields_set = req.model_fields_set
    updated = get_accounts_store().update_annotation(
        owner_user_id=user.id,
        annotation_id=annotation_id,
        kind=req.kind,
        anchor=req.anchor.model_dump() if req.anchor is not None else None,
        note_text=req.note_text,
        color=req.color,
        # 显式传了 null = 清空;没传 = 保持不变(靠 model_fields_set 区分)。
        clear_note_text="note_text" in fields_set and req.note_text is None,
        clear_color="color" in fields_set and req.color is None,
    )
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="标注不存在"
        )
    return _to_response(updated)


@annotations_router.delete(
    "/annotations/{annotation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_annotation(
    annotation_id: str,
    user: User = Depends(require_user),
):
    """删一条标注。不是本人的当不存在,返 404(不暴露"存在但不是你的")。"""
    ok = get_accounts_store().delete_annotation(
        owner_user_id=user.id, annotation_id=annotation_id
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="标注不存在"
        )
    return None


__all__ = ["annotations_router"]
