"""Language detection for BookScope.

Fast Unicode-range-based detection for CJK languages, with langdetect fallback
for ambiguous cases. Optimised for book text where we primarily care about
distinguishing Chinese / English / Japanese.

Returns a normalised code:
    "zh"      — Chinese (simplified or traditional)
    "en"      — English / Latin-script
    "ja"      — Japanese
    <code>    — other BCP-47 code (via langdetect fallback)
    "unknown" — detection failed or text too short
"""

import re
import unicodedata

_SAMPLE_LEN = 2000

# Unicode ranges
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")  # CJK Unified Ideographs
_HIRAGANA_RE = re.compile(r"[\u3040-\u309f]")
_KATAKANA_RE = re.compile(r"[\u30a0-\u30ff]")
_LATIN_RE = re.compile(r"[a-zA-Z]")


def detect_language(text: str) -> str:
    """Return the language code for *text*.

    Uses fast Unicode character counting for CJK detection.
    Falls back to langdetect only for ambiguous Latin-script text.
    """
    if not text or not text.strip():
        return "unknown"

    sample = text.strip()[:_SAMPLE_LEN]
    # Only count actual letters/characters, skip whitespace and punctuation
    total = sum(1 for c in sample if unicodedata.category(c)[0] in ("L", "N"))
    if total == 0:
        return "unknown"

    cjk_count = len(_CJK_RE.findall(sample))
    hiragana_count = len(_HIRAGANA_RE.findall(sample))
    katakana_count = len(_KATAKANA_RE.findall(sample))
    latin_count = len(_LATIN_RE.findall(sample))

    cjk_ratio = cjk_count / total
    jp_kana_count = hiragana_count + katakana_count

    # Japanese: has CJK + kana characters
    if jp_kana_count > 10 and cjk_ratio > 0.1:
        return "ja"

    # Chinese: dominant CJK with minimal kana
    if cjk_ratio > 0.3:
        return "zh"

    # English / Latin-dominant
    if latin_count / total > 0.5:
        return "en"

    # Ambiguous: fall back to langdetect (lazy import to avoid startup cost)
    try:
        from langdetect import detect  # type: ignore[import]
        code = detect(sample)
    except Exception:
        return "unknown"

    if code in ("zh-cn", "zh-tw", "zh"):
        return "zh"
    return code
