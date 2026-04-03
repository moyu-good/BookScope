# TODOS

## Deferred from QA (2026-03-26)

- [x] **ISSUE-001 — Document pip install step more prominently** _(done 2026-03-27)_
  Added `pip install -e ".[dev]"` as the primary install command in Quick Start,
  plus an explicit tip box for the ModuleNotFoundError case.
  README also updated for v0.2.0.0: multilingual, PDF/URL, 192 tests.
  _Source: QA report 2026-03-26_

- [x] **Gitignore `.hypothesis/`** _(done 2026-03-27, commit 416d1ad)_
  The initial commit included `.hypothesis/` (Hypothesis property-test constants).
  Add `/.hypothesis/` to `.gitignore` to avoid committing auto-generated test data.
  _Source: QA session 2026-03-26_

## Redesign (2026-03-27)

- [x] **UI redesign — modern dark theme + full EN/ZH/JA i18n** _(done 2026-03-27, branch feature/ui-ux-i18n-redesign)_
  - Modern dark UI: purple accent, gradient hero card, card-style metric panels
  - Hero insight card: book title, one-sentence summary, dominant emotion, arc name
  - Sidebar language toggle (EN / 中文 / 日本語) — all UI text switches instantly
  - Localized arc names (ZH idioms: 乐极生悲/好事多磨/回光返照; JA equivalents)
  - Plain-language descriptions for every chart so general users understand

## Deferred from v0.4.0.0 autoplan (2026-03-27)

- [x] **Load saved analysis from sidebar** — `▶ Load` button on each saved entry; resumes prior
  analysis without re-uploading. Loaded badge + "× New analysis" clear button. _(done 2026-03-27)_

- [x] **Streamlit Cloud deployment prep** — Demo mode added (welcome screen "Try demo" button
  loads embedded 20-paragraph story); `requirements.txt` generated; `pyproject.toml` enables
  auto-install on Cloud. _(done 2026-03-27)_ To deploy: push to GitHub, connect repo at
  share.streamlit.io, set Main file path to `app/main.py`.

- [x] **spaCy NER for character extraction** — `extract_character_names` tries spaCy NER first,
  falls back to regex. Optional dep `pip install -e ".[spacy]"`. _(done 2026-03-27)_

- [x] **Full CJK Quick Insight genre labels** — ZH/JA genre labels from `_EMOTIONAL_GENRE`
  now displayed in fiction headline card for Chinese and Japanese UI languages. _(done 2026-03-27)_

## Fixed during QA (2026-03-27)

- [x] **ISSUE-004 — CJK word_count displayed as 0–1 for Chinese/Japanese** _(fixed 2026-03-27, commit be62d60)_
  `ChunkResult.word_count` used `len(text.split())` which returns near-zero for CJK
  text (no spaces). Fixed: chunker now passes `word_count=_word_count(text, lang)`.
  _Source: QA session 2026-03-27_

## v0.6.0 — completed 2026-03-30

- [x] **app/main.py refactor** — 1869 → 296 lines, split into 8 modules under `app/tabs/`,
  `app/sidebar.py`, `app/analysis_flow.py`, `app/css.py`, `app/strings.py`. _(commit 3f262f4)_
- [x] **LLM narrative insight** — `bookscope/nlp/llm_analyzer.py`, Claude Haiku AI Narrative
  card in Quick Insight tab, MD5 cache key, truncation guard, 12 new tests. _(commit 0474fbd)_
- [x] **Compare tab QA + polish** — same-book guard (`_content_fingerprint`), single-book note,
  fixed hardcoded `"No style data."`, 10 new tests. _(commit c049f3d)_
- Tests: 221 → 243 (+22)

## v0.7.0 — completed 2026-03-30

- [x] **Analysis card sharing** — `bookscope/viz/card_renderer.py`: 800×480 dark PNG card with
  title, top emotion badge, arc pattern, stats, and emotion bar chart. Download button in
  Export tab. No new runtime deps (matplotlib already present). 7 new tests. _(commit 31de16c)_
- [x] **LLM model selector in sidebar** — Haiku (fast) / Sonnet (quality) radio in "AI options"
  expander. Choice stored in `st.session_state["llm_model"]` and read by `generate_narrative_insight`.
  _(same commit)_
- Tests: 243 → 250 (+7)

## v0.8.0 — completed 2026-03-30

- [x] **Genre-aware LLM prompt pipeline** — `llm_analyzer.py` extended with 3 prompt builders
  (fiction / nonfiction / essay), `genre_type` param, "academic" alias. 10 new tests. _(commit 031a482)_
- [x] **`genre_analyzer.py` — raw-text LLM extraction** — New module reads actual chunk text
  (not scores) via uniform 5-chunk sampling. `extract_nonfiction_concepts()` → concept tags +
  argument sentence. `extract_essay_voice()` → 2-sentence voice description. Session-state
  cache. Graceful fallback when API key absent. 39 new tests. _(commit fce1c1a)_
- [x] **Wire genre_analyzer into quick_insight.py** — Nonfiction Card 1 (Core Concepts): LLM
  first, heuristic fallback. Essay Card 2 (Voice Fingerprint): LLM sub-text enriches heuristic
  label. Both use `st.spinner`. _(commit e551e66)_
- [x] **Code quality** — Remove dead `TYPE_CHECKING` import in `genre_analyzer.py`; fix E501 in
  `llm_analyzer.py`. _(commit 95e3e11)_
- Tests: 250 → 299 (+49 new tests)

## v0.9 — completed 2026-03-30

- [x] **Chat Tab (Approach C)** — `app/tabs/chat.py`; 8-chunk context sampling, MD5 cache,
  10-turn rolling window, no session_state in worker threads. _(commit 17c6d4f)_
- [x] **Reading time estimate** — "~X hr Y min" in hero card; wpm by book type × readability
  factor; guard for <100 or >200-hr equivalent. _(commit 17c6d4f)_
- [x] **Emotion DNA radar chart** — `EmotionRadarRenderer` + `build_emotion_radar_data()`;
  8-axis polar, fill keyed to dominant emotion color. _(commit 17c6d4f)_
- [x] **Book recommendations [Experimental]** — `_render_book_recommendations()` in
  quick_insight.py; gated by `ENABLE_BOOK_RECS=true`; MD5 session cache. _(commit 17c6d4f)_
- [x] **Pre-reading quick preview** — Quick Preview gate in `app/main.py`; LLM 3-sentence
  summary from first 5 chunks before full analysis. _(commit 17c6d4f)_
- [x] **Multi-book library view** — `app/tabs/library.py` + `EmotionComparisonRenderer`;
  most recent 20 analyses; mini dual-arc comparison with normalized x-axis. _(commit 17c6d4f)_
- [x] **Parallelize LLM calls** — `ThreadPoolExecutor(max_workers=2)` for academic/essay
  Quick Insight; worker threads receive model as explicit arg (no session_state). _(commit 17c6d4f)_
- [x] **`_call_llm` unit tests** — `TestCallLlm` class (9 tests): max_tokens, model path,
  API client construction, truncation, empty content. _(commit 17c6d4f)_
- [x] **`quick_insight.py` smoke test** — 6 tests in `test_quick_insight_smoke.py`: all three
  book types, empty chunks, CJK lang, markdown call assertion. _(commit 75c555d)_
- [x] **Japanese LLM output validation** — `TestJapaneseLLMPrompt` (7 tests): all three genre
  prompts include "Japanese" for lang='ja'. _(commit 75c555d)_
- Tests: 299 → 379 (+80)

## v1.0 Pre-dev Checklist（实现前必须完成）

- [ ] **CJK prompt 质量验证** — 实现 CJK 人物关系图前，手动评测现有 EN prompt 对 3 本中文小说的效果。
  取前 5 章，运行 `relation_extractor`，人工标注准确率。
  通过阈值：>75% 则直接复用 EN prompt，否则加入中文说明（`"Output character names in the original Chinese/Japanese"`）。
  _来源：CEO Review 2026-04-01，cross-model 张力决策_
  (Human: ~30min / CC: 协助评估)

- [x] **Streaming + st.expander() 兼容性测试** — `app/streaming_compat_test.py` 已创建。
  运行 `streamlit run app/streaming_compat_test.py` 验证 Test A/C。
  实现采用 Plan A（streaming 在 expander 外，使用 `st.write_stream()` 原生渲染）。
  _来源：CEO Review 2026-04-01，Outside Voice 发现_

- [x] **render_gilded_library.py 清理** — 已加入 `.gitignore`（commit 408ba7b）。
  _来源：CEO Review 2026-04-01，系统审计_

## v1.0 — 实现完成 2026-04-01

- [x] **CJK 人物关系图** — `relation_extractor.py`: guard 改为 `lang not in ("en","zh","ja")`，
  新增 `_presegment_cjk()` (jieba NR/NRF + janome 固有名詞)，hints 注入 prompt。
  `quick_insight.py`: 图门控扩展至 `detected_lang in ("en","zh","ja")`，<2实体时显示多语言空状态提示。
- [x] **非虚构概念图** — `genre_analyzer.py`: 新增 `extract_concept_relations()` (5-chunk 采样)
  和 `_parse_concept_graph()`。`relation_graph_renderer.py`: 新增 `edge_palette` 参数，
  contradicts→虚线，其余按色编码。`quick_insight.py`: academic 段落结尾渲染概念图。
- [x] **流式 LLM 输出** — `llm_analyzer.py`: 新增 `generate_narrative_insight_stream()` 独立 Generator 函数。
  `quick_insight.py` fiction 段: `_render_ai_card()` 替换为 `st.caption()` + `st.write_stream()`。
- [x] **Book Club Pack PNG** — `models/schemas.py`: 新增 `BookClubPack` Pydantic 模型 (Literal difficulty)。
  `llm_analyzer.py`: 新增 `generate_book_club_pack_structured()`。
  `card_renderer.py`: 新增 `render_book_club_card()` 800×600 PNG。
  `export_tab.py`: 新增 Book Club Pack PNG 生成 + 下载按钮。
- [x] **Essay 随笔时间线图** — `genre_analyzer.py`: 新增 `extract_essay_phrases()` (8-chunk 采样)。
  新文件 `viz/essay_graph_renderer.py`: `render_essay_timeline()` Plotly Scatter 平行时间线 (height=120px)。
  `quick_insight.py` essay 段: Voice Fingerprint 卡片之后渲染时间线。
- Tests: 399 → 399 (所有现有测试通过，无回归)

## Deferred to v1.0+

- [ ] **AnalyzerProtocol for LLM** — wrap `llm_analyzer.py` in `AnalyzerProtocol` when a
  second LLM backend is introduced. Not needed while only one backend exists.
- [ ] **Author cross-book comparison** — compare emotion arcs and style signatures across
  multiple books by the same author. Requires library view (v0.9) first.
  (Human: 2d / CC: ~45 min)
- [ ] **Server-side shareable URLs** — each analysis gets a public URL with cached results.
  Requires replacing local JSON store with server-side persistence (major architecture change).
  (Human: ~1 week / CC: ~3 hours)

## v1.2 — completed 2026-04-02

- [x] **Reader Verdict card** — `bookscope/insights.py`: `build_reader_verdict()` + 48-entry
  `_VERDICT_TABLE` (6 arc × 8 emotion, EN/ZH/JA). `bookscope/models/schemas.py`: `ReaderVerdict`
  Pydantic model. `app/tabs/quick_insight.py`: `_render_verdict_card()` helper, called before
  book-type branch. `app/strings.py`: verdict i18n keys. `app/css.py`: 5-layer typography +
  `.bs-verdict-card` styles.
- [x] **Page flow reorder** — `app/main.py`: Hero lite (removed "chunks" metric) →
  `render_quick_insight()` (Verdict first) → Deep Analysis expander → Save/Share (moved to bottom
  with `st.divider()`). Save/Share no longer appears above content.
- Tests: 413 → 422 (+9 `TestBuildReaderVerdict`)

## Deferred from v1.1 autoplan (2026-04-02)

- [ ] **v1.2 — 按书类型的风格基准线** — fiction/nonfiction/essay 三套 `_STYLE_RANGES`，按 `book_type` 选择
- [ ] **v1.2 — Emotion Radar Y 轴改为绝对计数** — 显示情感词密度而非仅比例
- [ ] **v1.3 — 可读性公式对齐标准** — 替换自定义权重，使用 Flesch-Kincaid 或 Dale-Chall
- [ ] **v1.3 — Arc 分类精度验证** — 建立人工标注测试集，验证 distance_to_arc 准确率

## Deferred from v1.2 autoplan (2026-04-02)

- [ ] **v1.3 — Share 确认弹窗移至侧边栏** — 当前 Save/Share 移至底部后，确认对话框远离按钮（已知 UX 权衡，低优先级）
- [ ] **v1.3 — LLM 内容摘要（Content Brief）** — 等 API key 普及率提升后，作为 Reader Verdict 的可选 LLM 增强（有 key 时加载，无 key 静默隐藏）
- [ ] **v1.3 — Reader Verdict 个性化** — 基于用户历史分析记录，调整"适合/不适合"的表达方式

## Strategic / Long-term (from CEO outside voice, 2026-04-02)

- [ ] **v2.0 — NRC 多语言准确率验证** — zh/ja 翻译版 NRC 词典准确率未经验证。
  考虑以 sentence-transformers 或 multilingual emotion model 替代 NRC 作为中日文后端。
  _来源：CEO 外部声音，Critical 发现_
- [ ] **v2.0 — 竞争差异化叙事** — 明确"可视化 + LLM 叙事组合"作为护城河的产品文案，
  区分于纯 LLM chatbot 竞品（Storygraph、GPT-4o 类应用）。
