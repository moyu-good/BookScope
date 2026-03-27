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

## Fixed during QA (2026-03-27)

- [x] **ISSUE-004 — CJK word_count displayed as 0–1 for Chinese/Japanese** _(fixed 2026-03-27, commit be62d60)_
  `ChunkResult.word_count` used `len(text.split())` which returns near-zero for CJK
  text (no spaces). Fixed: chunker now passes `word_count=_word_count(text, lang)`.
  _Source: QA session 2026-03-27_
