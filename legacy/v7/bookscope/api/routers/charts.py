"""Charts router — GET /api/charts/{id}/* for visualization data."""

from __future__ import annotations

from fastapi import APIRouter

from bookscope.api.dependencies import require_analysis, require_session
from bookscope.nlp.prompt_builders import EMOTION_FIELDS

router = APIRouter()


@router.get("/api/charts/{session_id}/emotion-overview")
async def emotion_overview(session_id: str):
    session = require_session(session_id)
    require_analysis(session)
    scores = session.emotion_scores
    n = len(scores)
    avgs = {}
    for field in EMOTION_FIELDS:
        avgs[field] = round(sum(getattr(s, field) for s in scores) / n, 4) if n else 0

    from collections import Counter
    dominants = Counter(s.dominant_emotion for s in scores)
    top = dominants.most_common(1)[0][0] if dominants else "joy"
    density = round(sum(s.emotion_density for s in scores) / n, 4) if n else 0

    return {**avgs, "dominant_emotion": top, "emotion_density_avg": density}


@router.get("/api/charts/{session_id}/emotion-heatmap")
async def emotion_heatmap(session_id: str):
    session = require_session(session_id)
    require_analysis(session)
    scores = session.emotion_scores
    chunk_labels = [f"Chunk {s.chunk_index + 1}" for s in scores]
    matrix = []
    for field in EMOTION_FIELDS:
        row = [getattr(s, field) for s in scores]
        matrix.append(row)
    return {
        "chunk_labels": chunk_labels,
        "emotion_labels": list(EMOTION_FIELDS),
        "matrix": matrix,
    }


@router.get("/api/charts/{session_id}/emotion-timeline")
async def emotion_timeline(session_id: str):
    session = require_session(session_id)
    require_analysis(session)
    scores = session.emotion_scores
    indices = [s.chunk_index for s in scores]
    series = {f: [] for f in EMOTION_FIELDS}
    for s in scores:
        for f in EMOTION_FIELDS:
            series[f].append(getattr(s, f))
    return {"chunk_indices": indices, "series": series}


@router.get("/api/charts/{session_id}/style-radar")
async def style_radar(session_id: str):
    session = require_session(session_id)
    require_analysis(session)
    scores = session.style_scores
    n = len(scores)
    if n == 0:
        return {"metrics": {}}
    fields = ("avg_sentence_length", "ttr", "noun_ratio", "verb_ratio", "adj_ratio", "adv_ratio")
    metrics = {}
    for f in fields:
        metrics[f] = round(sum(getattr(s, f) for s in scores) / n, 4)
    return {"metrics": metrics}


@router.get("/api/charts/{session_id}/arc-pattern")
async def arc_pattern(session_id: str):
    session = require_session(session_id)
    require_analysis(session)
    return {
        "arc_pattern": session.arc_pattern or "Unknown",
        "valence_series": session.valence_series or [],
    }
