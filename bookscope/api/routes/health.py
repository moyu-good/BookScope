"""健康检查端点。

返回项目版本号（``bookscope.__version__``，与发版时对齐的三处版本号同源）
与代际标识，供前端或监控系统做 liveness / readiness 探活。
"""

from __future__ import annotations

from fastapi import APIRouter

from bookscope import __version__
from bookscope.api.schemas import HealthResponse

health_router = APIRouter(tags=["health"])


@health_router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """返回 API 健康状态与版本信息。

    ``version`` 直接取 ``bookscope.__version__``——和 ``web/package.json`` /
    ``CHANGELOG`` 一同发版对齐，不再读那份独立漂移的 VERSION 文件。
    当前只做静态字段回显；若未来要加实际连通性检查（例如探活向量索引、
    默认 provider 连通性），也在本函数里分支聚合。
    """
    return HealthResponse(status="ok", version=__version__, generation="r1-agent-loop")


__all__ = ["health_router"]
