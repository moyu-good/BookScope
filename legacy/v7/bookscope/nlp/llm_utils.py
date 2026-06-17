"""Shared LLM response utilities.

Consolidates JSON parsing logic from api/main.py and knowledge_extractor.py.
"""

from __future__ import annotations

import json


def parse_json_response(raw: str) -> dict | None:
    """Parse JSON from LLM response, stripping markdown fences."""
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(
            line for line in lines if not line.startswith("```")
        ).strip()
    # Strip trailing ellipsis from call_llm truncation guard
    if text.endswith(" …"):
        text = text[:-2].strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def sse_line(data: dict) -> str:
    """Format a dict as an SSE data line."""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
