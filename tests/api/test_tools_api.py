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
