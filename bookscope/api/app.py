"""BookScope r1-agent-loop FastAPI 应用工厂。

使用 factory pattern 而非模块级 ``app = FastAPI()``：让测试能够构造
隔离的应用实例，且未来若要按不同配置起多实例（例如开发 / 生产）
只需在外部传参。

生产部署（Docker）下，本应用还兼任**前端静态托管**：环境变量
``BOOKSCOPE_STATIC_DIR`` 指向前端 ``dist`` 时，同源挂载前端，浏览器看到的
是同源请求——前端代码里全是 ``fetch("/api/...")`` 相对路径，同源即免 CORS
折腾。dev 不设该变量，前端仍由 vite dev server 出。
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from bookscope import __version__
from bookscope.api.book_sessions import get_book_session_store
from bookscope.api.deployment import deployment_mode, is_hosted
from bookscope.api.middleware import AbuseGuardMiddleware
from bookscope.api.routes import (
    agent_router,
    books_router,
    health_router,
    sessions_router,
)

logger = logging.getLogger("bookscope.api")


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用 lifespan hook：启动时打印一行日志，关闭时清空 session 存储。"""
    logger.info(
        "BookScope r1-agent-loop API starting (version=%s, deployment_mode=%s)",
        app.version,
        deployment_mode(),
    )
    try:
        yield
    finally:
        # 进程退出前把 session 内存引用释放掉；单测里也会用到。
        get_book_session_store().clear()
        logger.info("BookScope r1-agent-loop API stopped")


class SPAStaticFiles(StaticFiles):
    """前端 SPA 回退：找不到的静态文件回 ``index.html``，交给前端路由。

    关键：``/api/*`` 的 404 **不**回退——API 路径打不到文件就该老老实实 404
    返 JSON，不能被前端 ``index.html`` 顶成 200。靠 ``scope["path"]`` 判前缀。
    """

    async def get_response(self, path: str, scope):  # type: ignore[override]
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as ex:
            if ex.status_code == 404 and not scope["path"].startswith("/api"):
                return await super().get_response("index.html", scope)
            raise


def _cors_origins() -> list[str]:
    """CORS 允许来源：读 ``BOOKSCOPE_CORS_ORIGINS``，逗号分隔；默认 ``*``。

    同源部署（前端由本应用托管）下 CORS 不触发，留着是为 dev（前端走
    vite :5173 跨 :8000）和"前端另部署到别处"两种场景。
    """
    raw = os.environ.get("BOOKSCOPE_CORS_ORIGINS", "").strip()
    if not raw:
        return ["*"]
    return [o.strip() for o in raw.split(",") if o.strip()]


def create_app() -> FastAPI:
    """构造一个 FastAPI 实例。

    每次调用都生成一个**全新**的 app 对象，不复用单例——测试里可以
    独立构造、独立挂 router、独立替换 dependency_overrides，互不干扰。
    """
    app = FastAPI(
        title="BookScope r1 API",
        description=(
            "BookScope r1-agent-loop 代际的 FastAPI 入口。"
            "只暴露最小必要端点（health + agent/ask）；"
            "不保留 v7 的上传 / 分析 / 导出端点。"
        ),
        version=__version__,
        lifespan=_lifespan,
    )

    # 防滥用：上传体积封顶 + IP 令牌桶限流（护运营方 CPU/带宽，BYOK 下 LLM 走用户 key）。
    # BOOKSCOPE_RATELIMIT_DISABLED=1 可关（测试用）。
    app.add_middleware(
        AbuseGuardMiddleware,
        enabled=os.environ.get("BOOKSCOPE_RATELIMIT_DISABLED", "").strip() != "1",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 所有业务路由统一挂到 /api 前缀下。先注册，确保比根 StaticFiles 早匹配。
    app.include_router(health_router, prefix="/api")
    app.include_router(agent_router, prefix="/api")
    app.include_router(books_router, prefix="/api")
    app.include_router(sessions_router, prefix="/api")

    # 托管版才挂账号路由(ADR-011)+ 标注路由(WP-reading-workspace Phase C)。
    # 懒 import:local 不挂、也不 import 这些模块,故启动不会把 argon2 /
    # itsdangerous 拽进来——纯 pip install -e . 照样跑得起。标注 local 走前端
    # localStorage,这些端点 local 打过去 404,本地版逐字节零变化。
    if is_hosted():
        from bookscope.api.routes.accounts import accounts_router
        from bookscope.api.routes.annotations import annotations_router

        app.include_router(accounts_router, prefix="/api")
        app.include_router(annotations_router, prefix="/api")

    # 生产：同源托管前端 dist（Vite base="/" 产物）。dev 不设此变量则跳过，
    # 前端仍由 vite dev server 出。
    static_dir = os.environ.get("BOOKSCOPE_STATIC_DIR", "").strip()
    if static_dir and Path(static_dir).is_dir():
        app.mount("/", SPAStaticFiles(directory=static_dir, html=True), name="spa")
        logger.info("同源托管前端静态资源：%s", static_dir)
    else:
        # 非生产兜底：根路径给一个占位，方便裸起后端时知道前端没挂。
        @app.get("/")
        async def _root_placeholder():  # pragma: no cover — dev 用
            return {
                "name": "BookScope API",
                "version": __version__,
                "hint": "前端未托管（BOOKSCOPE_STATIC_DIR 未设）。dev 请用 vite dev server。",
            }

    return app


if __name__ == "__main__":  # pragma: no cover — 本地起服用
    import uvicorn

    uvicorn.run(
        "bookscope.api.app:create_app",
        factory=True,
        host="127.0.0.1",
        port=8000,
        reload=True,
    )


__all__ = ["create_app"]
