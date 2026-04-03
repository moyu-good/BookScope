<!-- /autoplan restore point: /c/Users/yincheng.guo/.gstack/projects/moyu-good-BookScope/main-autoplan-restore-20260402-131412.md -->

# BookScope v1.2 — UX Redesign: Reader Verdict First

## Problem Statement

用户上传书籍后，看到的第一屏是数字指标和操作按钮，无法判断"我会喜欢这本书吗"。BookScope 的独特优势是情感弧线+风格指纹的量化分析——这些数据从未被翻译成用户能直接决策的人话。

**CEO 审查前提修正（2026-04-02）：**
原计划误诊为"缺少内容摘要"。小红书用户已看过推荐帖、已知书讲什么；真实问题是"我会喜欢它吗"。LLM 内容摘要是 ChatGPT 做得更好的事，不是 BookScope 的护城河。正确解法是把情感指纹翻译成人话判断。

---

## Goals

1. 页面最顶部显示 **Reader Verdict**：一句人话判断 + 适合/不适合人群（本地生成，零 API 依赖）
2. 重构页面流：**Reader Verdict → 情感叙事 → 分析卡片 → 深度分析**
3. Save/Share/作者输入框 移至页面底部
4. CSS 建立清晰 5 层视觉层级（L1/L2/L3/L3.5/L4）
5. 所有新文本 i18n（EN/ZH/JA）

---

## User Story

**场景：** 小红书用户看到书的推荐，上传前几章到 BookScope。
**期望：** 30 秒内看到 "我会喜欢它吗" 的人话判断，而不是数字指标。

---

## Architecture

```
bookscope/models/schemas.py
  ├── EmotionScore, StyleScore (existing)
  └── ReaderVerdict (NEW dataclass)
      fields: sentence: str, for_you: str, not_for_you: str, confidence: float

bookscope/insights.py
  └── build_reader_verdict(arc_value, top_emotion_key,
                           style_scores, book_type, ui_lang) -> ReaderVerdict
      └── queries _VERDICT_TABLE (6 arc × 8 emotion, 48 entries + fallback)
          NOTE: extends / merges with existing _EMOTIONAL_GENRE dict pattern
                to avoid duplicate key-space (DRY)

app/main.py
  [REORDERED FLOW]
  ① Hero(lite: title+reading_time only)
  ② render_quick_insight()          ← Reader Verdict is first thing inside
  ③ Deep Analysis expander
  ④ Save/Share block (MOVED HERE from top)

app/tabs/quick_insight.py
  render_quick_insight()
    ├── build_reader_verdict() → _render_verdict_card()   ← BEFORE if-branch
    ├── if book_type == "fiction":  [Book DNA streaming + cards]
    ├── elif book_type == "academic": [...]
    └── else (essay): [...]

app/css.py
  L1: 24px/700  — book title
  L2: 12px/600 uppercase 0.08em  — section labels (raised from 11px for CJK)
  L3: 16px/400  — verdict sentence, Book DNA body
  L3.5: 14px/400 — card body data (NEW: fills gap between L3 and L4)
  L4: 12px/400  — auxiliary notes, confidence disclaimer

app/strings.py
  NEW keys: verdict_label, verdict_for_you, verdict_not_for_you,
            verdict_low_confidence, verdict_confidence
```

---

## Proposed Changes

### Change 1 — `ReaderVerdict` dataclass

**文件:** `bookscope/models/schemas.py`（per CLAUDE.md 架构约定：domain models go in models/）

```python
class ReaderVerdict(BaseModel):
    sentence: str = ""        # "步步收紧的心理张力，走向无法挽回的结局"
    for_you: str = ""         # "适合喜欢高张力的读者"
    not_for_you: str = ""     # "不适合要求快节奏的读者"
    confidence: float = 0.0   # 0.0 = 数据不足；1.0 = 完整匹配
```

导出自 `bookscope/models/__init__.py`。

### Change 2 — `build_reader_verdict()` 函数

**文件:** `bookscope/insights.py`

```python
def build_reader_verdict(
    arc_value: str,
    top_emotion_key: str,
    style_scores: list,
    book_type: str = "fiction",
    ui_lang: str = "en",
) -> ReaderVerdict:
```

逻辑：
1. 查找 `_VERDICT_TABLE[(arc_value, top_emotion_key)]`（基础句子 EN/ZH/JA + for_you + not_for_you）
2. 根据 `style_scores` 计算 style modifier（句长/TTR/adj_ratio）→ 附加修饰短语
3. 计算 confidence：`arc_value == "Unknown"` → 0.2；`style_scores == []` → 减 0.2；`top_emotion_key` 不在表 → 0.1；完整数据 → 0.9
4. `ui_lang` 不在 `{"en","zh","ja"}` → fallback to "en"；`book_type` 未知 → fallback to "fiction"

`_VERDICT_TABLE` 覆盖所有 6 arc × 8 emotion = 48 组合 + 通用 fallback。
注：`_VERDICT_TABLE` 的 key 格式与 `quick_insight._EMOTIONAL_GENRE` 相同——实现时将其迁移到 `insights.py` 统一维护（DRY）。

### Change 3 — `_render_verdict_card()` helper + Reader Verdict Card

**文件:** `app/tabs/quick_insight.py`

提取 helper（避免 3x 分支重复）：
```python
def _render_verdict_card(verdict: ReaderVerdict, T: dict, ui_lang: str) -> None:
    """Render the Reader Verdict card. Called ONCE before book_type branch."""
    ...
```

在 `render_quick_insight()` 开头、`if book_type == "fiction":` 分支之前调用：
```python
verdict = build_reader_verdict(arc_value, top_emotion_key, style_scores, book_type, ui_lang)
_render_verdict_card(verdict, T, ui_lang)
```

**Verdict Card 视觉规格（Design 审查补全）：**
- 左边框：`4px solid #6366f1`（indigo）
- 背景：`rgba(99, 102, 241, 0.06)`（极淡 indigo tint，与 void 背景区分）
- 内边距：`1rem 1.25rem`
- 首行：`for_you`（**判断先于描述**）—— "✅ 适合耐心型读者"
- 次行：`sentence`（读起来感受描述）—— L3 16px
- 第三行：`not_for_you`（"❌ 不适合…"）—— L3.5 14px
- confidence < 0.3：底部加 L4 disclaimer（`verdict_low_confidence` 字符串）
- 图标：使用 Material Symbols Rounded span（与现有 app 一致），不用 emoji `⭐`
- **Loading state**：分析期间 Verdict 不显示（build_reader_verdict 在 emotion_scores/style_scores 计算完成后调用，无 partial 状态）

**UI States 规格（Design 审查补全）：**
- Loading：Verdict 组件不渲染（在 `render_quick_insight` 调用之前 spinner 已完成）
- Empty（无书）：Welcome screen 拦截，never reaches Verdict
- Partial（arc=UNKNOWN 或 style=[]）：渲染 low-confidence Verdict + disclaimer

### Change 4 — 页面流重构

**文件:** `app/main.py`

```
BEFORE:                          AFTER:
① Hero 指标卡（多指标）          ① Hero 卡（仅：书名 + 情感 + 字数 + 阅读时间）
② 作者输入 + Save/Share          ② render_quick_insight()
③ render_quick_insight()              └── _render_verdict_card()（顶部）
   └── Book DNA                        └── Book DNA
   └── 3列卡片                         └── 卡片区域
④ Deep Analysis 折叠              ③ Deep Analysis 折叠
                                  ④ 作者输入 + Save/Share（移底部）
```

Hero 轻量化：移除"分块数"指标。

**Save/Share 位置注意：** `_share_confirm_pending` 弹窗将随 block 移至底部——确认对话框远离按钮是已知 UX 权衡，可接受（低优先级，未来可改为侧边栏）。

### Change 5 — CSS 5层视觉层级

**文件:** `app/css.py`

```css
/* L1 — 书名 */
.bs-hero-title { font-size: 24px; font-weight: 700; line-height: 1.2; }

/* L2 — Section 标签（升至12px保障CJK可读性） */
.bs-insight-headline-label {
  font-size: 12px; font-weight: 600;
  letter-spacing: 0.08em; text-transform: uppercase;
}

/* L3 — 核心内容（verdict sentence, Book DNA body） */
.bs-verdict-sentence { font-size: 16px; font-weight: 400; line-height: 1.65; }

/* L3.5 — 卡片正文数据（新增，填补L3和L4之间的空白） */
.bs-card-body { font-size: 14px; font-weight: 400; line-height: 1.5; }

/* L4 — 辅助说明 */
.bs-verdict-sub { font-size: 12px; color: #7d8590; line-height: 1.4; }
```

Reader Verdict Card：左边框 `#6366f1`（indigo）
Book DNA Card：左边框 `#e8b84b`（amber，保持原色）

### Change 6 — i18n strings

**文件:** `app/strings.py`

```python
"verdict_label":          {"en": "READER VERDICT",      "zh": "读者判断",     "ja": "読者の判定"},
"verdict_for_you":        {"en": "Great for",            "zh": "✅ 适合",      "ja": "✅ おすすめ"},
"verdict_not_for_you":    {"en": "Skip if",              "zh": "❌ 不适合",    "ja": "❌ 向いてない"},
"verdict_low_confidence": {"en": "Limited data — rough guide only",
                           "zh": "数据不足，仅供参考",
                           "ja": "データ不足、参考程度に"},
```

---

## Files Affected

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `bookscope/models/schemas.py` | 新增 class | `ReaderVerdict` Pydantic model |
| `bookscope/models/__init__.py` | 修改 | 导出 `ReaderVerdict` |
| `bookscope/insights.py` | 新增函数 | `build_reader_verdict()` + `_VERDICT_TABLE` |
| `app/tabs/quick_insight.py` | 修改 | `_render_verdict_card()` helper，在 branch 前调用 |
| `app/main.py` | 修改 | 重排页面，Hero 轻量化，Save/Share 移底部 |
| `app/css.py` | 修改 | 5层视觉层级 |
| `app/strings.py` | 修改 | 新增 verdict i18n keys |
| `tests/test_insights.py` | 修改 | 新增 `build_reader_verdict()` 测试（≥9 个）|

---

## Test Plan

```
build_reader_verdict() — 9 tests:
  ├── [happy path] arc=RAGS_TO_RICHES + joy + fiction, en
  │       → sentence not empty, confidence >= 0.5
  ├── [fallback-arc] arc=UNKNOWN
  │       → confidence < 0.3, sentence has fallback text (not empty)
  ├── [fallback-style] style_scores=[]
  │       → no exception, confidence reduced, style modifier absent
  ├── [table-gap] emotion=disgust (sparse in existing genre table)
  │       → fallback used, no KeyError
  ├── [lang-fallback] ui_lang="de"
  │       → returns EN sentence without error
  ├── [type-fallback] book_type="unknown"
  │       → returns fiction-category verdict without error
  ├── [double-fallback] arc=UNKNOWN + style_scores=[]
  │       → confidence=0.0
  ├── [smoke-all-arcs] all 6 named arc patterns
  │       → each returns non-empty sentence
  └── [model-serial] model_dump() includes all 4 fields

_render_verdict_card() — integration (covered by quick_insight smoke tests):
  ├── confidence >= 0.3 → disclaimer NOT in rendered markdown
  └── confidence < 0.3 → disclaimer string present

ReaderVerdict model:
  └── in test_models.py: fields + default values
```

---

## NOT in scope (this plan)

- LLM 内容摘要（延后至 v1.3）
- 新的分析算法或图表类型
- NRC 管道任何修改
- 移动端响应式
- 图表视觉重设计
- 完整 CSS 主题重写
- Share 确认弹窗移至侧边栏（延后，低优先级）

---

## Error & Rescue Registry

| 错误场景 | 影响 | 救援策略 |
|---------|------|---------|
| arc = UNKNOWN（数据不足） | 低置信 | confidence < 0.3 + fallback sentence |
| emotion_scores 为空 | 无主导情感 | arc + style 生成简化 verdict，confidence = 0.1 |
| style_scores 为空 | 无 style 修饰符 | 跳过 modifier，confidence -= 0.2 |
| 非 EN/ZH/JA 语言 | 无翻译 | fallback to EN |
| book_type 未知 | 无类型 verdict | fallback to fiction |
| 双重 fallback | 最差情况 | confidence=0.0，显示 low_confidence disclaimer |

---

## Failure Modes Registry

| 场景 | 风险 | 预防 |
|-----|------|------|
| Verdict 文字通用化（"这是本好书"）| HIGH | 48条映射逐条要求可区分，review 后上线 |
| ZH/JA 翻译不自然 | MEDIUM | 硬编码，人工校对，不使用机器翻译 |
| 同一 arc+emotion 文字重复 | MEDIUM | 48条映射保证无完全重复 |
| Share 确认弹窗远离按钮 | LOW | 已知权衡，接受 |
| Streamlit 状态丢失（Save/Share 移位）| LOW | 整块原子移动，widget key 不变 |

---

## Dream State Delta

```
THIS PLAN (v1.2)               12-MONTH IDEAL             GAP
─────────────────────────────  ─────────────────────────  ───────────────────
Reader Verdict（本地查找表）    Reader Verdict + ML个性化  △ 基础到位，未来增强
页面流：Verdict→DNA→卡片→深度   同                         ✅ 达成
Save/Share 底部                侧边栏                      △ 接近，share弹窗需改
CSS 5层视觉层级                完整设计系统                 △ 基础到位
                               跨书对比功能                未来版本
```

距离 12 月理想状态约 78%。

---

## Decision Audit Trail

| # | Phase | Decision | Principle | Rationale | Rejected |
|---|-------|----------|-----------|-----------|----------|
| 1 | CEO | 放弃 LLM 内容摘要，改为 Reader Verdict | P4+P5 | ChatGPT 已做得更好；Verdict 用现有数据，无重复 | LLM Content Summary |
| 2 | CEO | 选 B（纯本地 Verdict），不做 A+B 混合 | P3+P5 | 用户确认；混合方案增加维护复杂度 | A+B 混合 |
| 3 | CEO | Save/Share 移底部而非侧边栏 | P5 | 侧边栏改动范围更大；底部是最小改动 | 侧边栏 |
| 4 | CEO | Hero 卡移除"分块数"指标 | P5 | 分块数对读者无意义 | 保留所有指标 |
| 5 | Design | 3列网格改为纵向单列主卡片 | P2+P5 | 在 blast radius 内；3列是"别扭感"的主要来源 | 保留3列网格 |
| 6 | Design | Verdict 首行改为判断（for_you），描述放第二行 | P5 | 用户需要"yes/no for me"在前3个字 | 描述先，判断后 |
| 7 | Design | L2 升至 12px（原计划11px）| P5 | 11px 在 CJK 非 Retina 屏幕上不可读 | 11px |
| 8 | Design | 补全 loading/partial UI 状态规格 | P1 | 缺失状态规格 = 实现者3个独立决策 = 视觉不一致 | 未规格化 |
| 9 | Eng | `ReaderVerdict` 放 `models/schemas.py` | P5 | CLAUDE.md 约定：domain models in models/ | insights.py 内 dataclass |
| 10 | Eng | 扩展 `_EMOTIONAL_GENRE`，不新建48条表 | P4 | 同 key 空间存两张表 = 维护地雷 | 新建 _VERDICT_TABLE |
| 11 | Eng | 提取 `_render_verdict_card()` helper | P4 | 3分支各插入 = 未来必然 drift | 3x 分支各自插入 |
| 12 | Eng | 测试计划扩展至9个明确 case | P1 | 关键 fallback 路径必须有测试覆盖 | "≥8个" 无具体清单 |
| 13 | Eng | L3.5 14px 补入 CSS 体系 | P5 | 3列卡片数据无合适层级，会回退到 L3/L4 两极 | 只保留4层 |

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/autoplan` | Scope & strategy | 1 | DONE —前提修正（LLM摘要→Verdict）| 6 findings, 2 CRITICAL |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | 不可用（Windows） | — |
| Eng Review | `/autoplan` | Architecture & tests | 1 | DONE | 5 findings, 0 CRITICAL |
| Design Review | `/autoplan` | UI/UX gaps | 1 | DONE | 5 findings, 2 CRITICAL |

**VERDICT:** 3-phase review complete. 13 auto-decisions. 0 taste decisions remaining. Ready for approval.

