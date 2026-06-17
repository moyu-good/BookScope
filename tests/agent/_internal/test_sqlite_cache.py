"""``bookscope.agent._internal.sqlite_cache.SQLiteCache`` 单测 —— Sprint 8 W2。

覆盖：

- 基本 get / set / miss 语义
- schema_version 升级时旧 row 自动 miss + ``invalidate_by_version`` 物理清理
- ``stats()`` 数字准确
- 并发 set 不冲突（threading 测试）
- table_name 防 SQL 注入白名单
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from bookscope.agent._internal.sqlite_cache import SQLiteCache


@pytest.fixture
def cache_path(tmp_path: Path) -> Path:
    return tmp_path / "test_cache.db"


class TestSQLiteCacheBasic:
    """get / set / miss 基础语义。"""

    def test_get_miss_returns_none(self, cache_path: Path) -> None:
        cache = SQLiteCache(cache_path, "calls", "v1")
        assert cache.get("nope") is None

    def test_set_then_get_hit(self, cache_path: Path) -> None:
        cache = SQLiteCache(cache_path, "calls", "v1")
        cache.set("k1", b"hello")
        assert cache.get("k1") == b"hello"

    def test_set_overwrites_existing_key(self, cache_path: Path) -> None:
        cache = SQLiteCache(cache_path, "calls", "v1")
        cache.set("k1", b"v1")
        cache.set("k1", b"v2")
        assert cache.get("k1") == b"v2"
        assert cache.stats()["size"] == 1

    def test_empty_bytes_value_is_valid_hit(self, cache_path: Path) -> None:
        """存 b"" 应当能被取回；不应该被当成 miss。"""
        cache = SQLiteCache(cache_path, "calls", "v1")
        cache.set("k1", b"")
        assert cache.get("k1") == b""

    def test_persists_across_instances_same_path(self, cache_path: Path) -> None:
        """重启不丢——同 path 同 schema 第二个实例能读到第一个写的 row。"""
        cache1 = SQLiteCache(cache_path, "calls", "v1")
        cache1.set("k1", b"persisted")
        # 模拟进程重启：新实例同路径
        cache2 = SQLiteCache(cache_path, "calls", "v1")
        assert cache2.get("k1") == b"persisted"


class TestSchemaVersionInvalidate:
    """schema_version 升级时旧 row 失效。"""

    def test_version_mismatch_returns_miss(self, cache_path: Path) -> None:
        cache_v1 = SQLiteCache(cache_path, "calls", "v1")
        cache_v1.set("k1", b"old")
        # 新版本读：旧 row 视为 miss
        cache_v2 = SQLiteCache(cache_path, "calls", "v2")
        assert cache_v2.get("k1") is None

    def test_version_mismatch_does_not_delete_row(self, cache_path: Path) -> None:
        """版本不匹配只是 miss，row 物理上还在——等显式 invalidate 才删。"""
        cache_v1 = SQLiteCache(cache_path, "calls", "v1")
        cache_v1.set("k1", b"old")
        cache_v2 = SQLiteCache(cache_path, "calls", "v2")
        cache_v2.get("k1")
        # size 仍是 1
        assert cache_v2.stats()["size"] == 1

    def test_invalidate_by_version_deletes_matching_rows(
        self, cache_path: Path
    ) -> None:
        cache_v1 = SQLiteCache(cache_path, "calls", "v1")
        cache_v1.set("k1", b"a")
        cache_v1.set("k2", b"b")
        # 切到 v2，写入新 row
        cache_v2 = SQLiteCache(cache_path, "calls", "v2")
        cache_v2.set("k3", b"c")
        # 删 v1 所有 row
        removed = cache_v2.invalidate_by_version("v1")
        assert removed == 2
        assert cache_v2.stats()["size"] == 1
        assert cache_v2.get("k3") == b"c"

    def test_invalidate_by_unknown_version_returns_zero(
        self, cache_path: Path
    ) -> None:
        cache = SQLiteCache(cache_path, "calls", "v1")
        cache.set("k1", b"a")
        assert cache.invalidate_by_version("v99") == 0


class TestStats:
    """stats 数字准确性。"""

    def test_stats_initial(self, cache_path: Path) -> None:
        cache = SQLiteCache(cache_path, "calls", "v1")
        s = cache.stats()
        assert s == {"hit": 0, "miss": 0, "size": 0}

    def test_stats_hits_and_misses(self, cache_path: Path) -> None:
        cache = SQLiteCache(cache_path, "calls", "v1")
        cache.set("a", b"1")
        cache.get("a")  # hit
        cache.get("a")  # hit
        cache.get("b")  # miss
        cache.get("c")  # miss
        s = cache.stats()
        assert s["hit"] == 2
        assert s["miss"] == 2
        assert s["size"] == 1

    def test_clear_all_resets_everything(self, cache_path: Path) -> None:
        cache = SQLiteCache(cache_path, "calls", "v1")
        cache.set("a", b"1")
        cache.get("a")
        cache.get("missing")
        cache.clear_all()
        s = cache.stats()
        assert s == {"hit": 0, "miss": 0, "size": 0}


class TestConcurrency:
    """并发写不冲突——每次 get/set 新开 connection，sqlite3 文件锁兜底。"""

    def test_concurrent_set_no_lost_writes(self, cache_path: Path) -> None:
        """20 个线程各写 5 个 key，全部应该存进去。"""
        cache = SQLiteCache(cache_path, "calls", "v1")
        n_threads = 20
        keys_per_thread = 5

        def writer(tid: int) -> None:
            for i in range(keys_per_thread):
                cache.set(f"t{tid}_k{i}", f"val_{tid}_{i}".encode())

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert cache.stats()["size"] == n_threads * keys_per_thread
        # 随机抽样验证内容
        assert cache.get("t0_k0") == b"val_0_0"
        assert cache.get("t19_k4") == b"val_19_4"

    def test_concurrent_read_during_write_no_crash(self, cache_path: Path) -> None:
        """读写混合不应该崩——验证 sqlite3 文件锁 + WAL 模式工作。"""
        cache = SQLiteCache(cache_path, "calls", "v1")
        cache.set("shared_key", b"initial")

        errors: list[Exception] = []

        def reader() -> None:
            try:
                for _ in range(50):
                    cache.get("shared_key")
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        def writer() -> None:
            try:
                for i in range(50):
                    cache.set("shared_key", f"v{i}".encode())
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [
            threading.Thread(target=reader),
            threading.Thread(target=writer),
            threading.Thread(target=reader),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"concurrent ops raised: {errors}"


class TestSqlInjectionDefense:
    """table_name 白名单校验防 SQL 注入。"""

    def test_table_name_with_semicolon_rejected(self, cache_path: Path) -> None:
        with pytest.raises(ValueError):
            SQLiteCache(cache_path, "calls; DROP TABLE", "v1")

    def test_table_name_with_space_rejected(self, cache_path: Path) -> None:
        with pytest.raises(ValueError):
            SQLiteCache(cache_path, "my calls", "v1")

    def test_table_name_starting_with_digit_rejected(self, cache_path: Path) -> None:
        with pytest.raises(ValueError):
            SQLiteCache(cache_path, "1calls", "v1")

    def test_empty_table_name_rejected(self, cache_path: Path) -> None:
        with pytest.raises(ValueError):
            SQLiteCache(cache_path, "", "v1")

    def test_underscore_table_name_accepted(self, cache_path: Path) -> None:
        # 不抛即可
        SQLiteCache(cache_path, "_internal_calls_v1", "v1")


class TestPathCreation:
    """db_path 父目录自动创建。"""

    def test_parent_directory_auto_created(self, tmp_path: Path) -> None:
        nested = tmp_path / "nested" / "deeper" / "cache.db"
        # 父目录不存在
        assert not nested.parent.exists()
        SQLiteCache(nested, "calls", "v1")
        assert nested.parent.exists()
