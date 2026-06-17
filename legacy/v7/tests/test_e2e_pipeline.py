"""End-to-end pipeline test using the real 明朝那些事儿 epub.

Runs:  upload → extract (mock LLM) → chat with RAG (mock LLM)
Validates the entire FastAPI pipeline including vector store creation.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

EPUB_PATH = Path(__file__).resolve().parent.parent / "test明朝那些事儿.epub"

pytestmark = pytest.mark.skipif(
    not EPUB_PATH.exists(),
    reason=f"Test epub not found: {EPUB_PATH}",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(tmp_path, monkeypatch):
    from bookscope.api import session_store
    from bookscope.api.app import app

    session_store._sessions.clear()
    monkeypatch.setattr(session_store, "_SESSIONS_DIR", tmp_path / "sessions")
    return TestClient(app)


# Fake LLM responses for extraction
_FAKE_CHUNK_SUMMARY = json.dumps({
    "title": "朱元璋的崛起",
    "summary": "讲述了朱元璋从一个贫苦农民到推翻元朝建立明朝的传奇故事。",
    "key_events": ["参加红巾军", "攻克集庆"],
    "characters_mentioned": ["朱元璋", "陈友谅", "徐达"],
})

_FAKE_MERGE_CHARACTERS = json.dumps([
    {
        "name": "朱元璋",
        "aliases": ["朱重八", "洪武帝"],
        "description": "明朝开国皇帝，出身贫寒，最终统一天下。",
        "voice_style": "果断、威严、多疑",
        "motivations": ["推翻元朝", "建立新王朝"],
        "key_chapter_indices": [0, 1, 2],
        "arc_summary": "从乞丐到皇帝的逆袭之路。",
    },
    {
        "name": "徐达",
        "aliases": ["徐天德"],
        "description": "明朝开国功臣，朱元璋最信赖的将领。",
        "voice_style": "沉稳、谦逊",
        "motivations": ["追随朱元璋", "北伐中原"],
        "key_chapter_indices": [1, 2],
        "arc_summary": "忠诚的将领，战功赫赫。",
    },
])

_FAKE_CHAT_RESPONSE = (
    "朱元璋（1328-1398），原名朱重八，是明朝的开国皇帝。"
    "他出身于安徽凤阳一个贫苦农民家庭。"
)


def _fake_call_llm(prompt: str, *, api_key: str, model: str = "", max_tokens: int = 4096):
    """Route fake responses based on prompt content."""
    if "characters_mentioned" in prompt:
        return _FAKE_CHUNK_SUMMARY
    if "CharacterProfile" in prompt or "合并" in prompt or "merge" in prompt.lower():
        return _FAKE_MERGE_CHARACTERS
    # Chat
    return _FAKE_CHAT_RESPONSE


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestE2EPipeline:
    """Upload real epub → extract with mock LLM → chat with RAG."""

    def test_upload_epub(self, client):
        """Upload the real epub and verify chunks + vector store."""
        with open(EPUB_PATH, "rb") as f:
            resp = client.post("/api/upload", files={"file": ("明朝那些事儿.epub", f)})

        assert resp.status_code == 200
        data = resp.json()
        assert "session_id" in data
        assert data["total_chunks"] > 0
        assert data["title"]  # non-empty title

        # Verify session has vector store
        from bookscope.api.session_store import _sessions

        session = _sessions[data["session_id"]]
        vs = session.vector_store
        assert vs is not None, "Vector store should be created at upload"
        assert vs.chunk_count == data["total_chunks"]

        # upload OK: chunks + vector store created

    @patch("bookscope.nlp.knowledge_extractor.call_llm", side_effect=_fake_call_llm)
    def test_upload_then_extract(self, mock_llm, client):
        """Upload → extract knowledge graph with mock LLM."""
        # Upload
        with open(EPUB_PATH, "rb") as f:
            upload = client.post("/api/upload", files={"file": ("明朝那些事儿.epub", f)})
        sid = upload.json()["session_id"]
        total = upload.json()["total_chunks"]

        # Extract (mock LLM, with fake API key)
        with patch("bookscope.api.main._get_api_key", return_value="fake-key"):
            resp = client.post(
                "/api/extract",
                json={"session_id": sid, "model": "claude-haiku-4-5"},
            )

        assert resp.status_code == 200

        # Parse SSE events
        events = []
        for line in resp.text.strip().split("\n"):
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

        # Should have progress events + final done event
        progress = [e for e in events if e["type"] == "progress"]
        done = [e for e in events if e["type"] == "done"]

        assert len(progress) > 0, "Should emit progress events"
        assert len(done) == 1, "Should emit exactly one done event"

        graph = done[0]["graph"]
        assert graph["book_title"]
        assert len(graph["chapter_summaries"]) == total
        assert len(graph["characters"]) >= 1
        assert graph["characters"][0]["name"] == "朱元璋"

        # extract OK: chapters + characters extracted with sampled LLM calls

    @patch("bookscope.nlp.knowledge_extractor.call_llm", side_effect=_fake_call_llm)
    @patch("bookscope.nlp.llm_analyzer.call_llm", side_effect=_fake_call_llm)
    @patch("bookscope.api.main.call_llm", side_effect=_fake_call_llm)
    def test_full_flow_upload_extract_chat(self, mock_api_llm, mock_llm_mod, mock_ext_llm, client):
        """Full pipeline: upload → extract → chat with RAG retrieval."""
        # Step 1: Upload
        with open(EPUB_PATH, "rb") as f:
            upload = client.post("/api/upload", files={"file": ("明朝那些事儿.epub", f)})
        sid = upload.json()["session_id"]

        # Step 2: Extract
        with patch("bookscope.api.main._get_api_key", return_value="fake-key"):
            extract_resp = client.post(
                "/api/extract",
                json={"session_id": sid},
            )
        assert extract_resp.status_code == 200

        # Step 3: Chat — this should use RAG vector retrieval
        with patch("bookscope.api.main._get_api_key", return_value="fake-key"):
            chat_resp = client.post(
                "/api/chat/stream",
                json={"session_id": sid, "message": "朱元璋是谁？"},
            )
        assert chat_resp.status_code == 200

        # Parse chat SSE
        chat_events = []
        for line in chat_resp.text.strip().split("\n"):
            if line.startswith("data: "):
                chat_events.append(json.loads(line[6:]))

        msg_events = [e for e in chat_events if e["type"] == "message"]
        assert len(msg_events) >= 1
        assert "朱元璋" in msg_events[0]["content"]

        # Verify the prompt sent to LLM includes "相关段落" (RAG context)
        last_call_args = mock_api_llm.call_args
        prompt_sent = (
            last_call_args[0][0]
            if last_call_args[0]
            else last_call_args[1].get("prompt", "")
        )
        assert "相关段落" in prompt_sent, "Chat prompt should include RAG-retrieved chunks"

        # Assertions passed — full flow works

    def test_chat_without_extract_still_works_with_rag(self, client):
        """Chat immediately after upload (no extraction) — RAG still works."""
        with open(EPUB_PATH, "rb") as f:
            upload = client.post("/api/upload", files={"file": ("明朝那些事儿.epub", f)})
        sid = upload.json()["session_id"]

        with (
            patch("bookscope.api.main._get_api_key", return_value="fake-key"),
            patch("bookscope.api.main.call_llm", return_value=_FAKE_CHAT_RESPONSE),
        ):
            chat_resp = client.post(
                "/api/chat/stream",
                json={"session_id": sid, "message": "这本书讲什么？"},
            )
        assert chat_resp.status_code == 200

        events = []
        for line in chat_resp.text.strip().split("\n"):
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

        msg = [e for e in events if e["type"] == "message"]
        assert len(msg) >= 1
        # chat without extract OK: RAG-only works

    def test_vector_store_search_quality(self, client):
        """Upload, then verify vector search returns relevant chunks for a specific query."""
        with open(EPUB_PATH, "rb") as f:
            upload = client.post("/api/upload", files={"file": ("明朝那些事儿.epub", f)})
        sid = upload.json()["session_id"]

        from bookscope.api.session_store import _sessions

        vs = _sessions[sid]["vector_store"]
        results = vs.search("朱元璋当皇帝", top_k=3)

        assert len(results) > 0
        # At least one result should mention 朱元璋 or related terms
        texts = " ".join(chunk.text for chunk, _ in results)
        # The book is about 明朝, so results should be somewhat relevant
        has_relevant = any(
            kw in texts for kw in ["朱", "元璋", "明", "皇帝", "洪武", "天下"]
        )
        assert has_relevant, (
            f"Results should be relevant. Got: {texts[:200]}"
        )

        # Assertions passed — search returns relevant chunks
