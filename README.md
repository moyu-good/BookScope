# BookScope 📖

**Multi-dimensional book text analysis and visualization.**
**多次元書籍テキスト分析・可視化プラットフォーム**

[![CI](https://github.com/YOUR_USERNAME/BookScope/actions/workflows/ci.yml/badge.svg)](https://github.com/YOUR_USERNAME/BookScope/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## What is BookScope?

BookScope turns any plain-text book into an interactive emotional and stylistic dashboard.
Upload a `.txt` file and immediately see:

| Tab | What you get |
|-----|-------------|
| **Overview** | Dominant emotion, average scores, word count |
| **Heatmap** | 8-emotion × chunk intensity grid |
| **Emotion Timeline** | Scrollable arc chart across all chunks |
| **Style** | Radar fingerprint + per-metric trend lines |
| **Arc Pattern** | Automatic Vonnegut arc classification |
| **Export** | Download scores as CSV or full analysis as JSON |
| **Chunks** | Browse individual chunks with scores |

---

## Quick Start

```bash
# 1. Install
pip install -r requirements.txt

# 2. Download NLTK corpora (one-time)
python -m textblob.download_corpora

# 3. Download demo books (optional)
python scripts/download_demo.py

# 4. Launch
streamlit run app/main.py
```

Then open `http://localhost:8501` and upload any `.txt` file.

---

## Installation (development)

```bash
# Requires Python 3.11+
pip install uv
uv pip install -e ".[dev]"
python -m textblob.download_corpora

# Run tests
pytest

# Run linter
ruff check bookscope tests
```

---

## How It Works

```
.txt file
    │
    ├─ ingest/loader.py     UTF-8 / latin-1 / cp1252 fallback
    ├─ ingest/cleaner.py    Unicode NFC normalization + whitespace
    ├─ ingest/chunker.py    paragraph split or fixed-window (50% overlap)
    │
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

## Demo Books

Download public-domain classics from Project Gutenberg:

```bash
python scripts/download_demo.py
# Saves to data/demo/
```

Included books:
- *Pride and Prejudice* — Jane Austen (1813)
- *The Adventures of Sherlock Holmes* — Arthur Conan Doyle (1892)
- *Alice's Adventures in Wonderland* — Lewis Carroll (1865)

---

## Deploying to Streamlit Cloud

1. Push to GitHub
2. Go to [share.streamlit.io](https://share.streamlit.io) → New app
3. Set **Main file path** to `app/main.py`
4. Done — NLTK corpora are downloaded automatically on first run

---

## Project Structure

```
bookscope/
├── ingest/          Text loading, cleaning, chunking
├── models/          Pydantic schemas (BookText, EmotionScore, StyleScore, …)
├── nlp/             Emotion analysis, style metrics, arc classification
├── store/           JSON persistence (AnalysisResult, Repository)
├── utils/           NLTK bootstrap utility
└── viz/             Plotly renderers + ChartDataAdapter

app/
└── main.py          Streamlit entry point (7 tabs)

tests/               pytest unit + hypothesis property tests (118 tests)
scripts/             Utilities (download_demo.py)
data/demo/           Sample books (git-ignored)
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
| Tests | pytest + hypothesis |
| Lint | ruff |
| CI | GitHub Actions |

---

## Contributing

1. Fork the repo
2. Create a branch: `git checkout -b feature/your-feature`
3. Install dev deps: `uv pip install -e ".[dev]"`
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
