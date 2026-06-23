"""Book-level 章脉缓存(ADR-010 第5步,接 ADR-008 L3 思路)。

章脉(``chapter_spine.build_chapter_spine``)是整本一次精读的产出,建一次很贵(分维 × 几十段
LLM 调用),但书不变就不变 → 天然该缓存。建好缓存后,所有从章脉派生的视图(叙事曲线/节奏/
关系图/叙事流/时间线)重开书秒出、不再各跑全书。这是章脉转向"省下钱"真正落地的地方。

照搬 ``kg_book_cache`` 的 book-level 缓存模式:同 SQLite 底座、同 db 文件、不同表
(``chapter_spines``)。key = ``(all_chunks_text_concat, model, genre)`` hash;章脉是
list[dict] 原生 JSON,序列化比 KG 还简单。缓存层任何意外都降级直建,绝不 break。
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
from bookscope.agent.chapter_spine import SPINE_SCHEMA_VERSION, build_chapter_spine

logger = logging.getLogger(__name__)

ENV_DISABLED = "BOOKSCOPE_SPINE_CACHE_DISABLED"
ENV_DB_PATH = "BOOKSCOPE_SPINE_CACHE_DB_PATH"

_DEFAULT_DB_REL_PATH = ".bookscope_cache/kg_cache.db"
"""与 KG 缓存同库;不同表名 ``chapter_spines`` 区分。清缓存 rm 一个文件清所有 book 级层。"""

_CACHE_LOCK = threading.Lock()
_CACHE_INSTANCE: SQLiteCache | None = None


def _default_db_path() -> Path:
    env_override = os.environ.get(ENV_DB_PATH)
    if env_override:
        return Path(env_override)
    # bookscope/agent/_internal/chapter_spine_cache.py → repo root = parents[3]
    return Path(__file__).resolve().parents[3] / _DEFAULT_DB_REL_PATH


def _get_cache() -> SQLiteCache:
    global _CACHE_INSTANCE
    if _CACHE_INSTANCE is not None:
        return _CACHE_INSTANCE
    with _CACHE_LOCK:
        if _CACHE_INSTANCE is None:
            _CACHE_INSTANCE = SQLiteCache(
                db_path=_default_db_path(),
                table_name="chapter_spines",
                schema_version=SPINE_SCHEMA_VERSION,
            )
        return _CACHE_INSTANCE


def _is_cache_disabled() -> bool:
    return os.environ.get(ENV_DISABLED, "").strip() == "1"


def _compute_spine_cache_key(
    *, all_chunks: list[dict], model: str, genre: str
) -> str:
    """按 ``(all_chunks_text_concat, model, genre)`` 算 key(顺序敏感,24 字符 hex)。"""
    chunks_text_concat = "\n".join(str(c.get("text", "")) for c in all_chunks)
    payload = {"all_chunks": chunks_text_concat, "model": model, "genre": genre}
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def build_chapter_spine_cached(
    *,
    all_chunks: list[dict],
    model: str,
    genre: str,
    build_func: Callable[[], list[dict]],
) -> list[dict]:
    """带 book-level 缓存的章脉构建 wrapper。

    命中 → 直接返反序列化的章脉(跳过整本分维抽取);miss → 调 ``build_func`` 建一次、写缓存。
    缓存层任何意外(DB 锁/磁盘/key 计算)都降级直调 ``build_func``,绝不 break 章脉构建。
    空章脉(``[]``)不写缓存——避免把一次抽取失败钉死成"这本书没章脉"。
    """
    if _is_cache_disabled():
        return build_func()

    key: str | None = None
    try:
        cache = _get_cache()
        key = _compute_spine_cache_key(all_chunks=all_chunks, model=model, genre=genre)
        cached = cache.get(key)
        if cached is not None:
            try:
                spine = json.loads(cached.decode("utf-8"))
                if isinstance(spine, list):
                    return spine
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                logger.warning("spine_cache: deserialize failed (%s); 当 miss", exc)
    except Exception as exc:  # noqa: BLE001 — 缓存层意外不能 break 构建
        logger.warning("spine_cache: lookup raised %s: %s; 绕过缓存", type(exc).__name__, exc)
        return build_func()

    spine = build_func()

    if spine and key is not None:  # 空章脉不写,免得把失败钉死
        try:
            _get_cache().set(key, json.dumps(spine, ensure_ascii=False).encode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("spine_cache: set raised %s: %s; miss 状态保留", type(exc).__name__, exc)

    return spine


def get_or_build_spine(
    *,
    chunks: list[dict],
    llm_client: Any,
    model: str,
    genre: str = "fiction",
    **build_kwargs: Any,
) -> list[dict]:
    """端点入口:命中缓存直接返章脉,miss 则 ``build_chapter_spine`` 建一次并缓存。

    所有从章脉派生的视图端点都走这一个入口——重开同书命中缓存秒出,不再各跑全书。
    """
    return build_chapter_spine_cached(
        all_chunks=chunks,
        model=model,
        genre=genre,
        build_func=lambda: build_chapter_spine(
            chunks=chunks, llm_client=llm_client, model=model, genre=genre, **build_kwargs
        ),
    )


def clear_spine_cache() -> None:
    """清空整张章脉缓存表 + 重置 stats。给 CLI / 测试用。"""
    _get_cache().clear_all()


def get_spine_cache_stats() -> dict[str, int]:
    """返章脉缓存 hit / miss / size 快照。"""
    return _get_cache().stats()


def reset_spine_cache_singleton_for_test() -> None:
    """模块级单例重置为 None——给测试用。"""
    global _CACHE_INSTANCE
    with _CACHE_LOCK:
        _CACHE_INSTANCE = None


__all__ = [
    "ENV_DB_PATH",
    "ENV_DISABLED",
    "build_chapter_spine_cached",
    "clear_spine_cache",
    "get_or_build_spine",
    "get_spine_cache_stats",
    "reset_spine_cache_singleton_for_test",
]
