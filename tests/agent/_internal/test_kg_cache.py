"""``bookscope.agent._internal.kg_cache`` 单测 —— Sprint 6 第二步。

覆盖：

- 首次抽取 cache miss + 写入；二次同 ``(chunks, system_prompt, model)`` 命中
- 不同 chunks 不命中（chunk text 改 / chunk 顺序改 / chunk index 改）
- 不同 system_prompt 不命中（即便 chunks 相同）
- 不同 model 不命中
- env ``BOOKSCOPE_KG_CACHE_DISABLED=1`` 关缓存
- schema_version 升级 invalidate
- 跟 ``MinimalKGExtractor`` 集成：相同 batch 第二次 ``extract`` 跳 LLM
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from bookscope.agent._internal import kg_cache as kg_cache_mod
from bookscope.agent._internal.kg_cache import (
    _compute_kg_cache_key,
    _deserialize_entries,
    _serialize_entries,
    clear_kg_cache,
    extract_batch_cached,
    get_kg_cache_stats,
    invalidate_by_schema_version,
    reset_kg_cache_singleton_for_test,
)
from bookscope.agent.backends.minimal_kg_extractor import MinimalKGExtractor
from bookscope.models import BookText
from bookscope.models.schemas import ChunkResult


@pytest.fixture(autouse=True)
def isolated_cache_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """本模块测试用独立 DB 文件。全局 conftest 已 autouse 同款，本 fixture
    显式再设一遍是为了让 ``test_schema_version_invalidate`` 之类显式重建
    singleton 的用例语义更清晰——读起来不需要追溯到 conftest。"""
    monkeypatch.setenv(
        "BOOKSCOPE_KG_CACHE_DB_PATH", str(tmp_path / "kg.db")
    )
    reset_kg_cache_singleton_for_test()
    yield
    reset_kg_cache_singleton_for_test()


def _chunks(texts: list[str], start_index: int = 0) -> list[ChunkResult]:
    return [
        ChunkResult(index=start_index + i, text=t) for i, t in enumerate(texts)
    ]


def _entries() -> list[dict[str, Any]]:
    return [
        {
            "name": "朱元璋",
            "canonical_name": "朱元璋",
            "key_chapter_indices": [1, 2, 3],
        },
        {
            "name": "刘伯温",
            "canonical_name": "刘基",
            "key_chapter_indices": [2],
        },
    ]


# ---------------------------------------------------------------------------
# key 算法
# ---------------------------------------------------------------------------


class TestComputeKey:
    def test_key_is_24_hex_chars(self) -> None:
        key = _compute_kg_cache_key(
            chunks=_chunks(["abc"]),
            system_prompt="sys",
            model="m",
        )
        assert len(key) == 24
        int(key, 16)  # 不抛异常即为合法 hex

    def test_same_inputs_same_key(self) -> None:
        a = _compute_kg_cache_key(
            chunks=_chunks(["a", "b"]),
            system_prompt="sys",
            model="m",
        )
        b = _compute_kg_cache_key(
            chunks=_chunks(["a", "b"]),
            system_prompt="sys",
            model="m",
        )
        assert a == b

    def test_chunk_text_changes_key(self) -> None:
        a = _compute_kg_cache_key(
            chunks=_chunks(["a"]),
            system_prompt="sys",
            model="m",
        )
        b = _compute_kg_cache_key(
            chunks=_chunks(["A"]),
            system_prompt="sys",
            model="m",
        )
        assert a != b

    def test_chunk_order_changes_key(self) -> None:
        a = _compute_kg_cache_key(
            chunks=_chunks(["a", "b"]),
            system_prompt="sys",
            model="m",
        )
        b = _compute_kg_cache_key(
            chunks=_chunks(["b", "a"]),
            system_prompt="sys",
            model="m",
        )
        assert a != b

    def test_chunk_index_changes_key(self) -> None:
        a = _compute_kg_cache_key(
            chunks=_chunks(["a"], start_index=0),
            system_prompt="sys",
            model="m",
        )
        b = _compute_kg_cache_key(
            chunks=_chunks(["a"], start_index=5),
            system_prompt="sys",
            model="m",
        )
        assert a != b

    def test_system_prompt_changes_key(self) -> None:
        a = _compute_kg_cache_key(
            chunks=_chunks(["a"]),
            system_prompt="sys1",
            model="m",
        )
        b = _compute_kg_cache_key(
            chunks=_chunks(["a"]),
            system_prompt="sys2",
            model="m",
        )
        assert a != b

    def test_model_changes_key(self) -> None:
        a = _compute_kg_cache_key(
            chunks=_chunks(["a"]),
            system_prompt="sys",
            model="deepseek-chat",
        )
        b = _compute_kg_cache_key(
            chunks=_chunks(["a"]),
            system_prompt="sys",
            model="claude-haiku",
        )
        assert a != b


# ---------------------------------------------------------------------------
# 序列化 / 反序列化
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_roundtrip(self) -> None:
        entries = _entries()
        blob = _serialize_entries(entries)
        assert isinstance(blob, bytes)
        back = _deserialize_entries(blob)
        assert back == entries

    def test_deserialize_non_list_raises(self) -> None:
        blob = json.dumps({"not": "a list"}).encode("utf-8")
        with pytest.raises(ValueError):
            _deserialize_entries(blob)


# ---------------------------------------------------------------------------
# extract_batch_cached 行为
# ---------------------------------------------------------------------------


class TestExtractBatchCached:
    def test_first_call_misses_writes_cache(self) -> None:
        call_count = {"n": 0}

        def fn() -> list[dict[str, Any]]:
            call_count["n"] += 1
            return _entries()

        chunks = _chunks(["第一段。"])
        out = extract_batch_cached(
            chunks=chunks,
            system_prompt="sys",
            model="m",
            extract_func=fn,
        )
        assert out == _entries()
        assert call_count["n"] == 1
        stats = get_kg_cache_stats()
        assert stats["size"] == 1

    def test_second_same_call_hits(self) -> None:
        call_count = {"n": 0}

        def fn() -> list[dict[str, Any]]:
            call_count["n"] += 1
            return _entries()

        chunks = _chunks(["第一段。"])
        kw = {
            "chunks": chunks,
            "system_prompt": "sys",
            "model": "m",
            "extract_func": fn,
        }
        first = extract_batch_cached(**kw)
        second = extract_batch_cached(**kw)
        assert first == second
        assert call_count["n"] == 1  # 二次跳了 LLM

    def test_different_chunks_misses(self) -> None:
        call_count = {"n": 0}

        def fn() -> list[dict[str, Any]]:
            call_count["n"] += 1
            return _entries()

        extract_batch_cached(
            chunks=_chunks(["A"]),
            system_prompt="sys",
            model="m",
            extract_func=fn,
        )
        extract_batch_cached(
            chunks=_chunks(["B"]),
            system_prompt="sys",
            model="m",
            extract_func=fn,
        )
        assert call_count["n"] == 2

    def test_different_system_prompt_misses(self) -> None:
        call_count = {"n": 0}

        def fn() -> list[dict[str, Any]]:
            call_count["n"] += 1
            return _entries()

        chunks = _chunks(["A"])
        extract_batch_cached(
            chunks=chunks,
            system_prompt="sys1",
            model="m",
            extract_func=fn,
        )
        extract_batch_cached(
            chunks=chunks,
            system_prompt="sys2",
            model="m",
            extract_func=fn,
        )
        assert call_count["n"] == 2

    def test_different_model_misses(self) -> None:
        call_count = {"n": 0}

        def fn() -> list[dict[str, Any]]:
            call_count["n"] += 1
            return _entries()

        chunks = _chunks(["A"])
        extract_batch_cached(
            chunks=chunks,
            system_prompt="sys",
            model="m1",
            extract_func=fn,
        )
        extract_batch_cached(
            chunks=chunks,
            system_prompt="sys",
            model="m2",
            extract_func=fn,
        )
        assert call_count["n"] == 2

    def test_env_disabled_bypasses_cache(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BOOKSCOPE_KG_CACHE_DISABLED", "1")
        call_count = {"n": 0}

        def fn() -> list[dict[str, Any]]:
            call_count["n"] += 1
            return _entries()

        kw = {
            "chunks": _chunks(["A"]),
            "system_prompt": "sys",
            "model": "m",
            "extract_func": fn,
        }
        extract_batch_cached(**kw)
        extract_batch_cached(**kw)
        # env 关掉了缓存：两次都真调 fn
        assert call_count["n"] == 2

    def test_clear_kg_cache(self) -> None:
        def fn() -> list[dict[str, Any]]:
            return _entries()

        kw = {
            "chunks": _chunks(["A"]),
            "system_prompt": "sys",
            "model": "m",
            "extract_func": fn,
        }
        extract_batch_cached(**kw)
        assert get_kg_cache_stats()["size"] == 1
        clear_kg_cache()
        assert get_kg_cache_stats()["size"] == 0


# ---------------------------------------------------------------------------
# schema_version 失效
# ---------------------------------------------------------------------------


class TestSchemaVersionInvalidate:
    def test_invalidate_by_schema_version_removes_old_rows(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """旧 schema_version 升级后 invalidate 应清掉旧 row。"""
        monkeypatch.setenv(
            "BOOKSCOPE_KG_CACHE_DB_PATH", str(tmp_path / "kg2.db")
        )
        reset_kg_cache_singleton_for_test()

        def fn() -> list[dict[str, Any]]:
            return _entries()

        # 先用当前 v1 写一条
        extract_batch_cached(
            chunks=_chunks(["A"]),
            system_prompt="sys",
            model="m",
            extract_func=fn,
        )
        assert get_kg_cache_stats()["size"] == 1

        # 调 invalidate_by_schema_version("v1") —— 当前 schema 就是 v1
        removed = invalidate_by_schema_version(
            kg_cache_mod.KG_CACHE_SCHEMA_VERSION
        )
        assert removed == 1
        assert get_kg_cache_stats()["size"] == 0

    def test_invalidate_unknown_version_no_op(self) -> None:
        def fn() -> list[dict[str, Any]]:
            return _entries()

        extract_batch_cached(
            chunks=_chunks(["A"]),
            system_prompt="sys",
            model="m",
            extract_func=fn,
        )
        assert get_kg_cache_stats()["size"] == 1
        removed = invalidate_by_schema_version("v_does_not_exist")
        assert removed == 0
        assert get_kg_cache_stats()["size"] == 1


# ---------------------------------------------------------------------------
# 与 MinimalKGExtractor 集成
# ---------------------------------------------------------------------------


class _FakeClient:
    """最简 fake：按预置 response 序列吐回。"""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._queue = list(responses)
        self.call_count = 0

    def messages_create(self, **kwargs: Any) -> dict[str, Any]:
        self.call_count += 1
        if not self._queue:
            raise AssertionError("fake client out of responses")
        return self._queue.pop(0)

    def extract_final_text(self, response: Any) -> str:
        return response["content"][0]["text"]

    def extract_usage_tokens(self, response: Any) -> tuple[int, int]:
        return 0, 0


def _response_with_json(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "stop_reason": "end_turn",
        "content": [
            {"type": "text", "text": json.dumps(payload, ensure_ascii=False)}
        ],
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }


class TestExtractorIntegration:
    def test_second_extract_hits_cache_skips_llm(self) -> None:
        """同 book + 同 chunks + 同 model 的二次 extract 应跳 LLM。"""
        payload = {
            "characters": [
                {
                    "name": "朱元璋",
                    "canonical_name": "朱元璋",
                    "key_chapter_indices": [1, 2],
                }
            ]
        }
        # 只准备一条 response —— 二次必须命中缓存，不会再问 client
        client = _FakeClient([_response_with_json(payload)])
        extractor = MinimalKGExtractor(client=client, model="deepseek-chat")
        chunks = [
            ChunkResult(index=0, text="朱元璋出生在濠州。"),
        ]

        kg1 = extractor.extract(chunks=chunks, book_title="测试")
        kg2 = extractor.extract(chunks=chunks, book_title="测试")

        assert client.call_count == 1
        assert [c.name for c in kg1.characters] == ["朱元璋"]
        assert [c.name for c in kg2.characters] == ["朱元璋"]

    def test_different_chunks_re_invokes_llm(self) -> None:
        payload1 = {
            "characters": [
                {
                    "name": "朱元璋",
                    "canonical_name": "朱元璋",
                    "key_chapter_indices": [1],
                }
            ]
        }
        payload2 = {
            "characters": [
                {
                    "name": "刘伯温",
                    "canonical_name": "刘基",
                    "key_chapter_indices": [2],
                }
            ]
        }
        client = _FakeClient(
            [_response_with_json(payload1), _response_with_json(payload2)]
        )
        extractor = MinimalKGExtractor(client=client, model="deepseek-chat")
        kg1 = extractor.extract(
            chunks=[ChunkResult(index=0, text="第一段。")],
            book_title="测试",
        )
        kg2 = extractor.extract(
            chunks=[ChunkResult(index=0, text="第二段。")],
            book_title="测试",
        )
        assert client.call_count == 2
        assert [c.name for c in kg1.characters] == ["朱元璋"]
        assert [c.name for c in kg2.characters] == ["刘伯温"]


# ---------------------------------------------------------------------------
# 增量 ingest 场景（Sprint 6 第三步 · 章节追加自动命中）
# ---------------------------------------------------------------------------
#
# Audit 结论（见 `docs/internal/STATE.md` 第 35 轮 BE 报告）：
#
# - `book_chunker.chunk_book` 是纯函数（regex 章切 + 段落合并 + 字符计数），
#   同输入产同输出 —— **chunker 决定性成立**。
# - `MinimalKGExtractor._split_into_batches` 按固定 60 切片
#   （`chunks[start : start + 60]`），与 chunks 内容无关 —— **batch 划分稳
#   定**。
# - KG cache key 算法（`_compute_kg_cache_key`）按
#   `{"index", "text"}` 序列入 hash —— 同样 chunks 内容产同 key。
#
# 三者叠加 →"用户给同本书追加几章后旧章节 batch 自动命中缓存"是 cache key
# 算法的天然推论，**不需要任何增量代码改动**。下面两条用例把这条推论钉成
# 回归门：未来若有人改 `_split_into_batches`（如换成按字符总长动态切）或
# `_compute_kg_cache_key`（如把 cache key 加上 book_title），下面会立刻
# 失败提示。


def _make_book_text(chapters: list[tuple[str, str]]) -> BookText:
    """从 (chapter_title, body) 序列拼一本测试用 BookText。"""
    parts: list[str] = []
    for title, body in chapters:
        parts.append(f"{title}\n{body}")
    return BookText(
        title="增量测试书",
        raw_text="\n\n".join(parts),
        language="zh",
    )


class TestIncrementalIngest:
    """章节追加场景：旧章节产生的 batch 在追加后必须直接命中缓存。

    这层测试不直 mock `_extract_from_batch`，而是真跑 `book_chunker.chunk_book`
    + `MinimalKGExtractor.extract`，用 `_FakeClient` 当 LLM 桩——LLM 被调
    几次是判别命中率的硬数据。
    """

    def test_chunker_is_deterministic_same_input_same_chunks(self) -> None:
        """chunker 决定性 —— 同输入两次 chunk_book 产完全相同的 chunks。

        增量缓存命中的前提就是这个性质；前置 assert 一道避免未来 chunker
        引入随机/并发后默默把缓存命中率拉到 0。
        """
        from bookscope.ingest.book_chunker import chunk_book

        # 用够长的段落让 chunker 走完三层逻辑（章切 / 段落合并 / 头注前置）
        long_body = "正文段落。" * 80  # ~400 char，超过 CHUNK_CHAR_MIN
        book = _make_book_text(
            [
                ("第一章 开端", long_body),
                ("第二章 发展", long_body),
                ("第三章 高潮", long_body),
            ]
        )
        first = chunk_book(book)
        second = chunk_book(book)

        assert len(first) == len(second)
        assert [(c.index, c.text, c.chapter) for c in first] == [
            (c.index, c.text, c.chapter) for c in second
        ]

    def test_batch_split_is_content_independent(self) -> None:
        """batch 划分稳定 —— 前 K 个 chunks 不变 → 前若干个 batch 一致。

        覆盖`_split_into_batches`改动的回归。当前实现是固定 60 切片：前 K
        个 chunks 决定前 K // 60 + 1 个 batch 的边界。
        """
        from bookscope.agent.backends.minimal_kg_extractor import (
            MinimalKGExtractor,
        )

        # 任意一个不会真被调的 fake client —— 我们只用 _split_into_batches。
        extractor = MinimalKGExtractor(
            client=_FakeClient([]),
            max_chunks_per_batch=3,  # 小一点便于断言
        )

        old_chunks = _chunks([f"段{i}。" for i in range(7)])
        # 增量场景：在末尾追加 3 个 chunk，前 7 个完全不变
        new_chunks = _chunks([f"段{i}。" for i in range(10)])

        old_batches = extractor._split_into_batches(old_chunks)
        new_batches = extractor._split_into_batches(new_chunks)

        # 前两个满 batch（各 3 chunk）应完全一致
        assert len(old_batches[0]) == 3
        assert len(old_batches[1]) == 3
        assert [
            (c.index, c.text) for c in old_batches[0]
        ] == [(c.index, c.text) for c in new_batches[0]]
        assert [
            (c.index, c.text) for c in old_batches[1]
        ] == [(c.index, c.text) for c in new_batches[1]]
        # 第三个 batch 在旧版是 [6]，新版变成 [6,7,8]——边界不再一致
        # （这部分被预期 cache miss，是增量算法的剩余少量重抽成本）
        assert [c.index for c in old_batches[2]] == [6]
        assert [c.index for c in new_batches[2]] == [6, 7, 8]

    def test_appended_chapter_reuses_old_batch_caches(self) -> None:
        """端到端：先 ingest 3 章 → 追加第 4 章再 ingest → 旧 batch 全命中。

        - max_chunks_per_batch 设小（=1）让每个 chunk 自成一 batch，
          边界清晰便于断言。
        - LLM 被调几次 = client.call_count；增量后第二次 extract 只能为
          "新章节产生的新 chunks 数" 量级，绝不应再调旧 batch 的 LLM。
        """
        from bookscope.agent.backends.minimal_kg_extractor import (
            MinimalKGExtractor,
        )
        from bookscope.ingest.book_chunker import chunk_book

        body = "段落正文。" * 80  # 单章 ~400 char，触发 chunk_book 切分

        # 第一次 ingest：3 章
        book_v1 = _make_book_text(
            [
                ("第一章 开端", body),
                ("第二章 发展", body),
                ("第三章 高潮", body),
            ]
        )
        chunks_v1 = chunk_book(book_v1)
        n1 = len(chunks_v1)

        # 第二次 ingest：同前 3 章 + 追加第 4 章
        book_v2 = _make_book_text(
            [
                ("第一章 开端", body),
                ("第二章 发展", body),
                ("第三章 高潮", body),
                ("第四章 结局", body),
            ]
        )
        chunks_v2 = chunk_book(book_v2)
        n2 = len(chunks_v2)

        # 前 n1 个 chunks 必须跟 v1 完全一致（增量命中前提）
        assert n2 > n1
        for i in range(n1):
            assert chunks_v1[i].index == chunks_v2[i].index
            assert chunks_v1[i].text == chunks_v2[i].text

        # 每个 chunk 一个 batch；预备充足的 fake response
        payload = {
            "characters": [
                {
                    "name": "测试角色",
                    "canonical_name": "测试角色",
                    "key_chapter_indices": [1],
                }
            ]
        }
        responses = [_response_with_json(payload) for _ in range(n2 + 10)]
        client = _FakeClient(responses)
        extractor = MinimalKGExtractor(
            client=client,
            model="deepseek-chat",
            max_chunks_per_batch=1,
            max_workers=1,  # 串行让 call_count 不受线程调度影响
        )

        # v1 ingest：LLM 被调 n1 次（每个 chunk 一次）
        extractor.extract(chunks=chunks_v1, book_title="增量测试书")
        assert client.call_count == n1

        # v2 ingest：前 n1 个 chunks 应全部命中缓存，只对新增 n2 - n1 个调 LLM
        extractor.extract(chunks=chunks_v2, book_title="增量测试书")
        new_calls = client.call_count - n1
        assert new_calls == n2 - n1, (
            f"expected {n2 - n1} new LLM calls for {n2 - n1} appended chunks, "
            f"got {new_calls} — 旧 batch 缓存命中失败"
        )
