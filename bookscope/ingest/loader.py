"""Load plain-text and EPUB book files into BookText objects.

Supported formats:
  .txt   — UTF-8 / latin-1 / cp1252 with automatic fallback
  .epub  — extracted via ebooklib + HTML tag stripping
"""

from html.parser import HTMLParser
from pathlib import Path

from bookscope.models import BookText


class EmptyTextError(ValueError):
    """Raised when the loaded file contains no usable text."""


FALLBACK_ENCODINGS = ["utf-8", "latin-1", "cp1252"]


def load_text(path: Path | str, title: str | None = None) -> BookText:
    """Read a .txt or .epub file and return a BookText.

    Dispatches to the appropriate loader based on file extension.

    Args:
        path: Path to the .txt or .epub file.
        title: Display title. Defaults to the filename stem.

    Raises:
        FileNotFoundError: If the file does not exist.
        EmptyTextError: If the file contains no non-whitespace text.
        ValueError: If the file extension is not supported.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    suffix = path.suffix.lower()
    if suffix == ".epub":
        return _load_epub(path, title)
    if suffix in (".txt", ""):
        return _load_txt(path, title)
    raise ValueError(f"Unsupported file type: {suffix!r}. Supported: .txt, .epub")


# ---------------------------------------------------------------------------
# Private loaders
# ---------------------------------------------------------------------------

def _load_txt(path: Path, title: str | None) -> BookText:
    raw_text: str | None = None
    used_encoding = "utf-8"

    for enc in FALLBACK_ENCODINGS:
        try:
            raw_text = path.read_text(encoding=enc)
            used_encoding = enc
            break
        except UnicodeDecodeError:
            continue

    if raw_text is None:
        raw_text = path.read_text(encoding="utf-8", errors="ignore")
        used_encoding = "utf-8"

    if not raw_text.strip():
        raise EmptyTextError(f"File is empty or contains only whitespace: {path}")

    return BookText(title=title or path.stem, raw_text=raw_text, encoding=used_encoding)


def _load_epub(path: Path, title: str | None) -> BookText:
    """Extract plain text from an EPUB file via ebooklib."""
    try:
        import ebooklib  # type: ignore[import]
        from ebooklib import epub  # type: ignore[import]
    except ImportError as exc:
        raise ImportError(
            "ebooklib is required for EPUB support. "
            "Install it with: pip install ebooklib"
        ) from exc

    book = epub.read_epub(str(path), options={"ignore_ncx": True})

    # Extract display title from metadata if not provided
    if title is None:
        meta_titles = book.get_metadata("DC", "title")
        title = meta_titles[0][0] if meta_titles else path.stem

    parts: list[str] = []
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        html_bytes = item.get_content()
        html_str = html_bytes.decode("utf-8", errors="replace")
        extractor = _HTMLTextExtractor()
        extractor.feed(html_str)
        text = extractor.get_text().strip()
        if text:
            parts.append(text)

    raw_text = "\n\n".join(parts)
    if not raw_text.strip():
        raise EmptyTextError(f"EPUB contains no readable text: {path}")

    return BookText(title=title, raw_text=raw_text, encoding="utf-8")


class _HTMLTextExtractor(HTMLParser):
    """Minimal HTML → plain-text extractor (no external dependencies).

    Block-level elements (p, h1-h6, div, li, blockquote, …) emit \\n\\n
    so that the paragraph chunker can split on blank lines.
    Inline <br> emits a single \\n.
    """

    _SKIP_TAGS = frozenset(["script", "style", "head", "meta", "link"])
    _BLOCK_TAGS = frozenset([
        "p", "div", "h1", "h2", "h3", "h4", "h5", "h6",
        "li", "blockquote", "section", "article", "tr", "td", "th",
    ])

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        elif tag == "br" and self._skip_depth == 0:
            self._parts.append("\n")
        elif tag in self._BLOCK_TAGS and self._skip_depth == 0:
            self._parts.append("\n\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in self._BLOCK_TAGS and self._skip_depth == 0:
            self._parts.append("\n\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._parts.append(data)

    def get_text(self) -> str:
        import re
        # Join without separator; block tags already inserted \n\n
        text = "".join(self._parts)
        # Collapse runs of spaces/tabs within each line, preserve newlines
        text = re.sub(r"[^\S\n]+", " ", text)
        # Normalise multiple blank lines to a single blank line
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
