"""``JSONFileConversationStore`` 单测（ADR-009 Phase 1a，D-3）。

覆盖：新建对话、追加轮次、读取历史、落盘结构、evidence_chunk_ids 收集、
registry_chunk_ids 去重并集、续不上的 id 报 ConversationNotFound、损坏文件
报 ConversationCorrupted。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bookscope.api.conversation_store import (
    ConversationCorrupted,
    ConversationNotFound,
    JSONFileConversationStore,
)

_SESSION = "sess-1"


@pytest.fixture()
def store(tmp_path: Path) -> JSONFileConversationStore:
    return JSONFileConversationStore(root=tmp_path)


def _cite(chapter: int, chunk_id: str | None, snippet: str = "原文") -> dict:
    c: dict = {"chapter": chapter, "snippet": snippet}
    if chunk_id is not None:
        c["chunk_id"] = chunk_id
    return c


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


def test_create_returns_id_and_writes_empty_skeleton(
    store: JSONFileConversationStore, tmp_path: Path
) -> None:
    conv_id = store.create(_SESSION)
    assert conv_id
    # 落盘路径符合 ADR D-3：<root>/<session_id>/conversations/<conv_id>.json
    path = tmp_path / _SESSION / "conversations" / f"{conv_id}.json"
    assert path.is_file()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["conversation_id"] == conv_id
    assert data["book_session_id"] == _SESSION
    assert data["turns"] == []
    assert data["registry_chunk_ids"] == []


def test_create_two_conversations_distinct_ids(
    store: JSONFileConversationStore,
) -> None:
    a = store.create(_SESSION)
    b = store.create(_SESSION)
    assert a != b


def test_new_conversation_has_no_last_turn(
    store: JSONFileConversationStore,
) -> None:
    conv_id = store.create(_SESSION)
    assert store.get_last_turn(_SESSION, conv_id) is None
    assert store.get_turns(_SESSION, conv_id) == []


# ---------------------------------------------------------------------------
# append_turn
# ---------------------------------------------------------------------------


def test_append_first_turn_index_is_one(
    store: JSONFileConversationStore,
) -> None:
    conv_id = store.create(_SESSION)
    idx = store.append_turn(
        _SESSION,
        conv_id,
        question="节奏前密后疏吗？",
        answer="是的。",
        citations=[_cite(3, "r0-chunk-3")],
    )
    assert idx == 1


def test_append_increments_turn_index(
    store: JSONFileConversationStore,
) -> None:
    conv_id = store.create(_SESSION)
    i1 = store.append_turn(
        _SESSION, conv_id, question="q1", answer="a1", citations=[]
    )
    i2 = store.append_turn(
        _SESSION, conv_id, question="q2", answer="a2", citations=[]
    )
    i3 = store.append_turn(
        _SESSION, conv_id, question="q3", answer="a3", citations=[]
    )
    assert (i1, i2, i3) == (1, 2, 3)


def test_append_persists_turn_fields(
    store: JSONFileConversationStore,
) -> None:
    conv_id = store.create(_SESSION)
    store.append_turn(
        _SESSION,
        conv_id,
        question="哪几章最稀？",
        answer="第 40-45 章。",
        citations=[_cite(40, "r0-chunk-40")],
    )
    turn = store.get_last_turn(_SESSION, conv_id)
    assert turn is not None
    assert turn["turn_index"] == 1
    assert turn["question"] == "哪几章最稀？"
    assert turn["answer"] == "第 40-45 章。"
    assert turn["citations"] == [_cite(40, "r0-chunk-40")]
    assert turn["evidence_chunk_ids"] == ["r0-chunk-40"]
    # rewritten_question 本步（Phase 1a）固定留空——指代消解是 Phase 1b
    assert turn["rewritten_question"] == ""
    assert turn["created_at"]  # 时间戳非空


def test_evidence_chunk_ids_dedup_and_skip_missing(
    store: JSONFileConversationStore,
) -> None:
    conv_id = store.create(_SESSION)
    store.append_turn(
        _SESSION,
        conv_id,
        question="q",
        answer="a",
        citations=[
            _cite(1, "r0-chunk-1"),
            _cite(2, "r0-chunk-1"),  # 重复 chunk_id → 去重
            _cite(3, None),  # 没 chunk_id（fast_path 自动拼的）→ 跳过
            _cite(4, "r0-chunk-4"),
        ],
    )
    turn = store.get_last_turn(_SESSION, conv_id)
    assert turn is not None
    assert turn["evidence_chunk_ids"] == ["r0-chunk-1", "r0-chunk-4"]


def test_registry_chunk_ids_merges_across_turns(
    store: JSONFileConversationStore,
) -> None:
    conv_id = store.create(_SESSION)
    store.append_turn(
        _SESSION,
        conv_id,
        question="q1",
        answer="a1",
        citations=[_cite(1, "r0-chunk-1"), _cite(2, "r0-chunk-2")],
    )
    store.append_turn(
        _SESSION,
        conv_id,
        question="q2",
        answer="a2",
        citations=[_cite(2, "r0-chunk-2"), _cite(3, "r0-chunk-3")],  # chunk-2 重叠
    )
    turns = store.get_turns(_SESSION, conv_id)
    assert len(turns) == 2
    # registry 是跨轮去重并集（指针台账，Phase 2 预热用）
    conv_id_path = store._conversation_path(_SESSION, conv_id)  # noqa: SLF001
    data = json.loads(conv_id_path.read_text(encoding="utf-8"))
    assert data["registry_chunk_ids"] == ["r0-chunk-1", "r0-chunk-2", "r0-chunk-3"]


def test_get_last_turn_returns_latest(
    store: JSONFileConversationStore,
) -> None:
    conv_id = store.create(_SESSION)
    store.append_turn(_SESSION, conv_id, question="q1", answer="a1", citations=[])
    store.append_turn(_SESSION, conv_id, question="q2", answer="a2", citations=[])
    last = store.get_last_turn(_SESSION, conv_id)
    assert last is not None
    assert last["turn_index"] == 2
    assert last["question"] == "q2"


# ---------------------------------------------------------------------------
# error paths
# ---------------------------------------------------------------------------


def test_append_to_missing_conversation_raises(
    store: JSONFileConversationStore,
) -> None:
    with pytest.raises(ConversationNotFound):
        store.append_turn(
            _SESSION, "no-such-id", question="q", answer="a", citations=[]
        )


def test_get_turns_missing_conversation_raises(
    store: JSONFileConversationStore,
) -> None:
    with pytest.raises(ConversationNotFound):
        store.get_turns(_SESSION, "no-such-id")


def test_corrupted_json_raises(
    store: JSONFileConversationStore, tmp_path: Path
) -> None:
    conv_id = store.create(_SESSION)
    path = tmp_path / _SESSION / "conversations" / f"{conv_id}.json"
    path.write_text("{ this is not valid json", encoding="utf-8")
    with pytest.raises(ConversationCorrupted):
        store.get_turns(_SESSION, conv_id)


def test_exists(store: JSONFileConversationStore) -> None:
    conv_id = store.create(_SESSION)
    assert store.exists(_SESSION, conv_id) is True
    assert store.exists(_SESSION, "no-such-id") is False


def test_path_traversal_rejected(store: JSONFileConversationStore) -> None:
    with pytest.raises(ValueError):
        store.exists(_SESSION, "../escape")
    with pytest.raises(ValueError):
        store.create("../escape")
