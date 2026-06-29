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
from typing import Literal

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


def get_current_user() -> None:
    """当前用户依赖（FastAPI ``Depends``）——Phase 0 永远返回 ``None``。

    ``local`` 模式没有"用户"这个概念，账号层旁路，永远 ``None``，所有现有
    端点行为不变。

    ``hosted`` 模式 Phase 0 也先返 ``None``：账号 / 鉴权（校 JWT 或 session
    cookie、查 ``users`` 表、失败 401）是 Phase 1 才接的活。这里留个桩，把
    "现有端点该在哪拿当前用户"这个接缝先焊好，Phase 1 只改这个函数体、不
    动调用它的路由。

    返回值类型现在是 ``None``；Phase 1 接真鉴权后会变成 ``User | None``
    （local 仍 None，hosted 返当前用户或抛 401）。
    """
    # TODO(1.6.2 Phase 1): hosted 模式在此校 JWT / session cookie，查 users
    # 表，失败抛 401；local 模式保持返 None。当前两种模式都旁路。
    return None


__all__ = [
    "DeploymentMode",
    "deployment_mode",
    "get_current_user",
    "is_hosted",
]
