"""``search_chunks_cached`` wrapper 单测 —— Sprint 8 W1。

覆盖：
- 首次 miss + 写缓存
- 二次同参数 hit + 跳过 backend
- 不同字段（query / chapter_scope / character_filter / top_k / session_id）不命中
- 大小写 / 首尾空格归一化后命中
- character_filter 顺序不影响命中
- session_id=None 降级（不走缓存）
- clear_session_search_cache 清完 session 的条目后下次 miss
"""

from __future__ import annotations

from typing import Any

import pytest

from bookscope.agent._internal.search_cache import (
    _compute_search_cache_key,
    clear_session_search_cache,
    get_search_cache_stats,
    reset_search_cache,
    search_chunks_cached,
)
from bookscope.agent.tools.schemas import ChunkMatch


@pytest.fixture(autouse=True)
def _isolated_cache() -> None:
    """每条测试前清掉模块单例，避免互扰。"""
    reset_search_cache()


def _make_match(chapter: int = 1, text: str = "原文") -> ChunkMatch:
    return ChunkMatch(
        chunk_id=f"test-chunk-{chapter}",
        chapter=chapter,
        text=text,
        relevance_score=1.0,
        contains_characters=[],
        source_version="r0",
    )


class _FakeBackend:
    """记录 retrieve 调用次数与参数。"""

    def __init__(self, returns: list[ChunkMatch] | None = None) -> None:
        self._returns = returns or [_make_match()]
        self.calls: list[dict[str, Any]] = []

    def retrieve(
        self,
        query: str,
        chapter_scope: tuple[int, int] | None,
        character_filter: list[str] | None,
        top_k: int,
    ) -> list[ChunkMatch]:
        self.calls.append(
            {
                "query": query,
                "chapter_scope": chapter_scope,
                "character_filter": character_filter,
                "top_k": top_k,
            }
        )
        return self._returns


class TestCacheKeyCompute:
    """``_compute_search_cache_key`` 算法。"""

    def test_same_inputs_same_key(self) -> None:
        k1 = _compute_search_cache_key("s1", "找曾国藩", None, None, 10)
        k2 = _compute_search_cache_key("s1", "找曾国藩", None, None, 10)
        assert k1 == k2

    def test_session_id_prefix_present(self) -> None:
        k = _compute_search_cache_key("sess_xyz", "q", None, None, 10)
        assert k.startswith("sess_xyz:")

    def test_query_case_normalized(self) -> None:
        k1 = _compute_search_cache_key("s1", "Hello", None, None, 10)
        k2 = _compute_search_cache_key("s1", "hello", None, None, 10)
        k3 = _compute_search_cache_key("s1", "  hello  ", None, None, 10)
        assert k1 == k2 == k3

    def test_character_filter_order_insensitive(self) -> None:
        k1 = _compute_search_cache_key("s1", "q", None, ["李", "张"], 10)
        k2 = _compute_search_cache_key("s1", "q", None, ["张", "李"], 10)
        assert k1 == k2

    def test_different_top_k_different_key(self) -> None:
        k1 = _compute_search_cache_key("s1", "q", None, None, 5)
        k2 = _compute_search_cache_key("s1", "q", None, None, 10)
        assert k1 != k2

    def test_different_chapter_scope_different_key(self) -> None:
        k1 = _compute_search_cache_key("s1", "q", None, None, 10)
        k2 = _compute_search_cache_key("s1", "q", (1, 5), None, 10)
        assert k1 != k2


class TestCachedRetrieveBasic:
    """wrapper 基本 hit / miss 语义。"""

    def test_first_call_misses_and_caches(self) -> None:
        backend = _FakeBackend(returns=[_make_match(chapter=3)])
        result = search_chunks_cached(
            backend, session_id="s1", query="q",
        )
        assert len(backend.calls) == 1
        assert len(result) == 1
        assert result[0].chapter == 3

    def test_second_same_call_hits(self) -> None:
        backend = _FakeBackend()
        search_chunks_cached(backend, session_id="s1", query="q")
        search_chunks_cached(backend, session_id="s1", query="q")
        assert len(backend.calls) == 1  # 第二次没调 backend

    def test_case_and_whitespace_normalized_hit(self) -> None:
        backend = _FakeBackend()
        search_chunks_cached(backend, session_id="s1", query="Question")
        search_chunks_cached(backend, session_id="s1", query="question")
        search_chunks_cached(backend, session_id="s1", query="  question ")
        assert len(backend.calls) == 1


class TestCachedRetrieveKeyDifferentiation:
    """不同 key 字段不命中。"""

    def test_different_query_misses(self) -> None:
        backend = _FakeBackend()
        search_chunks_cached(backend, session_id="s1", query="q1")
        search_chunks_cached(backend, session_id="s1", query="q2")
        assert len(backend.calls) == 2

    def test_different_session_id_misses(self) -> None:
        backend = _FakeBackend()
        search_chunks_cached(backend, session_id="s1", query="q")
        search_chunks_cached(backend, session_id="s2", query="q")
        assert len(backend.calls) == 2

    def test_different_character_filter_misses(self) -> None:
        backend = _FakeBackend()
        search_chunks_cached(
            backend, session_id="s1", query="q", character_filter=["李"],
        )
        search_chunks_cached(
            backend, session_id="s1", query="q", character_filter=["张"],
        )
        assert len(backend.calls) == 2

    def test_different_chapter_scope_misses(self) -> None:
        backend = _FakeBackend()
        search_chunks_cached(
            backend, session_id="s1", query="q", chapter_scope=(1, 5),
        )
        search_chunks_cached(
            backend, session_id="s1", query="q", chapter_scope=(6, 10),
        )
        assert len(backend.calls) == 2

    def test_different_top_k_misses(self) -> None:
        backend = _FakeBackend()
        search_chunks_cached(backend, session_id="s1", query="q", top_k=5)
        search_chunks_cached(backend, session_id="s1", query="q", top_k=10)
        assert len(backend.calls) == 2

    def test_character_filter_order_hits(self) -> None:
        backend = _FakeBackend()
        search_chunks_cached(
            backend, session_id="s1", query="q", character_filter=["李", "张"],
        )
        search_chunks_cached(
            backend, session_id="s1", query="q", character_filter=["张", "李"],
        )
        assert len(backend.calls) == 1


class TestSessionIdNoneFallback:
    """session_id=None 降级行为。"""

    def test_session_id_none_skips_cache(self) -> None:
        backend = _FakeBackend()
        search_chunks_cached(backend, session_id=None, query="q")
        search_chunks_cached(backend, session_id=None, query="q")
        assert len(backend.calls) == 2  # 没缓存

    def test_session_id_none_returns_backend_result(self) -> None:
        backend = _FakeBackend(returns=[_make_match(chapter=7)])
        result = search_chunks_cached(backend, session_id=None, query="q")
        assert result[0].chapter == 7


class TestClearSession:
    """clear_session_search_cache 行为。"""

    def test_clear_session_makes_next_call_miss(self) -> None:
        backend = _FakeBackend()
        search_chunks_cached(backend, session_id="s1", query="q")
        removed = clear_session_search_cache("s1")
        assert removed == 1
        search_chunks_cached(backend, session_id="s1", query="q")
        assert len(backend.calls) == 2

    def test_clear_session_isolates_other_sessions(self) -> None:
        backend = _FakeBackend()
        search_chunks_cached(backend, session_id="s1", query="q")
        search_chunks_cached(backend, session_id="s2", query="q")
        clear_session_search_cache("s1")
        # s2 仍然命中
        search_chunks_cached(backend, session_id="s2", query="q")
        assert len(backend.calls) == 2  # 共 2 次 backend 调用


class TestStatsExposed:
    """get_search_cache_stats 暴露 L1 stats。"""

    def test_stats_reflect_hits_and_misses(self) -> None:
        backend = _FakeBackend()
        search_chunks_cached(backend, session_id="s1", query="q")
        search_chunks_cached(backend, session_id="s1", query="q")
        s = get_search_cache_stats()
        assert s["miss"] == 1
        assert s["hit"] == 1
        assert s["size"] == 1


class TestBackendExceptionPassthrough:
    """backend 抛错时不缓存且向上抛。"""

    def test_exception_not_cached(self) -> None:
        class _Raising:
            def __init__(self) -> None:
                self.calls = 0

            def retrieve(self, **kwargs: Any) -> list[ChunkMatch]:
                self.calls += 1
                raise RuntimeError("boom")

        backend = _Raising()
        with pytest.raises(RuntimeError):
            search_chunks_cached(backend, session_id="s1", query="q")
        with pytest.raises(RuntimeError):
            search_chunks_cached(backend, session_id="s1", query="q")
        assert backend.calls == 2  # 第二次也调了，没缓存失败
