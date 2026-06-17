"""``bookscope.agent._internal.llm_cache`` 单测 —— Sprint 8 W2。

覆盖：

- 同 messages 第二次调用命中
- assistant 消息里 tool_calls id 归一化后跨 provider 抖动仍命中
- messages 顺序不同不命中
- tools 列表顺序差异不影响 key（按 name 排序）
- 不同 model / 不同 system 不命中
- env ``BOOKSCOPE_LLM_CACHE_DISABLED=1`` 关缓存
- 显式 ``cache_enabled=False`` 关缓存（reviewer 路径硬约束模拟）
- 失败响应（ContentFiltered / RateLimited）不写缓存
- ``invalidate_by_prompt_version`` 按 schema_version 清理
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from bookscope.agent._internal import llm_cache as llm_cache_mod
from bookscope.agent._internal.llm_cache import (
    _compute_llm_cache_key,
    _normalize_messages,
    _normalize_tools,
    clear_llm_cache,
    get_llm_cache_stats,
    invalidate_by_prompt_version,
    invoke_client_cached,
    reset_llm_cache_singleton_for_test,
)
from bookscope.agent.errors import ContentFiltered


@pytest.fixture(autouse=True)
def isolated_cache_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """每个测试用 tmp_path 独立 DB 文件，避免污染。"""
    monkeypatch.setenv("BOOKSCOPE_LLM_CACHE_DB_PATH", str(tmp_path / "llm.db"))
    # 强制重建 singleton 让它指向新路径
    reset_llm_cache_singleton_for_test()
    yield
    reset_llm_cache_singleton_for_test()


# ---------------------------------------------------------------------------
# Fake LLM client
# ---------------------------------------------------------------------------


class _FakeLLMClient:
    """记录每次 messages_create 入参 + 按预置序列吐响应。"""

    def __init__(self, responses: list[Any]) -> None:
        self._queue: list[Any] = list(responses)
        self.call_count = 0
        self.last_kwargs: dict[str, Any] | None = None

    def messages_create(self, **kwargs: Any) -> Any:
        self.call_count += 1
        self.last_kwargs = kwargs
        if not self._queue:
            raise AssertionError("client ran out of responses")
        item = self._queue.pop(0)
        if callable(item):
            return item()
        return item


def _simple_response(text: str = "ok") -> dict[str, Any]:
    """构造 Anthropic 形态 response dict（最小）。"""
    return {
        "content": [{"type": "text", "text": text}],
        "usage": {"input_tokens": 100, "output_tokens": 50},
    }


def _r2_response(text: str = "ok") -> dict[str, Any]:
    """构造 OpenAI 形态 response dict（最小）。"""
    return {
        "choices": [
            {
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
    }


# ---------------------------------------------------------------------------
# 命中 / miss 基本语义
# ---------------------------------------------------------------------------


class TestCacheHitBasic:
    def test_same_messages_second_call_hits(self) -> None:
        """同样 messages 第二次调用应命中——client 只被调一次。"""
        client = _FakeLLMClient([_simple_response("first")])
        messages = [{"role": "user", "content": "你好"}]

        r1 = invoke_client_cached(
            client,
            model="m1",
            system="sys",
            tools=[],
            messages=messages,
            max_tokens=100,
        )
        r2 = invoke_client_cached(
            client,
            model="m1",
            system="sys",
            tools=[],
            messages=messages,
            max_tokens=100,
        )

        assert client.call_count == 1
        # r1 是首次原始 response（dict），r2 是反序列化命中（dict）
        assert r1["content"][0]["text"] == "first"
        assert r2["content"][0]["text"] == "first"

    def test_r2_response_shape_round_trips(self) -> None:
        """OpenAI choices 形态响应也能 round-trip 序列化反序列化。"""
        client = _FakeLLMClient([_r2_response("r2-answer")])
        messages = [{"role": "user", "content": "Q"}]

        invoke_client_cached(
            client,
            model="m1",
            system="sys",
            tools=[],
            messages=messages,
            max_tokens=100,
        )
        cached = invoke_client_cached(
            client,
            model="m1",
            system="sys",
            tools=[],
            messages=messages,
            max_tokens=100,
        )

        assert client.call_count == 1
        assert cached["choices"][0]["message"]["content"] == "r2-answer"
        assert cached["choices"][0]["finish_reason"] == "stop"


# ---------------------------------------------------------------------------
# Key 算法稳定性
# ---------------------------------------------------------------------------


class TestKeyAlgorithm:
    def test_message_order_differs_means_miss(self) -> None:
        """messages 顺序变了应该 miss——上下文顺序影响 LLM 输出。"""
        client = _FakeLLMClient(
            [_simple_response("first"), _simple_response("second")]
        )
        msgs_a = [
            {"role": "user", "content": "Q1"},
            {"role": "assistant", "content": "A1"},
            {"role": "user", "content": "Q2"},
        ]
        msgs_b = [
            {"role": "user", "content": "Q2"},
            {"role": "assistant", "content": "A1"},
            {"role": "user", "content": "Q1"},
        ]

        invoke_client_cached(
            client, model="m1", system="sys", tools=[], messages=msgs_a, max_tokens=100
        )
        invoke_client_cached(
            client, model="m1", system="sys", tools=[], messages=msgs_b, max_tokens=100
        )

        assert client.call_count == 2

    def test_tools_order_does_not_affect_key(self) -> None:
        """tools 列表顺序差异不该影响 key——provider 端 tool 顺序无关紧要。"""
        client = _FakeLLMClient([_simple_response("first")])
        tools_a = [
            {"name": "tool_b", "input_schema": {}},
            {"name": "tool_a", "input_schema": {}},
        ]
        tools_b = [
            {"name": "tool_a", "input_schema": {}},
            {"name": "tool_b", "input_schema": {}},
        ]
        messages = [{"role": "user", "content": "Q"}]

        invoke_client_cached(
            client,
            model="m1",
            system="sys",
            tools=tools_a,
            messages=messages,
            max_tokens=100,
        )
        invoke_client_cached(
            client,
            model="m1",
            system="sys",
            tools=tools_b,
            messages=messages,
            max_tokens=100,
        )

        # 顺序无关 → 第二次命中
        assert client.call_count == 1

    def test_different_model_is_miss(self) -> None:
        client = _FakeLLMClient(
            [_simple_response("first"), _simple_response("second")]
        )
        messages = [{"role": "user", "content": "Q"}]

        invoke_client_cached(
            client,
            model="model_a",
            system="sys",
            tools=[],
            messages=messages,
            max_tokens=100,
        )
        invoke_client_cached(
            client,
            model="model_b",
            system="sys",
            tools=[],
            messages=messages,
            max_tokens=100,
        )

        assert client.call_count == 2

    def test_different_system_is_miss(self) -> None:
        client = _FakeLLMClient(
            [_simple_response("first"), _simple_response("second")]
        )
        messages = [{"role": "user", "content": "Q"}]

        invoke_client_cached(
            client,
            model="m1",
            system="sys_v1",
            tools=[],
            messages=messages,
            max_tokens=100,
        )
        invoke_client_cached(
            client,
            model="m1",
            system="sys_v2",
            tools=[],
            messages=messages,
            max_tokens=100,
        )

        assert client.call_count == 2

    def test_tool_call_id_normalization_makes_keys_stable(self) -> None:
        """provider 端 tool_call random id 差异不该让两次 input 算出不同 key。"""
        # 模拟两次 input 完全一样但 assistant.tool_calls 的 id 来自 provider
        # 端 random 生成（call_abc / call_xyz），希望算出同 key。
        msgs_a = [
            {"role": "user", "content": "Q"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_abc123",
                        "type": "function",
                        "function": {"name": "search", "arguments": "{}"},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_abc123",
                "content": "result",
            },
        ]
        msgs_b = [
            {"role": "user", "content": "Q"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_xyz789",
                        "type": "function",
                        "function": {"name": "search", "arguments": "{}"},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_xyz789",
                "content": "result",
            },
        ]

        key_a = _compute_llm_cache_key(
            model="m1", system="sys", tools=[], messages=msgs_a, max_tokens=100
        )
        key_b = _compute_llm_cache_key(
            model="m1", system="sys", tools=[], messages=msgs_b, max_tokens=100
        )
        assert key_a == key_b

    def test_normalize_messages_remaps_tool_call_ids(self) -> None:
        msgs = [
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": "call_xyz", "function": {"name": "f"}},
                    {"id": "call_abc", "function": {"name": "g"}},
                ],
            },
            {"role": "tool", "tool_call_id": "call_xyz", "content": "r1"},
            {"role": "tool", "tool_call_id": "call_abc", "content": "r2"},
        ]
        out = _normalize_messages(msgs)
        assert out[0]["tool_calls"][0]["id"] == "call_0"
        assert out[0]["tool_calls"][1]["id"] == "call_1"
        assert out[1]["tool_call_id"] == "call_0"
        assert out[2]["tool_call_id"] == "call_1"

    def test_normalize_tools_sorts_by_name(self) -> None:
        # 混合 r1 / r2 风格
        tools = [
            {"type": "function", "function": {"name": "zeta"}},
            {"name": "alpha", "input_schema": {}},
            {"type": "function", "function": {"name": "beta"}},
        ]
        out = _normalize_tools(tools)
        # 排序后顺序应当是 alpha / beta / zeta
        names = []
        for t in out:
            if "function" in t:
                names.append(t["function"]["name"])
            else:
                names.append(t["name"])
        assert names == ["alpha", "beta", "zeta"]


# ---------------------------------------------------------------------------
# 开关 / opt-out
# ---------------------------------------------------------------------------


class TestCacheDisabled:
    def test_env_disabled_bypasses_cache(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BOOKSCOPE_LLM_CACHE_DISABLED", "1")
        client = _FakeLLMClient(
            [_simple_response("first"), _simple_response("second")]
        )
        messages = [{"role": "user", "content": "Q"}]

        invoke_client_cached(
            client, model="m1", system="sys", tools=[], messages=messages, max_tokens=100
        )
        invoke_client_cached(
            client, model="m1", system="sys", tools=[], messages=messages, max_tokens=100
        )

        # 两次都打 client，缓存被关
        assert client.call_count == 2

    def test_cache_enabled_false_bypasses(self) -> None:
        """模拟 reviewer 路径硬约束——显式关缓存。"""
        client = _FakeLLMClient(
            [_simple_response("first"), _simple_response("second")]
        )
        messages = [{"role": "user", "content": "Q"}]

        invoke_client_cached(
            client,
            model="m1",
            system="sys",
            tools=[],
            messages=messages,
            max_tokens=100,
            cache_enabled=False,
        )
        invoke_client_cached(
            client,
            model="m1",
            system="sys",
            tools=[],
            messages=messages,
            max_tokens=100,
            cache_enabled=False,
        )

        assert client.call_count == 2


# ---------------------------------------------------------------------------
# Reviewer 路径不接缓存的硬规则验证
# ---------------------------------------------------------------------------


class TestReviewerNotCached:
    def test_reviewer_module_does_not_use_invoke_client_cached(self) -> None:
        """硬规则验证：reviewer.py 不能 import 任何 cached wrapper。

        reviewer 每次评分必须重新跑（避免 stale 评分），ADR-008 Open Q-5
        明示 P2 待判前不接缓存。
        """
        import bookscope.agent.reviewer as reviewer_mod

        source = Path(reviewer_mod.__file__).read_text(encoding="utf-8")
        assert "invoke_client_cached" not in source
        assert "from bookscope.agent._internal.llm_cache" not in source
        # reviewer 直接调 client.messages_create，不走 invoke_client helper
        assert "client.messages_create" in source


# ---------------------------------------------------------------------------
# 失败响应不写缓存
# ---------------------------------------------------------------------------


class TestFailureNotCached:
    def test_content_filtered_not_cached(self) -> None:
        """ContentFiltered 抛出后不写缓存——下次重试可能成功。"""

        def _raise_filtered() -> Any:
            raise ContentFiltered("blocked")

        # 第一次抛 ContentFiltered；第二次返成功
        client = _FakeLLMClient([_raise_filtered, _simple_response("retry-ok")])
        messages = [{"role": "user", "content": "Q"}]

        with pytest.raises(ContentFiltered):
            invoke_client_cached(
                client,
                model="m1",
                system="sys",
                tools=[],
                messages=messages,
                max_tokens=100,
            )

        # 同 input 再来一次——应该重新调 client（不命中），拿到 "retry-ok"
        r = invoke_client_cached(
            client,
            model="m1",
            system="sys",
            tools=[],
            messages=messages,
            max_tokens=100,
        )
        assert client.call_count == 2
        assert r["content"][0]["text"] == "retry-ok"


# ---------------------------------------------------------------------------
# 版本失效
# ---------------------------------------------------------------------------


class TestInvalidateByVersion:
    def test_invalidate_clears_current_schema_rows(self) -> None:
        """invalidate_by_prompt_version 传当前 schema_version 应该清掉所有 row。"""
        client = _FakeLLMClient([_simple_response("a"), _simple_response("b")])
        messages = [{"role": "user", "content": "Q"}]

        invoke_client_cached(
            client, model="m1", system="sys", tools=[], messages=messages, max_tokens=100
        )
        # 命中验证
        invoke_client_cached(
            client, model="m1", system="sys", tools=[], messages=messages, max_tokens=100
        )
        assert client.call_count == 1

        # 失效当前 schema_version
        removed = invalidate_by_prompt_version(
            llm_cache_mod.LLM_CACHE_SCHEMA_VERSION
        )
        assert removed >= 1

        # 第三次调用应当 miss → client 再被调
        invoke_client_cached(
            client, model="m1", system="sys", tools=[], messages=messages, max_tokens=100
        )
        assert client.call_count == 2


# ---------------------------------------------------------------------------
# Stats / clear
# ---------------------------------------------------------------------------


class TestStatsAndClear:
    def test_stats_reflects_hits_and_misses(self) -> None:
        client = _FakeLLMClient([_simple_response("first")])
        messages = [{"role": "user", "content": "Q"}]

        invoke_client_cached(
            client, model="m1", system="sys", tools=[], messages=messages, max_tokens=100
        )  # miss → 写
        invoke_client_cached(
            client, model="m1", system="sys", tools=[], messages=messages, max_tokens=100
        )  # hit
        invoke_client_cached(
            client, model="m1", system="sys", tools=[], messages=messages, max_tokens=100
        )  # hit

        s = get_llm_cache_stats()
        # 至少 2 hit 1 miss（第一次是 miss）
        assert s["hit"] >= 2
        assert s["miss"] >= 1
        assert s["size"] >= 1

    def test_clear_llm_cache_empties_table(self) -> None:
        client = _FakeLLMClient(
            [_simple_response("first"), _simple_response("second")]
        )
        messages = [{"role": "user", "content": "Q"}]
        invoke_client_cached(
            client, model="m1", system="sys", tools=[], messages=messages, max_tokens=100
        )
        clear_llm_cache()
        # 清后再调应 miss
        invoke_client_cached(
            client, model="m1", system="sys", tools=[], messages=messages, max_tokens=100
        )
        assert client.call_count == 2
