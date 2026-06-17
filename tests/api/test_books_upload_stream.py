"""POST /api/books/upload/stream 端到端测试（Sprint 6 第六步）。

覆盖：

- happy path：txt → 流帧含 ``ingest_started`` / ``kg_batch_started`` /
  ``kg_batch_completed`` / ``ingest_done`` / ``upload_complete``
- book-level cache 命中场景：仅 ``ingest_started`` / ``kg_cache_hit`` /
  ``ingest_done`` / ``upload_complete``
- 不支持格式 → setup 阶段 HTTP 400（不发 SSE 头）
- 空文件 → HTTP 400
- KG 抽取抛 LLMFormatError → 流内 ``ingest_error`` + ``upload_error``，
  HTTP 仍 200

所有用例通过替换 ``MinimalKGExtractor`` 与 client builder 避免真 LLM 调用。
"""

from __future__ import annotations

import io
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from bookscope.agent.errors import LLMFormatError
from bookscope.agent.events import IngestEvent
from bookscope.api import create_app
from bookscope.api.book_sessions import BookSessionStore
from bookscope.api.dependencies import (
    get_book_session_store as dep_get_book_session_store,
)
from bookscope.api.dependencies import (
    reset_book_session_store_for_tests,
)
from bookscope.api.routes import books as books_route_module
from bookscope.models.schemas import BookKnowledgeGraph, CharacterProfile

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeStreamingExtractor:
    """模拟 MinimalKGExtractor 的对外契约：constructor 收 ``on_ingest_event``
    + ``book_session_id``；``extract`` 调用 callback 模拟事件序列。
    """

    def __init__(
        self,
        *,
        client: Any,
        model: str,
        on_ingest_event: Any = None,
        book_session_id: str = "",
        **_kw: Any,
    ) -> None:
        self._on_event = on_ingest_event
        self._session_id = book_session_id
        # 通过模块级 hook 拿到测试侧的 behavior 配置
        self._behavior = _FAKE_BEHAVIOR.copy()

    def extract(
        self,
        chunks: list,
        book_title: str,
        language: str = "zh",
    ) -> BookKnowledgeGraph:
        # emit ingest_started
        self._emit("ingest_started", total_batches=self._behavior["total_batches"])
        if self._behavior["raise_exc"] is not None:
            self._emit(
                "ingest_error",
                error_message=str(self._behavior["raise_exc"]),
            )
            raise self._behavior["raise_exc"]
        if self._behavior["book_cache_hit"]:
            self._emit("kg_cache_hit", cached=True)
        else:
            for i in range(self._behavior["total_batches"]):
                self._emit("kg_batch_started", batch_index=i)
                if i in self._behavior["batch_cache_hit_indices"]:
                    self._emit("kg_cache_hit", batch_index=i, cached=True)
                self._emit("kg_batch_completed", batch_index=i)
        self._emit("ingest_done")
        return BookKnowledgeGraph(
            book_title=book_title,
            language=language,
            characters=[
                CharacterProfile(name="主角甲", key_chapter_indices=[1]),
                CharacterProfile(name="主角乙", key_chapter_indices=[2]),
            ],
        )

    def _emit(self, event_type: str, **kw: Any) -> None:
        if self._on_event is None:
            return
        self._on_event(
            IngestEvent(
                event_type=event_type,  # type: ignore[arg-type]
                book_session_id=self._session_id,
                total_batches=kw.get("total_batches"),
                batch_index=kw.get("batch_index"),
                cached=kw.get("cached", False),
                error_message=kw.get("error_message"),
            )
        )


# Behavior dict (set by each test, read by fake constructor)
_FAKE_BEHAVIOR: dict[str, Any] = {
    "total_batches": 3,
    "batch_cache_hit_indices": set(),
    "book_cache_hit": False,
    "raise_exc": None,
}


def _set_fake_behavior(**kw: Any) -> None:
    _FAKE_BEHAVIOR["total_batches"] = kw.get("total_batches", 3)
    _FAKE_BEHAVIOR["batch_cache_hit_indices"] = kw.get(
        "batch_cache_hit_indices", set()
    )
    _FAKE_BEHAVIOR["book_cache_hit"] = kw.get("book_cache_hit", False)
    _FAKE_BEHAVIOR["raise_exc"] = kw.get("raise_exc", None)


def _install_fake_streaming_extractor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        books_route_module, "MinimalKGExtractor", _FakeStreamingExtractor
    )


def _install_fake_client_builder(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_builder(
        *, provider: str, api_key: str, base_url: str | None = None,
    ) -> object:
        return object()

    monkeypatch.setattr(
        books_route_module, "build_llm_client_from_params", fake_builder
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_store_between_tests() -> None:
    reset_book_session_store_for_tests()
    yield
    reset_book_session_store_for_tests()
    # 清 behavior 状态
    _set_fake_behavior()


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app = create_app()
    memory_store = BookSessionStore()
    app.dependency_overrides[dep_get_book_session_store] = lambda: memory_store
    with TestClient(app) as c:
        yield c


def _small_txt_bytes() -> bytes:
    parts = [
        "第一章 开端",
        "这是一本关于测试的书。" * 30,
        "",
        "第二章 发展",
        "主角甲开始行动。" * 30,
        "",
        "第三章 结局",
        "最终迎来圆满结局。" * 30,
    ]
    return "\n".join(parts).encode("utf-8")


def _parse_sse_frames(raw: str) -> list[tuple[str, dict[str, Any]]]:
    """跟 r2 SSE 测试用同算法——分 ``\\n\\n`` 拆帧，每帧拆 event/data。"""
    frames: list[tuple[str, dict[str, Any]]] = []
    for chunk in raw.split("\n\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        event_type = ""
        data_lines: list[str] = []
        for line in chunk.split("\n"):
            if line.startswith("event:"):
                event_type = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:") :].strip())
        if event_type and data_lines:
            data = json.loads("\n".join(data_lines))
            frames.append((event_type, data))
    return frames


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_upload_stream_happy_path(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """3-batch ingest → 完整事件序列 + upload_complete 含 session_id。"""
    _install_fake_streaming_extractor(monkeypatch)
    _install_fake_client_builder(monkeypatch)
    _set_fake_behavior(total_batches=3)

    files = {"file": ("t.txt", io.BytesIO(_small_txt_bytes()), "text/plain")}
    data = {
        "book_title": "测试书",
        "language": "zh",
        "provider": "deepseek",
        "api_key": "sk-test-0123456789",
    }
    with client.stream(
        "POST", "/api/books/upload/stream", files=files, data=data,
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        raw = "".join(resp.iter_text())

    frames = _parse_sse_frames(raw)
    types = [t for t, _ in frames]
    # 第一帧必为 ingest_started，末帧必为 upload_complete
    assert types[0] == "ingest_started"
    assert types[-1] == "upload_complete"
    # 包含每个 batch 的 started + completed
    assert types.count("kg_batch_started") == 3
    assert types.count("kg_batch_completed") == 3
    assert "ingest_done" in types
    # ingest_started 带 total_batches
    first = frames[0][1]
    assert first["total_batches"] == 3
    # upload_complete 含 session_id / chunk_count / character_count
    last = frames[-1][1]
    assert len(last["session_id"]) == 16
    assert last["book_title"] == "测试书"
    assert last["chunk_count"] >= 1
    assert last["character_count"] == 2


def test_upload_stream_emits_kg_cache_hit_for_batch(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """batch 1 命中 batch 级缓存——序列里有 kg_cache_hit 帧 + batch_index=1。"""
    _install_fake_streaming_extractor(monkeypatch)
    _install_fake_client_builder(monkeypatch)
    _set_fake_behavior(total_batches=3, batch_cache_hit_indices={1})

    files = {"file": ("t.txt", io.BytesIO(_small_txt_bytes()), "text/plain")}
    data = {
        "book_title": "X",
        "provider": "deepseek",
        "api_key": "sk-test-0123456789",
    }
    with client.stream(
        "POST", "/api/books/upload/stream", files=files, data=data,
    ) as resp:
        raw = "".join(resp.iter_text())

    frames = _parse_sse_frames(raw)
    cache_frames = [f for t, f in frames if t == "kg_cache_hit"]
    assert len(cache_frames) == 1
    assert cache_frames[0]["batch_index"] == 1
    assert cache_frames[0]["cached"] is True


def test_upload_stream_book_level_cache_hit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """book-level 缓存命中——压缩成 ingest_started → kg_cache_hit → ingest_done。"""
    _install_fake_streaming_extractor(monkeypatch)
    _install_fake_client_builder(monkeypatch)
    _set_fake_behavior(book_cache_hit=True, total_batches=0)

    files = {"file": ("t.txt", io.BytesIO(_small_txt_bytes()), "text/plain")}
    data = {
        "book_title": "X",
        "provider": "deepseek",
        "api_key": "sk-test-0123456789",
    }
    with client.stream(
        "POST", "/api/books/upload/stream", files=files, data=data,
    ) as resp:
        raw = "".join(resp.iter_text())

    frames = _parse_sse_frames(raw)
    types = [t for t, _ in frames]
    assert types == [
        "ingest_started",
        "kg_cache_hit",
        "ingest_done",
        "upload_complete",
    ]
    # book-level cache hit 帧的 batch_index 为 None
    cache_frame = frames[1][1]
    assert cache_frame["batch_index"] is None
    assert cache_frame["cached"] is True


# ---------------------------------------------------------------------------
# Setup-time 错误
# ---------------------------------------------------------------------------


def test_upload_stream_unsupported_extension_returns_400(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_streaming_extractor(monkeypatch)
    _install_fake_client_builder(monkeypatch)

    files = {
        "file": ("b.docx", io.BytesIO(b"x"), "application/msword"),
    }
    data = {
        "book_title": "X",
        "provider": "deepseek",
        "api_key": "sk-test-0123456789",
    }
    resp = client.post("/api/books/upload/stream", files=files, data=data)
    assert resp.status_code == 400
    assert resp.json()["detail"]["error_type"] == "UnsupportedFileType"


def test_upload_stream_empty_file_returns_400(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_streaming_extractor(monkeypatch)
    _install_fake_client_builder(monkeypatch)

    files = {"file": ("e.txt", io.BytesIO(b""), "text/plain")}
    data = {
        "book_title": "X",
        "provider": "deepseek",
        "api_key": "sk-test-0123456789",
    }
    resp = client.post("/api/books/upload/stream", files=files, data=data)
    assert resp.status_code == 400
    assert resp.json()["detail"]["error_type"] == "EmptyFile"


# ---------------------------------------------------------------------------
# Stream-internal 错误
# ---------------------------------------------------------------------------


def test_upload_stream_llm_format_error_emits_upload_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """KG 抽取抛 LLMFormatError → 流内 ingest_error + upload_error；HTTP 仍 200。"""
    _install_fake_streaming_extractor(monkeypatch)
    _install_fake_client_builder(monkeypatch)
    _set_fake_behavior(raise_exc=LLMFormatError("LLM 返了一堆乱码"))

    files = {"file": ("t.txt", io.BytesIO(_small_txt_bytes()), "text/plain")}
    data = {
        "book_title": "X",
        "provider": "deepseek",
        "api_key": "sk-test-0123456789",
    }
    with client.stream(
        "POST", "/api/books/upload/stream", files=files, data=data,
    ) as resp:
        assert resp.status_code == 200  # SSE 流内错误不改 HTTP 状态
        raw = "".join(resp.iter_text())

    frames = _parse_sse_frames(raw)
    types = [t for t, _ in frames]
    assert "ingest_started" in types
    assert "ingest_error" in types
    # 末帧是 upload_error，error_type=LLMFormatError
    assert types[-1] == "upload_error"
    err = frames[-1][1]
    assert err["error_type"] == "LLMFormatError"
    assert "LLM 返了一堆乱码" in err["message"]
