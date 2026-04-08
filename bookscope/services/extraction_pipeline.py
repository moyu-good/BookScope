"""Two-tier parallel extraction pipeline (v6).

Tier 1 (no LLM, <30s): emotion + style + arc analysis → immediate results
Tier 2 (LLM, ~1-2min):  knowledge graph (arcs + characters + outline)

Both tiers run in parallel threads. Tier 1 results are streamed first
so the user sees useful data within seconds. Yields SSE-ready dicts.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Generator
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bookscope.api.session_store import SessionData

logger = logging.getLogger(__name__)


def run_extraction(
    session: SessionData,
    api_key: str | None,
    model: str = "claude-haiku-4-5",
) -> Generator[dict, None, None]:
    """Run two-tier extraction: Tier 1 (CPU) + Tier 2 (LLM) in parallel.

    Yields SSE-ready dicts:
      { type: "progress", stage: "emotion"|"style"|"arc"|"kg", current, total }
      { type: "tier1_ready" }           — Tier 1 complete, basic data available
      { type: "kg_ready", summary, character_count }
      { type: "analysis_ready" }
      { type: "done" }
      { type: "error", message }
    """
    q: queue.Queue = queue.Queue()
    chunks = session.chunks
    lang = session.language

    def _run_tier1():
        """Tier 1: emotion + style + arc (CPU-bound, no LLM, <30s).

        Optimizations:
          - Emotion and style analysis run in parallel threads
          - Style analysis samples every Nth chunk (POS tagging is expensive)
        """
        try:
            from bookscope.nlp import ArcClassifier, LexiconAnalyzer, StyleAnalyzer

            n = len(chunks)
            _emotion_result: list = []
            _style_result: list = []

            def _do_emotion():
                analyzer = LexiconAnalyzer(language=lang)
                scores = []
                for i, chunk in enumerate(chunks):
                    score = analyzer.analyze_chunk(chunk)
                    scores.append(score)
                    if (i + 1) % max(1, n // 10) == 0 or i == n - 1:
                        q.put({"type": "progress", "stage": "emotion",
                               "current": i + 1, "total": n})
                _emotion_result.extend(scores)

            def _do_style():
                sty = StyleAnalyzer(language=lang)
                # Sample every Nth chunk for speed (POS tagging is expensive)
                # 200 samples is sufficient for book-level style metrics
                step = max(1, n // 200)
                sample_indices = list(range(0, n, step))
                sampled_scores = {}
                for j, idx in enumerate(sample_indices):
                    score = sty.analyze_chunk(chunks[idx])
                    sampled_scores[idx] = score
                    if (j + 1) % max(1, len(sample_indices) // 5) == 0 or j == len(sample_indices) - 1:
                        q.put({"type": "progress", "stage": "style",
                               "current": j + 1, "total": len(sample_indices)})

                # Fill non-sampled positions by interpolating from nearest sample
                scores = []
                sorted_sampled = sorted(sampled_scores.keys())
                for i in range(n):
                    if i in sampled_scores:
                        scores.append(sampled_scores[i])
                    else:
                        # Find nearest sampled index
                        nearest = min(sorted_sampled, key=lambda x: abs(x - i))
                        scores.append(sampled_scores[nearest])
                _style_result.extend(scores)

            # Run emotion and style in parallel
            t_emo = threading.Thread(target=_do_emotion, daemon=True)
            t_sty = threading.Thread(target=_do_style, daemon=True)
            t_emo.start()
            t_sty.start()
            t_emo.join()
            t_sty.join()

            emotion_scores = _emotion_result
            style_scores = _style_result

            # Arc classification (instant)
            q.put({"type": "progress", "stage": "arc", "current": 1, "total": 1})
            arc = ArcClassifier()
            pattern = arc.classify(emotion_scores)
            valence = arc.valence_series(emotion_scores)

            # Store Tier 1 results
            session.emotion_scores = emotion_scores
            session.style_scores = style_scores
            session.arc_pattern = pattern.value if hasattr(pattern, "value") else str(pattern)
            session.valence_series = valence

            q.put({"type": "tier1_ready"})
            q.put({"type": "analysis_ready"})
        except Exception as e:
            logger.exception("Tier 1 analysis failed")
            q.put({"type": "error", "message": f"Analysis failed: {e}"})
        finally:
            q.put(("_done", "tier1"))

    def _run_tier2():
        """Tier 2: knowledge graph extraction (LLM, ~1-2 min)."""
        if not api_key:
            q.put(("_done", "tier2"))
            return
        try:
            from bookscope.nlp.knowledge_extractor import extract_knowledge_graph

            def progress_cb(current: int, total: int):
                q.put({"type": "progress", "stage": "kg",
                       "current": current, "total": total})

            graph = extract_knowledge_graph(
                chunks=chunks,
                book_title=session.title,
                language=lang,
                api_key=api_key,
                model=model,
                progress_callback=progress_cb,
                enrich_souls=False,
                book_type=session.book_type,
            )
            session.knowledge_graph = graph
            q.put({
                "type": "kg_ready",
                "summary": graph.overall_summary or "",
                "character_count": len(graph.characters),
            })
        except Exception as e:
            logger.exception("Tier 2 KG extraction failed")
            q.put({"type": "error", "message": f"KG extraction failed: {e}"})
        finally:
            q.put(("_done", "tier2"))

    # Launch both tiers in parallel
    t1 = threading.Thread(target=_run_tier1, daemon=True)
    t2 = threading.Thread(target=_run_tier2, daemon=True)
    t1.start()
    t2.start()

    # Merge events from both threads
    done_count = 0
    has_error = False
    while done_count < 2:
        try:
            event = q.get(timeout=300)  # 5 min timeout for LLM tier
        except queue.Empty:
            yield {"type": "error", "message": "Extraction timed out"}
            break

        if isinstance(event, tuple) and event[0] == "_done":
            done_count += 1
            continue

        if event.get("type") == "error":
            has_error = True

        yield event

    session.extraction_status = "error" if has_error else "done"

    # Persist final session state
    from bookscope.api.session_store import persist_session
    try:
        persist_session(session)
    except Exception:
        logger.warning("Failed to persist session after extraction", exc_info=True)

    if not has_error:
        yield {"type": "done"}
