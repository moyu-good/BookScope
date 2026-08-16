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

# ── 单飞(single-flight):同一条章脉只让一个线程真建,其余等它建完再读缓存 ──────────
# 为什么:预热(prewarm 后台线程)和 viz 端点(FastAPI 线程池)都走 get_or_build_spine。冷启动
# 时缓存还空,两边都 miss → 各建一遍同一条章脉 = 双份 token + 双倍墙钟(直接踩"少 token / 2min"
# 目标的反面)。单飞让第二个及以后的调用等第一个的成果、不重复建。进程内多线程共享:一把锁 +
# 每 key 一个 Event。
_INFLIGHT_LOCK = threading.Lock()
_INFLIGHT: dict[str, threading.Event] = {}
_INFLIGHT_WAIT_TIMEOUT = 900.0
"""等"正在建的那条章脉"最多等多久(秒)——够几百万字超大书冷建;领头线程挂了等待方也不会永久卡。"""


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


def _read_cached(cache: SQLiteCache, key: str) -> list[dict] | None:
    """读并反序列化缓存的章脉;没有 / 坏 / 任何异常都当 miss 返 None(缓存层绝不 break 构建)。"""
    try:
        cached = cache.get(key)
        if cached is None:
            return None
        spine = json.loads(cached.decode("utf-8"))
        return spine if isinstance(spine, list) else None
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.warning("spine_cache: deserialize failed (%s); 当 miss", exc)
        return None
    except Exception as exc:  # noqa: BLE001 — 缓存层意外不能 break 构建
        logger.warning("spine_cache: read raised %s: %s; 当 miss", type(exc).__name__, exc)
        return None


def _write_cached(cache: SQLiteCache, key: str, spine: list[dict]) -> None:
    """写缓存;空章脉不写(不把失败钉死),任何异常只 warning、不抛(miss 状态保留、下次重建)。"""
    if not spine:
        return
    try:
        cache.set(key, json.dumps(spine, ensure_ascii=False).encode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("spine_cache: set raised %s: %s; miss 状态保留", type(exc).__name__, exc)


def _acquire_inflight(key: str) -> tuple[threading.Event, bool]:
    """登记"我要建这条 key":返 (event, is_leader)。leader 负责真建;非 leader 等这个 event。"""
    with _INFLIGHT_LOCK:
        event = _INFLIGHT.get(key)
        if event is not None:
            return event, False
        event = threading.Event()
        _INFLIGHT[key] = event
        return event, True


def _release_inflight(key: str, event: threading.Event) -> None:
    """建完(成功或失败)清登记 + 放行所有等待方(它们醒来重读缓存)。"""
    with _INFLIGHT_LOCK:
        if _INFLIGHT.get(key) is event:
            del _INFLIGHT[key]
    event.set()


def build_chapter_spine_cached(
    *,
    all_chunks: list[dict],
    model: str,
    genre: str,
    build_func: Callable[[], list[dict]],
) -> list[dict]:
    """带 book-level 缓存 + 单飞的章脉构建 wrapper。

    命中 → 直接返反序列化的章脉;miss → **单飞**建一次(同一 key 并发只建一遍,其余等它建完再读
    缓存)、写缓存。缓存层任何意外都降级直调 ``build_func``,绝不 break 构建。空章脉(``[]``)不写
    缓存——不把一次抽取失败钉死成"这本书没章脉"。

    单飞(2026-07-09):预热后台线程 + viz 端点冷启动时都 miss,原来各建一遍同一条章脉 = 双份
    token + 双倍墙钟。现在第二个及以后的调用等第一个的成果(接 2min 目标 / 少 token)。
    """
    if _is_cache_disabled():
        return build_func()

    try:
        cache = _get_cache()
        key = _compute_spine_cache_key(all_chunks=all_chunks, model=model, genre=genre)
    except Exception as exc:  # noqa: BLE001 — key / cache 初始化意外 → 直接建,不进单飞
        logger.warning("spine_cache: init raised %s: %s; 绕过缓存", type(exc).__name__, exc)
        return build_func()

    hit = _read_cached(cache, key)
    if hit is not None:
        return hit

    event, is_leader = _acquire_inflight(key)
    if not is_leader:
        # 有人在建同一条:等它(带超时防领头挂了永久卡),醒来重读缓存;读到用、没读到自己兜底建。
        event.wait(timeout=_INFLIGHT_WAIT_TIMEOUT)
        hit = _read_cached(cache, key)
        return hit if hit is not None else build_func()

    try:
        # 双检:从"首次 miss"到"抢到 leader"之间,可能有人刚建完并写了缓存。
        hit = _read_cached(cache, key)
        if hit is not None:
            return hit
        spine = build_func()
        _write_cached(cache, key, spine)
        return spine
    finally:
        _release_inflight(key, event)


def get_or_build_spine(
    *,
    chunks: list[dict],
    llm_client: Any,
    model: str,
    genre: str = "fiction",
    **build_kwargs: Any,
) -> list[dict]:
    """端点入口：按章粒度缓存，命中直接返章脉，只建缺失章并缓存。

    2026-08-16 改为按章缓存（连载稿子增量）：缓存键 = 每章内容哈希 + model + genre。
    改哪章只重算哪章（2-3 秒），其余章照常秒出；首次全量 = 全部章缺失，行为同旧整书
    构建（build_chapter_spine 内部仍按需分段）。

    所有从章脉派生的视图端点都走这一个入口——重开同书命中缓存秒出，不再各跑全书。
    """
    if _is_cache_disabled():
        return build_chapter_spine(
            chunks=chunks, llm_client=llm_client, model=model, genre=genre, **build_kwargs
        )
    try:
        cache = _get_cache()
    except Exception as exc:  # noqa: BLE001 — cache 初始化意外 → 直接建
        logger.warning("spine_cache: init raised %s: %s; 绕过缓存", type(exc).__name__, exc)
        return build_chapter_spine(
            chunks=chunks, llm_client=llm_client, model=model, genre=genre, **build_kwargs
        )

    groups = _chapter_groups(chunks)
    spine: list[dict[str, Any]] = []
    missing: list[tuple[int, list[dict]]] = []
    keys = [
        _compute_chapter_cache_key(chapter_chunks=ccs, chapter=ch, model=model, genre=genre)
        for ch, ccs in groups.items()
    ]
    try:
        cached_map = cache.get_many(keys)
    except Exception as exc:  # noqa: BLE001 — 批量读失败降级逐 key，仍不 break 构建
        logger.warning("spine_cache: batch read raised %s: %s; 降级逐 key", type(exc).__name__, exc)
        cached_map = {}
        for ch, ccs in groups.items():
            key = _compute_chapter_cache_key(chapter_chunks=ccs, chapter=ch, model=model, genre=genre)
            rec = _read_chapter_cached(cache, key)
            if rec is not None:
                cached_map[key] = rec
    for (ch, ccs), key in zip(groups.items(), keys):
        raw = cached_map.get(key)
        if raw is not None:
            try:
                rec = json.loads(raw.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                rec = None
            if isinstance(rec, dict):
                spine.append(rec)
            else:
                missing.append((ch, ccs))
        else:
            missing.append((ch, ccs))

    if missing:
        missing_chunks = [c for _, ccs in missing for c in ccs]
        built = build_chapter_spine(
            chunks=missing_chunks, llm_client=llm_client, model=model, genre=genre, **build_kwargs
        )
        for rec in built:
            ch = rec.get("chapter")
            if ch is None:
                continue
            ccs = next((ccs for cch, ccs in missing if cch == ch), None)
            if ccs is None:
                continue
            key = _compute_chapter_cache_key(chapter_chunks=ccs, chapter=ch, model=model, genre=genre)
            _write_chapter_cached(cache, key, rec)
            spine.append(rec)

    spine.sort(key=lambda r: r.get("chapter", 0))
    return spine


def peek_spine_cache(
    *, chunks: list[dict], model: str, genre: str = "fiction"
) -> list[dict] | None:
    """只**看**这本书的章脉有没有缓存，有就返**已建部分**、没有返 None——**绝不构建**。

    给后台预建端点判"要不要建"用：全部命中说明章脉已建过（整本书功能会秒出）；部分命中
    返回已建部分（渐进交付：报告可以先出已建章节）。缓存禁用 / 任何意外 → 返 None。
    key 与 ``get_or_build_spine`` 完全同口径（按章 hash），探的就是同一条章脉。
    """
    if _is_cache_disabled():
        return None
    try:
        cache = _get_cache()
    except Exception as exc:  # noqa: BLE001 — peek 失败当没缓存，绝不 break
        logger.warning("spine_cache: peek init raised %s: %s; 当无缓存", type(exc).__name__, exc)
        return None
    groups = _chapter_groups(chunks)
    keys = [
        _compute_chapter_cache_key(chapter_chunks=ccs, chapter=ch, model=model, genre=genre)
        for ch, ccs in groups.items()
    ]
    try:
        cached_map = cache.get_many(keys)
    except Exception as exc:  # noqa: BLE001 — 批量读失败降级逐 key
        logger.warning("spine_cache: peek batch read raised %s: %s; 降级逐 key", type(exc).__name__, exc)
        cached_map = {}
        for ch, ccs in groups.items():
            key = _compute_chapter_cache_key(chapter_chunks=ccs, chapter=ch, model=model, genre=genre)
            rec = _read_chapter_cached(cache, key)
            if rec is not None:
                cached_map[key] = rec
    spine: list[dict[str, Any]] = []
    for (ch, ccs), key in zip(groups.items(), keys):
        raw = cached_map.get(key)
        if raw is not None:
            try:
                rec = json.loads(raw.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                rec = None
            if isinstance(rec, dict):
                spine.append(rec)
    if not spine:
        return None
    spine.sort(key=lambda r: r.get("chapter", 0))
    return spine


def spine_build_progress(
    *, chunks: list[dict], model: str, genre: str = "fiction"
) -> dict:
    """缓存探测：这本书章脉已建到哪了（纯读缓存，绝不构建）。

    返回 ``{built, total, built_chapters, missing_chapters}``。渐进交付用：
    前端进度条 / 报告"已覆盖 N/M 章"。
    """
    groups = _chapter_groups(chunks)
    total = len(groups)
    built: list[int] = []
    missing: list[int] = []
    try:
        cache = _get_cache()
        keys = [
            _compute_chapter_cache_key(chapter_chunks=ccs, chapter=ch, model=model, genre=genre)
            for ch, ccs in groups.items()
        ]
        cached_map = cache.get_many(keys)
        for ch, key in zip(groups, keys):
            if cached_map.get(key) is not None:
                built.append(ch)
            else:
                missing.append(ch)
    except Exception as exc:  # noqa: BLE001 — 探测失败当全缺
        logger.warning("spine_cache: progress raised %s: %s; 当全缺", type(exc).__name__, exc)
        return {"built": 0, "total": total, "built_chapters": [], "missing_chapters": sorted(groups)}
    return {
        "built": len(built),
        "total": total,
        "built_chapters": sorted(built),
        "missing_chapters": sorted(missing),
    }


def _chapter_groups(chunks: list[dict]) -> dict[int, list[dict]]:
    """按章号分组（保序）；无章号 chunk 归 0（与旧整书 key 的容忍一致）。"""
    groups: dict[int, list[dict]] = {}
    for c in chunks:
        ch = c.get("chapter")
        if ch is None:
            ch = 0
        groups.setdefault(ch, []).append(c)
    return groups


def _compute_chapter_cache_key(
    *, chapter_chunks: list[dict], chapter: int, model: str, genre: str
) -> str:
    """按章缓存键：该章文本 + 章号 + model + genre（改章内容即失效）。"""
    text = "\n".join(str(c.get("text", "")) for c in chapter_chunks)
    payload = {"chapter": chapter, "text": text, "model": model, "genre": genre}
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return "ch:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _read_chapter_cached(cache: SQLiteCache, key: str) -> dict | None:
    """读并反序列化单章缓存；坏 / 异常当 miss。"""
    try:
        cached = cache.get(key)
        if cached is None:
            return None
        rec = json.loads(cached.decode("utf-8"))
        return rec if isinstance(rec, dict) else None
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.warning("spine_cache: chapter deserialize failed (%s); 当 miss", exc)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("spine_cache: chapter read raised %s: %s; 当 miss", type(exc).__name__, exc)
        return None


def _write_chapter_cached(cache: SQLiteCache, key: str, record: dict) -> None:
    """写单章缓存；空记录不写；异常只 warning。"""
    if not record:
        return
    try:
        cache.set(key, json.dumps(record, ensure_ascii=False).encode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("spine_cache: chapter set raised %s: %s; miss 状态保留", type(exc).__name__, exc)


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
    "peek_spine_cache",
    "spine_build_progress",
    "reset_spine_cache_singleton_for_test",
]
