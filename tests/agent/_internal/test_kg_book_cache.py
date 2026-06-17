"""``bookscope.agent._internal.kg_book_cache`` 单测 —— Sprint 6 第四步。

覆盖：

- 首次抽取 cache miss + 写入；二次同 ``(all_chunks, system_prompt, model)`` 命中
- chunks 顺序变化不命中（顺序敏感）
- 单个 chunk 内容变化不命中
- system_prompt / model 变化不命中
- env ``BOOKSCOPE_KG_BOOK_CACHE_DISABLED=1`` 关 book-level 但 batch 级仍工作
- book-level cache hit 时**完全跳过** batch 级抽取（验证不重复算）
- schema_version 升级 invalidate
- BookKnowledgeGraph 字段 round-trip 完整（嵌套 CharacterProfile 等）
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from bookscope.agent._internal import kg_book_cache as kg_book_cache_mod
from bookscope.agent._internal.kg_book_cache import (
    _compute_kg_book_cache_key,
    _deserialize_book_kg,
    _serialize_book_kg,
    clear_book_kg_cache,
    extract_book_kg_cached,
    get_book_kg_cache_stats,
    invalidate_by_schema_version,
    reset_book_kg_cache_singleton_for_test,
)
from bookscope.agent._internal.kg_cache import (
    get_kg_cache_stats,
    reset_kg_cache_singleton_for_test,
)
from bookscope.agent.backends.minimal_kg_extractor import MinimalKGExtractor
from bookscope.models.schemas import (
    BookKnowledgeGraph,
    CharacterProfile,
    ChunkResult,
)


@pytest.fixture(autouse=True)
def isolated_book_cache_db(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """本模块测试用独立 DB 文件 + 强制重建 singleton。

    全局 conftest 已 autouse 同款，本 fixture 显式再设一遍是为了让显式
    重建 singleton 的用例语义清晰。
    """
    monkeypatch.setenv(
        "BOOKSCOPE_KG_BOOK_CACHE_DB_PATH", str(tmp_path / "kg_book.db")
    )
    monkeypatch.setenv(
        "BOOKSCOPE_KG_CACHE_DB_PATH", str(tmp_path / "kg.db")
    )
    reset_book_kg_cache_singleton_for_test()
    reset_kg_cache_singleton_for_test()
    yield
    reset_book_kg_cache_singleton_for_test()
    reset_kg_cache_singleton_for_test()


def _chunks(texts: list[str], start_index: int = 0) -> list[ChunkResult]:
    return [
        ChunkResult(index=start_index + i, text=t) for i, t in enumerate(texts)
    ]


def _sample_kg() -> BookKnowledgeGraph:
    return BookKnowledgeGraph(
        book_title="测试书",
        language="zh",
        characters=[
            CharacterProfile(
                name="朱元璋",
                key_chapter_indices=[1, 2, 3],
                description="canonical: 朱元璋",
            ),
            CharacterProfile(
                name="刘伯温",
                aliases=["刘基"],
                key_chapter_indices=[2],
            ),
        ],
    )


# ---------------------------------------------------------------------------
# key 算法
# ---------------------------------------------------------------------------


class TestComputeKey:
    def test_key_is_24_hex_chars(self) -> None:
        key = _compute_kg_book_cache_key(
            all_chunks=_chunks(["abc"]),
            system_prompt="sys",
            model="m",
        )
        assert len(key) == 24
        int(key, 16)  # 合法 hex

    def test_same_inputs_same_key(self) -> None:
        a = _compute_kg_book_cache_key(
            all_chunks=_chunks(["a", "b"]),
            system_prompt="sys",
            model="m",
        )
        b = _compute_kg_book_cache_key(
            all_chunks=_chunks(["a", "b"]),
            system_prompt="sys",
            model="m",
        )
        assert a == b

    def test_chunk_text_changes_key(self) -> None:
        a = _compute_kg_book_cache_key(
            all_chunks=_chunks(["a", "b"]),
            system_prompt="sys",
            model="m",
        )
        b = _compute_kg_book_cache_key(
            all_chunks=_chunks(["a", "B"]),
            system_prompt="sys",
            model="m",
        )
        assert a != b

    def test_chunk_order_changes_key(self) -> None:
        a = _compute_kg_book_cache_key(
            all_chunks=_chunks(["a", "b"]),
            system_prompt="sys",
            model="m",
        )
        b = _compute_kg_book_cache_key(
            all_chunks=_chunks(["b", "a"]),
            system_prompt="sys",
            model="m",
        )
        assert a != b

    def test_system_prompt_changes_key(self) -> None:
        a = _compute_kg_book_cache_key(
            all_chunks=_chunks(["a"]),
            system_prompt="sys1",
            model="m",
        )
        b = _compute_kg_book_cache_key(
            all_chunks=_chunks(["a"]),
            system_prompt="sys2",
            model="m",
        )
        assert a != b

    def test_model_changes_key(self) -> None:
        a = _compute_kg_book_cache_key(
            all_chunks=_chunks(["a"]),
            system_prompt="sys",
            model="m1",
        )
        b = _compute_kg_book_cache_key(
            all_chunks=_chunks(["a"]),
            system_prompt="sys",
            model="m2",
        )
        assert a != b

    def test_chunk_index_does_not_change_key(self) -> None:
        """本层 key 不绑 chunk.index —— 整书重 ingest 时 index 由 text 顺序决定，
        text 一致就该命中。与 batch 级 key 算法不同。"""
        a = _compute_kg_book_cache_key(
            all_chunks=_chunks(["a", "b"], start_index=0),
            system_prompt="sys",
            model="m",
        )
        b = _compute_kg_book_cache_key(
            all_chunks=_chunks(["a", "b"], start_index=100),
            system_prompt="sys",
            model="m",
        )
        assert a == b


# ---------------------------------------------------------------------------
# 序列化 / 反序列化
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_roundtrip(self) -> None:
        kg = _sample_kg()
        blob = _serialize_book_kg(kg)
        assert isinstance(blob, bytes)
        back = _deserialize_book_kg(blob)
        assert back == kg

    def test_roundtrip_preserves_nested_character_fields(self) -> None:
        """嵌套 CharacterProfile 的所有字段都要原样回来。"""
        kg = _sample_kg()
        back = _deserialize_book_kg(_serialize_book_kg(kg))
        assert [c.name for c in back.characters] == ["朱元璋", "刘伯温"]
        assert back.characters[0].key_chapter_indices == [1, 2, 3]
        assert back.characters[0].description == "canonical: 朱元璋"
        assert back.characters[1].aliases == ["刘基"]

    def test_deserialize_invalid_blob_raises(self) -> None:
        blob = b"not json at all"
        with pytest.raises(ValueError):
            _deserialize_book_kg(blob)

    def test_deserialize_wrong_schema_raises(self) -> None:
        blob = json.dumps({"unrelated": "shape"}).encode("utf-8")
        with pytest.raises(ValueError):
            _deserialize_book_kg(blob)


# ---------------------------------------------------------------------------
# extract_book_kg_cached 行为
# ---------------------------------------------------------------------------


class TestExtractBookCached:
    def test_first_call_misses_writes_cache(self) -> None:
        call_count = {"n": 0}

        def fn() -> BookKnowledgeGraph:
            call_count["n"] += 1
            return _sample_kg()

        out = extract_book_kg_cached(
            all_chunks=_chunks(["第一段。"]),
            system_prompt="sys",
            model="m",
            extract_func=fn,
        )
        assert out == _sample_kg()
        assert call_count["n"] == 1
        assert get_book_kg_cache_stats()["size"] == 1

    def test_second_same_call_hits(self) -> None:
        call_count = {"n": 0}

        def fn() -> BookKnowledgeGraph:
            call_count["n"] += 1
            return _sample_kg()

        kw = {
            "all_chunks": _chunks(["第一段。"]),
            "system_prompt": "sys",
            "model": "m",
            "extract_func": fn,
        }
        first = extract_book_kg_cached(**kw)
        second = extract_book_kg_cached(**kw)
        assert first == second
        assert call_count["n"] == 1

    def test_different_chunks_misses(self) -> None:
        call_count = {"n": 0}

        def fn() -> BookKnowledgeGraph:
            call_count["n"] += 1
            return _sample_kg()

        extract_book_kg_cached(
            all_chunks=_chunks(["A"]),
            system_prompt="sys",
            model="m",
            extract_func=fn,
        )
        extract_book_kg_cached(
            all_chunks=_chunks(["B"]),
            system_prompt="sys",
            model="m",
            extract_func=fn,
        )
        assert call_count["n"] == 2

    def test_chunk_order_changes_misses(self) -> None:
        call_count = {"n": 0}

        def fn() -> BookKnowledgeGraph:
            call_count["n"] += 1
            return _sample_kg()

        extract_book_kg_cached(
            all_chunks=_chunks(["a", "b"]),
            system_prompt="sys",
            model="m",
            extract_func=fn,
        )
        extract_book_kg_cached(
            all_chunks=_chunks(["b", "a"]),
            system_prompt="sys",
            model="m",
            extract_func=fn,
        )
        assert call_count["n"] == 2

    def test_different_system_prompt_misses(self) -> None:
        call_count = {"n": 0}

        def fn() -> BookKnowledgeGraph:
            call_count["n"] += 1
            return _sample_kg()

        chunks = _chunks(["A"])
        extract_book_kg_cached(
            all_chunks=chunks,
            system_prompt="sys1",
            model="m",
            extract_func=fn,
        )
        extract_book_kg_cached(
            all_chunks=chunks,
            system_prompt="sys2",
            model="m",
            extract_func=fn,
        )
        assert call_count["n"] == 2

    def test_different_model_misses(self) -> None:
        call_count = {"n": 0}

        def fn() -> BookKnowledgeGraph:
            call_count["n"] += 1
            return _sample_kg()

        chunks = _chunks(["A"])
        extract_book_kg_cached(
            all_chunks=chunks,
            system_prompt="sys",
            model="m1",
            extract_func=fn,
        )
        extract_book_kg_cached(
            all_chunks=chunks,
            system_prompt="sys",
            model="m2",
            extract_func=fn,
        )
        assert call_count["n"] == 2

    def test_env_disabled_bypasses_book_cache(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BOOKSCOPE_KG_BOOK_CACHE_DISABLED", "1")
        call_count = {"n": 0}

        def fn() -> BookKnowledgeGraph:
            call_count["n"] += 1
            return _sample_kg()

        kw = {
            "all_chunks": _chunks(["A"]),
            "system_prompt": "sys",
            "model": "m",
            "extract_func": fn,
        }
        extract_book_kg_cached(**kw)
        extract_book_kg_cached(**kw)
        # env 关掉本层：两次都真调 fn
        assert call_count["n"] == 2

    def test_clear_book_kg_cache(self) -> None:
        def fn() -> BookKnowledgeGraph:
            return _sample_kg()

        extract_book_kg_cached(
            all_chunks=_chunks(["A"]),
            system_prompt="sys",
            model="m",
            extract_func=fn,
        )
        assert get_book_kg_cache_stats()["size"] == 1
        clear_book_kg_cache()
        assert get_book_kg_cache_stats()["size"] == 0


# ---------------------------------------------------------------------------
# schema_version 失效
# ---------------------------------------------------------------------------


class TestSchemaVersionInvalidate:
    def test_invalidate_by_schema_version_removes_old_rows(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv(
            "BOOKSCOPE_KG_BOOK_CACHE_DB_PATH", str(tmp_path / "kg_book2.db")
        )
        reset_book_kg_cache_singleton_for_test()

        def fn() -> BookKnowledgeGraph:
            return _sample_kg()

        extract_book_kg_cached(
            all_chunks=_chunks(["A"]),
            system_prompt="sys",
            model="m",
            extract_func=fn,
        )
        assert get_book_kg_cache_stats()["size"] == 1

        removed = invalidate_by_schema_version(
            kg_book_cache_mod.KG_BOOK_CACHE_SCHEMA_VERSION
        )
        assert removed == 1
        assert get_book_kg_cache_stats()["size"] == 0


# ---------------------------------------------------------------------------
# 与 MinimalKGExtractor 集成 + 双层叠加
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
    def test_book_level_hit_skips_batch_level_entirely(self) -> None:
        """book-level cache hit 时**完全跳过** batch 级抽取——验证不重复算。

        硬约束：第二次 extract 既不能再调 LLM，也不能再写 batch 级缓存
        （batch 级 size 应保持第一次的状态）。
        """
        payload = {
            "characters": [
                {
                    "name": "朱元璋",
                    "canonical_name": "朱元璋",
                    "key_chapter_indices": [1, 2],
                }
            ]
        }
        # 只准备 1 条 response —— 第二次 extract 必须 book-level 命中，
        # 完全不进 batch 抽取链路，否则 fake client 会因为没 response 抛
        client = _FakeClient([_response_with_json(payload)])
        extractor = MinimalKGExtractor(client=client, model="deepseek-chat")
        chunks = [ChunkResult(index=0, text="朱元璋出生在濠州。")]

        kg1 = extractor.extract(chunks=chunks, book_title="测试")

        batch_size_after_v1 = get_kg_cache_stats()["size"]
        book_size_after_v1 = get_book_kg_cache_stats()["size"]
        assert batch_size_after_v1 == 1  # batch 级写了 1 条
        assert book_size_after_v1 == 1  # book 级写了 1 条

        kg2 = extractor.extract(chunks=chunks, book_title="测试")

        # LLM 只被调 1 次（第一次）
        assert client.call_count == 1
        # batch 级 size 没变——book-level 命中跳过了整条 batch 链路
        assert get_kg_cache_stats()["size"] == batch_size_after_v1
        # KG 内容完全一致
        assert [c.name for c in kg1.characters] == [
            c.name for c in kg2.characters
        ]
        assert [c.key_chapter_indices for c in kg1.characters] == [
            c.key_chapter_indices for c in kg2.characters
        ]

    def test_book_level_disabled_batch_level_still_works(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """env 关 book-level 后，batch 级缓存继续生效——同 chunks 重抽 batch
        命中、跳 LLM 调用，但 book-level 表保持空。"""
        monkeypatch.setenv("BOOKSCOPE_KG_BOOK_CACHE_DISABLED", "1")
        reset_book_kg_cache_singleton_for_test()

        payload = {
            "characters": [
                {
                    "name": "朱元璋",
                    "canonical_name": "朱元璋",
                    "key_chapter_indices": [1],
                }
            ]
        }
        # 只给 1 条 response —— 二次必须靠 batch 级命中跳 LLM
        client = _FakeClient([_response_with_json(payload)])
        extractor = MinimalKGExtractor(client=client, model="deepseek-chat")
        chunks = [ChunkResult(index=0, text="一段。")]

        extractor.extract(chunks=chunks, book_title="测试")
        extractor.extract(chunks=chunks, book_title="测试")

        # LLM 只调 1 次——靠 batch 级缓存
        assert client.call_count == 1
        # book-level 表保持空——被 env disable
        assert get_book_kg_cache_stats()["size"] == 0
        # batch 级有 1 条
        assert get_kg_cache_stats()["size"] == 1

    def test_different_chunks_re_extracts(self) -> None:
        """chunks 不同时 book-level 必须 miss，重走抽取。"""
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
        assert get_book_kg_cache_stats()["size"] == 2

    def test_book_hit_returns_consistent_kg(self) -> None:
        """一致性硬约束：book-level cache hit 时 KG 与 miss 路径产出完全一致。

        撤回条件之一：本测试失败立刻停。
        """
        payload = {
            "characters": [
                {
                    "name": "朱元璋",
                    "canonical_name": "朱元璋",
                    "key_chapter_indices": [1, 5, 7],
                },
                {
                    "name": "刘基",
                    "canonical_name": "刘基",
                    "key_chapter_indices": [2],
                },
            ]
        }
        client = _FakeClient([_response_with_json(payload)])
        extractor = MinimalKGExtractor(client=client, model="deepseek-chat")
        chunks = [ChunkResult(index=0, text="测试文本。")]

        kg_miss = extractor.extract(chunks=chunks, book_title="一致性书")
        kg_hit = extractor.extract(chunks=chunks, book_title="一致性书")

        assert kg_miss == kg_hit
        assert kg_miss.book_title == kg_hit.book_title == "一致性书"
        assert kg_miss.language == kg_hit.language
        assert len(kg_miss.characters) == len(kg_hit.characters) == 2
        for cm, ch in zip(kg_miss.characters, kg_hit.characters, strict=True):
            assert cm.name == ch.name
            assert cm.key_chapter_indices == ch.key_chapter_indices
            assert cm.description == ch.description
