"""Load plain-text, EPUB, PDF, and URL sources into BookText objects.

Supported formats:
  .txt   — UTF-8 / latin-1 / cp1252 with automatic fallback
  .epub  — extracted via ebooklib + HTML tag stripping
  .pdf   — extracted via PyMuPDF (pymupdf)
  URL    — fetched via requests; HTML stripped or trafilatura if available
"""

import re
from html.parser import HTMLParser
from pathlib import Path

from bookscope.models import BookText


class EmptyTextError(ValueError):
    """Raised when the loaded file contains no usable text."""


FALLBACK_ENCODINGS = ["utf-8", "latin-1", "cp1252"]


def load_text(path: Path | str, title: str | None = None) -> BookText:
    """Read a .txt, .epub, or .pdf file and return a BookText.

    Dispatches to the appropriate loader based on file extension.

    Args:
        path: Path to the .txt, .epub, or .pdf file.
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
    if suffix == ".pdf":
        return _load_pdf(path, title)
    if suffix in (".txt", ""):
        return _load_txt(path, title)
    raise ValueError(f"Unsupported file type: {suffix!r}. Supported: .txt, .epub, .pdf")


def load_url(url: str, title: str | None = None) -> BookText:
    """Fetch a URL and return a BookText.

    Handles plain-text and HTML responses. HTML is cleaned via trafilatura
    (if installed) or the built-in _HTMLTextExtractor as a fallback.

    Args:
        url: HTTP/HTTPS URL to fetch.
        title: Display title. Defaults to the page <title> tag or the URL path.

    Raises:
        ImportError: If requests is not installed.
        EmptyTextError: If the URL returns no readable text.
        requests.HTTPError: If the server returns a non-2xx status.
    """
    try:
        import requests
    except ImportError as exc:
        raise ImportError(
            "requests is required for URL support. "
            "Install it with: pip install requests"
        ) from exc

    response = requests.get(
        url,
        timeout=20,
        headers={"User-Agent": "BookScope/0.2 (+https://github.com/bookscope)"},
    )
    response.raise_for_status()

    content_type = response.headers.get("content-type", "")

    if "text/plain" in content_type:
        raw_text = response.text
        if title is None:
            title = url.rstrip("/").rsplit("/", 1)[-1] or url
    else:
        html = response.text
        if title is None:
            m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
            title = m.group(1).strip() if m else (url.rstrip("/").rsplit("/", 1)[-1] or url)
        raw_text = _extract_html_text(html)

    if not raw_text.strip():
        raise EmptyTextError(f"URL returned no readable text: {url}")

    return BookText(title=title, raw_text=raw_text)


# ---------------------------------------------------------------------------
# Private loaders
# ---------------------------------------------------------------------------

def _load_pdf(path: Path, title: str | None) -> BookText:
    """Extract plain text from a PDF file via PyMuPDF."""
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise ImportError(
            "PyMuPDF is required for PDF support. "
            "Install it with: pip install pymupdf"
        ) from exc

    doc = fitz.open(str(path))

    if title is None:
        meta_title = (doc.metadata or {}).get("title", "").strip()
        title = meta_title or path.stem

    parts: list[str] = []
    for page in doc:
        text = page.get_text("text")
        if text.strip():
            parts.append(text.strip())
    doc.close()

    raw_text = "\n\n".join(parts)
    if not raw_text.strip():
        raise EmptyTextError(f"PDF contains no readable text: {path}")

    return BookText(title=title, raw_text=raw_text, encoding="utf-8")


def _extract_html_text(html: str) -> str:
    """Extract readable text from HTML.

    Tries trafilatura first (article-quality extraction);
    falls back to _HTMLTextExtractor if not installed.
    """
    try:
        import trafilatura
        text = trafilatura.extract(html, include_comments=False, include_tables=False)
        if text:
            return text
    except ImportError:
        pass

    extractor = _HTMLTextExtractor()
    extractor.feed(html)
    return extractor.get_text()


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
