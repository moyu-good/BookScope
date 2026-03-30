"""Tests for bookscope.viz.card_renderer."""


from bookscope.models import EmotionScore
from bookscope.viz.card_renderer import generate_share_card

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _emotion_scores(fear=0.6, joy=0.2, sadness=0.1, n=3):
    return [
        EmotionScore(chunk_index=i, fear=fear, joy=joy, sadness=sadness)
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGenerateShareCard:
    def test_returns_valid_png_bytes(self):
        """Output starts with the PNG magic bytes."""
        png = generate_share_card(
            book_title="The Great Gatsby",
            arc_pattern="Icarus",
            detected_lang="en",
            total_words=47094,
            n_chunks=42,
            emotion_scores=_emotion_scores(),
        )
        assert isinstance(png, bytes)
        assert png[:8] == b"\x89PNG\r\n\x1a\n", "Output is not a valid PNG"

    def test_non_empty_output(self):
        """Card is at least 1 KB (real content, not a stub)."""
        png = generate_share_card(
            book_title="Moby Dick",
            arc_pattern="Rags to Riches",
            detected_lang="en",
            total_words=206052,
            n_chunks=100,
            emotion_scores=_emotion_scores(fear=0.1, joy=0.7),
        )
        assert len(png) > 1024

    def test_empty_emotion_scores(self):
        """No emotion scores → renders without error (all bars at zero)."""
        png = generate_share_card(
            book_title="Empty Book",
            arc_pattern="Unknown",
            detected_lang="en",
            total_words=100,
            n_chunks=1,
            emotion_scores=[],
        )
        assert png[:8] == b"\x89PNG\r\n\x1a\n"

    def test_long_title_truncated(self):
        """Book titles longer than 55 characters are truncated, not overflow."""
        long_title = "A" * 80
        png = generate_share_card(
            book_title=long_title,
            arc_pattern="Cinderella",
            detected_lang="zh",
            total_words=50000,
            n_chunks=50,
            emotion_scores=_emotion_scores(joy=0.8),
        )
        assert png[:8] == b"\x89PNG\r\n\x1a\n"

    def test_chinese_detected_lang(self):
        """Chinese language label renders without error."""
        png = generate_share_card(
            book_title="红楼梦",
            arc_pattern="Oedipus",
            detected_lang="zh",
            total_words=780000,
            n_chunks=300,
            emotion_scores=_emotion_scores(sadness=0.7, n=10),
        )
        assert png[:8] == b"\x89PNG\r\n\x1a\n"

    def test_all_arc_patterns_render(self):
        """Every known arc pattern renders without error."""
        arcs = [
            "Rags to Riches", "Riches to Rags", "Man in a Hole",
            "Icarus", "Cinderella", "Oedipus", "Unknown",
        ]
        for arc in arcs:
            png = generate_share_card(
                book_title="Test",
                arc_pattern=arc,
                detected_lang="en",
                total_words=1000,
                n_chunks=5,
                emotion_scores=_emotion_scores(),
            )
            assert png[:8] == b"\x89PNG\r\n\x1a\n", f"Failed for arc: {arc}"

    def test_single_chunk(self):
        """Single-chunk analysis renders without division-by-zero."""
        png = generate_share_card(
            book_title="Short Story",
            arc_pattern="Unknown",
            detected_lang="ja",
            total_words=200,
            n_chunks=1,
            emotion_scores=_emotion_scores(n=1),
        )
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
