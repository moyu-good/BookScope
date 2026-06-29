"""账号路由 e2e 单测(1.6.2 Phase 1b-ii)。

走 TestClient 真打端点。命门两条:
1. hosted 下注册 / 登录 / whoami 全通,返回里**绝不带密码哈希**。
2. local 下 /auth/* 根本不挂 → 404(本地版零账号面)。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from bookscope.api import auth, deployment, mailer
from bookscope.api.app import create_app


@pytest.fixture
def hosted_client(monkeypatch, tmp_path):
    monkeypatch.setenv("BOOKSCOPE_DEPLOYMENT_MODE", "hosted")
    monkeypatch.setenv("BOOKSCOPE_AUTH_SECRET", "test-secret-key")
    monkeypatch.setenv("BOOKSCOPE_ACCOUNTS_DB", str(tmp_path / "acc.db"))
    monkeypatch.setenv("BOOKSCOPE_RATELIMIT_DISABLED", "1")
    deployment._reset_accounts_store()
    with TestClient(create_app()) as client:
        yield client
    deployment._reset_accounts_store()


def test_register_returns_token_and_user(hosted_client):
    r = hosted_client.post(
        "/api/auth/register", json={"email": "a@b.com", "password": "pw123456"}
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["token"]
    assert body["user"]["email"] == "a@b.com"
    # 对外绝不漏哈希 / 密码。
    assert "password" not in body["user"]
    assert "password_hash" not in body["user"]


def test_register_duplicate_returns_409(hosted_client):
    payload = {"email": "dup@b.com", "password": "pw123456"}
    hosted_client.post("/api/auth/register", json=payload)
    r = hosted_client.post("/api/auth/register", json=payload)
    assert r.status_code == 409


def test_register_short_password_422(hosted_client):
    r = hosted_client.post(
        "/api/auth/register", json={"email": "x@b.com", "password": "short"}
    )
    assert r.status_code == 422


def test_register_bad_email_422(hosted_client):
    r = hosted_client.post(
        "/api/auth/register", json={"email": "notanemail", "password": "pw123456"}
    )
    assert r.status_code == 422


def test_login_then_me(hosted_client):
    hosted_client.post(
        "/api/auth/register", json={"email": "log@b.com", "password": "pw123456"}
    )
    r = hosted_client.post(
        "/api/auth/login", json={"email": "log@b.com", "password": "pw123456"}
    )
    assert r.status_code == 200
    token = r.json()["token"]
    me = hosted_client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert me.status_code == 200
    assert me.json()["email"] == "log@b.com"


def test_login_wrong_password_401(hosted_client):
    hosted_client.post(
        "/api/auth/register", json={"email": "w@b.com", "password": "pw123456"}
    )
    r = hosted_client.post(
        "/api/auth/login", json={"email": "w@b.com", "password": "nope-wrong"}
    )
    assert r.status_code == 401


def test_me_without_token_401(hosted_client):
    assert hosted_client.get("/api/auth/me").status_code == 401


def test_local_mode_has_no_auth_routes(monkeypatch, tmp_path):
    # 命门:local 模式 /auth/* 根本没挂 → 404,本地版零账号面。
    monkeypatch.delenv("BOOKSCOPE_DEPLOYMENT_MODE", raising=False)
    monkeypatch.setenv("BOOKSCOPE_RATELIMIT_DISABLED", "1")
    deployment._reset_accounts_store()
    with TestClient(create_app()) as client:
        r = client.post(
            "/api/auth/register", json={"email": "a@b.com", "password": "pw123456"}
        )
        assert r.status_code == 404


def test_delete_account(hosted_client):
    hosted_client.post(
        "/api/auth/register", json={"email": "del@b.com", "password": "pw123456"}
    )
    login = hosted_client.post(
        "/api/auth/login", json={"email": "del@b.com", "password": "pw123456"}
    )
    hdr = {"Authorization": f"Bearer {login.json()['token']}"}
    # 注销 → 204
    assert hosted_client.delete("/api/auth/me", headers=hdr).status_code == 204
    # 账号没了:再登录 401
    relogin = hosted_client.post(
        "/api/auth/login", json={"email": "del@b.com", "password": "pw123456"}
    )
    assert relogin.status_code == 401
    # 令牌随之失效:whoami 401(user 查不到了)
    assert hosted_client.get("/api/auth/me", headers=hdr).status_code == 401


def test_delete_account_requires_login(hosted_client):
    assert hosted_client.delete("/api/auth/me").status_code == 401


# ---- Phase 2b:找回密码 ----


def test_forgot_password_sends_email_for_existing(hosted_client):
    cap = mailer.CapturingEmailSender()
    mailer.set_email_sender(cap)
    try:
        hosted_client.post(
            "/api/auth/register", json={"email": "f@b.com", "password": "pw123456"}
        )
        r = hosted_client.post("/api/auth/forgot-password", json={"email": "f@b.com"})
        assert r.status_code == 200
        assert len(cap.sent) == 1
        assert cap.sent[0]["to"] == "f@b.com"
    finally:
        mailer.set_email_sender(None)


def test_forgot_password_unknown_email_200_no_send(hosted_client):
    cap = mailer.CapturingEmailSender()
    mailer.set_email_sender(cap)
    try:
        # 不存在的邮箱也返 200(防枚举),但不真发。
        r = hosted_client.post(
            "/api/auth/forgot-password", json={"email": "ghost@b.com"}
        )
        assert r.status_code == 200
        assert cap.sent == []
    finally:
        mailer.set_email_sender(None)


def test_reset_password_changes_password(hosted_client):
    reg = hosted_client.post(
        "/api/auth/register", json={"email": "r@b.com", "password": "oldpass12"}
    )
    token = auth.issue_reset_token(reg.json()["user"]["id"])
    r = hosted_client.post(
        "/api/auth/reset-password",
        json={"token": token, "new_password": "newpass34"},
    )
    assert r.status_code == 200
    assert r.json()["token"]  # 重置成功直接给会话令牌
    # 旧密码不行,新密码行
    assert (
        hosted_client.post(
            "/api/auth/login", json={"email": "r@b.com", "password": "oldpass12"}
        ).status_code
        == 401
    )
    assert (
        hosted_client.post(
            "/api/auth/login", json={"email": "r@b.com", "password": "newpass34"}
        ).status_code
        == 200
    )


def test_reset_password_bad_token_400(hosted_client):
    r = hosted_client.post(
        "/api/auth/reset-password",
        json={"token": "garbage", "new_password": "newpass34"},
    )
    assert r.status_code == 400


def test_reset_password_short_password_422(hosted_client):
    reg = hosted_client.post(
        "/api/auth/register", json={"email": "r2@b.com", "password": "oldpass12"}
    )
    token = auth.issue_reset_token(reg.json()["user"]["id"])
    r = hosted_client.post(
        "/api/auth/reset-password", json={"token": token, "new_password": "short"}
    )
    assert r.status_code == 422
    deployment._reset_accounts_store()
