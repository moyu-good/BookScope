"""BookScope r1-agent-loop FastAPI 应用工厂。

使用 factory pattern 而非模块级 ``app = FastAPI()``：让测试能够构造
隔离的应用实例，且未来若要按不同配置起多实例（例如开发 / 生产）
只需在外部传参。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from bookscope import __version__
from bookscope.api.book_sessions import get_book_session_store
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
    logger.info("BookScope r1-agent-loop API starting (version=%s)", app.version)
    try:
        yield
    finally:
        # 进程退出前把 session 内存引用释放掉；单测里也会用到。
        get_book_session_store().clear()
        logger.info("BookScope r1-agent-loop API stopped")


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

    # TODO(生产环境)：allow_origins=["*"] 仅适用于开发；上线前必须收窄到
    # 实际前端域名。r1 开发期暂不引入 CORS 配置管理，保持最简。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 所有业务路由统一挂到 /api 前缀下。
    app.include_router(health_router, prefix="/api")
    app.include_router(agent_router, prefix="/api")
    app.include_router(books_router, prefix="/api")
    app.include_router(sessions_router, prefix="/api")

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
