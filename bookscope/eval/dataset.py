"""BookScope — Evaluation dataset model and loader."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field


class EvalSample(BaseModel):
    """A single evaluation sample with question, expected answer, and gold labels."""

    question: str
    expected_answer: str
    relevant_chunk_indices: list[int] = Field(default_factory=list)


def load_eval_dataset(path: str | Path) -> list[EvalSample]:
    """Load evaluation dataset from a JSON file.

    Expected format: JSON array of objects matching EvalSample fields.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [EvalSample(**item) for item in data]
