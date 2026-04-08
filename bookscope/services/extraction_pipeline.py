"""Parallel KG + emotion/style extraction pipeline.

Runs knowledge graph extraction (LLM, I/O-bound) and emotion/style analysis
(lexicon, CPU-bound) concurrently using threading. Yields SSE-ready dicts
so the router can stream progress.
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

# Sentinel to signal thread completion
_DONE = object()


def run_extraction(
    session: SessionData,
    api_key: str | None,
    model: str = "claude-haiku-4-5",
) -> Generator[dict, None, None]:
    """Run KG extraction + emotion/style analysis in parallel.

    Yields SSE-ready dicts:
      { type: "progress", stage: "emotion"|"style"|"arc"|"kg", current, total }
      { type: "kg_ready", summary, character_count }
      { type: "analysis_ready" }
      { type: "done" }
      { type: "error", message }
    """
    q: queue.Queue = queue.Queue()
    chunks = session.chunks
    lang = session.language

    def _run_analysis():
        """Thread 1: emotion + style + arc (CPU-bound, no LLM)."""
        try:
            from bookscope.nlp import ArcClassifier, LexiconAnalyzer, StyleAnalyzer

            n = len(chunks)

            # Emotion analysis — try Transformer first, fall back to Lexicon
            analyzer = None
            try:
                from bookscope.nlp.transformer_analyzer import TransformerAnalyzer
                analyzer = TransformerAnalyzer(language=lang)
                # Test model loading
                analyzer._get_classifier()
                logger.info("Using TransformerAnalyzer for emotion analysis")
            except Exception as e:
                logger.warning("TransformerAnalyzer unavailable (%s), falling back to LexiconAnalyzer", e)
                analyzer = LexiconAnalyzer(language=lang)

            emotion_scores = []
            for i, chunk in enumerate(chunks):
                score = analyzer.analyze_chunk(chunk)
                emotion_scores.append(score)
                if (i + 1) % max(1, n // 10) == 0 or i == n - 1:
                    q.put({"type": "progress", "stage": "emotion",
                           "current": i + 1, "total": n})

            # Style analysis
            sty = StyleAnalyzer(language=lang)
            style_scores = []
            for i, chunk in enumerate(chunks):
                score = sty.analyze_chunk(chunk)
                style_scores.append(score)
                if (i + 1) % max(1, n // 10) == 0 or i == n - 1:
                    q.put({"type": "progress", "stage": "style",
                           "current": i + 1, "total": n})

            # Arc classification
            q.put({"type": "progress", "stage": "arc", "current": 1, "total": 1})
            arc = ArcClassifier()
            pattern = arc.classify(emotion_scores)
            valence = arc.valence_series(emotion_scores)

            # Store results
            session.emotion_scores = emotion_scores
            session.style_scores = style_scores
            session.arc_pattern = pattern.value if hasattr(pattern, "value") else str(pattern)
            session.valence_series = valence

            q.put({"type": "analysis_ready"})
        except Exception as e:
            logger.exception("Analysis thread failed")
            q.put({"type": "error", "message": f"Analysis failed: {e}"})
        finally:
            q.put(("_done", "analysis"))

    def _run_kg():
        """Thread 2: knowledge graph extraction (LLM, I/O-bound)."""
        if not api_key:
            q.put(("_done", "kg"))
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
                enrich_souls=False,  # on-demand in v5
                book_type=session.book_type,
            )
            session.knowledge_graph = graph
            q.put({
                "type": "kg_ready",
                "summary": graph.overall_summary or "",
                "character_count": len(graph.characters),
            })
        except Exception as e:
            logger.exception("KG extraction thread failed")
            q.put({"type": "error", "message": f"KG extraction failed: {e}"})
        finally:
            q.put(("_done", "kg"))

    # Launch both threads
    t_analysis = threading.Thread(target=_run_analysis, daemon=True)
    t_kg = threading.Thread(target=_run_kg, daemon=True)
    t_analysis.start()
    t_kg.start()

    # Merge events from both threads
    done_count = 0
    has_error = False
    while done_count < 2:
        try:
            event = q.get(timeout=120)
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

    # Persist final session state (analysis results + status)
    from bookscope.api.session_store import persist_session
    try:
        persist_session(session)
    except Exception:
        logger.warning("Failed to persist session after extraction", exc_info=True)

    if not has_error:
        yield {"type": "done"}
