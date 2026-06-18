# Changelog

All notable changes to BookScope will be documented in this file.

## [1.2.0] - 2026-06-18 · 「给目标」模式：说一句话，它把相关分析串起来

以前用书鉴得自己挑功能点。这一版加了「给目标」：在问书里切过去，说你想搞清楚什么（比如"理清这本书的人物分属哪些阵营、彼此什么关系"），它自己决定该跑哪几个分析、按什么顺序，跑完综合成一份结论，每条结论挂得到原文、盖「鉴」印，整个过程摊在你眼前。22 个功能一个没少：知道要看什么就直接点按钮；有目标但不知道用哪个、或想要一份综合，就交给它。

### Added

- **「给目标」模式**：在问书里切到「给目标」，描述你想搞清楚的事，它规划（"我打算跑 X、Y，因为……"）、逐个跑、再综合成带原文证据的回答，综合不掺没原文支撑的话。
- **两扇门连起来**：综合里每块点一下就进对应功能的完整视图；在某个功能视图里也能一键把它跟别的维度串起来看。
- **顺手的建议**：问得比较开放、或连着看了好几个功能时，它会问一句要不要替你编排着跑（嫌烦能在设置里关掉）。

### Known limitations

- 综合的深度受它编排的单个分析的深度限制：目前单个分析只列最核心的部分（比如人物关系图约 30 条关系），所以综合可能不够全——理阵营时可能漏掉次要人物、甚至漏掉某一方。把单个分析做穷尽是后续版本的重点。

## [1.1.0] - 2026-06-18 · 可视化深化 + 精读注释 + 摄入与锚位更稳

这一版把"看见书的脉络"做深了一截，加了一个直接读原文的形态，并把摄入和原文定位的几个老毛病从根上修了。所有结论仍以原文证据为根——挂不上原文的判断一律不出。普通电脑可跑、自带 key（BYOK）不变。

### Added

- **可视化深化**——六张新图，直接看见人物与情节的脉络：
  - 人物叙事流图：谁和谁逐章同场
  - 多维叙事曲线：逐章的张力 / 情感 / 视角 / 主支线
  - 关系随时间演变：两人关系强度逐章升降，转折点配原文
  - 戏份 / 人物弧线：角色逐章的戏份密度与处境起落
  - 伏笔 → 回收弧线：哪个伏笔埋了、收没收，断掉的坑一眼可见
  - 支线编织图：每条支线何时活跃、在哪一章交汇
- **声口一致**：看每个角色说话的腔调稳不稳，标出"这句不像他说的"
- **改稿清单**：把一致性 / 伏笔 / 节奏 / 文体的诊断发现，聚成一张可勾选（待改 / 已改 / 不改）、可导出的修改清单
- **精读注释层**：读原文时行间浮出带证据的批注（伏笔、母题、矛盾、人物），点开就是支撑它的那段原文
- **格式扩大**：支持 docx、markdown、多文件系列（几十个 txt 当一本书读）
- **静态演示**：不用配 key、不用起后端，点进网页就能试，样本取自公版书的真实运行

### Fixed

- **原文锚位更准**：同一句话在多章重复出现时，引用不再贴错章——这条改善了全站所有功能的原文证据定位
- **章节识别对"脏书"更稳**：带目录、卷首摘录、重复回目的真实电子书不再把章号数错（某 120 回的书此前会被数成 240 章）；识别不出时安全退到顺序编号、绝不丢章

## [1.0.0] - 2026-06-17 · 首次公开发布

公开发布到 [github.com/moyu-good/BookScope](https://github.com/moyu-good/BookScope)，品牌「书鉴·BookScope」。核心：查询时智能代理 + 以原文证据为根的书籍深度分析——拒绝"批量预处理 + 静态展示"，所有结论现场由代理依据原文生成。此前的 `0.x` 为公开发布前的开发期版本（见下）。

## [0.10.0] - 2026-04-20 · r0 冻结 + r1-agent-loop 代际启动

本版本把项目从"批量预处理 + 静态展示"（r0/v7）整体切换到"查询时智能代理"（r1）。v7 独有代码通过 `git mv` 全部归档到 `legacy/v7/`，保留历史；r1 代际在 `bookscope/agent/` 下从零搭起，对外文档体系同步重建。

### Added

- **r1-agent-loop 代际**：查询时智能代理架构骨架全部落地，位于 `bookscope/agent/`
  - `tools/`：`search_chunks` / `get_chapter_range` / `list_characters_in_chapter` 的 Pydantic schema、dispatcher、以及 `ChunkRetrievalBackend` / `ChapterTextBackend` / `CharacterIndexBackend` 三个 Protocol
  - `backends/`：`R0SearchChunksBackend` / `R0ChapterRangeBackend` / `R0ListCharactersBackend` 三个 r0 数据接入实现 + `R0BookAssembler` 一键装配层
  - `adapters/`：`LLMClient` Protocol + `DeepSeekAdapter`（默认）+ `AnthropicAdapter`（备选），lazy import 各家 SDK
  - `loop.py`：`AgentLoop` 核心类，包含 duck-typed client、message loop、tool dispatch、citation 强制、失败重试、超时、LoopTrace 全链路
  - `prompts/`：版本化 system prompt（`loop_system_prompt_v1.md` + `citation_format_v1.md`）
  - `models.py`：`AgentQueryResult`、`LoopTrace`
  - `errors.py`：`AgentError` 层级 + provider 层 `ProviderError` / `ProviderUnavailable` / `RateLimited` / `ContextLimitExceeded`
- **架构决策记录（ADR）三份**
  - ADR-001：r1 三个 tool 接口规范，只做 3 个 tool，统一 `ToolResultBase` + `source_version` 追溯字段
  - ADR-002 v2：agent loop 技术选型（驳回 v1 锁定 Anthropic 的决策，改为"默认 DeepSeek function calling + Anthropic 备选 + provider-agnostic adapter 层"）
  - ADR-003：provider adapter 层设计，内容包括 `LLMClient` Protocol 契约、adapter 清单（DeepSeek / Anthropic / 后续 GLM / Qwen / Kimi）、OpenAI ↔ Anthropic 格式转换规范
- **长期工作手册与运行时核心文件**
  - `docs/internal/WORKFLOW.md`：十二节 CEO + AI 团队工作手册
  - `docs/internal/DEPUTY_MANAGER.md`：副管理模式完整操作手册（auto-accept 清单 + escalation 触发条件 + 汇报格式）
  - `docs/internal/NORTH_STAR.md` / `docs/internal/STATE.md` / `docs/internal/FLAGS.md`：方向、状态、告警三件套
- **文档目录七件套**：`docs/` 下新建 `build-log/` / `dogfood-notes/` / `architecture-decisions/` / `research-notes/` / `experiments/` / `reflections/` / `case-study/`
- **实验 001 设计**：`docs/internal/experiments/001-baseline-comparison-mingchao.md`，对《明朝那些事儿》第一卷的 6 对照组 × 5 题 × 3 维 rubric 横评设计
- **研究笔记 001 v1**：`docs/internal/research-notes/001-agentic-rag-landscape-v1.md`，agentic RAG + 长文本推理 + 书籍级 QA + grounded generation 四主线 13 篇 paper 地图
- **不变量"LLM provider 国内优先"**：写入 `docs/internal/NORTH_STAR.md`，首选 DeepSeek / GLM / Qwen / Kimi，Anthropic / OpenAI 降为备选；所有 LLM 调用必须 provider-agnostic

### Changed

- `AgentLoop` 默认 model 从 `claude-sonnet-4-6` 切到 `deepseek-chat`
- `CLAUDE.md` 重写为 r1 代际的入口文档：身份匿名化硬规则（禁止真实姓名 / 公司名出现）+ 项目目的三条 + 代际管理表 + 核心文件必读顺序 + 副管理模式
- `README.md` / `README.zh.md` / `README.ja.md` 三份 README 全部重写，反映 r1 代际现状
- `VERSION` 由 `0.9.3` 升至 `0.10.0`（minor 级跃迁，标记代际切换）

### Deprecated / Archived

- v7 三阶段流水线及全部独有代码归档至 `legacy/v7/`（167 个文件用 `git mv` 保留 git history）
  - `bookscope/{nlp, services, api, eval, viz, insights.py, app_utils.py, config.py}`
  - `bookscope-frontend/`（御览模式 React 前端）
  - `app/`（Streamlit 入口）
  - 根层 v7 文件：`PLAN.md`、`TODOS.md`、`landing.html`、`book-analyzer-project-plan.md`、`viz-module-design.md`、`render_gilded_library.py`
  - `scripts/inject_analysis.py`、`scripts/benchmark_embedding.py`
  - `tests/` 下 30 个 v7 测试文件
- `legacy/v7/README.md` 做归档导航

### Removed

- 临时 inject 脚本（`bookscope/api/routers/inject.py` + 根层 `inject_mingchao.py`），r1 不再需要无 API key 场景下的 KG 手工注入

### Fixed

- 清理项目文档里残留的真实姓名与系统用户名路径片段，统一使用 `moyu-good` 或职能称谓

### Internal

- Tests：r1 新套件 162 用例全绿（`tests/agent/`），覆盖三个 tool schema / dispatcher / 三个 r0 backend / 装配层 / `AgentLoop` 主循环 / 两个 adapter 的格式转换；r0 基础设施测试 133 个保持全绿
- Git：建立 `r0-baseline` 分支冻结 v7 最后状态（commit `3bd9676`），`r1-agent-loop` 为当前主线；每轮产出独立 commit，便于追溯
- Memory：长期偏好 `feedback_china_llm_first.md` / `feedback_anonymization.md` 等归档入 memory 体系

## [0.9.x] - 2026-03-28 至 2026-04-19 · v6 / v7 迭代（summarized）

本段期间的工作不在此 changelog 单独逐条列举，汇总要点如下（详细记录见 `legacy/v7/` 下的历史文档）：

- v6：御览模式前端落地（`ImperialBrush` / `MemorialSection` / `VermillionAnnotation` 等组件），以及 V2 / V3 共 13 项 UI/UX 修复
- v7：三阶段分析流水线（`chunk_scanner` → `chunk_selector` → 深度分析），从 v6 盲采样 20% 覆盖提升到全量覆盖
- 性能：分析耗时从 ~40 分钟降到 ~2 分钟
- `TransformerAnalyzer` 因要求 GPU 才可跑，在 Web 产品定位下被移除（无 GPU 不变量写入 NORTH_STAR）

## [0.5.2.0] - 2026-03-27

### Added
- **spaCy NER for character extraction** — `extract_character_names` now tries
  `spacy.load("en_core_web_sm")` first (proper PERSON entity recognition, handles
  multi-word names, eliminates common false positives). Falls back to regex NER
  automatically if spaCy / the model is not installed — zero behavior change for
  existing users. Enable with: `pip install -e ".[spacy]"`.
- **`[spacy]` optional extra** in `pyproject.toml` (`spacy>=3.7.0,<4.0.0`).
  `requirements.txt` includes the spaCy model wheel for Streamlit Cloud.
- **CJK genre labels in fiction Quick Insight** — `_EMOTIONAL_GENRE` ZH/JA labels
  (already defined in the mapping) are now displayed for Chinese and Japanese users.
  Previously the fiction headline card showed only arc + emotion name for non-EN users;
  now it shows the localized genre label (e.g. "心理悬疑 — 乐极生悲 ↗↘").

## [0.5.1.0] - 2026-03-27

### Added
- **Demo mode** — "📖 Try with a demo book" button on the welcome screen; loads a
  20-paragraph embedded story ("The Lighthouse Keeper's Last Storm") so visitors can
  explore all features without uploading a file. Demo badge + "× New analysis" clear
  button shown in the main area. Demo state cleared automatically when a real file/URL
  is provided.
- **`app/demo_book.txt`** — embedded demo story; Man-in-a-Hole arc, strong emotion mix,
  designed to exercise all 7 Full Analysis tabs and Quick Insight cards.
- **`requirements.txt`** — Streamlit Cloud compatible dependency list, kept in sync with
  `pyproject.toml`. Streamlit Cloud also auto-installs the `bookscope` package via
  `pyproject.toml` at build time.

## [0.5.0.0] - 2026-03-27

### Added
- **Load saved analysis from sidebar** — `▶ Load` button on each saved entry resumes a
  prior analysis instantly without re-uploading. Loaded badge + "× New analysis" clear button
  shown in main area. Save button hidden when viewing a saved result.
- **`detected_lang` field in `AnalysisResult`** — persisted to JSON (backward-compatible,
  defaults to `"en"` for old saves) so loaded analyses display the correct language label
  and drive CJK-aware features.

### Fixed
- **Chunks tab guarded for saved results** — shows info message instead of crashing when raw
  chunk text is not available (saved analyses store only scores, not source text)
- **Quick Insight `chunks=None` guards** — character extraction, key-theme extraction, and
  first-person density now handle `chunks=None` gracefully (return `[]` / `0.0`)
- **Export tab `detected_lang`** — analysis results exported/saved now include detected
  language field

## [0.4.0.0] - 2026-03-27

### Added
- **Quick Insight mode** — book-type-aware insight cards (headline + 3-col grid + "Who it's for")
  replacing the 7-tab view for general users; Full Analysis mode preserves all existing tabs
- **Book type selector** in sidebar (Fiction / Academic / Essay) — user-selected before upload,
  drives Quick Insight card content (no unreliable auto-detection)
- **`bookscope/insights.py`** — zero-new-dependency helpers: character extraction, key themes,
  readability grade, SVG sparkline, first-person density
- **`bookscope/app_utils.py`** — shared language/mode persistence via `st.query_params`
  (survives page navigation) + Google Fonts CDN injection
- **Language persistence across pages** — `?lang=` query param written on change; compare page
  reads it on load, language no longer resets when navigating main ↔ compare
- **Font override by language** — Instrument Serif + Inter (EN), Noto Serif/Sans SC (ZH),
  Noto Serif/Sans JP (JA); injected with `!important` to override OS system fonts
- **Compare page full i18n** — all labels, headers, captions in EN/ZH/JA
- **PDF support in compare page** — file uploader now accepts `.pdf` alongside `.txt` and `.epub`
- **Emotional genre classification** (EN fiction) — 11 arc×emotion combos mapped to reading-group
  recommendations; CJK books show emotion profile without uncertain genre labels
- New pytest tests for `bookscope/insights.py` (35 tests)

### Fixed
- **XSS via `unsafe_allow_html=True`** — all user-derived strings (book title, arc name,
  emotion name) now HTML-escaped before injection
- **`langdetect` non-determinism** — `DetectorFactory.seed = 0` in both pages for reproducible
  language detection inside `@st.cache_data`
- **PDF title stripping in compare page** — `.pdf` suffix now removed from book title display
- **`bookscope/app_utils.py` location** — moved from `app/ui_utils.py` into installed package
  to eliminate fragile `sys.path.insert` pattern
- **Sparkline zero-division** — flat valence series (common for CJK books) returns midpoint
  line instead of crashing
- **Character extraction CJK guard** — returns `[]` for ZH/JA/KO text immediately (no false
  positives from regex NER)
- **CSS animation replay** — session-keyed class prevents stagger animations replaying on
  every Streamlit widget interaction
- **disgust color** changed from `#a855f7` (clashed with purple accent) to `#84cc16`

### Changed
- `app/main.py`: mode toggle (Quick Insight / Full Analysis) appears below hero card;
  book type selector moved to sidebar (before upload); query_params language persistence
- `app/pages/02_compare.py`: full trilingual i18n, PDF support, language sync, langdetect seed
- `.streamlit/config.toml`: background `#0d1117`, card `#161b22`, text `#e6edf3`

## [0.3.0.0] - 2026-03-27

### Added
- Full trilingual UI (English / 中文 / 日本語): sidebar language toggle switches all labels,
  descriptions, tab names, arc names, and metric help text instantly without re-running analysis
- Hero insight card at top of analysis page: book title, one-sentence story summary,
  dominant emotion badge (color-coded), localized arc name with shape arrow, word count, chunk count
- Modern dark theme: deep navy background, purple accent (`#7c3aed`), gradient hero card,
  frosted-glass metric tiles, plain-language chart descriptions for general users
- Localized arc names — ZH idioms: 乐极生悲 / 好事多磨 / 回光返照 / 白手起家 / 盛极而衰 / 跌入谷底
- Localized arc names — JA: イカロス / シンデレラ / オイディプス / どん底からの成功 / etc.
- Emotion labels translated in bar charts, timeline selector, and chunk explorer (all 3 languages)
- Style metric labels and help text translated in Style tab
- Centered welcome screen with hero layout replaces plain info message

### Changed
- `app/main.py`: complete UI rewrite with i18n string dict, hero card HTML/CSS, language state
- `.streamlit/config.toml`: `primaryColor` updated to `#7c3aed` (purple)

## [0.2.0.0] - 2026-03-27

### Added
- Multilingual support: automatic language detection (English / Chinese / Japanese) via langdetect
- Chinese emotion analysis with jieba tokenization and bundled NRC Chinese lexicon (`nrc_zh.json`)
- Japanese emotion analysis with janome tokenization and bundled NRC Japanese lexicon (`nrc_ja.json`)
- CJK-aware word count: non-whitespace character count used as word proxy for Chinese and Japanese text
- Janome Tokenizer instance cached with `@lru_cache` to avoid 25–90 ms reload per chunk
- Language flag displayed in Overview tab (🇬🇧 / 🇨🇳 / 🇯🇵) alongside detected language name
- Test files: `test_book_zh.txt` (4-chapter Chinese), `test_book_ja.txt` (4-chapter Japanese)
- QA report: `.gstack/qa-reports/qa-report-localhost-2026-03-27.md` — health score 97/100

### Fixed
- ISSUE-004: `ChunkResult.word_count` returned 0–1 for CJK text because `model_post_init` used space-based splitting; chunker now passes `word_count=_word_count(text, lang)` explicitly
- Duplicate entries removed from `nrc_ja.json`: おびえる (fear ×2→×1), まさか (surprise ×2→×1)
- Unused `EMOTIONS` constant removed from `bookscope/nlp/multilingual.py`

### Changed
- `tests/test_multilingual.py`: 14 new tests covering CJK word count, language normalization, ISSUE-004 regression

## [0.1.0.0] - 2026-03-27

### Added
- Initial implementation of BookScope — multi-dimensional book text analysis and visualization tool
- Support for `.txt` and `.epub` file ingestion with HTML extraction and EPUB parsing
- Emotion analysis via NRCLex lexicon with per-chunk scoring for 10 emotion dimensions
- Style analysis: TTR, sentence length, noun/verb/adjective/adverb ratios
- Narrative arc classification (Freytag, Hero's Journey, Tragedy, Cinderella, Oedipus, Man in Hole, Linear)
- Streamlit UI with 7 analysis tabs: Overview, Heatmap, Timeline, Style Radar, Arc Pattern, Export, Chunks
- Book comparison page (`/compare`) — overlay emotion timelines and valence arcs for 2 books
- JSON persistence via Repository store
- 145 pytest tests (unit + Hypothesis property tests), 97% coverage

### Fixed
- CORS config conflict: `enableCORS = false` conflicted with `enableXsrfProtection = true` default — changed to `enableCORS = true`
- Info text on Overview tab now correctly mentions both `.txt` and `.epub` upload formats

### Changed
- `.hypothesis/` excluded from version control (auto-generated test data)
- Local editor settings excluded from version control (session-specific)
