"""Tests for bookscope.api.dependencies —— provider 构造与默认值。

第 30 轮：astron 已下线（API 失效），曾改测 minimax provider。
2026-06-11：minimax 也彻底弃用，provider 收回到 deepseek / anthropic 两家。
本套现在验证：
- ``DEFAULT_MODEL_BY_PROVIDER`` 只剩 deepseek / anthropic
- ``build_llm_client_from_params`` 识别这两家
- ``base_url`` 参数在 deepseek 路径能用（代理 / 私有部署 / 其他 OpenAI 兼容端点）
- minimax 等已弃用 provider 走 ``unsupported provider`` 分支报错
"""

from __future__ import annotations

import pytest

from bookscope.agent.adapters import AnthropicAdapter, DeepSeekAdapter
from bookscope.api.dependencies import (
    DEFAULT_MODEL_BY_PROVIDER,
    build_llm_client_from_params,
    default_model_for,
)


class TestDefaultModelFor:
    def test_deepseek_unchanged(self) -> None:
        assert default_model_for("deepseek") == "deepseek-v4-flash"

    def test_anthropic_unchanged(self) -> None:
        assert default_model_for("anthropic") == "claude-sonnet-4-6"

    def test_unknown_falls_back_to_deepseek(self) -> None:
        """Literal 在 schema 层兜底，这里只是 dict.get 默认值演练。"""
        assert default_model_for("unknown") == "deepseek-v4-flash"  # type: ignore[arg-type]

    def test_default_model_map_has_no_minimax(self) -> None:
        """minimax 已弃用：不再出现在默认模型表里。"""
        assert "minimax" not in DEFAULT_MODEL_BY_PROVIDER
        assert set(DEFAULT_MODEL_BY_PROVIDER) == {"deepseek", "anthropic"}


class TestBuildLLMClientFromParams:
    def test_deepseek_can_use_base_url_for_proxy(self) -> None:
        """deepseek 走代理 / OpenRouter 场景：允许覆盖 base_url。"""
        proxy = "https://openrouter.example.com/v1"
        client = build_llm_client_from_params(
            provider="deepseek",
            api_key="test-key-123",
            base_url=proxy,
        )
        assert isinstance(client, DeepSeekAdapter)
        assert client._base_url == proxy

    def test_deepseek_default_base_url_unchanged_when_none(self) -> None:
        """未传 base_url 时 deepseek 应走 adapter 自带的默认值。"""
        client = build_llm_client_from_params(
            provider="deepseek", api_key="test-key-123",
        )
        assert isinstance(client, DeepSeekAdapter)
        # DeepSeekAdapter 内部默认值定义在 adapter 本身，此处不硬编码 URL。
        assert "deepseek" in client._base_url

    def test_anthropic_ignores_base_url(self) -> None:
        """AnthropicAdapter 当前不消费 base_url，传入应被静默忽略。"""
        client = build_llm_client_from_params(
            provider="anthropic",
            api_key="test-key-123",
            base_url="https://ignored.example.com",
        )
        assert isinstance(client, AnthropicAdapter)

    def test_minimax_now_unsupported(self) -> None:
        """minimax 已彻底弃用：走 unsupported provider 分支报错。"""
        with pytest.raises(ValueError, match="unsupported provider"):
            build_llm_client_from_params(
                provider="minimax", api_key="test-key-123",
            )

    def test_unsupported_provider_raises(self) -> None:
        with pytest.raises(ValueError, match="unsupported provider"):
            build_llm_client_from_params(
                provider="unknown-provider", api_key="test-key-123",
            )
