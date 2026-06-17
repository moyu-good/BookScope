"""r0 backend 适配：把 r0 ``SessionVectorStore`` 包装成 r1 ``ChunkRetrievalBackend``。

本文件把 r0 v7 代际落盘的 FAISS + BM25 混合检索（``SessionVectorStore``）
包装成 r1 ADR-001 的 ``ChunkRetrievalBackend`` Protocol 实现，供
``search_chunks`` tool 调用。

### r0 数据能力评估（2026-04-20 梳理）

r0 的 ``bookscope.models.schemas.ChunkResult`` 字段只有 ``index / text /
word_count``，**不带** 下列 r1 需要的元数据：

1. ``chapter``：chunk 属于哪一章。r0 的 chunker 产物仅按固定窗口或段落切分，
   没保留 "chunk-to-chapter" 映射。
2. ``contains_characters``：chunk 包含哪些角色的 canonical_name。r0 KG 抽取
   阶段有 ``CharacterProfile.key_chapter_indices``（章节粒度），但**没有
   chunk 粒度**的角色倒排索引。

因此本 backend 不能只靠 r0 原生 API，必须**由调用方在构造时外部提供两份
补齐映射**：``chunk_index_to_chapter`` 和 ``chunk_index_to_characters``。
若缺失关键映射，本 backend 会抛 ``NotImplementedError`` 并把缺口记入
``docs/internal/STATE.md`` 的"需作者决策"区，**绝不回去硬改 r0**（那是代际级改动）。

### 适配假设

- r0 ``SessionVectorStore.search(query, top_k)`` 返回
  ``list[tuple[ChunkResult, float]]``；分数不保证落在 ``[0, 1]``（BM25 /
  RRF 的分数上限不可知，cross-encoder 的分数甚至可能是负 logit）。因此本
  backend 会做一次**局部归一化**：先过滤出在过滤条件下的候选，再把它们
  的分数线性映射到 ``[0, 1]``（最高分映射为 1.0，最低分映射为 0.0；
  只有一条时定为 1.0）。这是 ADR-001 要求 ``relevance_score`` 归一的最低
  限度兑现；语义 ranking 的绝对值解读留给下游。
- 为了留给过滤过滤掉一部分候选后仍有足够结果，内部向 r0 一次性取
  ``top_k * 3``（下限 ``top_k``）条候选。该倍数是工程试验值，后续可调。
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from bookscope.agent.tools.schemas import ChunkMatch

if TYPE_CHECKING:
    from bookscope.models.schemas import ChunkResult
    from bookscope.store.reranker_provider import RerankerProvider

logger = logging.getLogger(__name__)

# rerank 候选池倍数默认值；可被构造参数或 BOOKSCOPE_RERANK_OVERSAMPLE 覆盖。
_DEFAULT_OVERSAMPLE = 4


# ---------------------------------------------------------------------------
# 上游 r0 store 结构型 Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class _R0VectorStoreLike(Protocol):
    """r0 ``SessionVectorStore`` 的结构型 Protocol。

    本 backend 只依赖 ``search`` 方法，不耦合到具体类，便于在测试里用 Mock
    替换真 FAISS 实例。签名与 ``bookscope.store.vector_store.SessionVectorStore``
    保持一致。
    """

    def search(
        self,
        query: str,
        top_k: int = ...,
    ) -> list[tuple[ChunkResult, float]]:
        """执行一次 hybrid 检索，返回 (ChunkResult, raw_score) 列表。"""
        ...


# ---------------------------------------------------------------------------
# R0SearchChunksBackend
# ---------------------------------------------------------------------------


class R0SearchChunksBackend:
    """把 r0 ``SessionVectorStore`` 包装成 r1 ``ChunkRetrievalBackend``。

    构造参数：

    Args:
        vector_store: r0 的 ``SessionVectorStore`` 或任何结构兼容对象。
        chunk_index_to_chapter: r0 ``ChunkResult.index`` → 章节号的映射，
            用于满足 ADR-001 的 ``chapter_scope`` 过滤需求。r0 本身无此映射，
            必须由上层（例如 ingest pipeline 或 book_chunker）补齐后传入。
        chunk_index_to_characters: r0 ``ChunkResult.index`` → 该 chunk 出现
            的角色 ``canonical_name`` 列表；缺失的 chunk 视为无角色信息，
            ``character_filter`` 不会命中（合理降级）。
        chunk_id_prefix: ``chunk_id`` 的前缀，默认 ``"r0-chunk-"``，
            与原始 chunk index 拼成 stable id。跨 r0/r1 保持一致即可。
        oversample_factor: 内部向 r0 取候选时的倍数；默认 None 时读环境变量
            ``BOOKSCOPE_RERANK_OVERSAMPLE``（缺省 4）。rerank 的价值就是从更大
            候选池里挑准，候选给太少等于没给它发挥空间。取
            ``max(top_k * factor, top_k)`` 条。
        reranker: rerank provider；默认 None 时调 ``get_reranker_provider()``
            按配置解析（总开关关 / 没 key → 拿到 None → 跳过 rerank 走原排序，
            行为跟今天完全一样）。测试可显式传 Mock 或 None 绕过工厂。
    """

    def __init__(
        self,
        vector_store: _R0VectorStoreLike,
        *,
        chunk_index_to_chapter: Mapping[int, int],
        chunk_index_to_characters: Mapping[int, Sequence[str]] | None = None,
        chunk_id_prefix: str = "r0-chunk-",
        oversample_factor: int | None = None,
        reranker: RerankerProvider | None = None,
    ) -> None:
        if chunk_index_to_chapter is None:
            # r0 ChunkResult 不含 chapter 字段，调用方必须外部提供映射。
            # 实际路径：api/routes/books.py ingest 时由 R0BookAssembler 计算后注入。
            raise NotImplementedError(
                "R0SearchChunksBackend 需要 chunk_index_to_chapter 映射；"
                "r0 的 ChunkResult 不带 chapter 字段。"
                "请在构造时传入外部映射，或待 r0 补出该能力。"
            )
        self._store = vector_store
        self._chunk_to_chapter: dict[int, int] = dict(chunk_index_to_chapter)
        self._chunk_to_characters: dict[int, list[str]] = {
            idx: list(names)
            for idx, names in (chunk_index_to_characters or {}).items()
        }
        self._chunk_id_prefix = chunk_id_prefix
        self._oversample_factor = max(1, _resolve_oversample(oversample_factor))
        # reranker 没显式传时按配置解析；总开关关 / 没 key → None → 跳过 rerank。
        if reranker is None:
            from bookscope.store.reranker_provider import get_reranker_provider

            reranker = get_reranker_provider()
        self._reranker: RerankerProvider | None = reranker

    # ------------------------------------------------------------------
    # ChunkRetrievalBackend Protocol 实现
    # ------------------------------------------------------------------

    def retrieve(
        self,
        query: str,
        chapter_scope: tuple[int, int] | None,
        character_filter: list[str] | None,
        top_k: int,
    ) -> list[ChunkMatch]:
        """执行一次带 scope 和 character 过滤的 top-k 检索。

        流程：
        1. 向 r0 store 取 ``top_k * oversample_factor`` 条候选（下限 top_k）。
        2. 按 ``chapter_scope`` 过滤：chunk 的章节号必须落在 [start, end]（含端点）。
        3. 按 ``character_filter`` 过滤：chunk 必须至少涉及指定角色之一；
           若 chunk 在 ``chunk_index_to_characters`` 中无记录，则视为不命中。
        4. 把过滤后剩余的原始分数**局部归一化**到 ``[0, 1]``，
           封装为 ``ChunkMatch`` 并截取前 ``top_k`` 条返回。
        """
        fetch_k = max(top_k * self._oversample_factor, top_k)
        raw_candidates: list[tuple[ChunkResult, float]] = self._store.search(
            query, fetch_k,
        )

        # Step 1：按 chapter / character 过滤。
        filtered: list[tuple[ChunkResult, float, int, list[str]]] = []
        character_filter_set: set[str] | None = (
            set(character_filter) if character_filter else None
        )
        for chunk, raw_score in raw_candidates:
            chapter = self._chunk_to_chapter.get(chunk.index)
            if chapter is None:
                # chunk 没有章节映射，r1 无法回答 "在哪章"——跳过而非假设。
                continue
            if chapter_scope is not None:
                start, end = chapter_scope
                if chapter < start or chapter > end:
                    continue

            chunk_characters = self._chunk_to_characters.get(chunk.index, [])
            if character_filter_set is not None:
                if not any(name in character_filter_set for name in chunk_characters):
                    continue

            filtered.append((chunk, float(raw_score), chapter, chunk_characters))

        if not filtered:
            return []

        # WP2a：从 store 读检索模式，让"无 embedding 退 BM25"的降级在每条
        # 结果上留痕。用 getattr 兜底——老 store / 测试 Mock 没有该属性时
        # 填 None，不炸。基础值是 "hybrid" / "bm25_only" / None。
        retrieval_mode = getattr(self._store, "retrieval_mode", None)

        # Step 2：排序 + 截断到 top_k。
        # - 有 reranker：整批过滤后的候选发去 rerank，按精排分排完再截 top_k；
        #   真跑成功才把 retrieval_mode 标成 *_rerank（设计稿第 4 节那张表）。
        # - 没 reranker / rerank 失败：退回按原始分降序（r0 返回时已大致有序，
        #   过滤可能打破连续性，这里显式再排一次），mode 保持基础值不变。
        reranked, retrieval_mode = self._maybe_rerank(
            query, filtered, top_k, retrieval_mode,
        )
        trimmed = reranked[:top_k]

        # Step 3：归一化分数到 [0, 1]。
        normalised = _normalise_scores([score for _, score, _, _ in trimmed])

        matches: list[ChunkMatch] = []
        for (chunk, _raw, chapter, characters), score in zip(trimmed, normalised):
            matches.append(
                ChunkMatch(
                    chunk_id=f"{self._chunk_id_prefix}{chunk.index}",
                    chapter=chapter,
                    text=chunk.text,
                    relevance_score=score,
                    contains_characters=list(characters),
                    source_version="r0",
                    retrieval_mode=retrieval_mode,
                )
            )
        return matches

    # ------------------------------------------------------------------
    # rerank（WP-reranker-api）
    # ------------------------------------------------------------------

    def _maybe_rerank(
        self,
        query: str,
        filtered: list[tuple[ChunkResult, float, int, list[str]]],
        top_k: int,
        base_mode: str | None,
    ) -> tuple[list[tuple[ChunkResult, float, int, list[str]]], str | None]:
        """对过滤后的候选做 rerank；失败或没 reranker 时退回原排序。

        返回 ``(排好序的候选, 新的 retrieval_mode)``：

        - 没 reranker：按原始分降序，mode 保持 ``base_mode`` 不变。
        - rerank 成功：按精排分重排，mode 升成 ``*_rerank``。
        - rerank 抛异常（超时 / 报错 / 配额耗尽）：捕获、退回原始分降序、mode
          保持 ``base_mode``（没真成功就不许标 ``_rerank``）、记一条 warning。
          绝不让整个查询挂掉。
        """
        # 原始分降序：rerank 失败 / 没 reranker 的退回基准。
        by_raw = sorted(filtered, key=lambda tup: tup[1], reverse=True)

        if self._reranker is None:
            return by_raw, base_mode

        documents = [chunk.text for chunk, _raw, _chap, _chars in filtered]
        try:
            ranked = self._reranker.rerank(query, documents, top_n=top_k)
        except Exception:  # noqa: BLE001 — 任何 rerank 失败都退回原序，不让查询挂掉
            logger.warning(
                "rerank 调用失败，退回原始分排序（mode 保持 %r）",
                base_mode,
                exc_info=True,
            )
            return by_raw, base_mode

        # rerank 返回 [(原 documents 下标, 精排分), ...]，已按分降序。
        # 把精排分换进候选元组的 score 位，按这个顺序重排候选。
        reranked: list[tuple[ChunkResult, float, int, list[str]]] = []
        for idx, score in ranked:
            if not 0 <= idx < len(filtered):
                # provider 给了越界下标——跳过这条，不让坏数据炸掉整批。
                continue
            chunk, _raw, chapter, characters = filtered[idx]
            reranked.append((chunk, float(score), chapter, characters))

        if not reranked:
            # rerank 没回任何可用结果，当失败处理：退回原序、不标 _rerank。
            logger.warning(
                "rerank 返回空 / 全越界，退回原始分排序（mode 保持 %r）",
                base_mode,
            )
            return by_raw, base_mode

        return reranked, _rerank_mode(base_mode)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_oversample(explicit: int | None) -> int:
    """解析候选池倍数：显式参数优先，否则读 ``BOOKSCOPE_RERANK_OVERSAMPLE``。"""
    if explicit is not None:
        return int(explicit)
    raw = os.environ.get("BOOKSCOPE_RERANK_OVERSAMPLE", "").strip()
    if not raw:
        return _DEFAULT_OVERSAMPLE
    try:
        return int(raw)
    except ValueError:
        logger.warning(
            "BOOKSCOPE_RERANK_OVERSAMPLE=%r 不是整数，用默认 %d",
            raw,
            _DEFAULT_OVERSAMPLE,
        )
        return _DEFAULT_OVERSAMPLE


def _rerank_mode(base_mode: str | None) -> str | None:
    """rerank 真跑成功后给 retrieval_mode 升档（设计稿第 4 节那张表）。

    - ``"hybrid"`` → ``"hybrid_rerank"``
    - ``"bm25_only"`` → ``"bm25_rerank"``
    - 其它 / None：拿不到基础模式，不臆造，保持原值。
    """
    if base_mode == "hybrid":
        return "hybrid_rerank"
    if base_mode == "bm25_only":
        return "bm25_rerank"
    return base_mode


def _normalise_scores(raw_scores: Sequence[float]) -> list[float]:
    """把一组原始分数线性映射到 ``[0.0, 1.0]``。

    - 空列表返回空列表。
    - 单元素返回 ``[1.0]``。
    - 所有分数相同（max == min）时全部返回 ``1.0``（它们同等相关）。
    - 否则按 ``(x - min) / (max - min)`` 归一化；结果最高 1.0、最低 0.0。

    这不是语义意义上的"绝对相关性"，而是 ADR-001 对 ``ChunkMatch.relevance_score``
    字段取值区间 ``[0, 1]`` 的最低限度兑现；agent 侧只需知道"相对排序"，
    不应把该值当概率用。
    """
    if not raw_scores:
        return []
    if len(raw_scores) == 1:
        return [1.0]
    top = max(raw_scores)
    bottom = min(raw_scores)
    span = top - bottom
    if span <= 0.0:
        return [1.0] * len(raw_scores)
    return [(s - bottom) / span for s in raw_scores]
