"""BookScope — Chat Tab.

Lets users ask questions about their book using LLM + sampled text chunks.
Context is built once and cached in session_state; history is a rolling
window of the last 10 turns.

Also provides a full-text keyword search over all chunks (no LLM required).

Architecture (from v0.9 plan):
  - render_chat_tab(chunks, ui_lang, T) -> None
  - _build_context(chunks) -> str      (cached in session_state by chunk MD5)
  - _ask_llm(question, context, history, model, api_key) -> str
  - Uses st.text_input + button pattern (not st.chat_input, avoids UI freezes)
  - chunks=None guard: show info when loaded from saved analysis
"""

import hashlib
import html
import re

import streamlit as st

from bookscope.nlp.llm_analyzer import call_llm

_MAX_HISTORY_TURNS = 10   # rolling window
_CONTEXT_CHARS = 3000     # ~750 tokens for chunk context
_PER_CHUNK_CHARS = 400    # ~100 tokens per chunk excerpt

# Suggested prompt definitions: (strings_key, llm_prompt_en)
# Button labels come from T[strings_key]; LLM always receives the English prompt
# (chat.py already tells the LLM to respond in the user's UI language)
_SUGGEST_PROMPTS: dict[str, list[tuple[str, str]]] = {
    "fiction": [
        (
            "chat_suggest_fiction_1",
            "Briefly summarize what happens in each section or chapter of this book.",
        ),
        (
            "chat_suggest_fiction_2",
            "Who are the main characters? Describe each one in 1–2 sentences.",
        ),
    ],
    "academic": [
        (
            "chat_suggest_academic_1",
            "What is the core argument or thesis of this book? Explain clearly.",
        ),
        (
            "chat_suggest_academic_2",
            "What are the key concepts introduced in this book? List and briefly define them.",
        ),
    ],
    "essay": [
        (
            "chat_suggest_essay_1",
            "What is the author's core theme or central message in this essay?",
        ),
        (
            "chat_suggest_essay_2",
            "Analyze the narrative voice and point of view used in this essay.",
        ),
    ],
    "biography": [
        (
            "chat_suggest_biography_1",
            "What does this memoir or biography reveal about the subject's"
            " personality and worldview?",
        ),
        (
            "chat_suggest_biography_2",
            "What are the key turning points in the subject's life as described in this book?",
        ),
    ],
    "short_stories": [
        (
            "chat_suggest_short_stories_1",
            "Briefly summarize each story. What themes or ideas connect them?",
        ),
        (
            "chat_suggest_short_stories_2",
            "Which story has the strongest emotional impact and why?",
        ),
    ],
    "poetry": [
        (
            "chat_suggest_poetry_1",
            "What is the central theme or emotional mood of this poetry collection?",
        ),
        (
            "chat_suggest_poetry_2",
            "Describe the poet's voice, recurring imagery, and use of language.",
        ),
    ],
    "technical": [
        (
            "chat_suggest_technical_1",
            "What is the main technical problem or domain this book addresses?",
        ),
        (
            "chat_suggest_technical_2",
            "What are the key concepts, methods, or frameworks taught in this book?",
        ),
    ],
    "self_help": [
        (
            "chat_suggest_self_help_1",
            "What is the core framework or method this book teaches?",
        ),
        (
            "chat_suggest_self_help_2",
            "What are the most actionable insights or habit changes recommended in this book?",
        ),
    ],
}


def _build_context(chunks: list) -> str:
    """Build a text context block from up to 8 uniformly-sampled chunks.

    Cached in session_state by md5 of the combined chunk texts so repeated
    questions in the same session don't re-build the context.
    """
    if not chunks:
        return ""

    n = len(chunks)
    sample_size = min(8, n)
    indices = [i * n // sample_size for i in range(sample_size)]
    sampled = [chunks[i] for i in indices]

    # Per-chunk character budget to stay within CONTEXT_CHARS
    per_chunk = max(_PER_CHUNK_CHARS, _CONTEXT_CHARS // len(sampled))

    parts = []
    for i, chunk in enumerate(sampled, 1):
        text = getattr(chunk, "text", str(chunk))
        truncated = text[:per_chunk].rstrip()
        parts.append(f"[Excerpt {i} of {len(sampled)}]\n{truncated}")

    return "\n\n".join(parts)


def _context_cache_key(chunks: list) -> str:
    combined = "".join(getattr(c, "text", str(c))[:40] for c in chunks)
    return "chat_ctx_" + hashlib.md5(combined.encode()).hexdigest()[:8]


def render_chat_tab(
    chunks, ui_lang: str, T: dict, book_type: str = "fiction"
) -> None:
    """Render the Chat tab UI.

    Args:
        chunks:    list[ChunkResult] from the analysis pipeline, or None if
                   the user is viewing a saved analysis (no raw text stored).
        ui_lang:   UI language code ("en" / "zh" / "ja").
        T:         Localised string dictionary.
        book_type: "fiction" | "academic" | "essay" — selects suggested prompts.
    """
    # ── Full-text search (no LLM required) ───────────────────────────────────
    if chunks is not None:
        s_col, b_col = st.columns([3, 1])
        with s_col:
            search_kw = st.text_input(
                label=T.get("chat_search_label", "Search in book"),
                placeholder=T.get("chat_search_placeholder", "Enter keyword to search..."),
                label_visibility="collapsed",
                key="chat_search_input",
            )
        with b_col:
            do_search = st.button(
                T.get("chat_search_btn", "Search"),
                use_container_width=True,
                key="chat_search_btn_key",
            )

        if do_search and search_kw.strip():
            kw = search_kw.strip()
            kw_lower = kw.lower()
            matches = [c for c in chunks if kw_lower in getattr(c, "text", "").lower()]
            if matches:
                st.caption(T.get("chat_search_results", 'Found {n} match(es) for "{kw}"').format(
                    n=len(matches), kw=kw
                ))
                for chunk in matches[:10]:
                    idx = getattr(chunk, "index", "?")
                    label = T.get("chat_search_chunk", "Chunk {idx}").format(idx=idx)
                    # HTML-escape before highlighting to prevent XSS
                    safe_text = html.escape(getattr(chunk, "text", ""))
                    safe_kw = html.escape(kw)
                    highlighted = re.sub(
                        f"(?i){re.escape(safe_kw)}",
                        lambda m: f"**{m.group(0)}**",
                        safe_text,
                    )
                    with st.expander(label, expanded=False):
                        st.markdown(highlighted[:800] + ("…" if len(highlighted) > 800 else ""))
                if len(matches) > 10:
                    st.caption(f"… and {len(matches) - 10} more")
            else:
                msg = T.get("chat_search_no_results", 'No matches found for "{kw}"')
                st.info(msg.format(kw=kw))

        st.divider()

    # Guard: saved analyses don't have raw chunks
    if chunks is None:
        st.info(T.get(
            "chat_no_chunks",
            "Chat requires re-analyzing the book. Raw text is not stored in saved analyses.",
        ))
        return

    # Resolve API key and model (must be done in main Streamlit thread)
    import os
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        try:
            api_key = st.secrets.get("ANTHROPIC_API_KEY", None)
        except Exception:
            pass

    if not api_key:
        st.info(T.get(
            "chat_no_key",
            "Chat requires an LLM key. Add ANTHROPIC_API_KEY to enable this tab.",
        ))
        return

    model = st.session_state.get("llm_model", "claude-haiku-4-5")
    lang_name = {"en": "English", "zh": "Chinese", "ja": "Japanese"}.get(ui_lang, "English")

    # Build context (cached per book)
    ctx_key = _context_cache_key(chunks)
    context: str = st.session_state.get(ctx_key, "")
    if not context:
        context = _build_context(chunks)
        st.session_state[ctx_key] = context

    # Chat history keyed per book (ctx_key is unique per book's content)
    hist_key = f"_chat_history_{ctx_key}"
    if hist_key not in st.session_state:
        st.session_state[hist_key] = []
    history: list[dict] = st.session_state[hist_key]

    # ── Suggested prompts (shown when conversation is empty) ─────────────────
    _pending_q: str = st.session_state.pop("_chat_pending_q", "")
    if not history:
        _prompts = _SUGGEST_PROMPTS.get(book_type, _SUGGEST_PROMPTS["fiction"])
        _pcols = st.columns(len(_prompts))
        for i, (_str_key, _llm_prompt) in enumerate(_prompts):
            _btn_label = T.get(_str_key, _llm_prompt)
            if _pcols[i].button(_btn_label, use_container_width=True, key=f"_sp_{i}"):
                st.session_state["_chat_pending_q"] = _llm_prompt
                st.rerun()
        st.write("")

    # Render existing conversation
    for turn in history:
        role = turn["role"]
        content = turn["content"]
        with st.chat_message(role):
            st.markdown(content)

    # Input area (st.text_input + button — avoids chat_input re-run freeze)
    input_col, btn_col = st.columns([3, 1])
    with input_col:
        question = st.text_input(
            label=T.get("chat_input_label", "Ask a question about this book"),
            placeholder=T.get("chat_input_placeholder", "What themes appear most often?"),
            label_visibility="collapsed",
            key="chat_question_input",
        )
    with btn_col:
        send = st.button(
            T.get("chat_send_btn", "Send"),
            use_container_width=True,
        )

    # Resolve question: either from input box or from a pending suggested prompt
    _active_question = _pending_q or (question.strip() if send else "")

    if _active_question:
        q = _active_question

        # Add user message to history
        history.append({"role": "user", "content": q})
        with st.chat_message("user"):
            st.markdown(q)

        # Prune history to rolling window before sending to LLM
        recent = history[-(_MAX_HISTORY_TURNS * 2):]  # 10 turns = 20 entries

        # Build prompt
        history_text = "\n".join(
            f"{'User' if h['role'] == 'user' else 'Assistant'}: {h['content']}"
            for h in recent[:-1]  # exclude the current question (already in q)
        )
        prompt = (
            f"You are a literary analyst helping a reader understand a book. "
            f"Use ONLY the excerpts below to answer. "
            f"If the answer is not in the excerpts, say so. "
            f"Respond in {lang_name}.\n\n"
            f"--- Book Excerpts ---\n{context}\n\n"
        )
        if history_text:
            prompt += f"--- Prior conversation ---\n{history_text}\n\n"
        prompt += f"--- Question ---\n{q}"

        with st.chat_message("assistant"):
            with st.spinner(""):
                answer = call_llm(prompt, api_key=api_key, model=model, max_tokens=500)
            if not answer:
                answer = T.get("chat_error", "Sorry, I couldn't generate a response. Try again.")
            st.markdown(answer)

        history.append({"role": "assistant", "content": answer})
        st.session_state[hist_key] = history

        # Clear the input field by re-running
        st.rerun()

    # Clear conversation button
    if history:
        if st.button(T.get("chat_clear_btn", "Clear conversation"), key="chat_clear"):
            st.session_state[hist_key] = []
            st.rerun()
