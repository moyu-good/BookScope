"""健康检查端点。

返回项目版本号（从仓库根 VERSION 文件读取）与代际标识，供前端或
监控系统做 liveness / readiness 探活。VERSION 缺失时返回 ``"unknown"``
而非抛错，保证探活路径在任何情况下都能回 200。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from bookscope.api.schemas import HealthResponse

health_router = APIRouter(tags=["health"])

_VERSION_FILE = Path(__file__).resolve().parents[3] / "VERSION"


def _read_version_file() -> str:
    """读仓库根 ``VERSION`` 文件；任何异常（不存在 / 权限 / 空内容）
    都降级为 ``"unknown"``，保证健康检查永不失败。"""
    try:
        raw = _VERSION_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"
    return raw or "unknown"


@health_router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """返回 API 健康状态与版本信息。

    当前实现只做静态字段回显；若未来要加实际连通性检查（例如探活
    向量索引、默认 provider 连通性），也在本函数里分支聚合。
    """
    version = _read_version_file()
    return HealthResponse(status="ok", version=version, generation="r1-agent-loop")


__all__ = ["health_router"]
