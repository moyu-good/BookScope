from bookscope.nlp.analyzer_protocol import AnalyzerProtocol
from bookscope.nlp.arc_classifier import ArcClassifier, ArcPattern
from bookscope.nlp.genre_analyzer import extract_essay_voice, extract_nonfiction_concepts
from bookscope.nlp.lang_detect import detect_language
from bookscope.nlp.lexicon_analyzer import LexiconAnalyzer
from bookscope.nlp.llm_analyzer import generate_narrative_insight
from bookscope.nlp.narrative_protocol import (
    ClaudeBackend,
    NarrativeProtocol,
    OllamaBackend,
    OpenAIBackend,
)
from bookscope.nlp.style_analyzer import StyleAnalyzer

__all__ = [
    "AnalyzerProtocol",
    "ArcClassifier",
    "ArcPattern",
    "ClaudeBackend",
    "detect_language",
    "extract_essay_voice",
    "extract_nonfiction_concepts",
    "generate_narrative_insight",
    "LexiconAnalyzer",
    "NarrativeProtocol",
    "OllamaBackend",
    "OpenAIBackend",
    "StyleAnalyzer",
]
