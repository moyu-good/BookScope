"""KG 抽取结果缓存 —— Sprint 6 第二步（chunk batch 调度之后接的第二波）。

### 为什么有这个模块

``MinimalKGExtractor._extract_from_batch`` 是 KG 抽取的最小调用单位——拿一
批 ``ChunkResult`` 调一次 LLM 抽角色清单。同一本书在不同 session、不同进
程下被重复 ingest 时（用户切回 / 重启进程 / 多人共享同一本公开书），同
样的 ``(chunks, system_prompt, model)`` 三元组会反复触发同一次 LLM 调
用——KG 抽取是整个 r2 ingest 链路里最贵的一段（按 anshi 量级要几十秒到
几分钟），命中即省。

### 与 L2 LLM 缓存（``llm_cache.py``）的关系

L2 ``invoke_client_cached`` 已经按 ``(model, system, tools, messages,
max_tokens)`` 做了一层 LLM 响应缓存。本层（按 ADR-008 命名上属 KG 专用
缓存）多加一层的理由：

- 粒度不同：L2 缓存的是单次 ``messages_create`` 调用，本层缓存的是单个
  ``_extract_from_batch`` 调用的**已解析返回值**（角色 entries list）——
  命中时直接跳过 ``extract_final_text`` + ``_parse_characters_json``，省
  一次 JSON parse 与一次响应解码。
- 失效语义独立：本层 schema_version 跟着 KG prompt 升级走（``v1`` →
  ``v2`` 时整张表 invalidate），不绑 L2 key 算法版本。
- L2 与本层命中是冗余不冲突：两层都命中时，本层先返、L2 不被调；只有
  本层 miss 时才走 LLM 调用路径，那里再过 L2。两层都进入持久化是有意
  设计——L2 跨业务（reviewer / agent loop / KG 抽取都共享 L2），本层
  KG 专属。

### 设计要点

- **存储后端 SQLite**：跟 L2 同 ``SQLiteCache`` 底座，进程重启不丢。
- **key 算法**：把 chunks 的文本拼接、system prompt、model 三元组合一
  个 dict，``sort_keys`` JSON dump 后 sha256 取前 24 字符。chunks 顺序
  敏感（KG entries 顺序影响 merge 时的"首次出现写法"取舍），所以**不**
  做集合归一化——chunks 顺序 / chunk index 都直接进 key。
- **序列化**：``_extract_from_batch`` 返 ``list[dict[str, Any]]``，全
  JSON-serializable（``name`` / ``canonical_name`` 是 str，
  ``key_chapter_indices`` 是 list[int]），直接 ``json.dumps``。不需要
  pickle。反序列化拿回 dict list，与原路径返值同形。
- **schema_version**：``v1``。日后改 prompt / key 算法时升版本，
  ``SQLiteCache`` 自动按 version miss 旧条目。

### 环境变量

- ``BOOKSCOPE_KG_CACHE_DISABLED=1``：跑测试或 baseline 对比时关掉缓存
- ``BOOKSCOPE_KG_CACHE_DB_PATH``：自定义 DB 路径；未设走默认
  ``<repo_root>/.bookscope_cache/kg_cache.db``

### 不在 scope

- 不做按 book / session 维度的批量 invalidate ——本层 key 不含 book id
  （chunks 文本本身唯一定位内容），用户重传同 chunks 命中即返
- 不做缓存过期 / TTL ——chunks + prompt + model 完全确定的产出永久不会
  随时间变化
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
from bookscope.models.schemas import ChunkResult

logger = logging.getLogger(__name__)

KG_CACHE_SCHEMA_VERSION = "v1"
"""key 算法 / 序列化格式版本。改算法或 prompt 时升 → 旧 row 自动 miss。"""

ENV_DISABLED = "BOOKSCOPE_KG_CACHE_DISABLED"
ENV_DB_PATH = "BOOKSCOPE_KG_CACHE_DB_PATH"

_DEFAULT_DB_REL_PATH = ".bookscope_cache/kg_cache.db"


def _default_db_path() -> Path:
    """默认 DB 路径：repo root 下 ``.bookscope_cache/kg_cache.db``。

    repo root 通过本文件位置反推（``_internal/kg_cache.py`` 上溯 3 级）。
    env ``BOOKSCOPE_KG_CACHE_DB_PATH`` 覆盖。
    """
    env_override = os.environ.get(ENV_DB_PATH)
    if env_override:
        return Path(env_override)
    # bookscope/agent/_internal/kg_cache.py → repo root 是 parents[3]
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / _DEFAULT_DB_REL_PATH


# 模块级单例 + lazy init 锁——避免 import 期就建 DB 文件
_CACHE_LOCK = threading.Lock()
_CACHE_INSTANCE: SQLiteCache | None = None


def _get_cache() -> SQLiteCache:
    """惰性拿 module-level SQLiteCache 单例。"""
    global _CACHE_INSTANCE
    if _CACHE_INSTANCE is not None:
        return _CACHE_INSTANCE
    with _CACHE_LOCK:
        if _CACHE_INSTANCE is None:
            _CACHE_INSTANCE = SQLiteCache(
                db_path=_default_db_path(),
                table_name="kg_extractions",
                schema_version=KG_CACHE_SCHEMA_VERSION,
            )
        return _CACHE_INSTANCE


def _is_cache_disabled() -> bool:
    """env flag 检查。设 ``"1"`` 关闭；其他值（含未设）视为 on。"""
    return os.environ.get(ENV_DISABLED, "").strip() == "1"


# ---------------------------------------------------------------------------
# key 算法
# ---------------------------------------------------------------------------


def _compute_kg_cache_key(
    *,
    chunks: list[ChunkResult],
    system_prompt: str,
    model: str,
) -> str:
    """按 ``(chunks, system_prompt, model)`` 三元组算 cache key。

    chunks 的 ``index`` 与 ``text`` 都进 key——index 因为 merge 时需要章
    节号还原，text 是 LLM 实际输入。其它字段（chapter / metadata）不进
    key：KG extractor 只读 text 喂 LLM、读 index 做 prompt header。

    Returns:
        24 字符 hex 串。
    """
    chunk_payload = [{"index": c.index, "text": c.text} for c in chunks]
    payload = {
        "chunks": chunk_payload,
        "system_prompt": system_prompt,
        "model": model,
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


# ---------------------------------------------------------------------------
# 序列化 / 反序列化
# ---------------------------------------------------------------------------


def _serialize_entries(entries: list[dict[str, Any]]) -> bytes:
    """把 entries 序列化成 bytes。

    ``_extract_from_batch`` 返 ``list[dict[str, Any]]``，全 JSON-serializable
    （key 为 str，value 为 str / list[int] / int），直接 ``json.dumps``。
    """
    return json.dumps(entries, ensure_ascii=False).encode("utf-8")


def _deserialize_entries(blob: bytes) -> list[dict[str, Any]]:
    """从 bytes 反序列化回 entries list。"""
    obj = json.loads(blob.decode("utf-8"))
    if not isinstance(obj, list):
        # 防御性：理论上写入端是 list，但万一磁盘 row 损坏（旧版本残留），
        # 当 miss 处理，让上层重抽
        raise ValueError("cached KG entries blob is not a list")
    return obj


# ---------------------------------------------------------------------------
# 对外 API
# ---------------------------------------------------------------------------


def extract_batch_cached(
    *,
    chunks: list[ChunkResult],
    system_prompt: str,
    model: str,
    extract_func: Callable[[], list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """带 KG 缓存的 ``_extract_from_batch`` wrapper。

    Args:
        chunks: 本 batch 的 chunk 列表。
        system_prompt: KG extractor 的 system prompt。
        model: 模型名。
        extract_func: 无参 callable，调起来等价于"原 ``_extract_from_batch``
            的 LLM 调用 + 解析"那一段。命中缓存时不会被调；miss 时调一
            次并把返值写回缓存。

    Returns:
        entries list —— 跟原 ``_extract_from_batch`` 返值同形。

    Note:
        - env ``BOOKSCOPE_KG_CACHE_DISABLED=1`` 全局关——直接调 ``extract_func``
          不查 / 不写缓存。
        - 缓存层任何意外（DB 锁、磁盘满、key 计算异常）都不能 break KG 抽
          取——降级到直调 ``extract_func``。
        - 写缓存失败也包死异常，缓存 miss 状态保留，不影响本次返值。
    """
    if _is_cache_disabled():
        return extract_func()

    try:
        cache = _get_cache()
        key = _compute_kg_cache_key(
            chunks=chunks,
            system_prompt=system_prompt,
            model=model,
        )
        cached_bytes = cache.get(key)
        if cached_bytes is not None:
            try:
                return _deserialize_entries(cached_bytes)
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
                logger.warning(
                    "kg_cache: deserialize failed (%s); ignoring cached row",
                    exc,
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "kg_cache: cache lookup raised %s: %s; bypassing cache",
            type(exc).__name__,
            exc,
        )
        return extract_func()

    entries = extract_func()

    try:
        cache.set(key, _serialize_entries(entries))
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "kg_cache: cache set raised %s: %s; cache miss persists",
            type(exc).__name__,
            exc,
        )

    return entries


def invalidate_by_schema_version(old_version: str) -> int:
    """整版本失效 —— prompt 升级时显式调用。

    Args:
        old_version: 要清掉的旧 schema_version 字符串。

    Returns:
        实际删除的行数。
    """
    return _get_cache().invalidate_by_version(old_version)


def clear_kg_cache() -> None:
    """清空整张 KG 缓存表 + 重置 stats。给 CLI 工具 / 测试用。"""
    _get_cache().clear_all()


def get_kg_cache_stats() -> dict[str, int]:
    """返 KG 缓存的 hit / miss / size 快照。给 OPS dashboard 用。"""
    return _get_cache().stats()


def reset_kg_cache_singleton_for_test() -> None:
    """把模块级单例重置为 None——给测试用。"""
    global _CACHE_INSTANCE
    with _CACHE_LOCK:
        _CACHE_INSTANCE = None


__all__ = [
    "ENV_DB_PATH",
    "ENV_DISABLED",
    "KG_CACHE_SCHEMA_VERSION",
    "clear_kg_cache",
    "extract_batch_cached",
    "get_kg_cache_stats",
    "invalidate_by_schema_version",
    "reset_kg_cache_singleton_for_test",
]
