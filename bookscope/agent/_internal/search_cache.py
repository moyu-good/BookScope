"""L1 ``search_chunks`` 结果缓存 —— Sprint 8 第一波。

ADR-008 D-1 第一层：把 ``ChunkRetrievalBackend.retrieve`` 的返回结果按
``(session_id, query_normalized, chapter_scope, character_filter, top_k)``
作 key 缓存到进程内 LRU。命中时跳过一次 BM25 加 vector search 调用。

### 设计要点（按 ADR-008 D-3 算法 c 简化版）

- **key 形态**：``f"{session_id}:{hash16}"``——前缀放 session_id 让
  ``LRUCache.clear_session`` 按前缀清场；hash16 是字段 tuple 的 sha256
  前 16 字符短指纹。
- **query 归一化**：``query.strip().lower()``。最低限度避免大小写与
  首尾空格的虚假 miss——agent 重生成的 query 偶尔会带尾空格或大小写
  不一致，这点 normalization 收益直接。
- **chapter_scope / character_filter 进 key**：原参数 tuple 序列化即可；
  character_filter 排序后再哈希，避免顺序差异导致 miss。
- **session_id 可空降级**：调用方拿不到 session_id（如测试场景或未来
  的 stateless 入口）时传 None，wrapper 直接调 backend 不走缓存。
  这条让 L1 改造对老调用方零侵入。

### 模块单例

模块级 ``_SEARCH_CACHE = LRUCache(max_size=1000)``——ADR-008 D-2
推荐值。如果未来要在测试里隔离 cache，``reset_search_cache()`` 公开。
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from bookscope.agent._internal.cache import LRUCache

if TYPE_CHECKING:
    from bookscope.agent.tools import ChunkRetrievalBackend
    from bookscope.agent.tools.schemas import ChunkMatch


# 模块级单例：进程内全局共享。ADR-008 D-2 上限 1000 条。
_SEARCH_CACHE = LRUCache(max_size=1000)


def _compute_search_cache_key(
    session_id: str,
    query: str,
    chapter_scope: tuple[int, int] | None,
    character_filter: list[str] | None,
    top_k: int,
) -> str:
    """按 ADR-008 D-3 算法 c 简化版算 cache key。

    流程：

    1. query 归一化：``strip().lower()``。
    2. character_filter 排序（避免顺序差异 miss）。
    3. 字段 tuple → JSON dump（``sort_keys=True``，``ensure_ascii=False``
       保中文原样）。
    4. sha256 取前 16 字符。
    5. 拼上 ``f"{session_id}:"`` 前缀。

    Returns:
        形如 ``"session_xyz:1a2b3c4d5e6f7890"`` 的字符串。
    """
    query_normalized = query.strip().lower()
    cf_sorted = sorted(character_filter) if character_filter else None
    cs_serialized = (
        [chapter_scope[0], chapter_scope[1]] if chapter_scope is not None else None
    )
    payload = {
        "q": query_normalized,
        "cs": cs_serialized,
        "cf": cf_sorted,
        "k": top_k,
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"{session_id}:{digest}"


def search_chunks_cached(
    backend: ChunkRetrievalBackend,
    *,
    session_id: str | None,
    query: str,
    chapter_scope: tuple[int, int] | None = None,
    character_filter: list[str] | None = None,
    top_k: int = 10,
) -> list[ChunkMatch]:
    """带 L1 缓存的 ``backend.retrieve`` 包装。

    Args:
        backend: 任意 ``ChunkRetrievalBackend`` 实现。
        session_id: 当前 book session id；None 表示降级不走缓存，直接
            transparent 调 backend。
        query / chapter_scope / character_filter / top_k: 同
            ``backend.retrieve``。

    Returns:
        ``list[ChunkMatch]``——命中时返缓存里同一个 list 引用（**调用方
        不应改它**，BookScope 现状是只读消费）；miss 时调 backend 后写入
        缓存再返。

    Note:
        - session_id 为 None：跳过 key 计算与 cache I/O，直 backend
          调用——保留这条降级让老入口无 session_id 时也能用。
        - 抛错不缓存：backend 异常直接向上抛，调用方现状的 try/except
          处理不变。
    """
    if session_id is None:
        return backend.retrieve(
            query=query,
            chapter_scope=chapter_scope,
            character_filter=character_filter,
            top_k=top_k,
        )

    key = _compute_search_cache_key(
        session_id, query, chapter_scope, character_filter, top_k,
    )
    cached = _SEARCH_CACHE.get(key)
    if cached is not None:
        return cached  # type: ignore[no-any-return]

    result = backend.retrieve(
        query=query,
        chapter_scope=chapter_scope,
        character_filter=character_filter,
        top_k=top_k,
    )
    _SEARCH_CACHE.set(key, result)
    return result


def clear_session_search_cache(session_id: str) -> int:
    """清掉一个 session 的所有 L1 缓存条目。

    Returns:
        实际清掉的条目数。供 ``BookSessionStore.delete`` 在 session
        销毁时调用。
    """
    return _SEARCH_CACHE.clear_session(session_id)


def get_search_cache_stats() -> dict[str, int]:
    """返 L1 缓存的 hit / miss / evict / size 快照。给 OPS dashboard 用。"""
    return _SEARCH_CACHE.stats()


def reset_search_cache() -> None:
    """清空 L1 缓存。主要给测试用——业务路径不该调它。"""
    _SEARCH_CACHE.clear_all()


def _get_search_cache_for_test() -> LRUCache:
    """暴露内部 LRUCache 单例给测试。下划线前缀表明非公共 API。"""
    return _SEARCH_CACHE
