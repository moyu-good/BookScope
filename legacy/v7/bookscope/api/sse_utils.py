"""SSE (Server-Sent Events) helpers."""

from __future__ import annotations

import json


def sse(data: dict) -> str:
    """Format a dict as an SSE data line."""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
