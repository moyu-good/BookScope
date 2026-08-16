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
