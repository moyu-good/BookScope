# BookScope · 书鉴

[![CI](https://github.com/moyu-good/BookScope/actions/workflows/ci.yml/badge.svg)](https://github.com/moyu-good/BookScope/actions)
[![Python 3.14+](https://img.shields.io/badge/python-3.14+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[中文（full docs）](README.md) · English

> Drop a long book into your browser and ask it anything. Every quote is checked character-by-character against the source text, and only verified quotes are shown.

🔗 **Live demo**: [moyu-good.github.io/BookScope](https://moyu-good.github.io/BookScope/) — click and play, preloaded with a real analysis of *Romance of the Three Kingdoms* (no install, no key). To analyze your own book, clone and run locally.

![BookScope overview](docs/images/overview.png)

BookScope is a local tool for deep-reading long texts. Upload an epub / txt / pdf, ask open questions, or use 13 built-in lenses — character graphs, timelines, pacing curves, consistency scans, foreshadow tracking, argument structure, and more.

The difference from "chat with your PDF": every quote the model produces is checked against the original by a program. Matches are shown and stamped with a 「鉴」 (verification) seal; mismatches are dropped. The 鉴 in the name is that seal.

Bring your own key, runs locally. The book text goes straight to the LLM provider you choose — no middleman server.

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

Open `http://localhost:5173`, add your LLM key in settings, upload a book, ask. Default model: DeepSeek `deepseek-v4-flash`.

## Bring your own key

No vendor key is bundled. Eight providers preset — DeepSeek (default), GLM, Qwen, Kimi, OpenAI, Gemini, Grok via OpenAI-compatible endpoints; Anthropic native — pick one and the base URL auto-fills. Your key stays in the browser and goes straight to the provider. No telemetry.

## How it works

A light index is built on upload. At query time the agent reads the source live and verifies every citation:

- fits the context window → the whole book goes into the prompt, behind a stable prefix cache that saves tokens on repeat questions
- too large → BM25 + vector hybrid retrieval

## Docs

Full docs are in Chinese: [README](README.md) · [User Guide](docs/USER_GUIDE.md) · [Architecture](docs/ARCHITECTURE.md) · [Contributing](CONTRIBUTING.md).

## License

[MIT](LICENSE)
