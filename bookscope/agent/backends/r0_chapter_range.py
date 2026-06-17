"""r0 backend 适配：把 r0 章节原文数据包装成 r1 ``ChapterTextBackend``。

本文件把 r0 代际能够解析出的"整本书 → 章节 → 章节原文"结构包装成
r1 ADR-001 的 ``ChapterTextBackend`` Protocol 实现，供 ``get_chapter_range``
tool 调用。

### r0 数据能力评估（2026-04-20 梳理）

r0 **没有把"按章节存储的完整原文"做持久化**。具体事实：

1. ``bookscope.ingest.loader`` 只产出 ``BookText.raw_text``——整本书一大
   字符串，没有按章节切分字段。
2. ``bookscope.ingest.book_chunker.detect_chapters`` 是官方的公共 helper，
   在内部识别出 ``(chapter_num, chapter_title, chapter_body)`` 三元组。
   但 ``chunk_book`` 把这些三元组包装成扁平 ``list[ChunkResult]``，章节
   元数据以 ``"[《...》第X章]"`` header 字符串嵌入 chunk 文本，**不是结构化
   字段**；要按章节访问原文，必须直接调 ``detect_chapters``。
3. ``bookscope.models.schemas.BookKnowledgeGraph`` 有 ``ChapterAnalysis``
   和 ``ChapterSummary``——但它们是 LLM 产出的二次分析，不是章节原文。

因此本 backend **不能只靠 r0 原生 API 推断章节原文**；必须由调用方在
构造时**外部提供一份"章节号 → (标题, 原文, 字数)"的清单**。具体装配方式：
上层可调用 ``book_chunker.detect_chapters(clean(book.raw_text))`` 拿到
三元组，再包装成本 backend 需要的数据结构后传入；也可由未来 r0 ingest
阶段补一张 "chapter store" 表后直接喂进来。``R0BookAssembler`` 已经把
这条装配路径内置在 ``_compute_chapter_records`` 里，大多数调用方不必
自己重造，直接用 ``R0BookAssembler.build_chapter_range_backend()`` 即可。

若调用方不传任何章节数据（空列表），构造不会报错，但任何
``get_chapters / total_words`` 调用都会按"空书"的语义抛 ``ChapterNotFound``。
这是**合理降级**，相当于"r0 这本书还没来得及解析出章节"。

### 适配假设

- 章节号按自然顺序自 1 开始递增（r0 ``book_chunker`` 也是 1-based；
  它另外允许一个 ``0`` 号"序"，上层如果把"序"当第 1 章就能直接对齐，
  如果要保留 0 号则需要自行规避 ADR 的 ``ge=1`` 约束，不在本 backend 承担）。
- ``total_words`` 与 ``get_chapters`` 都按 ``[start, end]`` 含端点语义；
  ``total_words`` 做 cheap 累加（不触发 full_text 的拷贝），
  ``get_chapters`` 负责把原文打包回 ``ChapterText``。
- 超范围处理：本 backend 对"任一 start/end 指向不存在章节"一律抛
  ``ChapterNotFound``，不做静默截断。dispatcher 上层先通过
  ``total_words`` 做 20 万字上限检查——因此若 ``total_words`` 也抛
  ``ChapterNotFound``，请求会在 O(1) 内被拒，不做无谓 I/O。

### 为什么不改 r0

r0 原生没有章节原文结构化存储是代际级缺口；按项目规约（STATE.md
"需作者决策"区）新增字段属代际级改动，副管理不得自行扩 r0 schema。
此处选择"构造参数外部注入"workaround，和 ``R0SearchChunksBackend``
的做法一致。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from bookscope.agent.tools.errors import ChapterNotFound
from bookscope.agent.tools.schemas import ChapterText

# ---------------------------------------------------------------------------
# 章节原始数据容器（backend 内部）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class R0ChapterRecord:
    """backend 构造入参的章节原始记录。

    调用方负责把 r0 ``book_chunker.detect_chapters`` 或未来章节 store
    的产出装配成本数据类实例。本层不做字数计算——字数由调用方根据语种
    自行按 ``_char_count`` 或 ``len(split())`` 口径给出，避免在 r1 层再
    塞一份独立口径。

    Attributes:
        chapter: 章节号，必须 >= 1，严格自增。
        title: 章节标题；r0 无标题时传空串。
        full_text: 章节完整原文；不能为空（Pydantic ``ChapterText`` 要求
            ``min_length=1``，上层若传空串将在 ``get_chapters`` 时引发
            ValidationError）。
        word_count: 章节字数；中文按字符数、英文按 whitespace split。
    """

    chapter: int
    title: str
    full_text: str
    word_count: int


# ---------------------------------------------------------------------------
# R0ChapterRangeBackend
# ---------------------------------------------------------------------------


class R0ChapterRangeBackend:
    """把一份按章节组织的 r0 原文清单包装成 r1 ``ChapterTextBackend``。

    构造参数：

    Args:
        chapters: r0 侧整理出的章节原始记录。通常来自：
            1) ``book_chunker.detect_chapters(clean(book.raw_text))``
               产出的 ``(chapter_num, chapter_title, chapter_body)``
               三元组（再由上层计算 ``word_count`` 后包装）；或
            2) 未来 r0 ingest 阶段补出的章节 store。
            传入序列会被复制为内部 list 并按 ``chapter`` 升序排序，
            便于 ``total_words`` / ``get_chapters`` 用二分或线性切片。

    Raises:
        ValueError: 当传入的章节号有重复时直接拒绝——r0 的章节号自然递增，
            出现重复说明上层装配出错，不能静默合并。
    """

    def __init__(self, chapters: Iterable[R0ChapterRecord]) -> None:
        records = sorted(chapters, key=lambda r: r.chapter)
        seen: set[int] = set()
        for rec in records:
            if rec.chapter in seen:
                raise ValueError(
                    f"duplicate chapter number in r0 backend input: {rec.chapter}"
                )
            seen.add(rec.chapter)
        self._records: list[R0ChapterRecord] = records
        # 建 chapter → index 便于 O(1) 范围检查。
        self._chapter_index: dict[int, int] = {
            rec.chapter: idx for idx, rec in enumerate(records)
        }

    # ------------------------------------------------------------------
    # ChapterTextBackend Protocol 实现
    # ------------------------------------------------------------------

    def total_words(self, start: int, end: int) -> int:
        """返回 ``[start, end]`` 区间（含端点）章节的合计字数。

        - 空书（backend 无任何章节记录）：抛 ``ChapterNotFound``。
        - ``start`` 或 ``end`` 指向不存在章节：抛 ``ChapterNotFound``
          并在消息中指明最大可用章节号，引导 agent 收缩范围。
        - ``start > end``：抛 ``ValueError``（ADR-001 的 input schema
          本已守住这一点；此处再验证一次作为深度防御，因为 backend
          可能被脱离 dispatcher 直接调用，例如 agent loop 的 dry-run）。
        - ``start < 1``：抛 ``ValueError``。

        该方法 **cheap**：仅线性扫描章节 word_count 字段，不触碰 full_text。
        """
        self._validate_range(start, end)
        sliced = self._slice(start, end)
        return sum(rec.word_count for rec in sliced)

    def get_chapters(self, start: int, end: int) -> list[ChapterText]:
        """返回 ``[start, end]`` 区间（含端点）章节的完整原文。

        错误语义与 ``total_words`` 一致（超范围 → ``ChapterNotFound``、
        start/end 非法 → ``ValueError``）。

        返回的 ``ChapterText`` 按 ``chapter`` 升序；``source_version`` 固定
        为 ``"r0"``，追溯这些章节原文来自 r0 ingest 阶段产出。
        """
        self._validate_range(start, end)
        sliced = self._slice(start, end)
        return [
            ChapterText(
                chapter=rec.chapter,
                title=rec.title,
                full_text=rec.full_text,
                word_count=rec.word_count,
                source_version="r0",
            )
            for rec in sliced
        ]

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _validate_range(self, start: int, end: int) -> None:
        """校验 ``[start, end]`` 区间本身合法（不管 backend 里有没有数据）。

        顺序：先校验 ``start / end`` 的绝对值合法性，再校验 ``start <= end``，
        最后再查 backend 的章节覆盖情况。这样报错粒度从粗到细，方便
        agent 按错误类型做不同的自我修正。
        """
        if start < 1:
            raise ValueError(
                f"start_chapter must be >= 1 (got {start})"
            )
        if end < 1:
            raise ValueError(
                f"end_chapter must be >= 1 (got {end})"
            )
        if start > end:
            raise ValueError(
                "start_chapter must be <= end_chapter "
                f"(got start={start}, end={end})"
            )
        # backend 内部是否有数据。
        if not self._records:
            raise ChapterNotFound(
                "r0 backend has no chapter records "
                "(empty book or chapters not yet ingested)."
            )
        max_chapter = self._records[-1].chapter
        if end > max_chapter:
            raise ChapterNotFound(
                f"end_chapter {end} exceeds the last available chapter "
                f"{max_chapter}. Narrow the range or inspect the book's "
                "table of contents."
            )
        if start not in self._chapter_index:
            raise ChapterNotFound(
                f"start_chapter {start} is not present in r0 chapter store."
            )

    def _slice(self, start: int, end: int) -> Sequence[R0ChapterRecord]:
        """返回 ``[start, end]`` 含端点范围内的章节记录。

        仅在 ``_validate_range`` 之后调用。中间若有"跳号"（比如 r0 真的
        漏了某章），这里按"跳过该章"语义处理——因为 ``_validate_range``
        已确保 start/end 本身存在，其间偶有缺章不足以让整次请求失败。
        """
        start_idx = self._chapter_index[start]
        # end 已确认 <= max_chapter。找出 end 对应的 index——end 本身
        # 可能不在 _chapter_index（跳号场景）；此时找不大于 end 的最近一条。
        if end in self._chapter_index:
            end_idx = self._chapter_index[end]
        else:
            end_idx = start_idx
            for idx in range(start_idx, len(self._records)):
                if self._records[idx].chapter <= end:
                    end_idx = idx
                else:
                    break
        return self._records[start_idx : end_idx + 1]
