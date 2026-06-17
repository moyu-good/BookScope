"""L3 book 预热缓存单测 —— Sprint 8 W3。

覆盖：

- ``warm_book`` + ``get_warmed_book`` 基础 roundtrip
- 二次加载（LRU 第一层命中）
- 重启模拟（清 LRU 保留磁盘）→ 磁盘第二层命中 + 自动 promote 到 LRU
- 5+ 本上限 → LRU 淘汰最旧（lru_evict 计数）
- ``invalidate_book`` 清两层
- content_hash 不一致 → ``warm_book`` 覆盖时主动 invalidate 旧条目
- ``stats()`` 数字准确
- ``compute_content_hash`` 稳定 + 区分内容
- env disabled 时 get / warm 都 no-op
- 路径穿越 session_id 拒绝
- pickle 文件损坏视为 miss + 静默删
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bookscope.agent._internal import book_cache
from bookscope.agent._internal.book_cache import (
    ENV_DIR,
    ENV_DISABLED,
    WarmedBook,
    clear_all,
    compute_content_hash,
    get_warmed_book,
    invalidate_book,
    stats,
    warm_book,
)
from bookscope.agent.backends.r0_assembler import R0BookAssembler
from bookscope.models.schemas import (
    BookKnowledgeGraph,
    BookText,
    CharacterProfile,
    ChunkResult,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _build_assembler(
    *,
    book_title: str = "测试书",
    raw_text: str = "第一章 开端\n这是正文。",
) -> R0BookAssembler:
    book_text = BookText(title=book_title, raw_text=raw_text, language="zh")
    chunks = [
        ChunkResult(index=i, text=f"[《{book_title}》第{i + 1}章]\n第{i}段内容。")
        for i in range(2)
    ]
    kg = BookKnowledgeGraph(
        book_title=book_title,
        language="zh",
        characters=[CharacterProfile(name="主角甲", key_chapter_indices=[1])],
    )
    return R0BookAssembler(
        book_text=book_text,
        chunks=chunks,
        knowledge_graph=kg,
        session_vector_store=None,
    )


@pytest.fixture(autouse=True)
def isolated_cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """每个测试用独立的 cache dir + clean state。"""
    cache_dir = tmp_path / "book_warmup"
    monkeypatch.setenv(ENV_DIR, str(cache_dir))
    monkeypatch.delenv(ENV_DISABLED, raising=False)
    clear_all()
    yield cache_dir
    clear_all()


# ---------------------------------------------------------------------------
# 基础 roundtrip
# ---------------------------------------------------------------------------


class TestBasicRoundtrip:
    def test_get_miss_returns_none(self) -> None:
        assert get_warmed_book("sess-nope") is None

    def test_warm_then_get_lru_hit(self) -> None:
        assembler = _build_assembler()
        warm_book("sess-1", assembler)
        warmed = get_warmed_book("sess-1")
        assert warmed is not None
        assert isinstance(warmed, WarmedBook)
        # 同进程 LRU 第一层命中，返同一个 assembler 实例
        assert warmed.assembler is assembler
        # 命中累计到 lru_hit
        assert stats()["lru_hit"] == 1
        assert stats()["disk_hit"] == 0

    def test_warmed_book_carries_content_hash(self) -> None:
        assembler = _build_assembler(raw_text="abcdef")
        warm_book("sess-1", assembler)
        warmed = get_warmed_book("sess-1")
        assert warmed is not None
        assert warmed.content_hash == compute_content_hash(assembler)
        assert warmed.ingested_at  # 非空

    def test_pickle_file_written(self, isolated_cache_dir: Path) -> None:
        assembler = _build_assembler()
        warm_book("sess-1", assembler)
        assert (isolated_cache_dir / "sess-1.pkl").is_file()


# ---------------------------------------------------------------------------
# 重启模拟：清 LRU 保留磁盘 → 磁盘第二层命中
# ---------------------------------------------------------------------------


class TestDiskLayer:
    def test_disk_hit_after_lru_cleared(self) -> None:
        assembler = _build_assembler(raw_text="原文内容 X")
        warm_book("sess-disk", assembler)
        # 模拟"进程重启"：清空 LRU 但保留磁盘 pickle
        book_cache._LRU.clear_all()  # noqa: SLF001 — 测试需要绕过 stats reset
        # 注意 clear_all() 会清磁盘，所以这里不能用——只能直清 LRU 内部
        warmed = get_warmed_book("sess-disk")
        assert warmed is not None
        # 内容 hash 必须一致——pickle 反序列化没丢字段
        assert warmed.content_hash == compute_content_hash(assembler)
        # 反序列化后的 assembler 实例不是 is 同一个，但 raw_text 等价
        assert warmed.assembler._book_text.raw_text == "原文内容 X"  # noqa: SLF001
        # 累计 disk_hit
        assert stats()["disk_hit"] == 1

    def test_disk_hit_promotes_to_lru(self) -> None:
        assembler = _build_assembler()
        warm_book("sess-1", assembler)
        book_cache._LRU.clear_all()  # noqa: SLF001
        # 第一次 get：磁盘 hit + 自动 promote 到 LRU
        get_warmed_book("sess-1")
        # 第二次 get：LRU 直接命中
        get_warmed_book("sess-1")
        s = stats()
        assert s["disk_hit"] == 1
        assert s["lru_hit"] == 1


# ---------------------------------------------------------------------------
# LRU 上限 5 本
# ---------------------------------------------------------------------------


class TestLRUEviction:
    def test_lru_evicts_oldest_when_exceeding_5(self) -> None:
        # 写 6 本，第 1 本应被淘汰
        for i in range(6):
            asm = _build_assembler(raw_text=f"book-{i}")
            warm_book(f"sess-{i}", asm)
        # 当前 LRU size 应是 5
        assert stats()["size"] == 5
        assert stats()["lru_evict"] >= 1
        # 第 0 本不在 LRU 但磁盘还在——get 应该走 disk_hit
        # 先清 stats（不清缓存）来精确观察后续 hit
        # 实际：sess-0 的 LRU 已被淘汰；get 时磁盘 hit
        warmed_0 = get_warmed_book("sess-0")
        assert warmed_0 is not None


# ---------------------------------------------------------------------------
# Invalidate
# ---------------------------------------------------------------------------


class TestInvalidate:
    def test_invalidate_clears_both_layers(
        self, isolated_cache_dir: Path
    ) -> None:
        assembler = _build_assembler()
        warm_book("sess-1", assembler)
        assert (isolated_cache_dir / "sess-1.pkl").is_file()

        invalidate_book("sess-1")
        # LRU + 磁盘都没了
        assert get_warmed_book("sess-1") is None
        assert not (isolated_cache_dir / "sess-1.pkl").exists()

    def test_invalidate_nonexistent_session_is_idempotent(self) -> None:
        # 不抛错
        invalidate_book("nope-never-existed")

    def test_invalidate_empty_session_id_is_noop(self) -> None:
        invalidate_book("")

    def test_invalidate_invalid_session_id_is_noop(self) -> None:
        # 路径穿越的 session_id 被静默拒——不抛错
        invalidate_book("../bad")


# ---------------------------------------------------------------------------
# content_hash 一致性 / stale 检测
# ---------------------------------------------------------------------------


class TestContentHash:
    def test_compute_content_hash_is_deterministic(self) -> None:
        asm1 = _build_assembler(raw_text="同样的原文")
        asm2 = _build_assembler(raw_text="同样的原文")
        assert compute_content_hash(asm1) == compute_content_hash(asm2)

    def test_compute_content_hash_distinguishes_content(self) -> None:
        asm1 = _build_assembler(raw_text="原文 A")
        asm2 = _build_assembler(raw_text="原文 B")
        assert compute_content_hash(asm1) != compute_content_hash(asm2)

    def test_warm_book_same_id_different_content_replaces(
        self, isolated_cache_dir: Path
    ) -> None:
        """同 ID 但 content_hash 不同——视为重新上传同书，新条目覆盖旧。"""
        asm_v1 = _build_assembler(raw_text="原版内容")
        warm_book("sess-1", asm_v1)
        hash_v1 = compute_content_hash(asm_v1)

        asm_v2 = _build_assembler(raw_text="作者重新上传的修订版")
        warm_book("sess-1", asm_v2)
        hash_v2 = compute_content_hash(asm_v2)

        assert hash_v1 != hash_v2
        warmed = get_warmed_book("sess-1")
        assert warmed is not None
        assert warmed.content_hash == hash_v2
        # 磁盘 pickle 也应是新版
        book_cache._LRU.clear_all()  # noqa: SLF001
        warmed_from_disk = get_warmed_book("sess-1")
        assert warmed_from_disk is not None
        assert warmed_from_disk.content_hash == hash_v2


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------


class TestStats:
    def test_initial_stats_all_zero(self) -> None:
        s = stats()
        assert s == {
            "lru_hit": 0,
            "disk_hit": 0,
            "miss": 0,
            "size": 0,
            "lru_evict": 0,
        }

    def test_miss_increments_miss_counter(self) -> None:
        get_warmed_book("nope-1")
        get_warmed_book("nope-2")
        assert stats()["miss"] == 2

    def test_stats_field_keys_stable(self) -> None:
        """stats 字段名稳定——OPS dashboard 依赖。"""
        assert set(stats().keys()) == {
            "lru_hit", "disk_hit", "miss", "size", "lru_evict",
        }


# ---------------------------------------------------------------------------
# env disabled
# ---------------------------------------------------------------------------


class TestEnvDisabled:
    def test_disabled_get_returns_none_without_touching_anything(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(ENV_DISABLED, "1")
        assembler = _build_assembler()
        warm_book("sess-1", assembler)  # 写入也 no-op
        assert get_warmed_book("sess-1") is None
        # disabled 下 stats 不动
        assert stats()["miss"] == 0
        assert stats()["lru_hit"] == 0

    def test_disabled_value_other_than_1_treated_as_enabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(ENV_DISABLED, "true")  # 不是 "1" 视为 on
        assembler = _build_assembler()
        warm_book("sess-1", assembler)
        assert get_warmed_book("sess-1") is not None


# ---------------------------------------------------------------------------
# 损坏 pickle 文件视为 miss
# ---------------------------------------------------------------------------


class TestCorruptedPickle:
    def test_corrupted_pickle_treated_as_miss_and_deleted(
        self, isolated_cache_dir: Path
    ) -> None:
        # 手写一个坏 pickle 文件
        isolated_cache_dir.mkdir(parents=True, exist_ok=True)
        bad_pkl = isolated_cache_dir / "sess-bad.pkl"
        bad_pkl.write_bytes(b"this is not a valid pickle stream")
        # get 视作 miss + 静默删旧文件
        assert get_warmed_book("sess-bad") is None
        assert not bad_pkl.exists()
        assert stats()["miss"] == 1

    def test_pickle_with_wrong_type_treated_as_miss(
        self, isolated_cache_dir: Path
    ) -> None:
        """pickle 文件 valid 但反序列化不是 WarmedBook ——也按 miss 处理。"""
        import pickle as _pickle

        isolated_cache_dir.mkdir(parents=True, exist_ok=True)
        wrong_pkl = isolated_cache_dir / "sess-wrong.pkl"
        wrong_pkl.write_bytes(_pickle.dumps({"not": "warmed_book"}))
        assert get_warmed_book("sess-wrong") is None
        assert not wrong_pkl.exists()


# ---------------------------------------------------------------------------
# 路径穿越防护
# ---------------------------------------------------------------------------


class TestPathTraversalProtection:
    def test_warm_book_rejects_path_traversal(self) -> None:
        assembler = _build_assembler()
        # warm_book 内部 swallow 异常，不抛——但缓存写入会被跳过
        warm_book("../evil", assembler)
        # 缓存里不应有这条
        assert stats()["size"] == 0

    def test_get_warmed_book_rejects_path_traversal(self) -> None:
        with pytest.raises(ValueError):
            get_warmed_book("../evil")


# ---------------------------------------------------------------------------
# 与 BookSessionStore 集成
# ---------------------------------------------------------------------------


class TestBookSessionStoreIntegration:
    """register / get / delete 三处切入点的端到端命中验证。"""

    def test_register_warms_l3(self) -> None:
        from bookscope.api.book_sessions import BookSessionStore

        store = BookSessionStore()  # storage=None 走纯内存
        assembler = _build_assembler()
        store.register("sess-int-1", assembler)
        # L3 立即可读
        warmed = get_warmed_book("sess-int-1")
        assert warmed is not None
        assert warmed.assembler is assembler

    def test_delete_invalidates_l3(self, isolated_cache_dir: Path) -> None:
        from bookscope.api.book_sessions import BookSessionStore

        store = BookSessionStore()
        assembler = _build_assembler()
        store.register("sess-int-2", assembler)
        assert (isolated_cache_dir / "sess-int-2.pkl").is_file()

        store.delete("sess-int-2")
        assert get_warmed_book("sess-int-2") is None
        assert not (isolated_cache_dir / "sess-int-2.pkl").exists()

    def test_get_after_clear_internal_cache_hits_l3(self) -> None:
        """场景：register 后清掉 BookSessionStore 内存（模拟重启），
        get 走 L3 LRU 第一层命中——跳过 storage.load。"""
        from bookscope.api.book_sessions import BookSessionStore

        store = BookSessionStore()
        assembler = _build_assembler()
        store.register("sess-int-3", assembler)
        store.clear()  # 清 BookSessionStore 内存 cache
        # 再 get：内存 miss → L3 LRU 命中
        loaded = store.get("sess-int-3")
        assert loaded is assembler
        assert stats()["lru_hit"] == 1
