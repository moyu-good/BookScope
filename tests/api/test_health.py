"""GET /api/health 的端到端测试。

用 FastAPI TestClient 走完整的 ASGI 栈，验证：

  - 状态码 200
  - 响应字段齐全（status / version / generation）
  - generation 恒为 r1-agent-loop（代际不变量）
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from bookscope import __version__
from bookscope.api import create_app
from bookscope.api.book_sessions import get_book_session_store


@pytest.fixture()
def client() -> TestClient:
    """为每条测试构造隔离的 TestClient；退出时清空 session 存储。"""
    app = create_app()
    with TestClient(app) as c:
        yield c
    get_book_session_store().clear()


def test_health_returns_200(client: TestClient) -> None:
    """健康检查必须返回 200。"""
    resp = client.get("/api/health")
    assert resp.status_code == 200


def test_health_response_has_expected_fields(client: TestClient) -> None:
    """响应必须含 status / version / generation 三个字段。"""
    body = client.get("/api/health").json()
    assert "status" in body
    assert "version" in body
    assert "generation" in body


def test_health_status_ok(client: TestClient) -> None:
    """status 字段当前固定为 'ok'。"""
    body = client.get("/api/health").json()
    assert body["status"] == "ok"


def test_health_generation_is_r1_agent_loop(client: TestClient) -> None:
    """generation 恒为 r1-agent-loop；代际标识是永久合约。"""
    body = client.get("/api/health").json()
    assert body["generation"] == "r1-agent-loop"


def test_health_version_matches_package_version(client: TestClient) -> None:
    """version 字段必须等于 bookscope.__version__（对外 API 版本不许漂移）。"""
    body = client.get("/api/health").json()
    assert body["version"] == __version__


def test_health_deployment_mode_defaults_local(client: TestClient) -> None:
    """默认（未设 env）部署形态是 local——前端据此不显示登录入口。"""
    body = client.get("/api/health").json()
    assert body["deployment_mode"] == "local"


def test_health_deployment_mode_hosted(monkeypatch, tmp_path) -> None:
    """设了 BOOKSCOPE_DEPLOYMENT_MODE=hosted 时,health 如实回 hosted。"""
    monkeypatch.setenv("BOOKSCOPE_DEPLOYMENT_MODE", "hosted")
    monkeypatch.setenv("BOOKSCOPE_RATELIMIT_DISABLED", "1")
    with TestClient(create_app()) as c:
        body = c.get("/api/health").json()
    assert body["deployment_mode"] == "hosted"
    get_book_session_store().clear()
