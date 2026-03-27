# Changelog

All notable changes to BookScope will be documented in this file.

## [0.2.0.0] - 2026-03-27

### Added
- Multilingual support: automatic language detection (English / Chinese / Japanese) via langdetect
- Chinese emotion analysis with jieba tokenization and bundled NRC Chinese lexicon (`nrc_zh.json`)
- Japanese emotion analysis with janome tokenization and bundled NRC Japanese lexicon (`nrc_ja.json`)
- CJK-aware word count: non-whitespace character count used as word proxy for Chinese and Japanese text
- Janome Tokenizer instance cached with `@lru_cache` to avoid 25–90 ms reload per chunk
- Language flag displayed in Overview tab (🇬🇧 / 🇨🇳 / 🇯🇵) alongside detected language name
- Test files: `test_book_zh.txt` (4-chapter Chinese), `test_book_ja.txt` (4-chapter Japanese)
- QA report: `.gstack/qa-reports/qa-report-localhost-2026-03-27.md` — health score 97/100

### Fixed
- ISSUE-004: `ChunkResult.word_count` returned 0–1 for CJK text because `model_post_init` used space-based splitting; chunker now passes `word_count=_word_count(text, lang)` explicitly
- Duplicate entries removed from `nrc_ja.json`: おびえる (fear ×2→×1), まさか (surprise ×2→×1)
- Unused `EMOTIONS` constant removed from `bookscope/nlp/multilingual.py`

### Changed
- `tests/test_multilingual.py`: 14 new tests covering CJK word count, language normalization, ISSUE-004 regression

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
- Local editor settings excluded from version control (session-specific)
