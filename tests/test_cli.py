"""bookscope.cli 命令行测试（零 LLM 结构报告）。"""

from __future__ import annotations

import argparse
from pathlib import Path

from bookscope.cli import cmd_report


def test_cmd_report_generates_structure_html(tmp_path: Path) -> None:
    book = tmp_path / "sample.txt"
    book.write_text(
        "第一章 开端\n这是第一段正文。\n第二章 发展\n这是第二段正文。\n",
        encoding="utf-8",
    )
    out = tmp_path / "report.html"
    args = argparse.Namespace(path=str(book), out=str(out), title="测试书")
    assert cmd_report(args) == 0
    html = out.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in html
    assert "测试书" in html


def test_cmd_cross_without_key_returns_2(tmp_path: Path, monkeypatch) -> None:
    import bookscope.cli as cli

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    f1 = tmp_path / "a.txt"
    f2 = tmp_path / "b.txt"
    f1.write_text("第一章\n甲。\n", encoding="utf-8")
    f2.write_text("第一章\n乙。\n", encoding="utf-8")
    import argparse

    args = argparse.Namespace(
        file1=str(f1), file2=str(f2), out=str(tmp_path / "x.html"),
        title1=None, title2=None, provider="deepseek",
        api_key=None, model=None, base_url=None, open=False,
    )
    assert cli.cmd_cross(args) == 2


def test_cmd_ask_without_key_returns_2(tmp_path: Path, monkeypatch) -> None:
    import bookscope.cli as cli

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    f = tmp_path / "a.txt"
    f.write_text("第一章\n甲。\n", encoding="utf-8")
    import argparse

    args = argparse.Namespace(
        path=str(f), question="这本书讲了什么？", title=None,
        provider="deepseek", api_key=None, model=None, base_url=None, json=False,
    )
    assert cli.cmd_ask(args) == 2


def test_cmd_prewarm_without_key_returns_2(tmp_path: Path, monkeypatch) -> None:
    import bookscope.cli as cli

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    f = tmp_path / "a.txt"
    f.write_text("第一章\n甲。\n", encoding="utf-8")
    import argparse

    args = argparse.Namespace(
        path=str(f), title=None, provider="deepseek",
        api_key=None, model=None, base_url=None,
    )
    assert cli.cmd_prewarm(args) == 2


def test_cmd_cluster_without_key_returns_2(tmp_path: Path, monkeypatch) -> None:
    import bookscope.cli as cli

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    f1 = tmp_path / "a.txt"
    f2 = tmp_path / "b.txt"
    f1.write_text("第一章\n甲。\n", encoding="utf-8")
    f2.write_text("第一章\n乙。\n", encoding="utf-8")
    import argparse

    args = argparse.Namespace(
        files=[str(f1), str(f2)], name="组", out=str(tmp_path / "x.html"),
        provider="deepseek", api_key=None, model=None, base_url=None, open=False,
    )
    assert cli.cmd_cluster(args) == 2


def test_cmd_version_returns_0(capsys) -> None:
    import argparse

    import bookscope.cli as cli

    assert cli.cmd_version(argparse.Namespace()) == 0
    out = capsys.readouterr().out.strip()
    assert out


def test_cmd_report_deep_without_key_returns_2(tmp_path: Path, monkeypatch) -> None:
    import bookscope.cli as cli

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    f = tmp_path / "a.txt"
    f.write_text("第一章\n甲。\n", encoding="utf-8")
    import argparse

    args = argparse.Namespace(
        path=str(f), out=str(tmp_path / "r.html"), title="测试书", deep=True,
        provider="deepseek", api_key=None, model=None, base_url=None, open=False,
    )
    assert cli.cmd_report(args) == 2


def test_cmd_import_creates_session(tmp_path: Path, capsys) -> None:
    import bookscope.cli as cli

    f = tmp_path / "a.txt"
    f.write_text("第一章\n甲。\n第二章\n乙。\n", encoding="utf-8")
    data_dir = tmp_path / "sessions"
    import argparse

    args = argparse.Namespace(path=str(f), title="测试书", data_dir=str(data_dir))
    assert cli.cmd_import(args) == 0
    out = capsys.readouterr().out
    assert "已导入书库" in out
    # storage 目录应有至少一个 session 子目录
    assert any(data_dir.iterdir())


def test_cmd_list_shows_imported_book(tmp_path: Path, capsys) -> None:
    import bookscope.cli as cli

    f = tmp_path / "a.txt"
    f.write_text("第一章\n甲。\n", encoding="utf-8")
    data_dir = tmp_path / "sessions"
    import argparse

    assert cli.cmd_import(argparse.Namespace(path=str(f), title="测试书", data_dir=str(data_dir))) == 0
    assert cli.cmd_list(argparse.Namespace(data_dir=str(data_dir))) == 0
    out = capsys.readouterr().out
    assert "测试书" in out


def test_cmd_import_folder_imports_all(tmp_path: Path, capsys) -> None:
    import bookscope.cli as cli

    folder = tmp_path / "books"
    folder.mkdir()
    (folder / "a.txt").write_text("第一章\n甲。\n", encoding="utf-8")
    (folder / "b.md").write_text("# 第一章\n乙。\n", encoding="utf-8")
    (folder / "ignore.log").write_text("not supported", encoding="utf-8")
    data_dir = tmp_path / "sessions"
    import argparse

    assert cli.cmd_import(argparse.Namespace(path=str(folder), title=None, data_dir=str(data_dir))) == 0
    out = capsys.readouterr().out
    assert "成功 2/2" in out
    assert "a.txt" in out
    assert "b.md" in out


def test_local_ask_returns_results(capsys) -> None:
    import bookscope.cli as cli

    chunks = [
        {"chunk_id": "c0", "chapter": 1, "text": "这是关于经济改革的讨论。"},
        {"chunk_id": "c1", "chapter": 2, "text": "这里提到市场与政府的关系。"},
    ]
    assert cli._local_ask("市场与政府", chunks, json_out=False) == 0
    out = capsys.readouterr().out
    assert "本地检索结果" in out
    assert "市场与政府" in out or "第2章" in out


def test_cmd_summary_prints_chapters(tmp_path: Path, capsys) -> None:
    import bookscope.cli as cli

    f = tmp_path / "a.txt"
    f.write_text("第一章 开端\n甲。\n第二章 发展\n乙。\n", encoding="utf-8")
    import argparse

    assert cli.cmd_summary(argparse.Namespace(path=str(f), title="测试书")) == 0
    out = capsys.readouterr().out
    assert "测试书" in out
    assert "2 章" in out


def test_cmd_catalog_generates_index(tmp_path: Path, capsys) -> None:
    import bookscope.cli as cli

    folder = tmp_path / "books"
    folder.mkdir()
    (folder / "a.txt").write_text("第一章 开端\n甲。\n", encoding="utf-8")
    (folder / "b.md").write_text("# 第一章\n乙。\n", encoding="utf-8")
    out = tmp_path / "out"
    import argparse

    assert cli.cmd_catalog(argparse.Namespace(path=str(folder), out=str(out))) == 0
    assert (out / "index.html").exists()
    assert (out / "a.html").exists()
    assert (out / "b.html").exists()


def test_cmd_self_test_passes(capsys) -> None:
    import argparse

    import bookscope.cli as cli

    assert cli.cmd_self_test(argparse.Namespace()) == 0
    out = capsys.readouterr().out
    assert "零配置核心链路自检通过" in out
