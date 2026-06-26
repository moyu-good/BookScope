"""POST /api/books/upload 端到端测试（ADR-004 方案 B）。

所有路径通过 FastAPI ``dependency_overrides`` + monkeypatch 替换
:class:`MinimalKGExtractor` / adapter 构造函数，不调任何真 API。
覆盖：

- happy path：小样本 txt → 上传成功 → 返回 session_id
- 文件格式不支持（.rtf / .json；docx/md 已放开）→ 400
- 文件空内容 → 400
- 缺 api_key → Pydantic 422
- api_key 长度不足 → 422
- ingest 失败（空文本）→ 422
- LLM KG 提取格式错误（LLMFormatError）→ 502
- Provider 认证失败（ProviderUnavailable）→ 502
- Provider 限流（RateLimited）→ 429
- 上传后立即 POST /api/agent/ask 能用这个 session_id
- 持久化验证：上传 → clear 内存 cache → store.get 从 storage 重建
- 路由里的 chunks 与返回值里的 chunk_count 一致
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from bookscope.agent.errors import (
    LLMFormatError,
    ProviderUnavailable,
    RateLimited,
)
from bookscope.api import create_app
from bookscope.api.book_sessions import (
    BookSessionStore,
)
from bookscope.api.dependencies import (
    get_book_session_store as dep_get_book_session_store,
)
from bookscope.api.dependencies import (
    reset_book_session_store_for_tests,
)
from bookscope.api.routes import books as books_route_module
from bookscope.api.session_storage import JSONFileSessionStorage
from bookscope.models.schemas import BookKnowledgeGraph, CharacterProfile

# ---------------------------------------------------------------------------
# Fake MinimalKGExtractor：绕开真 LLM 调用
# ---------------------------------------------------------------------------


class _FakeKGExtractor:
    """最简 fake：extract 直接返回预设 KG 或抛异常。"""

    def __init__(
        self,
        *,
        kg: BookKnowledgeGraph | None = None,
        raise_exc: Exception | None = None,
    ) -> None:
        self._kg = kg
        self._raise = raise_exc
        self.call_count = 0

    def extract(
        self,
        chunks: list,
        book_title: str,
        language: str = "zh",
    ) -> BookKnowledgeGraph:
        self.call_count += 1
        if self._raise is not None:
            raise self._raise
        if self._kg is not None:
            return self._kg
        return BookKnowledgeGraph(
            book_title=book_title,
            language=language,
            characters=[
                CharacterProfile(name="主角甲", key_chapter_indices=[1]),
                CharacterProfile(name="主角乙", key_chapter_indices=[2]),
            ],
        )


def _install_fake_extractor(
    monkeypatch: pytest.MonkeyPatch,
    fake: _FakeKGExtractor,
) -> None:
    """让 books 路由里 ``MinimalKGExtractor(...)`` 返回 fake 实例。"""

    def fake_ctor(*_args: Any, **_kwargs: Any) -> _FakeKGExtractor:
        return fake

    monkeypatch.setattr(books_route_module, "MinimalKGExtractor", fake_ctor)


def _install_fake_client_builder(
    monkeypatch: pytest.MonkeyPatch,
    *,
    raise_exc: Exception | None = None,
) -> None:
    """替换 build_llm_client_from_params 为 fake。

    返回一个极简对象即可——路由只会把它传给 MinimalKGExtractor 构造，
    而我们已经把 extractor 本身 fake 掉了，client 不会被真正调用。
    """

    def fake_builder(
        *, provider: str, api_key: str, base_url: str | None = None,
    ) -> object:
        if raise_exc is not None:
            raise raise_exc
        return object()

    monkeypatch.setattr(books_route_module, "build_llm_client_from_params", fake_builder)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_store_between_tests() -> None:
    """每个测试前把共享 BookSessionStore 重置干净（内存 + 解绑 storage）。"""
    reset_book_session_store_for_tests()
    yield
    reset_book_session_store_for_tests()


@pytest.fixture()
def client_without_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    """提供一个纯内存 BookSessionStore 的 TestClient（不写磁盘）。"""
    app = create_app()
    # 用 dependency override 注入无 storage 的 store
    memory_store = BookSessionStore()
    app.dependency_overrides[dep_get_book_session_store] = lambda: memory_store

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def client_with_tmp_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, BookSessionStore]:
    """提供一个带 tmp_path JSONFileSessionStorage 的 TestClient。"""
    app = create_app()
    storage = JSONFileSessionStorage(root=tmp_path / "sessions")
    store = BookSessionStore(storage=storage)
    app.dependency_overrides[dep_get_book_session_store] = lambda: store

    with TestClient(app) as c:
        yield c, store


def _small_txt_bytes() -> bytes:
    """一段足够让 r0 ingest 顺利切出 chunk 的文本（多章节）。"""
    parts = []
    parts.append("第一章 开端")
    parts.append("这是一本关于测试的书。" * 30)
    parts.append("")
    parts.append("第二章 发展")
    parts.append("主角甲开始行动。" * 30)
    parts.append("")
    parts.append("第三章 结局")
    parts.append("最终迎来圆满结局。" * 30)
    return "\n".join(parts).encode("utf-8")


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_upload_happy_path(
    client_without_storage: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_extractor(monkeypatch, _FakeKGExtractor())
    _install_fake_client_builder(monkeypatch)

    files = {"file": ("test.txt", io.BytesIO(_small_txt_bytes()), "text/plain")}
    data = {
        "book_title": "测试书",
        "language": "zh",
        "provider": "deepseek",
        "api_key": "sk-test-0123456789",
    }
    resp = client_without_storage.post("/api/books/upload", files=files, data=data)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["book_title"] == "测试书"
    assert body["language"] == "zh"
    assert body["chunk_count"] >= 1
    assert body["character_count"] == 2
    assert len(body["session_id"]) == 16
    assert body["message"] == "upload succeeded"


def test_upload_registers_session_in_store(
    client_without_storage: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """上传成功后 store 里应能拿到这个 session。"""
    _install_fake_extractor(monkeypatch, _FakeKGExtractor())
    _install_fake_client_builder(monkeypatch)

    files = {"file": ("b.txt", io.BytesIO(_small_txt_bytes()), "text/plain")}
    data = {
        "book_title": "X",
        "provider": "deepseek",
        "api_key": "sk-test-0123456789",
    }
    resp = client_without_storage.post("/api/books/upload", files=files, data=data)
    sid = resp.json()["session_id"]
    # TestClient 与 dep 共享 store 实例
    store = client_without_storage.app.dependency_overrides[
        dep_get_book_session_store
    ]()
    assert store.has(sid)


# ---------------------------------------------------------------------------
# 文件格式 / 空文件
# ---------------------------------------------------------------------------


def test_upload_unsupported_extension_returns_400(
    client_without_storage: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_extractor(monkeypatch, _FakeKGExtractor())
    _install_fake_client_builder(monkeypatch)

    # .rtf 仍不支持(docx/md 已放开,见 _SUPPORTED_EXTENSIONS);拿它测 400。
    files = {"file": ("book.rtf", io.BytesIO(b"whatever"), "application/rtf")}
    data = {
        "book_title": "X",
        "provider": "deepseek",
        "api_key": "sk-test-0123456789",
    }
    resp = client_without_storage.post("/api/books/upload", files=files, data=data)
    assert resp.status_code == 400
    assert resp.json()["detail"]["error_type"] == "UnsupportedFileType"


def test_upload_empty_file_returns_400(
    client_without_storage: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_extractor(monkeypatch, _FakeKGExtractor())
    _install_fake_client_builder(monkeypatch)

    files = {"file": ("empty.txt", io.BytesIO(b""), "text/plain")}
    data = {
        "book_title": "X",
        "provider": "deepseek",
        "api_key": "sk-test-0123456789",
    }
    resp = client_without_storage.post("/api/books/upload", files=files, data=data)
    assert resp.status_code == 400
    assert resp.json()["detail"]["error_type"] == "EmptyFile"


# ---------------------------------------------------------------------------
# 参数校验
# ---------------------------------------------------------------------------


def test_upload_missing_api_key_returns_422(
    client_without_storage: TestClient,
) -> None:
    files = {"file": ("x.txt", io.BytesIO(_small_txt_bytes()), "text/plain")}
    data = {
        "book_title": "X",
        "provider": "deepseek",
        # api_key 缺失
    }
    resp = client_without_storage.post("/api/books/upload", files=files, data=data)
    assert resp.status_code == 422


def test_upload_api_key_too_short_returns_422(
    client_without_storage: TestClient,
) -> None:
    files = {"file": ("x.txt", io.BytesIO(_small_txt_bytes()), "text/plain")}
    data = {
        "book_title": "X",
        "provider": "deepseek",
        "api_key": "short",  # < 8
    }
    resp = client_without_storage.post("/api/books/upload", files=files, data=data)
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# ingest 失败
# ---------------------------------------------------------------------------


def test_upload_whitespace_only_file_returns_422(
    client_without_storage: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """只含空白字符的文件在 loader 阶段抛 EmptyTextError → 422。"""
    _install_fake_extractor(monkeypatch, _FakeKGExtractor())
    _install_fake_client_builder(monkeypatch)

    files = {"file": ("blank.txt", io.BytesIO(b"   \n\n\t\n"), "text/plain")}
    data = {
        "book_title": "X",
        "provider": "deepseek",
        "api_key": "sk-test-0123456789",
    }
    resp = client_without_storage.post("/api/books/upload", files=files, data=data)
    assert resp.status_code == 422
    assert resp.json()["detail"]["error_type"] == "EmptyBookText"


# ---------------------------------------------------------------------------
# LLM / Provider 错误
# ---------------------------------------------------------------------------


def test_upload_llm_format_error_502(
    client_without_storage: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_extractor(
        monkeypatch,
        _FakeKGExtractor(raise_exc=LLMFormatError("bad json")),
    )
    _install_fake_client_builder(monkeypatch)

    files = {"file": ("x.txt", io.BytesIO(_small_txt_bytes()), "text/plain")}
    data = {
        "book_title": "X",
        "provider": "deepseek",
        "api_key": "sk-test-0123456789",
    }
    resp = client_without_storage.post("/api/books/upload", files=files, data=data)
    assert resp.status_code == 502
    assert resp.json()["detail"]["error_type"] == "LLMFormatError"


def test_upload_provider_unavailable_502(
    client_without_storage: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_extractor(
        monkeypatch,
        _FakeKGExtractor(raise_exc=ProviderUnavailable("auth failed")),
    )
    _install_fake_client_builder(monkeypatch)

    files = {"file": ("x.txt", io.BytesIO(_small_txt_bytes()), "text/plain")}
    data = {
        "book_title": "X",
        "provider": "deepseek",
        "api_key": "sk-test-0123456789",
    }
    resp = client_without_storage.post("/api/books/upload", files=files, data=data)
    assert resp.status_code == 502
    assert resp.json()["detail"]["error_type"] == "ProviderUnavailable"


def test_upload_rate_limited_429(
    client_without_storage: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_extractor(
        monkeypatch,
        _FakeKGExtractor(raise_exc=RateLimited("too fast")),
    )
    _install_fake_client_builder(monkeypatch)

    files = {"file": ("x.txt", io.BytesIO(_small_txt_bytes()), "text/plain")}
    data = {
        "book_title": "X",
        "provider": "deepseek",
        "api_key": "sk-test-0123456789",
    }
    resp = client_without_storage.post("/api/books/upload", files=files, data=data)
    assert resp.status_code == 429
    assert resp.json()["detail"]["error_type"] == "RateLimited"


# ---------------------------------------------------------------------------
# 端到端 + 持久化
# ---------------------------------------------------------------------------


def test_upload_session_can_be_loaded_from_storage_after_cache_clear(
    client_with_tmp_storage: tuple[TestClient, BookSessionStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """上传 → 清空内存 cache → store.get 仍能从 JSONFileSessionStorage 重建。"""
    client, store = client_with_tmp_storage
    _install_fake_extractor(monkeypatch, _FakeKGExtractor())
    _install_fake_client_builder(monkeypatch)

    files = {"file": ("b.txt", io.BytesIO(_small_txt_bytes()), "text/plain")}
    data = {
        "book_title": "持久化测试",
        "provider": "deepseek",
        "api_key": "sk-test-0123456789",
    }
    resp = client.post("/api/books/upload", files=files, data=data)
    sid = resp.json()["session_id"]

    # 清空内存 cache，模拟进程重启
    store.clear()

    # 此时 store 里内存空，但 storage 里有这个 session
    reloaded = store.get(sid)
    assert reloaded._book_text.title == "持久化测试"  # noqa: SLF001


def test_upload_chunk_count_matches_returned(
    client_without_storage: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """返回里的 chunk_count 与 assembler 内部 chunks 长度一致。"""
    _install_fake_extractor(monkeypatch, _FakeKGExtractor())
    _install_fake_client_builder(monkeypatch)

    files = {"file": ("x.txt", io.BytesIO(_small_txt_bytes()), "text/plain")}
    data = {
        "book_title": "X",
        "provider": "deepseek",
        "api_key": "sk-test-0123456789",
    }
    resp = client_without_storage.post("/api/books/upload", files=files, data=data)
    sid = resp.json()["session_id"]
    reported = resp.json()["chunk_count"]

    store = client_without_storage.app.dependency_overrides[
        dep_get_book_session_store
    ]()
    assembler = store.get(sid)
    actual = len(assembler._chunks)  # noqa: SLF001
    assert reported == actual
