"""托管版鉴权令牌(1.6.2 Phase 1b · 只 hosted 用)。

登录成功后签发一个带签名 + 时限的令牌(itsdangerous,Pallets 团队那个签名库,
不自己手搓加密);后续请求带 ``Authorization: Bearer <token>``,服务端验签 +
验时限、取出 user_id。无状态:服务端不存 session,验真全靠密钥。

密钥来自 env ``BOOKSCOPE_AUTH_SECRET``。hosted 模式下它必须设——没设是误配,
签发 / 验证时直接抛 :class:`AuthSecretMissingError`(宁可炸响也别静默把人当匿名,
那样会把本该鉴权的端点漏给所有人)。local 模式根本不调这里。

令牌里只装 user_id,**绝不装用户的 API key**(ADR-011:key 永不入库、永不出
客户端)。
"""

from __future__ import annotations

import os

from itsdangerous import BadData, URLSafeTimedSerializer

_SALT = "bookscope-auth-v1"
_RESET_SALT = "bookscope-pwd-reset-v1"
_EMAIL_VERIFY_SALT = "bookscope-email-verify-v1"
# 会话令牌 14 天:够长省得老登录,够短压住被盗令牌窗口。
_MAX_AGE_SECONDS = 14 * 24 * 3600
# 找回密码令牌 1 小时:短命、一次性,降低被盗 / 转发风险。
_RESET_MAX_AGE_SECONDS = 3600
# 邮箱验证令牌 7 天:够用户慢慢点,不用太短。
_EMAIL_VERIFY_MAX_AGE_SECONDS = 7 * 24 * 3600


class AuthSecretMissingError(RuntimeError):
    """hosted 模式没设 ``BOOKSCOPE_AUTH_SECRET``。"""


def _serializer(salt: str = _SALT) -> URLSafeTimedSerializer:
    secret = os.environ.get("BOOKSCOPE_AUTH_SECRET", "").strip()
    if not secret:
        raise AuthSecretMissingError(
            "hosted 模式必须设 BOOKSCOPE_AUTH_SECRET(令牌签名密钥)"
        )
    return URLSafeTimedSerializer(secret, salt=salt)


def _read_uid(token: str, *, salt: str, max_age: int) -> str | None:
    """验签 + 验时限 + 取 uid。签坏 / 被改 / 过期 / 格式不对都返 ``None``。

    不同 salt 的令牌互不通用(会话令牌验不过找回密码,反之亦然)——令牌按用途绑死。
    """
    if not token:
        return None
    try:
        data = _serializer(salt).loads(token, max_age=max_age)
    except BadData:
        return None
    if not isinstance(data, dict):
        return None
    uid = data.get("uid")
    return uid if isinstance(uid, str) and uid else None


def issue_token(user_id: str) -> str:
    """给已登录用户签发会话令牌。"""
    return _serializer().dumps({"uid": user_id})


def verify_token(token: str, *, max_age: int = _MAX_AGE_SECONDS) -> str | None:
    """验会话令牌,过则返 user_id,否则 ``None``。

    密钥缺失是误配、不是"令牌不对",照样抛 :class:`AuthSecretMissingError`。
    """
    return _read_uid(token, salt=_SALT, max_age=max_age)


def issue_reset_token(user_id: str) -> str:
    """签发找回密码令牌(独立 salt + 1 小时时限,跟会话令牌互不通用)。"""
    return _serializer(_RESET_SALT).dumps({"uid": user_id})


def verify_reset_token(
    token: str, *, max_age: int = _RESET_MAX_AGE_SECONDS
) -> str | None:
    """验找回密码令牌,过则返 user_id,否则 ``None``。"""
    return _read_uid(token, salt=_RESET_SALT, max_age=max_age)


def issue_email_verify_token(user_id: str) -> str:
    """签发邮箱验证令牌(独立 salt + 7 天时限)。"""
    return _serializer(_EMAIL_VERIFY_SALT).dumps({"uid": user_id})


def read_email_verify_token(
    token: str, *, max_age: int = _EMAIL_VERIFY_MAX_AGE_SECONDS
) -> str | None:
    """验邮箱验证令牌,过则返 user_id,否则 ``None``。"""
    return _read_uid(token, salt=_EMAIL_VERIFY_SALT, max_age=max_age)


def bearer_token_from_header(authorization: str | None) -> str | None:
    """从 ``Authorization`` 头里抠出 Bearer 令牌;没有 / 格式不对返 ``None``。"""
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


__all__ = [
    "AuthSecretMissingError",
    "bearer_token_from_header",
    "issue_email_verify_token",
    "issue_reset_token",
    "issue_token",
    "read_email_verify_token",
    "verify_reset_token",
    "verify_token",
]
