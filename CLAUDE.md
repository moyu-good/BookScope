# BookScope — CLAUDE.md

## Project overview

Multi-dimensional book text analysis and visualization tool.
Stack: Python 3.11+, Streamlit, Plotly, Pydantic v2, nrclex, NLTK, numpy.

## Architecture

```
bookscope/
  ingest/          loader → cleaner → chunker
  models/          BookText, ChunkResult, EmotionScore, StyleScore, AnalysisResult
  nlp/             LexiconAnalyzer, StyleAnalyzer, ArcClassifier, AnalyzerProtocol
  store/           Repository (JSON persistence)
  utils/           ensure_nltk_data()
  viz/             ChartDataAdapter, EmotionTimelineRenderer, EmotionHeatmapRenderer,
                   StyleRadarRenderer, BaseRenderer, BookScopeTheme
app/main.py        Streamlit entry (7 tabs)
tests/             118 pytest tests (unit + hypothesis property tests)
```

## Key invariants

- **ChartDataAdapter** is the ONLY place that imports both domain models and Plotly.
  Renderers receive `*Data` dataclasses only — they never import from `bookscope.models`.
- **AnalyzerProtocol** — new NLP backends must implement `analyze_chunk` + `analyze_book`.
- **NLTK corpora** — call `ensure_nltk_data()` before any nrclex/NLTK usage.
  This is called automatically at `app/main.py` startup.
- All scores are normalized to `[0.0, 1.0]`.

## Setup

```bash
pip install -e ".[dev]"
python -m textblob.download_corpora   # one-time NLTK download
streamlit run app/main.py
```

## Tests

```bash
pytest                        # all 221 tests
pytest tests/test_models.py   # single module
```

## Lint

```bash
ruff check bookscope app tests
ruff check bookscope app tests --fix   # auto-fix
```

## GitHub Push

Local git config is NOT modified (no stored credentials in git).
Push using the token inline — token is stored in Claude memory (never in this file):

```bash
git push https://<TOKEN>@github.com/moyu-good/BookScope.git main
```

The token is in Claude memory under `reference_github_token.md`.

## Adding a new emotion backend (Phase 2+)

1. Implement `AnalyzerProtocol` in `bookscope/nlp/your_analyzer.py`
2. Export from `bookscope/nlp/__init__.py`
3. Add tests in `tests/test_your_analyzer.py`
4. Wire into `app/main.py` via a sidebar toggle

## Adding a new chart

1. Add `*Data` dataclass + static method to `bookscope/viz/chart_data_adapter.py`
2. Create `bookscope/viz/your_renderer.py` extending `BaseRenderer`
3. Export from `bookscope/viz/__init__.py`
4. Add tests in `tests/test_your_renderer.py`
