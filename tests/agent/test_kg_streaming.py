"""MinimalKGExtractor streaming callback hook 单元测试（Sprint 6 第六步）。

验证 ``on_ingest_event`` callback 在各路径下的 emit 行为：

- happy path 多 batch：emit 顺序 ingest_started → kg_batch_started/completed × N
  → ingest_done
- 空 chunks：ingest_started(total=0) → ingest_done（无 batch event）
- LLMFormatError：emit ingest_error 后异常透传
- callback 抛异常：被包死不破坏抽取主链路（KG 仍正确返出）
- book-level cache 命中：emit ingest_started → kg_cache_hit(batch_index=None) →
  ingest_done（重复 ``extract`` 同 chunks 自动命中）
- batch-level cache 命中：emit kg_cache_hit(batch_index=N) 在 kg_batch_completed
  之前（同一 batch 第二次跑命中 SQLite）

跟 ``tests/agent/test_minimal_kg_extractor.py`` 同 fake client 模式——本文件
只测 streaming hook 行为，KG 解析正确性留给原测试覆盖。
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from bookscope.agent.backends.minimal_kg_extractor import (
    MinimalKGExtractor,
    _extract_text_from_response,
)
from bookscope.agent.errors import ProviderUnavailable
from bookscope.agent.events import IngestEvent
from bookscope.models.schemas import ChunkResult


class _FakeClient:
    """跟 test_minimal_kg_extractor.py 同形——按 responses 顺序返。"""

    def __init__(
        self,
        responses: list[dict[str, Any]] | None = None,
        *,
        raise_exc: Exception | None = None,
    ) -> None:
        self._responses = list(responses or [])
        self._raise_exc = raise_exc
        self.call_count = 0

    def messages_create(self, **_kw: Any) -> dict[str, Any]:
        self.call_count += 1
        if self._raise_exc is not None:
            raise self._raise_exc
        if not self._responses:
            raise AssertionError("FakeClient exhausted")
        return self._responses.pop(0)

    def extract_final_text(self, response: Any) -> str:
        return _extract_text_from_response(response)

    def extract_usage_tokens(self, response: Any) -> tuple[int, int]:
        return 0, 0


def _response(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "stop_reason": "end_turn",
        "content": [
            {"type": "text", "text": json.dumps(payload, ensure_ascii=False)}
        ],
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


def _chars_payload(name: str) -> dict[str, Any]:
    return {
        "characters": [
            {
                "name": name,
                "canonical_name": name,
                "key_chapter_indices": [1],
            }
        ]
    }


def _chunks(n: int) -> list[ChunkResult]:
    return [ChunkResult(index=i, text=f"第{i}段文字。" * 5) for i in range(n)]


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_callback_emits_full_sequence_for_multi_batch() -> None:
    """3 chunks / max_chunks_per_batch=1 → 3 batches，验证完整事件序列。"""
    client = _FakeClient(
        [
            _response(_chars_payload("A")),
            _response(_chars_payload("B")),
            _response(_chars_payload("C")),
        ]
    )
    events: list[IngestEvent] = []
    extractor = MinimalKGExtractor(
        client=client,
        max_chunks_per_batch=1,
        max_workers=1,  # 串行，emit 顺序可断言
        on_ingest_event=events.append,
        book_session_id="sess-001",
    )
    extractor.extract(chunks=_chunks(3), book_title="X")

    types = [e.event_type for e in events]
    # 第一帧 ingest_started + total_batches=3
    assert types[0] == "ingest_started"
    assert events[0].total_batches == 3
    assert events[0].book_session_id == "sess-001"
    # 末帧 ingest_done
    assert types[-1] == "ingest_done"
    # 每个 batch 一对 started + completed
    assert types.count("kg_batch_started") == 3
    assert types.count("kg_batch_completed") == 3
    # 没有 cache_hit / ingest_error
    assert "kg_cache_hit" not in types
    assert "ingest_error" not in types


def test_callback_emits_batch_index_in_order() -> None:
    """串行 max_workers=1 时 batch_index 升序出现。"""
    client = _FakeClient(
        [_response(_chars_payload(c)) for c in ("A", "B", "C")]
    )
    events: list[IngestEvent] = []
    extractor = MinimalKGExtractor(
        client=client,
        max_chunks_per_batch=1,
        max_workers=1,
        on_ingest_event=events.append,
    )
    extractor.extract(chunks=_chunks(3), book_title="X")
    started_indices = [
        e.batch_index for e in events if e.event_type == "kg_batch_started"
    ]
    assert started_indices == [0, 1, 2]


def test_callback_empty_chunks_emits_minimal_sequence() -> None:
    """空 chunks 仅 emit ingest_started(total=0) + ingest_done。"""
    client = _FakeClient([])
    events: list[IngestEvent] = []
    extractor = MinimalKGExtractor(
        client=client,
        on_ingest_event=events.append,
    )
    extractor.extract(chunks=[], book_title="X")
    types = [e.event_type for e in events]
    assert types == ["ingest_started", "ingest_done"]
    assert events[0].total_batches == 0


# ---------------------------------------------------------------------------
# 错误路径
# ---------------------------------------------------------------------------


def test_callback_emits_ingest_error_on_provider_unavailable() -> None:
    """ProviderUnavailable (auth / 网络挂) → 透传 + emit ingest_error。

    第十六波改——LLMFormatError 不再透传（走 jieba 兜底 / 见
    `test_callback_emits_ingest_done_on_llm_format_with_jieba_fallback`）。
    ProviderUnavailable 仍透传——auth / 网络是用户能修的配置错，
    要冒给 API 层翻成 HTTP 错让用户看见。
    """
    client = _FakeClient(raise_exc=ProviderUnavailable("auth failed"))
    events: list[IngestEvent] = []
    extractor = MinimalKGExtractor(
        client=client,
        on_ingest_event=events.append,
    )
    with pytest.raises(ProviderUnavailable):
        extractor.extract(chunks=_chunks(1), book_title="X")
    types = [e.event_type for e in events]
    assert "ingest_started" in types
    assert types[-1] == "ingest_error"
    err = events[-1]
    assert err.error_message is not None
    assert "ProviderUnavailable" in err.error_message


def test_callback_emits_ingest_done_on_llm_format_with_jieba_fallback() -> None:
    """LLM 返非 JSON → jieba 兜底救回 / 链路成功 emit ingest_done（不 ingest_error）。

    第十六波加——LLMFormatError 走 jieba 兜底而非异常透传，整条 ingest
    链路对消费方是成功的（user 上传书不会因为 LLM 形态错而失败）。
    """
    client = _FakeClient([_response({"foo": "bar"})])  # 缺 characters → format error
    events: list[IngestEvent] = []
    extractor = MinimalKGExtractor(
        client=client,
        on_ingest_event=events.append,
    )
    # 喂含中文人名的 chunk 让 jieba 救回
    chunks = [ChunkResult(index=0, text="毛泽东与邓小平是新中国领导人。")]
    kg = extractor.extract(chunks=chunks, book_title="X")
    types = [e.event_type for e in events]
    assert types[-1] == "ingest_done"  # 不是 ingest_error
    # jieba 救回真人名
    names = {c.name for c in kg.characters}
    assert {"毛泽东", "邓小平"}.intersection(names)


def test_callback_failures_do_not_break_extraction() -> None:
    """callback 自己抛异常 → 被包死，KG 仍正确返出。"""
    client = _FakeClient([_response(_chars_payload("A"))])

    def bad_callback(_event: IngestEvent) -> None:
        raise RuntimeError("callback boom")

    extractor = MinimalKGExtractor(
        client=client,
        on_ingest_event=bad_callback,
    )
    kg = extractor.extract(chunks=_chunks(1), book_title="X")
    assert len(kg.characters) == 1
    assert kg.characters[0].name == "A"


# ---------------------------------------------------------------------------
# Cache 命中
# ---------------------------------------------------------------------------


def test_callback_emits_batch_cache_hit_on_second_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同 chunks + system_prompt + model 第二次跑 → batch 级缓存命中。

    第二次 ``extract`` 期间应 emit ``kg_cache_hit(batch_index=0, cached=True)``
    且 client.call_count 不增长（LLM 没被调）。
    """
    # 关 book-level cache 让我们只看 batch 级路径——不然第二次直接整本命中，
    # 看不到 batch 级的 kg_cache_hit emit。
    monkeypatch.setenv("BOOKSCOPE_KG_BOOK_CACHE_DISABLED", "1")
    # 重建 book cache singleton 让 env 生效
    from bookscope.agent._internal.kg_book_cache import (
        reset_book_kg_cache_singleton_for_test,
    )

    reset_book_kg_cache_singleton_for_test()

    chunks = _chunks(1)
    client1 = _FakeClient([_response(_chars_payload("A"))])
    extractor1 = MinimalKGExtractor(client=client1)
    extractor1.extract(chunks=chunks, book_title="X")
    assert client1.call_count == 1

    # 第二次跑，使用同 chunks
    client2 = _FakeClient([])  # 不该被调
    events: list[IngestEvent] = []
    extractor2 = MinimalKGExtractor(
        client=client2,
        on_ingest_event=events.append,
    )
    extractor2.extract(chunks=chunks, book_title="X")
    assert client2.call_count == 0  # LLM 没被调，确认命中
    types = [e.event_type for e in events]
    assert "kg_cache_hit" in types
    cache_event = next(e for e in events if e.event_type == "kg_cache_hit")
    assert cache_event.cached is True
    assert cache_event.batch_index == 0  # batch 级命中带 batch_index


def test_callback_emits_book_level_cache_hit_on_second_run() -> None:
    """book-level cache 命中。

    事件序列压缩成 ingest_started → kg_cache_hit(batch_index=None) →
    ingest_done。
    """
    chunks = _chunks(1)
    # 第一次跑装满 cache
    client1 = _FakeClient([_response(_chars_payload("A"))])
    MinimalKGExtractor(client=client1).extract(chunks=chunks, book_title="X")

    # 第二次跑应整本命中
    client2 = _FakeClient([])
    events: list[IngestEvent] = []
    extractor2 = MinimalKGExtractor(
        client=client2,
        on_ingest_event=events.append,
    )
    extractor2.extract(chunks=chunks, book_title="X")
    types = [e.event_type for e in events]
    # 整本命中：起 → kg_cache_hit(batch_index=None) → 完
    assert types == ["ingest_started", "kg_cache_hit", "ingest_done"]
    cache_event = events[1]
    assert cache_event.batch_index is None
    assert cache_event.cached is True


# ---------------------------------------------------------------------------
# 默认 None callback —— 不应抛
# ---------------------------------------------------------------------------


def test_extractor_works_without_callback() -> None:
    """on_ingest_event=None 时 emit 全部 no-op；KG 正常返出。"""
    client = _FakeClient([_response(_chars_payload("A"))])
    extractor = MinimalKGExtractor(client=client)  # 无 on_ingest_event
    kg = extractor.extract(chunks=_chunks(1), book_title="X")
    assert len(kg.characters) == 1
