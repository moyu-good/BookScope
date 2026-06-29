"""账号 + 文档归属数据层(1.6.2 Phase 1a · 只托管版用)。

ADR-011 定的:托管版加账号、在后端留住用户文档,本地克隆版完全旁路。
这个模块只在 ``hosted`` 模式被 import / 实例化;``local`` 模式从不加载它,
行为跟今天逐字节一致、零回归。

DB 选型先 SQLite(ADR-011 第 29 行"先 SQLite 后 Postgres")。两张表:

- ``users``:账号——邮箱 / 可选手机 / argon2 密码哈希。**任何表都没有 API key
  字段**(ADR-011 第 3 条:key 永不入库,焊死客户端、按请求传、用完即弃)。
- ``documents``:文档归属——谁传的哪份文档。

数据隔离是这层的命门,做在 SQL 的 WHERE 层、不在 Python 里过滤:
取某人的文档一律 ``WHERE owner_user_id = ?``;取单份带归属校验一律
``WHERE id = ? AND owner_user_id = ?``。查不到就是"没有"或"不是你的",两种
都返 ``None`` / 空,绝不先把别人的数据取出来、再在 Python 里判断该不该给。
"""

from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from pydantic import BaseModel

_DEFAULT_DB = Path("data") / "accounts.db"

# argon2id,默认参数(内存硬,CPU-only,无 GPU 依赖)。
_ph = PasswordHasher()

# 查无此人时也跑一次 verify,抵消时序差,防靠响应时间枚举哪些邮箱注册过。
_DUMMY_HASH = _ph.hash("bookscope-timing-equalizer")


class DuplicateEmailError(ValueError):
    """注册时邮箱已存在。"""


class User(BaseModel):
    """账号的对外视图——**绝不含 password_hash**,哈希不出数据层。"""

    id: str
    email: str
    phone: str | None = None
    email_verified: bool = False
    created_at: str


class Document(BaseModel):
    """一份用户文档的归属记录(不存文档正文,只记谁拥有哪份)。"""

    id: str
    owner_user_id: str
    title: str
    created_at: str


def hash_password(plain: str) -> str:
    """argon2id 哈希一个明文密码。"""
    return _ph.hash(plain)


def verify_password(stored_hash: str, plain: str) -> bool:
    """对则 True,不对(含哈希损坏)则 False,绝不抛给上层。"""
    try:
        return _ph.verify(stored_hash, plain)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def _row_to_user(row: sqlite3.Row | None) -> User | None:
    if row is None:
        return None
    return User(
        id=row["id"],
        email=row["email"],
        phone=row["phone"],
        email_verified=bool(row["email_verified"]),
        created_at=row["created_at"],
    )


def _row_to_doc(row: sqlite3.Row | None) -> Document | None:
    if row is None:
        return None
    return Document(
        id=row["id"],
        owner_user_id=row["owner_user_id"],
        title=row["title"],
        created_at=row["created_at"],
    )


class AccountsStore:
    """SQLite 账号 + 文档归属仓储。

    线程安全:FastAPI 同步路由跑在线程池里,故连接开 ``check_same_thread=False``
    再加一把进程内锁把写串行化。Phase 1a 这个量级够用;将来 Postgres 化时整层换掉。
    """

    def __init__(self, db_path: str | Path = _DEFAULT_DB) -> None:
        self._db_path = str(db_path)
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # 外键级联要这个连接级 PRAGMA 开着,删账号才能连带删归属。
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id            TEXT PRIMARY KEY,
                    email         TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    phone         TEXT,
                    password_hash TEXT NOT NULL,
                    created_at    TEXT NOT NULL,
                    email_verified INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS documents (
                    id            TEXT PRIMARY KEY,
                    owner_user_id TEXT NOT NULL
                                  REFERENCES users(id) ON DELETE CASCADE,
                    title         TEXT NOT NULL,
                    created_at    TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_documents_owner
                    ON documents(owner_user_id);
                """
            )
        self._migrate_add_email_verified()

    def _migrate_add_email_verified(self) -> None:
        """老库(Phase 2c 之前建的)补 ``email_verified`` 列;新库 CREATE 已含,no-op。"""
        with self._lock, self._conn:
            cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(users)")}
            if "email_verified" not in cols:
                self._conn.execute(
                    "ALTER TABLE users ADD COLUMN "
                    "email_verified INTEGER NOT NULL DEFAULT 0"
                )

    # ---- 账号 ----

    def create_user(
        self, *, email: str, password: str, phone: str | None = None
    ) -> User:
        """建账号。邮箱大小写不敏感地查重,重了抛 :class:`DuplicateEmailError`。"""
        email_norm = email.strip()
        if not email_norm:
            raise ValueError("email 不能为空")
        if not password:
            raise ValueError("password 不能为空")
        uid = uuid.uuid4().hex
        now = datetime.now(tz=UTC).isoformat()
        pw_hash = hash_password(password)
        try:
            with self._lock, self._conn:
                self._conn.execute(
                    "INSERT INTO users (id, email, phone, password_hash, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (uid, email_norm, phone, pw_hash, now),
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateEmailError(f"邮箱已注册:{email_norm}") from exc
        return User(
            id=uid,
            email=email_norm,
            phone=phone,
            email_verified=False,
            created_at=now,
        )

    def get_user_by_email(self, email: str) -> User | None:
        row = self._conn.execute(
            "SELECT id, email, phone, email_verified, created_at FROM users "
            "WHERE email = ? COLLATE NOCASE",
            (email.strip(),),
        ).fetchone()
        return _row_to_user(row)

    def get_user_by_id(self, user_id: str) -> User | None:
        row = self._conn.execute(
            "SELECT id, email, phone, email_verified, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        return _row_to_user(row)

    def verify_credentials(self, *, email: str, password: str) -> User | None:
        """邮箱 + 密码对则返 :class:`User`,否则 ``None``。

        查无此人和密码错都返 ``None``、不区分(防邮箱枚举);查无此人时也跑一次
        verify 抵消时序差。
        """
        row = self._conn.execute(
            "SELECT id, email, phone, email_verified, password_hash, created_at "
            "FROM users WHERE email = ? COLLATE NOCASE",
            (email.strip(),),
        ).fetchone()
        if row is None:
            verify_password(_DUMMY_HASH, password)
            return None
        if not verify_password(row["password_hash"], password):
            return None
        return _row_to_user(row)

    def set_password(self, user_id: str, new_password: str) -> bool:
        """改密码(找回密码 / 改密用)。改到返 ``True``,没这人返 ``False``。"""
        if not new_password:
            raise ValueError("password 不能为空")
        pw_hash = hash_password(new_password)
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (pw_hash, user_id),
            )
        return cur.rowcount > 0

    def mark_email_verified(self, user_id: str) -> bool:
        """把邮箱标记为已验证。标到返 ``True``,没这人返 ``False``。"""
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE users SET email_verified = 1 WHERE id = ?", (user_id,)
            )
        return cur.rowcount > 0

    def delete_user(self, user_id: str) -> bool:
        """彻底删账号,连带删它名下所有文档归属(ON DELETE CASCADE)。

        对应 ADR-011 的删除权;删到了返 ``True``,本就没有返 ``False``。
        """
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return cur.rowcount > 0

    # ---- 文档归属(隔离命门) ----

    def add_document(
        self, *, owner_user_id: str, doc_id: str, title: str
    ) -> Document:
        """记一份文档的归属。doc_id 沿用 session_id,全局唯一。"""
        now = datetime.now(tz=UTC).isoformat()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO documents (id, owner_user_id, title, created_at) "
                "VALUES (?, ?, ?, ?)",
                (doc_id, owner_user_id, title, now),
            )
        return Document(
            id=doc_id, owner_user_id=owner_user_id, title=title, created_at=now
        )

    def list_documents(self, owner_user_id: str) -> list[Document]:
        """只返这个用户自己的文档,新的在前(隔离做在 WHERE,不在 Python)。"""
        rows = self._conn.execute(
            "SELECT id, owner_user_id, title, created_at FROM documents "
            "WHERE owner_user_id = ? ORDER BY created_at DESC, id DESC",
            (owner_user_id,),
        ).fetchall()
        return [doc for r in rows if (doc := _row_to_doc(r)) is not None]

    def get_owned_document(
        self, *, owner_user_id: str, doc_id: str
    ) -> Document | None:
        """取单份并校验归属:不属于这个用户就当不存在、返 ``None``。

        归属校验焊进 SQL 的 ``WHERE id = ? AND owner_user_id = ?``——绝不先把
        别人的文档取出来再在 Python 里判断。查不到 = 没有 or 不是你的,都返 ``None``。
        """
        row = self._conn.execute(
            "SELECT id, owner_user_id, title, created_at FROM documents "
            "WHERE id = ? AND owner_user_id = ?",
            (doc_id, owner_user_id),
        ).fetchone()
        return _row_to_doc(row)

    def owns(self, *, owner_user_id: str, doc_id: str) -> bool:
        """这个用户拥有这份文档吗。"""
        return (
            self.get_owned_document(owner_user_id=owner_user_id, doc_id=doc_id)
            is not None
        )

    def delete_document(self, *, owner_user_id: str, doc_id: str) -> bool:
        """删一份自己的文档。只能删自己的——删别人的等于删不动,返 ``False``。"""
        with self._lock, self._conn:
            cur = self._conn.execute(
                "DELETE FROM documents WHERE id = ? AND owner_user_id = ?",
                (doc_id, owner_user_id),
            )
        return cur.rowcount > 0

    def close(self) -> None:
        self._conn.close()


__all__ = [
    "AccountsStore",
    "Document",
    "DuplicateEmailError",
    "User",
    "hash_password",
    "verify_password",
]
