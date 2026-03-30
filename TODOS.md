# TODOS

## Deferred from QA (2026-03-26)

- [x] **ISSUE-001 — Document pip install step more prominently** _(done 2026-03-27)_
  Added `pip install -e ".[dev]"` as the primary install command in Quick Start,
  plus an explicit tip box for the ModuleNotFoundError case.
  README also updated for v0.2.0.0: multilingual, PDF/URL, 192 tests.
  _Source: QA report 2026-03-26_

- [x] **Gitignore `.hypothesis/`** _(done 2026-03-27, commit 416d1ad)_
  The initial commit included `.hypothesis/` (Hypothesis property-test constants).
  Add `/.hypothesis/` to `.gitignore` to avoid committing auto-generated test data.
  _Source: QA session 2026-03-26_

## Redesign (2026-03-27)

- [x] **UI redesign — modern dark theme + full EN/ZH/JA i18n** _(done 2026-03-27, branch feature/ui-ux-i18n-redesign)_
  - Modern dark UI: purple accent, gradient hero card, card-style metric panels
  - Hero insight card: book title, one-sentence summary, dominant emotion, arc name
  - Sidebar language toggle (EN / 中文 / 日本語) — all UI text switches instantly
  - Localized arc names (ZH idioms: 乐极生悲/好事多磨/回光返照; JA equivalents)
  - Plain-language descriptions for every chart so general users understand

## Deferred from v0.4.0.0 autoplan (2026-03-27)

- [x] **Load saved analysis from sidebar** — `▶ Load` button on each saved entry; resumes prior
  analysis without re-uploading. Loaded badge + "× New analysis" clear button. _(done 2026-03-27)_

- [x] **Streamlit Cloud deployment prep** — Demo mode added (welcome screen "Try demo" button
  loads embedded 20-paragraph story); `requirements.txt` generated; `pyproject.toml` enables
  auto-install on Cloud. _(done 2026-03-27)_ To deploy: push to GitHub, connect repo at
  share.streamlit.io, set Main file path to `app/main.py`.

- [x] **spaCy NER for character extraction** — `extract_character_names` tries spaCy NER first,
  falls back to regex. Optional dep `pip install -e ".[spacy]"`. _(done 2026-03-27)_

- [x] **Full CJK Quick Insight genre labels** — ZH/JA genre labels from `_EMOTIONAL_GENRE`
  now displayed in fiction headline card for Chinese and Japanese UI languages. _(done 2026-03-27)_

## Fixed during QA (2026-03-27)

- [x] **ISSUE-004 — CJK word_count displayed as 0–1 for Chinese/Japanese** _(fixed 2026-03-27, commit be62d60)_
  `ChunkResult.word_count` used `len(text.split())` which returns near-zero for CJK
  text (no spaces). Fixed: chunker now passes `word_count=_word_count(text, lang)`.
  _Source: QA session 2026-03-27_

## v0.6.0 — completed 2026-03-30

- [x] **app/main.py refactor** — 1869 → 296 lines, split into 8 modules under `app/tabs/`,
  `app/sidebar.py`, `app/analysis_flow.py`, `app/css.py`, `app/strings.py`. _(commit 3f262f4)_
- [x] **LLM narrative insight** — `bookscope/nlp/llm_analyzer.py`, Claude Haiku AI Narrative
  card in Quick Insight tab, MD5 cache key, truncation guard, 12 new tests. _(commit 0474fbd)_
- [x] **Compare tab QA + polish** — same-book guard (`_content_fingerprint`), single-book note,
  fixed hardcoded `"No style data."`, 10 new tests. _(commit c049f3d)_
- Tests: 221 → 243 (+22)

## v0.7.0 — completed 2026-03-30

- [x] **Analysis card sharing** — `bookscope/viz/card_renderer.py`: 800×480 dark PNG card with
  title, top emotion badge, arc pattern, stats, and emotion bar chart. Download button in
  Export tab. No new runtime deps (matplotlib already present). 7 new tests. _(commit 31de16c)_
- [x] **LLM model selector in sidebar** — Haiku (fast) / Sonnet (quality) radio in "AI options"
  expander. Choice stored in `st.session_state["llm_model"]` and read by `generate_narrative_insight`.
  _(same commit)_
- Tests: 243 → 250 (+7)

## Deferred to v0.8+

- [ ] **AnalyzerProtocol integration for LLM**: If LLM output becomes structured EmotionScore,
  wrap `llm_analyzer.py` in AnalyzerProtocol.
