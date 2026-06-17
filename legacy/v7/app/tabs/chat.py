"""BookScope — Chat Tab (Dual-Mode: Book Analyst + Character Persona).

Lets users ask questions about their book using LLM + sampled text chunks.
Also allows "Talk to Character" mode — role-play chat with book characters.

Context is built once and cached in session_state; history is a rolling
window of the last 10 turns.

Also provides a full-text keyword search over all chunks (no LLM required).

Architecture:
  - render_chat_tab(chunks, ui_lang, T, book_type, characters) -> None
  - _build_context(chunks) -> str      (cached in session_state by chunk MD5)
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

# Character-specific suggested prompts (per-language)
_CHAR_SUGGEST: dict[str, list[tuple[str, str]]] = {
    "zh": [
        ("chat_char_suggest_1", "你最大的遗憾是什么？"),
        ("chat_char_suggest_2", "你的人生信条是什么？"),
    ],
    "en": [
        ("chat_char_suggest_1", "What is your greatest regret?"),
        ("chat_char_suggest_2", "What drives you forward?"),
    ],
    "ja": [
        ("chat_char_suggest_1", "あなたの最大の後悔は何ですか？"),
        ("chat_char_suggest_2", "あなたを突き動かすものは何ですか？"),
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


def _discover_characters(chunks: list, detected_lang: str, ctx_key: str) -> list:
    """Auto-discover characters from NER and cache as lightweight profiles."""
    cache_key = f"_chat_characters_{ctx_key}"
    if cache_key in st.session_state:
        return st.session_state[cache_key]

    try:
        from bookscope.models.schemas import CharacterProfile
        from bookscope.nlp.ner_extractor import extract_character_candidates

        candidates = extract_character_candidates(chunks, detected_lang, min_chunk_spread=2)
        # Build lightweight CharacterProfile stubs sorted by frequency
        profiles = []
        for name, indices in sorted(
            candidates.items(), key=lambda x: len(x[1]), reverse=True
        )[:8]:
            profiles.append(
                CharacterProfile(
                    name=name,
                    key_chapter_indices=indices,
                )
            )
        st.session_state[cache_key] = profiles
        return profiles
    except Exception:
        st.session_state[cache_key] = []
        return []


def render_chat_tab(
    chunks,
    ui_lang: str,
    T: dict,
    book_type: str = "fiction",
    characters: list | None = None,
    detected_lang: str | None = None,
) -> None:
    """Render the Chat tab UI with dual-mode: Book Analyst + Character Persona.

    Args:
        chunks:        list[ChunkResult] from the analysis pipeline, or None if
                       the user is viewing a saved analysis (no raw text stored).
        ui_lang:       UI language code ("en" / "zh" / "ja").
        T:             Localised string dictionary.
        book_type:     "fiction" | "academic" | "essay" — selects suggested prompts.
        characters:    Optional list of CharacterProfile for persona mode.
        detected_lang: Detected book language. Falls back to ui_lang.
    """
    book_lang = detected_lang or ui_lang

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

    # ── Mode selector (Book Analyst vs Character Persona) ────────────────────
    # Auto-discover characters if not provided and book is fiction-ish
    if characters is None and book_type in ("fiction", "biography", "short_stories"):
        characters = _discover_characters(chunks, book_lang, ctx_key)

    # Check for external mode switch (e.g. from Soul Card button)
    _external_mode = st.session_state.pop("chat_mode_select", None)

    chat_options = [T.get("chat_mode_analyst", "Book Analyst")]
    char_map: dict[str, object] = {}  # display_name -> CharacterProfile
    if characters:
        for c in characters[:8]:
            label = f"\U0001f4ac {c.name}"
            chat_options.append(label)
            char_map[label] = c

    # Determine default index from external switch
    default_idx = 0
    if _external_mode and _external_mode in chat_options:
        default_idx = chat_options.index(_external_mode)

    selected_mode = chat_options[0]
    if len(chat_options) > 1:
        selected_mode = st.selectbox(
            T.get("chat_mode_label", "Chat with"),
            chat_options,
            index=default_idx,
            key="chat_mode_selector",
            label_visibility="collapsed",
        )

    is_character_mode = selected_mode in char_map
    active_char = char_map.get(selected_mode)

    # ── Chat history (separate per mode) ─────────────────────────────────────
    if is_character_mode and active_char is not None:
        hist_key = f"_char_chat_{ctx_key}_{active_char.name}"
    else:
        hist_key = f"_chat_history_{ctx_key}"

    if hist_key not in st.session_state:
        st.session_state[hist_key] = []
    history: list[dict] = st.session_state[hist_key]

    # ── Suggested prompts (shown when conversation is empty) ─────────────────
    _pending_q: str = st.session_state.pop("_chat_pending_q", "")
    if not history:
        if is_character_mode:
            _prompts = _CHAR_SUGGEST.get(ui_lang, _CHAR_SUGGEST["en"])
        else:
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
        avatar = turn.get("avatar")
        with st.chat_message(role, avatar=avatar):
            st.markdown(content)

    # Input area (st.text_input + button — avoids chat_input re-run freeze)
    if is_character_mode and active_char is not None:
        _placeholder = T.get(
            "chat_char_placeholder", "Ask {name} a question..."
        ).format(name=active_char.name)
    else:
        _placeholder = T.get("chat_input_placeholder", "What themes appear most often?")

    input_col, btn_col = st.columns([3, 1])
    with input_col:
        question = st.text_input(
            label=T.get("chat_input_label", "Ask a question about this book"),
            placeholder=_placeholder,
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

        # Build prompt differently based on mode
        history_text = "\n".join(
            f"{'User' if h['role'] == 'user' else 'Assistant'}: {h['content']}"
            for h in recent[:-1]  # exclude the current question (already in q)
        )

        with st.chat_message("assistant", avatar="\U0001f3ad" if is_character_mode else None):
            with st.spinner(""):
                if is_character_mode and active_char is not None:
                    answer = _handle_character_chat(
                        active_char, chunks, q, history_text, lang_name,
                        api_key, model,
                    )
                else:
                    answer = _handle_analyst_chat(
                        context, q, history_text, lang_name, api_key, model,
                    )
            if not answer:
                answer = T.get("chat_error", "Sorry, I couldn't generate a response. Try again.")
            st.markdown(answer)

        assistant_entry: dict = {"role": "assistant", "content": answer}
        if is_character_mode:
            assistant_entry["avatar"] = "\U0001f3ad"
        history.append(assistant_entry)
        st.session_state[hist_key] = history

        # Clear the input field by re-running
        st.rerun()

    # Clear conversation button
    if history:
        if st.button(T.get("chat_clear_btn", "Clear conversation"), key="chat_clear"):
            st.session_state[hist_key] = []
            st.rerun()


def _handle_analyst_chat(
    context: str,
    question: str,
    history_text: str,
    lang_name: str,
    api_key: str,
    model: str,
) -> str:
    """Handle a question in Book Analyst mode (original behavior)."""
    prompt = (
        f"You are a literary analyst helping a reader understand a book. "
        f"Use ONLY the excerpts below to answer. "
        f"If the answer is not in the excerpts, say so. "
        f"Respond in {lang_name}.\n\n"
        f"--- Book Excerpts ---\n{context}\n\n"
    )
    if history_text:
        prompt += f"--- Prior conversation ---\n{history_text}\n\n"
    prompt += f"--- Question ---\n{question}"

    return call_llm(prompt, api_key=api_key, model=model, max_tokens=500)


def _handle_character_chat(
    character,
    chunks: list,
    question: str,
    history_text: str,
    lang_name: str,
    api_key: str,
    model: str,
) -> str:
    """Handle a question in Character Persona mode."""
    from bookscope.nlp.soul_engine import build_character_context, build_persona_prompt

    # Detect language from lang_name
    lang_code = {"English": "en", "Chinese": "zh", "Japanese": "ja"}.get(lang_name, "en")

    # Build persona system prompt
    book_title = st.session_state.get("book_title", "")
    system_prompt = build_persona_prompt(character, book_title, lang_code)

    # Build character-specific context
    char_context = build_character_context(
        chunks, character.key_chapter_indices, question, max_chars=2000,
    )

    # Build user prompt with context + history
    prompt_parts = []
    if char_context:
        prompt_parts.append(f"[Story context for reference]\n{char_context}\n")
    if history_text:
        prompt_parts.append(f"[Prior conversation]\n{history_text}\n")
    prompt_parts.append(question)

    return call_llm(
        "\n".join(prompt_parts),
        api_key=api_key,
        model=model,
        max_tokens=500,
        system=system_prompt,
    )
