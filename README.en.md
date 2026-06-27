<p align="center">
  <img src="docs/images/logo.svg" width="116" alt="BookScope">
</p>

<h1 align="center">BookScope · 书鉴</h1>

<p align="center">
  A tool for people who read long books and official documents. Every "the book says…" the AI gives you is checked word-by-word against the source; only matches are shown, each stamped with a 「鉴」(verify) seal. It also draws the whole book — through a reader's eye, not a dashboard.
</p>

<p align="center">
  <a href="https://github.com/moyu-good/BookScope/actions"><img src="https://github.com/moyu-good/BookScope/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.14+-blue.svg" alt="Python 3.14+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"></a>
</p>

<p align="center">
  <a href="README.md">中文（full docs）</a> · English · <a href="https://moyu-good.github.io/BookScope/">Live demo</a>
</p>

<p align="center">
  <img src="docs/images/graph.png" width="760" alt="Star-map of characters: each person a star, each line a relationship, click to see the source">
  <br>
  <sub>All 348 connected characters of <i>Romance of the Three Kingdoms</i> — each a star, brighter with more screen time, red for rivals and green for allies. Click a line to read the source from that chapter. A 120-chapter book should be this dense.</sub>
</p>

---

## What it is

Drop a long book (epub / txt / pdf) into your browser and ask it open questions. It also maps the whole book: who relates to whom, the rise and fall of tension chapter by chapter, the timeline, foreshadowing, where subplots cross, and whether the book contradicts itself.

It also reads Chinese government documents (red-header official documents, 红头文件). Drop one in and it recognizes the genre, switching to a document-reading toolkit: it turns officialese into plain language (spelling out what "in principle agreed" or "we'll study it" really mean), picks out the clauses that concern you, works out each clause's deadlines and thresholds, and can lay several documents side by side to see which cites which and how a policy evolved. Same rule as books: every claim is anchored to the source, verified ones get the 「鉴」seal, inferences are marked as judgement rather than fact.

It runs locally on your own AI account. The book text goes straight to the provider you pick (DeepSeek by default); there's no server in between, so nothing here ever touches your book or your key.

**Live demo**: [moyu-good.github.io/BookScope](https://moyu-good.github.io/BookScope/) — a finished analysis of *Romance of the Three Kingdoms* you can click through, no install and no key.

## Why it's different

**One: the check.** Today's AIs casually invent "the source says XX" — it sounds real, and you can't go back and verify every line. BookScope verifies every quote against the book by code: matches are shown and stamped with a 「鉴」seal, mismatches are dropped. Judgement calls (contradictions, foreshadowing, technique) follow the same rule — if it doesn't hold up in the source, it isn't said. This is the point of the project, not a feature on the side.

**Two: it draws the book through a reader's eye.** The tension curve is painted as an ink-wash mountain range; relationships as a night-sky star map; character arcs as flowering branches. Every stroke is anchored to the source — click a relationship line or a timeline event and it fetches the supporting sentence from that chapter, live.

<p align="center">
  <img src="docs/images/narrative.png" width="48%" alt="Narrative tension as an ink-wash mountain range">
  <img src="docs/images/arc.png" width="48%" alt="Character arcs as flowering branches">
  <br>
  <sub>Left: the narrative curve as an ink-wash scroll — each peak and valley a chapter's tension, red dots the climaxes. Right: character arcs as bird-and-flower painting — one branch per character, its rise and fall their fortunes, blossom density their screen time.</sub>
</p>

<p align="center">
  <img src="docs/images/relationship.png" width="48%" alt="Relationship evolution as small-multiple timelines">
  <img src="docs/images/foreshadow.png" width="48%" alt="Foreshadowing arcs from setup to payoff">
  <br>
  <sub>Left: relationship evolution — the heaviest few dozen pairs, one row each; the line rising means growing closer, falling means drifting apart. This splits work with the star map above: the map shows who connects to whom, this shows how a bond changed over the book. Right: foreshadowing — solid vermilion arcs span from a setup to its payoff (Wei Yan's "bone of rebellion," planted in ch. 53 and fulfilled in ch. 105, arcing across half the book); dashed grey arcs are setups left dangling.</sub>
</p>

<p align="center">
  <img src="docs/images/qa-citation.png" width="60%" alt="Answers carry their source; verified quotes get the 鉴 seal">
  <br>
  <sub>Ask the book: answers carry their source, quotes checked word-for-word get the 「鉴」seal; anything that fails the check never shows up.</sub>
</p>

> The UI is Chinese-first (中文优先 is a project invariant). This is a short English entry point; the full docs are in Chinese.

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

Open `http://localhost:5173`, add your LLM key in settings, upload a book, and ask. Default model: DeepSeek `deepseek-v4-flash`.

## Bring your own key

No vendor key is bundled. Eight providers are preset: DeepSeek (default), GLM, Qwen, Kimi, OpenAI, Gemini, and Grok over OpenAI-compatible endpoints, plus Anthropic native. Pick one and the base URL fills itself in. Your key stays in the browser and goes straight to the provider. No telemetry.

## How it works

A light index is built on upload. At query time the agent reads the source live and verifies every citation against it before showing anything.

For the whole-book maps (relationships, curves, foreshadowing), there's a second path: the book is read closely once into an evidence-anchored per-chapter structure, and every map is derived from that one read — no re-reading the whole book per view. So multi-million-word web novels work too; you're told up front how big the book is and that the first run reads it once, then it's cached and instant.

## Docs

Full docs are in Chinese: [README](README.md) · [User Guide](docs/USER_GUIDE.md) · [Architecture](docs/ARCHITECTURE.md) · [Contributing](CONTRIBUTING.md).

## License

[MIT](LICENSE)
