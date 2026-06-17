"""Tests for bookscope.eval.dataset — EvalSample model and JSON loader."""

from __future__ import annotations

import json

from bookscope.eval.dataset import EvalSample, load_eval_dataset


class TestEvalSample:

    def test_basic_construction(self):
        s = EvalSample(question="Q?", expected_answer="A.", relevant_chunk_indices=[0, 1])
        assert s.question == "Q?"
        assert s.relevant_chunk_indices == [0, 1]

    def test_default_empty_indices(self):
        s = EvalSample(question="Q?", expected_answer="A.")
        assert s.relevant_chunk_indices == []

    def test_serialization_round_trip(self):
        s = EvalSample(question="Q?", expected_answer="A.", relevant_chunk_indices=[3])
        data = json.loads(s.model_dump_json())
        s2 = EvalSample.model_validate(data)
        assert s2.question == s.question
        assert s2.relevant_chunk_indices == s.relevant_chunk_indices


class TestLoadEvalDataset:

    def test_load_from_file(self, tmp_path):
        data = [
            {"question": "Q1?", "expected_answer": "A1.", "relevant_chunk_indices": [0]},
            {"question": "Q2?", "expected_answer": "A2.", "relevant_chunk_indices": [1, 2]},
        ]
        p = tmp_path / "test_dataset.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        samples = load_eval_dataset(p)
        assert len(samples) == 2
        assert samples[0].question == "Q1?"
        assert samples[1].relevant_chunk_indices == [1, 2]

    def test_load_fixture_file(self):
        """Verify the shipped eval_dataset.json is valid."""
        from pathlib import Path

        fixture = Path(__file__).parent / "fixtures" / "eval_dataset.json"
        if fixture.exists():
            samples = load_eval_dataset(fixture)
            assert len(samples) >= 1
            for s in samples:
                assert s.question
                assert s.expected_answer
