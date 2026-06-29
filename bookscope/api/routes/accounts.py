"""托管版账号路由(1.6.2 Phase 1b-ii · 只 hosted 挂)。

注册 / 登录 / whoami。**只有 hosted 模式 create_app 才挂这个 router**;local
根本不 import 本模块,所以这里放心在顶层 import auth / accounts,不破坏本地版
"启动不加载 argon2 / itsdangerous"那条线。

key 不经过这里:登录只换鉴权令牌,API key 永远留浏览器、按请求传(ADR-011)。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from bookscope.api.auth import issue_token
from bookscope.api.dependencies import get_book_session_store
from bookscope.api.deployment import (
    get_accounts_store,
    get_current_user,
    require_user,
)
from bookscope.api.schemas import (
    AuthResponse,
    LoginRequest,
    RegisterRequest,
    UserPublic,
)
from bookscope.store.accounts import DuplicateEmailError, User

accounts_router = APIRouter(tags=["auth"])


def _to_public(user: User) -> UserPublic:
    return UserPublic(
        id=user.id,
        email=user.email,
        phone=user.phone,
        created_at=user.created_at,
    )


@accounts_router.post(
    "/auth/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(req: RegisterRequest) -> AuthResponse:
    """注册账号 → 直接签发令牌(注册即登录)。邮箱占用返 409。"""
    store = get_accounts_store()
    try:
        user = store.create_user(
            email=req.email, password=req.password, phone=req.phone
        )
    except DuplicateEmailError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="邮箱已注册"
        ) from exc
    return AuthResponse(token=issue_token(user.id), user=_to_public(user))


@accounts_router.post("/auth/login", response_model=AuthResponse)
async def login(req: LoginRequest) -> AuthResponse:
    """邮箱 + 密码登录 → 签发令牌。不对返 401(不区分查无此人 / 密码错)。"""
    user = get_accounts_store().verify_credentials(
        email=req.email, password=req.password
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="邮箱或密码不对"
        )
    return AuthResponse(token=issue_token(user.id), user=_to_public(user))


@accounts_router.get("/auth/me", response_model=UserPublic)
async def me(current: User | None = Depends(get_current_user)) -> UserPublic:
    """带令牌问"我是谁"。没登录 / 令牌坏返 401。FE 用它判登录态。"""
    if current is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录"
        )
    return _to_public(current)


@accounts_router.delete(
    "/auth/me",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_account(
    store=Depends(get_book_session_store),
    current=Depends(require_user),
):
    """彻底注销账号(ADR-011 删除权):删账号 + 名下所有书(连索引 / 缓存)+ 归属记录。

    先删这个用户名下每份文档对应的 session(store.delete 连带清 storage + 各级缓存),
    再 delete_user(ON DELETE CASCADE 连带删 documents 归属行)。不可逆。
    """
    acc = get_accounts_store()
    for doc in acc.list_documents(current.id):
        store.delete(doc.id)
    acc.delete_user(current.id)
    return None


__all__ = ["accounts_router"]
