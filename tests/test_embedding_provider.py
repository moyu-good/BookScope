"""Tests for bookscope.store.embedding_provider — SiliconFlow API only (ADR-006)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from bookscope.store.embedding_provider import (
    EmbeddingProvider,
    SiliconFlowProvider,
    get_embedding_provider,
)

# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------


class TestProtocolCompliance:

    def test_siliconflow_satisfies_protocol(self):
        assert isinstance(SiliconFlowProvider(api_key="test"), EmbeddingProvider)


# ---------------------------------------------------------------------------
# SiliconFlowProvider
# ---------------------------------------------------------------------------


class TestSiliconFlowProvider:

    def test_name_contains_model(self):
        p = SiliconFlowProvider(api_key="k", model="BAAI/bge-m3")
        assert "bge-m3" in p.name

    def test_dim_is_1024(self):
        assert SiliconFlowProvider(api_key="k").dim == 1024

    @patch("requests.post")
    def test_encode_documents_basic(self, mock_post):
        mock_post.return_value.json.return_value = {
            "data": [
                {"index": 0, "embedding": [1.0] * 1024},
                {"index": 1, "embedding": [2.0] * 1024},
            ],
        }
        mock_post.return_value.raise_for_status = MagicMock()

        p = SiliconFlowProvider(api_key="test-key")
        result = p.encode_documents(["hello", "world"])

        assert result.shape == (2, 1024)
        assert result.dtype == np.float32
        mock_post.assert_called_once()

        # Verify auth header
        call_kwargs = mock_post.call_args
        assert "Bearer test-key" in call_kwargs.kwargs["headers"]["Authorization"]

    @patch("requests.post")
    def test_encode_documents_reorders_by_index(self, mock_post):
        """API may return items out of order; provider should sort by index."""
        mock_post.return_value.json.return_value = {
            "data": [
                {"index": 1, "embedding": [2.0] * 1024},
                {"index": 0, "embedding": [1.0] * 1024},
            ],
        }
        mock_post.return_value.raise_for_status = MagicMock()

        p = SiliconFlowProvider(api_key="k")
        result = p.encode_documents(["a", "b"])

        assert result[0, 0] == pytest.approx(1.0)
        assert result[1, 0] == pytest.approx(2.0)

    @patch("requests.post")
    def test_encode_documents_batching(self, mock_post):
        """Texts exceeding batch size should trigger multiple API calls."""
        mock_post.return_value.raise_for_status = MagicMock()

        # Simulate two batches
        call_count = {"n": 0}

        def _json():
            call_count["n"] += 1
            if call_count["n"] == 1:
                return {"data": [{"index": i, "embedding": [float(i)] * 1024} for i in range(32)]}
            return {"data": [{"index": i, "embedding": [float(i + 32)] * 1024} for i in range(3)]}

        mock_post.return_value.json = _json

        p = SiliconFlowProvider(api_key="k")
        texts = [f"text{i}" for i in range(35)]
        result = p.encode_documents(texts)

        assert result.shape == (35, 1024)
        assert mock_post.call_count == 2

    def test_encode_documents_empty(self):
        p = SiliconFlowProvider(api_key="k")
        result = p.encode_documents([])
        assert result.shape == (0, 1024)

    def test_encode_queries_delegates_to_documents(self):
        """SiliconFlow does not differentiate queries from documents."""
        p = SiliconFlowProvider(api_key="k")
        with patch.object(p, "encode_documents") as mock_enc:
            mock_enc.return_value = np.ones((1, 1024), dtype=np.float32)
            result = p.encode_queries(["query"])
            mock_enc.assert_called_once_with(["query"])
            assert result.shape == (1, 1024)

    @patch("requests.post")
    def test_api_error_raises(self, mock_post):
        from requests import HTTPError

        mock_post.return_value.raise_for_status.side_effect = (
            HTTPError("401 Unauthorized")
        )
        p = SiliconFlowProvider(api_key="bad-key")
        with pytest.raises(HTTPError):
            p.encode_documents(["test"])

    def test_api_key_from_env(self):
        with patch.dict("os.environ", {"SILICONFLOW_API_KEY": "env-key"}):
            p = SiliconFlowProvider()
            assert p._api_key == "env-key"


# ---------------------------------------------------------------------------
# get_embedding_provider (factory) — ADR-006 simplified
# ---------------------------------------------------------------------------


class TestGetEmbeddingProvider:

    def test_explicit_siliconflow(self):
        with patch.dict("os.environ", {
            "BOOKSCOPE_EMBEDDING_PROVIDER": "siliconflow",
            "SILICONFLOW_API_KEY": "key",
        }):
            p = get_embedding_provider()
            assert isinstance(p, SiliconFlowProvider)

    def test_auto_siliconflow_when_key_present(self):
        with patch.dict("os.environ", {
            "BOOKSCOPE_EMBEDDING_PROVIDER": "",
            "SILICONFLOW_API_KEY": "auto-key",
        }):
            p = get_embedding_provider()
            assert isinstance(p, SiliconFlowProvider)

    def test_auto_none_when_nothing_available(self):
        with patch.dict("os.environ", {
            "BOOKSCOPE_EMBEDDING_PROVIDER": "",
            "SILICONFLOW_API_KEY": "",
        }):
            p = get_embedding_provider()
            assert p is None

    def test_unknown_explicit_falls_back_to_none(self):
        """ADR-006：local tiers 已移除，未知 provider 名不应命中任何实现。"""
        with patch.dict("os.environ", {
            "BOOKSCOPE_EMBEDDING_PROVIDER": "local-qwen3",
            "SILICONFLOW_API_KEY": "",
        }):
            p = get_embedding_provider()
            assert p is None
