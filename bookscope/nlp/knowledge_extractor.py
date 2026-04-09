"""BookScope v6 — Smart-sampling knowledge graph extractor.

Replaces the old full MapReduce approach (377 LLM calls for a 1069-chunk book)
with intelligent volume/arc grouping + budget-filling chunk selection (~19 calls).

Architecture:
    1. Detect volumes from chapter-number resets (第一章 reappearing)
    2. Group chapters into 10-15 narrative arcs
    3. Budget-fill each arc with chunks up to 25K chars (matching v5 depth)
    4. Arc-level deep analysis (one LLM call per arc)
    5. Character merge + outline + rhythm in parallel

Performance (1069-chunk / 159-chapter book):
    - Old v5: 376 LLM calls, 3.1M chars → ~20-40 min
    - New v6: ~19 LLM calls, ~375K chars → ~1-2 min (95% fewer calls)

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

import re as _re

from bookscope.models.schemas import (
    BookKnowledgeGraph,
    ChapterAnalysis,
    ChapterSummary,
    CharacterProfile,
    NarrativePoint,
    ThemeDescription,
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
    # Build index mapping for internal use; don't expose indices to LLM
    chunks_text = ""
    idx_map = {}  # position -> original chunk index
    for pos, (idx, text) in enumerate(batch):
        truncated = text[:_CHARS_PER_CHUNK]
        chunks_text += f"\n--- 以下内容 ---\n{truncated}\n"
        idx_map[pos] = idx

    if language == "zh":
        return (
            "你是一个书籍内容分析助手。请分析以下多个书籍片段，为每个片段返回摘要。\n"
            "所有输出内容必须使用中文，包括字段值。不允许英文单词或短语。\n"
            "严格返回合法JSON数组，不要返回markdown或其他文字。\n"
            "每个元素的schema:\n"
            '{"chunk_index": 片段序号(从0开始，按出现顺序), "title": "推断的章节标题", '
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
        f"{name}(多处出现)" for name in all_names.keys()
    )

    context_lines = []
    for s in summaries:
        if s.summary:
            context_lines.append(s.summary)
    context = "\n".join(context_lines[:30])  # cap context length

    prompt = (
        "你是一个书籍人物分析专家。根据以下信息，合并重复人物（同一人物的不同称呼），"
        "输出去重后的人物档案列表。\n"
        "所有输出内容必须使用中文，包括字段值。不允许英文单词或短语。\n"
        "要求：提取所有有名字的重要人物，至少8个（含配角和次要角色）。\n"
        "严格返回合法JSON数组，不要返回markdown或其他文字。\n"
        "每个人物的JSON schema:\n"
        '{"name": "主名称", "aliases": ["别名1"], '
        '"description": "至少50字的人物描述，包含身份背景、性格特征、关键行为、在故事中的作用", '
        '"voice_style": "具体描述说话风格，给出示例性语句", '
        '"motivations": ["动机1"], '
        '"key_chapter_indices": [0, 1], '
        '"arc_summary": "描述人物在全书中的变化轨迹"}\n\n'
        f"书名: {book_title}\n"
        f"出现的人物: {names_info}\n\n"
        f"内容摘要:\n{context}"
    )
    if language == "en":
        names_info_en = ", ".join(
            f"{name}(appears multiple times)" for name in all_names.keys()
        )
        context_en = "\n".join(
            s.summary for s in summaries[:30] if s.summary
        )
        prompt = (
            "You are a book character analyst. Merge duplicate characters "
            "(same person with different names/titles) and produce deduplicated "
            "character profiles.\n"
            "Extract all named important characters, at least 8 (including supporting roles).\n"
            "Return ONLY a valid JSON array, no markdown or explanation.\n"
            "Each character schema:\n"
            '{"name": "primary name", "aliases": ["alias1"], '
            '"description": "at least 50 words: background, personality, '
            'key actions, role in story", '
            '"voice_style": "specific speech style with example phrases", '
            '"motivations": ["motivation1"], '
            '"key_chapter_indices": [0, 1], '
            '"arc_summary": "character arc across the book"}\n\n'
            f"Book: {book_title}\n"
            f"Characters: {names_info_en}\n\n"
            f"Content summaries:\n{context_en}"
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
#  Deep chapter analysis — chapter grouping + per-chapter deep analysis
# ---------------------------------------------------------------------------

_HEADER_RE = _re.compile(r"^\[《.+?》(.+?)\]\n?")
_MAX_CHAPTER_CHARS = 25000  # max chars per chapter LLM call (~12K tokens)


def _group_chunks_by_chapter(
    chunks: list,
) -> list[tuple[str, list[int]]]:
    """Group chunk indices by their chapter header.

    Returns [(chapter_title, [chunk_indices])], ordered by first appearance.
    """
    chapters: dict[str, list[int]] = {}
    order: list[str] = []

    for chunk in chunks:
        text = getattr(chunk, "text", str(chunk))
        match = _HEADER_RE.match(text)
        key = match.group(1) if match else "未分章"
        if key not in chapters:
            chapters[key] = []
            order.append(key)
        chapters[key].append(getattr(chunk, "index", 0))

    return [(key, chapters[key]) for key in order]


# ---------------------------------------------------------------------------
#  Smart grouping: volumes → arcs → representative chunks
# ---------------------------------------------------------------------------

_CH_NUM_RE = _re.compile(r"^第一章\s")


def _detect_volumes(
    chapter_groups: list[tuple[str, list[int]]],
) -> list[list[tuple[str, list[int]]]]:
    """Detect volume boundaries by chapter-number resets.

    When '第一章' appears again, it marks the start of a new volume.
    Returns a list of volumes, each being a list of (title, chunk_indices).
    """
    if not chapter_groups:
        return []

    volumes: list[list[tuple[str, list[int]]]] = [[chapter_groups[0]]]

    for title, indices in chapter_groups[1:]:
        if _CH_NUM_RE.match(title):
            volumes.append([])
        volumes[-1].append((title, indices))

    # Merge tiny first volume (e.g. 序章 alone) into next volume
    if len(volumes) > 1 and len(volumes[0]) <= 2:
        volumes[1] = volumes[0] + volumes[1]
        volumes.pop(0)

    return volumes


def _split_volume_into_arcs(
    volume: list[tuple[str, list[int]]],
    max_chapters_per_arc: int = 8,
    min_chapters_per_arc: int = 3,
) -> list[list[tuple[str, list[int]]]]:
    """Split a volume into narrative arcs of manageable size.

    Each arc has min_chapters_per_arc..max_chapters_per_arc chapters.
    """
    n = len(volume)
    if n <= max_chapters_per_arc:
        return [volume]

    # Calculate how many arcs we need
    n_arcs = max(2, (n + max_chapters_per_arc - 1) // max_chapters_per_arc)
    arc_size = n // n_arcs

    arcs: list[list[tuple[str, list[int]]]] = []
    start = 0
    for i in range(n_arcs):
        end = start + arc_size if i < n_arcs - 1 else n
        # Ensure last arc gets remaining chapters
        if i == n_arcs - 1:
            end = n
        arcs.append(volume[start:end])
        start = end

    return [a for a in arcs if a]


def _build_arcs(
    chunks: list,
    target_arcs: int = 12,
) -> list[dict]:
    """Build narrative arcs from chapters via volume detection + splitting.

    Returns list of arc dicts:
        {
            "arc_index": int,
            "title": str,           # derived from first-last chapter titles
            "chapter_titles": [str],
            "all_chunk_indices": [int],
            "representative_chunks": [int],  # budget-filled chunks (~25K chars)
        }
    """
    chapter_groups = _group_chunks_by_chapter(chunks)
    if not chapter_groups:
        return []

    volumes = _detect_volumes(chapter_groups)
    logger.info("Detected %d volumes from %d chapters", len(volumes), len(chapter_groups))

    # Determine max arc size to hit target
    total_chapters = len(chapter_groups)
    max_per_arc = max(3, total_chapters // target_arcs + 1)

    all_arcs: list[list[tuple[str, list[int]]]] = []
    for volume in volumes:
        arcs = _split_volume_into_arcs(volume, max_chapters_per_arc=max_per_arc)
        all_arcs.extend(arcs)

    # Build arc descriptors with representative chunk selection
    result = []
    for arc_idx, arc_chapters in enumerate(all_arcs):
        titles = [t for t, _ in arc_chapters]
        all_indices: list[int] = []
        for _, indices in arc_chapters:
            all_indices.extend(indices)

        # Select representative chunks: first + last + longest middle
        rep_chunks = _select_representative_chunks(all_indices, chunks)

        # Build arc title from first and last chapter
        if len(titles) == 1:
            arc_title = titles[0]
        else:
            arc_title = f"{titles[0]} — {titles[-1]}"

        result.append({
            "arc_index": arc_idx,
            "title": arc_title,
            "chapter_titles": titles,
            "all_chunk_indices": all_indices,
            "representative_chunks": rep_chunks,
        })

    logger.info(
        "Built %d arcs from %d chapters, %d representative chunks total",
        len(result), total_chapters,
        sum(len(a["representative_chunks"]) for a in result),
    )
    return result


_MIN_CONTENT_LEN = 500  # Skip chunks shorter than this (likely TOC/headers)
_MAX_ARC_CHARS = 25000  # Text budget per arc (matches v5's per-chapter cap)


def _select_representative_chunks(
    indices: list[int],
    chunks: list,
    char_budget: int = _MAX_ARC_CHARS,
) -> list[int]:
    """Pick chunk indices to fill a character budget for an arc.

    Strategy (budget-filling):
      1. Filter out TOC/header-only chunks (< 500 chars)
      2. Seed with first + last + evenly-spaced anchors (coverage skeleton)
      3. Fill remaining budget by adding longest unselected chunks
      4. Stop when total selected text >= char_budget

    This ensures each arc gets ~25K chars of context (matching v5 depth)
    regardless of how many chunks the arc contains.
    """
    if not indices:
        return []

    # Score chunks by content length (skip headers)
    scored: list[tuple[int, int]] = []
    for idx in indices:
        if idx < len(chunks):
            text = getattr(chunks[idx], "text", str(chunks[idx]))
            content = _HEADER_RE.sub("", text, count=1).strip()
            scored.append((idx, len(content)))

    # Filter out tiny chunks (TOC/section headers)
    meaningful = [(idx, length) for idx, length in scored if length >= _MIN_CONTENT_LEN]
    if not meaningful:
        meaningful = scored[:3] if scored else []

    total_meaningful_chars = sum(length for _, length in meaningful)

    # If all meaningful chunks fit in budget, return all
    if total_meaningful_chars <= char_budget:
        return [idx for idx, _ in meaningful]

    # Seed: first + last + evenly-spaced anchors for structural coverage
    n = len(meaningful)
    n_anchors = min(5, n)  # 5 evenly-spaced anchor points
    anchor_positions = {0, n - 1}
    if n_anchors > 2:
        step = (n - 1) / (n_anchors - 1)
        for i in range(1, n_anchors - 1):
            anchor_positions.add(round(i * step))

    selected_set: set[int] = set()
    used_chars = 0
    for pos in sorted(anchor_positions):
        idx, length = meaningful[pos]
        selected_set.add(idx)
        used_chars += length

    # Fill remaining budget with longest unselected chunks
    remaining = [(idx, length) for idx, length in meaningful if idx not in selected_set]
    remaining.sort(key=lambda x: x[1], reverse=True)  # longest first

    for idx, length in remaining:
        if used_chars >= char_budget:
            break
        selected_set.add(idx)
        used_chars += length

    return sorted(selected_set)


def _get_chapter_text(chunks: list, indices: list[int]) -> str:
    """Concatenate chunk texts for a chapter, stripping headers."""
    parts = []
    for idx in indices:
        if idx < len(chunks):
            text = getattr(chunks[idx], "text", str(chunks[idx]))
            # Strip the contextual header line
            text = _HEADER_RE.sub("", text, count=1).strip()
            parts.append(text)
    return "\n\n".join(parts)


def _analyze_chapter_deep(
    chapter_title: str,
    chapter_text: str,
    chapter_index: int,
    book_title: str,
    language: str,
    api_key: str,
    model: str,
    book_type: str = "fiction",
) -> ChapterAnalysis | None:
    """Send full chapter text to LLM for deep analysis."""
    truncated = chapter_text[:_MAX_CHAPTER_CHARS]
    is_nonfiction = book_type in ("nonfiction", "academic", "technical", "self_help")
    is_essay = book_type in ("essay", "biography", "poetry")

    if language == "zh":
        if is_nonfiction:
            focus = (
                "分析重点：核心论点/史实、论据/证据链、知识结构、与全书论证的关系。"
                "人物列为历史人物/关键人物（非虚构角色）。"
            )
        elif is_essay:
            focus = (
                "分析重点：作者观点/立论、叙事策略、历史考证或个人经验、写作手法。"
                "人物列为传主或关键人物。"
            )
        else:
            focus = (
                "分析重点：情节发展、角色塑造与弧线、冲突/矛盾、叙事手法。"
                "人物列为虚构角色。"
            )
        prompt = (
            "你是一位资深书籍分析专家。请对以下章节进行深度分析。\n"
            "所有输出内容必须使用中文，包括字段值。不允许英文单词或短语。\n"
            f"{focus}\n"
            "严格返回合法JSON，不要返回markdown或其他文字。\n\n"
            "JSON schema:\n"
            "{\n"
            '  "analysis": "至少300字的深度分析，包含：核心情节推进、'
            '人物发展变化、主题意义。要具体引用原文细节，避免笼统概括",\n'
            '  "key_points": ["要点1（2-3句话，不要泛泛而谈）", "要点2", "要点3"],\n'
            '  "characters_involved": ["人物名1", "人物名2"],\n'
            '  "significance": "具体说明本章对全书的作用，不要空泛"\n'
            "}\n\n"
            f"书名：{book_title}\n"
            f"章节：{chapter_title}\n\n"
            f"【章节全文】\n{truncated}"
        )
    else:
        if is_nonfiction:
            focus = (
                "Focus: core arguments/facts, evidence chains, knowledge structure, "
                "relationship to overall thesis. List people as historical/key figures."
            )
        elif is_essay:
            focus = (
                "Focus: author's viewpoint, narrative strategy, evidence or experience, "
                "writing techniques. List people as subjects or key figures."
            )
        else:
            focus = (
                "Focus: plot development, character arcs, conflicts, narrative techniques. "
                "List people as fictional characters."
            )
        prompt = (
            "You are an expert book analyst. Provide a deep analysis of the following chapter.\n"
            f"{focus}\n"
            "Return ONLY valid JSON, no markdown or explanation.\n\n"
            "JSON schema:\n"
            "{\n"
            '  "analysis": "at least 300 words: plot progression, '
            'character development, thematic significance. '
            'Be specific, cite details, avoid generic statements",\n'
            '  "key_points": ["point 1 (2-3 sentences, be specific)", "point 2", "point 3"],\n'
            '  "characters_involved": ["person1", "person2"],\n'
            '  "significance": "specific contribution of this chapter to the book, not vague"\n'
            "}\n\n"
            f"Book: {book_title}\n"
            f"Chapter: {chapter_title}\n\n"
            f"[FULL CHAPTER TEXT]\n{truncated}"
        )

    # Budget more tokens for deep analysis
    raw = call_llm(prompt, api_key=api_key, model=model, max_tokens=2000) or ""
    data = _parse_json(raw)

    if data is None or not isinstance(data, dict):
        return None

    return ChapterAnalysis(
        chapter_index=chapter_index,
        title=chapter_title,
        analysis=str(data.get("analysis", "")),
        key_points=[str(p) for p in data.get("key_points", []) if p],
        characters_involved=[str(c) for c in data.get("characters_involved", []) if c],
        significance=str(data.get("significance", "")),
    )


def _analyze_arc(
    arc: dict,
    chunks: list,
    book_title: str,
    language: str,
    api_key: str,
    model: str,
    book_type: str = "fiction",
) -> ChapterAnalysis | None:
    """Analyze a narrative arc using its representative chunks.

    Sends 2-3 representative chunks (not the full arc text) to the LLM,
    plus chapter titles for context. Much faster than per-chapter analysis.
    """
    rep_indices = arc["representative_chunks"]
    chapter_titles = arc["chapter_titles"]

    # Build context from representative chunks (no per-chunk cap, arc-level budget)
    rep_text_parts = []
    total_text_chars = 0
    for idx in rep_indices:
        if idx < len(chunks):
            text = getattr(chunks[idx], "text", str(chunks[idx]))
            text = _HEADER_RE.sub("", text, count=1).strip()
            if total_text_chars + len(text) > _MAX_ARC_CHARS:
                # Truncate last chunk to fit budget
                remaining = _MAX_ARC_CHARS - total_text_chars
                if remaining > 200:
                    rep_text_parts.append(text[:remaining])
                    total_text_chars += remaining
                break
            rep_text_parts.append(text)
            total_text_chars += len(text)

    rep_text = "\n\n---\n\n".join(rep_text_parts)
    n_chapters = len(chapter_titles)

    is_nonfiction = book_type in ("nonfiction", "academic", "technical", "self_help")
    is_essay = book_type in ("essay", "biography", "poetry")

    # Build chapter title listing for structural context
    titles_numbered = "\n".join(f"  {i+1}. {t}" for i, t in enumerate(chapter_titles))

    if language == "zh":
        if is_nonfiction:
            focus = "分析重点：核心论点/史实、论据/证据链、知识结构。"
        elif is_essay:
            focus = "分析重点：作者观点、叙事策略、写作手法。"
        else:
            focus = "分析重点：情节发展、角色塑造与弧线、冲突/矛盾、叙事手法。"

        prompt = (
            "你是一位资深书籍分析专家。以下是一本书中某段叙事弧的代表性片段和章节列表。\n"
            "请结合章节标题（提供整体结构）和代表性片段（提供具体内容），\n"
            "对这段叙事弧进行深度分析。即使代表性片段无法覆盖所有章节，\n"
            "也请根据章节标题推断整体叙事脉络。\n"
            "所有输出内容必须使用中文，包括字段值。不允许英文单词或短语。\n"
            f"{focus}\n"
            "严格返回合法JSON，不要返回markdown或其他文字。\n\n"
            "JSON schema:\n"
            "{\n"
            '  "analysis": "至少300字的深度分析，要具体、有深度，引用原文细节，避免笼统概括",\n'
            '  "key_points": ["要点1（2-3句话，不要泛泛而谈）", "要点2", "要点3", "要点4"],\n'
            '  "characters_involved": ["人物名1", "人物名2"],\n'
            '  "significance": "具体说明这段叙事弧在全书中的位置和作用"\n'
            "}\n\n"
            f"书名：{book_title}\n"
            f"本弧涵盖{n_chapters}个章节：\n{titles_numbered}\n\n"
            f"【代表性片段（{len(rep_indices)}个）】\n{rep_text}"
        )
    else:
        if is_nonfiction:
            focus = "Focus: core arguments/facts, evidence chains, knowledge structure."
        elif is_essay:
            focus = "Focus: author's viewpoint, narrative strategy, writing techniques."
        else:
            focus = "Focus: plot development, character arcs, conflicts, narrative techniques."

        titles_numbered_en = "\n".join(f"  {i+1}. {t}" for i, t in enumerate(chapter_titles))
        prompt = (
            "You are an expert book analyst. Below are chapter titles (for structure) "
            "and representative excerpts (for detail) from a narrative arc.\n"
            "Use both chapter titles and excerpts to produce a deep analysis. "
            "Infer the overall narrative arc even from partial excerpts.\n"
            f"{focus}\n"
            "Return ONLY valid JSON, no markdown or explanation.\n\n"
            "JSON schema:\n"
            "{\n"
            '  "analysis": "300-800 word deep analysis of this narrative arc",\n'
            '  "key_points": ["point 1", "point 2", "point 3", "point 4"],\n'
            '  "characters_involved": ["person1", "person2"],\n'
            '  "significance": "1-2 sentences: role of this arc in the overall book"\n'
            "}\n\n"
            f"Book: {book_title}\n"
            f"This arc covers {n_chapters} chapters:\n{titles_numbered_en}\n\n"
            f"[REPRESENTATIVE EXCERPTS ({len(rep_indices)})]\n{rep_text}"
        )

    raw = call_llm(prompt, api_key=api_key, model=model, max_tokens=2000) or ""
    data = _parse_json(raw)

    if data is None or not isinstance(data, dict):
        return None

    return ChapterAnalysis(
        chapter_index=arc["arc_index"],
        title=arc["title"],
        chunk_indices=arc["all_chunk_indices"],
        analysis=str(data.get("analysis", "")),
        key_points=[str(p) for p in data.get("key_points", []) if p],
        characters_involved=[str(c) for c in data.get("characters_involved", []) if c],
        significance=str(data.get("significance", "")),
    )


def _generate_book_outline(
    chapter_analyses: list[ChapterAnalysis],
    book_title: str,
    language: str,
    api_key: str,
    model: str,
    book_type: str = "fiction",
) -> tuple[str, list[ThemeDescription]]:
    """Generate a structured book outline from all chapter analyses."""
    is_nonfiction = book_type in ("nonfiction", "academic", "technical", "self_help")
    is_essay = book_type in ("essay", "biography", "poetry")

    # Build chapter summary context
    chapter_lines = []
    for ca in chapter_analyses:
        brief = ca.analysis[:200] if ca.analysis else "(无分析)"
        chapter_lines.append(f"第{ca.chapter_index}章 {ca.title}: {brief}...")

    context = "\n".join(chapter_lines[:50])

    if language == "zh":
        if is_nonfiction:
            outline_desc = (
                "500-1000字的全书结构化大纲：核心论点/历史脉络、论证结构、"
                "各章如何构成完整论证、作者的研究方法和立场"
            )
            theme_desc = "核心论点/知识主题"
        elif is_essay:
            outline_desc = (
                "500-1000字的全书结构化大纲：作者核心观点、叙事线索、"
                "各章如何推进论述、写作风格和意图"
            )
            theme_desc = "核心议题/思想主题"
        else:
            outline_desc = (
                "500-1000字的全书结构化大纲：全书主旨、各部分如何构成整体、"
                "核心叙事脉络、作者的写作意图和方法"
            )
            theme_desc = "核心主题"
        prompt = (
            "你是一位资深书籍分析专家。根据以下各章节分析，撰写全书大纲。\n"
            "所有输出内容必须使用中文，包括字段值。不允许英文单词或短语。\n"
            "严格返回合法JSON，不要返回markdown或其他文字。\n\n"
            "JSON schema:\n"
            "{\n"
            f'  "outline": "{outline_desc}",\n'
            '  "themes": [\n'
            f'    {{"theme": "{theme_desc}名", "description": "2-3句详细描述"}},\n'
            "    ...\n"
            "  ]\n"
            "}\n\n"
            f"书名：{book_title}\n"
            f"共{len(chapter_analyses)}章\n\n"
            f"各章节分析摘要：\n{context}"
        )
    else:
        if is_nonfiction:
            outline_desc = (
                "500-1000 word structured outline: core thesis, argument structure, "
                "how chapters build the case, author's methodology and stance"
            )
        elif is_essay:
            outline_desc = (
                "500-1000 word structured outline: author's perspective, narrative thread, "
                "how chapters advance the argument, writing style and intent"
            )
        else:
            outline_desc = (
                "500-1000 word structured outline: thesis, how parts form the whole, "
                "core narrative thread, author intent and approach"
            )
        prompt = (
            "You are an expert book analyst. Based on the chapter analyses below, "
            "write a structured book outline.\n"
            "Return ONLY valid JSON, no markdown or explanation.\n\n"
            "JSON schema:\n"
            "{\n"
            f'  "outline": "{outline_desc}",\n'
            '  "themes": [\n'
            '    {"theme": "theme name", "description": "2-3 sentence description"},\n'
            "    ...\n"
            "  ]\n"
            "}\n\n"
            f"Book: {book_title}\n"
            f"{len(chapter_analyses)} chapters\n\n"
            f"Chapter analysis summaries:\n{context}"
        )

    raw = call_llm(prompt, api_key=api_key, model=model, max_tokens=2500) or ""
    data = _parse_json(raw)

    outline = ""
    themes: list[ThemeDescription] = []

    if data and isinstance(data, dict):
        outline = str(data.get("outline", ""))
        for t in data.get("themes", []):
            if isinstance(t, dict):
                themes.append(ThemeDescription(
                    theme=str(t.get("theme", "")),
                    description=str(t.get("description", "")),
                ))

    return outline, themes


def _generate_narrative_rhythm(
    chapter_analyses: list[ChapterAnalysis],
    book_title: str,
    language: str,
    api_key: str,
    model: str,
    book_type: str = "fiction",
) -> list[NarrativePoint]:
    """Generate narrative rhythm annotations from chapter analyses.

    Replaces abstract valence numbers with concrete event-annotated
    intensity ratings per chapter. Prompts adapt to book_type.
    """
    is_nonfiction = book_type in ("nonfiction", "academic", "technical", "self_help")

    chapter_lines = []
    for ca in chapter_analyses:
        brief = ca.analysis[:150] if ca.analysis else "(无)"
        points = ", ".join(ca.key_points[:3]) if ca.key_points else ""
        chapter_lines.append(
            f"第{ca.chapter_index}章 {ca.title}: {brief} | 要点: {points}"
        )

    context = "\n".join(chapter_lines[:50])

    if language == "zh":
        if is_nonfiction:
            type_guide = (
                "point_type 说明（非虚构/学术）:\n"
                "- setup: 背景交代/问题引入\n"
                "- rising: 论证推进/证据积累\n"
                "- climax: 核心论点/关键发现\n"
                "- turning: 观点转变/新视角引入\n"
                "- falling: 补充论证/反思\n"
                "- resolution: 结论/总结\n\n"
                "intensity 评分标准:\n"
                "- 0.0-0.3: 背景铺垫、定义说明\n"
                "- 0.3-0.6: 论证展开、案例分析\n"
                "- 0.6-0.8: 重要论点/关键史实\n"
                "- 0.8-1.0: 核心结论/全书关键发现\n\n"
                "event_label 要写具体的论点/史实（如'朱棣起兵靖难'），不要写抽象描述。"
            )
        else:
            type_guide = (
                "point_type 说明:\n"
                "- setup: 铺垫/背景交代\n"
                "- rising: 情节上升/矛盾积累\n"
                "- climax: 高潮/最激烈冲突\n"
                "- turning: 关键转折点\n"
                "- falling: 情节下降/后续影响\n"
                "- resolution: 收束/结局\n\n"
                "intensity 评分标准:\n"
                "- 0.0-0.3: 平缓叙述、铺垫、日常\n"
                "- 0.3-0.6: 有进展但无剧烈冲突\n"
                "- 0.6-0.8: 重要事件/转折\n"
                "- 0.8-1.0: 高潮/全书关键节点\n\n"
                "event_label 要写具体事件（如'宝黛初会'），不要写抽象描述。"
            )
        prompt = (
            "你是叙事分析专家。根据以下各章节分析，为每章标注叙事节奏。\n"
            "所有输出内容必须使用中文，包括title和event_label。不允许英文单词或短语。\n"
            "严格返回合法JSON数组，不要返回markdown或其他文字。\n\n"
            "每个元素的schema:\n"
            "{\n"
            '  "chapter_index": 章节序号(整数),\n'
            '  "title": "章节标题",\n'
            '  "intensity": 0.0-1.0的叙事张力/重要性评分,\n'
            '  "event_label": "本章最关键的一个事件/论点（5-15字）",\n'
            '  "point_type": "setup/rising/climax/turning/falling/resolution 之一"\n'
            "}\n\n"
            f"{type_guide}\n"
            f"书名：{book_title}\n"
            f"共{len(chapter_analyses)}章\n\n"
            f"各章分析：\n{context}"
        )
    else:
        prompt = (
            "You are a narrative analysis expert. Based on the chapter analyses below, "
            "annotate the narrative rhythm for each chapter.\n"
            "Return ONLY a valid JSON array, no markdown or explanation.\n\n"
            "Each element schema:\n"
            "{\n"
            '  "chapter_index": chapter number (integer),\n'
            '  "title": "chapter title",\n'
            '  "intensity": 0.0-1.0 narrative tension/importance score,\n'
            '  "event_label": "the single most important event/argument '
            '(5-15 words, specific not abstract)",\n'
            '  "point_type": "one of: setup/rising/climax/turning/falling/resolution"\n'
            "}\n\n"
            f"Book: {book_title}\n"
            f"{len(chapter_analyses)} chapters\n\n"
            f"Chapter analyses:\n{context}"
        )

    raw = call_llm(prompt, api_key=api_key, model=model, max_tokens=2000) or ""
    data = _parse_json(raw)

    points: list[NarrativePoint] = []
    if data and isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                intensity = item.get("intensity", 0.5)
                if isinstance(intensity, (int, float)):
                    intensity = max(0.0, min(1.0, float(intensity)))
                else:
                    intensity = 0.5
                points.append(NarrativePoint(
                    chapter_index=int(item.get("chapter_index", 0)),
                    title=str(item.get("title", "")),
                    intensity=intensity,
                    event_label=str(item.get("event_label", "")),
                    point_type=str(item.get("point_type", "narrative")),
                ))

    # Sort by chapter index
    points.sort(key=lambda p: p.chapter_index)
    return points


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
    max_extract: int = 0,  # ignored in v6, kept for API compat
    enrich_souls: bool = False,
    batch_size: int = _BATCH_SIZE,
    max_workers: int = _MAX_WORKERS,
    book_type: str = "fiction",
) -> BookKnowledgeGraph:
    """Extract a BookKnowledgeGraph using smart arc-based sampling (v6).

    Instead of processing every chunk (377 LLM calls for 1069 chunks),
    groups chapters into ~10-15 narrative arcs and samples 2-3 representative
    chunks per arc, reducing to ~25-30 LLM calls total.

    Pipeline:
        1. Local NER (no LLM) — character candidates
        2. Smart grouping: chapters → volumes → arcs
        3. Arc-level deep analysis (concurrent, ~10-15 calls)
        4. Character merge from arc analyses (1 call)
        5. Book outline + narrative rhythm + summary (3 calls, concurrent)

    Args:
        chunks: list[ChunkResult] from the analysis pipeline.
        book_title: Title of the book.
        language: Language code ("zh", "en", "ja").
        api_key: LLM API key (from BYOK settings).
        model: LLM model ID.
        progress_callback: Optional (current, total) progress reporter.
        enrich_souls: If True, enrich top 5 characters with soul profiles.
        max_workers: Concurrent LLM call threads (default 4).
        book_type: "fiction" / "nonfiction" / "essay" etc.

    Returns:
        BookKnowledgeGraph with arc analyses, characters, outline, rhythm.
    """
    if not chunks or not api_key:
        return BookKnowledgeGraph(book_title=book_title, language=language)

    total = len(chunks)

    # ── Step 1+2: NER + Smart grouping (parallel) ────────────────────
    # NER is CPU-intensive (~87s for 1069 chunks). Run it alongside
    # arc grouping and arc analysis instead of blocking.
    ner_candidates: dict[str, list[int]] = {}
    ner_future = None

    def _run_ner():
        return extract_character_candidates(chunks, language)

    # Start NER in background — results used later at character merge
    ner_executor = ThreadPoolExecutor(max_workers=1)
    try:
        ner_future = ner_executor.submit(_run_ner)
    except Exception:
        logger.warning("Failed to start NER thread")

    arcs = _build_arcs(chunks, target_arcs=12)
    n_arcs = len(arcs)
    total_rep = sum(len(a["representative_chunks"]) for a in arcs)
    logger.info(
        "Smart grouping: %d chunks → %d arcs, %d representative chunks "
        "(%.0f%% of original, ~%d LLM calls vs ~%d old)",
        total, n_arcs, total_rep,
        total_rep / max(total, 1) * 100,
        n_arcs + 4,  # arcs + merge + outline + rhythm + summary
        total // batch_size + len(_group_chunks_by_chapter(chunks)) + 4,
    )

    # Total steps for progress: arcs + 3 (merge + outline + rhythm&summary)
    total_steps = n_arcs + 3
    steps_done = 0

    def _report(done: int):
        nonlocal steps_done
        steps_done = done
        if progress_callback:
            progress_callback(min(steps_done, total_steps), total_steps)

    # ── Step 3: Arc-level deep analysis (concurrent) ──────────────────
    chapter_analyses: list[ChapterAnalysis] = []

    def _analyze_one_arc(arc: dict) -> ChapterAnalysis | None:
        return _analyze_arc(
            arc=arc,
            chunks=chunks,
            book_title=book_title,
            language=language,
            api_key=api_key,
            model=model,
            book_type=book_type,
        )

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_arc = {
            executor.submit(_analyze_one_arc, arc): arc
            for arc in arcs
        }
        for future in as_completed(future_to_arc):
            arc = future_to_arc[future]
            try:
                result = future.result()
                if result:
                    chapter_analyses.append(result)
            except Exception:
                logger.warning("Arc analysis failed: %s", arc["title"])
            steps_done += 1
            _report(steps_done)

    chapter_analyses.sort(key=lambda ca: ca.chapter_index)
    logger.info("Completed arc-level analysis for %d arcs", len(chapter_analyses))

    # ── Collect NER results (started in parallel with Step 2+3) ────────
    if ner_future is not None:
        try:
            ner_candidates = ner_future.result(timeout=120)
            logger.info("NER found %d character candidates", len(ner_candidates))
        except Exception:
            logger.warning("NER extraction failed, continuing with LLM-only")
    ner_executor.shutdown(wait=False)

    # ── Step 4: Character merge ───────────────────────────────────────
    # Build pseudo-summaries from arc analyses for character merging
    arc_summaries = [
        ChapterSummary(
            chunk_index=ca.chapter_index,
            title=ca.title,
            summary=ca.analysis[:300] if ca.analysis else "",
            characters_mentioned=ca.characters_involved,
        )
        for ca in chapter_analyses
    ]

    characters = _merge_characters(
        summaries=arc_summaries,
        book_title=book_title,
        language=language,
        api_key=api_key,
        model=model,
        ner_candidates=ner_candidates,
    )
    _report(steps_done + 1)
    logger.info("Merged %d characters", len(characters))

    # ── Step 5: Outline + Rhythm + Summary (concurrent) ───────────────
    book_outline = ""
    theme_analyses: list[ThemeDescription] = []
    narrative_rhythm: list[NarrativePoint] = []
    overall_summary = ""

    def _do_outline():
        return _generate_book_outline(
            chapter_analyses=chapter_analyses,
            book_title=book_title,
            language=language,
            api_key=api_key,
            model=model,
            book_type=book_type,
        )

    def _do_rhythm():
        return _generate_narrative_rhythm(
            chapter_analyses=chapter_analyses,
            book_title=book_title,
            language=language,
            api_key=api_key,
            model=model,
            book_type=book_type,
        )

    def _do_summary():
        summary_parts = [
            f"{ca.title}: {ca.analysis[:150]}"
            for ca in chapter_analyses if ca.analysis
        ]
        if not summary_parts:
            return ""
        context = "\n".join(summary_parts)
        prompt = (
            "根据以下书籍各段叙事弧分析，生成一段200-400字的全书总体概述。"
            "所有输出必须使用中文。严格返回纯文本，不要返回JSON或markdown。\n\n"
            f"书名：{book_title}\n\n{context}"
        ) if language == "zh" else (
            "Based on the following narrative arc analyses, write a 200-400 word "
            "overall summary. Return plain text only.\n\n"
            f"Book: {book_title}\n\n{context}"
        )
        return call_llm(prompt, api_key=api_key, model=model, max_tokens=800) or ""

    if chapter_analyses:
        with ThreadPoolExecutor(max_workers=3) as executor:
            f_outline = executor.submit(_do_outline)
            f_rhythm = executor.submit(_do_rhythm)
            f_summary = executor.submit(_do_summary)

            try:
                book_outline, theme_analyses = f_outline.result()
            except Exception:
                logger.warning("Outline generation failed")
            try:
                narrative_rhythm = f_rhythm.result()
            except Exception:
                logger.warning("Rhythm generation failed")
            try:
                overall_summary = f_summary.result()
            except Exception:
                logger.warning("Summary generation failed")

    _report(total_steps)
    logger.info(
        "KG complete: %d arcs, %d chars, outline=%d chars, rhythm=%d pts",
        len(chapter_analyses), len(characters),
        len(book_outline), len(narrative_rhythm),
    )

    # ── Optional: enrich top characters ───────────────────────────────
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

    return BookKnowledgeGraph(
        book_title=book_title,
        language=language,
        chapter_summaries=[],  # v6: skip per-chunk summaries for speed
        chapter_analyses=chapter_analyses,
        characters=characters,
        overall_summary=overall_summary,
        book_outline=book_outline,
        theme_analyses=theme_analyses,
        narrative_rhythm=narrative_rhythm,
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
