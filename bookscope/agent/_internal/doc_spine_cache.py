"""公文「文脉」缓存(1.6 红头文件 Phase 1)——章脉缓存的公文版。

文脉(``doc_spine.build_doc_spine``)是「一份公文精读一次出带证据结构」,建一次很贵
(头要素一次抽取 + 条款维分段并发 map-reduce),但同一份公文不变就不变 → 天然该缓存。
建好缓存后,所有从文脉派生的端点(单文件解读 / 跨文件视图)重开秒出、不再各跑一遍精读。

照搬 ``chapter_spine_cache`` 的 book-level 缓存模式:同 SQLite 底座、同 db 文件、不同表
(``doc_spines``)。key = ``(all_chunks_text_concat, model)`` hash——文脉不带 genre 维
(公文不分体裁,不像小说的 fiction/theory),所以 key 比章脉少一维。文脉是 dict(head +
clauses)原生 JSON,序列化直接走 ``json``。缓存层任何意外都降级直建,绝不 break。
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
from bookscope.agent.doc_spine import DOC_SPINE_SCHEMA_VERSION, build_doc_spine

logger = logging.getLogger(__name__)

ENV_DISABLED = "BOOKSCOPE_DOC_SPINE_CACHE_DISABLED"
ENV_DB_PATH = "BOOKSCOPE_DOC_SPINE_CACHE_DB_PATH"

_DEFAULT_DB_REL_PATH = ".bookscope_cache/kg_cache.db"
"""与 KG / 章脉缓存同库;不同表名 ``doc_spines`` 区分。清缓存 rm 一个文件清所有 book 级层。"""

_CACHE_LOCK = threading.Lock()
_CACHE_INSTANCE: SQLiteCache | None = None


def _default_db_path() -> Path:
    env_override = os.environ.get(ENV_DB_PATH)
    if env_override:
        return Path(env_override)
    # bookscope/agent/_internal/doc_spine_cache.py → repo root = parents[3]
    return Path(__file__).resolve().parents[3] / _DEFAULT_DB_REL_PATH


def _get_cache() -> SQLiteCache:
    global _CACHE_INSTANCE
    if _CACHE_INSTANCE is not None:
        return _CACHE_INSTANCE
    with _CACHE_LOCK:
        if _CACHE_INSTANCE is None:
            _CACHE_INSTANCE = SQLiteCache(
                db_path=_default_db_path(),
                table_name="doc_spines",
                schema_version=DOC_SPINE_SCHEMA_VERSION,
            )
        return _CACHE_INSTANCE


def _is_cache_disabled() -> bool:
    return os.environ.get(ENV_DISABLED, "").strip() == "1"


def _compute_doc_spine_cache_key(*, all_chunks: list[dict], model: str) -> str:
    """按 ``(all_chunks_text_concat, model)`` 算 key(顺序敏感,24 字符 hex)。

    文脉不带 genre 维(公文不分体裁),所以 key 比章脉少一维。
    """
    chunks_text_concat = "\n".join(str(c.get("text", "")) for c in all_chunks)
    payload = {"all_chunks": chunks_text_concat, "model": model}
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _is_empty_spine(spine: Any) -> bool:
    """这份文脉算不算「空」——头要素全留空 且 没抽到任何条款。

    文脉的 head 永远是全要素骨架(8 条,没抽到的也出一条空待核),所以不能光看 head 是否为
    list 判空。真「空」= 每个头要素 value 都空 且 clauses 空——这种是一次抽取失败,不写缓存
    (免得把失败钉死成「这份公文没文脉」,同章脉空章脉不缓存的纪律)。
    """
    if not isinstance(spine, dict):
        return True
    clauses = spine.get("clauses")
    if isinstance(clauses, list) and clauses:
        return False
    head = spine.get("head")
    if isinstance(head, list):
        for el in head:
            if isinstance(el, dict) and str(el.get("value", "")).strip():
                return False
    return True


def build_doc_spine_cached(
    *,
    all_chunks: list[dict],
    model: str,
    build_func: Callable[[], dict],
) -> dict:
    """带 book-level 缓存的文脉构建 wrapper。

    命中 → 直接返反序列化的文脉(跳过头要素抽取 + 条款维 map-reduce);miss → 调
    ``build_func`` 建一次、写缓存。缓存层任何意外(DB 锁/磁盘/key 计算)都降级直调
    ``build_func``,绝不 break 文脉构建。空文脉(全留空 + 没条款)不写缓存——避免把一次
    抽取失败钉死成「这份公文没文脉」。
    """
    if _is_cache_disabled():
        return build_func()

    key: str | None = None
    try:
        cache = _get_cache()
        key = _compute_doc_spine_cache_key(all_chunks=all_chunks, model=model)
        cached = cache.get(key)
        if cached is not None:
            try:
                spine = json.loads(cached.decode("utf-8"))
                if isinstance(spine, dict):
                    return spine
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                logger.warning("doc_spine_cache: deserialize failed (%s); 当 miss", exc)
    except Exception as exc:  # noqa: BLE001 — 缓存层意外不能 break 构建
        logger.warning(
            "doc_spine_cache: lookup raised %s: %s; 绕过缓存", type(exc).__name__, exc
        )
        return build_func()

    spine = build_func()

    if not _is_empty_spine(spine) and key is not None:  # 空文脉不写,免得把失败钉死
        try:
            _get_cache().set(key, json.dumps(spine, ensure_ascii=False).encode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "doc_spine_cache: set raised %s: %s; miss 状态保留", type(exc).__name__, exc
            )

    return spine


def get_or_build_doc_spine(
    *,
    chunks: list[dict],
    llm_client: Any,
    model: str,
    **build_kwargs: Any,
) -> dict:
    """端点入口:命中缓存直接返文脉,miss 则 ``build_doc_spine`` 建一次并缓存。

    所有从文脉派生的端点(单文件解读 / 跨文件视图)都走这一个入口——重开同份公文命中缓存
    秒出,跨文件视图逐份建文脉时同份公文也只精读一次。
    """
    return build_doc_spine_cached(
        all_chunks=chunks,
        model=model,
        build_func=lambda: build_doc_spine(
            chunks=chunks, llm_client=llm_client, model=model, **build_kwargs
        ),
    )


def peek_doc_spine_cache(*, chunks: list[dict], model: str) -> dict | None:
    """只**看**这份公文的完整文脉有没有缓存,有就返、没有返 None——**绝不构建**。

    给「公文结构」骨架鸟瞰用:先 peek,命中(说明逐条精读 / 办事清单已建过完整文脉)就直接用
    完整的(含条款,一并显示);miss 就退回只建 head 骨架(``build_doc_head_only``),把贵的条款
    map-reduce 留给用户真点逐条精读时。缓存禁用 / 任何意外 → 返 None(当没缓存,调用方建骨架)。
    """
    if _is_cache_disabled():
        return None
    try:
        cache = _get_cache()
        key = _compute_doc_spine_cache_key(all_chunks=chunks, model=model)
        cached = cache.get(key)
        if cached is None:
            return None
        spine = json.loads(cached.decode("utf-8"))
        return spine if isinstance(spine, dict) else None
    except Exception as exc:  # noqa: BLE001 — peek 失败当没缓存,绝不 break
        logger.warning("doc_spine_cache: peek raised %s: %s; 当无缓存", type(exc).__name__, exc)
        return None


def clear_doc_spine_cache() -> None:
    """清空整张文脉缓存表 + 重置 stats。给 CLI / 测试用。"""
    _get_cache().clear_all()


def get_doc_spine_cache_stats() -> dict[str, int]:
    """返文脉缓存 hit / miss / size 快照。"""
    return _get_cache().stats()


def reset_doc_spine_cache_singleton_for_test() -> None:
    """模块级单例重置为 None——给测试用。"""
    global _CACHE_INSTANCE
    with _CACHE_LOCK:
        _CACHE_INSTANCE = None


__all__ = [
    "ENV_DB_PATH",
    "ENV_DISABLED",
    "build_doc_spine_cached",
    "clear_doc_spine_cache",
    "get_doc_spine_cache_stats",
    "get_or_build_doc_spine",
    "peek_doc_spine_cache",
    "reset_doc_spine_cache_singleton_for_test",
]
