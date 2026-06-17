"""BookScope r1-agent-loop 代际的 FastAPI 入口。

本目录是 r1 全新重建的入口（v7 的 api 已归档到 legacy/v7/）。
只暴露最小必要端点：

  - GET /api/health         健康检查
  - POST /api/agent/ask     查询时智能代理主入口

设计原则：

  - BYOK：请求中携带 api_key，服务端不持久化任何 LLM 凭据。
  - Book session 通过内存管理（session_id -> R0BookAssembler），
    进程重启即丢失；r1 开发期够用。
  - 只依赖 bookscope.agent 和 bookscope.models，不依赖 legacy/v7/。
"""

from bookscope.api.app import create_app

__all__ = ["create_app"]
