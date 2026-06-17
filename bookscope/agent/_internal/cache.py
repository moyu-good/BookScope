"""LRU 缓存基础抽象 —— ADR-008 三层缓存共用底座。

Sprint 8 第一波只实例化 L1 ``search_chunks`` 结果缓存（``search_cache.py``）。
本模块只提供通用的 LRU 容器加 stats 计数加 per-session 前缀清理三件套，
不绑定具体的 key 算法、value 形态、TTL 策略——那些放到上一层的具体
cache 模块里。

设计取舍：

- **OrderedDict 而非第三方 lru**：标准库够用，不引依赖；BYOK 原则下
  零外部依赖更顺。
- **单进程内存内**：ADR-008 D-2 推荐 L1 用 in-memory dict + LRU 上限
  1000 条；不跨进程、不持久化、重启丢可接受。
- **session_id 作 key 前缀**：``LRUCache.clear_session(session_id)``
  按前缀线性扫描整张表删——成本 O(n)，本层 n 上限 1000 条不构成压力。
  未来如果 n 上来再换 per-session 索引。
- **stats 计数读取无锁**：hit / miss / evict / size 四个数字 ``dict``
  返回快照，不暴露内部 OrderedDict 引用，避免外部误改。
- **线程安全**：用 ``threading.Lock`` 包 get / set / clear_session；
  Sprint 8 之后 FastAPI 多 worker 部署下走多进程而非多线程，单进程内
  线程锁够用。
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any


class LRUCache:
    """通用 LRU 缓存容器，带 stats 计数与 per-session 前缀清理。

    Args:
        max_size: 容器上限。命中时 key 移到末尾（最近使用），set 时若
            超过上限则 popitem(last=False) 淘汰最久未访问条目。下限 1。

    用法：

        cache = LRUCache(max_size=1000)
        val = cache.get(key)
        if val is None:
            val = expensive_compute(...)
            cache.set(key, val)

    Note:
        - get 返 None 表示 miss——这意味着不能缓存 None 值。本层不区分
          "key 不存在" vs "key 存在但 value=None"，调用方有 None 语义
          需求时自己包装一层（如存空 list ``[]`` 表示 "查过但没结果"）。
        - clear_session(session_id) 按 key 字符串前缀 ``f"{session_id}:"``
          扫描，所以调用方在生成 key 时必须把 session_id 作为前缀字段。
    """

    def __init__(self, max_size: int = 1000) -> None:
        if max_size < 1:
            raise ValueError(f"max_size must be >= 1, got {max_size}")
        self._max_size = max_size
        self._store: OrderedDict[str, Any] = OrderedDict()
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0
        self._evicts = 0

    def get(self, key: str) -> Any | None:
        """取 key 对应的 value；miss 时返 None。

        命中会把 key 移到末尾（最近使用），同时 ``hits`` 计数 +1；
        miss 时 ``misses`` 计数 +1。
        """
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
                self._hits += 1
                return self._store[key]
            self._misses += 1
            return None

    def set(self, key: str, value: Any) -> None:
        """写入 (key, value)；满载时淘汰最久未访问条目并计 evict。"""
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
                self._store[key] = value
                return
            self._store[key] = value
            if len(self._store) > self._max_size:
                self._store.popitem(last=False)
                self._evicts += 1

    def clear_session(self, session_id: str) -> int:
        """删除所有 ``key`` 以 ``f"{session_id}:"`` 起头的条目。

        Returns:
            实际删除的条目数。session 不存在 / 没缓存条目时返 0。

        设计：本操作不计 evict——evict 是 LRU 自然淘汰，clear_session
        是显式失效，两件事不混。
        """
        prefix = f"{session_id}:"
        with self._lock:
            victims = [k for k in self._store if k.startswith(prefix)]
            for k in victims:
                del self._store[k]
            return len(victims)

    def clear_all(self) -> None:
        """清空缓存与所有 stats 计数。主要给测试用。"""
        with self._lock:
            self._store.clear()
            self._hits = 0
            self._misses = 0
            self._evicts = 0

    def stats(self) -> dict[str, int]:
        """返当前 hit / miss / evict / size 快照。

        Returns:
            dict 含四个 int 字段：
            - ``hit``：累计命中次数
            - ``miss``：累计 miss 次数
            - ``evict``：累计 LRU 淘汰次数
            - ``size``：当前条目数
        """
        with self._lock:
            return {
                "hit": self._hits,
                "miss": self._misses,
                "evict": self._evicts,
                "size": len(self._store),
            }

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)

    def __contains__(self, key: str) -> bool:
        with self._lock:
            return key in self._store
