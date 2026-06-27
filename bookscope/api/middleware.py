"""生产环境防滥用中间件（零依赖，自写）。

BookScope 是 BYOK 公开服务：LLM 费用走用户自己的 key，但 ingest（解析 +
分块 + KG 抽取）吃的是**运营方**服务器的 CPU / 带宽，必须护住。这里做两件：

1. **上传大小封顶**：``/api/books/upload*`` 的 ``Content-Length`` 超过
   ``BOOKSCOPE_MAX_UPLOAD_MB``（默认 50MB）直接 413，避免巨型文件吃满内存
   /带宽。``books.py`` 原本没有任何大小限制。
2. **IP 令牌桶限流**：按端点配额。上传最重（KG 抽取吃 CPU），限最严。

不用 slowapi：它的 ``@limiter.limit`` 装饰器与新版 fastapi 对带 ``File``/``Form``
端点的签名解析不兼容（``response_model`` 推断成 204 触发断言）。本中间件走
ASGI 层，不碰端点签名，单 worker（``BookSessionStore`` 进程级单例的硬约束）
下内存令牌桶完全够用，零第三方依赖。

**真实访客 IP**：服务在 Cloudflare Tunnel 后面，访客 IP 在 ``CF-Connecting-IP``
头。直接读 ``request.client.host`` 会拿到隧道容器 IP，所有限流被"一个 IP"
顶满——故优先 ``CF-Connecting-IP``，回退 ``X-Forwarded-For`` 首个，再回退
``client.host``。uvicorn 启动带 ``--proxy-headers --forwarded-allow-ips=*``。
"""

from __future__ import annotations

import os
import time
from collections.abc import Awaitable, Callable
from threading import Lock

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

# 上传体积上限（MB）。
_MAX_UPLOAD_MB = int(os.environ.get("BOOKSCOPE_MAX_UPLOAD_MB", "50"))
_MAX_UPLOAD_BYTES = _MAX_UPLOAD_MB * 1024 * 1024


def _client_ip(request: Request) -> str:
    """取真实访客 IP：CF-Connecting-IP > X-Forwarded-For 首个 > client.host。"""
    cf = request.headers.get("CF-Connecting-IP")
    if cf:
        return cf.strip()
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "0.0.0.0"


class _TokenBucket:
    """单 IP 单端点的令牌桶：容量 ``capacity``，每 ``refill_rate`` 秒补 1 个令牌。"""

    __slots__ = ("capacity", "refill_rate", "tokens", "ts", "lock")

    def __init__(self, capacity: int, refill_rate: float):
        self.capacity = capacity
        self.refill_rate = refill_rate  # 秒/令牌
        self.tokens = float(capacity)
        self.ts = time.monotonic()
        self.lock = Lock()

    def allow(self) -> bool:
        with self.lock:
            now = time.monotonic()
            self.tokens = min(self.capacity, self.tokens + (now - self.ts) / self.refill_rate)
            self.ts = now
            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return True
            return False


# 端点配额：(容量, 每令牌秒数)。上传重——3 次 / 10 分钟 = 容量 3、每 200 秒补 1。
# agent 端点适中——30 次 / 分钟 = 容量 30、每 2 秒补 1。
_RULES: dict[str, tuple[int, float]] = {
    "/api/books/upload": (3, 200.0),
    "/api/agent/": (30, 2.0),
}


def _match_rule(path: str) -> tuple[str, int, float] | None:
    """返回 (族名, 容量, 每令牌秒数) 或 None。族名用作令牌桶 dict 的 key 前缀。"""
    if path.startswith("/api/books/upload"):
        rule = _RULES["/api/books/upload"]
        return ("upload", rule[0], rule[1])
    if path.startswith("/api/agent/"):
        rule = _RULES["/api/agent/"]
        return ("agent", rule[0], rule[1])
    return None


class AbuseGuardMiddleware(BaseHTTPMiddleware):
    """上传封顶 + IP 令牌桶限流二合一。

    令牌桶状态按 ``(端点族, IP)`` 存进程内存 dict。单 worker 下这是共享的，
    所有限流有效；多 worker 会各自一份（本项目硬约束单 worker，不涉及）。
    dict 不主动清理——IP 数有限、桶对象极小（4 个 float），长期增长可忽略；
    真要做可加 LRU，但小规模公开服务无必要。
    """

    def __init__(self, app, enabled: bool = True):
        super().__init__(app)
        self.enabled = enabled
        self._buckets: dict[tuple[str, str], _TokenBucket] = {}
        self._lock = Lock()

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if not self.enabled:
            return await call_next(request)

        path = request.url.path

        # 1. 上传体积封顶（仅上传端点）
        if path.startswith("/api/books/upload"):
            cl = request.headers.get("content-length")
            if cl is not None:
                try:
                    if int(cl) > _MAX_UPLOAD_BYTES:
                        return JSONResponse(
                            status_code=413,
                            content={
                                "error_type": "UploadTooLarge",
                                "message": (
                                    f"上传文件过大：Content-Length {cl} 超过"
                                    f" {_MAX_UPLOAD_MB}MB 上限。"
                                ),
                                "details": {"max_mb": _MAX_UPLOAD_MB, "received_bytes": int(cl)},
                            },
                        )
                except ValueError:
                    pass  # 非法 Content-Length，交给 FastAPI 正常 400

        # 2. IP 令牌桶限流
        rule = _match_rule(path)
        if rule is not None:
            family, capacity, refill = rule
            ip = _client_ip(request)
            key = (family, ip)
            with self._lock:
                bucket = self._buckets.get(key)
                if bucket is None:
                    bucket = _TokenBucket(capacity, refill)
                    self._buckets[key] = bucket
            if not bucket.allow():
                return JSONResponse(
                    status_code=429,
                    content={
                        "error_type": "RateLimited",
                        "message": "请求太频繁，请稍后再试。",
                        "details": {"ip": ip, "path": path},
                    },
                    headers={"Retry-After": str(int(refill))},
                )

        return await call_next(request)


__all__ = ["AbuseGuardMiddleware", "_client_ip", "_MAX_UPLOAD_MB"]
