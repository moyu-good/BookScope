"""r0 数据装配层：把 r0 的原始产物拼成三个 backend 实例。

本模块是 r1 agent loop **最外一层** 的便利装配器：调用方只要把 r0 那侧
已有的 ``BookText`` / ``list[ChunkResult]`` / ``BookKnowledgeGraph`` /
``SessionVectorStore`` 喂进来，就能一次性拿到三个 backend 实例，省去
手工拼映射的一堆样板代码。

### 为什么要有这一层

三个 r0 backend（``R0SearchChunksBackend`` / ``R0ChapterRangeBackend`` /
``R0ListCharactersBackend``）都要求外部提供"r0 本身不生产"的辅助映射
（chunk→chapter、chunk→characters、章节记录、chapter→characters 等）。
这些映射对所有使用者的构造步骤高度重复，本装配器把它们集中到一个地方，
让 API router / CLI / 测试脚手架不必各自重造一份。

### 依赖说明（docstring 显式标注）

- 本装配层依赖 :func:`bookscope.ingest.book_chunker.detect_chapters`
  这个公共 helper——r0 没有把章节原文做结构化持久化；``detect_chapters``
  是唯一官方入口，返回 ``(chapter_num, chapter_title, chapter_body)``
  三元组。如果未来 r0 改其签名或行为，本装配层需同步调整。
- 本装配层**依赖 chunk text 以 ``[《书名》第X章 标题]`` 或
  ``[《书名》序章]`` header 开头的约定**——这是 r0 ``book_chunker._build_header``
  写入的固定格式。如果 r0 改 header 格式，本装配层的 parse 逻辑需同步。

### 为什么不直接改 r0

副管理不得自行扩 r0 schema（这是代际级改动）。本装配层只做 **wrapping +
推断**，不改任何 r0 代码。chunk→chapter 推断优先走 chunk header parse；
推断失败时回退到按 body offset 反查。
"""

from __future__ import annotations

import re
from typing import Protocol, runtime_checkable

from bookscope.agent.backends.r0_chapter_range import (
    R0ChapterRangeBackend,
    R0ChapterRecord,
)
from bookscope.agent.backends.r0_list_characters import (
    R0ListCharactersBackend,
    build_chapter_character_map,
)
from bookscope.agent.backends.r0_search_chunks import (
    R0SearchChunksBackend,
)
from bookscope.ingest.book_chunker import detect_chapters
from bookscope.ingest.cleaner import clean
from bookscope.models.schemas import (
    BookKnowledgeGraph,
    BookText,
    ChunkResult,
)

# ---------------------------------------------------------------------------
# Header 解析正则
# ---------------------------------------------------------------------------

# r0 ``book_chunker._build_header`` 产出的 header 形态：
# - ``[《书名》序章]``（chapter = 0）
# - ``[《书名》第X章]`` / ``[《书名》第X章 标题]`` / ``[《书名》Chapter X]`` 等。
# header 里的 "第X章" / "Chapter N" 等是 r0 从原文复制来的 ch_title_line，
# 我们从中再抽一次"数字"——本正则只关心中文 "第X章/回/节/篇/卷/部" 或
# "Chapter N" / "CHAPTER N"。
_HEADER_PROLOGUE_RE = re.compile(r"^\[《[^》]+》序章\]")
_HEADER_CHAPTER_NUM_RE = re.compile(
    r"^\[《[^》]+》(?:"
    r"第([一二三四五六七八九十百千零\d]+)[章回节篇卷部]"
    r"|Chapter\s+(\d+)"
    r"|CHAPTER\s+(\d+)"
    r"|卷([一二三四五六七八九十\d]+)"
    r")"
)

# 中文数字 → 阿拉伯数字（覆盖到 "九十九"；书里 chapter 很少超过 999）。
_CN_DIGITS: dict[str, int] = {
    "零": 0, "一": 1, "二": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}


def _cn_to_int(literal: str) -> int | None:
    """把 "第十二章" 里的 "十二" 这种中文数字串转阿拉伯数字。

    支持范围：0-999（足够覆盖绝大多数长篇小说的章节数）。
    纯阿拉伯数字直接 int() 转；纯中文按 "十" / "百" / "千" 分段。

    Returns:
        转换结果；无法解析时返回 None（交由上层回退策略处理）。
    """
    if not literal:
        return None
    # 纯阿拉伯数字
    if literal.isdigit():
        try:
            return int(literal)
        except ValueError:
            return None
    # 中文数字：按 "千百十" 三级展开
    total = 0
    section = 0
    for ch in literal:
        if ch in _CN_DIGITS:
            section = _CN_DIGITS[ch]
        elif ch == "十":
            # "十" 前无数字时隐含 1（"十二" = 12）
            total += section * 10 if section > 0 else 10
            section = 0
        elif ch == "百":
            total += section * 100 if section > 0 else 100
            section = 0
        elif ch == "千":
            total += section * 1000 if section > 0 else 1000
            section = 0
        else:
            return None
    total += section
    return total


# ---------------------------------------------------------------------------
# 可选 vector store 的结构型 Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class _VectorStoreOrNone(Protocol):
    """可选 vector store 参数的结构型 Protocol。

    只要求有 ``search`` 方法，不耦合到具体 ``SessionVectorStore`` 类——
    这样构造测试脚手架时可以喂一个最简替身，不用引入 FAISS 依赖。
    """

    def search(
        self,
        query: str,
        top_k: int = ...,
    ) -> list[tuple[ChunkResult, float]]:
        ...


# ---------------------------------------------------------------------------
# R0BookAssembler
# ---------------------------------------------------------------------------


class R0BookAssembler:
    """把 r0 的原始产物装配成三个 r1 backend 实例。

    典型用法：

    .. code-block:: python

        assembler = R0BookAssembler(
            book_text=book,
            chunks=chunks,
            knowledge_graph=kg,
            session_vector_store=vector_store,  # 可选；None 时 search_chunks 不可用
        )
        bundle = assembler.build_all()
        search_backend = bundle["search"]            # R0SearchChunksBackend | None
        chapter_backend = bundle["chapter_range"]    # R0ChapterRangeBackend
        character_backend = bundle["list_characters"]  # R0ListCharactersBackend

    构造参数:
        book_text: r0 的整本书文本对象（提供 ``raw_text`` / ``title`` / ``language``）。
        chunks: r0 ingest 产物；列表元素 ``index / text / word_count``。
        knowledge_graph: r0 KG 抽取产物；本装配层只用 ``characters`` 字段
            （``key_chapter_indices`` 反推 chunk→characters 映射）。
        session_vector_store: 可选 r0 ``SessionVectorStore``；``None`` 时
            ``build_search_chunks_backend`` 返回 ``None``，另两个 backend
            仍可正常构造——允许上层在还没建好向量索引时先构造出其它
            两个 backend 做轻量 QA。
    """

    def __init__(
        self,
        book_text: BookText,
        chunks: list[ChunkResult],
        knowledge_graph: BookKnowledgeGraph,
        session_vector_store: _VectorStoreOrNone | None = None,
    ) -> None:
        self._book_text = book_text
        self._chunks: list[ChunkResult] = list(chunks)
        self._kg = knowledge_graph
        self._vector_store = session_vector_store

        # 缓存推断结果，避免 build_all 多次 parse。
        self._chunk_to_chapter_cache: dict[int, int] | None = None
        self._chunk_to_characters_cache: dict[int, list[str]] | None = None
        self._chapter_records_cache: list[R0ChapterRecord] | None = None
        self._chapter_character_map_cache: dict[int, list[str]] | None = None

    # ------------------------------------------------------------------
    # 对外便利方法
    # ------------------------------------------------------------------

    def build_all(self) -> dict[str, object]:
        """一次性构造三个 backend 实例。

        Returns:
            ``{"search": R0SearchChunksBackend | None,
               "chapter_range": R0ChapterRangeBackend,
               "list_characters": R0ListCharactersBackend}``。
            ``search`` 在 ``session_vector_store`` 为 ``None`` 时为 ``None``；
            其余两个 backend 总是可用。
        """
        return {
            "search": self.build_search_chunks_backend(),
            "chapter_range": self.build_chapter_range_backend(),
            "list_characters": self.build_list_characters_backend(),
        }

    def build_search_chunks_backend(self) -> R0SearchChunksBackend | None:
        """构造 ``R0SearchChunksBackend``。

        - ``session_vector_store`` 为 ``None`` 但 chunks 非空时——现场建一个
          ``SessionVectorStore`` 兜底（lazy build），救回早期上传时
          ADR-005 留白的旧 session，不强求作者重传。
        - chunks 也空时降级返回 ``None``。
        - 自动推断 ``chunk_index_to_chapter`` 与 ``chunk_index_to_characters``
          两份映射并传入 backend。
        """
        if self._vector_store is None:
            if not self._chunks:
                return None
            from bookscope.store.vector_store import SessionVectorStore

            self._vector_store = SessionVectorStore(
                chunks=self._chunks, enable_vector=True
            )
        return R0SearchChunksBackend(
            self._vector_store,  # type: ignore[arg-type]
            chunk_index_to_chapter=self._compute_chunk_to_chapter_map(),
            chunk_index_to_characters=self._compute_chunk_to_characters_map(),
        )

    def build_chapter_range_backend(self) -> R0ChapterRangeBackend:
        """构造 ``R0ChapterRangeBackend``。

        章节原文通过 ``_compute_chapter_records`` 从 ``book_text.raw_text``
        现场解析得到（不消费 chunks，因为 chunks 的 header 已把 chunk 切散、
        无法无损还原章节原文）。
        """
        return R0ChapterRangeBackend(self._compute_chapter_records())

    def build_list_characters_backend(self) -> R0ListCharactersBackend:
        """构造 ``R0ListCharactersBackend``。

        ``chapter_character_map`` 由 ``build_chapter_character_map`` helper
        从 KG 的 ``characters`` 反推而来。
        """
        return R0ListCharactersBackend(
            character_profiles=list(self._kg.characters),
            chapter_character_map=self._compute_chapter_character_map(),
        )

    # ------------------------------------------------------------------
    # 内部映射推断
    # ------------------------------------------------------------------

    def _compute_chunk_to_chapter_map(self) -> dict[int, int]:
        """推断 ``chunk.index → chapter_num`` 映射。

        策略：优先解析 r0 ``book_chunker._build_header`` 写入 chunk 首行的
        header 字符串（``[《书名》第X章 标题]`` / ``[《书名》序章]``）。
        header 里的数字直接还原为章节号；"序章" 按章节号 0 处理——但这
        违反 ``CharacterRef.chapter`` / ``R0ChapterRecord.chapter`` 的
        ``>= 1`` 约束，因此本装配层把"序"映射为 **章节 1**，并让真 chapter
        1 向后顺延（这是 r0 ``detect_chapters`` 的现有约定的镜像：
        ``chapters.insert(0, (0, "序", prologue))`` 之后再让 agent 层统一 +1）。

        Returns:
            ``{chunk_index: chapter_num}``；解析失败的 chunk 不出现在 map 里
            （调用方看到的效果：``R0SearchChunksBackend`` 会把这些 chunk
            静默跳过——正是"没有章节映射的 chunk 无法被 agent 引用"的
            预期语义）。
        """
        if self._chunk_to_chapter_cache is not None:
            return self._chunk_to_chapter_cache

        # 先算 "r0 detect_chapters 输出的原始 chapter_num 序列 → 标准化
        # chapter 号" 映射：原始 0 号（"序"）在 agent 侧映射为 1，原 1→2，
        # 原 2→3 …… 这样的好处是统一满足 Pydantic schema 的 ``ge=1`` 约束。
        records_raw = self._detect_chapters_raw()
        if not records_raw:
            # 空书：chunk→chapter 没法建，返回空 map（安全降级）。
            self._chunk_to_chapter_cache = {}
            return self._chunk_to_chapter_cache

        has_prologue = records_raw[0][0] == 0
        # 原始 chapter_num → normalized chapter_num 的映射：
        # 有序章时全部 +1；无序章时保持不变。
        raw_to_norm: dict[int, int] = {}
        for raw_num, _title, _body in records_raw:
            raw_to_norm[raw_num] = raw_num + 1 if has_prologue else raw_num

        mapping: dict[int, int] = {}
        for chunk in self._chunks:
            # 优先走新 schema 字段 (``ChunkResult.chapter``)——由新版
            # ``chunk_book`` 填入的是 detect_chapters 的原始章节号
            # (0=序 / 1+=正章)，和本 map 里的 ``raw_to_norm`` 同一口径。
            # 老数据 / 手工构造的 ChunkResult 里 ``chapter=None``，
            # 退回解析 chunk 首行 header 的 regex 路径（保留旧行为）。
            if chunk.chapter is not None:
                raw_num: int | None = chunk.chapter
            else:
                raw_num = _parse_raw_chapter_num_from_chunk_header(chunk.text)
            if raw_num is None:
                continue
            norm = raw_to_norm.get(raw_num)
            if norm is None:
                # 章节号不在 detect_chapters 产出里——
                # 典型原因是 chunk 跨章或 header 被截断；跳过。
                continue
            mapping[chunk.index] = norm

        self._chunk_to_chapter_cache = mapping
        return self._chunk_to_chapter_cache

    def _compute_chunk_to_characters_map(self) -> dict[int, list[str]]:
        """粗粒度推断 ``chunk.index → 角色名列表``。

        策略：利用已计算的 ``chunk→chapter`` map + KG 的
        ``chapter_character_map``——chunk 所属章节出现的所有角色都打到
        这个 chunk 上。这是章节粒度的降级近似：比 chunk 层真 NER 粗得多，
        但是 r0 **根本没做 chunk 层 NER**，这已经是从现有数据能拿到的
        最好近似。

        Returns:
            ``{chunk_index: [canonical_name, ...]}``；该 chunk 所属章节
            无角色时不出现在 map 里（等价于 []）。
        """
        if self._chunk_to_characters_cache is not None:
            return self._chunk_to_characters_cache

        chunk_to_chapter = self._compute_chunk_to_chapter_map()
        chapter_to_chars = self._compute_chapter_character_map()

        mapping: dict[int, list[str]] = {}
        for chunk_index, chapter_num in chunk_to_chapter.items():
            names = chapter_to_chars.get(chapter_num)
            if names:
                mapping[chunk_index] = list(names)
        self._chunk_to_characters_cache = mapping
        return self._chunk_to_characters_cache

    def _compute_chapter_records(self) -> list[R0ChapterRecord]:
        """从 ``book_text.raw_text`` 解析章节原文清单。

        走 :func:`bookscope.ingest.book_chunker.detect_chapters`，再把三元组
        包装成 ``R0ChapterRecord``。章节号按 "原始 0 号序 → 标准化 1 号、原始 1
        号 → 标准化 2 号" 的规则平移，保证所有章节号 >= 1（兑现 Pydantic
        schema 约束）。

        字数按语种计算：中文 / 日文按字符数（去掉空白 / 换行），其余按
        whitespace split。

        Returns:
            按章节号升序的 ``R0ChapterRecord`` 列表；空书返回 ``[]``。
        """
        if self._chapter_records_cache is not None:
            return self._chapter_records_cache

        raw_tuples = self._detect_chapters_raw()
        if not raw_tuples:
            self._chapter_records_cache = []
            return self._chapter_records_cache

        has_prologue = raw_tuples[0][0] == 0
        lang = getattr(self._book_text, "language", "en")

        records: list[R0ChapterRecord] = []
        for raw_num, title, body in raw_tuples:
            if not body or not body.strip():
                # 空章节跳过——``R0ChapterRecord.full_text`` 与底层
                # ``ChapterText.full_text`` 都要求 ``min_length=1``；
                # 空章节只会在 dispatcher 层炸 ValidationError，降级为跳过。
                continue
            norm_num = raw_num + 1 if has_prologue else raw_num
            word_count = _lang_word_count(body, lang)
            records.append(
                R0ChapterRecord(
                    chapter=norm_num,
                    title=title or "",
                    full_text=body,
                    word_count=word_count,
                )
            )
        self._chapter_records_cache = records
        return self._chapter_records_cache

    def _compute_chapter_character_map(self) -> dict[int, list[str]]:
        """构造 ``chapter_num → 角色 name 列表`` 映射。

        直接走 ``build_chapter_character_map`` helper 作用于 KG 的
        ``characters``；不做章节号偏移——KG 的 ``key_chapter_indices``
        本就应该由上层按业务语义填写，本装配层不妄做解释。

        **注意**：如果 KG 的 ``key_chapter_indices`` 使用 "r0 原始章节号"
        （带 0 号序章）而本装配层已经把章节号平移为 "标准化 >= 1" 语义，
        那么角色过滤会出现 off-by-one。实践中 r0 KG 是 LLM 从 chunk
        summary 推断出来的章节号，通常是 **1-based**，所以这里不做偏移
        能对齐大多数场景。偏移一致性由上层调用方保证。
        """
        if self._chapter_character_map_cache is not None:
            return self._chapter_character_map_cache
        self._chapter_character_map_cache = build_chapter_character_map(
            list(self._kg.characters)
        )
        return self._chapter_character_map_cache

    # ------------------------------------------------------------------
    # 内部：调用 r0 公共 helper
    # ------------------------------------------------------------------

    def _detect_chapters_raw(self) -> list[tuple[int, str, str]]:
        """调用 r0 :func:`detect_chapters` 拿到 "(原始章节号, 标题, 原文)" 三元组。

        对 ``raw_text`` 先做 ``clean`` 归一化（和 r0 ``chunk_book`` 内部
        处理路径保持一致，避免正则识别时的换行差异影响章节切分）。
        """
        cleaned = clean(self._book_text.raw_text)
        if not cleaned:
            return []
        return detect_chapters(cleaned)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _parse_raw_chapter_num_from_chunk_header(chunk_text: str) -> int | None:
    """从 chunk 文本首行（r0 header）解析 **原始** 章节号。

    "原始" 指尚未经过 "序章→1、原章1→2" 平移。调用方负责用 raw_to_norm
    map 把原始号映射为标准化章节号。

    Returns:
        原始章节号；无法识别时 None。
    """
    if not chunk_text:
        return None
    # 只看 chunk 首行——header 永远在第一行。
    first_line_end = chunk_text.find("\n")
    head = chunk_text[:first_line_end] if first_line_end > 0 else chunk_text

    # 序章
    if _HEADER_PROLOGUE_RE.match(head):
        return 0

    m = _HEADER_CHAPTER_NUM_RE.match(head)
    if m is None:
        return None
    # 四个捕获组互斥：中文 "第X章" / Chapter N / CHAPTER N / 卷X
    for idx in range(1, 5):
        lit = m.group(idx)
        if lit:
            parsed = _cn_to_int(lit)
            if parsed is None:
                return None
            return parsed
    return None


def _lang_word_count(text: str, lang: str) -> int:
    """语种感知字数统计。

    中文 / 日文按字符数（去除空白与换行），其余按 whitespace split。
    与 r0 ``book_chunker._char_count`` 的口径一致。
    """
    if lang in ("zh", "ja"):
        return len(text.replace(" ", "").replace("\n", "").replace("\t", ""))
    return len(text.split())


__all__ = ["R0BookAssembler"]
