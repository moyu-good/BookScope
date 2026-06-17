"""r1 FastAPI 路由组。

每个子模块暴露一个 ``APIRouter`` 实例；:mod:`app` 把它们挂到统一
``/api`` 前缀下。
"""

from bookscope.api.routes.agent import agent_router
from bookscope.api.routes.books import books_router
from bookscope.api.routes.health import health_router
from bookscope.api.routes.sessions import sessions_router

__all__ = ["agent_router", "books_router", "health_router", "sessions_router"]
