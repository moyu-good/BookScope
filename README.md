# BookScope 📖

**Multi-dimensional book text analysis and visualization.**
**多次元書籍テキスト分析・可視化プラットフォーム**

[![CI](https://github.com/YOUR_USERNAME/BookScope/actions/workflows/ci.yml/badge.svg)](https://github.com/YOUR_USERNAME/BookScope/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## What is BookScope?

BookScope turns any long-form text into an interactive emotional and stylistic dashboard.
Upload a `.txt`, `.epub`, or `.pdf` file — or paste a URL — and immediately see:

| Tab | What you get |
|-----|-------------|
| **Overview** | Dominant emotion, average scores, word count, detected language |
| **Heatmap** | 8-emotion × chunk intensity grid |
| **Emotion Timeline** | Scrollable arc chart across all chunks |
| **Style** | Radar fingerprint + per-metric trend lines |
| **Arc Pattern** | Automatic Vonnegut arc classification |
| **Export** | Download scores as CSV or full analysis as JSON |
| **Chunks** | Browse individual chunks with scores |

---

## Quick Start

```bash
# 1. Clone and install (editable — required so Python finds the bookscope package)
git clone https://github.com/YOUR_USERNAME/BookScope.git
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

BookScope automatically detects the book language and switches analysis backends:

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
└── main.py          Streamlit entry point (7 tabs)

tests/               pytest unit + hypothesis property tests (192 tests)
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
ruff check bookscope tests

# Auto-fix lint
ruff check bookscope tests --fix
```

---

## Contributing

1. Fork the repo
2. Create a branch: `git checkout -b feature/your-feature`
3. Install dev deps: `pip install -e ".[dev]"`
4. Write tests for your changes
5. Run `pytest && ruff check bookscope tests`
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
