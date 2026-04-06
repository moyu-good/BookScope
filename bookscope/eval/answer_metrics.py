"""BookScope — Answer quality evaluation metrics (LLM-as-judge).

Uses the existing ``call_llm`` wrapper to evaluate answer quality.
Two metrics:
- **Faithfulness**: Is the answer grounded in the retrieved contexts?
- **Answer Relevancy**: Does the answer address the question?
"""

from __future__ import annotations

import json
import logging

from bookscope.nlp.llm_analyzer import call_llm

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_llm_response(text: str) -> str:
    """Strip markdown fences and the trailing ' …' that call_llm may append."""
    text = text.strip()
    # Strip markdown code fences
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(line for line in lines if not line.startswith("```")).strip()
    # Strip call_llm truncation suffix
    if text.endswith(" \u2026"):
        text = text[:-2].rstrip()
    return text


def _parse_json_array(text: str) -> list | None:
    """Parse a JSON array from LLM output, returning None on failure."""
    cleaned = _clean_llm_response(text)
    if not cleaned:
        return None
    try:
        data = json.loads(cleaned)
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, ValueError):
        pass
    return None


# ---------------------------------------------------------------------------
# Faithfulness
# ---------------------------------------------------------------------------

def faithfulness(
    answer: str,
    contexts: list[str],
    *,
    api_key: str | None = None,
    model: str | None = None,
) -> float:
    """Score how well the answer is grounded in retrieved contexts.

    Step 1: Decompose answer into atomic claims.
    Step 2: For each claim, judge SUPPORTED/NOT_SUPPORTED (NLI).
    Returns supported_claims / total_claims, or 0.0 on failure.
    """
    if not answer or not answer.strip():
        return 0.0

    # Step 1: claim decomposition
    decompose_prompt = (
        "Given the following answer, decompose it into a list of atomic factual claims.\n"
        "Each claim should be a single, verifiable statement.\n\n"
        f"Answer: {answer}\n\n"
        "Return ONLY a JSON array of strings. No explanation, no markdown."
    )
    raw_claims = call_llm(decompose_prompt, api_key=api_key, model=model, max_tokens=500)
    claims = _parse_json_array(raw_claims)
    if not claims:
        return 0.0

    # Step 2: NLI verification (batched into a single call)
    context_text = "\n\n".join(contexts)
    claims_list = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(claims))
    nli_prompt = (
        "Given the following context and claims, for each claim determine if it is "
        "SUPPORTED or NOT_SUPPORTED by the context.\n\n"
        f"Context:\n{context_text}\n\n"
        f"Claims:\n{claims_list}\n\n"
        "Return ONLY a JSON array of verdicts, e.g. "
        '["SUPPORTED", "NOT_SUPPORTED"]. One per claim, in order.'
    )
    raw_verdicts = call_llm(nli_prompt, api_key=api_key, model=model, max_tokens=300)
    verdicts = _parse_json_array(raw_verdicts)
    if not verdicts:
        return 0.0

    supported = sum(1 for v in verdicts if str(v).upper() == "SUPPORTED")
    return supported / len(claims)


# ---------------------------------------------------------------------------
# Answer Relevancy
# ---------------------------------------------------------------------------

def answer_relevancy(
    question: str,
    answer: str,
    *,
    api_key: str | None = None,
    model: str | None = None,
) -> float:
    """Score how well the answer addresses the question (0.0 to 1.0)."""
    if not answer or not answer.strip():
        return 0.0

    prompt = (
        "Rate how well the following answer addresses the given question.\n"
        "Return ONLY a single decimal number between 0.0 and 1.0.\n"
        "0.0 = completely irrelevant, 1.0 = perfectly addresses the question.\n\n"
        f"Question: {question}\n"
        f"Answer: {answer}\n\n"
        "Return ONLY the number, nothing else."
    )
    raw = call_llm(prompt, api_key=api_key, model=model, max_tokens=20)
    cleaned = _clean_llm_response(raw)
    try:
        score = float(cleaned)
        return max(0.0, min(1.0, score))
    except (ValueError, TypeError):
        return 0.0
