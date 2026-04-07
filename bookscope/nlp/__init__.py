from bookscope.nlp.analyzer_protocol import AnalyzerProtocol
from bookscope.nlp.arc_classifier import ArcClassifier, ArcPattern
from bookscope.nlp.genre_analyzer import extract_essay_voice, extract_nonfiction_concepts
from bookscope.nlp.knowledge_extractor import extract_knowledge_graph
from bookscope.nlp.lang_detect import detect_language
from bookscope.nlp.lexicon_analyzer import LexiconAnalyzer
from bookscope.nlp.llm_analyzer import generate_narrative_insight
from bookscope.nlp.narrative_protocol import (
    ClaudeBackend,
    NarrativeProtocol,
    OllamaBackend,
    OpenAIBackend,
)
from bookscope.nlp.ner_extractor import extract_character_candidates
from bookscope.nlp.soul_engine import (
    build_character_context,
    build_persona_prompt,
    enrich_soul_profile,
    extract_character_dialogues,
)
from bookscope.nlp.style_analyzer import StyleAnalyzer
from bookscope.nlp.transformer_analyzer import TransformerAnalyzer

__all__ = [
    "AnalyzerProtocol",
    "ArcClassifier",
    "ArcPattern",
    "build_character_context",
    "build_persona_prompt",
    "ClaudeBackend",
    "detect_language",
    "enrich_soul_profile",
    "extract_character_candidates",
    "extract_character_dialogues",
    "extract_essay_voice",
    "extract_knowledge_graph",
    "extract_nonfiction_concepts",
    "generate_narrative_insight",
    "LexiconAnalyzer",
    "NarrativeProtocol",
    "OllamaBackend",
    "OpenAIBackend",
    "StyleAnalyzer",
    "TransformerAnalyzer",
]
