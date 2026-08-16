"""SQLite 持久化缓存底座 —— Sprint 8 W2 L2 LLM 调用缓存的存储层。

ADR-008 D-2 推荐 L2 用 SQLite：进程重启不丢、stdlib 零外部依赖、单文件
方便清理。本模块只提供通用的 key→bytes 表加版本失效加 stats 三件套；
具体 cache key 算法、value 序列化、按业务字段 invalidate 都交给上层
（``llm_cache.py``）。

设计取舍：

- **每次调用新开 connection**：sqlite3 ``Connection`` 默认不允许跨线程
  共享，BookScope 的 FastAPI 多 worker / fast_path 并发 + ThreadPoolExecutor
  里都可能多线程访问。开新 conn 性能成本可接受（本地 SQLite open 是
  亚毫秒），换来线程安全无脑稳。
- **WAL 模式**：``PRAGMA journal_mode=WAL`` 让读写不互斥——单 worker 下
  收益不大，但 ADR-008 Open Q-7 提到多 worker 部署需 WAL，本层默认打开
  避免日后再迁。
- **schema_version 字段进表**：每条 row 带自己的 ``schema_version``，
  与本类构造时的 ``schema_version`` 不一致即视为 miss——不删 row（让
  ``invalidate_by_version`` 显式批量清理），避免读路径触发写。
- **stats 用 INTEGER 字段**：``hit_count`` 按 row 累计而非全局——日后
  做"hot key 分析"时直接 SQL 排序。全局 hit/miss/evict 走 process-local
  in-memory counter（不写 DB，避免每次 get 都 UPDATE）。
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path


class SQLiteCache:
    """通用 SQLite key→bytes 持久化缓存。

    Args:
        db_path: SQLite 文件路径。父目录会自动创建。
        table_name: 表名。本类支持多表共存于一个文件——不同 cache 用不同
            ``table_name`` 互不干扰。SQL 注入防御：``table_name`` 只允许
            ``[A-Za-z_][A-Za-z0-9_]*``，否则 ``ValueError``。
        schema_version: 本批缓存的 schema 版本。写入时记录到 row，读取时
            比对——不匹配视为 miss（不删 row）。升级 schema 时调用
            ``invalidate_by_version(old)`` 显式清理。

    用法：

        cache = SQLiteCache(Path(".cache/llm.db"), "llm_calls", "v1")
        val = cache.get("key123")
        if val is None:
            val = expensive_call()
            cache.set("key123", val)

    Note:
        - ``get`` 返 ``None`` 表示 miss（不存在 / version 不匹配）；存空
          bytes 用 ``b""`` 也合法且会命中。
        - 进程崩溃时 WAL 模式下未 commit 的写会回滚——本类每次 ``set``
          都 ``commit`` 一次，trade off 是高频写时性能下降。L2 是 LLM 调用
          后才写（频次远低于工具调用），可以接受。
    """

    # 进程级计数器加锁——sqlite3 conn 不跨线程，但 stats 计数本身要锁
    def __init__(
        self,
        db_path: Path,
        table_name: str,
        schema_version: str,
    ) -> None:
        if not _is_safe_identifier(table_name):
            raise ValueError(
                f"table_name must match [A-Za-z_][A-Za-z0-9_]*, got {table_name!r}"
            )
        self._db_path = Path(db_path)
        self._table = table_name
        self._schema_version = schema_version
        self._stats_lock = threading.Lock()
        self._hits = 0
        self._misses = 0
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_table()

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def get(self, key: str) -> bytes | None:
        """按 key 取 value；miss / version 不匹配返 None。

        命中时不更新 ``hit_count`` 字段——避免每次 get 都 UPDATE 拖慢
        热路径。如果后续要做 hot-key 分析再加 batch flush 机制。
        """
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT value, schema_version FROM {self._table} WHERE key = ?",
                (key,),
            ).fetchone()
        if row is None:
            with self._stats_lock:
                self._misses += 1
            return None
        value, row_version = row
        if row_version != self._schema_version:
            with self._stats_lock:
                self._misses += 1
            return None
        with self._stats_lock:
            self._hits += 1
        return bytes(value) if not isinstance(value, bytes) else value

    def get_many(self, keys: list[str]) -> dict[str, bytes]:
        """批量按 key 取 value；miss / version 不匹配不出现在结果里。

        和 ``get`` 一样不更新每行 hit_count，但会更新进程级 hit/miss 计数。
        一次连接内分批查询，避免几十万字书（上千章）逐 key 开连接的开销。
        """
        if not keys:
            return {}
        result: dict[str, bytes] = {}
        with self._connect() as conn:
            for i in range(0, len(keys), 500):
                chunk = keys[i : i + 500]
                placeholders = ",".join("?" * len(chunk))
                rows = conn.execute(
                    f"SELECT key, value, schema_version FROM {self._table} "
                    f"WHERE key IN ({placeholders})",
                    chunk,
                ).fetchall()
                for key, value, row_version in rows:
                    if row_version == self._schema_version:
                        result[key] = bytes(value) if not isinstance(value, bytes) else value
        with self._stats_lock:
            self._hits += len(result)
            self._misses += len(keys) - len(result)
        return result

    def set(self, key: str, value: bytes) -> None:
        """写入 (key, value)；同 key 已存在则覆盖（INSERT OR REPLACE）。"""
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                f"INSERT OR REPLACE INTO {self._table} "
                f"(key, value, schema_version, created_at, hit_count) "
                f"VALUES (?, ?, ?, ?, 0)",
                (key, sqlite3.Binary(value), self._schema_version, now),
            )
            conn.commit()

    def invalidate_by_version(self, old_version: str) -> int:
        """删除所有 ``schema_version == old_version`` 的 row。

        Returns:
            实际删除的行数。
        """
        with self._connect() as conn:
            cur = conn.execute(
                f"DELETE FROM {self._table} WHERE schema_version = ?",
                (old_version,),
            )
            conn.commit()
            return cur.rowcount

    def clear_all(self) -> None:
        """清空整张表 + 重置进程级 stats。主要给测试用。"""
        with self._connect() as conn:
            conn.execute(f"DELETE FROM {self._table}")
            conn.commit()
        with self._stats_lock:
            self._hits = 0
            self._misses = 0

    def stats(self) -> dict[str, int]:
        """返当前 hit / miss / size 快照。

        Returns:
            - ``hit`` / ``miss``：当前进程生命周期内累计（重启清零）
            - ``size``：表内总行数（含 schema_version 不匹配的过期 row）
        """
        with self._connect() as conn:
            (size,) = conn.execute(
                f"SELECT COUNT(*) FROM {self._table}"
            ).fetchone()
        with self._stats_lock:
            return {
                "hit": self._hits,
                "miss": self._misses,
                "size": int(size),
            }

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """每次开新 conn —— sqlite3 不允许跨线程共享 conn。"""
        conn = sqlite3.connect(self._db_path, timeout=10.0)
        # WAL 让读写并发更友好；ADR-008 Open Q-7 提到多 worker 部署需要。
        # journal_mode 是 file-level 设置，第一次设上去之后持久化在 DB 头。
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.DatabaseError:
            # 个别 fs（如 network mount）不支持 WAL；降级 default journal
            # 也能跑，只是并发读写性能差一点
            pass
        return conn

    def _ensure_table(self) -> None:
        """建表（IF NOT EXISTS），同时建 schema_version 索引便于版本失效。"""
        with self._connect() as conn:
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {self._table} ("
                f"key TEXT PRIMARY KEY, "
                f"value BLOB NOT NULL, "
                f"schema_version TEXT NOT NULL, "
                f"created_at TEXT NOT NULL, "
                f"hit_count INTEGER NOT NULL DEFAULT 0"
                f")"
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS "
                f"idx_{self._table}_schema_version "
                f"ON {self._table} (schema_version)"
            )
            conn.commit()


def _is_safe_identifier(name: str) -> bool:
    """SQL 标识符白名单校验——只允许字母数字下划线，首字符非数字。

    本层不走 parameterized table name（SQLite 不支持），所以 ``table_name``
    会直接拼进 SQL。白名单是唯一防注入手段。
    """
    if not name:
        return False
    if not (name[0].isalpha() or name[0] == "_"):
        return False
    return all(c.isalnum() or c == "_" for c in name)


__all__ = ["SQLiteCache"]
