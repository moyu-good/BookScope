"""BookScope v5 — Full MapReduce knowledge graph extractor.

Extracts chapter summaries and character profiles from ALL book chunks using LLM.
Uses batch processing (multiple chunks per LLM call) and concurrent execution
for full coverage at comparable cost to the old sampling approach.

Architecture:
    Map:    Chunks batched (5/call) → LLM → per-chunk summaries
    Reduce: Merge characters + generate overall summary

Performance (300-chunk book with DeepSeek):
    - Old: 60 sequential calls, 20% coverage, ~$0.50, ~2 min
    - New: 60 concurrent calls (4 workers), 100% coverage, ~$0.30-0.80, ~30s

Pure Python module — no Streamlit dependency.

Usage:
    from bookscope.nlp.knowledge_extractor import extract_knowledge_graph
    graph = extract_knowledge_graph(
        chunks=chunks,
        book_title="红楼梦",
        language="zh",
        api_key=key,
    )
"""

import json
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from bookscope.models.schemas import (
    BookKnowledgeGraph,
    ChapterSummary,
    CharacterProfile,
)
from bookscope.nlp.llm_analyzer import call_llm
from bookscope.nlp.ner_extractor import extract_character_candidates

logger = logging.getLogger(__name__)

_CHARS_PER_CHUNK = 1500  # max characters sent per chunk to LLM
_BATCH_SIZE = 5  # chunks per LLM call
_MAX_WORKERS = 4  # concurrent LLM calls


def _strip_fences(text: str) -> str:
    """Remove markdown code fences from LLM output."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(
            line for line in lines if not line.startswith("```")
        ).strip()
    return text


def _parse_json(raw: str) -> dict | list | None:
    """Parse JSON from LLM output, returning None on failure."""
    if not raw:
        return None
    # Remove trailing truncation guard ' …'
    cleaned = raw.strip()
    if cleaned.endswith(" …"):
        cleaned = cleaned[:-2]
    try:
        return json.loads(_strip_fences(cleaned))
    except (json.JSONDecodeError, ValueError):
        return None


# ---------------------------------------------------------------------------
#  Map phase: batch chunk summarization
# ---------------------------------------------------------------------------

def _build_batch_prompt(
    batch: list[tuple[int, str]],
    language: str,
) -> str:
    """Build a prompt for summarizing a batch of chunks."""
    chunks_text = ""
    for idx, text in batch:
        truncated = text[:_CHARS_PER_CHUNK]
        chunks_text += f"\n--- 片段 #{idx + 1} ---\n{truncated}\n"

    if language == "zh":
        return (
            "你是一个书籍内容分析助手。请分析以下多个书籍片段，为每个片段返回摘要。\n"
            "严格返回合法JSON数组，不要返回markdown或其他文字。\n"
            "每个元素的schema:\n"
            '{"chunk_index": 片段编号(从0开始), "title": "推断的章节标题", '
            '"summary": "50-100字概述", '
            '"key_events": ["事件1", "事件2"], '
            '"characters_mentioned": ["人物名1", "人物名2"]}\n\n'
            f"共{len(batch)}个片段:" + chunks_text
        )
    return (
        "You are a book content analyst. Analyze the following excerpts "
        "and return a summary for each.\n"
        "Return ONLY a valid JSON array, no markdown or explanation.\n"
        "Each element schema:\n"
        '{"chunk_index": N, "title": "inferred chapter title", '
        '"summary": "50-100 word summary", '
        '"key_events": ["event 1"], '
        '"characters_mentioned": ["Name1"]}\n\n'
        f"{len(batch)} excerpts:" + chunks_text
    )


def _extract_batch_summaries(
    batch: list[tuple[int, str]],
    language: str,
    api_key: str,
    model: str,
) -> list[ChapterSummary]:
    """Extract summaries for a batch of chunks in a single LLM call."""
    prompt = _build_batch_prompt(batch, language)
    batch_indices = {idx for idx, _ in batch}

    for attempt in range(2):
        # Larger max_tokens for batch responses
        raw = call_llm(prompt, api_key=api_key, model=model, max_tokens=300 * len(batch)) or ""
        data = _parse_json(raw)

        if data is not None:
            # data should be a list of dicts
            if isinstance(data, dict) and "summaries" in data:
                data = data["summaries"]
            if not isinstance(data, list):
                data = [data]

            results: list[ChapterSummary] = []
            parsed_indices: set[int] = set()

            for item in data:
                if not isinstance(item, dict):
                    continue
                ci = item.get("chunk_index")
                if ci is None:
                    continue
                # Adjust: LLM may return 1-based index from prompt
                if isinstance(ci, (int, float)):
                    ci = int(ci)
                    # If LLM returned 1-based (matching "片段 #N+1"), convert
                    if ci > 0 and (ci - 1) in batch_indices and ci not in batch_indices:
                        ci = ci - 1
                    parsed_indices.add(ci)
                    results.append(ChapterSummary(
                        chunk_index=ci,
                        title=str(item.get("title", "")),
                        summary=str(item.get("summary", "")),
                        key_events=[str(e) for e in item.get("key_events", []) if e],
                        characters_mentioned=[
                            str(c) for c in item.get("characters_mentioned", []) if c
                        ],
                    ))

            # Fill missing indices with empty summaries
            for idx, _ in batch:
                if idx not in parsed_indices:
                    results.append(ChapterSummary(chunk_index=idx))

            return results

        if attempt == 0:
            logger.debug("Batch parse failed, retrying")

    # Fallback: empty summaries for all chunks in batch
    return [ChapterSummary(chunk_index=idx) for idx, _ in batch]


# ---------------------------------------------------------------------------
#  Character merging (unchanged logic, improved prompt)
# ---------------------------------------------------------------------------

def _merge_characters(
    summaries: list[ChapterSummary],
    book_title: str,
    language: str,
    api_key: str,
    model: str,
    ner_candidates: dict[str, list[int]] | None = None,
) -> list[CharacterProfile]:
    """Merge all mentioned characters into deduplicated profiles via LLM."""
    all_names: dict[str, list[int]] = {}
    for s in summaries:
        for name in s.characters_mentioned:
            all_names.setdefault(name, []).append(s.chunk_index)

    if ner_candidates:
        for name, indices in ner_candidates.items():
            if name in all_names:
                all_names[name] = sorted(set(all_names[name] + indices))
            else:
                all_names[name] = indices

    if not all_names:
        return []

    names_info = ", ".join(
        f"{name}(出现在段落{idxs})" for name, idxs in all_names.items()
    )

    context_lines = []
    for s in summaries:
        if s.summary:
            context_lines.append(f"段落{s.chunk_index}: {s.summary}")
    context = "\n".join(context_lines[:30])  # cap context length

    prompt = (
        "你是一个书籍人物分析专家。根据以下信息，合并重复人物（同一人物的不同称呼），"
        "输出去重后的人物档案列表。\n"
        "严格返回合法JSON数组，不要返回markdown或其他文字。\n"
        "每个人物的JSON schema:\n"
        '{"name": "主名称", "aliases": ["别名1"], '
        '"description": "一句话描述", "voice_style": "说话风格", '
        '"motivations": ["动机1"], '
        '"key_chapter_indices": [0, 1], '
        '"arc_summary": "人物弧光概述"}\n\n'
        f"书名: {book_title}\n"
        f"出现的人物及段落: {names_info}\n\n"
        f"各段落摘要:\n{context}"
    )
    if language == "en":
        names_info_en = ", ".join(
            f"{name}(appears in chunks {idxs})" for name, idxs in all_names.items()
        )
        context_en = "\n".join(
            f"Chunk {s.chunk_index}: {s.summary}" for s in summaries[:30] if s.summary
        )
        prompt = (
            "You are a book character analyst. Merge duplicate characters "
            "(same person with different names/titles) and produce deduplicated "
            "character profiles.\n"
            "Return ONLY a valid JSON array, no markdown or explanation.\n"
            "Each character schema:\n"
            '{"name": "primary name", "aliases": ["alias1"], '
            '"description": "one-line description", "voice_style": "speech style", '
            '"motivations": ["motivation1"], '
            '"key_chapter_indices": [0, 1], '
            '"arc_summary": "character arc summary"}\n\n'
            f"Book: {book_title}\n"
            f"Characters and chunks: {names_info_en}\n\n"
            f"Chunk summaries:\n{context_en}"
        )

    raw = call_llm(prompt, api_key=api_key, model=model, max_tokens=2000) or ""
    data = _parse_json(raw)

    if data is None:
        return [
            CharacterProfile(name=name, key_chapter_indices=idxs)
            for name, idxs in all_names.items()
        ]

    if isinstance(data, dict) and "characters" in data:
        data = data["characters"]
    if not isinstance(data, list):
        return [
            CharacterProfile(name=name, key_chapter_indices=idxs)
            for name, idxs in all_names.items()
        ]

    profiles = []
    for item in data:
        if not isinstance(item, dict):
            continue
        profiles.append(CharacterProfile(
            name=str(item.get("name", "")),
            aliases=[str(a) for a in item.get("aliases", []) if a],
            description=str(item.get("description", "")),
            voice_style=str(item.get("voice_style", "")),
            motivations=[str(m) for m in item.get("motivations", []) if m],
            key_chapter_indices=[
                int(i) for i in item.get("key_chapter_indices", [])
                if isinstance(i, (int, float))
            ],
            arc_summary=str(item.get("arc_summary", "")),
        ))
    return profiles


# ---------------------------------------------------------------------------
#  Public API
# ---------------------------------------------------------------------------

def extract_knowledge_graph(
    chunks: list,
    book_title: str,
    language: str = "zh",
    api_key: str | None = None,
    model: str = "claude-haiku-4-5",
    progress_callback: Callable[[int, int], None] | None = None,
    max_extract: int = 0,  # 0 = all chunks (no sampling)
    enrich_souls: bool = False,
    batch_size: int = _BATCH_SIZE,
    max_workers: int = _MAX_WORKERS,
) -> BookKnowledgeGraph:
    """Extract a BookKnowledgeGraph from ALL book chunks using MapReduce.

    Map phase:  Chunks batched (batch_size per LLM call) → concurrent extraction
    Reduce phase: Merge characters + build overall summary

    Args:
        chunks: list[ChunkResult] from the analysis pipeline.
        book_title: Title of the book.
        language: Language code ("zh", "en", "ja").
        api_key: LLM API key (from BYOK settings).
        model: LLM model ID.
        progress_callback: Optional (current, total) progress reporter.
        max_extract: Max chunks to process (0 = all, for backward compat).
        enrich_souls: If True, enrich top 5 characters with soul profiles.
        batch_size: Number of chunks per LLM call (default 5).
        max_workers: Concurrent LLM call threads (default 4).

    Returns:
        BookKnowledgeGraph with chapter summaries and character profiles.
    """
    if not chunks or not api_key:
        return BookKnowledgeGraph(book_title=book_title, language=language)

    total = len(chunks)

    # Step 0: fast local NER on ALL chunks (no LLM)
    ner_candidates: dict[str, list[int]] = {}
    try:
        ner_candidates = extract_character_candidates(chunks, language)
        logger.info("NER found %d character candidates across all chunks", len(ner_candidates))
    except Exception:
        logger.warning("NER extraction failed, continuing with LLM-only")

    # Step A: prepare batches
    if max_extract > 0 and max_extract < total:
        # Backward compat: if explicitly limited, sample
        sample_set = set(_sample_indices(total, max_extract))
        process_indices = sorted(sample_set)
    else:
        process_indices = list(range(total))

    batches: list[list[tuple[int, str]]] = []
    current_batch: list[tuple[int, str]] = []
    for idx in process_indices:
        text = getattr(chunks[idx], "text", str(chunks[idx]))
        current_batch.append((idx, text))
        if len(current_batch) >= batch_size:
            batches.append(current_batch)
            current_batch = []
    if current_batch:
        batches.append(current_batch)

    total_to_process = len(process_indices)
    logger.info(
        "MapReduce KG: %d chunks in %d batches (%d workers)",
        total_to_process, len(batches), max_workers,
    )

    # Step B: Map phase — concurrent batch extraction
    summaries_map: dict[int, ChapterSummary] = {}
    progress_done = 0

    def _process_batch(batch: list[tuple[int, str]]) -> list[ChapterSummary]:
        return _extract_batch_summaries(batch, language, api_key, model)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_batch = {
            executor.submit(_process_batch, batch): batch
            for batch in batches
        }
        for future in as_completed(future_to_batch):
            batch = future_to_batch[future]
            try:
                batch_results = future.result()
                for summary in batch_results:
                    summaries_map[summary.chunk_index] = summary
            except Exception:
                logger.exception("Batch extraction failed")
                for idx, _ in batch:
                    summaries_map[idx] = ChapterSummary(chunk_index=idx)

            progress_done += len(batch)
            if progress_callback is not None:
                progress_callback(min(progress_done, total), total)

    # Build ordered summary list (all chunks, including non-processed ones)
    summaries: list[ChapterSummary] = []
    for i in range(total):
        if i in summaries_map:
            summaries.append(summaries_map[i])
        else:
            summaries.append(ChapterSummary(chunk_index=i))

    # Step C: Reduce — merge characters
    rich_summaries = [s for s in summaries if s.summary]
    logger.info("Rich summaries: %d / %d", len(rich_summaries), total)

    characters = _merge_characters(
        summaries=rich_summaries,
        book_title=book_title,
        language=language,
        api_key=api_key,
        model=model,
        ner_candidates=ner_candidates,
    )

    # Step D (optional): enrich top characters with soul profiles
    if enrich_souls and characters:
        from bookscope.nlp.soul_engine import enrich_soul_profile

        ranked = sorted(
            characters,
            key=lambda c: len(c.key_chapter_indices),
            reverse=True,
        )
        for char in ranked[:5]:
            try:
                enriched = enrich_soul_profile(
                    profile=char,
                    chunks=chunks,
                    chunk_indices=char.key_chapter_indices,
                    book_title=book_title,
                    language=language,
                    api_key=api_key,
                    model=model,
                )
                idx = characters.index(char)
                characters[idx] = enriched
            except Exception:
                logger.warning("Soul enrichment failed for %s", char.name)

    # Generate overall summary from chapter summaries
    overall_summary = ""
    if rich_summaries:
        summary_texts = [s.summary for s in rich_summaries[:20] if s.summary]
        if summary_texts:
            summary_prompt = (
                "根据以下书籍各章节摘要，生成一段100-200字的全书总体概述。"
                "严格返回纯文本，不要返回JSON或markdown。\n\n"
                f"书名：{book_title}\n\n"
                + "\n".join(f"- {s}" for s in summary_texts)
            ) if language == "zh" else (
                "Based on the following chapter summaries, write a 100-200 word "
                "overall summary of the book. Return plain text only.\n\n"
                f"Book: {book_title}\n\n"
                + "\n".join(f"- {s}" for s in summary_texts)
            )
            overall_summary = call_llm(
                summary_prompt, api_key=api_key, model=model, max_tokens=400
            ) or ""

    return BookKnowledgeGraph(
        book_title=book_title,
        language=language,
        chapter_summaries=summaries,
        characters=characters,
        overall_summary=overall_summary,
    )


# ---------------------------------------------------------------------------
#  Backward compat: sampling helper (used when max_extract > 0)
# ---------------------------------------------------------------------------

def _sample_indices(total: int, budget: int) -> list[int]:
    """Pick chunk indices when explicitly limited."""
    if total <= budget:
        return list(range(total))
    step = max(1, total / budget)
    sampled = {0, total - 1}
    sampled |= {min(int(i * step), total - 1) for i in range(budget)}
    indices = sorted(sampled)
    if len(indices) > budget:
        middle = indices[1:-1]
        keep = budget - 2
        step_m = max(1, len(middle) / keep)
        kept = [middle[int(i * step_m)] for i in range(keep)]
        indices = sorted({0, total - 1} | set(kept))
    return indices
