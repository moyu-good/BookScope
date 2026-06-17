"""MinimalKGExtractor 在 r2 OpenAI 形态下的兼容性测试。

### 起源

第 35 轮第十四波（Sprint 6 第二阶段）BE audit 发现：commit ``d888be9`` 之
前 ``_extract_from_batch`` 直接调模块级 ``_extract_text_from_response``，
按 Anthropic ``{"content": [{"type": "text", ...}]}`` block list 读响应。
Sprint 7 删 r1 后所有 adapter 默认走 r2 OpenAI 形态
（``{"choices": [{"message": {"content": "..."}}]}``），原 helper 读
``response.get("content")`` 恒为 ``None`` → 抛 ``LLMFormatError`` —— KG
提取在生产路径上 **100% 静默失败**。

### 修法

跟 fast_path r2 修复（commit ``0f36fb2``）同性质 ——主路径改走
``adapter.extract_final_text(response)``，让形态差异由各自 adapter 兜底。
Backlog B-1（commit ``038e11a``）已把 ``extract_final_text`` 落到
``LLMClient`` Protocol 契约里，无需扩展 extractor 构造签名。

### 本测试覆盖

- happy path：fake adapter 按 r2 OpenAI 形态返响应，KG 抽取真正常返
- 缺 ``choices`` / 缺 ``message`` / 缺 ``content``：优雅降级（adapter
  ``extract_final_text`` 返空串 → KG 抽取抛 ``LLMFormatError``，跟现行
  Anthropic 形态空响应行为一致，错误类型零回归）
- map-reduce 多 batch + 跨 batch 合并：r2 形态下并发调度也正确保序
"""

from __future__ import annotations

import json
from typing import Any

from bookscope.agent.adapters import LLMClient
from bookscope.agent.backends.minimal_kg_extractor import MinimalKGExtractor
from bookscope.models.schemas import ChunkResult

# ---------------------------------------------------------------------------
# fake r2 OpenAI 形态 client
# ---------------------------------------------------------------------------


class _FakeR2Client:
    """实现 ``LLMClient`` Protocol 的 r2 OpenAI 形态 fake。

    与 ``tests/agent/test_minimal_kg_extractor.py`` 里的 ``_FakeClient``
    最大区别：本 fake 的 ``messages_create`` 吐 OpenAI plain dict
    （``{"choices": [...], "usage": {"prompt_tokens", "completion_tokens"}}``），
    ``extract_final_text`` 按 ``choices[0].message.content`` 字符串读 ——
    完全镜像 ``DeepSeekAdapter`` / ``AnthropicAdapter`` 在 r2 下的对外
    契约。
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
            raise AssertionError("FakeR2Client exhausted prepared responses")
        return self._responses.pop(0)

    def extract_final_text(self, response: Any) -> str:
        """镜像 ``read_openai_choice_content`` —— 缺字段返空串，不抛。"""
        if response is None:
            return ""
        choices = response.get("choices") if isinstance(response, dict) else None
        if not choices:
            return ""
        first = choices[0]
        message = first.get("message") if isinstance(first, dict) else None
        if message is None:
            return ""
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str):
            return content.strip()
        return ""

    def extract_usage_tokens(self, response: Any) -> tuple[int, int]:
        usage = response.get("usage") if isinstance(response, dict) else None
        if usage is None:
            return 0, 0
        return int(usage.get("prompt_tokens", 0) or 0), int(
            usage.get("completion_tokens", 0) or 0
        )


def _r2_response_with_text(text: str) -> dict[str, Any]:
    """构造 r2 OpenAI 形态 response，``content`` 字段为 ``text``。"""
    return {
        "choices": [
            {
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


def _r2_response_with_json(payload: dict[str, Any]) -> dict[str, Any]:
    return _r2_response_with_text(json.dumps(payload, ensure_ascii=False))


def _chunks(n: int) -> list[ChunkResult]:
    return [ChunkResult(index=i, text=f"这是第{i}段文字。") for i in range(n)]


# ---------------------------------------------------------------------------
# Protocol 结构校验
# ---------------------------------------------------------------------------


def test_fake_r2_client_satisfies_llm_client_protocol() -> None:
    """守护测：fake 真符合 ``LLMClient`` Protocol。"""
    assert isinstance(_FakeR2Client(), LLMClient)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_kg_extract_works_under_r2_openai_response_shape() -> None:
    """**回归守护测**：r2 OpenAI 形态下 KG 抽取真正常返。

    修复前 ``_extract_from_batch`` 调模块级 ``_extract_text_from_response``，
    OpenAI 形态下 ``response.get("content")`` 恒为 None → 抛
    ``LLMFormatError`` —— 整条 upload → KG 链路 100% 挂。修复后走
    ``adapter.extract_final_text``，本测试断言 happy path 通过 +
    characters / chapters 解析无损。
    """
    client = _FakeR2Client(
        [
            _r2_response_with_json(
                {
                    "characters": [
                        {
                            "name": "朱元璋",
                            "canonical_name": "朱元璋",
                            "key_chapter_indices": [1, 2],
                        },
                        {
                            "name": "胡惟庸",
                            "canonical_name": "胡惟庸",
                            "key_chapter_indices": [3],
                        },
                    ]
                }
            )
        ]
    )
    extractor = MinimalKGExtractor(client=client, model="deepseek-chat")
    kg = extractor.extract(chunks=_chunks(3), book_title="明朝那些事儿")
    assert kg.book_title == "明朝那些事儿"
    assert {c.name for c in kg.characters} == {"朱元璋", "胡惟庸"}
    chapters = {c.name: c.key_chapter_indices for c in kg.characters}
    assert chapters["朱元璋"] == [1, 2]
    assert chapters["胡惟庸"] == [3]
    assert client.call_count == 1


def test_kg_extract_strips_code_fence_in_r2_response() -> None:
    """r2 OpenAI 形态下 LLM 偶尔会把 JSON 包在 ```json ... ``` 围栏里，需正常剥离。"""
    fenced = (
        "```json\n"
        + json.dumps(
            {"characters": [{"name": "李善长", "canonical_name": "李善长"}]},
            ensure_ascii=False,
        )
        + "\n```"
    )
    client = _FakeR2Client([_r2_response_with_text(fenced)])
    extractor = MinimalKGExtractor(client=client, model="deepseek-chat")
    kg = extractor.extract(chunks=_chunks(2), book_title="明朝那些事儿")
    assert len(kg.characters) == 1
    assert kg.characters[0].name == "李善长"


# ---------------------------------------------------------------------------
# Map-reduce 多 batch（跟 commit d888be9 的并发调度一起跑）
# ---------------------------------------------------------------------------


def test_kg_extract_map_reduce_merges_across_batches_under_r2() -> None:
    """r2 形态 + 跨 batch 合并：canonical_name 去重 + chapters 并集。

    跟 commit ``d888be9`` 加的 12 条并发测试一起跑 —— 验证 ThreadPoolExecutor
    保序 + r2 响应抽取双修复后多 batch 路径仍稳。
    """
    client = _FakeR2Client(
        [
            _r2_response_with_json(
                {
                    "characters": [
                        {
                            "name": "朱元璋",
                            "canonical_name": "朱元璋",
                            "key_chapter_indices": [1],
                        }
                    ]
                }
            ),
            _r2_response_with_json(
                {
                    "characters": [
                        {
                            "name": "朱元璋",
                            "canonical_name": "朱元璋",
                            "key_chapter_indices": [3, 5],
                        }
                    ]
                }
            ),
        ]
    )
    extractor = MinimalKGExtractor(
        client=client,
        model="deepseek-chat",
        max_chunks_per_batch=2,
    )
    kg = extractor.extract(chunks=_chunks(4), book_title="明朝那些事儿")
    assert client.call_count == 2
    assert len(kg.characters) == 1
    assert kg.characters[0].key_chapter_indices == [1, 3, 5]


# ---------------------------------------------------------------------------
# 缺字段降级
# ---------------------------------------------------------------------------


def test_kg_extract_missing_choices_falls_back_to_jieba() -> None:
    """r2 OpenAI 形态 response 缺 ``choices``：adapter 返空串 → KG path
    走 jieba 兜底（不再抛 LLMFormatError）。

    第十六波改——通用兜底链覆盖任何 provider / 任何错误下"不让分析"。
    chunks 内含人名 → jieba 救回 / kg 非空 / 整条链路不全挂。
    """
    client = _FakeR2Client([{"usage": {"prompt_tokens": 0, "completion_tokens": 0}}])
    extractor = MinimalKGExtractor(client=client, model="deepseek-chat")
    chunks = [ChunkResult(index=0, text="朱元璋登基。毛泽东建立新中国。")]
    kg = extractor.extract(chunks=chunks, book_title="明朝那些事儿")
    names = {c.name for c in kg.characters}
    assert {"朱元璋", "毛泽东"}.intersection(names)


def test_kg_extract_missing_message_falls_back_to_jieba() -> None:
    """``choices`` 存在但 ``message`` 缺失：同样走 jieba 兜底。"""
    client = _FakeR2Client(
        [{"choices": [{"finish_reason": "stop"}], "usage": {}}]
    )
    extractor = MinimalKGExtractor(client=client, model="deepseek-chat")
    chunks = [ChunkResult(index=0, text="商鞅推行变法，王安石也是改革者。")]
    kg = extractor.extract(chunks=chunks, book_title="明朝那些事儿")
    names = {c.name for c in kg.characters}
    assert {"商鞅", "王安石"}.intersection(names)


def test_kg_extract_null_content_falls_back_to_jieba() -> None:
    """``message.content`` 是 ``None`` （reasoning model 全程 think 无最终输出）：
    走 jieba 兜底而非抛 LLMFormatError。"""
    client = _FakeR2Client(
        [
            {
                "choices": [
                    {"message": {"role": "assistant", "content": None}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 0},
            }
        ]
    )
    extractor = MinimalKGExtractor(client=client, model="deepseek-chat")
    chunks = [ChunkResult(index=0, text="桑弘羊主持盐铁论。")]
    kg = extractor.extract(chunks=chunks, book_title="明朝那些事儿")
    names = {c.name for c in kg.characters}
    assert "桑弘羊" in names
