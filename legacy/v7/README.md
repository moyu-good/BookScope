# legacy/v7/ — v7 代际归档

本目录保留了 BookScope v7（r0-baseline）代际的所有独有代码，用于：

1. 历史参考 —— 查 v7 三阶段流水线实现
2. 案例研究 —— 未来 `docs/internal/case-study/` 里对比 r0 vs r1 需要引用
3. 代码复用 —— 若未来某些 r0 分析器（例如 ArcClassifier、LexiconAnalyzer）被 r1 重新启用，可以从这里挪回

## 目录映射

| 归档路径 | 原路径 | 内容 |
|---|---|---|
| `legacy/v7/bookscope/nlp/` | `bookscope/nlp/` | v7 三阶段流水线的分析器组件（lexicon / style / arc / ner / relation / knowledge / soul / llm） |
| `legacy/v7/bookscope/services/` | `bookscope/services/` | v7 服务层编排（extraction_pipeline、derived_fields） |
| `legacy/v7/bookscope/api/` | `bookscope/api/` | v7 FastAPI 入口 + 12 个 router（upload / extraction / book / character / chat / search / charts / library / export / share / session / settings） |
| `legacy/v7/bookscope/eval/` | `bookscope/eval/` | v7 评测模块（dataset / retrieval_metrics / answer_metrics） |
| `legacy/v7/bookscope/viz/` | `bookscope/viz/` | v7 可视化渲染器（emotion / style / relation / heatmap / card 等） |
| `legacy/v7/bookscope/insights.py` | `bookscope/insights.py` | v7 洞察派生逻辑 |
| `legacy/v7/bookscope-frontend/` | `bookscope-frontend/` | 御览模式 React 前端（Vite + TS + Tailwind v4） |
| `legacy/v7/app/` | `app/` | v7 Streamlit 上位层（main、tabs、pages） |
| `legacy/v7/render_gilded_library.py` | 根目录 | 御览封面渲染脚本 |
| `legacy/v7/PLAN.md` | 根目录 | v7 时代的计划文档 |
| `legacy/v7/landing.html` | 根目录 | v7 营销落地页 |
| `legacy/v7/book-analyzer-project-plan.md` | 根目录 | v7 项目计划书 |
| `legacy/v7/viz-module-design.md` | 根目录 | v7 viz 模块详细设计 |
| `legacy/v7/TODOS.md` | 根目录 | v7 时代 QA 遗留清单 |
| `legacy/v7/scripts_inject_analysis.py` | `scripts/inject_analysis.py` | v7 手工注入分析数据脚本（命中 v7 API）|
| `legacy/v7/scripts_benchmark_embedding.py` | `scripts/benchmark_embedding.py` | v7 embedding 基准脚本（依赖 bookscope.eval）|
| `legacy/v7/tests/` | `tests/<v7-only>.py` | v7 相关的老测试（30 个文件）|

## 与 r1 的关系

r1-agent-loop 代际只依赖以下 r0 基础模块（这些仍在原位）：

- `bookscope/models/` — Pydantic 数据模型
- `bookscope/ingest/` — 加载、清洗、分块、章节检测
- `bookscope/store/` — 仓储 + SessionVectorStore + embedding_provider
- `bookscope/utils/` — NLTK 资源下载等

r1 的代码在 `bookscope/agent/` 下，测试在 `tests/agent/`，**不依赖任何 legacy/v7/ 下的代码**。

当前仍在原位的根层 r0 测试（7 个）：`test_chunker.py` / `test_cleaner.py` / `test_embedding_provider.py` / `test_loader.py` / `test_models.py` / `test_repository.py` / `test_reranker.py`。

## 如何复活某个归档模块

如果未来 r1 或 r2 需要复用其中某个模块，用 `git mv` 把它移回原位，然后在 r1 代码中正常 import。保留 git history 让 blame 仍能追踪。

## 归档基线

- 归档时间：2026-04-20
- 归档前 r1 测试：162 passed
- 归档后 r1 测试：162 passed
- 归档后 r0-pure 测试：133 passed
