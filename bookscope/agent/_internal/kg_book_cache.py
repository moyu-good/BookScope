"""Book-level KG 缓存 —— Sprint 6 第四步（KG 持久化收尾）。

### 为什么有这层

``kg_cache.py`` 已经按 ``(chunks, system_prompt, model)`` 三元组缓存了
**单 batch** 的 LLM 抽取结果，让同 batch 的重复抽取直接命中。但
``MinimalKGExtractor.extract`` 出口的 ``BookKnowledgeGraph`` 自身——即
所有 batch 抽取后再 merge 出的最终 KG——并没有缓存。任何后端重读同一
本书，都要：

1. 把所有 chunks 切 batch；
2. 对每个 batch 查 batch 级缓存；
3. 把所有 batch 的 entries 收拢，跑 ``_merge_and_build_profiles``。

第 2 步 batch 全命中时单 batch 仍要做一次 SQLite get + JSON decode；第
3 步的 merge 在 anshi / mingchao 量级也是几十毫秒到上百毫秒的 Python
工作。在 ingest 完成后用户切回同书的常见路径下，这两步都是浪费——结果
完全可复用。

本层（"book-level KG 缓存"）按 ``(all_chunks_concat, system_prompt,
model)`` 整本 hash，命中时直接返已 deserialize 的 ``BookKnowledgeGraph``
对象，跳过整条 batch 切分 + 抽取 + merge 链路。两层并存：

- book-level 命中 → 跳过整本 KG 抽取
- book-level miss → 走 batch 级（``kg_cache.py``）继承 ``bdd9a20`` 的命中
  能力，省单 batch 的 LLM 调用

### 与 batch 级缓存（``kg_cache.py``）的关系

| 场景 | book-level | batch-level |
|------|------------|-------------|
| 用户切回同书同 chunks | hit | 不查（被跳过） |
| chunks 末尾追加章节（增量 ingest） | miss（chunks 改了） | 前 n1 个 batch hit |
| 同 chunks 跨书出现（极少见） | miss（整书 concat 不同） | 命中 |
| schema_version 升级 | 整张表 invalidate | 同样 invalidate |

两层的 schema_version 独立——本层用 ``v2``，batch 级仍是 ``v1``，但它
们走两张不同的 SQLite 表，互不影响。

### 设计要点

- **后端 SQLite**：跟 ``kg_cache.py`` 同 ``SQLiteCache`` 底座、同 db 文
  件（``.bookscope_cache/kg_cache.db``）、不同表（``kg_book_graphs``）。
  共享同一个 db 文件让 OPS 清缓存只 rm 一个文件就清两层。
- **key 算法**：把所有 chunks 的 ``text`` 拼接（``\n`` 分隔——和 BE 接续
  指引一致）、system_prompt、model 三个字段进 ``json.dumps`` ``sort_keys``
  再 sha256 取前 24 字符。chunks 顺序敏感（任何 chunk 顺序变动都该 miss，
  因为 merge 的 "首次出现写法" 取舍依赖顺序）。
- **chunks_concat 不含 index**：与 batch 级 key 不同——batch 级把
  ``index`` 进 key 是因为 prompt header 用 ``[chunk_index=N]``；本层
  key 是为 "重读同书" 服务，整书 chunks 的 index 实际上完全由 text 顺
  序决定（同书第二次 ingest 的 chunker 输出 index 与第一次一致），所以
  仅 text 序列足够定位。
- **序列化**：``BookKnowledgeGraph`` 是 Pydantic v2 model，
  ``model_dump`` 出 dict → ``json.dumps`` 出 bytes；反序列化
  ``model_validate_json`` 一步到位。所有嵌套字段（CharacterProfile /
  ChapterSummary / EmotionalStage / NarrativePoint 等）都是 Pydantic
  model，原生 JSON 友好——不需要 pickle。
- **schema_version**：``v2``。与 batch 级独立——本层 key 算法 / 序列化
  格式改动时升版本，对 batch 级零影响。

### 环境变量

- ``BOOKSCOPE_KG_BOOK_CACHE_DISABLED=1``：仅关 book-level；batch 级继续工作
- ``BOOKSCOPE_KG_BOOK_CACHE_DB_PATH``：自定义 DB 路径；未设走默认
  ``<repo_root>/.bookscope_cache/kg_cache.db``（与 batch 级同库不同表）

### 不在 scope

- 不做按 book_title 维度的批量 invalidate ——本层 key 不绑 book id，跨
  书共享 cache 表，没必要按 book 清；要清整张表用 ``clear_book_kg_cache``。
- 不做 TTL ——chunks + prompt + model 完全确定的产出永久不变。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from collections.abc import Callable
from pathlib import Path

from bookscope.agent._internal.sqlite_cache import SQLiteCache
from bookscope.models.schemas import BookKnowledgeGraph, ChunkResult

logger = logging.getLogger(__name__)

KG_BOOK_CACHE_SCHEMA_VERSION = "v2"
"""key 算法 / 序列化格式版本。改算法或 BookKnowledgeGraph schema 时升版本。

v2（2026-06-10 WP3 Phase B）：章节映射语义从"检测序号"换成"真章号"——
chunk header 与 KG 里的章节索引都跟着变。旧条目按新代码读会拿到旧章号
口径的 KG，版本不匹配一律 miss 重建；旧 row 不删，可逆。
"""

ENV_DISABLED = "BOOKSCOPE_KG_BOOK_CACHE_DISABLED"
ENV_DB_PATH = "BOOKSCOPE_KG_BOOK_CACHE_DB_PATH"

_DEFAULT_DB_REL_PATH = ".bookscope_cache/kg_cache.db"
"""与 batch 级缓存同库；不同表名 ``kg_book_graphs`` 区分。"""


def _default_db_path() -> Path:
    """默认 DB 路径：repo root 下 ``.bookscope_cache/kg_cache.db``（同 batch 级）。

    env ``BOOKSCOPE_KG_BOOK_CACHE_DB_PATH`` 覆盖。
    """
    env_override = os.environ.get(ENV_DB_PATH)
    if env_override:
        return Path(env_override)
    # bookscope/agent/_internal/kg_book_cache.py → repo root = parents[3]
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / _DEFAULT_DB_REL_PATH


_CACHE_LOCK = threading.Lock()
_CACHE_INSTANCE: SQLiteCache | None = None


def _get_cache() -> SQLiteCache:
    """惰性拿 book-level cache 的模块级单例。"""
    global _CACHE_INSTANCE
    if _CACHE_INSTANCE is not None:
        return _CACHE_INSTANCE
    with _CACHE_LOCK:
        if _CACHE_INSTANCE is None:
            _CACHE_INSTANCE = SQLiteCache(
                db_path=_default_db_path(),
                table_name="kg_book_graphs",
                schema_version=KG_BOOK_CACHE_SCHEMA_VERSION,
            )
        return _CACHE_INSTANCE


def _is_cache_disabled() -> bool:
    """env flag 检查。设 ``"1"`` 关本层；其他值（含未设）视为 on。"""
    return os.environ.get(ENV_DISABLED, "").strip() == "1"


# ---------------------------------------------------------------------------
# key 算法
# ---------------------------------------------------------------------------


def _compute_kg_book_cache_key(
    *,
    all_chunks: list[ChunkResult],
    system_prompt: str,
    model: str,
) -> str:
    """按 ``(all_chunks_text_concat, system_prompt, model)`` 算 cache key。

    chunks 文本以 ``\\n`` 拼接进 hash —— 顺序敏感。与 batch 级 key 不同的
    是：本层不把 ``index`` 也喂 hash —— 整书层面 text 序列已足够定位。

    Returns:
        24 字符 hex 串。
    """
    chunks_text_concat = "\n".join(c.text for c in all_chunks)
    payload = {
        "all_chunks": chunks_text_concat,
        "system_prompt": system_prompt,
        "model": model,
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


# ---------------------------------------------------------------------------
# 序列化 / 反序列化
# ---------------------------------------------------------------------------


def _serialize_book_kg(kg: BookKnowledgeGraph) -> bytes:
    """把 ``BookKnowledgeGraph`` 序列化成 bytes。

    走 Pydantic v2 ``model_dump`` → ``json.dumps``。``BookKnowledgeGraph``
    所有字段（含嵌套 CharacterProfile / EmotionalStage / NarrativePoint
    等）都是 Pydantic model + JSON-serializable，原生兼容。
    """
    return json.dumps(kg.model_dump(), ensure_ascii=False).encode("utf-8")


def _deserialize_book_kg(blob: bytes) -> BookKnowledgeGraph:
    """从 bytes 反序列化回 ``BookKnowledgeGraph``。

    用 ``model_validate_json`` 一步到位——内部走 Pydantic 校验，保证字段
    类型完全恢复。

    Raises:
        ValueError: blob 损坏 / 不是合法 BookKnowledgeGraph JSON。
            包装成 ``ValueError`` 让上层（``extract_book_kg_cached``）当
            miss 处理，触发重抽。
    """
    try:
        return BookKnowledgeGraph.model_validate_json(blob.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        raise ValueError(
            f"cached BookKnowledgeGraph blob is not valid: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# 对外 API
# ---------------------------------------------------------------------------


def extract_book_kg_cached(
    *,
    all_chunks: list[ChunkResult],
    system_prompt: str,
    model: str,
    extract_func: Callable[[], BookKnowledgeGraph],
) -> BookKnowledgeGraph:
    """带 book-level 缓存的 ``MinimalKGExtractor.extract`` wrapper。

    Args:
        all_chunks: 本书的全部 chunks（按 chunker 输出顺序）。
        system_prompt: KG extractor 的 system prompt。
        model: 模型名。
        extract_func: 无参 callable，调起来等价于"原 ``extract`` 的 batch
            切分 + LLM 抽取 + merge 全套"。命中缓存时不被调；miss 时调一
            次并把返值写回缓存。

    Returns:
        ``BookKnowledgeGraph`` —— 跟原 ``extract`` 返值同形（命中时是
        反序列化重建的对象，字段值完全一致）。

    Note:
        - env ``BOOKSCOPE_KG_BOOK_CACHE_DISABLED=1`` 全局关本层——直接调
          ``extract_func``，**不影响 batch 级缓存继续工作**。
        - 缓存层任何意外（DB 锁、磁盘满、key 计算异常）都不能 break KG
          抽取——降级到直调 ``extract_func``。
        - 写缓存失败也包死异常，缓存 miss 状态保留，不影响本次返值。
    """
    if _is_cache_disabled():
        return extract_func()

    try:
        cache = _get_cache()
        key = _compute_kg_book_cache_key(
            all_chunks=all_chunks,
            system_prompt=system_prompt,
            model=model,
        )
        cached_bytes = cache.get(key)
        if cached_bytes is not None:
            try:
                return _deserialize_book_kg(cached_bytes)
            except ValueError as exc:
                logger.warning(
                    "kg_book_cache: deserialize failed (%s); treating as miss",
                    exc,
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "kg_book_cache: cache lookup raised %s: %s; bypassing cache",
            type(exc).__name__,
            exc,
        )
        return extract_func()

    kg = extract_func()

    try:
        cache.set(key, _serialize_book_kg(kg))
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "kg_book_cache: cache set raised %s: %s; cache miss persists",
            type(exc).__name__,
            exc,
        )

    return kg


def invalidate_by_schema_version(old_version: str) -> int:
    """整版本失效 —— BookKnowledgeGraph schema 升级时显式调用。

    Args:
        old_version: 要清掉的旧 schema_version 字符串。

    Returns:
        实际删除的行数。
    """
    return _get_cache().invalidate_by_version(old_version)


def clear_book_kg_cache() -> None:
    """清空整张 book-level 缓存表 + 重置 stats。给 CLI 工具 / 测试用。"""
    _get_cache().clear_all()


def get_book_kg_cache_stats() -> dict[str, int]:
    """返 book-level 缓存的 hit / miss / size 快照。"""
    return _get_cache().stats()


def reset_book_kg_cache_singleton_for_test() -> None:
    """把模块级单例重置为 None——给测试用。"""
    global _CACHE_INSTANCE
    with _CACHE_LOCK:
        _CACHE_INSTANCE = None


__all__ = [
    "ENV_DB_PATH",
    "ENV_DISABLED",
    "KG_BOOK_CACHE_SCHEMA_VERSION",
    "clear_book_kg_cache",
    "extract_book_kg_cached",
    "get_book_kg_cache_stats",
    "invalidate_by_schema_version",
    "reset_book_kg_cache_singleton_for_test",
]
