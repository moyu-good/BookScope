"""Pydantic data schemas for BookScope.

Data flow:
    raw .txt file
        │
        ▼
    BookText         — full text + metadata
        │
        ▼
    list[ChunkResult] — text split into analysis units (paragraphs / fixed-size)
        │
        ▼
    EmotionScore      — 8-dimensional Plutchik emotion vector per chunk
"""

from pydantic import BaseModel, Field


class BookText(BaseModel):
    """Represents a loaded book before chunking."""

    title: str
    raw_text: str
    encoding: str = "utf-8"
    word_count: int = Field(default=0)

    def model_post_init(self, __context: object) -> None:
        if self.word_count == 0:
            self.word_count = len(self.raw_text.split())


class ChunkResult(BaseModel):
    """A single analysis unit (paragraph or fixed window) within a book."""

    index: int
    text: str
    word_count: int = Field(default=0)

    def model_post_init(self, __context: object) -> None:
        if self.word_count == 0:
            self.word_count = len(self.text.split())


class EmotionScore(BaseModel):
    """8-dimensional Plutchik emotion vector for one chunk.

    Scores are normalized to [0.0, 1.0].
    All values default to 0.0 (neutral / no signal).
    """

    chunk_index: int
    anger: float = 0.0
    anticipation: float = 0.0
    disgust: float = 0.0
    fear: float = 0.0
    joy: float = 0.0
    sadness: float = 0.0
    surprise: float = 0.0
    trust: float = 0.0

    @property
    def dominant_emotion(self) -> str:
        """Return the name of the highest-scoring emotion."""
        scores = {
            "anger": self.anger,
            "anticipation": self.anticipation,
            "disgust": self.disgust,
            "fear": self.fear,
            "joy": self.joy,
            "sadness": self.sadness,
            "surprise": self.surprise,
            "trust": self.trust,
        }
        return max(scores, key=lambda k: scores[k])

    def to_dict(self) -> dict[str, float]:
        return {
            "anger": self.anger,
            "anticipation": self.anticipation,
            "disgust": self.disgust,
            "fear": self.fear,
            "joy": self.joy,
            "sadness": self.sadness,
            "surprise": self.surprise,
            "trust": self.trust,
        }


class StyleScore(BaseModel):
    """Surface-level stylometric fingerprint for one chunk.

    Metrics:
        avg_sentence_length: Mean word count per sentence.
        ttr:                 Type-Token Ratio (unique / total alpha words).
        noun_ratio:          Fraction of alpha tokens tagged NN*.
        verb_ratio:          Fraction of alpha tokens tagged VB*.
        adj_ratio:           Fraction of alpha tokens tagged JJ*.
        adv_ratio:           Fraction of alpha tokens tagged RB*.
    """

    chunk_index: int
    avg_sentence_length: float = 0.0
    ttr: float = 0.0
    noun_ratio: float = 0.0
    verb_ratio: float = 0.0
    adj_ratio: float = 0.0
    adv_ratio: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {
            "avg_sentence_length": self.avg_sentence_length,
            "ttr": self.ttr,
            "noun_ratio": self.noun_ratio,
            "verb_ratio": self.verb_ratio,
            "adj_ratio": self.adj_ratio,
            "adv_ratio": self.adv_ratio,
        }
