"""Three-layer book chunker for long-form novels.

Designed for Chinese novels (50万字+) where paragraph-level chunking
produces 25K+ tiny fragments.  Implements a hierarchical approach:

    Layer 1 — Chapter detection (regex on 第X章/回/节)
    Layer 2 — Merge consecutive paragraphs into ~1500-char semantic chunks
    Layer 3 — Contextual headers prepended to each chunk

Result: 25K paragraphs → ~200-400 chunks, each with rich context.

References:
    - NVIDIA 2024 Benchmark: analytical questions need 1024+ tokens
    - Vectara NAACL 2025: context cliff at ~2500 tokens
    - Anthropic Contextual Retrieval: chunk headers reduce retrieval failure 67%
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from bookscope.ingest.cleaner import clean
from bookscope.models import BookText, ChunkResult

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CHUNK_CHAR_TARGET = 1500   # target chars per chunk (~800 tokens for Chinese)
CHUNK_CHAR_MIN = 300       # don't emit chunks shorter than this
CHUNK_CHAR_MAX = 3000      # hard cap (~1500 tokens, below context cliff)
OVERLAP_CHARS = 150        # ~10% overlap for continuity

# --- WP3 Phase A 告警阈值（启发式常量，跑过真书数据后再调）-----------------

NO_CHAPTER_WARN_MIN_BOOK_CHARS = 50_000
"""全书超过这个字数还检出 ≤ 1 章 → 检测大概率失效（无章节书 / 格式怪）。"""

COARSE_CHAPTER_WARN_AVG_CHARS = 100_000
"""平均章字数超过这个值 → 章切得太粗，章号对定位帮助有限。"""

OVERDETECTION_WARN_MAX_CHAPTERS = 3_000
"""检出章数超过这个值 → 大概率把正文里的列表项（"(1)" 类）当章节头了。"""

WARN_NO_CHAPTERS = "no_chapters_detected"
WARN_TOO_COARSE = "chapters_too_coarse"
WARN_OVERDETECTION = "suspicious_overdetection"
WARN_PARSE_INCONSISTENT = "parse_inconsistent"
WARN_TOC_STRIPPED = "toc_headings_stripped"

# Chinese chapter / volume heading patterns（WP3 Phase B 重构）
#
# 与旧版的两个差异：
# 1. 第X部/篇/卷、卷X 从"章节头"挪到"卷头"——分卷标记只计数不占章节号；
# 2. 章节头带命名捕获组抽出数字串，给真章号解析用。
_CN_NUM_CLASS = "一二三四五六七八九十百千万零〇两"

_CHAPTER_RE = re.compile(
    rf"^(?:"
    rf"(?P<zh_chapter>第(?P<zh_chapter_num>[{_CN_NUM_CLASS}\d]+)[章回节])"
    rf"|(?P<en_chapter>(?:Chapter|CHAPTER)\s+(?P<en_chapter_num>\d+))"
    rf"|(?P<zh_volume>第[{_CN_NUM_CLASS}\d]+[部篇卷]|卷[{_CN_NUM_CLASS}\d]+)"
    rf"|(?P<pian_volume>[上中下]篇)"
    rf"|(?P<paren_chapter>[（(](?P<paren_chapter_num>\d+)[)）])"
    rf")",
    re.MULTILINE,
)

# Chinese sentence-ending / clause-ending punctuation for splitting
# Includes full stops, exclamation, question, semicolons, colons, ellipsis, commas
_CN_SENT_END = re.compile(r"(?<=[。！？；：…\u2026，、\n])")


# ---------------------------------------------------------------------------
# WP3 Phase A: 章节检测质量观测
# ---------------------------------------------------------------------------


@dataclass
class ChapterDetectionStats:
    """一次章节检测的质量指标（WP3 Phase A）。

    citation 的 chapter 字段是作家定位修改的唯一坐标，检测质量必须可观测：
    漏检 / 过检 / 章号解析失败都要在这里留下数字，而不是等用户拿着错章号
    回来报 bug。``warnings`` 里的字符串是机器可比对的告警码（``WARN_*``
    常量），upload 响应与 session 元数据原样透出。
    """

    chapters_detected: int = 0
    """检出的章节头数量（不含合成的"序"章，不含卷头）。"""

    parse_success_rate: float = 0.0
    """章节头里解析出真章号的比例；0 个章节头时为 0.0。"""

    avg_chapter_chars: float = 0.0
    """平均章正文字符数（按最终返回的章节列表算，含序章）。"""

    max_chapter_chars: int = 0
    """最长一章的正文字符数。"""

    pattern_hits: dict[str, int] = field(default_factory=dict)
    """各正则模式族的命中次数（zh_chapter / en_chapter / paren_chapter /
    zh_volume / pian_volume）。"""

    warnings: list[str] = field(default_factory=list)
    """命中的告警码列表；空列表 = 检测看起来正常。"""

    volume_markers_found: int = 0
    """识别到的分卷标记数（卷X / 第X部 / 第X篇 / 上中下篇）。"""

    def to_dict(self) -> dict:
        """转 JSON 友好的 dict，给 API 响应 / 元数据落盘用。"""
        return asdict(self)


# ---------------------------------------------------------------------------
# WP3 Phase B: 中文数字转换（纯标准库）
# ---------------------------------------------------------------------------

_CN_DIGIT = {
    "零": 0, "〇": 0,
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}
_CN_UNIT_SMALL = {"十": 10, "百": 100, "千": 1000}


def chinese_numeral_to_int(token: str) -> int | None:
    """把章节头里的数字串转成 int；转不动返回 ``None``。

    支持三种形态：
    - 阿拉伯数字（含全角）：``"42"`` / ``"４２"`` → 42
    - 中文数字：``"四百二十"`` → 420、``"一千零一"`` → 1001、``"两百三十"``
      → 230、``"十"`` → 10、``"二十三"`` → 23
    - 万段：``"一万两千"`` → 12000

    不支持的字符（非数字非单位）直接返回 ``None``——调用方按解析失败回退
    检测序号，绝不猜。
    """
    token = token.strip()
    if not token:
        return None
    if token.isdigit():
        # int() 原生吃全角数字
        return int(token)

    total = 0      # 已结算的万段
    section = 0    # 当前万段内已结算的十/百/千
    digit = 0      # 待结算的个位
    for ch in token:
        if ch in _CN_DIGIT:
            digit = _CN_DIGIT[ch]
        elif ch in _CN_UNIT_SMALL:
            # "十" 单独出现按 1 个十算（十=10、十三=13）
            section += (digit or 1) * _CN_UNIT_SMALL[ch]
            digit = 0
        elif ch == "万":
            total += (section + digit) * 10_000
            section = 0
            digit = 0
        else:
            return None
    return total + section + digit


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def chunk_book(
    book: BookText,
    chunk_target: int = CHUNK_CHAR_TARGET,
    chunk_min: int = CHUNK_CHAR_MIN,
    overlap: int = OVERLAP_CHARS,
) -> list[ChunkResult]:
    """Split a book into semantically coherent chunks with chapter context.

    Returns a list of ``ChunkResult`` with contextual headers.

    向后兼容入口——签名与返回不变；要拿检测质量指标用
    :func:`chunk_book_with_stats`。
    """
    results, _stats = chunk_book_with_stats(book, chunk_target, chunk_min, overlap)
    return results


def chunk_book_with_stats(
    book: BookText,
    chunk_target: int = CHUNK_CHAR_TARGET,
    chunk_min: int = CHUNK_CHAR_MIN,
    overlap: int = OVERLAP_CHARS,
) -> tuple[list[ChunkResult], ChapterDetectionStats]:
    """同 :func:`chunk_book`，额外返回章节检测质量指标（WP3 Phase A）。"""
    text = clean(book.raw_text)
    lang = getattr(book, "language", "en")
    title = book.title

    # Layer 1: detect chapters
    chapters, stats = detect_chapters_with_stats(text)

    # Layer 2+3: merge paragraphs within chapters + add headers
    results: list[ChunkResult] = []
    for ch_num, ch_title, ch_text in chapters:
        header = _build_header(title, ch_num, ch_title)
        chunks = _merge_paragraphs(ch_text, chunk_target, chunk_min, overlap, lang)
        for chunk_text in chunks:
            full_text = f"{header}\n{chunk_text}" if header else chunk_text
            wc = _char_count(full_text, lang)
            results.append(ChunkResult(
                index=len(results),
                text=full_text,
                word_count=wc,
                chapter=ch_num,
            ))

    return results, stats


# ---------------------------------------------------------------------------
# Layer 1: Chapter detection
# ---------------------------------------------------------------------------

_MAX_HEADING_LINE_LEN = 60  # chapter heading lines should be short
_PAREN_HEADING_MAX_LINE_LEN = 40  # "(1)" 类章节头的行长上限（WP3 收紧）


def detect_chapters(text: str) -> list[tuple[int, str, str]]:
    """Split text into ``(chapter_number, chapter_title, chapter_body)`` tuples.

    Public helper — the single official entry point for chapter detection
    used by ``chunk_book``, ``R0BookAssembler`` (the r1 assembly layer),
    and any future caller that needs per-chapter text without building a
    full chunk list (e.g. a KG extractor that batches by chapter).

    向后兼容入口——返回形态不变；要拿检测质量指标用
    :func:`detect_chapters_with_stats`（章节号语义见那边的 docstring）。
    """
    chapters, _stats = detect_chapters_with_stats(text)
    return chapters


def detect_chapters_with_stats(
    text: str,
) -> tuple[list[tuple[int, str, str]], ChapterDetectionStats]:
    """章节检测 + 质量指标（WP3 Phase A 观测 + Phase B 真章号）。

    章节号语义（Phase B 起）：

    - 章节头里解析得出真章号（"第四十二章" → 42、"第42章" → 42、
      "Chapter 7" → 7、独立行 "(3)" → 3）就用真章号——漏检一章不再让
      后面全书错位；
    - 单条解析失败回退该条的检测序号；
    - **单调性守护**：最终章号序列非严格递增（重复 / 倒跳）时整书回退
      检测序号并记 ``parse_inconsistent``——宁可全书统一序号，绝不混用
      两种语义。

    卷头（第X部 / 第X篇 / 卷X / 独立行"上中下篇"）只计入
    ``stats.volume_markers_found``，不进章节列表不占章节号。

    其余行为与旧版一致：无章节头时全文作 1 章返回；首个章节头之前超过
    ``CHUNK_CHAR_MIN`` 的文本作 0 号"序"章；章节头行长须 ≤
    ``_MAX_HEADING_LINE_LEN``（"(1)" 类另收紧为 strip 后整行就是该模式
    且行长 < ``_PAREN_HEADING_MAX_LINE_LEN``）。
    """
    stats = ChapterDetectionStats()
    # (match, 解析出的真章号或 None, line_end)
    heads: list[tuple[re.Match, int | None, int]] = []

    for m in _CHAPTER_RE.finditer(text):
        line_end = text.find("\n", m.start())
        if line_end == -1:
            line_end = len(text)
        line = text[m.start():line_end]
        rest_of_line = line[m.end() - m.start():]

        if m.group("zh_volume") is not None or m.group("pian_volume") is not None:
            # 卷头识别。两条防误判规则：
            # - "上篇/中篇/下篇" 必须独立成行——"上篇说到……"是常见的正文
            #   回顾开头，不能当卷头；
            # - "第X部/篇/卷"、"卷X" 后面必须是行尾或空白（允许带卷名，如
            #   "第一卷 风云再起"）——压掉"第一篇文章里提到"这类正文行。
            if m.group("pian_volume") is not None:
                if rest_of_line.strip():
                    continue
                kind = "pian_volume"
            else:
                if len(line) > _MAX_HEADING_LINE_LEN:
                    continue
                if rest_of_line and not rest_of_line[0].isspace():
                    continue
                kind = "zh_volume"
            stats.volume_markers_found += 1
            stats.pattern_hits[kind] = stats.pattern_hits.get(kind, 0) + 1
            continue

        if m.group("paren_chapter") is not None:
            # WP3 收紧："(1)" 只有 strip 后整行就是该模式且行短才算章节头，
            # 压掉正文里的编号列表项误判（suspicious_overdetection 的主源）。
            if rest_of_line.strip() or len(line) >= _PAREN_HEADING_MAX_LINE_LEN:
                continue
            kind = "paren_chapter"
            num_token: str | None = m.group("paren_chapter_num")
        elif m.group("zh_chapter") is not None:
            if len(line) > _MAX_HEADING_LINE_LEN:
                continue
            kind = "zh_chapter"
            num_token = m.group("zh_chapter_num")
        else:
            if len(line) > _MAX_HEADING_LINE_LEN:
                continue
            kind = "en_chapter"
            num_token = m.group("en_chapter_num")

        parsed: int | None = None
        if num_token:
            n = chinese_numeral_to_int(num_token)
            # 0 与负数不收：0 号是合成"序"章的保留语义
            if n is not None and n >= 1:
                parsed = n
        heads.append((m, parsed, line_end))
        stats.pattern_hits[kind] = stats.pattern_hits.get(kind, 0) + 1

    if not heads:
        stats.avg_chapter_chars = float(len(text))
        stats.max_chapter_chars = len(text)
        _apply_detection_warnings(stats, total_chars=len(text))
        return [(1, "", text)], stats

    # 记原始首个章头位置（序章用），滤目录前定下来
    original_first_head_start = heads[0][0].start()

    # 先算每个章头的 body（到下一个章头之间的正文）
    head_bodies = [
        text[
            line_end + 1 : (heads[i + 1][0].start() if i + 1 < len(heads) else len(text))
        ].strip()
        for i, (_m, _p, line_end) in enumerate(heads)
    ]

    # 滤掉 body 为空的章头——目录条目 / 紧挨着的标题，不是真章节。带目录的书（全二册等）
    # 整列回目会被正则当成成倍的章头、只有正文段才有 body；不滤会触发下面的单调性回退、
    # 把章号摊成 1..2N，全书章号失真（实测三国 120 回被检成 240 章）。
    if any(head_bodies) and not all(head_bodies):
        kept = [(h, b) for h, b in zip(heads, head_bodies, strict=True) if b]
        heads = [h for h, _ in kept]
        head_bodies = [b for _, b in kept]
        stats.warnings.append(WARN_TOC_STRIPPED)

    # Phase B: 真章号 + 单调性守护（在滤掉目录后的真章节上做）
    parsed_ok = sum(1 for _, p, _ in heads if p is not None)
    nums = [p if p is not None else i + 1 for i, (_, p, _) in enumerate(heads)]
    if any(b <= a for a, b in zip(nums, nums[1:])):
        # 重复 / 倒跳——整书回退检测序号，绝不混用两种语义
        nums = list(range(1, len(heads) + 1))
        stats.warnings.append(WARN_PARSE_INCONSISTENT)

    chapters: list[tuple[int, str, str]] = []
    for i, (match, _parsed, line_end) in enumerate(heads):
        ch_title_line = text[match.start():line_end].strip()
        chapters.append((nums[i], ch_title_line, head_bodies[i]))

    # Include any text before the first chapter heading as "prologue"
    prologue = text[:original_first_head_start].strip()
    if prologue and len(prologue) > CHUNK_CHAR_MIN:
        chapters.insert(0, (0, "序", prologue))

    stats.chapters_detected = len(heads)
    stats.parse_success_rate = parsed_ok / len(heads)
    body_lens = [len(body) for _, _, body in chapters]
    stats.avg_chapter_chars = sum(body_lens) / len(body_lens)
    stats.max_chapter_chars = max(body_lens)
    _apply_detection_warnings(stats, total_chars=len(text))

    return chapters, stats


def _apply_detection_warnings(stats: ChapterDetectionStats, *, total_chars: int) -> None:
    """按三条启发式规则给 stats 追加告警码（WP3 Phase A）。"""
    if total_chars > NO_CHAPTER_WARN_MIN_BOOK_CHARS and stats.chapters_detected <= 1:
        stats.warnings.append(WARN_NO_CHAPTERS)
    if stats.avg_chapter_chars > COARSE_CHAPTER_WARN_AVG_CHARS:
        stats.warnings.append(WARN_TOO_COARSE)
    if stats.chapters_detected > OVERDETECTION_WARN_MAX_CHAPTERS:
        stats.warnings.append(WARN_OVERDETECTION)


# ---------------------------------------------------------------------------
# Layer 2: Paragraph merging
# ---------------------------------------------------------------------------

def _merge_paragraphs(
    text: str,
    target: int,
    minimum: int,
    overlap: int,
    lang: str,
) -> list[str]:
    """Merge consecutive paragraphs/sentences into chunks of ~target chars."""
    if not text.strip():
        return []

    # Split into paragraphs first
    paragraphs = re.split(r"\n\n+", text)
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    if not paragraphs:
        return []

    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        # If a single paragraph exceeds max, split it by sentences
        if len(para) > CHUNK_CHAR_MAX:
            # Flush current buffer
            if current.strip():
                chunks.append(current.strip())
                current = ""
            # Split long paragraph by sentence boundaries
            chunks.extend(_split_long_text(para, target, minimum, lang))
            continue

        # Try adding paragraph to current chunk
        candidate = f"{current}\n{para}" if current else para
        if len(candidate) > CHUNK_CHAR_MAX:
            # Current chunk is full, emit it
            if current.strip():
                chunks.append(current.strip())
            # Start new chunk with overlap
            if overlap > 0 and current:
                tail = current[-overlap:]
                current = f"{tail}\n{para}"
            else:
                current = para
        elif len(candidate) >= target:
            # Hit target, emit
            chunks.append(candidate.strip())
            # Overlap for next chunk
            if overlap > 0:
                current = para[-overlap:] if len(para) > overlap else para
            else:
                current = ""
        else:
            current = candidate

    # Flush remainder
    if current.strip():
        if chunks and len(current.strip()) < minimum:
            # Too short — append to last chunk
            chunks[-1] = f"{chunks[-1]}\n{current.strip()}"
        else:
            chunks.append(current.strip())

    return chunks


def _split_long_text(
    text: str,
    target: int,
    minimum: int,
    lang: str,
) -> list[str]:
    """Split a very long paragraph by sentence boundaries."""
    if lang in ("zh", "ja"):
        sentences = _CN_SENT_END.split(text)
    else:
        sentences = re.split(r"(?<=[.!?])\s+", text)

    sentences = [s.strip() for s in sentences if s.strip()]

    chunks: list[str] = []
    current = ""
    for sent in sentences:
        candidate = f"{current}{sent}" if current else sent
        if len(candidate) >= target:
            if current.strip():
                chunks.append(current.strip())
            current = sent
        else:
            current = candidate

    if current.strip():
        if chunks and len(current.strip()) < minimum:
            chunks[-1] += current.strip()
        else:
            chunks.append(current.strip())

    return chunks


# ---------------------------------------------------------------------------
# Layer 3: Contextual headers
# ---------------------------------------------------------------------------

def _build_header(book_title: str, chapter_num: int, chapter_title: str) -> str:
    """Build a contextual header for a chunk."""
    if chapter_num == 0:
        return f"[《{book_title}》序章]"
    if chapter_title:
        return f"[《{book_title}》{chapter_title}]"
    return f"[《{book_title}》第{chapter_num}章]"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _char_count(text: str, lang: str) -> int:
    """Language-aware character/word count."""
    if lang in ("zh", "ja"):
        return len(text.replace(" ", "").replace("\n", "").replace("\t", ""))
    return len(text.split())


# ---------------------------------------------------------------------------
# Backward-compatibility alias
# ---------------------------------------------------------------------------
#
# Historically ``_detect_chapters`` was a private helper.  It became the de
# facto entry point for the r1 assembly layer (``R0BookAssembler``) which
# needs raw ``(chapter_num, title, body)`` tuples without the chunk-list
# wrapping that ``chunk_book`` applies.  The function was promoted to the
# public name :func:`detect_chapters`; this alias is kept so older imports
# (including anything vendored under ``legacy/v7``) keep working.
_detect_chapters = detect_chapters
