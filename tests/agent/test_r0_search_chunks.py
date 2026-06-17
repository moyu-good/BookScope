"""``R0SearchChunksBackend`` 单测。

关键原则：**不跑真 FAISS**。真 FAISS 需要 embedding 模型下载、GPU/CPU
算力预热，不适合单元测试。用一个假的 ``SessionVectorStore`` 替身
（``_FakeVectorStore``）返回可控的假 chunk 结果，验证 backend 的过滤、
归一化、降级行为。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import pytest

from bookscope.agent.backends import R0SearchChunksBackend
from bookscope.agent.tools import ChunkRetrievalBackend
from bookscope.agent.tools.schemas import ChunkMatch

# ---------------------------------------------------------------------------
# 测试替身：最小 ChunkResult 与假 SessionVectorStore
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _FakeChunk:
    """仅保留 ``R0SearchChunksBackend`` 实际用到的字段，
    避免把真 ``ChunkResult`` 的其它行为（word_count 自动计算）拖进测试。
    """

    index: int
    text: str


class _FakeVectorStore:
    """``SessionVectorStore.search`` 的行为替身。

    构造时传入 ``(chunk, raw_score)`` 的预置结果列表；每次 ``search``
    调用原样返回（按传入的 ``top_k`` 截断）。记录 ``last_query`` 与
    ``last_top_k`` 方便断言。
    """

    def __init__(self, results: Sequence[tuple[_FakeChunk, float]]) -> None:
        self._results = list(results)
        self.last_query: str | None = None
        self.last_top_k: int | None = None
        self.call_count = 0

    def search(
        self,
        query: str,
        top_k: int = 5,
    ) -> list[tuple[_FakeChunk, float]]:
        self.last_query = query
        self.last_top_k = top_k
        self.call_count += 1
        return list(self._results[:top_k])


class _FakeReranker:
    """``RerankerProvider.rerank`` 的行为替身。

    构造时传入一个把 ``documents`` 映射成 ``[(下标, 精排分), ...]`` 的函数，
    模拟模型的重排序。记录最后一次调用的 query / documents / top_n 便于断言。
    """

    def __init__(self, ranker) -> None:
        self._ranker = ranker
        self.last_query: str | None = None
        self.last_documents: list[str] | None = None
        self.last_top_n: int | None = None
        self.call_count = 0

    @property
    def name(self) -> str:
        return "fake/reranker"

    def rerank(self, query, documents, top_n=None):
        self.last_query = query
        self.last_documents = list(documents)
        self.last_top_n = top_n
        self.call_count += 1
        return self._ranker(documents)


class _ExplodingReranker:
    """每次 ``rerank`` 都抛异常的替身，验证失败退回。"""

    def __init__(self) -> None:
        self.call_count = 0

    @property
    def name(self) -> str:
        return "fake/exploding"

    def rerank(self, query, documents, top_n=None):
        self.call_count += 1
        raise RuntimeError("rerank API 超时")


# ---------------------------------------------------------------------------
# Fixture：一批覆盖多个章节、多角色的 chunk
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_chunks() -> list[_FakeChunk]:
    return [
        _FakeChunk(index=0, text="第一章原文片段：开国称帝。"),
        _FakeChunk(index=1, text="第一章原文片段：封赏功臣。"),
        _FakeChunk(index=2, text="第二章原文片段：边境烽火。"),
        _FakeChunk(index=3, text="第三章原文片段：宫廷阴谋。"),
        _FakeChunk(index=4, text="第五章原文片段：削藩风波。"),
    ]


@pytest.fixture()
def chunk_to_chapter() -> dict[int, int]:
    # chunk 0,1 在章 1；chunk 2 在章 2；chunk 3 在章 3；chunk 4 在章 5。
    return {0: 1, 1: 1, 2: 2, 3: 3, 4: 5}


@pytest.fixture()
def chunk_to_characters() -> dict[int, list[str]]:
    return {
        0: ["朱元璋"],
        1: ["朱元璋", "李善长"],
        2: ["徐达"],
        3: ["朱棣", "姚广孝"],
        # chunk 4 故意不提供——用于验证"缺失降级"分支。
    }


# ---------------------------------------------------------------------------
# 测试 1：Protocol 结构型检查
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_backend_satisfies_chunk_retrieval_backend_protocol(
        self,
        sample_chunks,
        chunk_to_chapter,
    ):
        """``R0SearchChunksBackend`` 必须满足 ``ChunkRetrievalBackend`` Protocol。"""
        store = _FakeVectorStore(results=[(sample_chunks[0], 1.0)])
        backend = R0SearchChunksBackend(
            store,
            chunk_index_to_chapter=chunk_to_chapter,
        )
        # ``ChunkRetrievalBackend`` 未加 runtime_checkable（ADR 层面的
        # Protocol 保持纯 typing 用途），此处做"鸭子类型"风格检查：
        # retrieve 必须可调用、参数签名兼容。
        assert hasattr(backend, "retrieve")
        assert callable(backend.retrieve)

        # 保证 isinstance 级检查也 OK：取出本地 Protocol 做 runtime_checkable
        # 替身的方式见下方 _RuntimeCheckableProtocol。
        assert _looks_like_chunk_retrieval_backend(backend)


def _looks_like_chunk_retrieval_backend(obj: object) -> bool:
    """以结构兼容性判断 obj 是否满足 ``ChunkRetrievalBackend``。"""
    retrieve = getattr(obj, "retrieve", None)
    if retrieve is None or not callable(retrieve):
        return False
    # 通过 annotations 做一次最小 sanity 检查（避免硬编码签名细节）。
    import inspect

    sig = inspect.signature(retrieve)
    required = {"query", "chapter_scope", "character_filter", "top_k"}
    return required.issubset(sig.parameters.keys())


# ---------------------------------------------------------------------------
# 测试 2：返回类型与 source_version
# ---------------------------------------------------------------------------


class TestReturnShape:
    def test_all_results_are_chunk_match_with_source_version_r0(
        self,
        sample_chunks,
        chunk_to_chapter,
        chunk_to_characters,
    ):
        store = _FakeVectorStore(
            results=[
                (sample_chunks[0], 0.9),
                (sample_chunks[1], 0.5),
            ],
        )
        backend = R0SearchChunksBackend(
            store,
            chunk_index_to_chapter=chunk_to_chapter,
            chunk_index_to_characters=chunk_to_characters,
        )
        results = backend.retrieve(
            query="开国",
            chapter_scope=None,
            character_filter=None,
            top_k=10,
        )
        assert len(results) == 2
        assert all(isinstance(r, ChunkMatch) for r in results)
        assert all(r.source_version == "r0" for r in results)
        # 分数归一后最高 1.0、最低 0.0（两条场景）。
        assert results[0].relevance_score == pytest.approx(1.0)
        assert results[1].relevance_score == pytest.approx(0.0)
        # chunk_id 拼接正确。
        assert results[0].chunk_id == "r0-chunk-0"
        assert results[1].chunk_id == "r0-chunk-1"


# ---------------------------------------------------------------------------
# 测试 3：chapter_scope 过滤
# ---------------------------------------------------------------------------


class TestChapterScopeFilter:
    def test_chapter_scope_excludes_out_of_range(
        self,
        sample_chunks,
        chunk_to_chapter,
        chunk_to_characters,
    ):
        """chunk 3（章 3）与 chunk 4（章 5）都应被 scope=(1, 2) 过滤掉。"""
        store = _FakeVectorStore(
            results=[
                (sample_chunks[0], 0.9),  # 章 1，保留
                (sample_chunks[2], 0.8),  # 章 2，保留
                (sample_chunks[3], 0.7),  # 章 3，过滤
                (sample_chunks[4], 0.6),  # 章 5，过滤
            ],
        )
        backend = R0SearchChunksBackend(
            store,
            chunk_index_to_chapter=chunk_to_chapter,
            chunk_index_to_characters=chunk_to_characters,
        )
        results = backend.retrieve(
            query="任意",
            chapter_scope=(1, 2),
            character_filter=None,
            top_k=10,
        )
        chapters = {r.chapter for r in results}
        assert chapters == {1, 2}
        # 严格验证没有越界章节混入
        assert all(1 <= r.chapter <= 2 for r in results)

    def test_chapter_scope_inclusive_endpoints(
        self,
        sample_chunks,
        chunk_to_chapter,
        chunk_to_characters,
    ):
        """scope=(3, 3) 应仅保留章 3 的 chunk（端点含）。"""
        store = _FakeVectorStore(
            results=[
                (sample_chunks[2], 0.9),  # 章 2
                (sample_chunks[3], 0.8),  # 章 3
                (sample_chunks[4], 0.7),  # 章 5
            ],
        )
        backend = R0SearchChunksBackend(
            store,
            chunk_index_to_chapter=chunk_to_chapter,
            chunk_index_to_characters=chunk_to_characters,
        )
        results = backend.retrieve(
            query="任意",
            chapter_scope=(3, 3),
            character_filter=None,
            top_k=10,
        )
        assert len(results) == 1
        assert results[0].chapter == 3


# ---------------------------------------------------------------------------
# 测试 4：character_filter 过滤
# ---------------------------------------------------------------------------


class TestCharacterFilter:
    def test_character_filter_keeps_only_matching_chunks(
        self,
        sample_chunks,
        chunk_to_chapter,
        chunk_to_characters,
    ):
        """只保留涉及 "朱元璋" 的 chunk（chunk 0、1 含，chunk 2、3 不含）。"""
        store = _FakeVectorStore(
            results=[
                (sample_chunks[0], 0.9),
                (sample_chunks[1], 0.8),
                (sample_chunks[2], 0.7),
                (sample_chunks[3], 0.6),
            ],
        )
        backend = R0SearchChunksBackend(
            store,
            chunk_index_to_chapter=chunk_to_chapter,
            chunk_index_to_characters=chunk_to_characters,
        )
        results = backend.retrieve(
            query="任意",
            chapter_scope=None,
            character_filter=["朱元璋"],
            top_k=10,
        )
        assert len(results) == 2
        assert all("朱元璋" in r.contains_characters for r in results)

    def test_character_filter_with_chunk_missing_character_mapping_excluded(
        self,
        sample_chunks,
        chunk_to_chapter,
        chunk_to_characters,
    ):
        """chunk 4 在角色映射中缺失，``character_filter`` 传入时不应命中。"""
        store = _FakeVectorStore(
            results=[
                (sample_chunks[4], 0.9),  # 无角色映射
                (sample_chunks[0], 0.5),  # 有 "朱元璋"
            ],
        )
        backend = R0SearchChunksBackend(
            store,
            chunk_index_to_chapter=chunk_to_chapter,
            chunk_index_to_characters=chunk_to_characters,
        )
        results = backend.retrieve(
            query="任意",
            chapter_scope=None,
            character_filter=["朱元璋"],
            top_k=10,
        )
        assert len(results) == 1
        assert results[0].chunk_id == "r0-chunk-0"

    def test_character_filter_multi_names_is_or_semantics(
        self,
        sample_chunks,
        chunk_to_chapter,
        chunk_to_characters,
    ):
        """``character_filter`` 传多个名字是 OR：任一命中即保留。"""
        store = _FakeVectorStore(
            results=[
                (sample_chunks[0], 0.9),  # 朱元璋
                (sample_chunks[2], 0.8),  # 徐达
                (sample_chunks[3], 0.7),  # 朱棣、姚广孝
            ],
        )
        backend = R0SearchChunksBackend(
            store,
            chunk_index_to_chapter=chunk_to_chapter,
            chunk_index_to_characters=chunk_to_characters,
        )
        results = backend.retrieve(
            query="任意",
            chapter_scope=None,
            character_filter=["朱元璋", "朱棣"],
            top_k=10,
        )
        ids = {r.chunk_id for r in results}
        assert ids == {"r0-chunk-0", "r0-chunk-3"}


# ---------------------------------------------------------------------------
# 测试 5：top_k 限制
# ---------------------------------------------------------------------------


class TestTopKLimit:
    def test_returns_no_more_than_top_k(
        self,
        sample_chunks,
        chunk_to_chapter,
        chunk_to_characters,
    ):
        store = _FakeVectorStore(
            results=[(c, 1.0 - i * 0.1) for i, c in enumerate(sample_chunks)],
        )
        backend = R0SearchChunksBackend(
            store,
            chunk_index_to_chapter=chunk_to_chapter,
            chunk_index_to_characters=chunk_to_characters,
        )
        results = backend.retrieve(
            query="任意",
            chapter_scope=None,
            character_filter=None,
            top_k=2,
        )
        assert len(results) == 2

    def test_oversample_factor_expands_fetch(
        self,
        sample_chunks,
        chunk_to_chapter,
        chunk_to_characters,
    ):
        """backend 向 r0 store 请求时应放大 ``top_k * oversample_factor``。"""
        store = _FakeVectorStore(
            results=[(c, 1.0 - i * 0.1) for i, c in enumerate(sample_chunks)],
        )
        backend = R0SearchChunksBackend(
            store,
            chunk_index_to_chapter=chunk_to_chapter,
            chunk_index_to_characters=chunk_to_characters,
            oversample_factor=4,
        )
        _ = backend.retrieve(
            query="任意",
            chapter_scope=None,
            character_filter=None,
            top_k=3,
        )
        assert store.last_top_k == 12  # 3 * 4
        assert store.last_query == "任意"


# ---------------------------------------------------------------------------
# 测试 6：空结果不抛错
# ---------------------------------------------------------------------------


class TestEmptyResults:
    def test_empty_store_returns_empty_list(
        self,
        chunk_to_chapter,
    ):
        store = _FakeVectorStore(results=[])
        backend = R0SearchChunksBackend(
            store,
            chunk_index_to_chapter=chunk_to_chapter,
        )
        results = backend.retrieve(
            query="任意",
            chapter_scope=None,
            character_filter=None,
            top_k=10,
        )
        assert results == []

    def test_all_filtered_out_returns_empty_list(
        self,
        sample_chunks,
        chunk_to_chapter,
        chunk_to_characters,
    ):
        """章节 scope 把全部候选过滤掉时应返回空列表，不抛错。"""
        store = _FakeVectorStore(
            results=[(sample_chunks[0], 0.9), (sample_chunks[1], 0.8)],
        )
        backend = R0SearchChunksBackend(
            store,
            chunk_index_to_chapter=chunk_to_chapter,
            chunk_index_to_characters=chunk_to_characters,
        )
        results = backend.retrieve(
            query="任意",
            chapter_scope=(99, 100),  # 超出所有 chunk
            character_filter=None,
            top_k=10,
        )
        assert results == []


# ---------------------------------------------------------------------------
# 测试 7：字段缺失的降级行为
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    def test_missing_character_mapping_yields_empty_characters_list(
        self,
        sample_chunks,
        chunk_to_chapter,
    ):
        """不传 ``chunk_index_to_characters`` 时，所有 chunk 的角色列表应为 []，
        但本身不该抛错（只有在 character_filter 传入时才会因缺失过滤掉）。
        """
        store = _FakeVectorStore(
            results=[(sample_chunks[0], 0.9)],
        )
        backend = R0SearchChunksBackend(
            store,
            chunk_index_to_chapter=chunk_to_chapter,
        )
        results = backend.retrieve(
            query="任意",
            chapter_scope=None,
            character_filter=None,
            top_k=10,
        )
        assert len(results) == 1
        assert results[0].contains_characters == []

    def test_chunk_without_chapter_mapping_is_skipped(
        self,
        sample_chunks,
    ):
        """r0 store 返回的 chunk 如果在 ``chunk_index_to_chapter`` 中没有映射，
        应被静默跳过而非抛错——相当于 "r0 的这条数据 r1 还无法解读"。
        """
        store = _FakeVectorStore(
            results=[
                (sample_chunks[0], 0.9),
                (sample_chunks[1], 0.8),
            ],
        )
        # 只给 chunk 0 映射到章 1；chunk 1 故意不映射。
        backend = R0SearchChunksBackend(
            store,
            chunk_index_to_chapter={0: 1},
        )
        results = backend.retrieve(
            query="任意",
            chapter_scope=None,
            character_filter=None,
            top_k=10,
        )
        assert len(results) == 1
        assert results[0].chunk_id == "r0-chunk-0"

    def test_single_result_gets_score_one(
        self,
        sample_chunks,
        chunk_to_chapter,
    ):
        """只有一条结果时，归一化逻辑应把它定为 1.0（避免 0/0）。"""
        store = _FakeVectorStore(results=[(sample_chunks[0], 42.0)])
        backend = R0SearchChunksBackend(
            store,
            chunk_index_to_chapter=chunk_to_chapter,
        )
        results = backend.retrieve(
            query="任意",
            chapter_scope=None,
            character_filter=None,
            top_k=10,
        )
        assert len(results) == 1
        assert results[0].relevance_score == pytest.approx(1.0)

    def test_equal_scores_all_normalised_to_one(
        self,
        sample_chunks,
        chunk_to_chapter,
    ):
        """所有原始分数相等时，归一化应给每条都打 1.0（同等相关）。"""
        store = _FakeVectorStore(
            results=[
                (sample_chunks[0], 0.5),
                (sample_chunks[1], 0.5),
                (sample_chunks[2], 0.5),
            ],
        )
        backend = R0SearchChunksBackend(
            store,
            chunk_index_to_chapter=chunk_to_chapter,
        )
        results = backend.retrieve(
            query="任意",
            chapter_scope=None,
            character_filter=None,
            top_k=10,
        )
        assert len(results) == 3
        for r in results:
            assert r.relevance_score == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 测试 8：retrieval_mode 透传（WP2a 检索降级可见）
# ---------------------------------------------------------------------------


class TestRetrievalModePassthrough:
    def test_store_with_retrieval_mode_fills_chunk_match(
        self,
        sample_chunks,
        chunk_to_chapter,
    ):
        """store 带 ``retrieval_mode`` 属性时，每条 ChunkMatch 都该如实带上。"""
        store = _FakeVectorStore(
            results=[
                (sample_chunks[0], 0.9),
                (sample_chunks[1], 0.5),
            ],
        )
        store.retrieval_mode = "bm25_only"
        backend = R0SearchChunksBackend(
            store,
            chunk_index_to_chapter=chunk_to_chapter,
        )
        results = backend.retrieve(
            query="任意",
            chapter_scope=None,
            character_filter=None,
            top_k=10,
        )
        assert len(results) == 2
        assert all(r.retrieval_mode == "bm25_only" for r in results)

    def test_store_without_retrieval_mode_yields_none(
        self,
        sample_chunks,
        chunk_to_chapter,
    ):
        """老 store / Mock 没有 ``retrieval_mode`` 属性时，字段为 None 且不抛错。"""
        store = _FakeVectorStore(results=[(sample_chunks[0], 0.9)])
        assert not hasattr(store, "retrieval_mode")
        backend = R0SearchChunksBackend(
            store,
            chunk_index_to_chapter=chunk_to_chapter,
        )
        results = backend.retrieve(
            query="任意",
            chapter_scope=None,
            character_filter=None,
            top_k=10,
        )
        assert len(results) == 1
        assert results[0].retrieval_mode is None


# ---------------------------------------------------------------------------
# 测试 9：保证 dispatcher 层 Protocol 引用通畅
# ---------------------------------------------------------------------------


def test_backend_can_be_passed_where_protocol_is_expected(
    sample_chunks,
    chunk_to_chapter,
):
    """接 dispatcher 的路径：R0SearchChunksBackend 可以作为
    ``ChunkRetrievalBackend`` 参数传入（类型系统与运行期都通过）。

    dispatcher 本身仍是 NotImplementedError 占位，此处只验证 "参数传递路径
    本身打通"——下一轮把 dispatcher 切换为 delegate 后这个用例就会成为
    端到端契约的最小证据。
    """
    store = _FakeVectorStore(results=[(sample_chunks[0], 1.0)])
    backend: ChunkRetrievalBackend = R0SearchChunksBackend(
        store,
        chunk_index_to_chapter=chunk_to_chapter,
    )
    result = backend.retrieve(
        query="开国",
        chapter_scope=None,
        character_filter=None,
        top_k=5,
    )
    assert len(result) == 1
    assert result[0].source_version == "r0"


# ---------------------------------------------------------------------------
# 测试 10：rerank 三条路径（WP-reranker-api）
# ---------------------------------------------------------------------------


class TestRerank:
    """覆盖设计稿第 4/5 节三条路径：有 provider 跑通 / None 跳过 / 异常退回。"""

    def test_rerank_reorders_and_marks_hybrid_rerank(
        self,
        sample_chunks,
        chunk_to_chapter,
    ):
        """有 reranker：按精排分重排，retrieval_mode 升成 hybrid_rerank。

        store 给的原始分把 chunk 0 排最前（0.9），但 reranker 故意把最后一条
        （chunk 2）顶到第一。验证最终顺序按精排分、且 mode 标 hybrid_rerank。
        """
        store = _FakeVectorStore(
            results=[
                (sample_chunks[0], 0.9),
                (sample_chunks[1], 0.8),
                (sample_chunks[2], 0.7),
            ],
        )
        store.retrieval_mode = "hybrid"

        # reranker：把候选倒序——最后一条精排分最高。
        def _reverse_rank(documents):
            n = len(documents)
            return [(i, float(n - i)) for i in range(n - 1, -1, -1)]

        reranker = _FakeReranker(_reverse_rank)
        backend = R0SearchChunksBackend(
            store,
            chunk_index_to_chapter=chunk_to_chapter,
            reranker=reranker,
        )
        results = backend.retrieve(
            query="开国",
            chapter_scope=None,
            character_filter=None,
            top_k=3,
        )

        assert reranker.call_count == 1
        # 整批过滤后的候选都发去了 rerank（不是先截断再 rerank）。
        assert reranker.last_documents == [
            sample_chunks[0].text,
            sample_chunks[1].text,
            sample_chunks[2].text,
        ]
        assert reranker.last_top_n == 3
        # 精排把 chunk 2 顶到第一、chunk 0 沉到最后。
        assert [r.chunk_id for r in results] == [
            "r0-chunk-2",
            "r0-chunk-1",
            "r0-chunk-0",
        ]
        # 真跑成功 → mode 升档。
        assert all(r.retrieval_mode == "hybrid_rerank" for r in results)

    def test_rerank_bm25_only_marks_bm25_rerank(
        self,
        sample_chunks,
        chunk_to_chapter,
    ):
        """无向量（bm25_only）+ rerank 跑了 → mode 标 bm25_rerank。"""
        store = _FakeVectorStore(
            results=[(sample_chunks[0], 0.9), (sample_chunks[1], 0.5)],
        )
        store.retrieval_mode = "bm25_only"
        reranker = _FakeReranker(
            lambda docs: [(i, float(len(docs) - i)) for i in range(len(docs))]
        )
        backend = R0SearchChunksBackend(
            store,
            chunk_index_to_chapter=chunk_to_chapter,
            reranker=reranker,
        )
        results = backend.retrieve(
            query="任意",
            chapter_scope=None,
            character_filter=None,
            top_k=5,
        )
        assert all(r.retrieval_mode == "bm25_rerank" for r in results)

    def test_no_reranker_skips_and_keeps_mode(
        self,
        sample_chunks,
        chunk_to_chapter,
    ):
        """reranker 为 None（无 key）：跳过 rerank，顺序按原始分、mode 不带 _rerank。"""
        store = _FakeVectorStore(
            results=[
                (sample_chunks[0], 0.9),
                (sample_chunks[1], 0.5),
                (sample_chunks[2], 0.3),
            ],
        )
        store.retrieval_mode = "hybrid"
        backend = R0SearchChunksBackend(
            store,
            chunk_index_to_chapter=chunk_to_chapter,
            reranker=None,
            # 显式传 None 还不够——构造函数 None 时会去调工厂；这里用 monkeypatch
            # 的替代是直接验证默认工厂在测试环境（无 key、开关 off）返回 None。
        )
        results = backend.retrieve(
            query="任意",
            chapter_scope=None,
            character_filter=None,
            top_k=3,
        )
        # 顺序按原始分降序，没被重排。
        assert [r.chunk_id for r in results] == [
            "r0-chunk-0",
            "r0-chunk-1",
            "r0-chunk-2",
        ]
        # mode 保持基础值，不带 _rerank。
        assert all(r.retrieval_mode == "hybrid" for r in results)
        assert all("_rerank" not in r.retrieval_mode for r in results)

    def test_rerank_exception_falls_back_to_raw_order(
        self,
        sample_chunks,
        chunk_to_chapter,
    ):
        """reranker 抛异常：退回原始分排序 + mode 保持 hybrid + 不崩。"""
        store = _FakeVectorStore(
            results=[
                (sample_chunks[0], 0.9),
                (sample_chunks[1], 0.5),
                (sample_chunks[2], 0.3),
            ],
        )
        store.retrieval_mode = "hybrid"
        reranker = _ExplodingReranker()
        backend = R0SearchChunksBackend(
            store,
            chunk_index_to_chapter=chunk_to_chapter,
            reranker=reranker,
        )
        results = backend.retrieve(
            query="任意",
            chapter_scope=None,
            character_filter=None,
            top_k=3,
        )
        assert reranker.call_count == 1
        # 退回原始分降序，没崩。
        assert [r.chunk_id for r in results] == [
            "r0-chunk-0",
            "r0-chunk-1",
            "r0-chunk-2",
        ]
        # 没真成功 → 不许标 _rerank，保持基础值。
        assert all(r.retrieval_mode == "hybrid" for r in results)

    def test_rerank_empty_result_falls_back(
        self,
        sample_chunks,
        chunk_to_chapter,
    ):
        """reranker 返回空 / 全越界：当失败处理，退回原序、不标 _rerank。"""
        store = _FakeVectorStore(
            results=[(sample_chunks[0], 0.9), (sample_chunks[1], 0.5)],
        )
        store.retrieval_mode = "hybrid"
        # 返回越界下标，应被跳过 → reranked 为空 → 退回。
        reranker = _FakeReranker(lambda docs: [(999, 5.0)])
        backend = R0SearchChunksBackend(
            store,
            chunk_index_to_chapter=chunk_to_chapter,
            reranker=reranker,
        )
        results = backend.retrieve(
            query="任意",
            chapter_scope=None,
            character_filter=None,
            top_k=5,
        )
        assert [r.chunk_id for r in results] == ["r0-chunk-0", "r0-chunk-1"]
        assert all(r.retrieval_mode == "hybrid" for r in results)

    def test_default_factory_returns_none_without_key(
        self,
        sample_chunks,
        chunk_to_chapter,
        monkeypatch,
    ):
        """不传 reranker + 无 key + 开关默认 off：工厂给 None，行为跟今天一样。"""
        monkeypatch.delenv("BOOKSCOPE_RERANK", raising=False)
        monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
        store = _FakeVectorStore(results=[(sample_chunks[0], 0.9)])
        store.retrieval_mode = "hybrid"
        backend = R0SearchChunksBackend(
            store,
            chunk_index_to_chapter=chunk_to_chapter,
        )
        assert backend._reranker is None
        results = backend.retrieve(
            query="任意",
            chapter_scope=None,
            character_filter=None,
            top_k=5,
        )
        assert results[0].retrieval_mode == "hybrid"


# ---------------------------------------------------------------------------
# 测试 11：oversample 可配（BOOKSCOPE_RERANK_OVERSAMPLE）
# ---------------------------------------------------------------------------


class TestOversampleConfig:
    def test_default_oversample_is_four(
        self,
        sample_chunks,
        chunk_to_chapter,
        monkeypatch,
    ):
        """不传 oversample_factor、无环境变量时，默认倍数为 4。"""
        monkeypatch.delenv("BOOKSCOPE_RERANK_OVERSAMPLE", raising=False)
        store = _FakeVectorStore(
            results=[(c, 1.0 - i * 0.1) for i, c in enumerate(sample_chunks)],
        )
        backend = R0SearchChunksBackend(
            store,
            chunk_index_to_chapter=chunk_to_chapter,
        )
        backend.retrieve(
            query="任意",
            chapter_scope=None,
            character_filter=None,
            top_k=3,
        )
        assert store.last_top_k == 12  # 3 * 4

    def test_env_var_overrides_oversample(
        self,
        sample_chunks,
        chunk_to_chapter,
        monkeypatch,
    ):
        """环境变量 BOOKSCOPE_RERANK_OVERSAMPLE 覆盖默认倍数。"""
        monkeypatch.setenv("BOOKSCOPE_RERANK_OVERSAMPLE", "5")
        store = _FakeVectorStore(
            results=[(c, 1.0 - i * 0.1) for i, c in enumerate(sample_chunks)],
        )
        backend = R0SearchChunksBackend(
            store,
            chunk_index_to_chapter=chunk_to_chapter,
        )
        backend.retrieve(
            query="任意",
            chapter_scope=None,
            character_filter=None,
            top_k=2,
        )
        assert store.last_top_k == 10  # 2 * 5

    def test_explicit_arg_beats_env_var(
        self,
        sample_chunks,
        chunk_to_chapter,
        monkeypatch,
    ):
        """显式 oversample_factor 参数优先于环境变量。"""
        monkeypatch.setenv("BOOKSCOPE_RERANK_OVERSAMPLE", "5")
        store = _FakeVectorStore(
            results=[(c, 1.0 - i * 0.1) for i, c in enumerate(sample_chunks)],
        )
        backend = R0SearchChunksBackend(
            store,
            chunk_index_to_chapter=chunk_to_chapter,
            oversample_factor=2,
        )
        backend.retrieve(
            query="任意",
            chapter_scope=None,
            character_filter=None,
            top_k=3,
        )
        assert store.last_top_k == 6  # 3 * 2
