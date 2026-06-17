"""B-6 · 书名归一测试。

背景：anshi epub 的 DC:title 元数据存的是 ``安史之乱 : 历史、宣传与神话``
（半角冒号两边带空格），但出版物真实书名是 ``安史之乱：历史、宣传与神话``
全角冒号无空格。``normalize_book_title`` 把 epub 元数据兜底回出版物形态。

设计原则：
- 中文书名（含 CJK 字符）才启用归一；英文书名不动
- 半角 → 全角 punct + 标点两侧 ASCII 空格抹掉
- 幂等
"""

from __future__ import annotations

import pytest

from bookscope.ingest.loader import normalize_book_title


class TestNormalizeBookTitle:
    """半角→全角 + 空格剥离。"""

    def test_anshi_half_width_to_full_width(self) -> None:
        """anshi 的真实 bug 场景。"""
        got = normalize_book_title("安史之乱 : 历史、宣传与神话")
        assert got == "安史之乱：历史、宣传与神话"

    def test_anshi_full_width_unchanged(self) -> None:
        """已是出版物形态的 title 不被改动（幂等）。"""
        got = normalize_book_title("安史之乱：历史、宣传与神话")
        assert got == "安史之乱：历史、宣传与神话"

    def test_idempotent(self) -> None:
        """归一两次结果一致。"""
        once = normalize_book_title("安史之乱 : 历史、宣传与神话")
        twice = normalize_book_title(once)
        assert once == twice

    def test_no_extra_spaces_added(self) -> None:
        """归一不会在 title 两端 / 中段塞额外空格。"""
        got = normalize_book_title("明朝那些事儿")
        assert got == "明朝那些事儿"
        assert " " not in got

    def test_strip_leading_trailing_whitespace(self) -> None:
        got = normalize_book_title("  明朝那些事儿  ")
        assert got == "明朝那些事儿"

    def test_english_title_unchanged(self) -> None:
        """纯英文 title 不归一——半角标点是它们的本来形态。"""
        title = "The Great Gatsby: A Novel"
        got = normalize_book_title(title)
        assert got == title  # 冒号保持半角

    def test_english_with_parens_unchanged(self) -> None:
        title = "Anna Karenina (Translated Edition)"
        got = normalize_book_title(title)
        assert got == title

    def test_cjk_with_half_width_paren(self) -> None:
        """中文书名里半角圆括号也归一全角。"""
        got = normalize_book_title("安史之乱(张诗坪)")
        assert got == "安史之乱（张诗坪）"

    def test_cjk_with_half_width_semicolon(self) -> None:
        got = normalize_book_title("书名 ; 副标题")
        assert got == "书名；副标题"

    def test_empty_string(self) -> None:
        assert normalize_book_title("") == ""

    def test_pure_whitespace(self) -> None:
        assert normalize_book_title("   ") == ""


class TestLoaderIntegration:
    """``load_text`` 走 epub 路径时把归一应用到 DC:title。"""

    def test_anshi_epub_title_normalized(self, tmp_path) -> None:
        """anshi 真 epub 加载后 title 应该是全角冒号无空格形态。"""
        from pathlib import Path

        from bookscope.ingest.loader import load_text

        project_root = Path(__file__).resolve().parent.parent.parent
        anshi_path = project_root / "test安史之乱  历史、宣传与神话 (张诗坪, 胡可奇).epub"
        if not anshi_path.exists():
            pytest.skip(f"anshi 测试 epub 不在仓库工作目录: {anshi_path}")

        book = load_text(anshi_path)
        assert book.title == "安史之乱：历史、宣传与神话", (
            f"epub 元数据是半角冒号 + 空格，应归一为全角冒号无空格，"
            f"实际得到 {book.title!r}"
        )

    def test_mingchao_epub_title_unchanged(self, tmp_path) -> None:
        """mingchao 元数据本身没有冒号，归一不动它。"""
        from pathlib import Path

        from bookscope.ingest.loader import load_text

        project_root = Path(__file__).resolve().parent.parent.parent
        mingchao_path = project_root / "test明朝那些事儿.epub"
        if not mingchao_path.exists():
            pytest.skip(f"mingchao 测试 epub 不在仓库工作目录: {mingchao_path}")

        book = load_text(mingchao_path)
        assert book.title == "明朝那些事儿"
