"""部署模式开关 + 账号层旁路依赖（1.6.2 Phase 0 地基）。

BookScope 跑两种形态、共用一套代码（ADR-011）：

- ``local``（默认，本地克隆版）：无账号、无 DB、无邮件 / 短信。
  ``session_id`` 照旧匿名，账号层完全旁路，行为跟今天逐字节一致。
- ``hosted``（公网托管版）：账号 / 归属 / 鉴权激活（Phase 1 起接真东西）。

形态靠一个 env 开关分，不靠分叉代码——跟仓里已有的
``BOOKSCOPE_STATIC_DIR`` / ``BOOKSCOPE_CORS_ORIGINS`` /
``BOOKSCOPE_RATELIMIT_DISABLED`` / ``BOOKSCOPE_AGENT_PROTOCOL`` 一个套路：
同代码、读 env、按值分部署。

Phase 0 只放这层地基：开关 + 一个永远旁路的 ``get_current_user`` 桩。
DB / 账号表 / 鉴权路由 / argon2 / JWT 全是 Phase 1+，这里一律不碰。
"""

from __future__ import annotations

import os
import threading
from typing import TYPE_CHECKING, Literal

from fastapi import HTTPException, Request, status

if TYPE_CHECKING:
    from bookscope.store.accounts import AccountsStore, User

DeploymentMode = Literal["local", "hosted"]

_DEFAULT_MODE: DeploymentMode = "local"


def deployment_mode() -> DeploymentMode:
    """返回当前部署模式：``local``（默认）或 ``hosted``。

    读 ``BOOKSCOPE_DEPLOYMENT_MODE``，大小写 / 前后空格都容忍。除了显式
    写 ``hosted`` 的，其它一切——不设、空串、拼错、乱填——都落回
    ``local``。理由：本地版是默认形态，开关默认关；只有运营方主动把它
    拨到 ``hosted`` 才激活账号层，避免误配把本地用户拽进托管路径。
    """
    raw = os.environ.get("BOOKSCOPE_DEPLOYMENT_MODE", "").strip().lower()
    if raw == "hosted":
        return "hosted"
    return _DEFAULT_MODE


def is_hosted() -> bool:
    """是否托管模式。``local`` / 未设时为 ``False``。"""
    return deployment_mode() == "hosted"


# ---- 托管版账号单例 + 鉴权(只 hosted 用,全程懒加载) ----
#
# 这些函数只在 hosted 路径被调到。模块顶层绝不 import accounts / auth,免得
# local 启动时把 argon2 / itsdangerous 拽进来——ADR-011 定本地版不加载账号层,
# 且纯 ``pip install -e .``(没装 hosted extra)也得跑得起来。

_accounts_store: AccountsStore | None = None
_accounts_lock = threading.Lock()


def get_accounts_store() -> AccountsStore:
    """进程级 :class:`AccountsStore` 单例(只 hosted 用)。

    DB 路径来自 env ``BOOKSCOPE_ACCOUNTS_DB``,默认 ``data/accounts.db``。
    懒建:第一次调到才连库,local 模式永不触发。
    """
    global _accounts_store
    if _accounts_store is None:
        with _accounts_lock:
            if _accounts_store is None:
                from bookscope.store.accounts import AccountsStore

                db_path = os.environ.get("BOOKSCOPE_ACCOUNTS_DB", "").strip()
                _accounts_store = AccountsStore(db_path or "data/accounts.db")
    return _accounts_store


def _reset_accounts_store() -> None:
    """仅供测试:清掉单例,好让下个用例换一个干净 DB。"""
    global _accounts_store
    if _accounts_store is not None:
        try:
            _accounts_store.close()
        except Exception:
            pass
        _accounts_store = None


def resolve_user_from_token(authorization: str | None) -> User | None:
    """从 ``Authorization`` 头解析当前用户:验签 / 验时限 / 查库,任一不过返 ``None``。

    抽出来跟 FastAPI 解耦,好单测(直接喂字符串,不用造 Request)。local 模式
    一律 ``None``——账号层旁路,即便带合法令牌也当匿名。
    """
    if not is_hosted():
        return None
    from bookscope.api.auth import bearer_token_from_header, verify_token

    token = bearer_token_from_header(authorization)
    if not token:
        return None
    user_id = verify_token(token)
    if not user_id:
        return None
    return get_accounts_store().get_user_by_id(user_id)


def get_current_user(request: Request) -> User | None:
    """当前用户依赖(FastAPI ``Depends``)。

    ``local``:账号层旁路,永远 ``None``,所有现有端点行为逐字节不变。

    ``hosted``:校 ``Authorization`` 里的 Bearer 令牌 → 查 users 表 → 返当前用户;
    令牌缺失 / 坏 / 过期返 ``None``。是否据此抛 401 由具体路由按需决定,不在这里
    一刀切(有的端点匿名也能用)。
    """
    return resolve_user_from_token(request.headers.get("authorization"))


# ---- 文档归属:热路径端点的统一守卫(Phase 1c) ----
#
# 全用 is_hosted() 短路:local 模式这几个 helper 要么旁路、要么恒"放行 / 不过滤",
# 现有 books / sessions 端点行为逐字节不变。只有 hosted 才真按 owner 隔离。


def require_user(request: Request) -> User | None:
    """FastAPI 依赖:解析当前用户。hosted 没登录 → 401;local → 永远 None、不拦。

    给热路径端点(上传 / 书库列表 / 单本读写)统一挂。local 模式它就是个返 None
    的旁路,现有行为一字不变。
    """
    current = resolve_user_from_token(request.headers.get("authorization"))
    if is_hosted() and current is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="需要登录"
        )
    return current


def record_ownership(user: User | None, doc_id: str, title: str) -> None:
    """记一份文档归属。hosted + 已登录才记;local / 没登录 = no-op。"""
    if is_hosted() and user is not None:
        get_accounts_store().add_document(
            owner_user_id=user.id, doc_id=doc_id, title=title
        )


def forget_ownership(user: User | None, doc_id: str) -> None:
    """删一份文档归属(删 session 时连带,对应 ADR-011 删除权)。
    hosted + 已登录才删;local / 没登录 = no-op。"""
    if is_hosted() and user is not None:
        get_accounts_store().delete_document(owner_user_id=user.id, doc_id=doc_id)


def owned_session_ids(user: User | None) -> set[str] | None:
    """这个用户拥有的 session_id 集。local 返 ``None``(表示"别过滤、全都给")。"""
    if not is_hosted() or user is None:
        return None
    return {doc.id for doc in get_accounts_store().list_documents(user.id)}


def user_owns_session(user: User | None, session_id: str) -> bool:
    """hosted 下这个用户是否拥有该 session;local 恒 ``True``(本地版不隔离)。"""
    if not is_hosted():
        return True
    if user is None:
        return False
    return get_accounts_store().owns(owner_user_id=user.id, doc_id=session_id)


__all__ = [
    "DeploymentMode",
    "deployment_mode",
    "get_accounts_store",
    "get_current_user",
    "forget_ownership",
    "is_hosted",
    "owned_session_ids",
    "record_ownership",
    "require_user",
    "resolve_user_from_token",
    "user_owns_session",
]
