# Changelog

All notable changes to BookScope will be documented in this file.

## [0.1.0.0] - 2026-03-27

### Added
- Initial implementation of BookScope — multi-dimensional book text analysis and visualization tool
- Support for `.txt` and `.epub` file ingestion with HTML extraction and EPUB parsing
- Emotion analysis via NRCLex lexicon with per-chunk scoring for 10 emotion dimensions
- Style analysis: TTR, sentence length, noun/verb/adjective/adverb ratios
- Narrative arc classification (Freytag, Hero's Journey, Tragedy, Cinderella, Oedipus, Man in Hole, Linear)
- Streamlit UI with 7 analysis tabs: Overview, Heatmap, Timeline, Style Radar, Arc Pattern, Export, Chunks
- Book comparison page (`/compare`) — overlay emotion timelines and valence arcs for 2 books
- JSON persistence via Repository store
- 145 pytest tests (unit + Hypothesis property tests), 97% coverage

### Fixed
- CORS config conflict: `enableCORS = false` conflicted with `enableXsrfProtection = true` default — changed to `enableCORS = true`
- Info text on Overview tab now correctly mentions both `.txt` and `.epub` upload formats

### Changed
- `.hypothesis/` excluded from version control (auto-generated test data)
- `.claude/settings.local.json` excluded from version control (session-specific)
