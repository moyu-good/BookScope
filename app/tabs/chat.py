"""BookScope — Chat Tab.

Lets users ask questions about their book using LLM + sampled text chunks.
Context is built once and cached in session_state; history is a rolling
window of the last 10 turns.

Architecture (from v0.9 plan):
  - render_chat_tab(chunks, ui_lang, T) -> None
  - _build_context(chunks) -> str      (cached in session_state by chunk MD5)
  - _ask_llm(question, context, history, model, api_key) -> str
  - Uses st.text_input + button pattern (not st.chat_input, avoids UI freezes)
  - chunks=None guard: show info when loaded from saved analysis
"""

import hashlib

import streamlit as st

from bookscope.nlp.llm_analyzer import call_llm

_MAX_HISTORY_TURNS = 10   # rolling window
_CONTEXT_CHARS = 3000     # ~750 tokens for chunk context
_PER_CHUNK_CHARS = 400    # ~100 tokens per chunk excerpt


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


def render_chat_tab(chunks, ui_lang: str, T: dict) -> None:
    """Render the Chat tab UI.

    Args:
        chunks:  list[ChunkResult] from the analysis pipeline, or None if
                 the user is viewing a saved analysis (no raw text stored).
        ui_lang: UI language code ("en" / "zh" / "ja").
        T:       Localised string dictionary.
    """
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

    # Chat history in session_state
    if "_chat_history" not in st.session_state:
        st.session_state["_chat_history"] = []
    history: list[dict] = st.session_state["_chat_history"]

    # Render existing conversation
    for turn in history:
        role = turn["role"]
        content = turn["content"]
        with st.chat_message(role):
            st.markdown(content)

    # Input area (st.text_input + button — avoids chat_input re-run freeze)
    input_col, btn_col = st.columns([5, 1])
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

    if send and question.strip():
        q = question.strip()

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
        st.session_state["_chat_history"] = history

        # Clear the input field by re-running
        st.rerun()

    # Clear conversation button
    if history:
        if st.button(T.get("chat_clear_btn", "Clear conversation"), key="chat_clear"):
            st.session_state["_chat_history"] = []
            st.rerun()
