"""Language detection for BookScope.

Uses langdetect (https://pypi.org/project/langdetect/) to identify the
primary language of a book's text.  Returns a normalised code:

    "en"      — English
    "zh"      — Chinese (simplified or traditional)
    "ja"      — Japanese
    <code>    — any other BCP-47 code as returned by langdetect
    "unknown" — detection failed or text too short

Detection is run on the first 2000 characters to keep it fast.
"""

_SAMPLE_LEN = 2000


def detect_language(text: str) -> str:
    """Return the language code for *text*.

    Falls back to ``"unknown"`` if langdetect is unavailable or raises.
    """
    if not text or not text.strip():
        return "unknown"

    sample = text.strip()[:_SAMPLE_LEN]

    try:
        from langdetect import detect  # type: ignore[import]
        from langdetect.lang_detect_exception import LangDetectException  # type: ignore[import]

        code = detect(sample)
    except ImportError:
        return "unknown"
    except Exception:  # LangDetectException or any other
        return "unknown"

    # Normalise Chinese variants
    if code in ("zh-cn", "zh-tw", "zh"):
        return "zh"
    return code
