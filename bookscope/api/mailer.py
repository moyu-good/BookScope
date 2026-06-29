"""邮件发送(provider-agnostic · 托管版 Phase 2b)。

跟 LLM 一样不锁死服务商:抽象一个发送器,默认 dev 落日志、生产走 SMTP(env 配),
服务商(腾讯云 SES / SendGrid / 自建 SMTP 都行)以后插 env 即可,代码现在就能写、
能测。本地克隆版从不调这里。

生产 SMTP 的 env:``BOOKSCOPE_SMTP_HOST`` / ``_PORT`` / ``_USER`` / ``_PASSWORD`` /
``_FROM`` / ``_TLS``。没配 HOST 就退 :class:`LogEmailSender`(只记日志、不真发)——
dev、或还没接服务商时的安全默认,绝不静默假装发成功又什么都没干。
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage
from typing import Protocol

logger = logging.getLogger(__name__)


class EmailSender(Protocol):
    """发一封纯文本邮件。失败抛异常,由调用方决定吞还是报。"""

    def send(self, *, to: str, subject: str, body: str) -> None: ...


class LogEmailSender:
    """只把邮件记到日志、不真发。dev / 没配 SMTP 时的默认。"""

    def send(self, *, to: str, subject: str, body: str) -> None:
        logger.info("[mailer:log] to=%s subject=%s\n%s", to, subject, body)


class SMTPEmailSender:
    """走 SMTP 真发(env 配)。"""

    def __init__(self) -> None:
        self._host = os.environ.get("BOOKSCOPE_SMTP_HOST", "").strip()
        self._port = int(os.environ.get("BOOKSCOPE_SMTP_PORT", "587"))
        self._user = os.environ.get("BOOKSCOPE_SMTP_USER", "").strip()
        self._password = os.environ.get("BOOKSCOPE_SMTP_PASSWORD", "")
        self._from = os.environ.get("BOOKSCOPE_SMTP_FROM", "").strip() or self._user
        self._use_tls = os.environ.get("BOOKSCOPE_SMTP_TLS", "1").strip() != "0"

    def send(self, *, to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"] = self._from
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        with smtplib.SMTP(self._host, self._port) as server:
            if self._use_tls:
                server.starttls()
            if self._user:
                server.login(self._user, self._password)
            server.send_message(msg)


class CapturingEmailSender:
    """测试用:把发出去的邮件收集进 ``sent``,断言用,不真发。"""

    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    def send(self, *, to: str, subject: str, body: str) -> None:
        self.sent.append({"to": to, "subject": subject, "body": body})


_sender: EmailSender | None = None


def get_email_sender() -> EmailSender:
    """当前发送器(懒建单例)。配了 ``BOOKSCOPE_SMTP_HOST`` 走 SMTP,否则落日志。"""
    global _sender
    if _sender is None:
        if os.environ.get("BOOKSCOPE_SMTP_HOST", "").strip():
            _sender = SMTPEmailSender()
        else:
            _sender = LogEmailSender()
    return _sender


def set_email_sender(sender: EmailSender | None) -> None:
    """覆盖发送器(测试用;传 ``None`` 复位成懒建)。"""
    global _sender
    _sender = sender


def send_email(*, to: str, subject: str, body: str) -> None:
    """发一封邮件(走当前发送器)。"""
    get_email_sender().send(to=to, subject=subject, body=body)


__all__ = [
    "CapturingEmailSender",
    "EmailSender",
    "LogEmailSender",
    "SMTPEmailSender",
    "get_email_sender",
    "send_email",
    "set_email_sender",
]
