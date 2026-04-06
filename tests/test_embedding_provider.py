"""Tests for bookscope.store.embedding_provider — three-tier embedding architecture."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from bookscope.store.embedding_provider import (
    BgeM3LocalProvider,
    EmbeddingProvider,
    Qwen3LocalProvider,
    SiliconFlowProvider,
    _is_model_cached,
    get_embedding_provider,
)

# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------


class TestProtocolCompliance:

    def test_siliconflow_satisfies_protocol(self):
        assert isinstance(SiliconFlowProvider(api_key="test"), EmbeddingProvider)

    def test_qwen3_satisfies_protocol(self):
        assert isinstance(Qwen3LocalProvider(), EmbeddingProvider)

    def test_bgem3_satisfies_protocol(self):
        assert isinstance(BgeM3LocalProvider(), EmbeddingProvider)


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
# Qwen3LocalProvider
# ---------------------------------------------------------------------------


class TestQwen3LocalProvider:

    def test_name_contains_qwen3(self):
        assert "Qwen3" in Qwen3LocalProvider().name

    def test_dim_is_1024(self):
        assert Qwen3LocalProvider().dim == 1024

    def test_encode_documents_calls_model(self):
        p = Qwen3LocalProvider()
        mock_model = MagicMock()
        mock_model.encode.return_value = np.zeros((2, 1024), dtype=np.float32)
        p._model = mock_model

        result = p.encode_documents(["a", "b"])
        assert result.shape == (2, 1024)
        # Documents should NOT have instruction prefix
        call_args = mock_model.encode.call_args[0][0]
        assert not any(t.startswith("Instruct:") for t in call_args)

    def test_encode_queries_adds_instruction_prefix(self):
        p = Qwen3LocalProvider()
        mock_model = MagicMock()
        mock_model.encode.return_value = np.zeros((1, 1024), dtype=np.float32)
        p._model = mock_model

        p.encode_queries(["朱元璋是谁"])
        call_args = mock_model.encode.call_args[0][0]
        assert all(t.startswith("Instruct:") for t in call_args)
        assert "朱元璋是谁" in call_args[0]

    def test_encode_documents_empty(self):
        p = Qwen3LocalProvider()
        result = p.encode_documents([])
        assert result.shape == (0, 1024)

    def test_encode_queries_empty(self):
        p = Qwen3LocalProvider()
        result = p.encode_queries([])
        assert result.shape == (0, 1024)


# ---------------------------------------------------------------------------
# BgeM3LocalProvider
# ---------------------------------------------------------------------------


class TestBgeM3LocalProvider:

    def test_name_contains_bge(self):
        assert "bge-m3" in BgeM3LocalProvider().name

    def test_dim_is_1024(self):
        assert BgeM3LocalProvider().dim == 1024

    def test_encode_documents_calls_model(self):
        p = BgeM3LocalProvider()
        mock_model = MagicMock()
        mock_model.encode.return_value = np.zeros((2, 1024), dtype=np.float32)
        p._model = mock_model

        result = p.encode_documents(["a", "b"])
        assert result.shape == (2, 1024)

    def test_encode_queries_same_as_documents(self):
        """BGE-M3 does not use instruction-aware encoding."""
        p = BgeM3LocalProvider()
        mock_model = MagicMock()
        mock_model.encode.return_value = np.zeros((1, 1024), dtype=np.float32)
        p._model = mock_model

        p.encode_queries(["test query"])
        call_args = mock_model.encode.call_args[0][0]
        # Should NOT have instruction prefix
        assert call_args == ["test query"]

    def test_encode_documents_empty(self):
        p = BgeM3LocalProvider()
        result = p.encode_documents([])
        assert result.shape == (0, 1024)


# ---------------------------------------------------------------------------
# _is_model_cached
# ---------------------------------------------------------------------------


class TestIsModelCached:

    @patch("huggingface_hub.scan_cache_dir")
    def test_cached_model_found(self, mock_scan):
        repo = MagicMock()
        repo.repo_id = "BAAI/bge-m3"
        mock_scan.return_value.repos = [repo]

        assert _is_model_cached("BAAI/bge-m3") is True

    @patch("huggingface_hub.scan_cache_dir")
    def test_cached_model_not_found(self, mock_scan):
        mock_scan.return_value.repos = []
        assert _is_model_cached("BAAI/bge-m3") is False

    @patch("huggingface_hub.scan_cache_dir", side_effect=Exception("no hub"))
    def test_fallback_to_path_check_found(self, _mock_scan, tmp_path):
        # Create the expected cache directory structure
        cache_dir = tmp_path / "models--BAAI--bge-m3"
        cache_dir.mkdir(parents=True)

        with patch.dict("os.environ", {"HF_HOME": str(tmp_path)}):
            assert _is_model_cached("BAAI/bge-m3") is True

    @patch("huggingface_hub.scan_cache_dir", side_effect=Exception("no hub"))
    def test_fallback_to_path_check_not_found(self, _mock_scan, tmp_path):
        with patch.dict("os.environ", {"HF_HOME": str(tmp_path)}):
            assert _is_model_cached("BAAI/bge-m3") is False


# ---------------------------------------------------------------------------
# get_embedding_provider (factory)
# ---------------------------------------------------------------------------


class TestGetEmbeddingProvider:

    def test_explicit_siliconflow(self):
        with patch.dict("os.environ", {
            "BOOKSCOPE_EMBEDDING_PROVIDER": "siliconflow",
            "SILICONFLOW_API_KEY": "key",
        }):
            p = get_embedding_provider()
            assert isinstance(p, SiliconFlowProvider)

    @patch("bookscope.store.embedding_provider._is_model_cached", return_value=False)
    def test_explicit_local_qwen3(self, _mock_cache):
        with patch.dict("os.environ", {"BOOKSCOPE_EMBEDDING_PROVIDER": "local-qwen3"}):
            p = get_embedding_provider()
            assert isinstance(p, Qwen3LocalProvider)

    @patch("bookscope.store.embedding_provider._is_model_cached", return_value=False)
    def test_explicit_local_bge_m3(self, _mock_cache):
        with patch.dict("os.environ", {"BOOKSCOPE_EMBEDDING_PROVIDER": "local-bge-m3"}):
            p = get_embedding_provider()
            assert isinstance(p, BgeM3LocalProvider)

    def test_auto_siliconflow_when_key_present(self):
        with patch.dict("os.environ", {
            "BOOKSCOPE_EMBEDDING_PROVIDER": "",
            "SILICONFLOW_API_KEY": "auto-key",
        }):
            p = get_embedding_provider()
            assert isinstance(p, SiliconFlowProvider)

    @patch("bookscope.store.embedding_provider._is_model_cached")
    def test_auto_bge_m3_when_cached(self, mock_cached):
        mock_cached.side_effect = lambda repo_id: repo_id == "BAAI/bge-m3"
        with patch.dict("os.environ", {
            "BOOKSCOPE_EMBEDDING_PROVIDER": "",
            "SILICONFLOW_API_KEY": "",
        }, clear=False):
            # Remove keys that would trigger other paths
            env = {
                "BOOKSCOPE_EMBEDDING_PROVIDER": "",
                "SILICONFLOW_API_KEY": "",
            }
            with patch.dict("os.environ", env):
                p = get_embedding_provider()
                assert isinstance(p, BgeM3LocalProvider)

    @patch("bookscope.store.embedding_provider._is_model_cached")
    def test_auto_qwen3_when_cached(self, mock_cached):
        mock_cached.side_effect = lambda repo_id: repo_id == "Qwen/Qwen3-Embedding-0.6B"
        with patch.dict("os.environ", {
            "BOOKSCOPE_EMBEDDING_PROVIDER": "",
            "SILICONFLOW_API_KEY": "",
        }):
            p = get_embedding_provider()
            assert isinstance(p, Qwen3LocalProvider)

    @patch("bookscope.store.embedding_provider._is_model_cached", return_value=False)
    def test_auto_none_when_nothing_available(self, _mock_cached):
        with patch.dict("os.environ", {
            "BOOKSCOPE_EMBEDDING_PROVIDER": "",
            "SILICONFLOW_API_KEY": "",
        }):
            p = get_embedding_provider()
            assert p is None

    @patch("bookscope.store.embedding_provider._is_model_cached", return_value=False)
    def test_unknown_explicit_falls_to_auto(self, _mock_cached):
        with patch.dict("os.environ", {
            "BOOKSCOPE_EMBEDDING_PROVIDER": "unknown-provider",
            "SILICONFLOW_API_KEY": "",
        }):
            p = get_embedding_provider()
            assert p is None  # auto-detect also finds nothing
