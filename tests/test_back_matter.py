"""书末非正文区剔除（bookscope.ingest.back_matter）单元测试。

覆盖：参考文献/附录/后记识别、正文不误杀、无章号书不动、全文同步截断。
"""

import unittest

from bookscope.ingest.back_matter import _looks_like_back_matter_title, exclude_back_matter


class _Chunk:
    def __init__(self, index: int, text: str, chapter: int | None):
        self.index = index
        self.text = text
        self.chapter = chapter


class TestTitleDetect(unittest.TestCase):
    def test_chinese_titles(self):
        for t in ("参考文献", "附录", "后记", "致谢", "注 释", "参考 文献"):
            assert _looks_like_back_matter_title(t), t

    def test_english_titles(self):
        for t in ("References", "Bibliography", "Appendix A", "Notes", "Index", "Acknowledgments"):
            assert _looks_like_back_matter_title(t), t

    def test_normal_sentence_not_title(self):
        # 正文句子：太长 / 不是行首关键词
        assert not _looks_like_back_matter_title("参考文献是学术写作的重要部分，这里讲的是方法论与相关研究综述。")
        assert not _looks_like_back_matter_title("今天天气很好，我们去散步吧。")

    def test_long_title_not_match(self):
        assert not _looks_like_back_matter_title("参考文献与注释的格式规范说明（本文档第 120 页起，共三万字长文）")


class TestExclude(unittest.TestCase):
    CHUNKS = [
        _Chunk(0, "第一章 开始\n正文内容一", 1),
        _Chunk(1, "第二章 发展\n正文内容二", 2),
        _Chunk(2, "参考文献\n[1] 某某某. 论财政激励. 2024.\n[2] 某某. 论锦标赛. 2023.", 2),  # 并进最后一章
        _Chunk(3, "附录\n补充表格数据", None),
    ]
    FULL = ("第一章 开始\n正文内容一\n第二章 发展\n正文内容二\n参考文献\n"
            "[1] 某某某. 论财政激励. 2024.\n[2] 某某. 论锦标赛. 2023.\n附录\n补充表格数据")

    def test_back_matter_cut(self):
        ft, chunks = exclude_back_matter(self.FULL, self.CHUNKS)
        assert [c.index for c in chunks] == [0, 1]
        assert "参考文献" not in ft
        assert "正文内容二" in ft

    def test_no_back_matter_untouched(self):
        chunks = [_Chunk(0, "第一章\n正文", 1), _Chunk(1, "第二章\n正文", 2)]
        ft, out = exclude_back_matter("第一章\n正文第二章\n正文", chunks)
        assert len(out) == 2
        assert ft == "第一章\n正文第二章\n正文"

    def test_no_chapter_numbers_untouched(self):
        chunks = [_Chunk(0, "参考文献\n[1] a", None)]
        ft, out = exclude_back_matter("参考文献\n[1] a", chunks)
        assert len(out) == 1

    def test_mid_book_reference_section_untouched(self):
        # 参考文献出现在书中（后面还有正文章）→ 不是书末区，不动
        chunks = [_Chunk(0, "参考文献\n[1] a", 2), _Chunk(1, "第五章 继续\n正文", 5)]
        ft, out = exclude_back_matter("参考文献\n[1] a\n第五章 继续\n正文", chunks)
        assert len(out) == 2


if __name__ == "__main__":
    unittest.main()
