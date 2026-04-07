"""TransformerAnalyzer — multilingual emotion backend using zero-shot NLI.

Replaces the lexicon-based (nrclex) approach with a multilingual NLI model
for zero-shot classification of 8 Plutchik emotions.

Model: MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli  (~430 MB, 107M params)
  - 100+ languages (zh, en, ja, etc.)
  - ~20-50ms per forward pass on CPU
  - Downloaded on first use, cached in ~/.cache/huggingface/

Performance (200 chunks, 8 emotions, CPU):
  - ~60-90 seconds total (runs in parallel with KG extraction)

Fallback: If transformers/torch cannot be loaded or model download fails,
  the extraction_pipeline falls back to LexiconAnalyzer automatically.

For users in China: set HF_ENDPOINT=https://hf-mirror.com to use mirror.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from bookscope.models import ChunkResult, EmotionScore

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Plutchik emotion labels per language
_EMOTION_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "anger": "anger and rage",
        "anticipation": "anticipation and expectation",
        "disgust": "disgust and revulsion",
        "fear": "fear and anxiety",
        "joy": "joy and happiness",
        "sadness": "sadness and grief",
        "surprise": "surprise and astonishment",
        "trust": "trust and acceptance",
    },
    "zh": {
        "anger": "愤怒、恼怒、激愤",
        "anticipation": "期待、期盼、盼望",
        "disgust": "厌恶、反感、嫌弃",
        "fear": "恐惧、害怕、焦虑",
        "joy": "喜悦、快乐、幸福",
        "sadness": "悲伤、哀愁、忧伤",
        "surprise": "惊讶、震惊、意外",
        "trust": "信任、信赖、安心",
    },
    "ja": {
        "anger": "怒り、憤り、激怒",
        "anticipation": "期待、予感、待望",
        "disgust": "嫌悪、反感、不快",
        "fear": "恐怖、不安、恐れ",
        "joy": "喜び、幸福、楽しさ",
        "sadness": "悲しみ、哀愁、憂い",
        "surprise": "驚き、衝撃、意外",
        "trust": "信頼、安心、信用",
    },
}

_HYPOTHESIS_TEMPLATES: dict[str, str] = {
    "en": "This text expresses {}.",
    "zh": "这段文字表达了{}的情感。",
    "ja": "このテキストは{}の感情を表しています。",
}

_EMOTION_KEYS = ("anger", "anticipation", "disgust", "fear", "joy", "sadness", "surprise", "trust")

# Default model — small, multilingual, fast
DEFAULT_MODEL = "MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli"

# Max text length for the model (tokens ≈ chars/2 for CJK, /4 for English)
_MAX_TEXT_CHARS = 512


class TransformerAnalyzer:
    """Multilingual emotion analyzer using zero-shot NLI classification.

    Implements AnalyzerProtocol.
    """

    def __init__(self, language: str = "zh", model_name: str | None = None) -> None:
        self.language = language
        self._model_name = model_name or DEFAULT_MODEL
        self._classifier = None  # lazy load

        # Resolve labels and hypothesis template
        lang_key = language if language in _EMOTION_LABELS else "en"
        self._labels = _EMOTION_LABELS[lang_key]
        self._hypothesis = _HYPOTHESIS_TEMPLATES.get(lang_key, _HYPOTHESIS_TEMPLATES["en"])

    def _get_classifier(self):
        """Lazy-load the zero-shot classification pipeline."""
        if self._classifier is None:
            from transformers import pipeline

            logger.info("Loading zero-shot NLI model: %s", self._model_name)
            self._classifier = pipeline(
                "zero-shot-classification",
                model=self._model_name,
                device=-1,  # CPU
            )
            logger.info("Model loaded successfully")
        return self._classifier

    def analyze_chunk(self, chunk: ChunkResult) -> EmotionScore:
        """Classify a single chunk into 8 Plutchik emotion dimensions."""
        classifier = self._get_classifier()

        # Truncate text for model input
        text = chunk.text[:_MAX_TEXT_CHARS].strip()
        if not text:
            return EmotionScore(chunk_index=chunk.index)

        # Run zero-shot classification with all emotion labels
        candidate_labels = list(self._labels.values())
        result = classifier(
            text,
            candidate_labels,
            hypothesis_template=self._hypothesis,
            multi_label=True,
        )

        # Map scores back to Plutchik keys
        label_to_key = {v: k for k, v in self._labels.items()}
        scores: dict[str, float] = {}
        for label, score in zip(result["labels"], result["scores"]):
            key = label_to_key.get(label, "")
            if key:
                scores[key] = round(float(score), 4)

        # Ensure all 8 dimensions present
        for key in _EMOTION_KEYS:
            scores.setdefault(key, 0.0)

        # Compute emotion density (fraction of dimensions above threshold)
        active_count = sum(1 for v in scores.values() if v > 0.15)
        density = round(active_count / len(_EMOTION_KEYS), 4)

        return EmotionScore(
            chunk_index=chunk.index,
            emotion_density=density,
            **{k: scores[k] for k in _EMOTION_KEYS},
        )

    def analyze_book(self, chunks: list[ChunkResult]) -> list[EmotionScore]:
        """Analyze all chunks — loads model once, processes sequentially.

        The zero-shot pipeline handles internal batching.
        """
        # Pre-load model
        self._get_classifier()

        results: list[EmotionScore] = []
        for chunk in chunks:
            score = self.analyze_chunk(chunk)
            results.append(score)

        return results
