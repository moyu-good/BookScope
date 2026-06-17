"""Book session store —— 内存 cache + 可选持久化后端。

每个 session 保存一个 :class:`R0BookAssembler` 实例；agent_ask 端点通
过 session_id 拿到已装配好的三个 backend。

### 两层结构（ADR-005 落地）

- **内存 cache**：进程内最快的访问路径；所有已 load 的 session 都挂在
  ``self._sessions`` 字典里。
- **可选 :class:`SessionStorage` 持久化后端**：进程退出后状态不丢。
  默认注入 :class:`JSONFileSessionStorage`（见
  :func:`bookscope.api.dependencies.get_book_session_store`）。单测
  可传 ``storage=None`` 走纯内存模式，行为与持久化前完全一致。

### 访问语义

- ``get(session_id)``：先查内存 → miss 时从 storage load 并 cache →
  storage 里也找不到则抛 :class:`BookSessionNotFound`。
- ``register(session_id, assembler)``：加入内存 + 同步写 storage。
- ``list_sessions()``：返回内存 + storage 合并后的去重列表。
- ``delete(session_id)``：两处都删。
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from bookscope.agent.backends.r0_assembler import R0BookAssembler

if TYPE_CHECKING:
    from bookscope.api.session_storage import SessionStorage


class BookSessionNotFound(Exception):
    """session_id 对应的 book session 不存在。

    由 API 层翻译为 HTTP 404，不走 AgentError 体系——它与 agent loop
    无关，只关乎 API 资源查找。
    """


class BookSessionStore:
    """线程安全的 book session 管理器（内存 cache + 可选持久化）。

    用途：在一次 API 进程的生命周期内，把"已装配好的 R0BookAssembler"
    挂到一个短串 key 上，让后续 agent/ask 请求只需带 session_id 即可
    复用同一本书的后端。传入 ``storage`` 时额外负责把 session 写到
    磁盘，进程重启后仍能取回。

    典型用法（不持久化）::

        store = BookSessionStore()
        store.register("book-42", assembler)
        assembler_again = store.get("book-42")

    典型用法（持久化）::

        storage = JSONFileSessionStorage(root=Path("data/sessions"))
        store = BookSessionStore(storage=storage)
        store.register("book-42", assembler)  # 同时写内存 + 磁盘

    Args:
        storage: 可选的持久化后端。``None`` 时等价于 "纯内存 store"，
            行为与 ADR-005 之前的旧实现完全一致（向后兼容）。
    """

    def __init__(
        self,
        storage: SessionStorage | None = None,
    ) -> None:
        self._sessions: dict[str, R0BookAssembler] = {}
        self._storage = storage
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # 基础操作
    # ------------------------------------------------------------------

    def register(self, session_id: str, assembler: R0BookAssembler) -> None:
        """把 assembler 挂到 session_id 下，并同步写 storage（若配置了）。

        同 id 重复注册会覆盖（内存 + storage 都覆盖）。

        Sprint 8 W3：注册成功后同步把 assembler 写入 L3 book 预热缓存
        （进程内 LRU 5 本 + 磁盘 pickle），下次切回直接命中跳过 ingest。
        """
        with self._lock:
            self._sessions[session_id] = assembler
        if self._storage is not None:
            # storage.save 放在锁外：JSON 序列化可能慢，不阻塞其它 session 的
            # 内存访问；storage 自身应保证线程安全（JSONFileSessionStorage
            # 用内部全局锁）。
            self._storage.save(session_id, assembler)
        # 局部 import 规避顶层模块循环依赖；warm_book 内部已 swallow 异常，
        # 不会让 register 失败。
        from bookscope.agent._internal.book_cache import warm_book

        warm_book(session_id, assembler)

    def get(self, session_id: str) -> R0BookAssembler:
        """按 id 取 assembler；内存 miss 时尝试 L3 缓存 → storage 懒加载。

        Sprint 8 W3 后查找顺序：内存 self._sessions → L3 book 预热缓存
        （进程内 LRU + 磁盘 pickle）→ storage.load（含 JSON 反序列化 +
        Pydantic 校验 + 必要时建 vector store）。L3 命中时跳过整条 ingest
        路径直接拿到一个可用的 assembler。

        Raises:
            BookSessionNotFound: 内存、L3、storage 都找不到。
        """
        with self._lock:
            assembler = self._sessions.get(session_id)
        if assembler is not None:
            return assembler

        # L3 book 预热缓存：命中即跳过 storage.load
        # 局部 import 规避顶层模块循环依赖
        from bookscope.agent._internal.book_cache import get_warmed_book

        warmed = get_warmed_book(session_id)
        if warmed is not None:
            with self._lock:
                cached = self._sessions.get(session_id)
                if cached is not None:
                    return cached
                self._sessions[session_id] = warmed.assembler
            return warmed.assembler

        if self._storage is not None:
            # load 抛 BookSessionNotFound 时直接透传；抛
            # SessionStorageCorrupted 时也让调用方感知（异常不吞）。
            loaded = self._storage.load(session_id)
            with self._lock:
                # 再检查一次 cache，避免并发 double-load 产生两份 assembler
                # 实例漂移（保留最早那份，确保同一 session 内 assembler 身份稳定）。
                cached = self._sessions.get(session_id)
                if cached is not None:
                    return cached
                self._sessions[session_id] = loaded
            # storage.load 成功后写入 L3——下次切回不再走 JSON 反序列化路径。
            # 这里特意放锁外：warm_book pickle 整个 assembler 可能慢（几 MB），
            # 不阻塞其它 session 的内存访问。warm_book 内部 swallow 异常，
            # 写失败不会让 get 失败。
            from bookscope.agent._internal.book_cache import warm_book

            warm_book(session_id, loaded)
            return loaded

        raise BookSessionNotFound(
            f"book session {session_id!r} not found; register it first."
        )

    def has(self, session_id: str) -> bool:
        """是否存在某 session。内存 hit 即返回 True；否则查 storage。"""
        with self._lock:
            if session_id in self._sessions:
                return True
        if self._storage is not None:
            return self._storage.exists(session_id)
        return False

    def list_sessions(self) -> list[str]:
        """返回内存 + storage 合并去重后的 session_id 列表（升序）。"""
        with self._lock:
            ids: set[str] = set(self._sessions.keys())
        if self._storage is not None:
            ids.update(self._storage.list_all())
        return sorted(ids)

    def delete(self, session_id: str) -> None:
        """从内存和 storage 里同时删掉；两处都不存在时静默返回。

        Sprint 8 W1：同时清掉 L1 ``search_chunks`` 缓存里这个 session 的
        全部条目——session 删除后那批缓存永远不会再被读到，留着浪费空间。
        Sprint 8 W3：同样清掉 L3 book 预热缓存（LRU + 磁盘 pickle）。
        """
        with self._lock:
            self._sessions.pop(session_id, None)
        if self._storage is not None:
            self._storage.delete(session_id)
        # 局部 import 避免顶层模块循环依赖（_internal 模块下游有 tools/
        # schemas，理论上无环但保险用懒 import）。
        from bookscope.agent._internal.book_cache import invalidate_book
        from bookscope.agent._internal.search_cache import (
            clear_session_search_cache,
        )

        clear_session_search_cache(session_id)
        invalidate_book(session_id)

    def get_metadata(self, session_id: str) -> dict[str, str]:
        """返回 session 的元数据 dict（``session_id`` / ``book_title`` /
        ``language`` / ``created_at`` / ``last_accessed_at``）。

        优先从 :class:`SessionStorage` 读 ``metadata.json``——它是元数据的
        权威来源（含 created_at / last_accessed_at 时间戳）。当 store 没
        挂 storage（纯内存模式）时，从内存里 cache 的 assembler 现场拼一
        份元数据，时间戳留空字符串占位（纯内存模式没有持久化语义，时间
        戳只在持久化路径下才有意义）。

        Raises:
            BookSessionNotFound: storage 与内存里都找不到该 session。
        """
        # 1. 优先从 storage 读权威 metadata.json
        if self._storage is not None and hasattr(self._storage, "read_metadata"):
            # SessionStorage Protocol 没有 read_metadata，只有 JSONFileSessionStorage
            # 实现了；其它后端走兜底 fallback。
            return self._storage.read_metadata(session_id)  # type: ignore[attr-defined]

        # 2. 退化：从内存 cache 现场拼一份
        with self._lock:
            assembler = self._sessions.get(session_id)
        if assembler is None:
            # 即便 storage 不支持 read_metadata，也要给一次 list_all 兜底——
            # storage 里有但内存里没有的 session 必须能拿到（虽然没有完整
            # metadata，至少不要假装"不存在"）。当前 SessionStorage Protocol
            # 没有抽象的 read_metadata，所以退化路径只能给最低限度的字段。
            if self._storage is not None and self._storage.exists(session_id):
                return {
                    "session_id": session_id,
                    "book_title": "",
                    "language": "unknown",
                    "created_at": "",
                    "last_accessed_at": "",
                }
            raise BookSessionNotFound(
                f"book session {session_id!r} not found; register it first."
            )

        book_text = assembler._book_text  # noqa: SLF001 — 装配层内部字段
        return {
            "session_id": session_id,
            "book_title": book_text.title,
            "language": getattr(book_text, "language", "unknown"),
            "created_at": "",
            "last_accessed_at": "",
        }

    def clear(self) -> None:
        """只清空内存 cache（不清 storage）。单测 / 应用关闭时使用。

        不动 storage 的理由：clear 在进程生命周期内被频繁调用（lifespan
        shutdown / 测试 teardown），每次都扫磁盘删 session 会让本地数据
        不可预期地丢失。若真想删磁盘，请显式调 :meth:`delete`。
        """
        with self._lock:
            self._sessions.clear()


# ---------------------------------------------------------------------------
# 模块级单例
# ---------------------------------------------------------------------------


_store_singleton: BookSessionStore | None = None
_singleton_lock = threading.Lock()


def get_book_session_store() -> BookSessionStore:
    """返回进程级 :class:`BookSessionStore` 单例（懒构造）。

    默认 storage 由 :mod:`bookscope.api.dependencies` 的
    ``get_book_session_store`` 覆盖注入 JSON 文件后端；本函数单独调用
    时（非 FastAPI 依赖注入路径）退化为 **纯内存**，与旧行为一致。

    FastAPI 路由通过 ``Depends(get_book_session_store)`` 拿到同一个
    实例；smoke test 也通过本函数注册预装配好的 session。
    """
    global _store_singleton
    if _store_singleton is None:
        with _singleton_lock:
            if _store_singleton is None:
                _store_singleton = BookSessionStore()
    return _store_singleton


def reset_book_session_store() -> None:
    """重置模块级单例（仅测试用）。

    单测里改完全局依赖注入后需要让下一次 ``get_book_session_store``
    重新走构造路径；生产代码**不得**调用本函数。
    """
    global _store_singleton
    with _singleton_lock:
        _store_singleton = None


__all__ = [
    "BookSessionNotFound",
    "BookSessionStore",
    "get_book_session_store",
    "reset_book_session_store",
]
