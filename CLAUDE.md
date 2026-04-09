# BookScope — CLAUDE.md

## Project overview

Multi-dimensional book text analysis and visualization tool.
Stack: Python 3.11+, FastAPI, React (Vite+TS+Tailwind v4), Pydantic v2, nrclex, NLTK, numpy.

## Architecture (v5 — Progressive Disclosure)

```
bookscope/
  api/
    app.py             FastAPI entry point (v5)
    session_store.py   Typed SessionData + in-memory registry
    sse_utils.py       SSE formatting helper
    dependencies.py    Shared FastAPI deps (require_session, require_api_key)
    routers/           11 router modules (upload, extraction, book, character,
                       chat, search, charts, library, export, share, session)
  services/
    extraction_pipeline.py   Parallel KG + emotion/style extraction
    derived_fields.py        Compute readability, verdict, valence from scores
  ingest/          loader → cleaner → chunker → book_chunker
  models/          BookText, ChunkResult, EmotionScore, StyleScore, BookKnowledgeGraph,
                   CharacterProfile, ReaderVerdict, BookClubPack, AnalysisResult
  nlp/             LexiconAnalyzer, StyleAnalyzer, ArcClassifier, knowledge_extractor,
                   soul_engine, ner_extractor, relation_extractor, llm_analyzer,
                   chat_context, prompt_builders, llm_utils, AnalyzerProtocol
  store/           Repository (JSON persistence), SessionVectorStore (FAISS+BM25)
  utils/           ensure_nltk_data()
bookscope-frontend/   React (Vite + TypeScript + Tailwind v4)
tests/                pytest tests
```

## User flow

```
Upload → Extract (KG + analysis parallel) → Book Overview → Character Deep Dive → Chat
```

## Key invariants

- **Progressive disclosure**: KG extraction (structure) comes first, not emotion analysis
- **Parallel extraction**: KG (LLM, I/O-bound) runs alongside emotion/style (CPU-bound)
- **On-demand soul enrichment**: Characters are enriched only when user clicks into them
- **AnalyzerProtocol** — new NLP backends must implement `analyze_chunk` + `analyze_book`
- **NLTK corpora** — call `ensure_nltk_data()` before nrclex/NLTK usage
- All scores normalized to `[0.0, 1.0]`

## Setup

```bash
pip install -e ".[dev]"
python -m textblob.download_corpora   # one-time NLTK download
uvicorn bookscope.api.app:app --reload --port 8000
```

## Tests

```bash
pytest                        # all tests
pytest tests/test_models.py   # single module
```

## Lint

```bash
ruff check bookscope tests
ruff check bookscope tests --fix   # auto-fix
```

## GitHub Push

Local git config is NOT modified (no stored credentials in git).
Push using the token inline — token is stored in Claude memory (never in this file):

```bash
git push https://<TOKEN>@github.com/moyu-good/BookScope.git main
```

The token is in Claude memory under `reference_github_token.md`.

## Skill routing

When the user's request matches an available skill, ALWAYS invoke it using the Skill
tool as your FIRST action. Do NOT answer directly, do NOT use other tools first.
The skill has specialized workflows that produce better results than ad-hoc answers.

Key routing rules:
- Product ideas, "is this worth building", brainstorming → invoke office-hours
- Bugs, errors, "why is this broken", 500 errors → invoke investigate
- Ship, deploy, push, create PR → invoke ship
- QA, test the site, find bugs → invoke qa
- Code review, check my diff → invoke review
- Update docs after shipping → invoke document-release
- Weekly retro → invoke retro
- Design system, brand → invoke design-consultation
- Visual audit, design polish → invoke design-review
- Architecture review → invoke plan-eng-review
- Save progress, checkpoint, resume → invoke checkpoint
- Code quality, health check → invoke health
