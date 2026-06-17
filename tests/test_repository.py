"""Unit tests for bookscope.store.repository."""


from bookscope.models import EmotionScore, StyleScore
from bookscope.store.repository import AnalysisResult, Repository


def _make_result(title: str = "Test Book") -> AnalysisResult:
    return AnalysisResult.create(
        book_title=title,
        chunk_strategy="paragraph",
        total_chunks=3,
        total_words=300,
        arc_pattern="Icarus",
        emotion_scores=[EmotionScore(chunk_index=i, joy=0.5) for i in range(3)],
        style_scores=[StyleScore(chunk_index=i, ttr=0.6) for i in range(3)],
    )


class TestAnalysisResult:
    def test_create_sets_analyzed_at(self):
        result = _make_result()
        assert result.analyzed_at  # non-empty ISO string

    def test_to_csv_emotion_header(self):
        csv = _make_result().to_csv_emotion()
        assert csv.startswith("chunk_index,anger")

    def test_to_csv_emotion_row_count(self):
        result = _make_result()
        lines = result.to_csv_emotion().splitlines()
        assert len(lines) == 1 + result.total_chunks  # header + data rows

    def test_to_csv_style_header(self):
        csv = _make_result().to_csv_style()
        assert csv.startswith("chunk_index,avg_sentence_length")

    def test_to_csv_style_row_count(self):
        result = _make_result()
        lines = result.to_csv_style().splitlines()
        assert len(lines) == 1 + result.total_chunks

    def test_model_dump_json_roundtrip(self):
        original = _make_result()
        reloaded = AnalysisResult.model_validate_json(original.model_dump_json())
        assert reloaded.book_title == original.book_title
        assert len(reloaded.emotion_scores) == len(original.emotion_scores)

    def test_to_markdown_report_contains_title(self):
        md = _make_result("Pride and Prejudice").to_markdown_report()
        assert "Pride and Prejudice" in md

    def test_to_markdown_report_contains_arc(self):
        md = _make_result().to_markdown_report()
        assert "Icarus" in md

    def test_to_markdown_report_contains_emotion_table(self):
        md = _make_result().to_markdown_report()
        assert "| Emotion |" in md
        assert "Joy" in md

    def test_to_markdown_report_contains_style_table(self):
        md = _make_result().to_markdown_report()
        assert "| Metric |" in md
        assert "Ttr" in md


class TestRepository:
    def test_save_and_load(self, tmp_path):
        repo = Repository(tmp_path)
        result = _make_result("My Novel")
        path = repo.save(result)
        loaded = repo.load(path)
        assert loaded.book_title == "My Novel"
        assert len(loaded.emotion_scores) == 3

    def test_list_results_empty(self, tmp_path):
        repo = Repository(tmp_path / "empty")
        assert repo.list_results() == []

    def test_list_results_returns_saved(self, tmp_path):
        repo = Repository(tmp_path)
        repo.save(_make_result("A"))
        repo.save(_make_result("B"))
        assert len(repo.list_results()) == 2

    def test_delete_removes_file(self, tmp_path):
        repo = Repository(tmp_path)
        path = repo.save(_make_result())
        assert path.exists()
        repo.delete(path)
        assert not path.exists()

    def test_delete_missing_file_no_error(self, tmp_path):
        repo = Repository(tmp_path)
        repo.delete(tmp_path / "nonexistent.json")  # must not raise

    def test_save_creates_directory(self, tmp_path):
        repo = Repository(tmp_path / "deep" / "nested")
        repo.save(_make_result())
        assert (tmp_path / "deep" / "nested").exists()

    def test_filename_slug_from_title(self, tmp_path):
        repo = Repository(tmp_path)
        path = repo.save(_make_result("My Great Book"))
        assert "My_Great_Book" in path.stem
