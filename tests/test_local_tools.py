"""bookscope.local_tools 共享本地能力测试（零配置）。"""

from __future__ import annotations

from pathlib import Path

from bookscope.local_tools import import_file, load_chunks, structure_report_html


def test_load_chunks_returns_dicts(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    f.write_text("第一章 开端\n甲。\n第二章 发展\n乙。\n", encoding="utf-8")
    name, book, results, chunks = load_chunks(f, title="测试书")
    assert name == "测试书"
    assert book.title == "测试书"
    assert len(results) >= 1
    assert all("chunk_id" in c and "chapter" in c and "text" in c for c in chunks)


def test_structure_report_html_zero_llm(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    f.write_text("第一章 开端\n甲。\n", encoding="utf-8")
    html = structure_report_html(f, title="测试书")
    assert "<!DOCTYPE html>" in html
    assert "测试书" in html


def test_import_file_creates_session(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    f.write_text("第一章 开端\n甲。\n", encoding="utf-8")
    data_dir = tmp_path / "sessions"
    session_id = import_file(f, data_dir, title="测试书")
    assert session_id.startswith("api-")
    assert any(data_dir.iterdir())
