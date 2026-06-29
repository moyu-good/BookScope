"""部署开关 + 当前用户解析单测(1.6.2 Phase 0 + Phase 1b)。

重点护一条线:**local 模式即便带合法令牌也旁路返 None**——本地版零回归的命门。
hosted 模式才走真鉴权(验签 → 查库 → 返用户)。全程内存 / 临时 DB,不起服务。
"""

from __future__ import annotations

import pytest

from bookscope.api import auth, deployment


@pytest.fixture(autouse=True)
def _clean_singleton():
    deployment._reset_accounts_store()
    yield
    deployment._reset_accounts_store()


def _hosted_env(monkeypatch, tmp_path):
    monkeypatch.setenv("BOOKSCOPE_DEPLOYMENT_MODE", "hosted")
    monkeypatch.setenv("BOOKSCOPE_AUTH_SECRET", "s")
    monkeypatch.setenv("BOOKSCOPE_ACCOUNTS_DB", str(tmp_path / "acc.db"))
    deployment._reset_accounts_store()


# ---- 模式开关 ----

def test_default_is_local(monkeypatch):
    monkeypatch.delenv("BOOKSCOPE_DEPLOYMENT_MODE", raising=False)
    assert deployment.deployment_mode() == "local"
    assert deployment.is_hosted() is False


def test_hosted_tolerates_case_and_space(monkeypatch):
    monkeypatch.setenv("BOOKSCOPE_DEPLOYMENT_MODE", "  HoStEd ")
    assert deployment.is_hosted() is True


def test_unknown_value_falls_back_local(monkeypatch):
    monkeypatch.setenv("BOOKSCOPE_DEPLOYMENT_MODE", "typo")
    assert deployment.is_hosted() is False


# ---- local 旁路(命门) ----

def test_local_resolve_user_always_none(monkeypatch):
    # local 即便给一个本来合法的令牌,也旁路返 None。
    monkeypatch.delenv("BOOKSCOPE_DEPLOYMENT_MODE", raising=False)
    monkeypatch.setenv("BOOKSCOPE_AUTH_SECRET", "s")
    token = auth.issue_token("u-1")
    assert deployment.resolve_user_from_token(f"Bearer {token}") is None


# ---- hosted 真鉴权 ----

def test_hosted_resolve_valid_token(monkeypatch, tmp_path):
    _hosted_env(monkeypatch, tmp_path)
    user = deployment.get_accounts_store().create_user(
        email="x@y.com", password="pw123456"
    )
    token = auth.issue_token(user.id)
    got = deployment.resolve_user_from_token(f"Bearer {token}")
    assert got is not None and got.id == user.id


def test_hosted_resolve_no_or_bad_token(monkeypatch, tmp_path):
    _hosted_env(monkeypatch, tmp_path)
    assert deployment.resolve_user_from_token(None) is None
    assert deployment.resolve_user_from_token("Bearer garbage") is None
    assert deployment.resolve_user_from_token("NotBearer xxx") is None


def test_hosted_resolve_unknown_user_returns_none(monkeypatch, tmp_path):
    # 令牌签得合法,但 user 不在库(已删 / 伪造 id)→ None。
    _hosted_env(monkeypatch, tmp_path)
    token = auth.issue_token("ghost-user-id")
    assert deployment.resolve_user_from_token(f"Bearer {token}") is None


def test_get_current_user_reads_request_header(monkeypatch, tmp_path):
    _hosted_env(monkeypatch, tmp_path)
    user = deployment.get_accounts_store().create_user(
        email="z@y.com", password="pw123456"
    )
    token = auth.issue_token(user.id)

    class _Req:
        headers = {"authorization": f"Bearer {token}"}

    got = deployment.get_current_user(_Req())
    assert got is not None and got.id == user.id
