"""bookscope.agent.tools.search_chunks 的单测。

覆盖点：
- SearchChunksInput 的字段校验
- 未接后端时 search_chunks 抛 NotImplementedError
- 给定一个测试替身 backend 时 search_chunks 正确 delegate
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from bookscope.agent.tools.schemas import ChunkMatch
from bookscope.agent.tools.search_chunks import (
    ChunkRetrievalBackend,
    SearchChunksInput,
    search_chunks,
)

# ---------------------------------------------------------------------------
# SearchChunksInput
# ---------------------------------------------------------------------------


class TestSearchChunksInput:
    def test_accepts_minimal_params(self):
        inp = SearchChunksInput(query="朱元璋 和 李善长")
        assert inp.query == "朱元璋 和 李善长"
        assert inp.chapter_scope is None
        assert inp.character_filter is None
        assert inp.top_k == 10

    def test_accepts_full_params(self):
        inp = SearchChunksInput(
            query="权力斗争",
            chapter_scope=(1, 5),
            character_filter=["朱元璋"],
            top_k=5,
        )
        assert inp.chapter_scope == (1, 5)
        assert inp.character_filter == ["朱元璋"]
        assert inp.top_k == 5

    def test_rejects_empty_query(self):
        with pytest.raises(ValidationError):
            SearchChunksInput(query="")

    def test_rejects_zero_top_k(self):
        with pytest.raises(ValidationError):
            SearchChunksInput(query="x", top_k=0)

    def test_rejects_negative_top_k(self):
        with pytest.raises(ValidationError):
            SearchChunksInput(query="x", top_k=-1)

    def test_rejects_too_large_top_k(self):
        with pytest.raises(ValidationError):
            SearchChunksInput(query="x", top_k=51)


# ---------------------------------------------------------------------------
# search_chunks dispatcher
# ---------------------------------------------------------------------------


def test_search_chunks_delegates_to_backend():
    """search_chunks 把校验后的参数原样委托给 backend.retrieve。

    2026-06-10 起 dispatcher 从骨架占位（抛 NotImplementedError）改为
    直接 delegate——生产路径实际走 search_chunks_cached，本函数保留作
    Protocol 契约的可执行说明。
    """
    mock_backend = MagicMock(spec=ChunkRetrievalBackend)
    expected = [
        ChunkMatch(
            chunk_id="ch01-p01",
            chapter=1,
            text="开国之初，百废待兴。",
            relevance_score=0.9,
            contains_characters=["朱元璋"],
            source_version="r0",
        )
    ]
    mock_backend.retrieve.return_value = expected

    inp = SearchChunksInput(
        query="开国",
        chapter_scope=(1, 1),
        character_filter=["朱元璋"],
        top_k=10,
    )
    result = search_chunks(inp, mock_backend)

    assert result == expected
    mock_backend.retrieve.assert_called_once_with(
        query="开国",
        chapter_scope=(1, 1),
        character_filter=["朱元璋"],
        top_k=10,
    )
