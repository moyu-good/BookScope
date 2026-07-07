"""Book-level 卷层缓存(WP-hierarchical-spine,接 ADR-008 L3 思路)。

卷层(``chapter_arcs.build_arc_layer``)在逐章章脉上再切一趟 LLM,同一本书 + model 建一次就
不变 → 天然该缓存。照搬 ``chapter_spine_cache`` 的 book-level 缓存模式:同 SQLite 底座、同
db 文件、不同表(``chapter_arcs``)。

key 在章脉缓存键口径(``all_chunks_text_concat`` + model + genre)上**加一个 ``"arc"`` 标记 +
``min_chapters`` 阈值**——同一本书 + model + genre 复用同一条卷层;阈值变了(比如调短书门槛)
算不同 key、重建。缓存层任何意外都降级直建,绝不 break。

卷层可能是 ``None``(短书跳过)——**None 也缓存**(用哨兵),免得每次重开短书都白跑一趟守卫 c;
空列表 ``[]`` 不写(和章脉一致:免得把一次失败钉死)。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from bookscope.agent._internal.sqlite_cache import SQLiteCache
from bookscope.agent.chapter_arcs import ARC_SCHEMA_VERSION, build_arc_layer

logger = logging.getLogger(__name__)

ENV_DISABLED = "BOOKSCOPE_ARC_CACHE_DISABLED"
ENV_DB_PATH = "BOOKSCOPE_ARC_CACHE_DB_PATH"

_DEFAULT_DB_REL_PATH = ".bookscope_cache/kg_cache.db"
"""与 KG / 章脉缓存同库;不同表名 ``chapter_arcs`` 区分。清缓存 rm 一个文件清所有 book 级层。"""

# 短书跳过时缓存的哨兵——区分「建过、结果是 None(短书)」和「没建过(miss)」。
_NONE_SENTINEL = b'{"__arc_none__": true}'

_CACHE_LOCK = threading.Lock()
_CACHE_INSTANCE: SQLiteCache | None = None


def _default_db_path() -> Path:
    env_override = os.environ.get(ENV_DB_PATH)
    if env_override:
        return Path(env_override)
    # bookscope/agent/_internal/chapter_arc_cache.py → repo root = parents[3]
    return Path(__file__).resolve().parents[3] / _DEFAULT_DB_REL_PATH


def _get_cache() -> SQLiteCache:
    global _CACHE_INSTANCE
    if _CACHE_INSTANCE is not None:
        return _CACHE_INSTANCE
    with _CACHE_LOCK:
        if _CACHE_INSTANCE is None:
            _CACHE_INSTANCE = SQLiteCache(
                db_path=_default_db_path(),
                table_name="chapter_arcs",
                schema_version=ARC_SCHEMA_VERSION,
            )
        return _CACHE_INSTANCE


def _is_cache_disabled() -> bool:
    return os.environ.get(ENV_DISABLED, "").strip() == "1"


def _compute_arc_cache_key(
    *, all_chunks: list[dict], model: str, genre: str, min_chapters: int
) -> str:
    """按 ``(all_chunks_text_concat, model, genre, "arc", min_chapters)`` 算 key(24 字符 hex)。

    在章脉缓存键口径上加 ``layer="arc"`` 标记 + ``min_chapters``——和章脉共享 chunks/model/genre
    口径(同一本书天然对齐),但落在不同 key,不撞章脉那条。
    """
    chunks_text_concat = "\n".join(str(c.get("text", "")) for c in all_chunks)
    payload = {
        "all_chunks": chunks_text_concat,
        "model": model,
        "genre": genre,
        "layer": "arc",
        "min_chapters": min_chapters,
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _deserialize(cached: bytes) -> list[dict] | None:
    """反序列化缓存值:哨兵 → None(短书);合法 list → 卷层;其他 → 当 miss(返 None)。

    注意:短书的 None 和「反序列化失败当 miss」都返 None,但语义不同——调用方
    ``build_arc_layer_cached`` 命中路径直接返这个 None(短书);失败路径会 fall through 到重建。
    这里只负责解码;哨兵判定放在调用方,避免歧义。
    """
    if cached == _NONE_SENTINEL:
        return None
    spine = json.loads(cached.decode("utf-8"))
    return spine if isinstance(spine, list) else None


def build_arc_layer_cached(
    *,
    all_chunks: list[dict],
    model: str,
    genre: str,
    min_chapters: int,
    build_func: Callable[[], list[dict] | None],
) -> list[dict] | None:
    """带 book-level 缓存的卷层构建 wrapper。

    命中 → 直接返(短书哨兵 → None;list → 卷层);miss → 调 ``build_func`` 建一次、写缓存。
    缓存层任何意外都降级直调 ``build_func``,绝不 break。短书的 ``None`` 用哨兵缓存(免得每次
    重开短书都白跑守卫 c);空列表 ``[]`` 不写(免得把一次失败钉死成「这本书没卷层」)。
    """
    if _is_cache_disabled():
        return build_func()

    key: str | None = None
    try:
        cache = _get_cache()
        key = _compute_arc_cache_key(
            all_chunks=all_chunks, model=model, genre=genre, min_chapters=min_chapters
        )
        cached = cache.get(key)
        if cached is not None:
            if cached == _NONE_SENTINEL:
                return None  # 命中「短书跳过」哨兵
            try:
                arcs = _deserialize(cached)
                if arcs is not None:
                    return arcs
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                logger.warning("arc_cache: deserialize failed (%s); 当 miss", exc)
    except Exception as exc:  # noqa: BLE001 — 缓存层意外不能 break 构建
        logger.warning("arc_cache: lookup raised %s: %s; 绕过缓存", type(exc).__name__, exc)
        return build_func()

    arcs = build_func()

    if key is not None:
        # 短书(None)存哨兵;非空卷层存 JSON;空列表不写(免得钉死失败)。
        blob: bytes | None
        if arcs is None:
            blob = _NONE_SENTINEL
        elif arcs:
            blob = json.dumps(arcs, ensure_ascii=False).encode("utf-8")
        else:
            blob = None
        if blob is not None:
            try:
                _get_cache().set(key, blob)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "arc_cache: set raised %s: %s; miss 状态保留", type(exc).__name__, exc
                )

    return arcs


def get_or_build_arc_layer(
    *,
    spine: list[dict],
    all_chunks: list[dict],
    llm_client: Any,
    model: str,
    genre: str = "fiction",
    min_chapters: int | None = None,
    **build_kwargs: Any,
) -> list[dict] | None:
    """端点入口:命中缓存直接返卷层,miss 则 ``build_arc_layer`` 建一次并缓存。

    ``spine`` 是已建好的逐章章脉(调用方先 ``get_or_build_spine`` 拿到);``all_chunks`` 只用来
    算缓存键(与章脉缓存键口径对齐)。``min_chapters`` 不传走 ``build_arc_layer`` 的默认阈值,
    但缓存键要用**同一个值**——所以这里先落定再同时喂缓存键和构建。
    """
    from bookscope.agent.chapter_arcs import _ARC_MIN_CHAPTERS

    effective_min = _ARC_MIN_CHAPTERS if min_chapters is None else min_chapters
    return build_arc_layer_cached(
        all_chunks=all_chunks,
        model=model,
        genre=genre,
        min_chapters=effective_min,
        build_func=lambda: build_arc_layer(
            spine=spine,
            llm_client=llm_client,
            model=model,
            min_chapters=effective_min,
            **build_kwargs,
        ),
    )


def peek_arc_cache(
    *,
    all_chunks: list[dict],
    model: str,
    genre: str = "fiction",
    min_chapters: int | None = None,
) -> list[dict] | None:
    """只**看**这本书的卷层有没有缓存,有就返、没有返 None——**绝不构建**。

    给后台预建端点判「要不要建」用。key 与 ``get_or_build_arc_layer`` 完全同口径。
    注意:**短书哨兵和真 miss 都返 None**——peek 只区分「有可用卷层」vs「其他」,短书当作
    「不用建/无卷层」处理(和真 miss 对调用方是一样的动作:走章层)。缓存禁用 / 任何意外 → None。
    """
    if _is_cache_disabled():
        return None
    from bookscope.agent.chapter_arcs import _ARC_MIN_CHAPTERS

    effective_min = _ARC_MIN_CHAPTERS if min_chapters is None else min_chapters
    try:
        cache = _get_cache()
        key = _compute_arc_cache_key(
            all_chunks=all_chunks, model=model, genre=genre, min_chapters=effective_min
        )
        cached = cache.get(key)
        if cached is None or cached == _NONE_SENTINEL:
            return None
        arcs = json.loads(cached.decode("utf-8"))
        return arcs if isinstance(arcs, list) else None
    except Exception as exc:  # noqa: BLE001 — peek 失败当没缓存,绝不 break
        logger.warning("arc_cache: peek raised %s: %s; 当无缓存", type(exc).__name__, exc)
        return None


def clear_arc_cache() -> None:
    """清空整张卷层缓存表 + 重置 stats。给 CLI / 测试用。"""
    _get_cache().clear_all()


def get_arc_cache_stats() -> dict[str, int]:
    """返卷层缓存 hit / miss / size 快照。"""
    return _get_cache().stats()


def reset_arc_cache_singleton_for_test() -> None:
    """模块级单例重置为 None——给测试用。"""
    global _CACHE_INSTANCE
    with _CACHE_LOCK:
        _CACHE_INSTANCE = None


__all__ = [
    "ENV_DB_PATH",
    "ENV_DISABLED",
    "build_arc_layer_cached",
    "clear_arc_cache",
    "get_arc_cache_stats",
    "get_or_build_arc_layer",
    "peek_arc_cache",
    "reset_arc_cache_singleton_for_test",
]
