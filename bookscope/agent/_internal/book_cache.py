"""L3 book 预热缓存 —— Sprint 8 W3。

ADR-008 D-1 第三层：把已装配好的 ``R0BookAssembler`` 实例 pickle 起来，
按 ``book_session_id`` 做 key 写两层缓存（进程内 LRU 5 本 + 磁盘 pickle
永久）。命中时跳过整条 ingest / JSON 反序列化 / Pydantic 校验 / vector
index lazy build 路径——session 切回时直接拿到一个可用的 assembler。

### 设计要点

- **缓存对象 = R0BookAssembler 整体 pickle**：ADR-005 的 JSON 持久化已经
  保证"重启不丢"，但首次切回时 ``JSONFileSessionStorage.load`` 仍要 (1)
  JSON 解码 (2) Pydantic 校验 (3) 必要时现场建 vector store。L3 把整个
  装配好的 assembler（含 chunks + KG + vector_store）pickle 进磁盘，命中
  时直接 ``pickle.loads`` 一步到位。
- **content_hash 防 stale**：用户重新上传同 session_id 但 book 内容变了
  时，新 assembler 的 ``book_text.raw_text`` sha256 与缓存里那份不同，
  ``warm_book`` 时会覆盖；读路径上一旦发现 hash 不匹配主动调
  ``invalidate_book``。content_hash 不进 cache key——key 还是
  ``book_session_id``——而是作为读取后比对字段。
- **两层结构（同 L1 / L2 mode）**：
  - L3a 进程内 LRU 5 本（``LRUCache(max_size=5)``）：跟 L1 用同一份
    ``cache.LRUCache`` 底座，stats 计数 / 线程锁全复用
  - L3b 磁盘 pickle：``.bookscope_cache/book_warmup/<book_session_id>.pkl``，
    永久不设 TTL；invalidate 时显式删
  - 读路径：先查 L3a，miss 查 L3b 并自动加入 L3a；都 miss 返 None
- **pickle 安全**：``.bookscope_cache/`` 是本地路径不接受外部 input；本
  模块只 pickle 自家产出的 dataclass + R0BookAssembler，反序列化只可能
  撞自家代码升级带来的 schema 漂移——撞了就当 miss 静默删旧文件让上层
  重 ingest。
- **进程级 stats**：累计 ``lru_hit`` / ``disk_hit`` / ``miss`` / ``lru_evict``
  四个数字 + 当前 LRU ``size``。L3a 自身的 LRUCache hit/miss/evict 跟 L3
  整体语义不一致（L3 整体 hit = L3a hit + L3b hit），所以本层维护自己的
  计数器而不直接转发 ``LRUCache.stats``。

### 环境变量

- ``BOOKSCOPE_BOOK_CACHE_DISABLED=1``：跑测试或对比 baseline 时关掉
- ``BOOKSCOPE_BOOK_CACHE_DIR``：自定义磁盘缓存目录；未设走默认
  ``<repo_root>/.bookscope_cache/book_warmup/``

### 不在 scope

- 不缓存 vector index 二进制文件——它已经被 pickle 进 R0BookAssembler 的
  ``_vector_store`` 字段（``SessionVectorStore`` 实例可 pickle）
- 不做磁盘大小上限——单本 anshi 量级 pickle 文件几 MB，5 本上限的 LRU 已
  约束进程内；磁盘永久保留是 ADR-005 session 持久化的同款语义
"""

from __future__ import annotations

import hashlib
import logging
import os
import pickle
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from bookscope.agent._internal.cache import LRUCache

if TYPE_CHECKING:
    from bookscope.agent.backends.r0_assembler import R0BookAssembler

logger = logging.getLogger(__name__)

ENV_DISABLED = "BOOKSCOPE_BOOK_CACHE_DISABLED"
ENV_DIR = "BOOKSCOPE_BOOK_CACHE_DIR"

_DEFAULT_DIR_REL = ".bookscope_cache/book_warmup"
_LRU_MAX_SIZE = 5
_PICKLE_PROTOCOL = pickle.HIGHEST_PROTOCOL

BOOK_CACHE_SCHEMA_VERSION = "v2"
"""L3 pickle 条目的 schema 版本。

v2（2026-06-10 WP3 Phase B）：章节映射语义从"检测序号"换成"真章号"。
旧 pickle 里的 assembler 还带旧章号的 chunks 与映射缓存，按新代码读会把
citation 引到错章——版本不匹配一律当 miss 删旧文件重建。v1 时代根本没有
这个字段（靠 pickle 反序列化失败兜底 schema 漂移），老条目缺字段同样判
miss，等价于 v1 → v2 整层失效。
"""


# ---------------------------------------------------------------------------
# WarmedBook dataclass
# ---------------------------------------------------------------------------


@dataclass
class WarmedBook:
    """L3 缓存条目的 wire 形态。

    pickle 序列化的最小单元；含 assembler 本体加防 stale 的 content_hash
    与时间戳。
    """

    assembler: R0BookAssembler
    """已装配好的 R0BookAssembler 实例（含 chunks / KG / vector_store）。"""

    content_hash: str
    """``sha256(book_text.raw_text)`` 全文 hex digest。读路径比对此字段，
    不一致即视为 stale 强制 invalidate。"""

    ingested_at: str
    """ISO-8601 UTC 时间戳，warm 写入时的瞬时；调试 / OPS dashboard 用。"""

    schema_version: str
    """写入时的 ``BOOK_CACHE_SCHEMA_VERSION``。读路径不匹配即当 miss——
    不给默认值，让老 pickle（无此字段）自然落到 getattr 的 None 分支。"""


# ---------------------------------------------------------------------------
# content_hash 计算
# ---------------------------------------------------------------------------


def compute_content_hash(assembler: R0BookAssembler) -> str:
    """按 ``book_text.raw_text`` 算 sha256 hex digest。

    选 raw_text 而非 chunks 序列化：(1) raw_text 是 ingest 唯一权威输入，
    ingest 算法升级（chunk 切分变更 / KG 抽取器换）也不影响它；(2) 算一次
    sha256 over raw_text 是 O(N) 单遍扫描，比把 chunks 全部 dump 再 hash 快
    一个量级。
    """
    raw = assembler._book_text.raw_text  # noqa: SLF001 — 装配层内部字段
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# 缓存目录解析
# ---------------------------------------------------------------------------


def _default_cache_dir() -> Path:
    """默认缓存目录：``<repo_root>/.bookscope_cache/book_warmup/``。

    repo_root 通过本文件位置反推（``_internal/book_cache.py`` 上溯 3 级）。
    env ``BOOKSCOPE_BOOK_CACHE_DIR`` 覆盖。
    """
    env_override = os.environ.get(ENV_DIR)
    if env_override:
        return Path(env_override)
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / _DEFAULT_DIR_REL


def _is_cache_disabled() -> bool:
    """env flag 检查。设 ``"1"`` 关闭；其他值（含未设）视为 on。"""
    return os.environ.get(ENV_DISABLED, "").strip() == "1"


# ---------------------------------------------------------------------------
# 模块级单例
# ---------------------------------------------------------------------------


_LRU = LRUCache(max_size=_LRU_MAX_SIZE)
_STATS_LOCK = threading.Lock()
_DISK_LOCK = threading.Lock()
_LRU_HITS = 0
_DISK_HITS = 0
_MISSES = 0
# LRU 自带的 evict 数转发到 L3 层 stats —— LRUCache.stats() 的 evict 是
# 包含外部 clear_session 的；本层不调 clear_session（只用 set / get），
# 所以 LRUCache 自身 evict 等同 L3 LRU 淘汰数。


def _safe_session_id(session_id: str) -> str:
    """拒绝路径穿越——pickle 文件名直接拼 session_id，必须先校验。

    与 ``JSONFileSessionStorage._session_dir`` 同款校验，保持一致。
    """
    if "/" in session_id or "\\" in session_id or ".." in session_id:
        raise ValueError(f"invalid session_id: {session_id!r}")
    if not session_id:
        raise ValueError("session_id cannot be empty")
    return session_id


def _pickle_path(session_id: str) -> Path:
    """返回 ``<cache_dir>/<session_id>.pkl`` 路径。"""
    return _default_cache_dir() / f"{_safe_session_id(session_id)}.pkl"


# ---------------------------------------------------------------------------
# 对外 API
# ---------------------------------------------------------------------------


def get_warmed_book(book_session_id: str) -> WarmedBook | None:
    """按 session_id 取 WarmedBook；两层都 miss 返 None。

    流程：

    1. env disabled → 直接返 None（不查任何层）
    2. 查 L3a 进程内 LRU；命中累计 lru_hit
    3. miss 查 L3b 磁盘 pickle；命中累计 disk_hit + 自动 promote 到 LRU
    4. 都 miss 累计 miss + 返 None

    Note:
        - 反序列化失败（schema 漂移 / 文件损坏）视为 miss 并静默删旧文件；
          上层会走完整 ingest 重新 warm
        - pickle 反序列化抛任何异常都吞掉，不让缓存层 break session 加载
    """
    global _LRU_HITS, _DISK_HITS, _MISSES

    if _is_cache_disabled():
        return None

    session_id = _safe_session_id(book_session_id)

    # L3a 进程内 LRU
    cached = _LRU.get(session_id)
    if cached is not None:
        with _STATS_LOCK:
            _LRU_HITS += 1
        return cached  # type: ignore[no-any-return]

    # L3b 磁盘 pickle
    pkl_path = _pickle_path(session_id)
    if not pkl_path.is_file():
        with _STATS_LOCK:
            _MISSES += 1
        return None

    try:
        with _DISK_LOCK, pkl_path.open("rb") as fp:
            warmed = pickle.load(fp)  # noqa: S301 — 本地受信路径
    except (
        pickle.UnpicklingError,
        EOFError,
        AttributeError,
        ImportError,
        ModuleNotFoundError,
        OSError,
    ) as exc:
        # schema 漂移 / 文件损坏 —— 当 miss + 静默删旧 pickle 让上层重 warm
        logger.warning(
            "book_cache: pickle load failed for %s (%s: %s); treating as miss",
            session_id, type(exc).__name__, exc,
        )
        try:
            pkl_path.unlink(missing_ok=True)
        except OSError:
            pass
        with _STATS_LOCK:
            _MISSES += 1
        return None

    if not isinstance(warmed, WarmedBook):
        # pickle 文件里塞了别的东西——按 miss 处理
        logger.warning(
            "book_cache: pickle for %s is not a WarmedBook (got %s); treating as miss",
            session_id, type(warmed).__name__,
        )
        try:
            pkl_path.unlink(missing_ok=True)
        except OSError:
            pass
        with _STATS_LOCK:
            _MISSES += 1
        return None

    if getattr(warmed, "schema_version", None) != BOOK_CACHE_SCHEMA_VERSION:
        # 旧版本条目（含 v1 时代无此字段的 pickle）——章节映射语义已变，
        # 当 miss 删旧文件让上层重 ingest（不删 session JSON，可逆）
        logger.info(
            "book_cache: pickle for %s has stale schema_version %r (want %r); "
            "treating as miss",
            session_id,
            getattr(warmed, "schema_version", None),
            BOOK_CACHE_SCHEMA_VERSION,
        )
        try:
            pkl_path.unlink(missing_ok=True)
        except OSError:
            pass
        with _STATS_LOCK:
            _MISSES += 1
        return None

    # promote 到 L3a
    _LRU.set(session_id, warmed)
    with _STATS_LOCK:
        _DISK_HITS += 1
    return warmed


def warm_book(book_session_id: str, assembler: R0BookAssembler) -> None:
    """把 assembler pickle 写两层缓存。

    Args:
        book_session_id: session 业务唯一 ID。
        assembler: 已装配完成的 R0BookAssembler 实例。

    Note:
        - content_hash 由本函数内部按 ``book_text.raw_text`` 计算，调用方
          不需要传
        - 同 session_id 第二次调用：内容 hash 不同时视为"用户重新上传同书"，
          先 invalidate 再写新——避免老 pickle 跟新 assembler 共存
        - 任何异常（磁盘满 / pickle 失败 / 目录创建失败）都 swallow 不抛——
          缓存写失败不该 break 主路径
    """
    if _is_cache_disabled():
        return

    try:
        session_id = _safe_session_id(book_session_id)
        content_hash = compute_content_hash(assembler)
        ingested_at = datetime.now(UTC).isoformat()
        warmed = WarmedBook(
            assembler=assembler,
            content_hash=content_hash,
            ingested_at=ingested_at,
            schema_version=BOOK_CACHE_SCHEMA_VERSION,
        )

        # 内容 hash 不同 → 旧条目先清掉（包括磁盘 pickle）
        existing = _LRU.get(session_id)
        if (
            isinstance(existing, WarmedBook)
            and existing.content_hash != content_hash
        ):
            invalidate_book(session_id)

        _LRU.set(session_id, warmed)

        pkl_path = _pickle_path(session_id)
        pkl_path.parent.mkdir(parents=True, exist_ok=True)
        with _DISK_LOCK:
            # 写临时文件 + rename 原子替换——避免半写文件被下次 load 撞上
            tmp_path = pkl_path.with_suffix(".pkl.tmp")
            with tmp_path.open("wb") as fp:
                pickle.dump(warmed, fp, protocol=_PICKLE_PROTOCOL)
            tmp_path.replace(pkl_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "book_cache: warm_book failed for %r (%s: %s); cache write skipped",
            book_session_id, type(exc).__name__, exc,
        )


def invalidate_book(book_session_id: str) -> None:
    """删 LRU + 磁盘 pickle 两层。

    幂等——条目不存在时静默返回。
    """
    if not book_session_id:
        return
    try:
        session_id = _safe_session_id(book_session_id)
    except ValueError:
        return

    # L3a: 用 LRUCache.clear_session 删——key 就是 session_id 本身，没前缀
    # 形态。改用直接 pop 内部 _store。LRUCache 没暴露单 key 删 API，本层
    # 手动操作内部状态。
    # 简洁做法：set 一个 sentinel 然后用 clear_session 不合适。直接调用
    # LRU 私有字段不优雅。考虑加个 LRUCache.pop(key) 是更通用的扩展——但
    # 本轮 surgical：用 ``clear_all`` 太重；用 prefix 也不对（key 就是
    # session_id 全字符串）。
    # 选项：在 LRU 上加一个 ``_store.pop`` 的薄包装函数 → 直接复用 __contains__。
    # 这里直接借 ``_store`` 私有属性：本层 + LRUCache 在同一个 _internal 包，
    # 算合理的 friend 边界。
    with _LRU._lock:  # noqa: SLF001 — 内部包友元
        _LRU._store.pop(session_id, None)  # noqa: SLF001

    # L3b: 磁盘 pickle
    pkl_path = _pickle_path(session_id)
    try:
        with _DISK_LOCK:
            pkl_path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning(
            "book_cache: invalidate pickle failed for %s: %s", session_id, exc,
        )


def clear_all() -> None:
    """清空两层缓存 + 重置 stats。给测试 / CLI 工具用。

    磁盘层只删本 cache_dir 下的 ``*.pkl`` 文件，不删整个目录（避免与其他
    Sprint 8 cache 共目录时误删）。
    """
    global _LRU_HITS, _DISK_HITS, _MISSES
    _LRU.clear_all()
    cache_dir = _default_cache_dir()
    if cache_dir.is_dir():
        with _DISK_LOCK:
            for pkl in cache_dir.glob("*.pkl"):
                try:
                    pkl.unlink()
                except OSError:
                    pass
            for tmp in cache_dir.glob("*.pkl.tmp"):
                try:
                    tmp.unlink()
                except OSError:
                    pass
    with _STATS_LOCK:
        _LRU_HITS = 0
        _DISK_HITS = 0
        _MISSES = 0


def stats() -> dict[str, int]:
    """返当前 L3 缓存的命中分布与 LRU 状态。

    Returns:
        dict 含 5 个 int 字段：
        - ``lru_hit``：L3a 进程内 LRU 累计命中
        - ``disk_hit``：L3b 磁盘 pickle 累计命中
        - ``miss``：两层都 miss 累计次数
        - ``size``：L3a 当前条目数（上限 5）
        - ``lru_evict``：L3a 因满载而淘汰的累计次数
    """
    lru_stats = _LRU.stats()
    with _STATS_LOCK:
        return {
            "lru_hit": _LRU_HITS,
            "disk_hit": _DISK_HITS,
            "miss": _MISSES,
            "size": lru_stats["size"],
            "lru_evict": lru_stats["evict"],
        }


__all__ = [
    "BOOK_CACHE_SCHEMA_VERSION",
    "ENV_DIR",
    "ENV_DISABLED",
    "WarmedBook",
    "clear_all",
    "compute_content_hash",
    "get_warmed_book",
    "invalidate_book",
    "stats",
    "warm_book",
]
