"""BookScope v7 — Phase 1: Lightweight full-coverage chunk scanner.

Sends EVERY chunk through a cheap/fast LLM (Haiku/DeepSeek) with a
minimal structured schema. This ensures 100% content coverage at low cost.

Output per chunk (~200 tokens):
    {characters, events, tension, themes, summary}

Cost estimate (400 chunks, Haiku):
    Input:  ~400K tokens × $0.80/1M = $0.32
    Output: ~80K tokens  × $4.00/1M = $0.32
    Total:  ~$0.64

The scan results feed Phase 2 (smart selection) and Phase 3 (deep analysis).
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from bookscope.models.schemas import ChunkScanResult
from bookscope.nlp.llm_analyzer import call_llm

logger = logging.getLogger(__name__)

_HEADER_RE = re.compile(r"^\[《.+?》(.+?)\]\n?")

# Batch size: 3-4 chunks per LLM call balances throughput vs output quality
_SCAN_BATCH_SIZE = 4
# Max concurrent LLM calls for Phase 1
_SCAN_MAX_WORKERS = 8
# Max chars per chunk sent to LLM (truncate very long chunks)
_SCAN_CHUNK_CHARS = 2000


def _build_scan_prompt(
    batch: list[tuple[int, str]],
    language: str,
    book_type: str,
) -> str:
    """Build a lightweight extraction prompt for a batch of chunks."""
    chunks_text = ""
    for pos, (idx, text) in enumerate(batch):
        # Strip contextual header
        clean = _HEADER_RE.sub("", text, count=1).strip()
        truncated = clean[:_SCAN_CHUNK_CHARS]
        chunks_text += f"\n[片段{pos}]\n{truncated}\n"

    is_nonfiction = book_type in ("nonfiction", "academic", "technical", "self_help")

    if language == "zh":
        role_hint = "历史人物/关键人物" if is_nonfiction else "角色"
        event_hint = "论点/史实/关键发现" if is_nonfiction else "事件"
        return (
            "从以下书籍片段中提取结构化元数据。严格返回JSON数组，每个片段一个对象。\n"
            "所有输出必须使用中文。\n\n"
            "每个对象schema:\n"
            "{\n"
            '  "characters": [{"name":"人名",'
            '"action":"做了什么(10字内)",'
            f'"role":"main/supporting/mentioned"}}],\n'
            f'  "events": [{{"event":"{event_hint}名(5-15字)",'
            '"importance":0.0-1.0}],\n'
            '  "tension": 0.0-1.0的叙事张力/重要性,\n'
            '  "themes": ["主题词1","主题词2"],\n'
            '  "summary": "1-2句核心内容概述(30-60字)"\n'
            "}\n\n"
            "importance评分: 0.0=日常铺垫 0.3=一般推进 "
            f"0.6=重要{event_hint} 0.8=关键转折 1.0=全书核心\n"
            f"tension评分: 0.0=平静 0.3=有进展 0.6=紧张 0.8=高潮 1.0=极度紧张\n"
            f"role说明: main=主要{role_hint} supporting=次要{role_hint} mentioned=仅提及\n\n"
            "【输出禁令】summary/event/action/themes 等文本字段必须是自然叙述，"
            "严禁出现：chunk、片段N、片段#N、索引、idx、根据提取结果、以上片段 等字样。"
            "即使 prompt 里用了[片段N]作为分隔符，输出中也不得回显此类技术标签。\n\n"
            f"共{len(batch)}个片段:" + chunks_text
        )
    return (
        "Extract structured metadata from the following book passages. "
        "Return a JSON array with one object per passage.\n\n"
        "Each object schema:\n"
        "{\n"
        '  "characters": [{"name":"Name",'
        '"action":"what they did (brief)",'
        '"role":"main/supporting/mentioned"}],\n'
        '  "events": [{"event":"event name (5-15 words)","importance":0.0-1.0}],\n'
        '  "tension": 0.0-1.0 narrative tension,\n'
        '  "themes": ["theme1","theme2"],\n'
        '  "summary": "1-2 sentence core summary"\n'
        "}\n\n"
        "[OUTPUT RULE] summary/event/action/themes fields must be natural prose. "
        "Do NOT echo technical labels like [passage N], chunk, idx, 'based on the "
        "excerpts above'. Prompt delimiters must not appear in output.\n\n"
        f"{len(batch)} passages:" + chunks_text
    )


def _parse_scan_response(
    raw: str,
    batch: list[tuple[int, str]],
) -> list[ChunkScanResult]:
    """Parse Phase 1 scan response into ChunkScanResult objects."""
    if not raw:
        return [ChunkScanResult(chunk_index=idx) for idx, _ in batch]

    # Strip markdown fences
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(
            line for line in lines if not line.startswith("```")
        ).strip()
    if text.endswith(" …"):
        text = text[:-2]

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return [ChunkScanResult(chunk_index=idx) for idx, _ in batch]

    # Normalize to list
    if isinstance(data, dict):
        if "results" in data:
            data = data["results"]
        else:
            data = [data]
    if not isinstance(data, list):
        return [ChunkScanResult(chunk_index=idx) for idx, _ in batch]

    results: list[ChunkScanResult] = []
    for pos, (idx, _text) in enumerate(batch):
        if pos < len(data) and isinstance(data[pos], dict):
            item = data[pos]
            # Parse tension safely
            tension = item.get("tension", 0.5)
            if isinstance(tension, (int, float)):
                tension = max(0.0, min(1.0, float(tension)))
            else:
                tension = 0.5

            # Parse characters safely
            characters = []
            for c in item.get("characters", []):
                if isinstance(c, dict) and c.get("name"):
                    characters.append({
                        "name": str(c.get("name", "")),
                        "action": str(c.get("action", "")),
                        "role": str(c.get("role", "mentioned")),
                    })

            # Parse events safely
            events = []
            for e in item.get("events", []):
                if isinstance(e, dict) and e.get("event"):
                    imp = e.get("importance", 0.5)
                    if not isinstance(imp, (int, float)):
                        imp = 0.5
                    events.append({
                        "event": str(e.get("event", "")),
                        "importance": max(0.0, min(1.0, float(imp))),
                    })

            results.append(ChunkScanResult(
                chunk_index=idx,
                characters=characters,
                events=events,
                tension=tension,
                themes=[str(t) for t in item.get("themes", []) if t],
                summary=str(item.get("summary", "")),
            ))
        else:
            results.append(ChunkScanResult(chunk_index=idx))

    return results


def scan_all_chunks(
    chunks: list,
    language: str = "zh",
    api_key: str = "",
    model: str = "claude-haiku-4-5",
    book_type: str = "fiction",
    batch_size: int = _SCAN_BATCH_SIZE,
    max_workers: int = _SCAN_MAX_WORKERS,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[ChunkScanResult]:
    """Phase 1: Scan ALL chunks with lightweight structured extraction.

    Returns one ChunkScanResult per chunk, ordered by chunk_index.
    Uses batching (4 chunks/call) and high concurrency (8 workers)
    to process 400 chunks in ~50 parallel batches ≈ 2-3 minutes.
    """
    if not chunks or not api_key:
        return [ChunkScanResult(chunk_index=i) for i in range(len(chunks))]

    # Build batches of (chunk_index, chunk_text) tuples
    all_items: list[tuple[int, str]] = []
    for chunk in chunks:
        idx = getattr(chunk, "index", 0)
        text = getattr(chunk, "text", str(chunk))
        all_items.append((idx, text))

    batches: list[list[tuple[int, str]]] = [
        all_items[i:i + batch_size]
        for i in range(0, len(all_items), batch_size)
    ]

    total_batches = len(batches)
    results: list[ChunkScanResult] = []
    completed = 0

    def _process_batch(batch: list[tuple[int, str]]) -> list[ChunkScanResult]:
        prompt = _build_scan_prompt(batch, language, book_type)
        # ~200 output tokens per chunk
        max_tokens = 250 * len(batch)
        raw = call_llm(prompt, api_key=api_key, model=model, max_tokens=max_tokens) or ""
        return _parse_scan_response(raw, batch)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_batch = {
            executor.submit(_process_batch, batch): batch
            for batch in batches
        }

        for future in as_completed(future_to_batch):
            batch = future_to_batch[future]
            try:
                batch_results = future.result()
                results.extend(batch_results)
            except Exception:
                logger.warning(
                    "Scan batch failed for chunks %s",
                    [idx for idx, _ in batch],
                )
                # Fallback: empty results for failed batch
                results.extend(
                    ChunkScanResult(chunk_index=idx) for idx, _ in batch
                )

            completed += 1
            if progress_callback:
                progress_callback(completed, total_batches)

    # Sort by chunk_index for consistent ordering
    results.sort(key=lambda r: r.chunk_index)
    logger.info(
        "Phase 1 scan complete: %d chunks, %d batches, "
        "%d characters found, %d events found",
        len(results), total_batches,
        sum(len(r.characters) for r in results),
        sum(len(r.events) for r in results),
    )
    return results
