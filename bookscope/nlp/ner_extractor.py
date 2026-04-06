"""BookScope — Fast local NER for character candidate extraction.

Runs on ALL chunks without LLM dependency.  Three language backends:
- Chinese: jieba.posseg nr/nrf tags + dialogue/title regex
- English: spaCy PERSON NER (optional) + dialogue/title regex fallback
- Japanese: janome proper-noun filter + dialogue regex

Returns name -> chunk_indices mapping for downstream LLM enrichment.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bookscope.models.schemas import ChunkResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Chinese patterns
# ---------------------------------------------------------------------------

_ZH_SPEECH_VERBS = r"(?:说|道|问|答|叫|喊|笑|叹|怒|惊|嚷|吼|哭|嗤|吟|咏|呼|唤)"
_ZH_DIALOGUE_PAT = re.compile(r"([\u4e00-\u9fff]{2,4})" + _ZH_SPEECH_VERBS)
_ZH_TITLE_PAT = re.compile(
    r"([\u4e00-\u9fff]{1,4})"
    r"(?:先生|夫人|小姐|大人|老爷|太太|姑娘|公子|老师|师傅|师父)"
)

# ---------------------------------------------------------------------------
# English patterns
# ---------------------------------------------------------------------------

_EN_SPEECH_VERBS = (
    r"(?:said|asked|replied|whispered|shouted|cried|murmured|exclaimed|"
    r"muttered|called|answered|demanded|declared|insisted|suggested)"
)
_EN_DIALOGUE_PAT = re.compile(
    # "said Alice" pattern
    _EN_SPEECH_VERBS + r"\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)"
    r"|"
    # "Alice said" pattern
    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+" + _EN_SPEECH_VERBS
)
_EN_TITLE_PAT = re.compile(
    r"((?:Mr\.|Mrs\.|Ms\.|Miss|Lord|Lady|Sir|Dr\.|Professor|Captain|Colonel)"
    r"\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)"
)
_EN_TITLE_NAME_PAT = re.compile(
    r"(?:Mr\.|Mrs\.|Ms\.|Miss|Lord|Lady|Sir|Dr\.|Professor|Captain|Colonel)"
    r"\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)"
)

# ---------------------------------------------------------------------------
# Japanese patterns
# ---------------------------------------------------------------------------

_JA_DIALOGUE_PAT = re.compile(
    r"\u300c[^\u300d]*\u300d\s*(?:\u3068)?\s*([\u3040-\u9fff]{2,6})"
    r"(?:\u304c|\u306f|\u306e|\u306b)"
)


# ---------------------------------------------------------------------------
# Per-language extractors
# ---------------------------------------------------------------------------


def _extract_zh(text: str) -> set[str]:
    """Extract Chinese character-name candidates from one chunk."""
    names: set[str] = set()

    # 1. jieba.posseg NR/NRF tags
    try:
        import jieba.posseg as pseg

        for word, flag in pseg.cut(text):
            if flag in ("nr", "nrf") and len(word) >= 2:
                names.add(word)
    except ImportError:
        pass

    # 2. Dialogue attribution regex
    for m in _ZH_DIALOGUE_PAT.finditer(text):
        candidate = m.group(1)
        if len(candidate) >= 2:
            names.add(candidate)

    # 3. Title / honorific patterns
    for m in _ZH_TITLE_PAT.finditer(text):
        prefix = m.group(1)
        if len(prefix) >= 2:
            names.add(prefix)

    return names


def _extract_en(text: str) -> set[str]:
    """Extract English character-name candidates from one chunk."""
    names: set[str] = set()

    # 1. spaCy PERSON NER (optional — reuses insights.py singleton)
    try:
        from bookscope.insights import _get_spacy_nlp

        nlp = _get_spacy_nlp()
        if nlp is not None:
            doc = nlp(text[:5000])
            for ent in doc.ents:
                if ent.label_ == "PERSON" and len(ent.text.strip()) >= 2:
                    names.add(ent.text.strip())
    except Exception:
        pass

    # 2. Dialogue tag regex
    for m in _EN_DIALOGUE_PAT.finditer(text):
        name = m.group(1) or m.group(2)
        if name:
            names.add(name)

    # 3. Title patterns — capture both "Mr. Darcy" and "Darcy"
    for m in _EN_TITLE_PAT.finditer(text):
        names.add(m.group(1))
    for m in _EN_TITLE_NAME_PAT.finditer(text):
        names.add(m.group(1))

    return names


def _extract_ja(text: str) -> set[str]:
    """Extract Japanese character-name candidates from one chunk."""
    names: set[str] = set()

    # 1. janome proper-noun filter
    try:
        from janome.tokenizer import Tokenizer

        t = Tokenizer()
        for tok in t.tokenize(text):
            if "固有名詞" in tok.part_of_speech and len(tok.surface) >= 2:
                names.add(tok.surface)
    except ImportError:
        pass

    # 2. Dialogue regex: 「...」とXが/は
    for m in _JA_DIALOGUE_PAT.finditer(text):
        names.add(m.group(1))

    return names


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_EXTRACTORS = {
    "zh": _extract_zh,
    "en": _extract_en,
    "ja": _extract_ja,
}


def extract_character_candidates(
    chunks: list[ChunkResult],
    language: str,
    *,
    min_chunk_spread: int = 2,
) -> dict[str, list[int]]:
    """Extract character-name candidates from ALL chunks using local NER.

    Args:
        chunks: All book chunks.
        language: Language code ("zh", "en", "ja").
        min_chunk_spread: Minimum number of distinct chunks a name must
            appear in to be kept (filters noise).

    Returns:
        Mapping of name -> sorted list of chunk indices where name appears.
    """
    if not chunks:
        return {}

    extractor = _EXTRACTORS.get(language, _extract_en)

    raw: dict[str, set[int]] = {}
    for i, chunk in enumerate(chunks):
        text = getattr(chunk, "text", str(chunk))
        for name in extractor(text):
            raw.setdefault(name, set()).add(i)

    # Filter: keep names appearing in >= min_chunk_spread distinct chunks
    return {
        name: sorted(indices)
        for name, indices in raw.items()
        if len(indices) >= min_chunk_spread
    }
