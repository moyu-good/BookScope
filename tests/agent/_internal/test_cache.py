"""``bookscope.agent._internal.cache.LRUCache`` 单测 —— Sprint 8 W1。"""

from __future__ import annotations

import pytest

from bookscope.agent._internal.cache import LRUCache


class TestLRUCacheBasic:
    """get / set / miss / hit 基础语义。"""

    def test_get_miss_returns_none(self) -> None:
        cache = LRUCache(max_size=10)
        assert cache.get("nope") is None

    def test_set_then_get_hit(self) -> None:
        cache = LRUCache(max_size=10)
        cache.set("k1", "v1")
        assert cache.get("k1") == "v1"

    def test_overwrite_existing_key(self) -> None:
        cache = LRUCache(max_size=10)
        cache.set("k1", "v1")
        cache.set("k1", "v2")
        assert cache.get("k1") == "v2"
        assert cache.stats()["size"] == 1

    def test_max_size_must_be_positive(self) -> None:
        with pytest.raises(ValueError):
            LRUCache(max_size=0)

    def test_len_and_contains(self) -> None:
        cache = LRUCache(max_size=10)
        cache.set("k1", "v1")
        assert len(cache) == 1
        assert "k1" in cache
        assert "k2" not in cache


class TestLRUEviction:
    """LRU 淘汰行为。"""

    def test_eviction_when_full(self) -> None:
        cache = LRUCache(max_size=3)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        cache.set("d", 4)  # 淘汰 "a"
        assert cache.get("a") is None
        assert cache.get("b") == 2
        assert cache.get("c") == 3
        assert cache.get("d") == 4
        assert cache.stats()["evict"] == 1

    def test_get_marks_recently_used(self) -> None:
        cache = LRUCache(max_size=3)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        cache.get("a")  # a 变成最近
        cache.set("d", 4)  # 淘汰最久未访问的 b
        assert cache.get("a") == 1
        assert cache.get("b") is None
        assert cache.get("c") == 3
        assert cache.get("d") == 4

    def test_set_existing_does_not_evict(self) -> None:
        cache = LRUCache(max_size=2)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("a", 99)  # 覆盖不算新增
        assert cache.stats()["size"] == 2
        assert cache.stats()["evict"] == 0


class TestClearSession:
    """clear_session 按前缀清。"""

    def test_clear_session_removes_only_matching_prefix(self) -> None:
        cache = LRUCache(max_size=10)
        cache.set("sess_A:k1", 1)
        cache.set("sess_A:k2", 2)
        cache.set("sess_B:k1", 3)
        cache.set("other:k1", 4)

        removed = cache.clear_session("sess_A")
        assert removed == 2
        assert cache.get("sess_A:k1") is None
        assert cache.get("sess_A:k2") is None
        assert cache.get("sess_B:k1") == 3
        assert cache.get("other:k1") == 4

    def test_clear_session_no_match_returns_zero(self) -> None:
        cache = LRUCache(max_size=10)
        cache.set("sess_A:k1", 1)
        removed = cache.clear_session("nonexistent")
        assert removed == 0
        assert cache.get("sess_A:k1") == 1

    def test_clear_session_does_not_count_as_evict(self) -> None:
        cache = LRUCache(max_size=10)
        cache.set("sess_A:k1", 1)
        cache.clear_session("sess_A")
        assert cache.stats()["evict"] == 0

    def test_prefix_must_be_followed_by_colon(self) -> None:
        # 防止 "sess_A" 误清掉 "sess_AB" 起头的 key
        cache = LRUCache(max_size=10)
        cache.set("sess_A:k1", 1)
        cache.set("sess_AB:k1", 2)
        cache.clear_session("sess_A")
        assert cache.get("sess_A:k1") is None
        assert cache.get("sess_AB:k1") == 2


class TestStats:
    """stats 数字准确性。"""

    def test_stats_initial(self) -> None:
        cache = LRUCache(max_size=10)
        s = cache.stats()
        assert s == {"hit": 0, "miss": 0, "evict": 0, "size": 0}

    def test_stats_hits_and_misses(self) -> None:
        cache = LRUCache(max_size=10)
        cache.set("a", 1)
        cache.get("a")  # hit
        cache.get("a")  # hit
        cache.get("b")  # miss
        cache.get("c")  # miss
        s = cache.stats()
        assert s["hit"] == 2
        assert s["miss"] == 2
        assert s["size"] == 1

    def test_stats_evicts_after_overflow(self) -> None:
        cache = LRUCache(max_size=2)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        cache.set("d", 4)
        assert cache.stats()["evict"] == 2

    def test_stats_size_reflects_current(self) -> None:
        cache = LRUCache(max_size=10)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        assert cache.stats()["size"] == 3

    def test_clear_all_resets_everything(self) -> None:
        cache = LRUCache(max_size=10)
        cache.set("a", 1)
        cache.get("a")
        cache.get("missing")
        cache.clear_all()
        s = cache.stats()
        assert s == {"hit": 0, "miss": 0, "evict": 0, "size": 0}
