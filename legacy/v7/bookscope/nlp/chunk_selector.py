"""BookScope v7 — Phase 2: Smart chunk selection from Phase 1 scan data.

No LLM calls. Pure algorithmic selection based on Phase 1 metadata.

Selection criteria (scored per chunk):
    1. Tension peaks — local maxima in narrative tension
    2. Event importance — chunks with high-importance events
    3. Character novelty — chunks introducing characters for the first time
    4. Structural coverage — ensure every arc/chapter gets representation
    5. Information density — chunks with more entities/events per character

The selector ensures:
    - Every chapter/arc gets at least 1 representative chunk
    - High-tension peaks are never missed
    - Character introductions are always included
    - Final selection is 30-50 chunks (configurable)
"""

from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict

from bookscope.models.schemas import ChunkScanResult

logger = logging.getLogger(__name__)

_HEADER_RE = re.compile(r"^\[《.+?》(.+?)\]\n?")

# Default target: select top N chunks for deep analysis
_DEFAULT_TARGET = 50
_MIN_TARGET = 20
_MAX_TARGET = 80


def select_key_chunks(
    scan_results: list[ChunkScanResult],
    chunks: list,
    target: int = _DEFAULT_TARGET,
) -> list[int]:
    """Phase 2: Select the most information-dense chunk indices.

    Returns sorted list of chunk indices for Phase 3 deep analysis.
    Guarantees structural coverage (every chapter gets at least 1 chunk).
    """
    if not scan_results:
        return []

    target = max(_MIN_TARGET, min(_MAX_TARGET, target))
    n = len(scan_results)

    # For small books, just return all
    if n <= target:
        return [sr.chunk_index for sr in scan_results]

    # Build chapter grouping from chunk headers
    chapter_chunks = _group_by_chapter(chunks)

    # Track first appearance of each character
    char_first_seen = _find_character_introductions(scan_results)

    # Score each chunk
    scores: list[tuple[int, float]] = []
    for sr in scan_results:
        score = _score_chunk(sr, char_first_seen, scan_results)
        scores.append((sr.chunk_index, score))

    # Phase A: Mandatory selections (structural coverage + tension peaks)
    mandatory = set()

    # A1: Ensure every chapter gets at least 1 chunk
    for _chapter, indices in chapter_chunks.items():
        if not indices:
            continue
        # Pick the highest-scored chunk from each chapter
        chapter_scores = [
            (idx, s) for idx, s in scores if idx in set(indices)
        ]
        if chapter_scores:
            best = max(chapter_scores, key=lambda x: x[1])
            mandatory.add(best[0])

    # A2: Tension peaks (local maxima with tension > 0.6)
    tension_peaks = _find_tension_peaks(scan_results, threshold=0.6)
    mandatory.update(tension_peaks)

    # A3: Character introduction chunks
    mandatory.update(char_first_seen.values())

    # A4: First and last chunks (opening + ending)
    if scan_results:
        mandatory.add(scan_results[0].chunk_index)
        mandatory.add(scan_results[-1].chunk_index)

    # Phase B: Fill remaining slots with highest-scored chunks
    remaining_budget = target - len(mandatory)
    if remaining_budget > 0:
        # Sort non-mandatory chunks by score descending
        candidates = [
            (idx, s) for idx, s in scores if idx not in mandatory
        ]
        candidates.sort(key=lambda x: x[1], reverse=True)
        for idx, _s in candidates[:remaining_budget]:
            mandatory.add(idx)

    selected = sorted(mandatory)

    logger.info(
        "Phase 2 selection: %d/%d chunks selected "
        "(%.0f%% coverage, %d chapters covered, %d tension peaks, "
        "%d character intros)",
        len(selected), n,
        len(selected) / n * 100,
        len(chapter_chunks),
        len(tension_peaks),
        len(char_first_seen),
    )
    return selected


def _score_chunk(
    sr: ChunkScanResult,
    char_first_seen: dict[str, int],
    all_results: list[ChunkScanResult],
) -> float:
    """Score a single chunk by information density and importance."""
    score = 0.0

    # 1. Tension (0-2 points)
    score += sr.tension * 2.0

    # 2. Event importance (0-1.5 points)
    if sr.events:
        max_imp = max(
            (e.get("importance", 0) for e in sr.events),
            default=0,
        )
        score += float(max_imp) * 1.5

    # 3. Character novelty bonus (0-2 points)
    # Chunks that introduce a character for the first time get bonus
    for c in sr.characters:
        name = c.get("name", "")
        if name and char_first_seen.get(name) == sr.chunk_index:
            role = c.get("role", "mentioned")
            if role == "main":
                score += 1.0
            elif role == "supporting":
                score += 0.6
            else:
                score += 0.3

    # 4. Information density (0-1 point)
    entity_count = len(sr.characters) + len(sr.events) + len(sr.themes)
    score += min(1.0, entity_count * 0.15)

    # 5. Summary quality (0-0.5 points)
    if sr.summary and len(sr.summary) > 20:
        score += 0.5

    return score


def _find_tension_peaks(
    scan_results: list[ChunkScanResult],
    threshold: float = 0.6,
    window: int = 3,
) -> set[int]:
    """Find local tension maxima above threshold.

    A chunk is a peak if its tension is higher than all chunks
    within `window` positions on either side.
    """
    peaks = set()
    n = len(scan_results)

    for i, sr in enumerate(scan_results):
        if sr.tension < threshold:
            continue

        is_peak = True
        for j in range(max(0, i - window), min(n, i + window + 1)):
            if j != i and scan_results[j].tension > sr.tension:
                is_peak = False
                break

        if is_peak:
            peaks.add(sr.chunk_index)

    return peaks


def _find_character_introductions(
    scan_results: list[ChunkScanResult],
) -> dict[str, int]:
    """Find the first chunk where each character appears.

    Returns {character_name: chunk_index} for characters with
    role "main" or "supporting" (skip "mentioned" for noise reduction).
    """
    first_seen: dict[str, int] = {}

    for sr in scan_results:
        for c in sr.characters:
            name = c.get("name", "")
            role = c.get("role", "mentioned")
            if not name or role == "mentioned":
                continue
            if name not in first_seen:
                first_seen[name] = sr.chunk_index

    return first_seen


def _group_by_chapter(
    chunks: list,
) -> dict[str, list[int]]:
    """Group chunk indices by chapter header."""
    chapters: dict[str, list[int]] = defaultdict(list)

    for chunk in chunks:
        text = getattr(chunk, "text", str(chunk))
        match = _HEADER_RE.match(text)
        key = match.group(1) if match else "未分章"
        idx = getattr(chunk, "index", 0)
        chapters[key].append(idx)

    return dict(chapters)


def build_scan_context(
    scan_results: list[ChunkScanResult],
    selected_indices: list[int],
) -> str:
    """Build a compact context string from Phase 1 scan results.

    Used as supplementary context in Phase 3 prompts, giving the LLM
    awareness of ALL chunks (not just the selected deep-analysis ones).
    """
    selected_set = set(selected_indices)
    lines = []

    for sr in scan_results:
        if sr.chunk_index in selected_set:
            continue  # Skip selected chunks — they'll be analyzed in full

        if not sr.summary and not sr.events:
            continue

        parts = [f"[{sr.chunk_index}]"]
        if sr.summary:
            parts.append(sr.summary[:80])
        if sr.characters:
            names = [c.get("name", "") for c in sr.characters[:3]]
            parts.append(f"人物:{','.join(n for n in names if n)}")
        if sr.events:
            evts = [e.get("event", "") for e in sr.events[:2]]
            parts.append(f"事件:{','.join(e for e in evts if e)}")

        lines.append(" | ".join(parts))

    return "\n".join(lines)


def aggregate_all_characters(
    scan_results: list[ChunkScanResult],
) -> dict[str, dict]:
    """Aggregate character mentions across all chunks from Phase 1.

    Returns {name: {appearances: int, roles: Counter, actions: list, chunks: list}}.
    Much more comprehensive than NER-only extraction.
    """
    chars: dict[str, dict] = {}

    for sr in scan_results:
        for c in sr.characters:
            name = c.get("name", "")
            if not name:
                continue

            if name not in chars:
                chars[name] = {
                    "appearances": 0,
                    "roles": Counter(),
                    "actions": [],
                    "chunks": [],
                }

            chars[name]["appearances"] += 1
            chars[name]["roles"][c.get("role", "mentioned")] += 1
            chars[name]["chunks"].append(sr.chunk_index)
            action = c.get("action", "")
            if action and len(chars[name]["actions"]) < 10:
                chars[name]["actions"].append(action)

    return chars


def aggregate_all_events(
    scan_results: list[ChunkScanResult],
) -> list[dict]:
    """Aggregate significant events across all chunks from Phase 1.

    Returns sorted list of {event, importance, chunk_index} for events
    with importance >= 0.5.
    """
    events = []
    for sr in scan_results:
        for e in sr.events:
            imp = e.get("importance", 0)
            if isinstance(imp, (int, float)) and imp >= 0.5:
                events.append({
                    "event": e.get("event", ""),
                    "importance": float(imp),
                    "chunk_index": sr.chunk_index,
                })

    events.sort(key=lambda x: x["importance"], reverse=True)
    return events
