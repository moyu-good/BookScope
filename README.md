# BookScope 📖

**🌐 Language / 语言 / 言語:** [English](README.md) · [中文](README.zh.md) · [日本語](README.ja.md)

---

**Book intelligence for readers, writers, and book clubs — in English, 中文, and 日本語.**

[![CI](https://github.com/moyu-good/BookScope/actions/workflows/ci.yml/badge.svg)](https://github.com/moyu-good/BookScope/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## What is BookScope?

BookScope turns any long-form text into an interactive emotional and stylistic dashboard.
Upload a `.txt`, `.epub`, or `.pdf` file — or paste a URL — and immediately get:

- **Quick Insight mode** — book-type cards (fiction / academic / essay) with genre label, story shape, writing style, and an AI-generated narrative paragraph (Claude API)
- **Hero insight card** — dominant emotion, arc pattern, word count at a glance
- **Language toggle** — switch the entire UI between English / 中文 / 日本語 instantly
- **Book comparison** — upload two books and compare emotion timelines, style fingerprints, arc patterns, and vocabulary overlap side-by-side
- **Plain-language explanations** for every chart, designed for general (non-technical) users

| View | What you get |
|------|-------------|
| **Quick Insight** | Genre label, story shape, AI narrative paragraph, "who it's for" recommendation |
| **Overview** | Dominant emotion, average scores, word count, detected language |
| **Heatmap** | 8-emotion × chunk intensity grid |
| **Emotion Timeline** | Scrollable arc chart across all chunks |
| **Style** | Radar fingerprint + per-metric trend lines |
| **Arc Pattern** | Automatic Vonnegut arc classification |
| **Export** | CSV · JSON · Markdown report · PNG share card |
| **Chunks** | Browse individual chunks with scores |
| **Compare** | Side-by-side emotion, style, arc, and vocabulary comparison |

---

## Quick Start

```bash
# 1. Clone and install (editable — required so Python finds the bookscope package)
git clone https://github.com/moyu-good/BookScope.git
cd BookScope
pip install -e ".[dev]"

# 2. Download NLTK corpora (one-time)
python -m textblob.download_corpora

# 3. Launch
streamlit run app/main.py
```

Then open `http://localhost:8501`, upload a `.txt`, `.epub`, or `.pdf` file, or enter a URL.

> **Tip:** If you see `ModuleNotFoundError: No module named 'bookscope'`, run `pip install -e .` from the project root.

---

## Supported Input Formats

| Format | How |
|--------|-----|
| `.txt` | UTF-8 / latin-1 / cp1252, auto-detected |
| `.epub` | Extracts HTML document items via ebooklib |
| `.pdf` | Per-page text extraction via PyMuPDF |
| URL | Fetches HTML or plain text; article body extracted via trafilatura |

---

## Multilingual Support

BookScope automatically detects the book language and switches analysis backends.
The **entire UI** — all labels, descriptions, arc names, and chart titles — is available
in English, Chinese, and Japanese via the sidebar language toggle.

**Analysis backends:**

| Language | Detection | Tokenization | Emotion Lexicon |
|----------|-----------|-------------|-----------------|
| 🇬🇧 English | langdetect | NLTK | NRC English |
| 🇨🇳 Chinese | langdetect | jieba | NRC Chinese (bundled) |
| 🇯🇵 Japanese | langdetect | janome | NRC Japanese (bundled) |

Word count for CJK text uses non-whitespace character count as a proxy (since there are no spaces between words).

---

## How It Works

```
.txt / .epub / .pdf / URL
    │
    ├─ ingest/loader.py     format dispatch → plain text
    ├─ ingest/cleaner.py    Unicode NFC normalization + whitespace
    ├─ ingest/chunker.py    paragraph split or fixed-window (50% overlap)
    │
    ├─ nlp/multilingual.py  language detection, CJK tokenization
    ├─ nlp/lexicon_analyzer.py   NRC Emotion Lexicon → 8 Plutchik scores [0,1]
    ├─ nlp/style_analyzer.py     NLTK POS tagging → TTR, sentence length, POS ratios
    ├─ nlp/arc_classifier.py     Polynomial valence fit → Vonnegut arc pattern
    │
    └─ viz/
        ├─ emotion_timeline.py   Filled area chart
        ├─ heatmap.py            Plotly Heatmap
        └─ style_radar.py        Radar (spider) chart
```

### Emotion Model — Plutchik's Wheel of Emotions

BookScope scores each text chunk across 8 primary emotions from [Robert Plutchik's model](https://en.wikipedia.org/wiki/Robert_Plutchik):

`anger` · `anticipation` · `disgust` · `fear` · `joy` · `sadness` · `surprise` · `trust`

Scores are normalized to `[0, 1]` by dividing each emotion count by the total affected word count (NRC Emotion Lexicon, Mohammad & Turney 2013).

### Arc Patterns — Vonnegut's Shape of Stories

BookScope detects one of six emotional arc patterns identified by [Reagan et al. (2016)](https://epjdatascience.springeropen.com/articles/10.1140/epjds/s13688-016-0093-1):

| Pattern | Shape | Example |
|---------|-------|---------|
| Rags to Riches | ↗ sustained rise | *Great Expectations* |
| Riches to Rags | ↘ sustained fall | *Hamlet* |
| Man in a Hole | ↘↗ fall then rise | *The Hobbit* |
| Icarus | ↗↘ rise then fall | *Macbeth* |
| Cinderella | ↗↘↗ rise-fall-rise | *Cinderella* |
| Oedipus | ↘↗↘ fall-rise-fall | *Oedipus Rex* |

---

## Project Structure

```
bookscope/
├── ingest/          Text loading (.txt/.epub/.pdf/URL), cleaning, chunking
├── models/          Pydantic schemas (BookText, EmotionScore, StyleScore, …)
├── nlp/             Emotion analysis, style metrics, arc classification, multilingual
├── store/           JSON persistence (AnalysisResult, Repository)
├── utils/           NLTK bootstrap utility
└── viz/             Plotly renderers + ChartDataAdapter

app/
├── main.py          Streamlit entry point (Quick Insight + Full Analysis modes)
├── analysis_flow.py Analysis state resolver
├── sidebar.py       Sidebar inputs + language selector + AI options
├── strings.py       All UI strings (EN / ZH / JA)
├── css.py           Injected CSS
├── ui_constants.py  Emotion colors, icons, field lists
└── tabs/            overview · heatmap · timeline · style · arc · export · quick_insight · chunks

tests/               pytest unit + hypothesis property tests (250 tests)
.streamlit/          Streamlit theme config (dark theme, purple accent)
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.11+ |
| UI | Streamlit |
| Charts | Plotly |
| Data models | Pydantic v2 |
| Emotion analysis | nrclex (NRC Emotion Lexicon) |
| Style analysis | NLTK averaged_perceptron_tagger |
| Arc detection | numpy polynomial fitting |
| Language detection | langdetect |
| Chinese tokenization | jieba |
| Japanese tokenization | janome |
| PDF extraction | PyMuPDF |
| URL fetching | requests + trafilatura |
| AI narrative | anthropic (Claude API) |
| Share card | matplotlib (Agg backend) |
| Tests | pytest + hypothesis |
| Lint | ruff |
| CI | GitHub Actions |

---

## Deploying to Streamlit Cloud

1. Push to GitHub
2. Go to [share.streamlit.io](https://share.streamlit.io) → New app
3. Set **Main file path** to `app/main.py`
4. Done — NLTK corpora are downloaded automatically on first run

---

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run linter
ruff check bookscope app tests

# Auto-fix lint
ruff check bookscope app tests --fix
```

---

## Contributing

1. Fork the repo
2. Create a branch: `git checkout -b feature/your-feature`
3. Install dev deps: `pip install -e ".[dev]"`
4. Write tests for your changes
5. Run `pytest && ruff check bookscope app tests`
6. Open a pull request

---

## License

MIT — see [LICENSE](LICENSE).

---

## References

- Mohammad, S. M., & Turney, P. D. (2013). *Crowdsourcing a word-emotion association lexicon*. Computational Intelligence.
- Plutchik, R. (1980). *Emotion: A psychoevolutionary synthesis*. Harper & Row.
- Reagan, A. J., et al. (2016). *The emotional arcs of stories are dominated by six basic shapes*. EPJ Data Science.
- Vonnegut, K. (1981). *Palm Sunday: An Autobiographical Collage*. Delacorte Press.
