"""StyleAnalyzer — surface-level stylometric metrics with multilingual support.

Language dispatch:
  "en" (default) — NLTK sentence tokenizer + Penn Treebank POS tagger
  "zh"           — jieba.posseg segmentation (no sentence splitting)
  "ja"           — janome morphological analysis (UniDic/IPAdic POS tags)
  other / unknown — falls back to English NLTK

Computed metrics (all languages):
  avg_sentence_length   mean tokens per sentence (CJK: chars-per-line proxy)
  ttr                   type-token ratio on content tokens
  noun_ratio            fraction of tokens tagged as noun
  verb_ratio            fraction of tokens tagged as verb
  adj_ratio             fraction of tokens tagged as adjective
  adv_ratio             fraction of tokens tagged as adverb
"""

from __future__ import annotations

from bookscope.models import ChunkResult, StyleScore

# ---------------------------------------------------------------------------
# English (NLTK)
# ---------------------------------------------------------------------------

_NOUN_TAGS = frozenset(["NN", "NNS", "NNP", "NNPS"])
_VERB_TAGS = frozenset(["VB", "VBD", "VBG", "VBN", "VBP", "VBZ"])
_ADJ_TAGS  = frozenset(["JJ", "JJR", "JJS"])
_ADV_TAGS  = frozenset(["RB", "RBR", "RBS"])


def _analyze_en(text: str, chunk_index: int) -> StyleScore:
    from nltk import pos_tag
    from nltk.tokenize import sent_tokenize, word_tokenize  # type: ignore[import]

    sentences = sent_tokenize(text)
    sent_lengths = [len(word_tokenize(s)) for s in sentences]
    avg_sentence_length = sum(sent_lengths) / max(len(sent_lengths), 1)

    all_tokens = word_tokenize(text)
    alpha_tokens = [t for t in all_tokens if t.isalpha()]

    if not alpha_tokens:
        return StyleScore(chunk_index=chunk_index, avg_sentence_length=avg_sentence_length)

    n = len(alpha_tokens)
    ttr = len({t.lower() for t in alpha_tokens}) / n
    tagged = pos_tag(alpha_tokens)
    noun_ratio = sum(1 for _, tag in tagged if tag in _NOUN_TAGS) / n
    verb_ratio = sum(1 for _, tag in tagged if tag in _VERB_TAGS) / n
    adj_ratio  = sum(1 for _, tag in tagged if tag in _ADJ_TAGS) / n
    adv_ratio  = sum(1 for _, tag in tagged if tag in _ADV_TAGS) / n

    return StyleScore(
        chunk_index=chunk_index,
        avg_sentence_length=avg_sentence_length,
        ttr=ttr,
        noun_ratio=noun_ratio,
        verb_ratio=verb_ratio,
        adj_ratio=adj_ratio,
        adv_ratio=adv_ratio,
    )


# ---------------------------------------------------------------------------
# Chinese (jieba)
# ---------------------------------------------------------------------------

# jieba.posseg POS tag prefixes
_ZH_NOUN_TAGS = frozenset(["n", "nr", "ns", "nz", "nt"])   # nouns
_ZH_VERB_TAGS = frozenset(["v", "vd", "vn", "vg"])          # verbs
_ZH_ADJ_TAGS  = frozenset(["a", "ad", "an", "ag"])           # adjectives
_ZH_ADV_TAGS  = frozenset(["d", "dg"])                       # adverbs


def _analyze_zh(text: str, chunk_index: int) -> StyleScore:
    try:
        import jieba.posseg as pseg  # type: ignore[import]
    except ImportError:
        return StyleScore(chunk_index=chunk_index)

    # Sentence-length proxy: mean characters per line
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    avg_sentence_length = (
        sum(len(ln) for ln in lines) / len(lines) if lines else float(len(text))
    )

    pairs = list(pseg.cut(text))
    # Filter punctuation and spaces
    content = [(word, flag) for word, flag in pairs if word.strip() and not _is_punct(word)]

    if not content:
        return StyleScore(chunk_index=chunk_index, avg_sentence_length=avg_sentence_length)

    n = len(content)
    ttr = len({word for word, _ in content}) / n

    def _match(flag: str, tag_set: frozenset[str]) -> bool:
        return flag in tag_set or flag[:2] in tag_set or flag[:1] in tag_set

    noun_ratio = sum(1 for _, f in content if _match(f, _ZH_NOUN_TAGS)) / n
    verb_ratio = sum(1 for _, f in content if _match(f, _ZH_VERB_TAGS)) / n
    adj_ratio  = sum(1 for _, f in content if _match(f, _ZH_ADJ_TAGS))  / n
    adv_ratio  = sum(1 for _, f in content if _match(f, _ZH_ADV_TAGS))  / n

    return StyleScore(
        chunk_index=chunk_index,
        avg_sentence_length=avg_sentence_length,
        ttr=ttr,
        noun_ratio=noun_ratio,
        verb_ratio=verb_ratio,
        adj_ratio=adj_ratio,
        adv_ratio=adv_ratio,
    )


# ---------------------------------------------------------------------------
# Japanese (janome)
# ---------------------------------------------------------------------------

# janome uses IPAdic POS — first element of the comma-separated part_of_speech field
_JA_NOUN = "名詞"
_JA_VERB = "動詞"
_JA_ADJ  = "形容詞"
_JA_ADV  = "副詞"


from functools import lru_cache as _lru_cache


@_lru_cache(maxsize=1)
def _get_ja_tokenizer():  # type: ignore[return]
    """Return a cached janome Tokenizer (expensive to init — load dictionary once)."""
    from janome.tokenizer import Tokenizer  # type: ignore[import]
    return Tokenizer()


def _analyze_ja(text: str, chunk_index: int) -> StyleScore:
    try:
        t = _get_ja_tokenizer()
    except ImportError:
        return StyleScore(chunk_index=chunk_index)

    tokens = list(t.tokenize(text))

    # Sentence-length proxy: mean characters per line
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    avg_sentence_length = (
        sum(len(ln) for ln in lines) / len(lines) if lines else float(len(text))
    )

    # Filter punctuation/whitespace tokens
    content = [tok for tok in tokens if tok.surface.strip() and not _is_punct(tok.surface)]

    if not content:
        return StyleScore(chunk_index=chunk_index, avg_sentence_length=avg_sentence_length)

    n = len(content)
    ttr = len({tok.surface for tok in content}) / n

    def _pos(tok) -> str:  # type: ignore[type-arg]
        return tok.part_of_speech.split(",")[0]

    noun_ratio = sum(1 for tok in content if _pos(tok) == _JA_NOUN) / n
    verb_ratio = sum(1 for tok in content if _pos(tok) == _JA_VERB) / n
    adj_ratio  = sum(1 for tok in content if _pos(tok) == _JA_ADJ)  / n
    adv_ratio  = sum(1 for tok in content if _pos(tok) == _JA_ADV)  / n

    return StyleScore(
        chunk_index=chunk_index,
        avg_sentence_length=avg_sentence_length,
        ttr=ttr,
        noun_ratio=noun_ratio,
        verb_ratio=verb_ratio,
        adj_ratio=adj_ratio,
        adv_ratio=adv_ratio,
    )


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------

def _is_punct(s: str) -> bool:
    """True if *s* contains only punctuation / whitespace."""
    import unicodedata
    return all(unicodedata.category(ch) in ("Po", "Ps", "Pe", "Pd", "Pc", "Zs", "Cc") for ch in s)


# ---------------------------------------------------------------------------
# Public analyzer
# ---------------------------------------------------------------------------

class StyleAnalyzer:
    """Computes surface stylometric metrics per chunk.

    Args:
        language: ``"en"``, ``"zh"``, ``"ja"``, or any other code (→ English).
    """

    def __init__(self, language: str = "en") -> None:
        self.language = language

    def analyze_chunk(self, chunk: ChunkResult) -> StyleScore:
        text = chunk.text.strip()
        if not text:
            return StyleScore(chunk_index=chunk.index)

        if self.language == "zh":
            return _analyze_zh(text, chunk.index)
        elif self.language == "ja":
            return _analyze_ja(text, chunk.index)
        else:
            return _analyze_en(text, chunk.index)

    def analyze_book(self, chunks: list[ChunkResult]) -> list[StyleScore]:
        """Analyze all chunks sequentially."""
        return [self.analyze_chunk(c) for c in chunks]
