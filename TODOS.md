# TODOS

## Deferred from QA (2026-03-26)

- [ ] **ISSUE-001 — Document pip install step more prominently**
  Add `pip install -e .` to the "Quick Start" section at the top of README.md
  so first-time users don't hit `ModuleNotFoundError: No module named 'bookscope'`.
  _Source: QA report 2026-03-26_

- [x] **Gitignore `.hypothesis/`** _(done 2026-03-27, commit 416d1ad)_
  The initial commit included `.hypothesis/` (Hypothesis property-test constants).
  Add `/.hypothesis/` to `.gitignore` to avoid committing auto-generated test data.
  _Source: QA session 2026-03-26_
