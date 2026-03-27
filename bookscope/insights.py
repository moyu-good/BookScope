"""BookScope quick-insight helpers.

Derives character names, key themes, readability grade, SVG sparkline,
and first-person density from existing analysis results.

Character extraction uses spaCy en_core_web_sm when available
(install with: pip install -e ".[spacy]"), falling back to regex NER.
All other helpers have zero new runtime dependencies (re + Counter only).
"""

import re
from collections import Counter

# ── spaCy NER — lazy-loaded, optional ────────────────────────────────────────

_spacy_nlp_loaded: bool = False
_spacy_nlp = None  # spacy.Language object or None


def _get_spacy_nlp():
    """Load spaCy en_core_web_sm once and cache. Returns None if unavailable."""
    global _spacy_nlp, _spacy_nlp_loaded
    if _spacy_nlp_loaded:
        return _spacy_nlp
    _spacy_nlp_loaded = True
    try:
        import spacy  # noqa: PLC0415
        _spacy_nlp = spacy.load("en_core_web_sm")
    except (ImportError, OSError):
        _spacy_nlp = None
    return _spacy_nlp


def _spacy_extract_names(
    chunks, top_n: int, min_frac: float
) -> list[str] | None:
    """Use spaCy PERSON entities. Returns None if spaCy is unavailable."""
    nlp = _get_spacy_nlp()
    if nlp is None:
        return None

    n = len(chunks)
    min_c = max(2, int(n * min_frac))
    chunk_pres: Counter = Counter()
    global_freq: Counter = Counter()

    for chunk in chunks:
        # Cap text per chunk so large chunks don't slow the pipeline
        doc = nlp(chunk.text[:5000])
        seen: set[str] = set()
        for ent in doc.ents:
            if ent.label_ == "PERSON":
                name = ent.text.strip()
                if len(name) >= 2:
                    global_freq[name] += 1
                    seen.add(name)
        for name in seen:
            chunk_pres[name] += 1

    candidates = {w: f for w, f in global_freq.items() if chunk_pres[w] >= min_c}
    return [w for w, _ in Counter(candidates).most_common(top_n)]


# ── Regex NER fallback ────────────────────────────────────────────────────────

_NON_NAMES = frozenset([
    "The", "He", "She", "They", "It", "We", "You", "But", "And",
    "So", "Then", "When", "While", "After", "His", "Her", "Their",
    "Its", "Our", "Mr", "Mrs", "Dr", "Chapter", "Part", "One", "Two",
    "Said", "Into", "From", "That", "This", "With", "Have", "Been",
    "Just", "Now", "Here", "There", "Again", "Like", "Even", "Well",
])

_NAME_PAT = re.compile(r'(?:^|(?<=[.!?\s]))[A-Z][a-z]{2,}\b')


def _regex_extract_names(chunks, top_n: int, min_frac: float) -> list[str]:
    n = len(chunks)
    min_c = max(2, int(n * min_frac))
    chunk_pres: Counter = Counter()
    global_freq: Counter = Counter()

    for chunk in chunks:
        seen: set[str] = set()
        for w in _NAME_PAT.findall(chunk.text):
            if w not in _NON_NAMES:
                global_freq[w] += 1
                if w not in seen:
                    chunk_pres[w] += 1
                    seen.add(w)

    candidates = {w: f for w, f in global_freq.items() if chunk_pres[w] >= min_c}
    return [w for w, _ in Counter(candidates).most_common(top_n)]


def extract_character_names(
    chunks, top_n: int = 5, min_frac: float = 0.05, lang: str = "en"
) -> list[str]:
    """Return top character-name candidates from English fiction chunks.

    Uses spaCy en_core_web_sm NER when installed (better accuracy, handles
    multi-word names and titles). Falls back to regex NER automatically.
    Returns [] immediately for CJK-script languages.
    """
    if lang in ("zh", "ja", "ko") or chunks is None:
        return []

    # Prefer spaCy NER (optional dep)
    result = _spacy_extract_names(chunks, top_n, min_frac)
    if result is not None:
        return result

    # Regex fallback
    return _regex_extract_names(chunks, top_n, min_frac)


# ── Key themes (academic / essay) ────────────────────────────────────────────

_STOPWORDS = frozenset([
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of",
    "with", "by", "from", "is", "are", "was", "were", "be", "been", "has", "have",
    "had", "do", "does", "did", "will", "would", "could", "should", "this", "that",
    "these", "those", "it", "its", "we", "they", "he", "she", "you", "which", "who",
    "what", "when", "how", "also", "more", "most", "not", "no", "so", "if", "as",
    "than", "into", "about", "each", "other", "new", "however", "thus", "therefore",
    "said", "just", "very", "can", "may", "one", "two", "all", "any", "such", "then",
])

_WORD_PAT = re.compile(r'\b[a-z]{4,}\b')


def extract_key_themes(chunks, style_scores, top_n: int = 6) -> list[str]:
    """Return top thematic words weighted by noun_ratio.

    Uses noun_ratio from existing StyleScore objects — no POS re-tagging.
    """
    nr_map = {s.chunk_index: s.noun_ratio for s in style_scores}
    weighted: dict[str, float] = {}
    pres: Counter = Counter()

    for chunk in chunks:
        nr = nr_map.get(chunk.index, 0.2)
        weight = 0.5 + nr
        words = _WORD_PAT.findall(chunk.text.lower())
        seen: set[str] = set()
        for word in words:
            if word not in _STOPWORDS:
                weighted[word] = weighted.get(word, 0.0) + weight
                if word not in seen:
                    pres[word] += 1
                    seen.add(word)

    min_c = max(3, int(len(chunks) * 0.20))
    cands = {w: s for w, s in weighted.items() if pres[w] >= min_c}
    return [w for w, _ in sorted(cands.items(), key=lambda x: -x[1])[:top_n]]


# ── Readability grade ─────────────────────────────────────────────────────────

_READABILITY_LABELS = {
    "en": ("Accessible", "Moderate", "Dense", "Specialist"),
    "zh": ("通俗易读", "一般难度", "较难", "专业级"),
    "ja": ("読みやすい", "普通", "難しい", "専門的"),
}


def compute_readability(style_scores, ui_lang: str = "en") -> tuple[float, str, float]:
    """Return (score 0–1, label str, confidence 0–1).

    Confidence is low for short texts (<10 chunks).
    """
    if not style_scores:
        labels = _READABILITY_LABELS.get(ui_lang, _READABILITY_LABELS["en"])
        return 0.5, labels[1], 0.0

    confidence = min(1.0, len(style_scores) / 10.0)
    n = len(style_scores)
    ttr  = sum(s.ttr for s in style_scores) / n
    sent = sum(s.avg_sentence_length for s in style_scores) / n
    noun = sum(s.noun_ratio for s in style_scores) / n

    ttr_n  = min(1.0, max(0.0, (ttr  - 0.30) / 0.55))
    sent_n = min(1.0, max(0.0, (sent - 8.0)  / 27.0))
    noun_n = min(1.0, max(0.0, (noun - 0.15) / 0.30))

    score = 0.4 * sent_n + 0.35 * ttr_n + 0.25 * noun_n
    labels = _READABILITY_LABELS.get(ui_lang, _READABILITY_LABELS["en"])
    label = (
        labels[0] if score < 0.30 else
        labels[1] if score < 0.55 else
        labels[2] if score < 0.78 else
        labels[3]
    )
    return score, label, confidence


# ── SVG sparkline ─────────────────────────────────────────────────────────────

def compute_sparkline_points(
    valence_series: list[float],
    width: int = 200,
    height: int = 40,
    pad: int = 4,
) -> str:
    """Return SVG polyline points string for the valence series.

    Guards against empty list and flat line (zero range).
    """
    if not valence_series:
        mid = height // 2
        return f"0,{mid} {width},{mid}"

    v_min, v_max = min(valence_series), max(valence_series)
    r = v_max - v_min
    if r == 0:
        mid = height // 2
        return f"0,{mid} {width},{mid}"

    n = len(valence_series)
    pts = []
    for i, v in enumerate(valence_series):
        x = (i / max(n - 1, 1)) * width
        y = height - pad - ((v - v_min) / r) * (height - 2 * pad)
        pts.append(f"{x:.1f},{y:.1f}")
    return " ".join(pts)


# ── First-person density ──────────────────────────────────────────────────────

_FP_BY_LANG: dict[str, re.Pattern] = {
    "en": re.compile(
        r'\b(I|me|my|myself|mine|we|our|ourselves|ours)\b', re.IGNORECASE
    ),
    "zh": re.compile(r'[我咱俺我们咱们]'),
    "ja": re.compile(r'[私僕俺わたし自分]'),
}


def first_person_density(chunks, lang: str = "en") -> float:
    """Return fraction of words that are first-person pronouns.

    Dispatches to language-appropriate pattern for CJK texts.
    """
    pat = _FP_BY_LANG.get(lang, _FP_BY_LANG["en"])
    total_words = 0
    fp_count = 0
    for chunk in chunks:
        words = chunk.text.split()
        total_words += len(words)
        fp_count += len(pat.findall(chunk.text))
    return fp_count / max(total_words, 1)
