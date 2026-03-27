"""Unit tests for bookscope.ingest.loader."""

import io
import zipfile
from pathlib import Path  # noqa: F401  (used in type annotation)
from unittest.mock import MagicMock, patch

import pytest

from bookscope.ingest.loader import EmptyTextError, load_text, load_url

# ---------------------------------------------------------------------------
# EPUB helpers
# ---------------------------------------------------------------------------

def _make_epub(tmp_path, body_html: str, dc_title: str | None = None) -> "Path":
    """Build a minimal but valid EPUB 2 file for testing."""
    epub_path = tmp_path / "test.epub"
    dc_title_xml = (
        f'<dc:title xmlns:dc="http://purl.org/dc/elements/1.1/">{dc_title}</dc:title>'
        if dc_title
        else ""
    )
    container_xml = (
        '<?xml version="1.0"?>'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles>'
        '<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
        '</rootfiles>'
        '</container>'
    )
    opf_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="uid">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        '<dc:identifier id="uid">urn:uuid:test-123</dc:identifier>'
        f'{dc_title_xml}'
        '</metadata>'
        '<manifest>'
        '<item id="chapter1" href="chapter1.html" media-type="application/xhtml+xml"/>'
        '</manifest>'
        '<spine><itemref idref="chapter1"/></spine>'
        '</package>'
    )
    chapter_html = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<!DOCTYPE html>'
        '<html><head><title>Chapter</title></head>'
        f'<body>{body_html}</body>'
        '</html>'
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", container_xml)
        zf.writestr("OEBPS/content.opf", opf_xml)
        zf.writestr("OEBPS/chapter1.html", chapter_html)
    epub_path.write_bytes(buf.getvalue())
    return epub_path


def test_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_text(tmp_path / "nonexistent.txt")


def test_empty_file_raises(tmp_path):
    f = tmp_path / "empty.txt"
    f.write_text("   \n  \t  ", encoding="utf-8")
    with pytest.raises(EmptyTextError):
        load_text(f)


def test_load_utf8(tmp_path):
    f = tmp_path / "book.txt"
    f.write_text("Hello world", encoding="utf-8")
    bt = load_text(f)
    assert bt.raw_text == "Hello world"
    assert bt.encoding == "utf-8"
    assert bt.title == "book"


def test_explicit_title(tmp_path):
    f = tmp_path / "book.txt"
    f.write_text("x", encoding="utf-8")
    bt = load_text(f, title="My Title")
    assert bt.title == "My Title"


def test_load_latin1(tmp_path):
    f = tmp_path / "latin.txt"
    content = "caf\xe9"  # 'café' in latin-1
    f.write_bytes(content.encode("latin-1"))
    bt = load_text(f)
    assert "caf" in bt.raw_text


def test_unsupported_extension_raises(tmp_path):
    f = tmp_path / "book.docx"
    f.write_bytes(b"PK\x03\x04")
    with pytest.raises(ValueError, match="Unsupported file type"):
        load_text(f)


# ---------------------------------------------------------------------------
# EPUB tests (require ebooklib)
# ---------------------------------------------------------------------------

pytest.importorskip("ebooklib", reason="ebooklib not installed")


def test_epub_loads_text(tmp_path):
    epub = _make_epub(tmp_path, "<p>Hello EPUB world</p>")
    bt = load_text(epub)
    assert "Hello EPUB world" in bt.raw_text
    assert bt.encoding == "utf-8"


def test_epub_uses_dc_title(tmp_path):
    epub = _make_epub(tmp_path, "<p>Some text</p>", dc_title="My Great Novel")
    bt = load_text(epub)
    assert bt.title == "My Great Novel"


def test_epub_falls_back_to_stem_when_no_dc_title(tmp_path):
    epub = _make_epub(tmp_path, "<p>Some text</p>", dc_title=None)
    bt = load_text(epub)
    assert bt.title == "test"  # stem of test.epub


def test_epub_explicit_title_overrides_metadata(tmp_path):
    epub = _make_epub(tmp_path, "<p>Some text</p>", dc_title="Metadata Title")
    bt = load_text(epub, title="Override Title")
    assert bt.title == "Override Title"


def test_epub_strips_script_tags(tmp_path):
    epub = _make_epub(tmp_path, "<script>alert('x')</script><p>Clean text</p>")
    bt = load_text(epub)
    assert "alert" not in bt.raw_text
    assert "Clean text" in bt.raw_text


def test_epub_strips_style_tags(tmp_path):
    epub = _make_epub(tmp_path, "<style>body{color:red}</style><p>Visible</p>")
    bt = load_text(epub)
    assert "color" not in bt.raw_text
    assert "Visible" in bt.raw_text


def test_epub_block_tags_produce_paragraph_breaks(tmp_path):
    """Paragraph chunker needs \\n\\n between <p> elements."""
    epub = _make_epub(tmp_path, "<p>First paragraph.</p><p>Second paragraph.</p>")
    bt = load_text(epub)
    assert "\n\n" in bt.raw_text


def test_epub_multiple_paragraphs_are_individually_chunkable(tmp_path):
    """Each <p> should become a separate chunk when paragraphs are long enough."""
    from bookscope.ingest.chunker import chunk

    body = "".join(f"<p>{'word ' * 30}paragraph {i}.</p>" for i in range(5))
    epub = _make_epub(tmp_path, body)
    bt = load_text(epub)
    chunks = chunk(bt, strategy="paragraph", min_words=10)
    assert len(chunks) >= 3


def test_epub_br_tag_becomes_newline(tmp_path):
    """<br> inside a paragraph should produce a newline in the extracted text."""
    epub = _make_epub(tmp_path, "<p>Line one<br/>Line two</p>")
    bt = load_text(epub)
    assert "\n" in bt.raw_text


def test_epub_empty_content_raises(tmp_path):
    """An EPUB with no readable text should raise EmptyTextError."""
    epub = _make_epub(tmp_path, "<p>   </p>")
    with pytest.raises(EmptyTextError):
        load_text(epub)


# ---------------------------------------------------------------------------
# PDF tests (require pymupdf / fitz)
# ---------------------------------------------------------------------------

fitz = pytest.importorskip("fitz", reason="pymupdf not installed")


def _make_pdf(tmp_path, text: str, title: str | None = None) -> Path:
    """Create a minimal single-page PDF containing the given text."""
    pdf_path = tmp_path / "test.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text, fontsize=12)
    if title:
        doc.set_metadata({"title": title})
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def test_pdf_loads_text(tmp_path):
    pdf = _make_pdf(tmp_path, "Hello PDF world")
    bt = load_text(pdf)
    assert "Hello PDF world" in bt.raw_text
    assert bt.encoding == "utf-8"


def test_pdf_uses_metadata_title(tmp_path):
    pdf = _make_pdf(tmp_path, "Some text", title="My Great Book")
    bt = load_text(pdf)
    assert bt.title == "My Great Book"


def test_pdf_falls_back_to_stem_when_no_title(tmp_path):
    pdf = _make_pdf(tmp_path, "Some text", title=None)
    bt = load_text(pdf)
    assert bt.title == "test"


def test_pdf_explicit_title_overrides_metadata(tmp_path):
    pdf = _make_pdf(tmp_path, "Some text", title="Metadata Title")
    bt = load_text(pdf, title="Override")
    assert bt.title == "Override"


def test_pdf_multipage(tmp_path):
    """Text from all pages should be present."""
    pdf_path = tmp_path / "multi.pdf"
    doc = fitz.open()
    for i in range(3):
        page = doc.new_page()
        page.insert_text((72, 72), f"Page {i} content here", fontsize=12)
    doc.save(str(pdf_path))
    doc.close()

    bt = load_text(pdf_path)
    for i in range(3):
        assert f"Page {i}" in bt.raw_text


def test_pdf_empty_raises(tmp_path):
    """A PDF with no text content should raise EmptyTextError."""
    pdf_path = tmp_path / "blank.pdf"
    doc = fitz.open()
    doc.new_page()  # blank page, no text
    doc.save(str(pdf_path))
    doc.close()

    with pytest.raises(EmptyTextError):
        load_text(pdf_path)


# ---------------------------------------------------------------------------
# URL tests (require requests; use mocks — no network calls in tests)
# ---------------------------------------------------------------------------

pytest.importorskip("requests", reason="requests not installed")


def _mock_response(text: str, content_type: str = "text/html; charset=utf-8") -> MagicMock:
    resp = MagicMock()
    resp.text = text
    resp.headers = {"content-type": content_type}
    resp.raise_for_status = MagicMock()
    return resp


def test_url_plain_text(tmp_path):
    with patch("requests.get", return_value=_mock_response(
        "Hello URL world", content_type="text/plain"
    )):
        bt = load_url("http://example.com/book.txt")
    assert "Hello URL world" in bt.raw_text


def test_url_plain_text_title_from_path():
    with patch("requests.get", return_value=_mock_response(
        "Some text", content_type="text/plain"
    )):
        bt = load_url("http://example.com/my-novel.txt")
    assert bt.title == "my-novel.txt"


def test_url_explicit_title_overrides():
    with patch("requests.get", return_value=_mock_response(
        "Some text", content_type="text/plain"
    )):
        bt = load_url("http://example.com/book.txt", title="Override")
    assert bt.title == "Override"


def test_url_html_extracts_text():
    html = "<html><head><title>Test Page</title></head><body><p>Article content here.</p></body></html>"
    with patch("requests.get", return_value=_mock_response(html)):
        bt = load_url("http://example.com/article")
    assert "Article content" in bt.raw_text


def test_url_html_title_from_title_tag():
    html = "<html><head><title>My Article</title></head><body><p>Content.</p></body></html>"
    with patch("requests.get", return_value=_mock_response(html)):
        bt = load_url("http://example.com/article")
    assert bt.title == "My Article"


def test_url_empty_response_raises():
    with patch("requests.get", return_value=_mock_response("   ", content_type="text/plain")):
        with pytest.raises(EmptyTextError):
            load_url("http://example.com/empty.txt")


def test_url_http_error_propagates():
    import requests

    resp = MagicMock()
    resp.raise_for_status.side_effect = requests.HTTPError("404")
    with patch("requests.get", return_value=resp):
        with pytest.raises(requests.HTTPError):
            load_url("http://example.com/notfound")
