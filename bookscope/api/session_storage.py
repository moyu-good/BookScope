"""Book session 持久化层（ADR-005 方案 A）。

定义 :class:`SessionStorage` Protocol 与基于本地文件系统的默认实现
:class:`JSONFileSessionStorage`。

### 目录结构

每个 session 一个独立目录，形如::

    <root>/<session_id>/
      metadata.json       # {session_id, book_title, language, created_at, last_accessed_at}
      book_text.json      # BookText.model_dump()
      chunks.json         # {"chunks": [...ChunkResult.model_dump()]}
      kg.json             # BookKnowledgeGraph.model_dump()
      vector_index/       # SessionVectorStore.save_to_dir 产出
        manifest.json     # 版本号 / chunk 数 / has_vector / 保存时的
                          # embedding provider 名称和维度
        chunks.json       # 索引内部持有的 ChunkResult 副本（自包含）
        bm25.pkl          # BM25Okapi pickle
        faiss.index       # FAISS 二进制（仅 has_vector=True 时存在）

### vector_index 的行为

``SessionVectorStore.load_from_dir`` 会校验 manifest 里记录的 embedding
provider 名称与当前环境匹配；不匹配或加载失败会被本模块降级成
``vector_store=None``，``agent_ask`` 路由会据此回 400 并提示作者重建
索引，而不是静默用另一个模型回答查询。

### 文件可见性是资产

作者可以直接打开 ``kg.json`` 人眼审阅 KG 提取质量（ADR-005 明确列出的
开发期调试优势）。任何存储格式变更必须保证 JSON 仍是"打开就能看"的
格式，不要上 pickle / msgpack 等二进制。
"""

from __future__ import annotations

import json
import logging
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from bookscope.agent.backends.r0_assembler import R0BookAssembler
from bookscope.models.schemas import (
    BookKnowledgeGraph,
    BookText,
    ChunkResult,
)
from bookscope.store.vector_store import (
    SessionVectorStore,
    VectorStoreLoadError,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------


class SessionStorageError(Exception):
    """``SessionStorage`` 层所有错误的根基类。"""


class SessionStorageCorrupted(SessionStorageError):
    """本地文件损坏或 schema 不匹配，无法还原 session。

    包括 JSON parse 失败、必要文件缺失、Pydantic 校验失败等。上层可据
    此决定是否删除该 session 目录。
    """


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class SessionStorage(Protocol):
    """Book session 持久化后端抽象。

    实现方负责把 :class:`R0BookAssembler` 的内部状态无损序列化到后端
    存储，并能反向还原。所有方法都是**同步**的——session 的 save / load
    频率很低（每 session 上传时 save 一次、重启后首次访问时 load 一次），
    不必异步化。
    """

    def save(self, session_id: str, assembler: R0BookAssembler) -> None:
        """把 ``assembler`` 持久化到 ``session_id`` 名下。重复调用应覆盖旧数据。"""
        ...

    def load(self, session_id: str) -> R0BookAssembler:
        """按 id 反序列化出一个 :class:`R0BookAssembler`。

        Raises:
            BookSessionNotFound: session_id 不存在。
            SessionStorageCorrupted: 文件损坏 / schema 不匹配。
        """
        ...

    def list_all(self) -> list[str]:
        """返回存储里所有已知的 session_id 列表。"""
        ...

    def delete(self, session_id: str) -> None:
        """删除 session。不存在时静默返回（不抛错）。"""
        ...

    def exists(self, session_id: str) -> bool:
        """session 是否存在。不抛错，只返回布尔。"""
        ...


# ---------------------------------------------------------------------------
# JSONFileSessionStorage
# ---------------------------------------------------------------------------


_METADATA_FILE = "metadata.json"
_BOOK_TEXT_FILE = "book_text.json"
_CHUNKS_FILE = "chunks.json"
_KG_FILE = "kg.json"
_VECTOR_INDEX_DIR = "vector_index"


class JSONFileSessionStorage:
    """基于本地 JSON 文件的 SessionStorage 实现（ADR-005 方案 A）。

    Args:
        root: 数据根目录；不存在时 ``save`` 第一次写入会自动创建。
            测试可传 ``tmp_path``；生产默认由 ``get_book_session_store``
            注入 ``Path("data/sessions")``。
    """

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)
        # 一把 per-session 的并发锁：按 session_id 分桶，粒度比全局锁细；
        # 本轮直接用一个全局锁，等到并发压力出现再细化——单用户场景不紧迫。
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # SessionStorage Protocol 实现
    # ------------------------------------------------------------------

    def save(self, session_id: str, assembler: R0BookAssembler) -> None:
        """把 assembler 的内部状态写到 ``<root>/<session_id>/``。"""
        if not session_id:
            raise ValueError("session_id cannot be empty")

        session_dir = self._session_dir(session_id)
        with self._lock:
            session_dir.mkdir(parents=True, exist_ok=True)

            book_text = assembler._book_text  # noqa: SLF001 — 装配层内部字段
            chunks = assembler._chunks  # noqa: SLF001
            kg = assembler._kg  # noqa: SLF001

            now = _utc_now_iso()
            # metadata 里的 created_at 尽量复用旧值；若旧文件缺失或坏掉就用 now。
            created_at = _read_created_at_or(session_dir / _METADATA_FILE, now)
            metadata = {
                "session_id": session_id,
                "book_title": book_text.title,
                "language": getattr(book_text, "language", "unknown"),
                "created_at": created_at,
                "last_accessed_at": now,
            }
            # WP3 Phase A：upload 链路会把章节检测指标挂在 assembler 上
            # （books.py 的 ``assembler.chapter_detection_stats``）；有就随
            # 元数据落盘，没有（老路径 / 手工装配）就不写——读侧都按可缺
            # 字段处理。
            chapter_detection = getattr(assembler, "chapter_detection_stats", None)
            if chapter_detection is not None:
                metadata["chapter_detection"] = chapter_detection

            _write_json(session_dir / _METADATA_FILE, metadata)
            _write_json(
                session_dir / _BOOK_TEXT_FILE,
                book_text.model_dump(),
            )
            _write_json(
                session_dir / _CHUNKS_FILE,
                {"chunks": [c.model_dump() for c in chunks]},
            )
            _write_json(session_dir / _KG_FILE, kg.model_dump())

            vector_index_dir = session_dir / _VECTOR_INDEX_DIR
            vector_store = assembler._vector_store  # noqa: SLF001
            if vector_store is not None:
                # Wipe any stale snapshot from prior save so a mid-write
                # crash last time does not poison this one.
                shutil.rmtree(vector_index_dir, ignore_errors=True)
                vector_index_dir.mkdir(exist_ok=True)
                try:
                    vector_store.save_to_dir(vector_index_dir)
                except Exception as exc:  # noqa: BLE001
                    # Persistence failure must not block session save —
                    # the authoritative state (BookText/chunks/KG) is
                    # already on disk and the index can be rebuilt from
                    # chunks. Clear partial index files so load falls
                    # back to None cleanly instead of hitting a half file.
                    logger.warning(
                        "failed to persist vector index for %s: %s",
                        session_id, exc,
                    )
                    shutil.rmtree(vector_index_dir, ignore_errors=True)
                    vector_index_dir.mkdir(exist_ok=True)
            else:
                # No vector store to save. Reset the directory so stale
                # manifest from a previous save with vector store does
                # not mislead the next load.
                shutil.rmtree(vector_index_dir, ignore_errors=True)
                vector_index_dir.mkdir(exist_ok=True)

    def load(self, session_id: str) -> R0BookAssembler:
        """从 ``<root>/<session_id>/`` 反序列化出一个 R0BookAssembler。"""
        # 局部 import 规避循环依赖：book_sessions 里 import session_storage，
        # 如果顶层 import 反过来会出循环。
        from bookscope.api.book_sessions import BookSessionNotFound

        session_dir = self._session_dir(session_id)
        if not session_dir.is_dir():
            raise BookSessionNotFound(
                f"book session {session_id!r} not found in storage"
            )

        try:
            book_text_raw = _read_json(session_dir / _BOOK_TEXT_FILE)
            chunks_raw = _read_json(session_dir / _CHUNKS_FILE)
            kg_raw = _read_json(session_dir / _KG_FILE)
        except FileNotFoundError as exc:
            raise SessionStorageCorrupted(
                f"session {session_id!r} missing required file: {exc}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise SessionStorageCorrupted(
                f"session {session_id!r} has corrupted JSON: {exc}"
            ) from exc

        try:
            book_text = BookText.model_validate(book_text_raw)
            chunks = [ChunkResult.model_validate(c) for c in chunks_raw.get("chunks", [])]
            kg = BookKnowledgeGraph.model_validate(kg_raw)
        except Exception as exc:  # noqa: BLE001 — Pydantic ValidationError 等
            raise SessionStorageCorrupted(
                f"session {session_id!r} failed schema validation: {exc}"
            ) from exc

        # 刷新 last_accessed_at；失败不阻塞 load（只是访问时间戳丢了）。
        try:
            self._touch_accessed_at(session_dir)
        except OSError:  # pragma: no cover — best-effort
            logger.debug("failed to touch last_accessed_at for %s", session_id)

        vector_store: SessionVectorStore | None = None
        vector_index_dir = session_dir / _VECTOR_INDEX_DIR
        if (vector_index_dir / "manifest.json").is_file():
            try:
                vector_store = SessionVectorStore.load_from_dir(
                    vector_index_dir
                )
            except VectorStoreLoadError as exc:
                # Persisted index is unusable (schema bump, provider
                # mismatch, half-written file). Degrade to None so the
                # session is still usable for non-vector tools; the
                # search_chunks backend will disable itself and
                # ``agent_ask`` will surface a 400 telling the author
                # to rebuild the index. This mirrors the pre-ADR-005A
                # workaround and keeps load resilient.
                logger.warning(
                    "vector_index for session %s unusable, loading without "
                    "vector store: %s",
                    session_id, exc,
                )
                vector_store = None

        return R0BookAssembler(
            book_text=book_text,
            chunks=chunks,
            knowledge_graph=kg,
            session_vector_store=vector_store,
        )

    def list_all(self) -> list[str]:
        """返回所有有 metadata.json 的子目录名。"""
        if not self._root.is_dir():
            return []
        out: list[str] = []
        for child in self._root.iterdir():
            if child.is_dir() and (child / _METADATA_FILE).is_file():
                out.append(child.name)
        return sorted(out)

    def delete(self, session_id: str) -> None:
        session_dir = self._session_dir(session_id)
        if not session_dir.exists():
            return
        with self._lock:
            shutil.rmtree(session_dir, ignore_errors=True)

    def exists(self, session_id: str) -> bool:
        return self._session_dir(session_id).is_dir()

    def read_metadata(self, session_id: str) -> dict[str, Any]:
        """读取并返回 ``<root>/<session_id>/metadata.json`` 的内容。

        仅返回 metadata 字段（``session_id`` / ``book_title`` /
        ``language`` / ``created_at`` / ``last_accessed_at``），不触碰
        chunks / kg / vector_index 等内部资产。

        Raises:
            BookSessionNotFound: 目录不存在。
            SessionStorageCorrupted: metadata.json 缺失或无法解析。
        """
        # 局部 import 规避循环依赖（同 load）。
        from bookscope.api.book_sessions import BookSessionNotFound

        session_dir = self._session_dir(session_id)
        if not session_dir.is_dir():
            raise BookSessionNotFound(
                f"book session {session_id!r} not found in storage"
            )
        metadata_path = session_dir / _METADATA_FILE
        try:
            data = _read_json(metadata_path)
        except FileNotFoundError as exc:
            raise SessionStorageCorrupted(
                f"session {session_id!r} missing metadata.json"
            ) from exc
        except json.JSONDecodeError as exc:
            raise SessionStorageCorrupted(
                f"session {session_id!r} has corrupted metadata.json: {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise SessionStorageCorrupted(
                f"session {session_id!r} metadata.json is not a JSON object"
            )
        return data

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _session_dir(self, session_id: str) -> Path:
        """返回 session 目录路径。不保证已存在；调用方按需 mkdir。"""
        # 基本安全：拒绝路径穿越 ``..`` 与绝对路径 ``/``。
        if "/" in session_id or "\\" in session_id or ".." in session_id:
            raise ValueError(f"invalid session_id: {session_id!r}")
        return self._root / session_id

    def _touch_accessed_at(self, session_dir: Path) -> None:
        """更新 metadata.json 的 last_accessed_at 字段（best-effort）。"""
        metadata_path = session_dir / _METADATA_FILE
        try:
            metadata = _read_json(metadata_path)
        except (FileNotFoundError, json.JSONDecodeError):
            return
        metadata["last_accessed_at"] = _utc_now_iso()
        _write_json(metadata_path, metadata)


# ---------------------------------------------------------------------------
# module-level helpers
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    """ISO-8601 UTC 时间戳（精度到秒）。无 timezone SDK 依赖。"""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _write_json(path: Path, data: Any) -> None:
    """写入 JSON；总是 UTF-8 + ensure_ascii=False，让中文可读。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)


def _read_json(path: Path) -> Any:
    """读取 JSON；UTF-8 解码。抛 ``FileNotFoundError`` / ``JSONDecodeError``。"""
    with path.open("r", encoding="utf-8") as fp:
        return json.load(fp)


def _read_created_at_or(metadata_path: Path, fallback: str) -> str:
    """从旧 metadata.json 读 ``created_at``；读不到就用 ``fallback``。"""
    try:
        with metadata_path.open("r", encoding="utf-8") as fp:
            data = json.load(fp)
        val = data.get("created_at")
        if isinstance(val, str) and val:
            return val
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return fallback


__all__ = [
    "JSONFileSessionStorage",
    "SessionStorage",
    "SessionStorageCorrupted",
    "SessionStorageError",
]
