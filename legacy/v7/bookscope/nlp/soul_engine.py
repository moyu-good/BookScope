"""BookScope v3 — Character Soul Engine.

Extracts character dialogues, enriches soul profiles via LLM, and builds
persona prompts for character role-play chat.

Pure Python module — no Streamlit dependency.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

from bookscope.models.schemas import CharacterProfile, EmotionalStage
from bookscope.nlp.llm_analyzer import call_llm
from bookscope.nlp.ner_extractor import (
    _EN_SPEECH_VERBS,
    _ZH_SPEECH_VERBS,
)

if TYPE_CHECKING:
    from bookscope.models.schemas import ChunkResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dialogue extraction patterns (capture the quoted text, not just the name)
# ---------------------------------------------------------------------------

# Chinese: "…" followed by name+verb  OR  name+verb+"…"
_ZH_QUOTE_PAT = re.compile(
    r"\u201c([^\u201d]{4,80})\u201d\s*"
    + r"(?:[\u4e00-\u9fff]{2,4})"
    + _ZH_SPEECH_VERBS
    + r"|"
    + r"(?:[\u4e00-\u9fff]{2,4})"
    + _ZH_SPEECH_VERBS
    + r"\s*(?:：|:)?\s*\u201c([^\u201d]{4,80})\u201d"
)

# English: "…" said Name  OR  Name said "…"
_EN_QUOTE_PAT = re.compile(
    r'"([^"]{10,200})"\s*'
    + _EN_SPEECH_VERBS
    + r"\s+[A-Z][a-z]+"
    + r"|"
    + r"[A-Z][a-z]+\s+"
    + _EN_SPEECH_VERBS
    + r'\s*,?\s*"([^"]{10,200})"'
)

# Japanese: 「…」と{Name}が
_JA_QUOTE_PAT = re.compile(
    r"\u300c([^\u300d]{4,80})\u300d\s*(?:\u3068)?\s*"
    r"[\u3040-\u9fff]{2,6}(?:\u304c|\u306f)"
)

_QUOTE_PATTERNS: dict[str, re.Pattern[str]] = {
    "zh": _ZH_QUOTE_PAT,
    "en": _EN_QUOTE_PAT,
    "ja": _JA_QUOTE_PAT,
}

# ---------------------------------------------------------------------------
# A) Dialogue extraction — pure regex, zero LLM
# ---------------------------------------------------------------------------


def extract_character_dialogues(
    chunks: list[ChunkResult],
    character_name: str,
    aliases: list[str] | None = None,
    language: str = "zh",
    max_quotes: int = 10,
) -> list[str]:
    """Extract dialogue lines attributed to *character_name* from chunks.

    Uses language-aware regex to find quoted speech near the character's name.
    Falls back to a simpler "name near quotes" heuristic when the structured
    pattern yields few results.

    Returns up to *max_quotes* quotes sorted by length descending (longer
    quotes tend to be more characteristic).
    """
    all_names = {character_name}
    if aliases:
        all_names.update(aliases)

    pattern = _QUOTE_PATTERNS.get(language)
    quotes: list[str] = []

    for chunk in chunks:
        text = chunk.text
        # Check if this chunk mentions the character at all
        if not any(n in text for n in all_names):
            continue

        if pattern:
            for m in pattern.finditer(text):
                # Pattern groups: one will be None depending on which branch matched
                quote = m.group(1) or m.group(2) if m.lastindex and m.lastindex >= 2 else m.group(1)
                if quote and _quote_near_name(text, m.start(), m.end(), all_names):
                    quotes.append(quote.strip())

        # Fallback: grab any quoted text near the character name
        if len(quotes) < 3:
            quotes.extend(_fallback_quotes(text, all_names, language))

    # Deduplicate preserving order, sort by length desc
    seen: set[str] = set()
    unique: list[str] = []
    for q in quotes:
        if q not in seen:
            seen.add(q)
            unique.append(q)
    unique.sort(key=len, reverse=True)
    return unique[:max_quotes]


def _quote_near_name(
    text: str, match_start: int, match_end: int, names: set[str], window: int = 120
) -> bool:
    """Check if any character name appears within *window* chars of the match."""
    start = max(0, match_start - window)
    end = min(len(text), match_end + window)
    region = text[start:end]
    return any(n in region for n in names)


def _fallback_quotes(text: str, names: set[str], language: str) -> list[str]:
    """Simple fallback: find quoted text within 80 chars of a name mention."""
    results: list[str] = []
    if language == "zh":
        quote_pat = re.compile(r"\u201c([^\u201d]{4,80})\u201d")
    elif language == "ja":
        quote_pat = re.compile(r"\u300c([^\u300d]{4,80})\u300d")
    else:
        quote_pat = re.compile(r'"([^"]{10,200})"')

    for m in quote_pat.finditer(text):
        if _quote_near_name(text, m.start(), m.end(), names, window=80):
            results.append(m.group(1).strip())
    return results


# ---------------------------------------------------------------------------
# B) Soul profile enrichment — single LLM call per character
# ---------------------------------------------------------------------------

_SOUL_PROMPT_ZH = """\
你是一个文学人物分析专家。根据以下书籍片段，分析角色「{name}」。

返回严格合法 JSON（不要 markdown 代码块），schema:
{{
  "personality_type": "MBTI类型 — 中文名称（如 INTJ — 策略家）",
  "values": ["核心价值观1", "核心价值观2", "核心价值观3"],
  "key_quotes": ["代表性语录1", "代表性语录2", "代表性语录3"],
  "emotional_stages": [
    {{"stage": "early", "emotion": "情感词", "event": "关键事件"}},
    {{"stage": "middle", "emotion": "情感词", "event": "关键事件"}},
    {{"stage": "late", "emotion": "情感词", "event": "关键事件"}}
  ]
}}

书名：《{book_title}》
角色：{name}
已知信息：{description}

相关片段：
{context}
"""

_SOUL_PROMPT_EN = """\
You are a literary character analyst. Analyze the character "{name}" \
based on the book excerpts below.

Return ONLY valid JSON (no markdown fences), schema:
{{
  "personality_type": "MBTI type — label (e.g. INTJ — Architect)",
  "values": ["core value 1", "core value 2", "core value 3"],
  "key_quotes": ["representative quote 1", "representative quote 2"],
  "emotional_stages": [
    {{"stage": "early", "emotion": "emotion word", "event": "key event"}},
    {{"stage": "middle", "emotion": "emotion word", "event": "key event"}},
    {{"stage": "late", "emotion": "emotion word", "event": "key event"}}
  ]
}}

Book: {book_title}
Character: {name}
Known info: {description}

Relevant excerpts:
{context}
"""

_SOUL_PROMPT_JA = """\
あなたは文学キャラクター分析の専門家です。以下の書籍抜粋に基づいて、\
キャラクター「{name}」を分析してください。

厳密な JSON のみを返してください（マークダウンフェンスなし）。スキーマ：
{{
  "personality_type": "MBTIタイプ — 日本語名（例：INTJ — 建築家）",
  "values": ["核心的価値観1", "核心的価値観2", "核心的価値観3"],
  "key_quotes": ["代表的な台詞1", "代表的な台詞2"],
  "emotional_stages": [
    {{"stage": "early", "emotion": "感情語", "event": "主要イベント"}},
    {{"stage": "middle", "emotion": "感情語", "event": "主要イベント"}},
    {{"stage": "late", "emotion": "感情語", "event": "主要イベント"}}
  ]
}}

書名：{book_title}
キャラクター：{name}
既知情報：{description}

関連抜粋：
{context}
"""

_SOUL_PROMPTS: dict[str, str] = {
    "zh": _SOUL_PROMPT_ZH,
    "en": _SOUL_PROMPT_EN,
    "ja": _SOUL_PROMPT_JA,
}


def enrich_soul_profile(
    profile: CharacterProfile,
    chunks: list[ChunkResult],
    chunk_indices: list[int],
    book_title: str,
    language: str = "zh",
    api_key: str | None = None,
    model: str = "claude-haiku-4-5",
) -> CharacterProfile:
    """Enrich a CharacterProfile with soul data (MBTI, quotes, values, arc).

    Makes one LLM call per character.  On failure returns the original profile
    unchanged (graceful degradation).
    """
    # Collect context from character's chunks (capped ~3000 chars)
    context_parts: list[str] = []
    total = 0
    for idx in chunk_indices:
        if idx < len(chunks):
            part = chunks[idx].text[:800]
            if total + len(part) > 3000:
                break
            context_parts.append(part)
            total += len(part)

    if not context_parts:
        return profile

    context = "\n---\n".join(context_parts)

    # Extract dialogues via regex first
    regex_quotes = extract_character_dialogues(
        [chunks[i] for i in chunk_indices if i < len(chunks)],
        profile.name,
        profile.aliases,
        language,
        max_quotes=5,
    )

    # LLM enrichment
    template = _SOUL_PROMPTS.get(language, _SOUL_PROMPT_EN)
    prompt = template.format(
        name=profile.name,
        book_title=book_title,
        description=profile.description or "N/A",
        context=context,
    )

    raw = call_llm(prompt, api_key=api_key, model=model, max_tokens=800)
    data = _parse_soul_json(raw)
    if data is None:
        # Even without LLM, populate regex quotes
        if regex_quotes:
            profile = profile.model_copy(update={"key_quotes": regex_quotes})
        return profile

    # Merge LLM results into profile
    updates: dict = {}
    if data.get("personality_type"):
        updates["personality_type"] = str(data["personality_type"])
    if data.get("values"):
        updates["values"] = [str(v) for v in data["values"][:5]]

    # Merge regex + LLM quotes, dedup
    llm_quotes = [str(q) for q in data.get("key_quotes", []) if q]
    merged_quotes = _dedup_list(regex_quotes + llm_quotes)[:5]
    if merged_quotes:
        updates["key_quotes"] = merged_quotes

    if data.get("emotional_stages"):
        stages = []
        for s in data["emotional_stages"][:4]:
            if isinstance(s, dict):
                stages.append(
                    EmotionalStage(
                        stage=str(s.get("stage", "")),
                        emotion=str(s.get("emotion", "")),
                        event=str(s.get("event", "")),
                    )
                )
        if stages:
            updates["emotional_stages"] = stages

    if updates:
        profile = profile.model_copy(update=updates)
    return profile


def _parse_soul_json(raw: str) -> dict | None:
    """Parse JSON from LLM soul output, stripping fences."""
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(
            line for line in lines if not line.startswith("```")
        ).strip()
    # Strip trailing ellipsis added by call_llm
    if text.endswith(" …"):
        text = text[:-2].strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        logger.warning("Failed to parse soul JSON: %.100s", raw)
        return None


def _dedup_list(items: list[str]) -> list[str]:
    """Deduplicate a list preserving order."""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


# ---------------------------------------------------------------------------
# C) Persona prompt builder — pure function
# ---------------------------------------------------------------------------


def build_persona_prompt(
    profile: CharacterProfile,
    book_title: str,
    language: str = "zh",
) -> str:
    """Build a system prompt for character role-play chat.

    The returned string is intended for the ``system`` parameter of
    :func:`call_llm`.
    """
    if language == "zh":
        return _build_persona_zh(profile, book_title)
    if language == "ja":
        return _build_persona_ja(profile, book_title)
    return _build_persona_en(profile, book_title)


def _build_persona_zh(profile: CharacterProfile, book_title: str) -> str:
    lines = [f"你是《{book_title}》中的{profile.name}。"]
    if profile.personality_type:
        lines.append(f"性格类型：{profile.personality_type}")
    if profile.voice_style:
        lines.append(f"说话风格：{profile.voice_style}")
    if profile.values:
        lines.append(f"核心价值观：{'、'.join(profile.values)}")
    if profile.motivations:
        lines.append(f"内心动机：{'、'.join(profile.motivations)}")
    if profile.key_quotes:
        lines.append("你说过的话：")
        for q in profile.key_quotes[:3]:
            lines.append(f"  - \u201c{q}\u201d")
    lines.append("")
    lines.append(
        f"始终以{profile.name}的身份回答，使用TA的说话方式和世界观。"
    )
    lines.append("如果被问到故事之外的事，请以角色身份表示不清楚。")
    lines.append("不要打破角色，不要说你是AI。用中文回答。")
    return "\n".join(lines)


def _build_persona_en(profile: CharacterProfile, book_title: str) -> str:
    lines = [f'You are {profile.name} from "{book_title}".']
    if profile.personality_type:
        lines.append(f"Personality: {profile.personality_type}")
    if profile.voice_style:
        lines.append(f"Speaking style: {profile.voice_style}")
    if profile.values:
        lines.append(f"Core values: {', '.join(profile.values)}")
    if profile.motivations:
        lines.append(f"Inner motivations: {', '.join(profile.motivations)}")
    if profile.key_quotes:
        lines.append("Things you have said:")
        for q in profile.key_quotes[:3]:
            lines.append(f'  - "{q}"')
    lines.append("")
    lines.append(
        f"Always answer as {profile.name}, using their voice and worldview."
    )
    lines.append(
        "If asked about things beyond the story, stay in character "
        "and say you don't know."
    )
    lines.append("Never break character. Never say you are an AI. Reply in English.")
    return "\n".join(lines)


def _build_persona_ja(profile: CharacterProfile, book_title: str) -> str:
    lines = [f"あなたは『{book_title}』の{profile.name}です。"]
    if profile.personality_type:
        lines.append(f"性格タイプ：{profile.personality_type}")
    if profile.voice_style:
        lines.append(f"話し方：{profile.voice_style}")
    if profile.values:
        lines.append(f"核心的価値観：{'、'.join(profile.values)}")
    if profile.motivations:
        lines.append(f"内なる動機：{'、'.join(profile.motivations)}")
    if profile.key_quotes:
        lines.append("あなたが言ったこと：")
        for q in profile.key_quotes[:3]:
            lines.append(f"  - 「{q}」")
    lines.append("")
    lines.append(
        f"常に{profile.name}として答えてください。"
        "キャラクターの話し方と世界観を使ってください。"
    )
    lines.append("物語の外のことを聞かれたら、キャラクターとして分からないと答えてください。")
    lines.append("キャラクターを壊さないでください。AIだと言わないでください。日本語で答えてください。")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# D) Character-specific context builder — pure function
# ---------------------------------------------------------------------------


def build_character_context(
    chunks: list[ChunkResult],
    chunk_indices: list[int],
    query: str,
    max_chars: int = 3000,
) -> str:
    """Build context from a character's chunks, selecting those most relevant
    to *query* via simple keyword overlap (BM25-lite).

    Falls back to uniform sampling if the query is empty or very short.
    """
    valid = [chunks[i] for i in chunk_indices if i < len(chunks)]
    if not valid:
        return ""

    if len(query.strip()) < 2:
        # No meaningful query — take evenly spaced chunks
        return _uniform_sample(valid, max_chars)

    # Simple keyword relevance scoring
    query_tokens = set(query.lower().split())
    scored: list[tuple[float, int, ChunkResult]] = []
    for idx, chunk in enumerate(valid):
        tokens = set(chunk.text.lower().split())
        overlap = len(query_tokens & tokens)
        scored.append((overlap, idx, chunk))

    scored.sort(key=lambda x: (-x[0], x[1]))

    parts: list[str] = []
    total = 0
    for _score, _idx, chunk in scored:
        part = chunk.text[:800]
        if total + len(part) > max_chars:
            break
        parts.append(part)
        total += len(part)

    return "\n---\n".join(parts)


def _uniform_sample(chunks: list[ChunkResult], max_chars: int) -> str:
    """Take evenly spaced chunks up to max_chars."""
    if not chunks:
        return ""
    n = len(chunks)
    # Aim for ~4 chunks
    step = max(1, n // 4)
    parts: list[str] = []
    total = 0
    for i in range(0, n, step):
        part = chunks[i].text[:800]
        if total + len(part) > max_chars:
            break
        parts.append(part)
        total += len(part)
    return "\n---\n".join(parts)
