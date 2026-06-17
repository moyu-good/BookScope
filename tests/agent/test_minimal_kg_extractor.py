"""MinimalKGExtractor 单元测试。

所有用例用 fake LLMClient，不调任何真 API。覆盖：

- happy path：单 batch 抽取
- chunks < 阈值：单轮调用
- chunks > 阈值：map-reduce 多轮 + 跨 batch 合并
- LLM 返回非 JSON → LLMFormatError
- LLM JSON 缺 characters / 非对象 → LLMFormatError
- LLM 返回代码围栏 ```json ... ``` 正常剥离
- 跨 batch 重复角色：canonical_name 去重 + chapters 并集
- chunks 为空：直接返回空 KG，不调 LLM
- Provider 错误（ProviderUnavailable）透传
- canonical 与 name 不同：description 记录 canonical 指针
- 构造参数校验：max_chunks_per_batch < 1 → ValueError
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from bookscope.agent.backends.minimal_kg_extractor import (
    MinimalKGExtractor,
    _coerce_int,
    _extract_text_from_response,
    _jieba_extract_names,
    _parse_characters_json,
    _strip_code_fence,
)
from bookscope.agent.errors import (
    ContentFiltered,
    ContextLimitExceeded,
    LLMFormatError,
    ProviderUnavailable,
    RateLimited,
)
from bookscope.models.schemas import ChunkResult

# ---------------------------------------------------------------------------
# Fake LLMClient
# ---------------------------------------------------------------------------


class _FakeClient:
    """实现 LLMClient Protocol 的最简 fake。

    按入参顺序依次返回 ``responses``；``raise_exc`` 不为 None 时一律抛异常。
    """

    def __init__(
        self,
        responses: list[dict[str, Any]] | None = None,
        *,
        raise_exc: Exception | None = None,
    ) -> None:
        self._responses = list(responses or [])
        self._raise_exc = raise_exc
        self.call_count = 0
        self.last_kwargs: dict[str, Any] | None = None

    def messages_create(self, **kwargs: Any) -> dict[str, Any]:
        self.call_count += 1
        self.last_kwargs = kwargs
        if self._raise_exc is not None:
            raise self._raise_exc
        if not self._responses:
            raise AssertionError("FakeClient exhausted prepared responses")
        return self._responses.pop(0)

    def extract_final_text(self, response: Any) -> str:
        """LLMClient Protocol（B-1 下沉）。

        本 fake 沿用模块级 ``_extract_text_from_response`` 读 Anthropic 形态
        content block list ——本文件全部 fixture 都按 Anthropic 形态构造，
        测试覆盖的是 KG extractor 的逻辑而非 adapter 形态差异（adapter 形态
        差异由 ``tests/agent/r2/test_minimal_kg_extractor_r2.py`` 覆盖）。
        """
        return _extract_text_from_response(response)

    def extract_usage_tokens(self, response: Any) -> tuple[int, int]:
        """LLMClient Protocol 兜底。KG extractor 不读 usage，返 (0, 0) 即可。"""
        return 0, 0


def _response_with_json(payload: dict[str, Any]) -> dict[str, Any]:
    """构造一条 Anthropic 风格 response dict，text block 内容为 JSON。"""
    return {
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }


def _response_with_text(text: str) -> dict[str, Any]:
    return {
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": text}],
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }


def _chunks(n: int) -> list[ChunkResult]:
    return [ChunkResult(index=i, text=f"这是第{i}段文字。") for i in range(n)]


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_extract_happy_path_single_batch() -> None:
    client = _FakeClient(
        [
            _response_with_json(
                {
                    "characters": [
                        {
                            "name": "朱元璋",
                            "canonical_name": "朱元璋",
                            "key_chapter_indices": [1, 2],
                        }
                    ]
                }
            )
        ]
    )
    extractor = MinimalKGExtractor(client=client, model="deepseek-chat")
    kg = extractor.extract(chunks=_chunks(3), book_title="明朝那些事儿")
    assert kg.book_title == "明朝那些事儿"
    assert len(kg.characters) == 1
    assert kg.characters[0].name == "朱元璋"
    assert kg.characters[0].key_chapter_indices == [1, 2]
    assert client.call_count == 1


def test_extract_passes_model_and_system_to_client() -> None:
    """verify adapter 收到的 model / system / messages 都合规。"""
    client = _FakeClient(
        [_response_with_json({"characters": []})]
    )
    extractor = MinimalKGExtractor(client=client, model="deepseek-chat")
    extractor.extract(chunks=_chunks(1), book_title="X")
    kwargs = client.last_kwargs
    assert kwargs is not None
    assert kwargs["model"] == "deepseek-chat"
    assert isinstance(kwargs["system"], str) and len(kwargs["system"]) > 50
    assert kwargs["tools"] == []
    assert isinstance(kwargs["messages"], list)
    assert kwargs["messages"][0]["role"] == "user"
    # user message 应该把 chunk_index header 写进去
    assert "chunk_index=0" in kwargs["messages"][0]["content"]


# ---------------------------------------------------------------------------
# Single batch vs map-reduce
# ---------------------------------------------------------------------------


def test_extract_under_threshold_single_call() -> None:
    """chunks 少于阈值时只调一次 LLM。"""
    client = _FakeClient(
        [_response_with_json({"characters": []})]
    )
    extractor = MinimalKGExtractor(client=client, max_chunks_per_batch=10)
    extractor.extract(chunks=_chunks(5), book_title="X")
    assert client.call_count == 1


def test_extract_over_threshold_map_reduce() -> None:
    """chunks 超过阈值时走多 batch；每个 batch 一次调用。"""
    client = _FakeClient(
        [
            _response_with_json(
                {"characters": [{"name": "A", "canonical_name": "A", "key_chapter_indices": [1]}]}
            ),
            _response_with_json(
                {"characters": [{"name": "B", "canonical_name": "B", "key_chapter_indices": [2]}]}
            ),
            _response_with_json(
                {"characters": [{"name": "C", "canonical_name": "C", "key_chapter_indices": [3]}]}
            ),
        ]
    )
    extractor = MinimalKGExtractor(client=client, max_chunks_per_batch=2)
    kg = extractor.extract(chunks=_chunks(5), book_title="X")  # 5 chunks / 2 -> 3 batches
    assert client.call_count == 3
    names = {c.name for c in kg.characters}
    assert names == {"A", "B", "C"}


def test_extract_merges_duplicates_across_batches() -> None:
    """同 canonical_name 在不同 batch 出现时：合并为一条，chapters 取并集 + 升序。"""
    client = _FakeClient(
        [
            _response_with_json(
                {
                    "characters": [
                        {
                            "name": "朱元璋",
                            "canonical_name": "朱元璋",
                            "key_chapter_indices": [1, 3],
                        }
                    ]
                }
            ),
            _response_with_json(
                {
                    "characters": [
                        {
                            "name": "朱重八",  # 不同写法但 canonical 一致
                            "canonical_name": "朱元璋",
                            "key_chapter_indices": [2, 3, 5],
                        }
                    ]
                }
            ),
        ]
    )
    # max_workers=1 强制串行：FakeClient.pop FIFO 与 batch idx 顺序一致，
    # 让"name 取首次出现写法"断言不受 ThreadPoolExecutor 调度顺序影响
    extractor = MinimalKGExtractor(
        client=client, max_chunks_per_batch=1, max_workers=1,
    )
    kg = extractor.extract(chunks=_chunks(2), book_title="X")
    assert len(kg.characters) == 1
    profile = kg.characters[0]
    # name 保留第一次出现的写法
    assert profile.name == "朱元璋"
    # chapters 并集升序
    assert profile.key_chapter_indices == [1, 2, 3, 5]


def test_extract_keeps_canonical_in_description_when_name_differs() -> None:
    """当 name 与 canonical_name 不同时，description 记录 canonical 指针。

    这保留了信息（便于人工审阅 kg.json），但不进入 r1 三个 backend 的读取路径。
    """
    client = _FakeClient(
        [
            _response_with_json(
                {
                    "characters": [
                        {
                            "name": "朱重八",
                            "canonical_name": "朱元璋",
                            "key_chapter_indices": [1],
                        }
                    ]
                }
            )
        ]
    )
    extractor = MinimalKGExtractor(client=client)
    kg = extractor.extract(chunks=_chunks(1), book_title="X")
    assert len(kg.characters) == 1
    assert kg.characters[0].name == "朱重八"
    assert "朱元璋" in kg.characters[0].description


# ---------------------------------------------------------------------------
# LLM 错误形态
# ---------------------------------------------------------------------------


def test_extract_non_json_text_falls_back_to_jieba() -> None:
    """LLM 返回非 JSON → 走 jieba 兜底 / 不抛异常。

    第十六波改——LLMFormatError 不再 raise（autofix 救不回的破 JSON 本来就该兜底）。
    chunks 内含中文人名 → jieba 抽出来 / kg 非空。
    """
    client = _FakeClient([_response_with_text("这完全不是 JSON，请直接忽略。")])
    extractor = MinimalKGExtractor(client=client)
    chunks = [ChunkResult(index=0, text="朱镕基与桑弘羊都是改革者。商鞅推行变法。")]
    kg = extractor.extract(chunks=chunks, book_title="X")
    names = {c.name for c in kg.characters}
    assert "朱镕基" in names or "桑弘羊" in names or "商鞅" in names


def test_extract_json_missing_characters_falls_back_to_jieba() -> None:
    """LLM 返回 JSON 但缺 'characters' 字段 → jieba 兜底而非抛错。"""
    client = _FakeClient([_response_with_text(json.dumps({"foo": "bar"}))])
    extractor = MinimalKGExtractor(client=client)
    chunks = [ChunkResult(index=0, text="毛泽东和邓小平是新中国领导人。")]
    kg = extractor.extract(chunks=chunks, book_title="X")
    names = {c.name for c in kg.characters}
    assert {"毛泽东", "邓小平"}.intersection(names)


def test_extract_llm_format_error_with_no_names_returns_empty_kg() -> None:
    """LLM 形态错 + chunks 内无人名 → 兜底降级 0 角色 / 不抛异常。

    兜底链 last-resort 行为 —— LLM 错 + jieba 也无人名时返空 kg 不挂。
    """
    client = _FakeClient([_response_with_text(json.dumps({"characters": "not a list"}))])
    extractor = MinimalKGExtractor(client=client)
    chunks = [ChunkResult(index=0, text="天空很蓝，云朵飘动。")]
    kg = extractor.extract(chunks=chunks, book_title="X")
    assert len(kg.characters) <= 1  # tolerate jieba 偶发误标


def test_extract_handles_code_fence() -> None:
    """LLM 把 JSON 包在 ```json ... ``` 里时要能正确剥离。"""
    payload = {"characters": [{"name": "X", "canonical_name": "X", "key_chapter_indices": [1]}]}
    fenced = f"```json\n{json.dumps(payload, ensure_ascii=False)}\n```"
    client = _FakeClient([_response_with_text(fenced)])
    extractor = MinimalKGExtractor(client=client)
    kg = extractor.extract(chunks=_chunks(1), book_title="X")
    assert len(kg.characters) == 1


# ---------------------------------------------------------------------------
# 边界条件
# ---------------------------------------------------------------------------


def test_extract_empty_chunks_returns_empty_kg_without_llm() -> None:
    """空 chunks 不触发 LLM 调用，直接返回空 KG。"""
    client = _FakeClient([])
    extractor = MinimalKGExtractor(client=client)
    kg = extractor.extract(chunks=[], book_title="X", language="zh")
    assert kg.book_title == "X"
    assert kg.language == "zh"
    assert kg.characters == []
    assert client.call_count == 0


def test_extract_provider_error_passthrough() -> None:
    """adapter 抛 ProviderUnavailable 时透传出来，不被 LLMFormatError 吞。"""
    client = _FakeClient(raise_exc=ProviderUnavailable("auth failed"))
    extractor = MinimalKGExtractor(client=client)
    with pytest.raises(ProviderUnavailable):
        extractor.extract(chunks=_chunks(1), book_title="X")


def test_constructor_rejects_non_positive_batch_size() -> None:
    with pytest.raises(ValueError):
        MinimalKGExtractor(client=_FakeClient(), max_chunks_per_batch=0)


# ---------------------------------------------------------------------------
# 直接测试 module-level helpers
# ---------------------------------------------------------------------------


def test_strip_code_fence_handles_plain_and_fenced() -> None:
    assert _strip_code_fence("{\"x\": 1}") == "{\"x\": 1}"
    assert _strip_code_fence("```json\n{\"x\": 1}\n```") == "{\"x\": 1}"
    assert _strip_code_fence("```\n{\"x\": 1}\n```") == "{\"x\": 1}"


def test_coerce_int_variants() -> None:
    assert _coerce_int(3) == 3
    assert _coerce_int("5") == 5
    assert _coerce_int("  7  ") == 7
    assert _coerce_int(3.0) == 3
    assert _coerce_int(3.5) is None
    assert _coerce_int("abc") is None
    assert _coerce_int(None) is None
    assert _coerce_int(True) is None  # bool rejected


def test_extract_text_from_response_raises_on_empty() -> None:
    with pytest.raises(LLMFormatError):
        _extract_text_from_response({"content": []})


def test_parse_characters_json_accepts_missing_chapters() -> None:
    """key_chapter_indices 缺失时应兜底为空 list，不抛错。"""
    out = _parse_characters_json(json.dumps({"characters": [{"name": "A", "canonical_name": "A"}]}))
    assert out[0]["key_chapter_indices"] == []


def test_parse_characters_json_rejects_non_list_chapters() -> None:
    bad = json.dumps(
        {"characters": [{"name": "A", "canonical_name": "A", "key_chapter_indices": "1,2"}]}
    )
    with pytest.raises(LLMFormatError):
        _parse_characters_json(bad)


# ---------------------------------------------------------------------------
# 第十六波加 · jieba NER 兜底 + ContentFiltered 三层重试
# ---------------------------------------------------------------------------


def test_jieba_extract_names_picks_up_chinese_person_names() -> None:
    """jieba.posseg nr 标的 happy path——已知中文人名能抽出去重。"""
    chunks = [
        ChunkResult(
            index=0,
            text="朱镕基与桑弘羊都是改革者。商鞅推行变法，毛泽东和邓小平是新中国领导人。",
        ),
        ChunkResult(
            index=1,
            text="朱镕基再次出现在第二段。王莽建立新朝。",
        ),
    ]
    entries = _jieba_extract_names(chunks)
    names = {e["name"] for e in entries}
    assert {"朱镕基", "毛泽东", "邓小平", "王莽"}.issubset(names)
    # 去重——朱镕基只出现一次
    assert sum(1 for e in entries if e["name"] == "朱镕基") == 1
    # schema 完整——每条都有 name / canonical_name / key_chapter_indices
    for entry in entries:
        assert entry["name"] == entry["canonical_name"]
        assert entry["key_chapter_indices"] == []


def test_jieba_extract_names_returns_empty_when_no_names() -> None:
    """全自然描写无人名的文本——jieba 返回空 list。"""
    chunks = [
        ChunkResult(index=0, text="天空很蓝，云朵飘动，远处是山。"),
        ChunkResult(index=1, text="春天到了，花开了，鸟在叫。"),
    ]
    entries = _jieba_extract_names(chunks)
    # 自然描写偶有误标，但应该极少——至少不该有大量误抽
    assert len(entries) <= 1  # tolerate jieba 偶发误标


def test_jieba_extract_names_filters_short_names() -> None:
    """单字过滤——长度 < DEFAULT_JIEBA_NAME_MIN_LEN 的不进 entries。"""
    chunks = [ChunkResult(index=0, text="王说：刘也来了。")]
    entries = _jieba_extract_names(chunks)
    # 单字"王"/"刘"被过滤掉
    short_names = [e["name"] for e in entries if len(e["name"]) < 2]
    assert short_names == []


def test_extract_content_filtered_exhausts_retries_then_jieba_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ContentFiltered 重试链耗尽 → 走 jieba 兜底返人名 entries / 不返空。"""
    # retry_limit 调到 2 加速测试（默认 3）
    monkeypatch.setenv("BOOKSCOPE_KG_CONTENT_FILTER_RETRY_LIMIT", "2")
    client = _FakeClient(raise_exc=ContentFiltered("test 422 new_sensitive"))
    extractor = MinimalKGExtractor(client=client)
    chunks = [
        ChunkResult(
            index=0,
            text="朱镕基与桑弘羊都是改革者。商鞅推行变法，毛泽东和邓小平是新中国领导人。",
        )
    ]
    kg = extractor.extract(chunks=chunks, book_title="测试")
    # jieba 兜底应该抽到至少 3 个真人名
    names = {c.name for c in kg.characters}
    assert {"朱镕基", "毛泽东", "邓小平"}.issubset(names)
    # client 被调了 retry_limit + 1 次（2 + 1 = 3 次都拒后走 jieba）
    assert client.call_count == 3


def test_extract_rate_limited_falls_back_to_jieba() -> None:
    """RateLimited 是暂态错——重试烧时间无意义，直接走 jieba 兜底。"""
    client = _FakeClient(raise_exc=RateLimited("429 quota exceeded"))
    extractor = MinimalKGExtractor(client=client)
    chunks = [ChunkResult(index=0, text="商鞅推行变法，王安石也是改革者。")]
    kg = extractor.extract(chunks=chunks, book_title="X")
    names = {c.name for c in kg.characters}
    assert {"商鞅", "王安石"}.intersection(names)


def test_extract_context_limit_exceeded_falls_back_to_jieba() -> None:
    """ContextLimitExceeded 当前 batch 太大，走 jieba 兜底。"""
    client = _FakeClient(raise_exc=ContextLimitExceeded("input too long"))
    extractor = MinimalKGExtractor(client=client)
    chunks = [ChunkResult(index=0, text="毛泽东与邓小平。")]
    kg = extractor.extract(chunks=chunks, book_title="X")
    names = {c.name for c in kg.characters}
    assert {"毛泽东", "邓小平"}.intersection(names)


def test_extract_content_filtered_jieba_empty_returns_empty_kg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """重试耗尽 + jieba 也无人名 → 兜底降级 0 角色 / 不抛异常。"""
    monkeypatch.setenv("BOOKSCOPE_KG_CONTENT_FILTER_RETRY_LIMIT", "1")
    client = _FakeClient(raise_exc=ContentFiltered("test"))
    extractor = MinimalKGExtractor(client=client)
    chunks = [ChunkResult(index=0, text="天空很蓝，云朵飘动，远处是连绵的山脉。")]
    kg = extractor.extract(chunks=chunks, book_title="测试")
    # 自然描写无真人名 / jieba 没抽出 / 兜底降级 0 角色但不挂
    assert len(kg.characters) <= 1  # tolerate jieba 偶发误标
