# BookScope · 书鉴

[![CI](https://github.com/moyu-good/BookScope/actions/workflows/ci.yml/badge.svg)](https://github.com/moyu-good/BookScope/actions)
[![Python 3.14+](https://img.shields.io/badge/python-3.14+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[中文（full docs）](README.md) · English

> Drop a long book into your browser and interrogate it — every claim points back to the source text, **shown only after the quote is checked character-by-character against the original.** Fabricated citations get caught.

![BookScope overview](docs/images/overview.png)

Upload a book (novel, history, paper, theory) and ask anything — or use 13 built-in lenses: character graphs, timelines, pacing curves, consistency scans, foreshadow tracking, argument structure, and more.

What sets it apart from "chat with your PDF": a quote is never trusted on the model's word — a program checks it against the original, and only verified quotes display. That's why it works where ChatGPT guesses: your unpublished draft, last week's paper, an obscure theory book. Bring your own key, runs locally, no GPU — your manuscript never leaves.

> The UI is Chinese-first (中文优先 is a project invariant). This is a short English entry point; full docs are in Chinese.

## Quick start

Requires Python 3.14+ and Node.js.

```bash
git clone https://github.com/moyu-good/BookScope.git
cd BookScope
pip install -e ".[dev]"
python -m textblob.download_corpora

uvicorn bookscope.api.app:create_app --factory --reload --port 8000
# in another shell
cd web && npm install && npm run dev          # http://localhost:5173
```

Open `http://localhost:5173`, drop in your LLM key, upload a book, ask. Default model: DeepSeek `deepseek-v4-flash`.

## Bring your own key

No vendor key is bundled. Eight providers preset — DeepSeek (default), GLM, Qwen, Kimi, OpenAI, Gemini, Grok via OpenAI-compatible endpoints; Anthropic native — pick one and the base URL auto-fills. Your key stays in the browser and goes straight to the provider. No telemetry.

## How it works

Light index on upload; at query time the agent reads the source live and verifies every citation:

- fits the context window → whole book goes in the prompt (≥90% cache hit on repeats)
- too large → BM25 + vector hybrid retrieval

Runs on CPU. No GPU.

## Where it sits

"Chat with PDF" RAG tools cite retrieved chunks but never re-verify the model's quote. Open-source NotebookLM alternatives are general document Q&A. AI tools for novelists are mostly closed and write-oriented. BookScope is **verified-citation, query-time deep reading of one long book** — open source, BYOK, GPU-free.

## Docs

Full docs are in Chinese: [README](README.md) · [User Guide](docs/USER_GUIDE.md) · [Architecture](docs/ARCHITECTURE.md) · [Contributing](CONTRIBUTING.md).

## License

[MIT](LICENSE)
