# WP3 设计稿 · 章节识别鲁棒性（Phase A 观测 + Phase B 真章号）

**日期**：2026-06-10
**状态**：✅ Phase A+B 已落地（commit `bb008d2`，2026-06-10）· 第 4 步对照通过

**实现 vs 设计 vs 目的对照**：成功标准 5/5 验证（真章号解析 / 卷头不占号 / 告警进 upload 响应 / 四本真书实测落档 / 859 测试零回归）。偏离五处全部带理由记录在 commit 与实测落档文档：带卷名卷头放宽、book_cache 用必填版本字段替代不存在的版本常量、session 元数据走挂属性、probe 脚本保留供 Phase C 用、"第X回"误吃发现未修留档。**实测意外收获**：mingchao 七部书章号重排 / kuicheng 真重复章号 / zhinei 章节三重复——三个登记过的疑团首次拿到直接证据，单调守护让三本书自动安全回退。Phase C（虚拟分章）待单独设计。
**上游**：`docs/internal/design/2026-06-10-design-gap-review.md` 缺口 6

---

## 目的

citation 的 `chapter` 字段是作家定位修改的唯一坐标，但当前章节号是"正则命中序号"不是"书内真章号"——漏检一个全书偏移，卷章混排全部错位，无章节书整本算第 1 章。本 WP 让章节号变得**真实**（解析标题里的真章号）且**可观测**（检测质量指标 + 异常告警），无章节书的降级（Phase C）单独一期。

**受益者**：作者（citation 章号能直接对上自己稿子的章节）；多书型主张（CLAUDE.md：历史 / 理论 / 工具书 / 诗歌都要能跑）。

**成功标准**（可检验）：
1. "第四百二十章""第42章""第四十二回"解析出 420 / 42 / 42 真章号；解析失败回退序号并记录
2. 卷头（卷一 / 第二部 / 上篇）不再占用章节号
3. 上传响应带章节检测质量指标（检出数 / 解析成功率 / 平均章长），异常时带告警标志（如全书 5 万字只检出 1 章）
4. 四本测试书的章节检测指标实测落档（用真 epub 跑，零 LLM 成本）
5. 全套测试零回归 + 新增测试

## 方法论锚

1. **钱学森控制论（影响分析 → 分阶段 → 可逆）**——Phase A 纯观测零行为改动先行；Phase B 行为改变伴随缓存版本升级（旧缓存自动 miss，可逆 = 不删旧数据）；Phase C（虚拟分章）影响最深，单独一期。
2. **症状 ≠ 根因（本人沉淀）**——mingchao 1069 chunks vs anshi 267 chunks 两个数量级差异是登记过的异常（test-book-templates 第 48 行），Phase A 的指标正是给这类异常装检测器，不急于猜原因。

## 方案概要

### Phase A · 检测质量可观测（零行为改动）

1. `book_chunker` 新增 `chapter_detection_stats`：检出章数、章号解析成功率、平均/最大章字数、命中的正则模式分布
2. 异常告警规则（纯启发式常量，进代码留调）：
   - 全书 > 50,000 字但检出 ≤ 1 章 → `no_chapters_detected`
   - 平均章字数 > 100,000 → `chapters_too_coarse`
   - 检出 > 3,000 章 → `suspicious_overdetection`（正文 "(1)" 类误判嫌疑）
3. 指标进 upload 响应（`BookUploadResponse` 向后兼容附加字段）与 session 元数据；FE 展示留 PM 排期

### Phase B · 真章号解析

1. 标题解析：`第[中文数字/阿拉伯数字]+[章回节]` → 真章号（中文数字转换含"百千万零〇两"）；解析失败回退检测序号
2. 卷头识别：`卷X / 第X部 / 第X篇 / 上中下篇` 单独行视为分卷标记，**不占章节号**，记录进 stats
3. 单调性守护：解析出的章号序列非严格递增时（重复 / 倒跳），整书回退序号模式并在 stats 标 `parse_inconsistent`——宁可全书统一序号，不要混用两种语义
4. `[（(]\d+[)）]` 模式收紧：仅独立成行且行长 < 40 字才算章节头（压正文列表项误判）
5. **缓存版本升级**：章节映射语义变了，L3 book cache 与 KG book cache 的 schema_version 各升一级（v1→v2），旧 pickle / SQLite 条目自然 miss 重建——不删旧数据，可逆

### 实测落档

四本测试书（repo 根 test*.epub）各跑一次 ingest（零 LLM），检测指标写进 `docs/internal/case-study/test-book-templates.md` 新节——顺手给登记过的 chunks 数量级异常一份新数据。

## 影响范围

- `bookscope/ingest/book_chunker.py`（核心改动）
- `bookscope/api/routes/books.py` + `api/schemas.py`（指标透出）
- `bookscope/agent/_internal/book_cache.py` / `kg_book_cache.py`（schema_version 升级）
- 新测试 + `docs/internal/case-study/test-book-templates.md` 数据节

## 不做什么

- 不做无章节书虚拟分章（Phase C，单独设计——chapter 字段语义要引入 virtual 标记，影响三 tool 契约）
- 不做分块可视化页面（FE/PM）
- 不动 chunk 切分粒度本身（B-3 chunker 参数对齐是另一笔账，本 WP 只装观测）
- 不回溯修旧 batch 数据的章号

## 验证方法

- 单测：中文数字转换边界（四百二十 / 一千零一 / 两百）/ 卷章混排 / 倒跳回退 / "(1)" 误判压制 / 告警规则各条
- 四本真书 ingest 实测指标落档
- 全套回归（基线 825）+ ruff

---

## 自审记录（以目的为抓手）

| 要素 | 服务哪个目的 | 锚透镜 |
|---|---|---|
| Phase A 先行 | 成功标准 3/4——异常先可见 | 控制论分阶段 ✓ |
| 单调性守护整书回退 | 成功标准 1——宁可统一序号不混语义 | 可逆、简洁 ✓ |
| 缓存版本升级 | 防 stale（章号变了旧缓存还是旧映射） | 影响分析 ✓ |
| 实测落档 | 成功标准 4 + 给登记过的异常装数据 | 症状≠根因 ✓ |
| 砍掉：Phase C / 可视化 / 粒度 | 影响面更深，分期 | 外科手术 ✓ |

**估时**：Phase A+B 合计 2 agent 天 → 一个执行代理一轮。
