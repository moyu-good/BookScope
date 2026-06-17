"""Load plain-text, EPUB, PDF, DOCX, Markdown, multi-file series, and URL sources.

Supported formats:
  .txt        — UTF-8 / latin-1 / cp1252 with automatic fallback
  .epub       — extracted via ebooklib + HTML tag stripping
  .pdf        — extracted via PyMuPDF (pymupdf)
  .docx       — extracted via python-docx（正文段落 + 标题样式）
  .md/.markdown — 标准库 + 正则剥 front-matter / 代码栅栏，标题转检测器友好形态
  多文件系列  — 一个文件夹 / 一组文件 → 按文件名数字序拼成一本书（load_series）
  URL         — fetched via requests; HTML stripped or trafilatura if available
"""

import re
from html.parser import HTMLParser
from pathlib import Path

from bookscope.ingest.book_chunker import chinese_numeral_to_int
from bookscope.models import BookText


class EmptyTextError(ValueError):
    """Raised when the loaded file contains no usable text."""


FALLBACK_ENCODINGS = ["utf-8", "latin-1", "cp1252"]


_CJK_CHAR_RE = re.compile(r"[㐀-鿿]")
"""粗略 CJK 表意字符检测（够识别中文书名）。"""

# 全角 ↔ 半角 标点对照。仅在书名含 CJK 字符时把半角及其周围空格归一回全角，
# 保留出版物真实书名形态（如 `安史之乱：历史、宣传与神话`，不被改成
# `安史之乱 : 历史、宣传与神话` —— 后者来自部分 epub 元数据的工具脏污）。
_HALF_TO_FULL_PUNCT = {
    ":": "：",
    ";": "；",
    ",": "，",
    "!": "！",
    "?": "？",
    "(": "（",
    ")": "）",
}


def normalize_book_title(title: str) -> str:
    """归一中文书名里的半角标点为全角，并去掉标点两侧的多余空格。

    设计意图：B-6 修复——anshi epub 元数据存的是 ``安史之乱 : 历史、宣传
    与神话``（半角冒号 + 两侧空格），但出版物真实书名是 ``安史之乱：历史
    、宣传与神话`` 全角冒号无空格。该函数把 epub 元数据兜底回出版物形态。

    规则：
    - 仅当 title 含 CJK 表意字符时启用（英文书名不动）
    - 半角冒号 / 分号 / 逗号 / 感叹 / 问号 / 圆括号转全角
    - 全角标点两侧的 ASCII 空格删掉（``A : B`` → ``A：B``，``A ：B`` → ``A：B``）
    - 多余首尾空白 strip

    幂等：``normalize_book_title(normalize_book_title(x)) == normalize_book_title(x)``。
    """
    if not title:
        return title
    stripped = title.strip()
    if not _CJK_CHAR_RE.search(stripped):
        # 非中文书名（纯英文 / 拉丁脚本）不动——半角标点是它们的本来形态。
        return stripped

    out = stripped
    for half, full in _HALF_TO_FULL_PUNCT.items():
        out = out.replace(half, full)
    # 删掉全角标点两侧的 ASCII 空格（针对 `A ： B` / `A：B ` / ` ：B` 形态）
    full_chars = "".join(_HALF_TO_FULL_PUNCT.values()) + "、。"
    out = re.sub(rf"\s*([{full_chars}])\s*", r"\1", out)
    return out


def load_text(path: Path | str, title: str | None = None) -> BookText:
    """Read a single book file and return a BookText.

    Dispatches to the appropriate loader based on file extension.
    支持 .txt / .epub / .pdf / .docx / .md / .markdown。多文件系列走
    :func:`load_series`。

    Args:
        path: Path to the source file.
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
    if suffix == ".docx":
        return _load_docx(path, title)
    if suffix in (".md", ".markdown"):
        return _load_markdown(path, title)
    if suffix in (".txt", ""):
        return _load_txt(path, title)
    raise ValueError(
        f"Unsupported file type: {suffix!r}. "
        "Supported: .txt, .epub, .pdf, .docx, .md, .markdown"
    )


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
# 多文件系列：一组分章文件 → 一本连续的书
# ---------------------------------------------------------------------------

# 单文件可作系列成员的后缀（系列里不混 epub/pdf——它们自带章节结构，不靠文件分隔）
_SERIES_MEMBER_SUFFIXES = frozenset({".txt", ".md", ".markdown", ".docx", ""})


def load_series(
    source: Path | str | list[Path | str],
    title: str | None = None,
) -> BookText:
    """把一组分章文件按文件名**数字序**拼成一本连续的书。

    网文连载的常态是几十上百个分章文件（``第001章.txt``、``第002章.txt`` …），
    要当**一本书**处理而不是几十本散文件。每个文件 = 一章，**章节边界由文件
    给定**，不靠正则猜——这比单文件靠 ``_CHAPTER_RE`` 猜更可靠。

    Args:
        source: 一个文件夹路径（取其中所有受支持成员文件），或一组文件路径。
        title: 书名。默认取文件夹名 / 第一个文件所在目录名。

    排序：按文件名里的数字（阿拉伯 / 全角 / 中文数字，复用
    ``chinese_numeral_to_int``）做**数字感知排序**——``第10章`` 排在 ``第2章``
    之后，不按字典序。解析不出数字的文件按文件名字典序排到末尾（保持稳定）。

    章号：每个文件边界处合成一行 ``第N章 <文件名>`` 标题。N 取文件名里解析出的
    数字；同一组里所有文件都解析不出数字时，回退用 1-based 位置序号。合成标题交给
    下游 ``detect_chapters`` 用现有 ``_CHAPTER_RE`` 识别——**不动正则**。章号准确性
    是这件事对 evidence-first 的全部责任。

    Raises:
        FileNotFoundError: source 不存在 / 文件夹里没有受支持的成员文件。
        EmptyTextError: 所有成员文件都没有可用文本。
        ValueError: source 是空列表。
    """
    files = _collect_series_files(source)

    # 解析每个文件的文件名数字（用于排序 + 章号）
    indexed: list[tuple[int | None, str, Path]] = []
    for f in files:
        num = _filename_to_number(f.stem)
        indexed.append((num, f.name, f))

    # 数字感知排序：有数字的按数字升序在前，无数字的按文件名字典序排末尾
    indexed.sort(key=lambda t: (t[0] is None, t[0] if t[0] is not None else 0, t[1]))

    any_number = any(num is not None for num, _, _ in indexed)

    parts: list[str] = []
    loaded_any = False
    for position, (num, _name, f) in enumerate(indexed, start=1):
        try:
            member = load_text(f)
        except EmptyTextError:
            continue  # 跳过空成员，不让一章空把整本书拖崩
        loaded_any = True
        # 章号：优先文件名数字；整组都无数字才回退位置序号
        chapter_no = num if (any_number and num is not None) else position
        heading = f"第{chapter_no}章 {f.stem}"
        parts.append(f"{heading}\n{member.raw_text.strip()}")

    if not loaded_any:
        raise EmptyTextError(f"No readable text in series: {source}")

    raw_text = "\n\n".join(parts)
    final_title = normalize_book_title(title or _series_default_title(source, files))
    return BookText(title=final_title, raw_text=raw_text, encoding="utf-8")


def _collect_series_files(source: Path | str | list[Path | str]) -> list[Path]:
    """把 source 归一成一个受支持的成员文件列表（未排序）。"""
    if isinstance(source, list):
        if not source:
            raise ValueError("load_series got an empty file list")
        files = [Path(p) for p in source]
        for f in files:
            if not f.exists():
                raise FileNotFoundError(f"Series member not found: {f}")
        return [f for f in files if f.suffix.lower() in _SERIES_MEMBER_SUFFIXES]

    root = Path(source)
    if not root.exists():
        raise FileNotFoundError(f"Series source not found: {root}")
    if root.is_dir():
        members = [
            p
            for p in root.iterdir()
            if p.is_file() and p.suffix.lower() in _SERIES_MEMBER_SUFFIXES
        ]
        if not members:
            raise FileNotFoundError(f"No supported series files in directory: {root}")
        return members
    # 单个文件当成一元系列
    return [root]


_FILENAME_NUM_RE = re.compile(rf"([0-9０-９]+|[{'一二三四五六七八九十百千万零〇两'}]+)")


def _filename_to_number(stem: str) -> int | None:
    """从文件名（去后缀）里抽出章号数字；抽不出返回 None。

    ``第012章`` → 12、``chapter_5`` → 5、``第十二回`` → 12。取文件名里第一个能解析
    成数字的串（阿拉伯 / 全角 / 中文数字均可）。
    """
    for token in _FILENAME_NUM_RE.findall(stem):
        n = chinese_numeral_to_int(token)
        if n is not None:
            return n
    return None


def _series_default_title(
    source: Path | str | list[Path | str], files: list[Path]
) -> str:
    """系列书名兜底：文件夹名 > 成员文件的公共父目录名。"""
    if not isinstance(source, list):
        root = Path(source)
        if root.is_dir():
            return root.name
    if files:
        return files[0].parent.name or files[0].stem
    return "series"


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
    title = normalize_book_title(title)

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

    final_title = title or path.stem
    final_title = normalize_book_title(final_title)
    return BookText(title=final_title, raw_text=raw_text, encoding=used_encoding)


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

    # 书名优先取 epub 内容元数据（DC:title）——这是出版物真名；传进来的 title
    # 多半是文件名（上传表单按文件名自动填的），不如内容里的真书名。元数据缺失
    # 才退回传入 title / 文件名。2026-06-16 作者反馈"书名该从内容提取不是文件名"。
    meta_titles = book.get_metadata("DC", "title")
    meta_title = (
        str(meta_titles[0][0]).strip()
        if meta_titles and meta_titles[0] and meta_titles[0][0]
        else None
    )
    title = normalize_book_title(meta_title or title or path.stem)

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


def _load_docx(path: Path, title: str | None) -> BookText:
    """Extract plain text from a .docx file via python-docx.

    取每个段落的纯文本，段落之间留空行（``\\n\\n``）让切块器按段切。Word 的
    章标题常靠**样式**（Heading 1/2）而非文字 ``第X章``——标题段落原样保留成
    独立行：若标题文字本身就是 ``第X章`` / ``Chapter N``，现有 ``_CHAPTER_RE``
    自然认得；纯样式标题（无章节字样）保留为短独立行，至少守住段落边界，不
    凭空编造章号（章号错下游 evidence-first 全错，宁缺毋滥）。

    Word 的核心稿件信号是段落文本；表格 / 页眉页脚 / 图片不当正文塞进来。
    """
    try:
        import docx  # python-docx
    except ImportError as exc:
        raise ImportError(
            "python-docx is required for .docx support. "
            "Install it with: pip install python-docx"
        ) from exc

    document = docx.Document(str(path))

    if title is None:
        meta_title = (document.core_properties.title or "").strip()
        title = meta_title or path.stem
    title = normalize_book_title(title)

    parts: list[str] = []
    for para in document.paragraphs:
        text = para.text.strip()
        if text:
            parts.append(text)

    raw_text = "\n\n".join(parts)
    if not raw_text.strip():
        raise EmptyTextError(f"DOCX contains no readable text: {path}")

    return BookText(title=title, raw_text=raw_text, encoding="utf-8")


# Markdown 预处理用的正则（纯标准库，不引 markdown 渲染库）
_MD_FRONT_MATTER_RE = re.compile(r"\A---\r?\n.*?\r?\n---\r?\n", re.DOTALL)
_MD_CODE_FENCE_RE = re.compile(r"^\s*(```|~~~).*$", re.MULTILINE)
_MD_ATX_HEADING_RE = re.compile(r"^[ \t]{0,3}(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$", re.MULTILINE)


def _load_markdown(path: Path, title: str | None) -> BookText:
    """Load a Markdown file as plain text, chapter-detector friendly.

    Markdown 本就是文本，纯正则处理即可，不引渲染库：

    - 剥掉文件开头的 YAML front-matter（``---`` ... ``---``）——它是元数据不是正文；
    - 把 ATX 标题（``# 第三章`` / ``## 楔子``）的 ``#`` 标记去掉，只留标题文字成
      独立行——``第X章`` 字样会被现有 ``_CHAPTER_RE`` 认出，纯文字标题也守住段落边界，
      不动正则、不碰所有书；
    - 代码栅栏标记（``` ``` ``` / ``~~~``）去掉，但**保留栅栏内代码内容**（技术书的
      代码是正文的一部分，网文不会有，默认保留）。

    其余 Markdown 语法（加粗 / 链接等）保持原样——它们是行内文本，不影响章节切分。
    """
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

    processed = _strip_markdown_scaffolding(raw_text)
    if not processed.strip():
        raise EmptyTextError(f"Markdown file is empty or contains only whitespace: {path}")

    final_title = normalize_book_title(title or path.stem)
    return BookText(title=final_title, raw_text=processed, encoding=used_encoding)


def _strip_markdown_scaffolding(text: str) -> str:
    """剥 front-matter / 栅栏标记，把 ATX 标题降成纯文字独立行。"""
    # 1. front-matter 仅在文件最开头才算（行内 "---" 是分隔线，不动）
    text = _MD_FRONT_MATTER_RE.sub("", text)
    # 2. 去掉代码栅栏行本身，保留栅栏内代码内容
    text = _MD_CODE_FENCE_RE.sub("", text)
    # 3. ATX 标题：去掉前导 #，保留标题文字（让 _CHAPTER_RE 能认 "第X章" 字样）
    text = _MD_ATX_HEADING_RE.sub(lambda m: m.group(2).strip(), text)
    return text


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
