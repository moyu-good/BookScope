# Changelog

All notable changes to BookScope will be documented in this file.

## [0.5.2.0] - 2026-03-27

### Added
- **spaCy NER for character extraction** — `extract_character_names` now tries
  `spacy.load("en_core_web_sm")` first (proper PERSON entity recognition, handles
  multi-word names, eliminates common false positives). Falls back to regex NER
  automatically if spaCy / the model is not installed — zero behavior change for
  existing users. Enable with: `pip install -e ".[spacy]"`.
- **`[spacy]` optional extra** in `pyproject.toml` (`spacy>=3.7.0,<4.0.0`).
  `requirements.txt` includes the spaCy model wheel for Streamlit Cloud.
- **CJK genre labels in fiction Quick Insight** — `_EMOTIONAL_GENRE` ZH/JA labels
  (already defined in the mapping) are now displayed for Chinese and Japanese users.
  Previously the fiction headline card showed only arc + emotion name for non-EN users;
  now it shows the localized genre label (e.g. "心理悬疑 — 乐极生悲 ↗↘").

## [0.5.1.0] - 2026-03-27

### Added
- **Demo mode** — "📖 Try with a demo book" button on the welcome screen; loads a
  20-paragraph embedded story ("The Lighthouse Keeper's Last Storm") so visitors can
  explore all features without uploading a file. Demo badge + "× New analysis" clear
  button shown in the main area. Demo state cleared automatically when a real file/URL
  is provided.
- **`app/demo_book.txt`** — embedded demo story; Man-in-a-Hole arc, strong emotion mix,
  designed to exercise all 7 Full Analysis tabs and Quick Insight cards.
- **`requirements.txt`** — Streamlit Cloud compatible dependency list, kept in sync with
  `pyproject.toml`. Streamlit Cloud also auto-installs the `bookscope` package via
  `pyproject.toml` at build time.

## [0.5.0.0] - 2026-03-27

### Added
- **Load saved analysis from sidebar** — `▶ Load` button on each saved entry resumes a
  prior analysis instantly without re-uploading. Loaded badge + "× New analysis" clear button
  shown in main area. Save button hidden when viewing a saved result.
- **`detected_lang` field in `AnalysisResult`** — persisted to JSON (backward-compatible,
  defaults to `"en"` for old saves) so loaded analyses display the correct language label
  and drive CJK-aware features.

### Fixed
- **Chunks tab guarded for saved results** — shows info message instead of crashing when raw
  chunk text is not available (saved analyses store only scores, not source text)
- **Quick Insight `chunks=None` guards** — character extraction, key-theme extraction, and
  first-person density now handle `chunks=None` gracefully (return `[]` / `0.0`)
- **Export tab `detected_lang`** — analysis results exported/saved now include detected
  language field

## [0.4.0.0] - 2026-03-27

### Added
- **Quick Insight mode** — book-type-aware insight cards (headline + 3-col grid + "Who it's for")
  replacing the 7-tab view for general users; Full Analysis mode preserves all existing tabs
- **Book type selector** in sidebar (Fiction / Academic / Essay) — user-selected before upload,
  drives Quick Insight card content (no unreliable auto-detection)
- **`bookscope/insights.py`** — zero-new-dependency helpers: character extraction, key themes,
  readability grade, SVG sparkline, first-person density
- **`bookscope/app_utils.py`** — shared language/mode persistence via `st.query_params`
  (survives page navigation) + Google Fonts CDN injection
- **Language persistence across pages** — `?lang=` query param written on change; compare page
  reads it on load, language no longer resets when navigating main ↔ compare
- **Font override by language** — Instrument Serif + Inter (EN), Noto Serif/Sans SC (ZH),
  Noto Serif/Sans JP (JA); injected with `!important` to override OS system fonts
- **Compare page full i18n** — all labels, headers, captions in EN/ZH/JA
- **PDF support in compare page** — file uploader now accepts `.pdf` alongside `.txt` and `.epub`
- **Emotional genre classification** (EN fiction) — 11 arc×emotion combos mapped to reading-group
  recommendations; CJK books show emotion profile without uncertain genre labels
- New pytest tests for `bookscope/insights.py` (35 tests)

### Fixed
- **XSS via `unsafe_allow_html=True`** — all user-derived strings (book title, arc name,
  emotion name) now HTML-escaped before injection
- **`langdetect` non-determinism** — `DetectorFactory.seed = 0` in both pages for reproducible
  language detection inside `@st.cache_data`
- **PDF title stripping in compare page** — `.pdf` suffix now removed from book title display
- **`bookscope/app_utils.py` location** — moved from `app/ui_utils.py` into installed package
  to eliminate fragile `sys.path.insert` pattern
- **Sparkline zero-division** — flat valence series (common for CJK books) returns midpoint
  line instead of crashing
- **Character extraction CJK guard** — returns `[]` for ZH/JA/KO text immediately (no false
  positives from regex NER)
- **CSS animation replay** — session-keyed class prevents stagger animations replaying on
  every Streamlit widget interaction
- **disgust color** changed from `#a855f7` (clashed with purple accent) to `#84cc16`

### Changed
- `app/main.py`: mode toggle (Quick Insight / Full Analysis) appears below hero card;
  book type selector moved to sidebar (before upload); query_params language persistence
- `app/pages/02_compare.py`: full trilingual i18n, PDF support, language sync, langdetect seed
- `.streamlit/config.toml`: background `#0d1117`, card `#161b22`, text `#e6edf3`

## [0.3.0.0] - 2026-03-27

### Added
- Full trilingual UI (English / 中文 / 日本語): sidebar language toggle switches all labels,
  descriptions, tab names, arc names, and metric help text instantly without re-running analysis
- Hero insight card at top of analysis page: book title, one-sentence story summary,
  dominant emotion badge (color-coded), localized arc name with shape arrow, word count, chunk count
- Modern dark theme: deep navy background, purple accent (`#7c3aed`), gradient hero card,
  frosted-glass metric tiles, plain-language chart descriptions for general users
- Localized arc names — ZH idioms: 乐极生悲 / 好事多磨 / 回光返照 / 白手起家 / 盛极而衰 / 跌入谷底
- Localized arc names — JA: イカロス / シンデレラ / オイディプス / どん底からの成功 / etc.
- Emotion labels translated in bar charts, timeline selector, and chunk explorer (all 3 languages)
- Style metric labels and help text translated in Style tab
- Centered welcome screen with hero layout replaces plain info message

### Changed
- `app/main.py`: complete UI rewrite with i18n string dict, hero card HTML/CSS, language state
- `.streamlit/config.toml`: `primaryColor` updated to `#7c3aed` (purple)

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
