"""Tests for multilingual support: language detection, CJK emotion & style analysis."""

import pytest

from bookscope.models import BookText, ChunkResult
from bookscope.nlp.lang_detect import detect_language
from bookscope.nlp.lexicon_analyzer import LexiconAnalyzer
from bookscope.nlp.style_analyzer import StyleAnalyzer
from bookscope.ingest.chunker import chunk, _word_count


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

class TestDetectLanguage:
    def test_english(self):
        text = "This is a wonderful story about love and friendship in the countryside."
        assert detect_language(text) == "en"

    def test_chinese(self):
        text = "这是一个关于爱情和友情的美好故事，发生在美丽的乡村。"
        assert detect_language(text) == "zh"

    def test_japanese(self):
        text = "これは美しい田舎で起きた愛と友情についての素晴らしい物語です。"
        assert detect_language(text) == "ja"

    def test_empty_returns_unknown(self):
        assert detect_language("") == "unknown"

    def test_whitespace_only_returns_unknown(self):
        assert detect_language("   \n\t  ") == "unknown"


# ---------------------------------------------------------------------------
# LexiconAnalyzer — CJK
# ---------------------------------------------------------------------------

class TestLexiconAnalyzerChinese:
    def setup_method(self):
        self.analyzer = LexiconAnalyzer(language="zh")

    def test_returns_emotion_score(self):
        chunk = ChunkResult(index=0, text="他充满了喜悦和幸福，笑容满面。")
        score = self.analyzer.analyze_chunk(chunk)
        assert score.chunk_index == 0

    def test_empty_chunk_all_zeros(self):
        chunk = ChunkResult(index=1, text="")
        score = self.analyzer.analyze_chunk(chunk)
        assert score.joy == pytest.approx(0.0)
        assert score.anger == pytest.approx(0.0)

    def test_joy_words_raise_joy_score(self):
        chunk = ChunkResult(index=0, text="喜悦 快乐 幸福 高兴 欢乐 笑")
        score = self.analyzer.analyze_chunk(chunk)
        assert score.joy > 0.0

    def test_analyze_book(self):
        chunks = [
            ChunkResult(index=0, text="他非常愤怒，怒火中烧。"),
            ChunkResult(index=1, text="她感到悲伤，泪流满面。"),
        ]
        scores = self.analyzer.analyze_book(chunks)
        assert len(scores) == 2
        assert scores[0].chunk_index == 0
        assert scores[1].chunk_index == 1

    def test_scores_normalized(self):
        chunk = ChunkResult(index=0, text="愤怒 恐惧 悲伤 喜悦 信任 期待")
        score = self.analyzer.analyze_chunk(chunk)
        total = sum(score.to_dict().values())
        assert total == pytest.approx(1.0, abs=1e-6)


class TestLexiconAnalyzerJapanese:
    def setup_method(self):
        self.analyzer = LexiconAnalyzer(language="ja")

    def test_returns_emotion_score(self):
        chunk = ChunkResult(index=0, text="彼は喜びと幸せに満ちていた。")
        score = self.analyzer.analyze_chunk(chunk)
        assert score.chunk_index == 0

    def test_empty_chunk_all_zeros(self):
        chunk = ChunkResult(index=2, text="   ")
        score = self.analyzer.analyze_chunk(chunk)
        assert score.anger == pytest.approx(0.0)

    def test_joy_words_raise_joy_score(self):
        chunk = ChunkResult(index=0, text="喜び 嬉しい 楽しい 幸せ 笑い")
        score = self.analyzer.analyze_chunk(chunk)
        assert score.joy > 0.0

    def test_analyze_book(self):
        chunks = [ChunkResult(index=i, text=t) for i, t in enumerate([
            "彼は激しく怒り、怒号を上げた。",
            "彼女は悲しみに暮れ、涙を流した。",
        ])]
        scores = self.analyzer.analyze_book(chunks)
        assert len(scores) == 2


# ---------------------------------------------------------------------------
# StyleAnalyzer — CJK
# ---------------------------------------------------------------------------

class TestStyleAnalyzerChinese:
    def setup_method(self):
        self.analyzer = StyleAnalyzer(language="zh")

    def test_returns_style_score(self):
        chunk = ChunkResult(index=0, text="他走进了房间。她站在窗边。阳光照耀着大地。")
        score = self.analyzer.analyze_chunk(chunk)
        assert score.chunk_index == 0

    def test_empty_chunk_all_zeros(self):
        chunk = ChunkResult(index=0, text="")
        score = self.analyzer.analyze_chunk(chunk)
        assert score.ttr == pytest.approx(0.0)

    def test_avg_sentence_length_positive(self):
        chunk = ChunkResult(index=0, text="这是一个长句子，包含很多词语和内容。\n这是另一个句子。")
        score = self.analyzer.analyze_chunk(chunk)
        assert score.avg_sentence_length > 0.0

    def test_ttr_between_zero_and_one(self):
        chunk = ChunkResult(index=0, text="这是一个关于爱情的故事，爱情是美好的，爱情让人快乐。")
        score = self.analyzer.analyze_chunk(chunk)
        assert 0.0 <= score.ttr <= 1.0

    def test_analyze_book(self):
        chunks = [ChunkResult(index=i, text=f"这是第{i}个段落，包含一些中文文字。") for i in range(3)]
        scores = self.analyzer.analyze_book(chunks)
        assert len(scores) == 3


class TestStyleAnalyzerJapanese:
    def setup_method(self):
        self.analyzer = StyleAnalyzer(language="ja")

    def test_returns_style_score(self):
        chunk = ChunkResult(index=0, text="彼は静かに部屋に入った。彼女は窓の傍に立っていた。")
        score = self.analyzer.analyze_chunk(chunk)
        assert score.chunk_index == 0

    def test_ttr_between_zero_and_one(self):
        chunk = ChunkResult(index=0, text="愛は美しい。愛は深い。愛は永遠だ。")
        score = self.analyzer.analyze_chunk(chunk)
        assert 0.0 <= score.ttr <= 1.0

    def test_analyze_book(self):
        chunks = [ChunkResult(index=i, text=f"これは第{i}段落です。日本語のテキストを含む。") for i in range(3)]
        scores = self.analyzer.analyze_book(chunks)
        assert len(scores) == 3


# ---------------------------------------------------------------------------
# BookText language field
# ---------------------------------------------------------------------------

class TestBookTextLanguage:
    def test_default_language_is_unknown(self):
        book = BookText(title="Test", raw_text="Some text here.")
        assert book.language == "unknown"

    def test_language_can_be_set(self):
        book = BookText(title="Test", raw_text="テスト。", language="ja")
        assert book.language == "ja"

    def test_model_copy_with_language(self):
        book = BookText(title="Test", raw_text="Some text.")
        updated = book.model_copy(update={"language": "en"})
        assert updated.language == "en"
        assert book.language == "unknown"  # original unchanged


# ---------------------------------------------------------------------------
# Chunker — CJK word count and fixed chunking
# ---------------------------------------------------------------------------

class TestCJKChunker:
    def test_word_count_chinese(self):
        # Chinese: non-whitespace chars = word count proxy
        count = _word_count("这是一个测试。", "zh")
        assert count == 7  # 7 non-whitespace chars

    def test_word_count_english(self):
        count = _word_count("this is a test", "en")
        assert count == 4

    def test_chunk_chinese_paragraph(self):
        book = BookText(
            title="test",
            raw_text="这是第一段。这是一个很长的段落，包含很多中文字符，用来测试分段功能是否正常工作。\n\n"
                     "这是第二段。同样是一个较长的中文段落，测试多语言分段支持。",
            language="zh",
        )
        chunks = chunk(book, strategy="paragraph", min_words=5)
        assert len(chunks) >= 1

    def test_chunk_japanese_paragraph(self):
        book = BookText(
            title="test",
            raw_text="これは最初の段落です。日本語のテキストを使ってテストを行います。\n\n"
                     "これは二番目の段落です。同様に日本語のテキストを含んでいます。",
            language="ja",
        )
        chunks = chunk(book, strategy="paragraph", min_words=5)
        assert len(chunks) >= 1

    def test_word_count_japanese(self):
        # Japanese: non-whitespace chars = word count proxy
        count = _word_count("これはテスト。", "ja")
        assert count == 7  # 7 non-whitespace chars

    def test_word_count_spaces_excluded(self):
        # Spaces/tabs/newlines not counted
        count = _word_count("こ れ\tは\nテスト", "zh")
        assert count == 6  # こ れ は テ ス ト = 6 non-whitespace chars


# ---------------------------------------------------------------------------
# Language detection — edge cases
# ---------------------------------------------------------------------------

class TestDetectLanguageEdgeCases:
    def test_zh_cn_code_normalized(self):
        """langdetect may return 'zh-cn' — must be normalized to 'zh'."""
        from bookscope.nlp.lang_detect import detect_language
        # Feed unambiguously Simplified Chinese text
        text = "这是一段中文文字，用于测试语言检测功能是否正确返回zh。"
        result = detect_language(text)
        assert result == "zh"

    def test_long_text_uses_sample(self):
        """Very long text should still return a result (uses _SAMPLE_LEN slice)."""
        from bookscope.nlp.lang_detect import detect_language
        text = "Hello world. " * 500  # ~6500 chars, well above sample limit
        result = detect_language(text)
        assert result == "en"
