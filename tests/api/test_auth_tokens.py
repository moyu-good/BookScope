"""鉴权令牌单测(1.6.2 Phase 1b · bookscope/api/auth.py)。

不碰 DB、不调 LLM、不起服务。验签 / 时限 / 篡改 / 换密钥 / 缺密钥 / Bearer 解析。
"""

from __future__ import annotations

import pytest

from bookscope.api import auth


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("BOOKSCOPE_AUTH_SECRET", "test-secret-key")


def test_issue_verify_roundtrip():
    token = auth.issue_token("user-123")
    assert auth.verify_token(token) == "user-123"


def test_verify_tampered_or_garbage_returns_none():
    token = auth.issue_token("user-123")
    assert auth.verify_token(token + "x") is None
    assert auth.verify_token("garbage") is None
    assert auth.verify_token("") is None


def test_verify_expired_returns_none():
    token = auth.issue_token("user-123")
    # max_age 负数 → 任何年龄都算过期。
    assert auth.verify_token(token, max_age=-1) is None


def test_verify_wrong_secret_returns_none(monkeypatch):
    token = auth.issue_token("user-123")
    monkeypatch.setenv("BOOKSCOPE_AUTH_SECRET", "a-different-secret")
    assert auth.verify_token(token) is None


def test_missing_secret_raises(monkeypatch):
    monkeypatch.delenv("BOOKSCOPE_AUTH_SECRET", raising=False)
    with pytest.raises(auth.AuthSecretMissingError):
        auth.issue_token("u")
    with pytest.raises(auth.AuthSecretMissingError):
        auth.verify_token("any-token")


def test_bearer_token_from_header():
    assert auth.bearer_token_from_header("Bearer abc.def") == "abc.def"
    assert auth.bearer_token_from_header("bearer abc") == "abc"  # 大小写不敏感
    assert auth.bearer_token_from_header("Basic abc") is None
    assert auth.bearer_token_from_header("just-a-token") is None
    assert auth.bearer_token_from_header(None) is None
    assert auth.bearer_token_from_header("Bearer    ") is None
