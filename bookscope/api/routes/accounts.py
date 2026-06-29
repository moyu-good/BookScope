"""托管版账号路由(1.6.2 Phase 1b-ii · 只 hosted 挂)。

注册 / 登录 / whoami。**只有 hosted 模式 create_app 才挂这个 router**;local
根本不 import 本模块,所以这里放心在顶层 import auth / accounts,不破坏本地版
"启动不加载 argon2 / itsdangerous"那条线。

key 不经过这里:登录只换鉴权令牌,API key 永远留浏览器、按请求传(ADR-011)。
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends, HTTPException, status

from bookscope.api.auth import (
    issue_email_verify_token,
    issue_reset_token,
    issue_token,
    read_email_verify_token,
    verify_reset_token,
)
from bookscope.api.dependencies import get_book_session_store
from bookscope.api.deployment import (
    get_accounts_store,
    get_current_user,
    require_user,
)
from bookscope.api.mailer import send_email
from bookscope.api.schemas import (
    AuthResponse,
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    UserPublic,
    VerifyEmailRequest,
)
from bookscope.store.accounts import DuplicateEmailError, User

logger = logging.getLogger(__name__)

accounts_router = APIRouter(tags=["auth"])


def _to_public(user: User) -> UserPublic:
    return UserPublic(
        id=user.id,
        email=user.email,
        phone=user.phone,
        email_verified=user.email_verified,
        created_at=user.created_at,
    )


def _send_verify_email(user: User) -> None:
    """给账号发邮箱验证邮件(best-effort,失败不阻断注册)。"""
    token = issue_email_verify_token(user.id)
    public_url = os.environ.get("BOOKSCOPE_PUBLIC_URL", "").strip().rstrip("/")
    link = f"{public_url}/?verify_email={token}" if public_url else f"verify_email={token}"
    try:
        send_email(
            to=user.email,
            subject="书鉴 · 验证邮箱",
            body=(
                "欢迎用书鉴。点这个链接验证邮箱(7 天内有效):\n"
                f"{link}\n\n"
                "没注册过书鉴就忽略这封邮件。"
            ),
        )
    except Exception:  # noqa: BLE001 — 发信失败不阻断注册
        logger.warning("发送验证邮件失败 to=%s", user.email)


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
    _send_verify_email(user)
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


@accounts_router.post("/auth/forgot-password")
async def forgot_password(req: ForgotPasswordRequest) -> dict:
    """发找回密码邮件。无论邮箱在不在都返 200(防邮箱枚举);在才真发。

    发信失败(SMTP 挂)也吞掉、照返 200——不向客户端泄露这个邮箱到底在不在。
    """
    user = get_accounts_store().get_user_by_email(req.email)
    if user is not None:
        token = issue_reset_token(user.id)
        public_url = os.environ.get("BOOKSCOPE_PUBLIC_URL", "").strip().rstrip("/")
        link = f"{public_url}/?reset_token={token}" if public_url else f"reset_token={token}"
        try:
            send_email(
                to=user.email,
                subject="书鉴 · 重置密码",
                body=(
                    "你(或冒用你邮箱的人)申请重置书鉴账号密码。\n\n"
                    f"打开这个链接重置(1 小时内有效):\n{link}\n\n"
                    "不是你本人操作,忽略这封邮件即可,密码不会变。"
                ),
            )
        except Exception:  # noqa: BLE001 — 发信失败不向客户端泄露邮箱存在性
            logger.warning("发送找回密码邮件失败 to=%s", user.email)
    return {"ok": True}


@accounts_router.post("/auth/reset-password", response_model=AuthResponse)
async def reset_password(req: ResetPasswordRequest) -> AuthResponse:
    """凭找回密码令牌设新密码。令牌坏 / 过期 / 人已注销 → 400;成功直接签发新会话令牌。"""
    user_id = verify_reset_token(req.token)
    acc = get_accounts_store()
    if user_id is None or not acc.set_password(user_id, req.new_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="链接无效或已过期,重新申请一次",
        )
    user = acc.get_user_by_id(user_id)
    if user is None:  # 理论到不了(set_password 刚成功),收口类型
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="链接无效或已过期,重新申请一次",
        )
    return AuthResponse(token=issue_token(user.id), user=_to_public(user))


@accounts_router.post("/auth/verify-email", response_model=UserPublic)
async def verify_email(req: VerifyEmailRequest) -> UserPublic:
    """凭验证令牌把邮箱标为已验证。令牌坏 / 过期 / 人已注销 → 400。"""
    user_id = read_email_verify_token(req.token)
    acc = get_accounts_store()
    if user_id is None or not acc.mark_email_verified(user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="验证链接无效或已过期,重新申请验证",
        )
    user = acc.get_user_by_id(user_id)
    if user is None:  # 理论到不了
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="验证链接无效或已过期,重新申请验证",
        )
    return _to_public(user)


__all__ = ["accounts_router"]
