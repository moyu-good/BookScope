"""reviewer 重试路径单测——ContentFiltered 重试 + 空 text 重试。

第十六波 dogfood 两本作者亲选书答题时 reviewer 都返空 text 导致评分挂——
加 empty text 重试后才能救回。这一波同时补 ContentFiltered 重试的缺失覆盖
（之前只有 integration 测试 monkey-patch 整个 review_answer，内部 retry
路径无单测护栏）。

按 memory `feedback_global_not_single_case.md`——单测覆盖错误类不是单 case：
每种间歇性错误（422 / empty text）各一条断言重试机制起作用 + 一条断言超限抛错。
"""

from __future__ import annotations

from typing import Any

import pytest

from bookscope.agent import reviewer as reviewer_module
from bookscope.agent.errors import ContentFiltered, LLMFormatError
from bookscope.agent.reviewer import review_answer


class _ContentFilterFlakeyClient:
    """前 N 次抛 ContentFiltered，第 N+1 次返合法 review JSON。"""

    def __init__(self, *, raise_count: int, response: dict[str, Any]) -> None:
        self._raise_count = raise_count
        self._response = response
        self.call_count = 0

    def messages_create(self, **_kwargs: Any) -> dict[str, Any]:
        self.call_count += 1
        if self.call_count <= self._raise_count:
            raise ContentFiltered(f"422 attempt {self.call_count}")
        return self._response


class _EmptyTextFlakeyClient:
    """前 N 次返空 text（minimax 静默拒答形态），第 N+1 次返合法 JSON。"""

    def __init__(self, *, empty_count: int, response: dict[str, Any]) -> None:
        self._empty_count = empty_count
        self._response = response
        self.call_count = 0

    def messages_create(self, **_kwargs: Any) -> dict[str, Any]:
        self.call_count += 1
        if self.call_count <= self._empty_count:
            return {
                "content": [{"type": "text", "text": ""}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 0},
            }
        return self._response


def _good_review_response() -> dict[str, Any]:
    """合法 review JSON response——填够 rubric 必填字段。"""
    payload = (
        '{"scores": {"structural_judgment": 5, "evidence_density": 5, '
        '"honesty": 5, "actionability": 5, "cross_chapter_coherence": 5}, '
        '"per_dimension_comment": {"structural_judgment": "ok", '
        '"evidence_density": "ok", "honesty": "ok", "actionability": "ok", '
        '"cross_chapter_coherence": "ok"}, "overall": 25, '
        '"top_issues": [], "single_most_valuable_improvement": "none"}'
    )
    return {
        "content": [{"type": "text", "text": payload}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 10, "output_tokens": 50},
    }


def _common_args() -> dict[str, Any]:
    return dict(
        model="MiniMax-M2.7",
        question="测试题",
        answer="测试答案",
        citations=[{"chapter": 1, "snippet": "测试 snippet"}],
        book_title="测试书",
        language="zh",
        max_tokens=4000,
    )


def test_reviewer_content_filtered_retry_recovers_within_limit() -> None:
    """ContentFiltered 抛 1 次后第 2 次成功——返回合法 review dict。"""
    client = _ContentFilterFlakeyClient(raise_count=1, response=_good_review_response())
    result = review_answer(client=client, **_common_args())
    assert result["overall"] == 25
    assert client.call_count == 2  # 1 次拒 + 1 次救回


def test_reviewer_content_filtered_exceeds_limit_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ContentFiltered 超出重试上限——透传异常给上层。"""
    monkeypatch.setattr(reviewer_module, "DEFAULT_CONTENT_FILTER_RETRY_LIMIT", 1)
    client = _ContentFilterFlakeyClient(
        raise_count=10, response=_good_review_response()
    )
    with pytest.raises(ContentFiltered):
        review_answer(client=client, **_common_args())


def test_reviewer_empty_text_retry_recovers_within_limit() -> None:
    """空 text 返 1 次后第 2 次成功——返回合法 review dict。

    第十六波加——minimax 间歇性返 200 + 空 content 是另一种拒答形态，
    跟 422 同 root cause 不同表现，重试常能过。
    """
    client = _EmptyTextFlakeyClient(empty_count=1, response=_good_review_response())
    result = review_answer(client=client, **_common_args())
    assert result["overall"] == 25
    assert client.call_count == 2


def test_reviewer_empty_text_exceeds_limit_raises_format_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """空 text 超出重试上限——抛 LLMFormatError 含 attempts 数。"""
    monkeypatch.setattr(reviewer_module, "DEFAULT_EMPTY_TEXT_RETRY_LIMIT", 1)
    client = _EmptyTextFlakeyClient(
        empty_count=10, response=_good_review_response()
    )
    with pytest.raises(LLMFormatError) as excinfo:
        review_answer(client=client, **_common_args())
    assert "empty text" in str(excinfo.value)
    assert "attempts" in str(excinfo.value)


class _RecordingClient:
    """记下每次 messages_create 收到的 system，前 N 次返空 / 之后返合法 JSON。"""

    def __init__(self, *, empty_count: int, response: dict[str, Any]) -> None:
        self._empty_count = empty_count
        self._response = response
        self.call_count = 0
        self.systems_seen: list[str] = []

    def messages_create(self, **kwargs: Any) -> dict[str, Any]:
        self.call_count += 1
        self.systems_seen.append(kwargs.get("system", ""))
        if self.call_count <= self._empty_count:
            return {
                "content": [{"type": "text", "text": ""}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 0},
            }
        return self._response


def test_reviewer_empty_text_second_attempt_adds_neutralize_hint() -> None:
    """空 text 第 1 次失败后第 2 次 system 末尾要 append 中性化提示。

    给 LLM 一次改用学术化措辞的机会再降级——比单纯重试同 input 更有
    救回概率。
    """
    client = _RecordingClient(empty_count=1, response=_good_review_response())
    review_answer(client=client, **_common_args())
    assert client.call_count == 2
    # 第 1 次 system 不含中性化提示
    assert "中性、学术化" not in client.systems_seen[0]
    # 第 2 次 system 末尾追加了中性化提示
    assert "中性、学术化" in client.systems_seen[1]
    assert "评分 rubric / JSON 结构不变" in client.systems_seen[1]


class _OpenAIFormClient:
    """返回 OpenAI 形态 response 的 mock——r2 现行 adapter 的真实形态。

    2026-06-10 修 bug 后加：Sprint 7 起 adapter 返回
    ``choices[0].message.content``，reviewer 原来只认 Anthropic block list，
    导致 r2 切换起 reviewer 对所有 provider 一律 "returned empty text"
    （exp006 的 60/60 全空根因）。本 mock 锁住 OpenAI 形态必须能被抽出文本。
    """

    def __init__(self, response: dict[str, Any]) -> None:
        self._response = response
        self.call_count = 0

    def messages_create(self, **_kwargs: Any) -> dict[str, Any]:
        self.call_count += 1
        return self._response


def _good_review_response_openai_form() -> dict[str, Any]:
    payload = _good_review_response()["content"][0]["text"]
    return {
        "choices": [
            {
                "message": {"content": payload, "tool_calls": None},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 50},
    }


def test_reviewer_extracts_openai_form_response() -> None:
    """OpenAI 形态（r2 现行 adapter）的 response 必须能抽出文本并评分。"""
    client = _OpenAIFormClient(_good_review_response_openai_form())
    result = review_answer(client=client, **_common_args())
    assert result["overall"] == 25
    assert client.call_count == 1
