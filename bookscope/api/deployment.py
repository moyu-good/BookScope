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

from fastapi import Request

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


__all__ = [
    "DeploymentMode",
    "deployment_mode",
    "get_accounts_store",
    "get_current_user",
    "is_hosted",
    "resolve_user_from_token",
]
