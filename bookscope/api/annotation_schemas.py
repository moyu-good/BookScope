"""阅读标注端点的请求 / 响应 Pydantic schema(WP-reading-workspace Phase C)。

单独成文件、**不进 ``schemas.py``**——那个文件另有并行改动,避免撞。字段形状对齐
前端 ``web/src/annotationStore.ts`` 的 ``Annotation`` / ``Anchor``:四类标注用
``kind`` 区分,锚点是带冗余、可二次定位的值对象。

这条链(读书 / 标注)是纯 CRUD、**根本不碰 LLM、不传 key**(设计稿红线,免费守住):
这里没有任何 ``api_key`` / ``provider`` 字段。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

AnnotationKind = Literal["bookmark", "highlight", "note", "emphasis"]
AnnotationColor = Literal["seal", "ink", "neutral"]


class AnchorModel(BaseModel):
    """锚点:钉在原文哪里。多重冗余、可降级,对齐前端 ``Anchor``。

    冗余度从精到粗:``char_start``(快路)→ ``quote``(文字主键)→
    ``prefix`` / ``suffix``(上下文窗口,多命中时消歧)→ ``para_index`` /
    ``chapter``(粗定位,章最稳)。整条 anchor 在 DB 里序列化成一列 JSON。
    """

    chapter: int = Field(..., description="章号,Reader 按章取正文,最稳的锚。")
    para_index: int = Field(..., description="章内第几段(text 按 \\n 切段后的序号)。")
    quote: str = Field(..., description="选中的那截原文,文字级定位的主键。")
    prefix: str = Field(
        default="", description="quote 前面约 24 字窗口,跨章 / 跨段复现时消歧。"
    )
    suffix: str = Field(default="", description="quote 后面约 24 字窗口,同上。")
    char_start: int | None = Field(
        default=None, description="段内字符偏移,定位快捷线索;书签可粗到段 / 章级时为 null。"
    )


class AnnotationCreateRequest(BaseModel):
    """POST /api/annotations 请求体——加一条标注(只 hosted)。"""

    book_session_id: str = Field(
        ..., min_length=1, description="属于哪本书(沿用 session_id)。"
    )
    kind: AnnotationKind = Field(..., description="四类:bookmark / highlight / note / emphasis。")
    anchor: AnchorModel = Field(..., description="钉在原文哪里,载重字段。")
    note_text: str | None = Field(
        default=None, max_length=20000, description="用户写的笔记正文;note 类必有,其余可空。"
    )
    color: AnnotationColor | None = Field(
        default=None, description="高亮 / 重点的颜色档;书签 / 笔记可空。"
    )


class AnnotationUpdateRequest(BaseModel):
    """PATCH /api/annotations/{id} 请求体——改一条标注(只 hosted)。

    全字段可选:传了才改,没传保持不变。``note_text`` / ``color`` 显式给 ``null``
    即把它置空(改回无笔记 / 无颜色),靠 ``model_fields_set`` 区分"没传"和"传了 null"。
    """

    kind: AnnotationKind | None = Field(default=None, description="改类型。")
    anchor: AnchorModel | None = Field(default=None, description="改锚点。")
    note_text: str | None = Field(
        default=None, max_length=20000, description="改笔记正文;显式 null = 清空。"
    )
    color: AnnotationColor | None = Field(default=None, description="改颜色档;显式 null = 清空。")


class AnnotationResponse(BaseModel):
    """一条标注的对外视图。**不含 owner_user_id**(归属是内部隔离字段,不外泄)。"""

    id: str
    book_session_id: str
    kind: AnnotationKind
    anchor: AnchorModel
    note_text: str | None = None
    color: AnnotationColor | None = None
    created_at: str
    updated_at: str


class AnnotationListResponse(BaseModel):
    """列标注的响应:一组标注。"""

    annotations: list[AnnotationResponse] = Field(default_factory=list)


__all__ = [
    "AnchorModel",
    "AnnotationColor",
    "AnnotationCreateRequest",
    "AnnotationKind",
    "AnnotationListResponse",
    "AnnotationResponse",
    "AnnotationUpdateRequest",
]
