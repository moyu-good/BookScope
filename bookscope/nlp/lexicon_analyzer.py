"""LexiconAnalyzer — emotion backend with multilingual support.

Language dispatch:
  "en" (default) — NRC Emotion Lexicon via nrclex
  "zh"           — jieba word segmentation + bundled Chinese NRC lexicon
  "ja"           — janome morphological analysis + bundled Japanese NRC lexicon
  other / unknown — falls back to English nrclex

All scores are normalized to [0.0, 1.0].
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from bookscope.models import ChunkResult, EmotionScore

_NRC_FIELDS = ("anger", "anticipation", "disgust", "fear", "joy", "sadness", "surprise", "trust")
_DATA_DIR = Path(__file__).parent.parent / "data"


# ---------------------------------------------------------------------------
# Lexicon loading (cached)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=2)
def _load_cjk_lexicon(lang: str) -> dict[str, list[str]]:
    """Load Chinese or Japanese emotion lexicon from bundled JSON."""
    path = _DATA_DIR / f"nrc_{lang}.json"
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _build_word_map(lexicon: dict[str, list[str]]) -> dict[str, list[str]]:
    """Invert lexicon: word → [emotion, ...] for O(1) lookup."""
    word_map: dict[str, list[str]] = {}
    for emotion, words in lexicon.items():
        for word in words:
            word_map.setdefault(word, []).append(emotion)
    return word_map


@lru_cache(maxsize=2)
def _load_word_map(lang: str) -> dict[str, list[str]]:
    return _build_word_map(_load_cjk_lexicon(lang))


# ---------------------------------------------------------------------------
# Tokenizers
# ---------------------------------------------------------------------------

def _tokenize_zh(text: str) -> list[str]:
    """Segment Chinese text into words using jieba."""
    try:
        import jieba  # type: ignore[import]
        return list(jieba.cut(text))
    except ImportError:
        return text.split()


def _tokenize_ja(text: str) -> list[str]:
    """Tokenize Japanese text using janome."""
    try:
        from janome.tokenizer import Tokenizer  # type: ignore[import]
        t = Tokenizer()
        return [token.surface for token in t.tokenize(text)]
    except ImportError:
        return list(text)


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _score_en(text: str) -> dict[str, float]:
    """Score English text with nrclex."""
    from nrclex import NRCLex  # type: ignore[import]

    nrc = NRCLex()
    nrc.load_raw_text(text)
    raw: dict[str, float] = nrc.raw_emotion_scores
    total = sum(raw.get(f, 0.0) for f in _NRC_FIELDS)
    if total == 0:
        return {}
    return {f: raw.get(f, 0.0) / total for f in _NRC_FIELDS}


def _score_cjk(tokens: list[str], lang: str) -> dict[str, float]:
    """Score CJK tokens against the bundled lexicon."""
    word_map = _load_word_map(lang)
    counts: dict[str, float] = {f: 0.0 for f in _NRC_FIELDS}
    for token in tokens:
        for emotion in word_map.get(token, []):
            if emotion in counts:
                counts[emotion] += 1.0
    total = sum(counts.values())
    if total == 0:
        return {}
    return {f: counts[f] / total for f in _NRC_FIELDS}


# ---------------------------------------------------------------------------
# Public analyzer
# ---------------------------------------------------------------------------

class LexiconAnalyzer:
    """Emotion analyzer with English / Chinese / Japanese support.

    Args:
        language: BCP-47 language code. ``"en"``, ``"zh"``, ``"ja"``, or
                  any other value (falls back to English nrclex).
    """

    def __init__(self, language: str = "en") -> None:
        self.language = language

    def analyze_chunk(self, chunk: ChunkResult) -> EmotionScore:
        """Score one chunk across 8 Plutchik dimensions."""
        if not chunk.text.strip():
            return EmotionScore(chunk_index=chunk.index)

        lang = self.language
        scores: dict[str, float]

        if lang == "zh":
            tokens = _tokenize_zh(chunk.text)
            scores = _score_cjk(tokens, "zh")
        elif lang == "ja":
            tokens = _tokenize_ja(chunk.text)
            scores = _score_cjk(tokens, "ja")
        else:
            scores = _score_en(chunk.text)

        if not scores:
            return EmotionScore(chunk_index=chunk.index)

        return EmotionScore(chunk_index=chunk.index, **scores)

    def analyze_book(self, chunks: list[ChunkResult]) -> list[EmotionScore]:
        """Analyze all chunks sequentially."""
        return [self.analyze_chunk(c) for c in chunks]
