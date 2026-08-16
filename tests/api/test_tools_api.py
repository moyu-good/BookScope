"""本地零配置工具 API 测试（不需要 LLM key）。"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bookscope.api import create_app
from bookscope.api.dependencies import reset_book_session_store_for_tests


@pytest.fixture(autouse=True)
def _reset_store() -> Iterator[None]:
    reset_book_session_store_for_tests()
    yield
    reset_book_session_store_for_tests()


@pytest.fixture()
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as c:
        yield c


def test_tools_report_returns_structure_html(client: TestClient, tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    f.write_text("第一章\\n甲。\\n", encoding="utf-8")
    resp = client.post("/api/tools/report", json={"path": str(f), "title": "测试书"})
    assert resp.status_code == 200, resp.text
    assert "text/html" in resp.headers["content-type"]
    assert resp.headers.get("X-Report-Coverage") == "structure"
    assert "测试书" in resp.text


def test_tools_import_creates_session(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "sessions"
    monkeypatch.setenv("BOOKSCOPE_DATA_DIR", str(data_dir))
    f = tmp_path / "a.txt"
    f.write_text("第一章\\n甲。\\n", encoding="utf-8")
    resp = client.post("/api/tools/import", json={"path": str(f), "title": "测试书"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["session_id"].startswith("api-")
    assert body["book_title"] == "测试书"
    assert any(data_dir.iterdir())


def test_tools_upload_zero_config(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "sessions"
    monkeypatch.setenv("BOOKSCOPE_DATA_DIR", str(data_dir))
    resp = client.post(
        "/api/tools/upload",
        data={"book_title": "测试书", "language": "zh"},
        files={"file": ("a.txt", "第一章\n甲。\n".encode(), "text/plain")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["session_id"].startswith("api-")
    assert body["book_title"] == "测试书"
    assert body["chunk_count"] >= 1
    assert any(data_dir.iterdir())


def test_tools_ask_local_returns_results(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "sessions"
    monkeypatch.setenv("BOOKSCOPE_DATA_DIR", str(data_dir))
    f = tmp_path / "a.txt"
    f.write_text("第一章 开端\n这是关于经济改革的讨论。\n第二章 发展\n这里提到市场与政府的关系。\n", encoding="utf-8")
    imp = client.post("/api/tools/import", json={"path": str(f), "title": "测试书"})
    sid = imp.json()["session_id"]
    resp = client.post("/api/tools/ask-local", json={"session_id": sid, "question": "市场与政府"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mode"] == "local"
    assert len(body["results"]) >= 1


def test_tools_catalog_generates_index(client: TestClient, tmp_path: Path) -> None:
    folder = tmp_path / "books"
    folder.mkdir()
    (folder / "a.txt").write_text("第一章\n甲。\n", encoding="utf-8")
    out = tmp_path / "out"
    resp = client.post("/api/tools/catalog", json={"path": str(folder), "out": str(out)})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 1
    assert (out / "index.html").exists()
    assert (out / "a.html").exists()


def test_tools_search_returns_results(client: TestClient, tmp_path: Path) -> None:
    folder = tmp_path / "books"
    folder.mkdir()
    (folder / "a.txt").write_text("第一章 开端\n这里提到市场与政府的关系。\n", encoding="utf-8")
    resp = client.post("/api/tools/search", json={"path": str(folder), "query": "市场"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] >= 1
    assert body["results"][0]["book"] == "a"
