"""StyleAnalyzer — surface-level stylometric metrics using NLTK.

Computes 6 metrics per chunk without requiring spaCy models:
  - avg_sentence_length  (NLTK sentence tokenizer)
  - ttr                  (type-token ratio on alpha words)
  - noun / verb / adj / adv ratios  (NLTK averaged_perceptron_tagger_eng)

NLTK corpora required (one-time download):
  python -m textblob.download_corpora
"""

from nltk import pos_tag
from nltk.tokenize import sent_tokenize, word_tokenize  # type: ignore[import]

from bookscope.models import ChunkResult, StyleScore

_NOUN_TAGS = frozenset(["NN", "NNS", "NNP", "NNPS"])
_VERB_TAGS = frozenset(["VB", "VBD", "VBG", "VBN", "VBP", "VBZ"])
_ADJ_TAGS = frozenset(["JJ", "JJR", "JJS"])
_ADV_TAGS = frozenset(["RB", "RBR", "RBS"])


class StyleAnalyzer:
    """Computes surface stylometric metrics for each chunk via NLTK POS tagging."""

    def analyze_chunk(self, chunk: ChunkResult) -> StyleScore:
        """Score one chunk across 6 style dimensions.

        Args:
            chunk: ChunkResult with .text.

        Returns:
            StyleScore with all metrics. All zeros for empty/whitespace input.
        """
        text = chunk.text.strip()
        if not text:
            return StyleScore(chunk_index=chunk.index)

        # Sentence-level average length
        sentences = sent_tokenize(text)
        sent_lengths = [len(word_tokenize(s)) for s in sentences]
        avg_sentence_length = sum(sent_lengths) / max(len(sent_lengths), 1)

        # All tokens for POS tagging (alphabetic only)
        all_tokens = word_tokenize(text)
        alpha_tokens = [t for t in all_tokens if t.isalpha()]

        if not alpha_tokens:
            return StyleScore(
                chunk_index=chunk.index,
                avg_sentence_length=avg_sentence_length,
            )

        n = len(alpha_tokens)

        # Type-token ratio
        ttr = len({t.lower() for t in alpha_tokens}) / n

        # POS ratios
        tagged = pos_tag(alpha_tokens)
        noun_ratio = sum(1 for _, tag in tagged if tag in _NOUN_TAGS) / n
        verb_ratio = sum(1 for _, tag in tagged if tag in _VERB_TAGS) / n
        adj_ratio = sum(1 for _, tag in tagged if tag in _ADJ_TAGS) / n
        adv_ratio = sum(1 for _, tag in tagged if tag in _ADV_TAGS) / n

        return StyleScore(
            chunk_index=chunk.index,
            avg_sentence_length=avg_sentence_length,
            ttr=ttr,
            noun_ratio=noun_ratio,
            verb_ratio=verb_ratio,
            adj_ratio=adj_ratio,
            adv_ratio=adv_ratio,
        )

    def analyze_book(self, chunks: list[ChunkResult]) -> list[StyleScore]:
        """Analyze all chunks sequentially."""
        return [self.analyze_chunk(c) for c in chunks]
