"""BookScope v4 — Unified FastAPI backend.

Serves as the single backend for the React frontend.
Endpoints grouped by domain:
    Session:   /api/upload, /api/session/{id}
    Analysis:  /api/analyze (SSE), /api/preview
    Charts:    /api/charts/{id}/*
    Insights:  /api/insights/*
    KG:        /api/extract (SSE)
    Chat:      /api/chat/stream (SSE), /api/search
    Library:   /api/library/*
    Export:    /api/export/*
    Share:     /api/share/*

Run:
    uvicorn bookscope.api.main:app --reload --port 8000
"""

import json
import os
import tempfile
import uuid
from collections import Counter
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from bookscope.ingest import chunk_book, clean, load_text
from bookscope.insights import (
    build_reader_verdict,
    compute_readability,
    extract_character_names,
    extract_key_themes,
    first_person_density,
)
from bookscope.models import (
    BookKnowledgeGraph,
    EmotionScore,
    StyleScore,
)
from bookscope.nlp import (
    ArcClassifier,
    LexiconAnalyzer,
    StyleAnalyzer,
    detect_language,
    extract_character_candidates,
    extract_knowledge_graph,
)
from bookscope.nlp.llm_analyzer import call_llm

try:
    from bookscope.store.vector_store import SessionVectorStore
except ImportError:
    SessionVectorStore = None  # type: ignore[assignment,misc]

app = FastAPI(title="BookScope API", version="4.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory session store (single worker; TTL cleanup planned for Phase 2)
_sessions: dict[str, dict] = {}

_EMOTION_FIELDS = (
    "anger", "anticipation", "disgust", "fear",
    "joy", "sadness", "surprise", "trust",
)


def _get_api_key() -> str | None:
    return os.environ.get("ANTHROPIC_API_KEY")


def _get_session(session_id: str) -> dict:
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


# ═══════════════════════════════════════════════════════════════════════════════
# SESSION & UPLOAD
# ═══════════════════════════════════════════════════════════════════════════════


class UploadResponse(BaseModel):
    session_id: str
    title: str
    language: str
    total_chunks: int
    total_words: int


@app.post("/api/upload", response_model=UploadResponse)
async def upload_file(file: UploadFile = File(...)):
    """Upload a text file, chunk it, detect language, build vector index."""
    content = await file.read()
    title = Path(file.filename or "untitled").stem
    suffix = Path(file.filename or "file.txt").suffix.lower() or ".txt"

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        book = load_text(tmp_path, title=title)
    finally:
        tmp_path.unlink(missing_ok=True)

    cleaned_text = clean(book.raw_text)
    lang = detect_language(cleaned_text)
    book.language = lang

    chunks = chunk_book(book)
    total_words = sum(c.word_count for c in chunks)

    # Build FAISS vector index for RAG
    vector_store = None
    if SessionVectorStore is not None:
        try:
            vector_store = SessionVectorStore(chunks)
        except Exception:
            pass

    session_id = uuid.uuid4().hex[:12]
    _sessions[session_id] = {
        "title": title,
        "book": book,
        "chunks": chunks,
        "total_words": total_words,
        "language": lang,
        "knowledge_graph": None,
        "vector_store": vector_store,
        "emotion_scores": None,
        "style_scores": None,
        "arc_pattern": None,
        "arc_confidence": None,
        "valence_series": None,
    }

    return UploadResponse(
        session_id=session_id,
        title=title,
        language=lang,
        total_chunks=len(chunks),
        total_words=total_words,
    )


class SessionResponse(BaseModel):
    session_id: str
    title: str
    language: str
    total_chunks: int
    total_words: int
    has_analysis: bool
    has_knowledge_graph: bool


@app.get("/api/session/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str):
    """Get session metadata and status flags."""
    s = _get_session(session_id)
    return SessionResponse(
        session_id=session_id,
        title=s["title"],
        language=s["language"],
        total_chunks=len(s["chunks"]),
        total_words=s["total_words"],
        has_analysis=s["emotion_scores"] is not None,
        has_knowledge_graph=s["knowledge_graph"] is not None,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# ANALYSIS PIPELINE (SSE)
# ═══════════════════════════════════════════════════════════════════════════════


class AnalyzeRequest(BaseModel):
    session_id: str
    book_type: str = "fiction"
    ui_lang: str = "en"


@app.post("/api/analyze")
async def analyze(req: AnalyzeRequest):
    """Run emotion + style + arc analysis. Returns SSE progress stream.

    Final event contains the full analysis result.
    """
    session = _get_session(req.session_id)
    chunks = session["chunks"]
    lang = session["language"]

    def event_stream():
        n = len(chunks)

        # Stage 1: Emotion analysis
        yield _sse({"type": "progress", "stage": "emotion", "current": 0, "total": n})
        lexicon = LexiconAnalyzer()
        emotion_scores: list[EmotionScore] = []
        for i, chunk in enumerate(chunks):
            scores = lexicon.analyze_chunk(chunk)
            emotion_scores.extend(scores if isinstance(scores, list) else [scores])
            if (i + 1) % max(1, n // 10) == 0 or i == n - 1:
                yield _sse({"type": "progress", "stage": "emotion", "current": i + 1, "total": n})

        # Stage 2: Style analysis
        yield _sse({"type": "progress", "stage": "style", "current": 0, "total": n})
        style_analyzer = StyleAnalyzer()
        style_scores: list[StyleScore] = []
        for i, chunk in enumerate(chunks):
            scores = style_analyzer.analyze_chunk(chunk)
            style_scores.extend(scores if isinstance(scores, list) else [scores])
            if (i + 1) % max(1, n // 10) == 0 or i == n - 1:
                yield _sse({"type": "progress", "stage": "style", "current": i + 1, "total": n})

        # Stage 3: Arc classification
        yield _sse({"type": "progress", "stage": "arc", "current": 0, "total": 1})
        arc_classifier = ArcClassifier()
        arc = arc_classifier.classify(emotion_scores)
        valence_series = (
            arc_classifier.valence_series(emotion_scores)
            if len(emotion_scores) >= 2
            else []
        )
        yield _sse({"type": "progress", "stage": "arc", "current": 1, "total": 1})

        # Stage 4: Derived insights
        readability_score, readability_label, read_confidence = compute_readability(
            style_scores, req.ui_lang,
        )

        dominants = Counter(
            s.dominant_emotion for s in emotion_scores
        ) if emotion_scores else Counter()
        top_emotion = dominants.most_common(1)[0][0] if dominants else "joy"

        verdict = build_reader_verdict(
            arc_value=arc.value,
            top_emotion_key=top_emotion,
            style_scores=style_scores,
            book_type=req.book_type,
            ui_lang=req.ui_lang,
        )

        # Store in session for chart endpoints
        session["emotion_scores"] = emotion_scores
        session["style_scores"] = style_scores
        session["arc_pattern"] = arc.value
        session["valence_series"] = valence_series

        # Build final result
        result = {
            "type": "done",
            "emotion_scores": [s.model_dump() for s in emotion_scores],
            "style_scores": [s.model_dump() for s in style_scores],
            "arc_pattern": arc.value,
            "dominant_emotion": top_emotion,
            "valence_series": valence_series,
            "readability": {
                "score": readability_score,
                "label": readability_label,
                "confidence": read_confidence,
            },
            "reader_verdict": verdict.model_dump() if hasattr(verdict, "model_dump") else {
                "sentence": getattr(verdict, "sentence", ""),
                "for_you": getattr(verdict, "for_you", ""),
                "not_for_you": getattr(verdict, "not_for_you", ""),
                "confidence": getattr(verdict, "confidence", 0.0),
            },
        }
        yield _sse(result)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ═══════════════════════════════════════════════════════════════════════════════
# QUICK PREVIEW (LLM)
# ═══════════════════════════════════════════════════════════════════════════════


class PreviewRequest(BaseModel):
    session_id: str
    language: str = "en"
    model: str = "claude-haiku-4-5"


class PreviewResponse(BaseModel):
    preview_text: str


@app.post("/api/preview", response_model=PreviewResponse)
async def preview(req: PreviewRequest):
    """Generate a 3-sentence LLM summary from the first 5 chunks."""
    session = _get_session(req.session_id)
    api_key = _get_api_key()
    if not api_key:
        raise HTTPException(status_code=422, detail="ANTHROPIC_API_KEY not set")

    chunks = session["chunks"]
    lang_name = {"en": "English", "zh": "Chinese", "ja": "Japanese"}.get(
        req.language, "English",
    )
    sample = "\n\n".join(c.text[:800] for c in chunks[:5])
    prompt = (
        f"Based on these opening passages of a book:\n\n{sample}\n\n"
        f"Answer in 3 sentences, in {lang_name}:\n"
        f"1. What is this book about?\n"
        f"2. How does it feel to read?\n"
        f"3. Who is it for?"
    )
    text = call_llm(prompt, api_key=api_key, model=req.model, max_tokens=300) or ""
    return PreviewResponse(preview_text=text)


# ═══════════════════════════════════════════════════════════════════════════════
# CHART DATA ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════


def _require_analysis(session: dict) -> tuple[list[EmotionScore], list[StyleScore]]:
    e = session.get("emotion_scores")
    s = session.get("style_scores")
    if e is None or s is None:
        raise HTTPException(
            status_code=409,
            detail="Analysis not yet run. Call POST /api/analyze first.",
        )
    return e, s


@app.get("/api/charts/{session_id}/emotion-overview")
async def chart_emotion_overview(session_id: str):
    """Average emotion scores across all chunks (radar chart data)."""
    session = _get_session(session_id)
    emotion_scores, _ = _require_analysis(session)
    n = len(emotion_scores)
    avgs = {}
    for field in _EMOTION_FIELDS:
        avgs[field] = sum(getattr(s, field) for s in emotion_scores) / n

    dominants = Counter(s.dominant_emotion for s in emotion_scores)
    dominant = dominants.most_common(1)[0][0] if dominants else "joy"
    density_avg = sum(s.emotion_density for s in emotion_scores) / n

    return {
        "emotions": avgs,
        "dominant_emotion": dominant,
        "emotion_density_avg": round(density_avg, 4),
    }


@app.get("/api/charts/{session_id}/emotion-heatmap")
async def chart_emotion_heatmap(session_id: str):
    """Per-chunk emotion matrix for heatmap visualization."""
    session = _get_session(session_id)
    emotion_scores, _ = _require_analysis(session)
    matrix = []
    for s in emotion_scores:
        row = [getattr(s, f) for f in _EMOTION_FIELDS]
        matrix.append(row)

    return {
        "chunk_labels": [f"Chunk {s.chunk_index + 1}" for s in emotion_scores],
        "emotion_labels": list(_EMOTION_FIELDS),
        "matrix": matrix,
    }


@app.get("/api/charts/{session_id}/emotion-timeline")
async def chart_emotion_timeline(session_id: str):
    """Per-chunk emotion values for line chart (timeline view)."""
    session = _get_session(session_id)
    emotion_scores, _ = _require_analysis(session)
    series: dict[str, list[float]] = {f: [] for f in _EMOTION_FIELDS}
    indices = []
    for s in emotion_scores:
        indices.append(s.chunk_index)
        for f in _EMOTION_FIELDS:
            series[f].append(getattr(s, f))

    return {"chunk_indices": indices, "series": series}


@app.get("/api/charts/{session_id}/style-radar")
async def chart_style_radar(session_id: str):
    """Aggregated style metrics for radar chart."""
    session = _get_session(session_id)
    _, style_scores = _require_analysis(session)
    n = len(style_scores)
    fields = ("avg_sentence_length", "ttr", "noun_ratio", "verb_ratio", "adj_ratio", "adv_ratio")
    metrics = {}
    for f in fields:
        metrics[f] = round(sum(getattr(s, f) for s in style_scores) / n, 4)

    return {"metrics": metrics}


@app.get("/api/charts/{session_id}/arc-pattern")
async def chart_arc_pattern(session_id: str):
    """Valence series + arc classification for arc visualization."""
    session = _get_session(session_id)
    emotion_scores, _ = _require_analysis(session)
    arc_pattern = session.get("arc_pattern", "Unknown")
    valence_series = session.get("valence_series", [])

    return {
        "arc_pattern": arc_pattern,
        "valence_series": valence_series,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# INSIGHT ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════


class InsightCharactersRequest(BaseModel):
    session_id: str
    top_n: int = 8


@app.post("/api/insights/characters")
async def insight_characters(req: InsightCharactersRequest):
    """Extract character names via NER."""
    session = _get_session(req.session_id)
    chunks = session["chunks"]
    lang = session["language"]

    # NER extractor (returns dict[name, chunk_indices])
    candidates = extract_character_candidates(chunks, language=lang)
    # Also try simpler extraction
    names = extract_character_names(chunks, top_n=req.top_n, lang=lang)

    characters = []
    seen = set()
    # Prefer NER candidates (have chunk indices)
    for name, indices in sorted(candidates.items(), key=lambda x: -len(x[1])):
        if len(characters) >= req.top_n:
            break
        characters.append({"name": name, "chunk_indices": indices[:20]})
        seen.add(name)

    # Fill from simpler extraction
    for name in names:
        if name not in seen and len(characters) < req.top_n:
            characters.append({"name": name, "chunk_indices": []})

    return {"characters": characters}


class InsightThemesRequest(BaseModel):
    session_id: str
    book_type: str = "fiction"
    top_n: int = 6


@app.post("/api/insights/themes")
async def insight_themes(req: InsightThemesRequest):
    """Extract key themes (heuristic)."""
    session = _get_session(req.session_id)
    chunks = session["chunks"]
    _, style_scores = _require_analysis(session)
    themes = extract_key_themes(chunks, style_scores, top_n=req.top_n)
    fp_density = first_person_density(chunks, lang=session["language"])
    return {"themes": themes, "first_person_density": round(fp_density, 4)}


# ── LLM Insight endpoints (Phase 2) ─────────────────────────────────────────

class NarrativeRequest(BaseModel):
    session_id: str
    book_type: str = "fiction"
    ui_lang: str = "en"
    model: str = "claude-haiku-4-5"


@app.post("/api/insights/narrative")
async def insight_narrative(req: NarrativeRequest):
    """Generate streaming narrative insight (2-3 sentences about the reading experience).

    SSE stream: yields token chunks, then a final done event.
    """
    session = _get_session(req.session_id)
    emotion_scores, style_scores = _require_analysis(session)
    api_key = _get_api_key()
    if not api_key:
        raise HTTPException(status_code=422, detail="ANTHROPIC_API_KEY not set")

    prompt = _build_narrative_prompt(
        emotion_scores, style_scores,
        session.get("arc_pattern", "Unknown"),
        req.book_type, req.ui_lang,
    )

    def event_stream():
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            accumulated: list[str] = []
            with client.messages.stream(
                model=req.model, max_tokens=250,
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                for chunk in stream.text_stream:
                    accumulated.append(chunk)
                    yield _sse({"type": "token", "text": chunk})
            full = "".join(accumulated)
            yield _sse({"type": "done", "text": full})
        except Exception as exc:
            yield _sse({"type": "error", "message": str(exc)})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


class SoulEnrichRequest(BaseModel):
    session_id: str
    model: str = "claude-haiku-4-5"
    top_n: int = 4


@app.post("/api/insights/soul-enrich")
async def insight_soul_enrich(req: SoulEnrichRequest):
    """Enrich top characters with Soul Engine (MBTI, quotes, values, emotional arc).

    SSE stream: progress per character, then done with enriched profiles.
    Requires knowledge graph extraction to have been run first.
    """
    session = _get_session(req.session_id)
    api_key = _get_api_key()
    if not api_key:
        raise HTTPException(status_code=422, detail="ANTHROPIC_API_KEY not set")

    graph: BookKnowledgeGraph | None = session.get("knowledge_graph")
    if not graph or not graph.characters:
        raise HTTPException(
            status_code=409,
            detail="Knowledge graph not extracted. Call POST /api/extract first.",
        )

    from bookscope.nlp.soul_engine import enrich_soul_profile

    characters = graph.characters[: req.top_n]
    chunks = session["chunks"]
    book = session["book"]

    def event_stream():
        total = len(characters)
        enriched = []
        for i, char in enumerate(characters):
            yield _sse({
                "type": "progress", "current": i, "total": total,
                "character": char.name,
            })
            profile = enrich_soul_profile(
                profile=char,
                chunks=chunks,
                chunk_indices=char.key_chapter_indices,
                book_title=book.title,
                language=book.language,
                api_key=api_key,
                model=req.model,
            )
            enriched.append(profile.model_dump())

        # Update the graph's characters with enriched profiles
        for i, profile_data in enumerate(enriched):
            from bookscope.models.schemas import CharacterProfile
            graph.characters[i] = CharacterProfile(**profile_data)

        yield _sse({
            "type": "done",
            "characters": enriched,
        })

    return StreamingResponse(event_stream(), media_type="text/event-stream")


class BookClubRequest(BaseModel):
    session_id: str
    book_type: str = "fiction"
    ui_lang: str = "en"
    model: str = "claude-haiku-4-5"


@app.post("/api/insights/book-club-pack")
async def insight_book_club_pack(req: BookClubRequest):
    """Generate a structured book club discussion pack (questions, difficulty, audience)."""
    session = _get_session(req.session_id)
    emotion_scores, _ = _require_analysis(session)
    api_key = _get_api_key()
    if not api_key:
        raise HTTPException(status_code=422, detail="ANTHROPIC_API_KEY not set")

    dominants = Counter(s.dominant_emotion for s in emotion_scores) if emotion_scores else Counter()
    top_emotion = dominants.most_common(1)[0][0] if dominants else "joy"
    arc_value = session.get("arc_pattern", "Unknown")
    title = session["title"]

    lang_name = {"en": "English", "zh": "Chinese", "ja": "Japanese"}.get(req.ui_lang, "English")
    type_label = {
        "fiction": "fiction", "nonfiction": "non-fiction", "academic": "non-fiction",
        "essay": "essay/memoir", "biography": "biography", "poetry": "poetry",
    }.get(req.book_type, req.book_type)

    prompt = (
        f"You are preparing a book club pack for '{title}', "
        f"a {type_label} with a {arc_value} arc, dominant emotion: {top_emotion}.\n"
        f"\nReturn ONLY valid JSON — no markdown, no explanation:\n"
        f'{{"questions": ["Q1", "Q2", "Q3"], '
        f'"difficulty": "Easy|Medium|Challenging", '
        f'"target_audience": "≤60 chars", '
        f'"arc_summary": "≤120 chars, 2-3 sentences about the emotional arc"}}\n'
        f"Rules:\n"
        f"- 3 to 5 discussion questions that explore themes, not just plot.\n"
        f"- difficulty: Easy (accessible prose), Medium (some complexity), "
        f"Challenging (dense / specialist).\n"
        f"- Use {lang_name} for all text values."
    )

    raw = call_llm(prompt, api_key=api_key, model=req.model, max_tokens=400)
    data = _parse_json_response(raw)
    if data is None:
        raise HTTPException(status_code=502, detail="LLM returned unparseable response")

    return data


class RecommendationsRequest(BaseModel):
    session_id: str
    book_type: str = "fiction"
    ui_lang: str = "en"
    model: str = "claude-haiku-4-5"


@app.post("/api/insights/recommendations")
async def insight_recommendations(req: RecommendationsRequest):
    """Generate 3-5 similar book recommendations based on analysis data."""
    session = _get_session(req.session_id)
    emotion_scores, style_scores = _require_analysis(session)
    api_key = _get_api_key()
    if not api_key:
        raise HTTPException(status_code=422, detail="ANTHROPIC_API_KEY not set")

    title = session["title"]
    arc_value = session.get("arc_pattern", "Unknown")
    dominants = Counter(s.dominant_emotion for s in emotion_scores) if emotion_scores else Counter()
    top_emotion = dominants.most_common(1)[0][0] if dominants else "joy"

    n_style = len(style_scores)
    avg_ttr = round(sum(s.ttr for s in style_scores) / n_style, 2) if n_style else 0.5
    avg_sent = round(
        sum(s.avg_sentence_length for s in style_scores) / n_style, 2
    ) if n_style else 15.0

    lang_name = {"en": "English", "zh": "Chinese", "ja": "Japanese"}.get(req.ui_lang, "English")

    prompt = (
        f"Based on a book titled '{title}' with these characteristics:\n"
        f"- Type: {req.book_type}\n"
        f"- Dominant emotion: {top_emotion}\n"
        f"- Story arc: {arc_value}\n"
        f"- Writing style: TTR={avg_ttr}, avg sentence length={avg_sent}\n\n"
        f"Return ONLY valid JSON — no markdown, no explanation:\n"
        f'{{"recommendations": [\n'
        f'  {{"title": "Book Title", "author": "Author Name", "reason": "≤80 chars why similar"}},\n'
        f'  ...\n'
        f"]}}\n"
        f"Rules:\n"
        f"- 3 to 5 recommendations of REAL, well-known books.\n"
        f"- Match based on emotional tone, writing style, and arc pattern.\n"
        f"- Use {lang_name} for the reason field."
    )

    raw = call_llm(prompt, api_key=api_key, model=req.model, max_tokens=500)
    data = _parse_json_response(raw)
    if data is None:
        raise HTTPException(status_code=502, detail="LLM returned unparseable response")

    return data


# ═══════════════════════════════════════════════════════════════════════════════
# KNOWLEDGE GRAPH EXTRACTION (SSE)
# ═══════════════════════════════════════════════════════════════════════════════


class ExtractRequest(BaseModel):
    session_id: str
    model: str = "claude-haiku-4-5"
    enrich_souls: bool = True


@app.post("/api/extract")
async def extract(req: ExtractRequest):
    """Extract knowledge graph from uploaded book. Returns SSE progress stream."""
    session = _get_session(req.session_id)
    api_key = _get_api_key()
    if not api_key:
        raise HTTPException(status_code=422, detail="ANTHROPIC_API_KEY not set")

    chunks = session["chunks"]
    book = session["book"]

    def event_stream():
        progress_events: list[str] = []

        def collect_progress(current: int, total: int):
            progress_events.append(
                _sse({"type": "progress", "current": current, "total": total})
            )

        graph = extract_knowledge_graph(
            chunks=chunks,
            book_title=book.title,
            language=book.language,
            api_key=api_key,
            model=req.model,
            progress_callback=collect_progress,
            enrich_souls=req.enrich_souls,
        )
        session["knowledge_graph"] = graph

        yield from progress_events
        yield _sse({"type": "done", "graph": graph.model_dump()})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ═══════════════════════════════════════════════════════════════════════════════
# CHAT & SEARCH
# ═══════════════════════════════════════════════════════════════════════════════

_CHUNK_CHAR_LIMIT = 600
_RAG_TOP_K = 5


def _build_chat_context(book, graph, vector_store, message: str) -> str:
    """Build hybrid context: RAG-retrieved chunks + condensed knowledge graph."""
    parts = [f"Book: {book.title}", f"Language: {book.language}"]

    if graph:
        if graph.overall_summary:
            parts.append(f"\n--- Book Summary ---\n{graph.overall_summary}")
        chars_desc = []
        for c in graph.characters[:4]:
            line = c.name
            if c.description:
                line += f" — {c.description[:80]}"
            chars_desc.append(line)
        if chars_desc:
            parts.append("Main characters: " + "; ".join(chars_desc))

    if vector_store is not None:
        retrieved = vector_store.search(message, top_k=_RAG_TOP_K)
        if retrieved:
            parts.append("\n--- Relevant passages ---")
            for chunk_result, score in retrieved:
                text = chunk_result.text[:_CHUNK_CHAR_LIMIT]
                parts.append(
                    f"[Passage {chunk_result.index + 1} (relevance: {score:.2f})]\n{text}"
                )
    elif graph:
        for ch in graph.chapter_summaries[:10]:
            if ch.summary:
                parts.append(f"Section {ch.chunk_index}: {ch.summary}")

    return "\n".join(parts)


class ChatRequest(BaseModel):
    session_id: str
    message: str
    model: str = "claude-haiku-4-5"
    character_name: str | None = None
    ui_lang: str = "en"


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    """Chat about the book using RAG. Returns SSE stream.

    character_name switches to Character Persona mode.
    """
    session = _get_session(req.session_id)
    api_key = _get_api_key()
    if not api_key:
        raise HTTPException(status_code=422, detail="ANTHROPIC_API_KEY not set")

    graph: BookKnowledgeGraph | None = session.get("knowledge_graph")
    book = session["book"]
    vector_store = session.get("vector_store")

    lang_name = {"en": "English", "zh": "Chinese", "ja": "Japanese"}.get(
        req.ui_lang, "English",
    )

    # Character Persona mode
    if req.character_name and graph:
        char = next(
            (c for c in graph.characters if c.name == req.character_name), None,
        )
        if char is not None:
            from bookscope.nlp.soul_engine import (
                build_character_context,
                build_persona_prompt,
            )

            system_prompt = build_persona_prompt(char, book.title, book.language)
            char_context = build_character_context(
                session["chunks"],
                char.key_chapter_indices,
                req.message,
                max_chars=2000,
            )
            prompt = ""
            if char_context:
                prompt += f"[Story context]\n{char_context}\n\n"
            prompt += req.message

            def char_event_stream():
                response = call_llm(
                    prompt, api_key=api_key, model=req.model,
                    max_tokens=800, system=system_prompt,
                ) or ""
                yield _sse({"type": "message", "content": response})
                yield _sse({"type": "done"})

            return StreamingResponse(
                char_event_stream(), media_type="text/event-stream",
            )

    # Book Analyst mode (default)
    context = _build_chat_context(book, graph, vector_store, req.message)
    prompt = (
        f"You are a book analysis assistant. Based on the book information and "
        f"relevant passages below, answer the user's question. "
        f"Respond in {lang_name}. "
        f"If information is insufficient, say so honestly.\n\n"
        f"{context}\n\n"
        f"User question: {req.message}"
    )

    def event_stream():
        response = call_llm(
            prompt, api_key=api_key, model=req.model, max_tokens=800,
        ) or ""
        yield _sse({"type": "message", "content": response})
        yield _sse({"type": "done"})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


class SearchRequest(BaseModel):
    session_id: str
    query: str
    max_results: int = 20


@app.post("/api/search")
async def search(req: SearchRequest):
    """Full-text keyword search across all chunks."""
    session = _get_session(req.session_id)
    chunks = session["chunks"]
    query_lower = req.query.lower()
    results = []

    for chunk in chunks:
        text_lower = chunk.text.lower()
        if query_lower in text_lower:
            # Find highlight positions
            positions = []
            start = 0
            while True:
                idx = text_lower.find(query_lower, start)
                if idx == -1:
                    break
                positions.append([idx, idx + len(req.query)])
                start = idx + 1

            # Build preview (context around first match)
            first_idx = positions[0][0] if positions else 0
            preview_start = max(0, first_idx - 60)
            preview_end = min(len(chunk.text), first_idx + 120)
            preview = chunk.text[preview_start:preview_end]
            if preview_start > 0:
                preview = "..." + preview
            if preview_end < len(chunk.text):
                preview = preview + "..."

            results.append({
                "chunk_index": chunk.index,
                "text_preview": preview,
                "highlight_positions": positions[:10],
                "match_count": len(positions),
            })

            if len(results) >= req.max_results:
                break

    return {"total_matches": len(results), "results": results}


# ═══════════════════════════════════════════════════════════════════════════════
# HEALTH
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "4.0.0"}


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _sse(data: dict) -> str:
    """Format a dict as an SSE data line."""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _build_narrative_prompt(
    emotion_scores: list[EmotionScore],
    style_scores: list[StyleScore],
    arc_pattern: str,
    book_type: str,
    ui_lang: str,
) -> str:
    """Build a narrative insight prompt from analysis data.

    Distilled from llm_analyzer.py's genre-specific builders but decoupled
    from Streamlit and AnalysisResult objects.
    """
    lang_name = {"en": "English", "zh": "Chinese", "ja": "Japanese"}.get(ui_lang, "English")
    n = len(emotion_scores)

    # Top 3 emotions
    if n > 0:
        avg_emotions = {
            f: round(sum(getattr(s, f) for s in emotion_scores) / n, 2)
            for f in _EMOTION_FIELDS
        }
    else:
        avg_emotions = {}
    top_3 = sorted(avg_emotions.items(), key=lambda x: -x[1])[:3]
    top_3_str = ", ".join(f"{e}={v}" for e, v in top_3)

    # Style summary
    n_style = len(style_scores)
    avg_ttr = round(sum(s.ttr for s in style_scores) / n_style, 2) if n_style else 0.5
    avg_sent = round(
        sum(s.avg_sentence_length for s in style_scores) / n_style, 2
    ) if n_style else 15.0

    arc_desc_map = {
        "Rags to Riches": "sustained emotional rise toward hope",
        "Riches to Rags": "sustained emotional fall toward darkness",
        "Man in a Hole": "fall then rise — protagonist recovers",
        "Icarus": "rise then fall — early success gives way to tragedy",
        "Cinderella": "rise, fall, then ultimate triumph",
        "Oedipus": "fall, brief rise, then fall again",
        "Unknown": "no clear arc detected",
    }
    arc_desc = arc_desc_map.get(arc_pattern, arc_pattern)

    if book_type in ("nonfiction", "academic", "technical", "self_help"):
        return (
            f"You are a reading advisor. Given this non-fiction book's data:\n"
            f"- Top emotions: {top_3_str}\n"
            f"- Argument trajectory: {arc_pattern} — {arc_desc}\n"
            f"- Style: TTR={avg_ttr}, avg_sentence_length={avg_sent}\n"
            f"Write 2-3 sentences about the reading experience: how dense it is, "
            f"what it demands from the reader, and a practical reading strategy. "
            f"Be specific. Use {lang_name}. No generic praise."
        )
    if book_type in ("essay", "biography", "poetry"):
        return (
            f"You are a literary companion. Given this essay/memoir's data:\n"
            f"- Emotional atmosphere: {top_3_str}\n"
            f"- Personal arc: {arc_pattern} — {arc_desc}\n"
            f"- Voice: TTR={avg_ttr}, avg_sentence_length={avg_sent}\n"
            f"Write 2-3 sentences on the author's voice, the emotional atmosphere, "
            f"and who would find it resonant. Be specific. Use {lang_name}. No generic praise."
        )
    return (
        f"You are a literary analyst. Given this fiction book's data:\n"
        f"- Top emotions: {top_3_str}\n"
        f"- Arc pattern: {arc_pattern} ({arc_desc})\n"
        f"- Style: TTR={avg_ttr}, avg_sentence_length={avg_sent}\n"
        f"Write 2-3 sentences describing the emotional experience of reading this book. "
        f"Be specific about what it FEELS like to read. "
        f"Use {lang_name}. No generic praise."
    )


def _parse_json_response(raw: str) -> dict | None:
    """Parse JSON from LLM response, stripping markdown fences."""
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(line for line in lines if not line.startswith("```")).strip()
    # Strip trailing ellipsis from call_llm truncation guard
    if text.endswith(" …"):
        text = text[:-2].strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
