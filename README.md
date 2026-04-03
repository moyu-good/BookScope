# BookScope

[![CI](https://github.com/moyu-good/BookScope/actions/workflows/ci.yml/badge.svg)](https://github.com/moyu-good/BookScope/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**🌐** [English](README.md) · [中文](README.zh.md) · [日本語](README.ja.md)

---

> *"There is no reason why the simple shapes of stories can't be fed into computers — they are beautiful shapes."*
> — Kurt Vonnegut, 1981

In 2016, Reagan et al. fed 1,327 Project Gutenberg novels into a sentiment pipeline and confirmed what Vonnegut suspected: nearly every story follows one of six emotional arc shapes. BookScope lets you run that same analysis on **any** book — in under a minute, from a raw text file.

---

## What it does (technically)

BookScope is a Streamlit app that takes raw text (`.txt`, `.epub`, `.pdf`, or URL), splits it into ~50 chunks with 50% overlap, runs NRC Emotion Lexicon scoring on each chunk, fits a polynomial to the valence arc, and classifies it against Vonnegut's six shapes. Layered on top: style fingerprinting via NLTK POS tags, an 8-emotion × chunk heatmap, and an optional Claude API narrative paragraph.

The entire pipeline works **without an API key**. LLM is additive, not required.

---

## The arc detection algorithm

```
raw text
  └─ ingest: clean → paragraph chunks (≈ 50, 50% overlap)
        └─ NRC lexicon scoring: 8 Plutchik emotions per chunk → [0,1]
              └─ valence = (joy + trust + anticipation) − (anger + fear + disgust + sadness)
                    └─ numpy polyfit(degree=3) over [chunk_index, valence]
                          └─ inflection point count → arc label
```

Six arcs emerge from the inflection structure:

| Arc | Shape | Inflections | Classic example |
|-----|-------|-------------|-----------------|
| Rags to Riches | ↗ | 0, monotone rise | *Great Expectations* |
| Riches to Rags | ↘ | 0, monotone fall | *Hamlet* |
| Man in a Hole | ↘↗ | 1, fall-then-rise | *The Hobbit* |
| Icarus | ↗↘ | 1, rise-then-fall | *Macbeth* |
| Cinderella | ↗↘↗ | 2 | *Cinderella* |
| Oedipus | ↘↗↘ | 2 | *Oedipus Rex* |

The polynomial fit means the classifier is noise-tolerant — a single dark chapter doesn't flip a Rags to Riches arc. Degree 3 was chosen empirically: lower degrees miss Cinderella/Oedipus, higher degrees overfit local spikes.

---

## Emotion model — Plutchik's Wheel

Eight primary emotions, scored per chunk via the NRC Word-Emotion Association Lexicon (Mohammad & Turney 2013):

```
anger · anticipation · disgust · fear · joy · sadness · surprise · trust
```

Each score is normalized by total NRC-tagged word count in the chunk — so a 200-word chunk and a 600-word chunk are directly comparable. The normalization prevents long chapters from dominating the arc shape.

---

## Architecture decisions

**ChartDataAdapter as the only cross-boundary import**  
Domain models (`EmotionScore`, `StyleScore`) and Plotly charts live in separate layers. `ChartDataAdapter` is the single file that imports both. Every renderer receives plain `*Data` dataclasses — they never touch the domain layer. This makes the viz layer independently testable and keeps Plotly out of the NLP tests.

**Session-state cache keyed by MD5 of chunk content**  
LLM calls are expensive. The cache key is `md5(first 40 chars of each chunk text)[:8]` — stable across reruns, unique per book, cheap to compute. Genre type is included in the key so the same book analyzed as "fiction" vs. "essay" gets different cached insight text.

**Three NLP pipelines behind eight book types**  
The UI exposes 8 book type tiles (Fiction, Biography & Memoir, Short Stories, Poetry, Academic, Essay, Technical, Self-Help). Behind the scenes, three prompt builders cover all eight:

```
fiction NLP ← Fiction, Short Stories
nonfiction NLP ← Academic, Technical, Self-Help
essay NLP ← Essay, Biography & Memoir, Poetry
```

Adding a new type is a one-line mapping change, not a new prompt.

**No stored credentials anywhere**  
The Claude API key lives only in env vars or Streamlit secrets — never in session state, never serialized. The `call_llm()` function is thread-safe: it builds a per-call client from a key passed as an argument, so it can safely be called from background threads.

---

## Pipeline overview

```
bookscope/
├── ingest/
│   ├── loader.py          format dispatch (.txt / .epub / .pdf / URL)
│   ├── cleaner.py         Unicode NFC normalization, whitespace
│   └── chunker.py         paragraph split or fixed-window (50% overlap)
│
├── nlp/
│   ├── lexicon_analyzer.py    NRC scoring → 8 Plutchik scores [0,1]
│   ├── style_analyzer.py      NLTK POS tagging → TTR, sentence length, POS ratios
│   ├── arc_classifier.py      polyfit + inflection → Vonnegut arc label
│   ├── genre_analyzer.py      fiction / nonfiction / essay classification
│   ├── llm_analyzer.py        Claude API narrative insight (optional)
│   └── multilingual.py        langdetect + jieba (ZH) + janome (JA)
│
├── models/
│   └── schemas.py         Pydantic v2: BookText, ChunkResult, EmotionScore,
│                          StyleScore, AnalysisResult, BookClubPack
│
├── viz/
│   ├── chart_data_adapter.py  the ONLY file that imports both domain + Plotly
│   ├── heatmap.py             8-emotion × chunk Plotly heatmap
│   ├── card_renderer.py       Quick Insight genre cards
│   └── relation_graph_renderer.py  character/concept network graph
│
└── store/
    └── repository.py      JSON persistence (save / load AnalysisResult)

app/
├── main.py                Streamlit entry: Welcome → Upload → Analysis tabs
├── sidebar.py             Book type tiles (2×4 grid), language toggle, AI opts
├── strings.py             All UI strings — EN / ZH / JA (single source of truth)
└── tabs/                  quick_insight · overview · heatmap · timeline ·
                           style · arc · export · chunks · compare · chat
```

---

## Multilingual support

BookScope detects the book language and switches NLP backends automatically:

| Language | Detection | Tokenization | Emotion lexicon |
|----------|-----------|--------------|-----------------|
| English | langdetect | NLTK | NRC English |
| Chinese | langdetect | jieba | NRC Chinese (bundled) |
| Japanese | langdetect | janome | NRC Japanese (bundled) |

The UI itself — all labels, chart titles, arc names, insight text — can be switched independently between EN / 中文 / 日本語 at any time. Book language and UI language are decoupled.

---

## Quick start

```bash
git clone https://github.com/moyu-good/BookScope.git
cd BookScope
pip install -e ".[dev]"
python -m textblob.download_corpora   # one-time NLTK corpus download
streamlit run app/main.py
```

Open `http://localhost:8501`. No API key needed for the core analysis — add `ANTHROPIC_API_KEY` to `.env` or Streamlit secrets to unlock the AI narrative card and Chat tab.

---

## Running tests

```bash
pytest                        # 422 tests
pytest tests/test_arc_classifier.py   # just arc detection
ruff check bookscope app tests        # lint
```

The test suite includes hypothesis property tests for the emotion normalizer and arc classifier — arbitrary chunk counts and score distributions are tested, not just hand-written fixtures.

---

## Deploy to Streamlit Cloud

1. Fork the repo and push to GitHub
2. [share.streamlit.io](https://share.streamlit.io) → New app → set main file to `app/main.py`
3. Add `ANTHROPIC_API_KEY` to Streamlit secrets (optional)

NLTK corpora are downloaded automatically on first run via `ensure_nltk_data()`.

---

## Tech stack

| Concern | Library |
|---------|---------|
| UI | Streamlit |
| Charts | Plotly |
| Data models | Pydantic v2 |
| Emotion scoring | nrclex (NRC Lexicon) |
| Style analysis | NLTK averaged_perceptron_tagger |
| Arc detection | numpy polyfit |
| Language detection | langdetect |
| Chinese tokenization | jieba |
| Japanese tokenization | janome |
| PDF extraction | PyMuPDF |
| URL extraction | requests + trafilatura |
| AI narrative | anthropic (Claude API) |
| Share card | matplotlib (Agg) |
| Tests | pytest + hypothesis |
| Lint / CI | ruff + GitHub Actions |

---

## References

- Mohammad, S. M., & Turney, P. D. (2013). *Crowdsourcing a word-emotion association lexicon.* Computational Intelligence, 29(3), 436–465.
- Plutchik, R. (1980). *Emotion: A psychoevolutionary synthesis.* Harper & Row.
- Reagan, A. J., Mitchell, L., Kiley, D., Danforth, C. M., & Dodds, P. S. (2016). *The emotional arcs of stories are dominated by six basic shapes.* EPJ Data Science, 5(1), 31.
- Vonnegut, K. (1981). *Palm Sunday: An Autobiographical Collage.* Delacorte Press.

---

MIT License
