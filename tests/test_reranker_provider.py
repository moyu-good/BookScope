"""Tests for bookscope.store.reranker_provider — SiliconFlow rerank API only.

关键原则：不发真网络请求。``requests.post`` 全程 mock，验证请求体形状、
响应解析、以及三段式工厂（总开关 / 显式 / 自动 / 兜底）的解析顺序。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from bookscope.store.reranker_provider import (
    RerankerProvider,
    SiliconFlowRerankerProvider,
    get_reranker_provider,
)

# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------


class TestProtocolCompliance:

    def test_siliconflow_satisfies_protocol(self):
        assert isinstance(
            SiliconFlowRerankerProvider(api_key="test"), RerankerProvider
        )


# ---------------------------------------------------------------------------
# SiliconFlowRerankerProvider
# ---------------------------------------------------------------------------


class TestSiliconFlowRerankerProvider:

    def test_name_contains_model(self):
        p = SiliconFlowRerankerProvider(api_key="k")
        assert "bge-reranker-v2-m3" in p.name

    def test_default_model(self):
        p = SiliconFlowRerankerProvider(api_key="k")
        assert p._model == "BAAI/bge-reranker-v2-m3"

    def test_api_key_from_env(self):
        with patch.dict("os.environ", {"SILICONFLOW_API_KEY": "env-key"}):
            p = SiliconFlowRerankerProvider()
            assert p._api_key == "env-key"

    def test_empty_documents_short_circuits(self):
        """空候选直接返回空列表，不发请求。"""
        p = SiliconFlowRerankerProvider(api_key="k")
        with patch("requests.post") as mock_post:
            result = p.rerank("query", [])
            assert result == []
            mock_post.assert_not_called()

    @patch("requests.post")
    def test_rerank_maps_results(self, mock_post):
        """响应 {"results":[{"index","relevance_score"},...]} 映射成 [(下标, 分)]。"""
        mock_post.return_value.json.return_value = {
            "results": [
                {"index": 2, "relevance_score": 0.95},
                {"index": 0, "relevance_score": 0.40},
                {"index": 1, "relevance_score": 0.12},
            ],
        }
        mock_post.return_value.raise_for_status = MagicMock()

        p = SiliconFlowRerankerProvider(api_key="test-key")
        result = p.rerank("查询", ["a", "b", "c"], top_n=3)

        assert result == [(2, pytest.approx(0.95)), (0, pytest.approx(0.40)),
                          (1, pytest.approx(0.12))]

    @patch("requests.post")
    def test_request_body_shape(self, mock_post):
        """请求体含 model/query/documents/top_n/return_documents=false + 鉴权头。"""
        mock_post.return_value.json.return_value = {"results": []}
        mock_post.return_value.raise_for_status = MagicMock()

        p = SiliconFlowRerankerProvider(api_key="test-key")
        p.rerank("查询词", ["doc1", "doc2"], top_n=2)

        mock_post.assert_called_once()
        kwargs = mock_post.call_args.kwargs
        body = kwargs["json"]
        assert body["model"] == "BAAI/bge-reranker-v2-m3"
        assert body["query"] == "查询词"
        assert body["documents"] == ["doc1", "doc2"]
        assert body["top_n"] == 2
        assert body["return_documents"] is False
        assert "Bearer test-key" in kwargs["headers"]["Authorization"]

    @patch("requests.post")
    def test_top_n_omitted_when_none(self, mock_post):
        """top_n 为 None 时请求体不带该字段（让 API 返回全部排序）。"""
        mock_post.return_value.json.return_value = {"results": []}
        mock_post.return_value.raise_for_status = MagicMock()

        p = SiliconFlowRerankerProvider(api_key="k")
        p.rerank("q", ["a"])

        body = mock_post.call_args.kwargs["json"]
        assert "top_n" not in body

    @patch("requests.post")
    def test_api_error_raises(self, mock_post):
        from requests import HTTPError

        mock_post.return_value.raise_for_status.side_effect = (
            HTTPError("401 Unauthorized")
        )
        p = SiliconFlowRerankerProvider(api_key="bad-key")
        with pytest.raises(HTTPError):
            p.rerank("q", ["a", "b"])


# ---------------------------------------------------------------------------
# get_reranker_provider (factory)
# ---------------------------------------------------------------------------


class TestGetRerankerProvider:

    def test_off_by_default_returns_none(self):
        """总开关默认 off：连 key 都不看，直接 None。"""
        with patch.dict("os.environ", {
            "BOOKSCOPE_RERANK": "",
            "SILICONFLOW_API_KEY": "key",
        }):
            assert get_reranker_provider() is None

    def test_off_explicit_returns_none_even_with_key(self):
        with patch.dict("os.environ", {
            "BOOKSCOPE_RERANK": "off",
            "SILICONFLOW_API_KEY": "key",
        }):
            assert get_reranker_provider() is None

    def test_on_explicit_provider(self):
        with patch.dict("os.environ", {
            "BOOKSCOPE_RERANK": "on",
            "BOOKSCOPE_RERANKER_PROVIDER": "siliconflow",
            "SILICONFLOW_API_KEY": "key",
        }):
            p = get_reranker_provider()
            assert isinstance(p, SiliconFlowRerankerProvider)

    def test_on_auto_when_key_present(self):
        with patch.dict("os.environ", {
            "BOOKSCOPE_RERANK": "on",
            "BOOKSCOPE_RERANKER_PROVIDER": "",
            "SILICONFLOW_API_KEY": "auto-key",
        }):
            p = get_reranker_provider()
            assert isinstance(p, SiliconFlowRerankerProvider)

    def test_on_but_no_key_returns_none(self):
        """开关开了但没 key：可见跳过（返回 None），不报错。"""
        with patch.dict("os.environ", {
            "BOOKSCOPE_RERANK": "on",
            "BOOKSCOPE_RERANKER_PROVIDER": "",
            "SILICONFLOW_API_KEY": "",
        }):
            assert get_reranker_provider() is None

    def test_on_unknown_explicit_falls_back_to_auto(self):
        """未知 provider 名：警告后退回自动检测（有 key 则起 SiliconFlow）。"""
        with patch.dict("os.environ", {
            "BOOKSCOPE_RERANK": "on",
            "BOOKSCOPE_RERANKER_PROVIDER": "some-unknown",
            "SILICONFLOW_API_KEY": "key",
        }):
            p = get_reranker_provider()
            assert isinstance(p, SiliconFlowRerankerProvider)
