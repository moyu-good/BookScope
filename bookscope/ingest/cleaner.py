"""Normalize raw book text before chunking."""

import re
import unicodedata


def clean(text: str) -> str:
    """Normalize raw text for NLP processing.

    Operations (in order):
      1. Normalize Unicode to NFC form
      2. Remove control characters (except \\n, \\t)
      3. Collapse 3+ consecutive newlines → 2 (paragraph separator)
      4. Collapse horizontal whitespace runs → single space per line
      5. Strip leading/trailing whitespace

    Args:
        text: Raw text string (any length, including empty).

    Returns:
        Cleaned text string. Returns empty string for empty input.
    """
    if not text:
        return ""

    # 1. Unicode normalization
    text = unicodedata.normalize("NFC", text)

    # 2. Remove control characters except \n and \t
    text = re.sub(r"[^\S\n\t ]+", " ", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

    # 3. Collapse 3+ blank lines → 2 (preserve paragraph breaks)
    text = re.sub(r"\n{3,}", "\n\n", text)

    # 4. Collapse multiple spaces/tabs on a single line
    text = re.sub(r"[^\S\n]+", " ", text)

    # 5. Strip
    return text.strip()
