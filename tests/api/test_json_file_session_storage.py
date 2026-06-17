"""JSONFileSessionStorage 单元测试（ADR-005 方案 A）。

覆盖：

- save / load roundtrip 对 book_text / chunks / kg 三份数据做深等价断言
- save 覆盖同 id：新数据替换旧
- load 不存在 → BookSessionNotFound
- list_all：多 session 后列出所有 id（升序 + 去重）
- delete：删除后 list 不含、exists False、load 抛
- exists：存在 True、不存在 False
- JSON 损坏 → SessionStorageCorrupted
- pydantic 校验失败 → SessionStorageCorrupted
- 缺必要文件 → SessionStorageCorrupted
- 目录不存在时 save 自动创建
- 并发 save / 并发 delete 的最低线程安全保障
- session_id 含 ``..`` / 斜杠 → ValueError（路径穿越防护）
- BookSessionStore + storage 的 get miss cache → storage load → 再 cache
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from bookscope.agent.backends.r0_assembler import R0BookAssembler
from bookscope.api.book_sessions import BookSessionNotFound, BookSessionStore
from bookscope.api.session_storage import (
    JSONFileSessionStorage,
    SessionStorageCorrupted,
)
from bookscope.models.schemas import (
    BookKnowledgeGraph,
    BookText,
    CharacterProfile,
    ChunkResult,
)

# ---------------------------------------------------------------------------
# Fixture 构造一个真 R0BookAssembler（用极小数据，避免依赖 FAISS / jieba）
# ---------------------------------------------------------------------------


def _build_assembler(
    *,
    book_title: str = "测试书",
    language: str = "zh",
    raw_text: str = "第一章 开端\n这是正文。\n\n第二章 高潮\n这是正文。",
    chunk_count: int = 2,
    characters: list[str] | None = None,
) -> R0BookAssembler:
    characters = characters or ["主角甲"]
    book_text = BookText(
        title=book_title,
        raw_text=raw_text,
        language=language,
    )
    chunks = [
        ChunkResult(index=i, text=f"[《{book_title}》第{i + 1}章]\n第{i}段内容。")
        for i in range(chunk_count)
    ]
    kg = BookKnowledgeGraph(
        book_title=book_title,
        language=language,
        characters=[
            CharacterProfile(name=name, key_chapter_indices=[1])
            for name in characters
        ],
    )
    return R0BookAssembler(
        book_text=book_text,
        chunks=chunks,
        knowledge_graph=kg,
        session_vector_store=None,
    )


# ---------------------------------------------------------------------------
# 基础 save / load
# ---------------------------------------------------------------------------


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    storage = JSONFileSessionStorage(root=tmp_path)
    assembler = _build_assembler()
    storage.save("sess-001", assembler)

    loaded = storage.load("sess-001")
    # book_text 字段逐一断言（Pydantic 深等价通过 model_dump 对比）
    assert loaded._book_text.model_dump() == assembler._book_text.model_dump()  # noqa: SLF001
    assert [c.model_dump() for c in loaded._chunks] == [  # noqa: SLF001
        c.model_dump() for c in assembler._chunks  # noqa: SLF001
    ]
    assert loaded._kg.model_dump() == assembler._kg.model_dump()  # noqa: SLF001


def test_save_creates_directory(tmp_path: Path) -> None:
    """传入不存在的 root，save 应自动建目录。"""
    new_root = tmp_path / "does" / "not" / "exist" / "yet"
    assert not new_root.exists()
    storage = JSONFileSessionStorage(root=new_root)
    storage.save("sess-x", _build_assembler())
    assert (new_root / "sess-x" / "metadata.json").is_file()


def test_save_overwrites_same_session(tmp_path: Path) -> None:
    storage = JSONFileSessionStorage(root=tmp_path)
    first = _build_assembler(book_title="第一版")
    second = _build_assembler(book_title="第二版")
    storage.save("sess-over", first)
    storage.save("sess-over", second)
    loaded = storage.load("sess-over")
    assert loaded._book_text.title == "第二版"  # noqa: SLF001


def test_save_preserves_created_at_on_overwrite(tmp_path: Path) -> None:
    """覆盖 save 时应保留最早的 created_at，只更新 last_accessed_at。"""
    storage = JSONFileSessionStorage(root=tmp_path)
    storage.save("sess-ts", _build_assembler())
    metadata_path = tmp_path / "sess-ts" / "metadata.json"
    first_meta = json.loads(metadata_path.read_text(encoding="utf-8"))

    # 保存第二次
    storage.save("sess-ts", _build_assembler())
    second_meta = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert second_meta["created_at"] == first_meta["created_at"]


# ---------------------------------------------------------------------------
# load 错误路径
# ---------------------------------------------------------------------------


def test_load_missing_raises_book_session_not_found(tmp_path: Path) -> None:
    storage = JSONFileSessionStorage(root=tmp_path)
    with pytest.raises(BookSessionNotFound):
        storage.load("nope")


def test_load_corrupted_json_raises(tmp_path: Path) -> None:
    storage = JSONFileSessionStorage(root=tmp_path)
    storage.save("sess-broken", _build_assembler())
    # 把 kg.json 搞坏
    (tmp_path / "sess-broken" / "kg.json").write_text(
        "this is not json {{", encoding="utf-8"
    )
    with pytest.raises(SessionStorageCorrupted):
        storage.load("sess-broken")


def test_load_missing_file_raises(tmp_path: Path) -> None:
    storage = JSONFileSessionStorage(root=tmp_path)
    storage.save("sess-partial", _build_assembler())
    # 删除 chunks.json
    (tmp_path / "sess-partial" / "chunks.json").unlink()
    with pytest.raises(SessionStorageCorrupted):
        storage.load("sess-partial")


def test_load_schema_validation_failure_raises(tmp_path: Path) -> None:
    storage = JSONFileSessionStorage(root=tmp_path)
    storage.save("sess-schema", _build_assembler())
    # 写入一个 schema 不合规的 book_text.json（缺 title / raw_text）
    (tmp_path / "sess-schema" / "book_text.json").write_text(
        json.dumps({"foo": "bar"}), encoding="utf-8"
    )
    with pytest.raises(SessionStorageCorrupted):
        storage.load("sess-schema")


# ---------------------------------------------------------------------------
# list_all / delete / exists
# ---------------------------------------------------------------------------


def test_list_all_returns_sorted_session_ids(tmp_path: Path) -> None:
    storage = JSONFileSessionStorage(root=tmp_path)
    storage.save("zeta", _build_assembler())
    storage.save("alpha", _build_assembler())
    storage.save("mid", _build_assembler())
    assert storage.list_all() == ["alpha", "mid", "zeta"]


def test_list_all_ignores_dirs_without_metadata(tmp_path: Path) -> None:
    storage = JSONFileSessionStorage(root=tmp_path)
    storage.save("real", _build_assembler())
    # 伪造一个没有 metadata.json 的目录，不应被列出
    (tmp_path / "fake").mkdir()
    (tmp_path / "fake" / "junk.txt").write_text("noise", encoding="utf-8")
    assert storage.list_all() == ["real"]


def test_list_all_empty_when_root_missing(tmp_path: Path) -> None:
    storage = JSONFileSessionStorage(root=tmp_path / "nonexistent")
    assert storage.list_all() == []


def test_delete_removes_session(tmp_path: Path) -> None:
    storage = JSONFileSessionStorage(root=tmp_path)
    storage.save("to-delete", _build_assembler())
    assert storage.exists("to-delete")
    storage.delete("to-delete")
    assert not storage.exists("to-delete")
    assert "to-delete" not in storage.list_all()
    with pytest.raises(BookSessionNotFound):
        storage.load("to-delete")


def test_delete_nonexistent_is_silent(tmp_path: Path) -> None:
    storage = JSONFileSessionStorage(root=tmp_path)
    storage.delete("never-existed")  # should not raise


def test_exists_true_and_false(tmp_path: Path) -> None:
    storage = JSONFileSessionStorage(root=tmp_path)
    storage.save("yes", _build_assembler())
    assert storage.exists("yes") is True
    assert storage.exists("no") is False


# ---------------------------------------------------------------------------
# 路径安全
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_id", ["../evil", "a/b", "a\\b", "..\\etc"])
def test_invalid_session_id_rejected(tmp_path: Path, bad_id: str) -> None:
    storage = JSONFileSessionStorage(root=tmp_path)
    with pytest.raises(ValueError):
        storage.save(bad_id, _build_assembler())


def test_empty_session_id_rejected(tmp_path: Path) -> None:
    storage = JSONFileSessionStorage(root=tmp_path)
    with pytest.raises(ValueError):
        storage.save("", _build_assembler())


# ---------------------------------------------------------------------------
# 并发
# ---------------------------------------------------------------------------


def test_concurrent_save_same_session(tmp_path: Path) -> None:
    """多线程同时 save 同一 session，不应崩溃，最终文件可正常 load。"""
    storage = JSONFileSessionStorage(root=tmp_path)
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            storage.save("sess-concurrent", _build_assembler())
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    # 依然可以 load
    storage.load("sess-concurrent")


# ---------------------------------------------------------------------------
# BookSessionStore 与 storage 集成
# ---------------------------------------------------------------------------


def test_store_load_from_storage_on_cache_miss(tmp_path: Path) -> None:
    """register 后清空内存 cache，get 应从 storage 懒加载并回灌 cache。"""
    storage = JSONFileSessionStorage(root=tmp_path)
    store = BookSessionStore(storage=storage)
    assembler = _build_assembler(book_title="持久化测试")
    store.register("sess-persist", assembler)

    # 清空内存 cache 模拟进程重启
    store.clear()

    loaded = store.get("sess-persist")
    assert loaded._book_text.title == "持久化测试"  # noqa: SLF001
    # get 命中后应回灌 cache，第二次 get 直接返回同一实例
    assert store.get("sess-persist") is loaded


def test_store_has_checks_storage_when_memory_miss(tmp_path: Path) -> None:
    storage = JSONFileSessionStorage(root=tmp_path)
    store = BookSessionStore(storage=storage)
    store.register("sess-exists", _build_assembler())
    store.clear()  # 内存清了
    assert store.has("sess-exists") is True  # storage 里还有
    assert store.has("does-not-exist") is False


def test_store_delete_removes_both_memory_and_storage(tmp_path: Path) -> None:
    storage = JSONFileSessionStorage(root=tmp_path)
    store = BookSessionStore(storage=storage)
    store.register("sess-del", _build_assembler())
    store.delete("sess-del")
    assert "sess-del" not in store.list_sessions()
    assert not storage.exists("sess-del")


def test_store_list_sessions_merges_memory_and_storage(tmp_path: Path) -> None:
    storage = JSONFileSessionStorage(root=tmp_path)
    # 预先在 storage 里放一个（模拟进程重启前留下的）
    storage.save("only-in-storage", _build_assembler())
    store = BookSessionStore(storage=storage)
    # 只在内存注册另一个
    asm2 = _build_assembler()
    store._sessions["only-in-memory"] = asm2  # noqa: SLF001
    result = store.list_sessions()
    assert "only-in-storage" in result
    assert "only-in-memory" in result
    # 升序 + 去重
    assert result == sorted(set(result))


def test_store_get_memory_only_mode_still_works(tmp_path: Path) -> None:
    """storage=None 时行为与旧版完全一致（向后兼容）。"""
    store = BookSessionStore()  # 不传 storage
    assert store.list_sessions() == []
    with pytest.raises(BookSessionNotFound):
        store.get("nope")
    store.register("x", _build_assembler())
    assert store.get("x") is not None


# ---------------------------------------------------------------------------
# vector_index 持久化（ADR-005 落地要点第 4 步）
# ---------------------------------------------------------------------------


def test_save_load_preserves_bm25_vector_store(tmp_path: Path) -> None:
    """装配了 BM25-only SessionVectorStore 的 assembler，save/load 后能恢复。"""
    from bookscope.store import vector_store as vs_module
    from bookscope.store.vector_store import SessionVectorStore

    # 强制 provider=None，走 BM25-only 分支（不依赖任何 embedding API）
    original_provider = vs_module._provider  # noqa: SLF001
    vs_module._provider = None  # noqa: SLF001
    try:
        assembler = _build_assembler(
            raw_text="第一章 林冲\n雪夜山神庙。\n\n第二章 武松\n景阳岗打虎。",
            chunk_count=2,
        )
        chunks = assembler._chunks  # noqa: SLF001
        vector_store = SessionVectorStore(chunks, enable_vector=False)
        # 直接替换 vector_store（_build_assembler 创建时为 None）
        assembler._vector_store = vector_store  # noqa: SLF001

        storage = JSONFileSessionStorage(root=tmp_path)
        storage.save("sess-vs", assembler)

        vector_dir = tmp_path / "sess-vs" / "vector_index"
        assert (vector_dir / "manifest.json").is_file()
        assert (vector_dir / "bm25.pkl").is_file()

        loaded = storage.load("sess-vs")
        assert loaded._vector_store is not None  # noqa: SLF001
        assert loaded._vector_store.has_bm25 is True  # noqa: SLF001
        assert loaded._vector_store.has_vector is False  # noqa: SLF001
        assert loaded._vector_store.chunk_count == 2  # noqa: SLF001
    finally:
        vs_module._provider = original_provider  # noqa: SLF001


def test_save_without_vector_store_leaves_empty_vector_dir(
    tmp_path: Path,
) -> None:
    """assembler._vector_store is None → vector_index 目录为空，load 还原为 None。"""
    storage = JSONFileSessionStorage(root=tmp_path)
    storage.save("sess-none", _build_assembler())

    vector_dir = tmp_path / "sess-none" / "vector_index"
    assert vector_dir.is_dir()
    assert not (vector_dir / "manifest.json").exists()

    loaded = storage.load("sess-none")
    assert loaded._vector_store is None  # noqa: SLF001


def test_resave_wipes_stale_vector_index(tmp_path: Path) -> None:
    """先保存一个带 vector store 的 session，再用无 vector store 的 assembler 覆盖，
    旧的 manifest / bm25.pkl 必须被清掉，否则下次 load 会误装配一个不属于当前
    session 的向量索引。"""
    from bookscope.store import vector_store as vs_module
    from bookscope.store.vector_store import SessionVectorStore

    original_provider = vs_module._provider  # noqa: SLF001
    vs_module._provider = None  # noqa: SLF001
    try:
        storage = JSONFileSessionStorage(root=tmp_path)

        first = _build_assembler()
        first._vector_store = SessionVectorStore(  # noqa: SLF001
            first._chunks, enable_vector=False,  # noqa: SLF001
        )
        storage.save("sess-dup", first)
        assert (tmp_path / "sess-dup" / "vector_index" / "manifest.json").is_file()

        second = _build_assembler()  # 不装 vector_store
        storage.save("sess-dup", second)

        assert not (
            tmp_path / "sess-dup" / "vector_index" / "manifest.json"
        ).exists()

        loaded = storage.load("sess-dup")
        assert loaded._vector_store is None  # noqa: SLF001
    finally:
        vs_module._provider = original_provider  # noqa: SLF001


def test_load_degrades_to_none_when_vector_index_corrupted(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """手动损坏 manifest 后，load 应降级为 vector_store=None 并打 warning，
    不让损坏的 vector index 阻塞其余数据的 load。"""
    from bookscope.store import vector_store as vs_module
    from bookscope.store.vector_store import SessionVectorStore

    original_provider = vs_module._provider  # noqa: SLF001
    vs_module._provider = None  # noqa: SLF001
    try:
        storage = JSONFileSessionStorage(root=tmp_path)
        asm = _build_assembler()
        asm._vector_store = SessionVectorStore(  # noqa: SLF001
            asm._chunks, enable_vector=False,  # noqa: SLF001
        )
        storage.save("sess-corrupt", asm)

        (tmp_path / "sess-corrupt" / "vector_index" / "manifest.json").write_text(
            "{ not valid", encoding="utf-8",
        )

        with caplog.at_level("WARNING", logger="bookscope.api.session_storage"):
            loaded = storage.load("sess-corrupt")

        assert loaded._vector_store is None  # noqa: SLF001
        assert any("unusable" in r.message for r in caplog.records)
    finally:
        vs_module._provider = original_provider  # noqa: SLF001
