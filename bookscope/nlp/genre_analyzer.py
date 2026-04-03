"""BookScope — Genre-specific deep analysis via LLM + raw text chunks.

Unlike llm_analyzer (which reads scores), this module reads ACTUAL text chunks
to extract information only available from the source text:
  - Academic/non-fiction: key concept list + argument structure
  - Essay/memoir: voice characterization + intimacy analysis

Public API:
    extract_nonfiction_concepts(chunks, lang) -> list[str]
    extract_essay_voice(chunks, lang) -> str

Both functions return empty results if ANTHROPIC_API_KEY is absent, making the
LLM analysis an optional enhancement layer over the heuristic cards.

Chunk sampling: uniform 5-chunk sampling (every total/5th chunk) covers the
full arc of the book rather than just the opening (which may be a preface).
"""

import hashlib
import os

try:
    import streamlit as st
except ImportError:
    st = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_api_key() -> str | None:
    """Resolve ANTHROPIC_API_KEY from environment or Streamlit secrets."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    if st is not None:
        try:
            return st.secrets.get("ANTHROPIC_API_KEY", None)
        except Exception:
            pass
    return None


def _sample_chunks(chunks: list, n: int = 5) -> list:
    """Return n uniformly-spaced chunks covering start→end of the book.

    For a 20-chunk book with n=5, returns chunks at indices 0, 4, 8, 12, 16.
    This ensures we read content throughout the book, not just the preface.
    """
    if not chunks:
        return []
    if len(chunks) <= n:
        return list(chunks)
    step = len(chunks) / n
    return [chunks[int(i * step)] for i in range(n)]


def _chunk_text_block(chunks: list, max_chars: int = 3000) -> str:
    """Format sampled chunks into a numbered text block for the prompt.

    Truncates each chunk to keep total context within max_chars.
    """
    if not chunks:
        return "(no text available)"
    per_chunk = max(200, max_chars // len(chunks))
    parts = []
    for i, chunk in enumerate(chunks, 1):
        text = getattr(chunk, "text", str(chunk))
        truncated = text[:per_chunk].rstrip()
        label = f"[Excerpt {i} of {len(chunks)}]"
        parts.append(f"{label}\n{truncated}")
    return "\n\n".join(parts)


def _cache_key_genre(book_title: str, genre_type: str, chunk_hashes: str) -> str:
    """Stable session-state cache key for genre analysis results."""
    content_hash = hashlib.md5(chunk_hashes.encode()).hexdigest()[:8]
    normalized = "nonfiction" if genre_type == "academic" else genre_type
    return f"genre_insight_{book_title}_{normalized}_{content_hash}"


def _get_model() -> str:
    """Return the model ID from session_state or fall back to haiku.

    MUST be called from the main Streamlit thread only — not from worker threads.
    """
    _default = "claude-haiku-4-5"
    if st is not None:
        try:
            return st.session_state.get("llm_model", _default)
        except Exception:
            pass
    return _default


def _call_llm(prompt: str, api_key: str, model: str | None = None) -> str:
    """Make a single Claude API call and return stripped text, or "".

    Args:
        prompt:   The user prompt to send.
        api_key:  Anthropic API key (resolved in the caller's thread).
        model:    Model ID.  If None, resolved via _get_model() (main-thread safe only).
                  Pass model explicitly when calling from a worker thread.
    """
    try:
        import anthropic

        resolved_model = model if model is not None else _get_model()
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=resolved_model,
            max_tokens=250,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip() if message.content else ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Non-fiction: concept extraction
# ---------------------------------------------------------------------------

def _build_nonfiction_prompt(text_block: str, lang: str) -> str:
    lang_name = {"en": "English", "zh": "Chinese", "ja": "Japanese"}.get(lang, "English")
    return (
        f"You are a reading advisor analysing a non-fiction book.\n"
        f"Here are {text_block.count('[Excerpt')} representative excerpts "
        f"sampled uniformly from start to finish:\n\n"
        f"{text_block}\n\n"
        f"Based ONLY on these excerpts:\n"
        f"1. List the 4-6 most important concepts or terms (comma-separated, "
        f"noun phrases only, no articles).\n"
        f"2. In one sentence, describe the author's argumentative style "
        f"(e.g. builds from evidence, states thesis early, uses case studies).\n\n"
        f"Format your response as:\n"
        f"CONCEPTS: <comma-separated list>\n"
        f"ARGUMENT: <one sentence>\n\n"
        f"Use {lang_name}. No additional commentary."
    )


def _parse_nonfiction_response(text: str) -> tuple[list[str], str]:
    """Parse the structured response into (concepts_list, argument_sentence)."""
    concepts: list[str] = []
    argument = ""
    for line in text.splitlines():
        line = line.strip()
        if line.upper().startswith("CONCEPTS:"):
            raw = line.split(":", 1)[1].strip()
            concepts = [c.strip() for c in raw.split(",") if c.strip()]
        elif line.upper().startswith("ARGUMENT:"):
            argument = line.split(":", 1)[1].strip()
    return concepts, argument


def extract_nonfiction_concepts(
    chunks: list,
    lang: str,
    book_title: str = "",
    model: str | None = None,
) -> tuple[list[str], str]:
    """Extract key concepts and argument style from non-fiction text.

    Args:
        chunks:     list[ChunkResult] — raw chunks from chunker
        lang:       UI language code ("en" / "zh" / "ja")
        book_title: used for session-state cache key
        model:      Model ID to use.  If None, read from session_state (main-thread only).
                    Pass explicitly when calling from a ThreadPoolExecutor worker.

    Returns:
        (concepts: list[str], argument_sentence: str)
        Both are empty when the API key is absent or the call fails.
    """
    api_key = _get_api_key()
    if not api_key:
        return [], ""

    sampled = _sample_chunks(chunks, n=5)
    chunk_hashes = "".join(getattr(c, "text", str(c))[:40] for c in sampled)
    ck = _cache_key_genre(book_title, "nonfiction", chunk_hashes)

    if st is not None:
        try:
            cached = st.session_state.get(ck)
            if cached is not None:
                return cached
        except Exception:
            pass

    text_block = _chunk_text_block(sampled)
    prompt = _build_nonfiction_prompt(text_block, lang)
    response = _call_llm(prompt, api_key, model=model)
    result = _parse_nonfiction_response(response) if response else ([], "")

    if st is not None and ck:
        try:
            st.session_state[ck] = result
        except Exception:
            pass

    return result


# ---------------------------------------------------------------------------
# Non-fiction: concept relation extraction (for concept graph)
# ---------------------------------------------------------------------------

def _build_concept_relation_prompt(text_block: str, lang: str) -> str:
    lang_name = {"en": "English", "zh": "Chinese", "ja": "Japanese"}.get(lang, "English")
    return (
        f"You are analysing a non-fiction book.\n"
        f"Here are {text_block.count('[Excerpt')} representative excerpts:\n\n"
        f"{text_block}\n\n"
        f"Extract key concepts and their relationships.\n"
        f"Return ONLY valid JSON — no markdown, no explanation:\n"
        '{{"concepts": ["Concept A", ...], "relations": [{{"source": "A", '
        '"target": "B", "relation": "supports|contradicts|extends|defines"}}]}}\n'
        "Rules:\n"
        "- Max 8 concepts, max 12 relations.\n"
        "- relation must be one of: supports, contradicts, extends, defines.\n"
        "  supports=A is evidence for B; contradicts=A conflicts with B;\n"
        "  extends=A builds on B; defines=A provides definition of B.\n"
        f"Use {lang_name} for concept names."
    )


def _parse_concept_graph(raw: str) -> tuple[list[str], list[dict]]:
    """Parse LLM JSON into (concepts, raw_relations). Returns ([], []) on failure."""
    import json

    if not raw:
        return [], []
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(line for line in lines if not line.startswith("```")).strip()
    try:
        data = json.loads(text)
        concepts = [str(c).strip() for c in data.get("concepts", []) if c][:8]
        valid_types = {"supports", "contradicts", "extends", "defines"}
        raw_relations = []
        for r in data.get("relations", []):
            src = str(r.get("source", "")).strip()
            tgt = str(r.get("target", "")).strip()
            rel = str(r.get("relation", "")).strip().lower()
            if src and tgt and rel in valid_types:
                raw_relations.append({"source": src, "target": tgt, "relation": rel})
        return concepts, raw_relations[:12]
    except Exception:
        return [], []


def extract_concept_relations(
    chunks: list,
    lang: str,
    book_title: str = "",
    model: str | None = None,
):
    """Extract concept relationships from non-fiction text for concept graph.

    Returns a RelationGraph (from relation_extractor) where characters = concepts.
    Returns empty graph if API key absent / call fails / <2 concepts.
    """
    from bookscope.nlp.relation_extractor import CharacterRelation, RelationGraph

    api_key = _get_api_key()
    if not api_key:
        return RelationGraph(characters=[], relations=[])

    sampled = _sample_chunks(chunks, n=5)
    chunk_hashes = "".join(getattr(c, "text", str(c))[:40] for c in sampled)
    ck = _cache_key_genre(book_title, "concept_graph", chunk_hashes)

    if st is not None:
        try:
            cached = st.session_state.get(ck)
            if cached is not None:
                return cached
        except Exception:
            pass

    text_block = _chunk_text_block(sampled)
    prompt = _build_concept_relation_prompt(text_block, lang)
    response = _call_llm(prompt, api_key, model=model)

    concepts, raw_relations = _parse_concept_graph(response) if response else ([], [])
    relations = [
        CharacterRelation(source=r["source"], target=r["target"], relation=r["relation"])
        for r in raw_relations
        if r["source"] in concepts and r["target"] in concepts
    ]
    graph = RelationGraph(characters=concepts, relations=relations)

    if st is not None and ck:
        try:
            st.session_state[ck] = graph
        except Exception:
            pass

    return graph


# ---------------------------------------------------------------------------
# Essay / memoir: voice characterization
# ---------------------------------------------------------------------------

def _build_essay_prompt(text_block: str, lang: str) -> str:
    lang_name = {"en": "English", "zh": "Chinese", "ja": "Japanese"}.get(lang, "English")
    return (
        f"You are a literary companion analysing an essay or memoir.\n"
        f"Here are {text_block.count('[Excerpt')} representative excerpts "
        f"from across the book:\n\n"
        f"{text_block}\n\n"
        f"Based ONLY on these excerpts, write 2 sentences:\n"
        f"1. Describe the author's voice and sentence rhythm "
        f"(e.g. lyrical, spare, conversational, meditative).\n"
        f"2. Describe the emotional atmosphere "
        f"(e.g. melancholy but hopeful, wry and detached, warmly intimate).\n\n"
        f"Be specific. Use {lang_name}. No generic praise."
    )


def extract_essay_voice(
    chunks: list,
    lang: str,
    book_title: str = "",
    model: str | None = None,
) -> str:
    """Characterize the author's voice and emotional atmosphere from essay text.

    Args:
        chunks:     list[ChunkResult] — raw chunks from chunker
        lang:       UI language code ("en" / "zh" / "ja")
        book_title: used for session-state cache key
        model:      Model ID to use.  If None, read from session_state (main-thread only).
                    Pass explicitly when calling from a ThreadPoolExecutor worker.

    Returns:
        2-sentence voice description, or "" if API key absent / call fails.
    """
    api_key = _get_api_key()
    if not api_key:
        return ""

    sampled = _sample_chunks(chunks, n=5)
    chunk_hashes = "".join(getattr(c, "text", str(c))[:40] for c in sampled)
    ck = _cache_key_genre(book_title, "essay", chunk_hashes)

    if st is not None:
        try:
            cached = st.session_state.get(ck)
            if cached is not None:
                return cached
        except Exception:
            pass

    text_block = _chunk_text_block(sampled)
    prompt = _build_essay_prompt(text_block, lang)
    result = _call_llm(prompt, api_key, model=model)

    if st is not None and ck:
        try:
            st.session_state[ck] = result
        except Exception:
            pass

    return result


# ---------------------------------------------------------------------------
# Essay: key phrase extraction for timeline
# ---------------------------------------------------------------------------

def _build_essay_phrases_prompt(text_block: str, lang: str) -> str:
    lang_name = {"en": "English", "zh": "Chinese", "ja": "Japanese"}.get(lang, "English")
    return (
        f"You are analysing an essay or memoir.\n"
        f"Here are {text_block.count('[Excerpt')} representative excerpts:\n\n"
        f"{text_block}\n\n"
        f"For each excerpt, give ONE key idea phrase (maximum 10 characters each).\n"
        f"Return ONLY a JSON array of strings — no markdown, no explanation:\n"
        f'["phrase1", "phrase2", ...]\n\n'
        f"The array length must equal the number of excerpts above.\n"
        f"Use {lang_name}."
    )


def _parse_essay_phrases(raw: str) -> list[str]:
    """Parse JSON array of phrases from LLM response."""
    import json

    if not raw:
        return []
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(line for line in lines if not line.startswith("```")).strip()
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return [str(p)[:10].strip() for p in data if p]
        return []
    except Exception:
        return []


def extract_essay_phrases(
    chunks: list,
    lang: str,
    book_title: str = "",
    model: str | None = None,
) -> list[str]:
    """Return one key phrase per sampled chunk (≤10 chars each) for timeline.

    Uses 8-chunk uniform sampling. Returns [] if API absent / call fails.
    """
    api_key = _get_api_key()
    if not api_key:
        return []

    sampled = _sample_chunks(chunks, n=8)
    if not sampled:
        return []

    chunk_hashes = "".join(getattr(c, "text", str(c))[:40] for c in sampled)
    ck = _cache_key_genre(book_title, "essay_phrases", chunk_hashes)

    if st is not None:
        try:
            cached = st.session_state.get(ck)
            if cached is not None:
                return cached
        except Exception:
            pass

    text_block = _chunk_text_block(sampled)
    prompt = _build_essay_phrases_prompt(text_block, lang)
    response = _call_llm(prompt, api_key, model=model)

    phrases = _parse_essay_phrases(response) if response else []

    if st is not None and ck:
        try:
            st.session_state[ck] = phrases
        except Exception:
            pass

    return phrases
