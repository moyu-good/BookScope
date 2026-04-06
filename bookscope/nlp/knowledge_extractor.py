"""BookScope v3 — Knowledge graph extractor.

Extracts chapter summaries and character profiles from book chunks using LLM.
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

from bookscope.models.schemas import (
    BookKnowledgeGraph,
    ChapterSummary,
    CharacterProfile,
)
from bookscope.nlp.llm_analyzer import call_llm
from bookscope.nlp.ner_extractor import extract_character_candidates

logger = logging.getLogger(__name__)

_CHARS_PER_CHUNK = 1500  # max characters sent per chunk to LLM


def _strip_fences(text: str) -> str:
    """Remove markdown code fences from LLM output."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(
            line for line in lines if not line.startswith("```")
        ).strip()
    return text


def _parse_json(raw: str) -> dict | None:
    """Parse JSON from LLM output, returning None on failure."""
    if not raw:
        return None
    try:
        return json.loads(_strip_fences(raw))
    except (json.JSONDecodeError, ValueError):
        return None


def _extract_chunk_summary(
    chunk_index: int,
    chunk_text: str,
    language: str,
    api_key: str,
    model: str,
) -> ChapterSummary:
    """Extract a ChapterSummary from a single chunk via LLM. Retry once on failure."""
    prompt = (
        "你是一个书籍内容分析助手。请分析以下书籍片段，返回JSON格式的摘要。\n"
        "严格返回合法JSON，不要返回markdown或其他文字。\n"
        "JSON schema:\n"
        '{"title": "推断的章节标题(可为空字符串)", '
        '"summary": "50-100字的内容概述", '
        '"key_events": ["事件1", "事件2"], '
        '"characters_mentioned": ["人物名1", "人物名2"]}\n\n'
        f"片段 #{chunk_index + 1}:\n"
        f"{chunk_text[:_CHARS_PER_CHUNK]}"
    )
    if language == "en":
        prompt = (
            "You are a book content analyst. Analyze the following excerpt "
            "and return a JSON summary.\n"
            "Return ONLY valid JSON, no markdown or explanation.\n"
            "JSON schema:\n"
            '{"title": "inferred chapter title (empty string if unclear)", '
            '"summary": "50-100 word summary", '
            '"key_events": ["event 1", "event 2"], '
            '"characters_mentioned": ["Name1", "Name2"]}\n\n'
            f"Excerpt #{chunk_index + 1}:\n"
            f"{chunk_text[:_CHARS_PER_CHUNK]}"
        )

    for attempt in range(2):
        raw = call_llm(prompt, api_key=api_key, model=model, max_tokens=600) or ""
        data = _parse_json(raw)
        if data is not None:
            return ChapterSummary(
                chunk_index=chunk_index,
                title=str(data.get("title", "")),
                summary=str(data.get("summary", "")),
                key_events=[str(e) for e in data.get("key_events", []) if e],
                characters_mentioned=[
                    str(c) for c in data.get("characters_mentioned", []) if c
                ],
            )
        if attempt == 0:
            logger.debug("chunk %d: JSON parse failed, retrying", chunk_index)

    logger.warning("chunk %d: fallback to empty summary after 2 attempts", chunk_index)
    return ChapterSummary(chunk_index=chunk_index)


def _merge_characters(
    summaries: list[ChapterSummary],
    book_title: str,
    language: str,
    api_key: str,
    model: str,
    ner_candidates: dict[str, list[int]] | None = None,
) -> list[CharacterProfile]:
    """Merge all mentioned characters into deduplicated profiles via a single LLM call."""
    all_names: dict[str, list[int]] = {}
    for s in summaries:
        for name in s.characters_mentioned:
            all_names.setdefault(name, []).append(s.chunk_index)

    # Merge NER candidates (may include names from non-sampled chunks)
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

    # Build context from summaries
    context_lines = []
    for s in summaries:
        if s.summary:
            context_lines.append(f"段落{s.chunk_index}: {s.summary}")
    context = "\n".join(context_lines[:20])  # cap context length

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
            f"Chunk {s.chunk_index}: {s.summary}" for s in summaries[:20] if s.summary
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

    raw = call_llm(prompt, api_key=api_key, model=model, max_tokens=1500) or ""
    data = _parse_json(raw)

    if data is None:
        # Fallback: return raw character list without merging
        return [
            CharacterProfile(name=name, key_chapter_indices=idxs)
            for name, idxs in all_names.items()
        ]

    # data should be a list
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


_MAX_EXTRACT_CHUNKS = 60  # LLM-extract at most this many chunks


def _sample_indices(total: int, budget: int) -> list[int]:
    """Pick chunk indices to extract when total > budget.

    Strategy: uniform spread ensuring first, last, and evenly-spaced middle.
    """
    if total <= budget:
        return list(range(total))
    step = max(1, total / budget)
    sampled = {0, total - 1}
    sampled |= {min(int(i * step), total - 1) for i in range(budget)}
    indices = sorted(sampled)
    # Keep budget but always include first and last
    if len(indices) > budget:
        # Remove from the middle to stay in budget, keep endpoints
        middle = indices[1:-1]
        keep = budget - 2
        step_m = max(1, len(middle) / keep)
        kept = [middle[int(i * step_m)] for i in range(keep)]
        indices = sorted({0, total - 1} | set(kept))
    return indices


def extract_knowledge_graph(
    chunks: list,
    book_title: str,
    language: str = "zh",
    api_key: str | None = None,
    model: str = "claude-haiku-4-5",
    progress_callback: Callable[[int, int], None] | None = None,
    max_extract: int = _MAX_EXTRACT_CHUNKS,
) -> BookKnowledgeGraph:
    """Extract a BookKnowledgeGraph from chunked book text.

    Args:
        chunks: list[ChunkResult] from the analysis pipeline.
        book_title: Title of the book.
        language: Language code ("zh", "en", "ja").
        api_key: Anthropic API key.
        model: Claude model ID.
        progress_callback: Optional (current, total) progress reporter.
        max_extract: Max chunks to LLM-extract (others get empty summaries).

    Returns:
        BookKnowledgeGraph with chapter summaries and character profiles.
    """
    if not chunks or not api_key:
        return BookKnowledgeGraph(book_title=book_title, language=language)

    total = len(chunks)
    sample_set = set(_sample_indices(total, max_extract))
    extract_count = len(sample_set)

    logger.info(
        "Extracting %d/%d chunks (sampled)" if extract_count < total
        else "Extracting all %d chunks",
        extract_count, total,
    )

    # Step 0: fast local NER on ALL chunks (no LLM)
    ner_candidates: dict[str, list[int]] = {}
    try:
        ner_candidates = extract_character_candidates(chunks, language)
        logger.info("NER found %d character candidates across all chunks", len(ner_candidates))
    except Exception:
        logger.warning("NER extraction failed, continuing with LLM-only")

    # Step A: extract per-chunk summaries (sampled)
    summaries: list[ChapterSummary] = []
    progress_done = 0
    for i, chunk in enumerate(chunks):
        if i in sample_set:
            text = getattr(chunk, "text", str(chunk))
            summary = _extract_chunk_summary(
                chunk_index=i,
                chunk_text=text,
                language=language,
                api_key=api_key,
                model=model,
            )
            summaries.append(summary)
        else:
            # Non-sampled chunk: lightweight placeholder
            summaries.append(ChapterSummary(chunk_index=i))
        progress_done += 1
        if progress_callback is not None:
            progress_callback(progress_done, total)

    # Step B: merge characters (using only non-empty summaries)
    rich_summaries = [s for s in summaries if s.summary]
    characters = _merge_characters(
        summaries=rich_summaries,
        book_title=book_title,
        language=language,
        api_key=api_key,
        model=model,
        ner_candidates=ner_candidates,
    )

    return BookKnowledgeGraph(
        book_title=book_title,
        language=language,
        chapter_summaries=summaries,
        characters=characters,
    )
