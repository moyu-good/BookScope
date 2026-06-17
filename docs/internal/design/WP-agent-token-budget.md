# WP-agent-token-budget 设计草稿 · 砍 agent loop 的 token 体量（降 DeepSeek 成本）

> **性质：设计草稿，待作者审，批准前不动代码。**

**日期**：2026-06-12
**上游**：exp-008 全量 probe 的真实 token 账本 + DeepSeek 官方定价调研 + 本轮"成本由 cache miss 驱动"的结论
**方法论锚**：戴明（无测量不改进）——先 profile 出 miss token 花在哪，再据数据砍；不靠直觉拍"砍哪"。对应项目第 33 轮"测量仪器先于优化"的教训。

---

## 1. 目的（盯对数）

砍用户的 DeepSeek 账单，顺带降延迟。

**先把优化目标钉死，免得跑偏**：盯的是**每查询的 cache miss token 总量**，**不是缓存命中率%**。这条反直觉，必须写进文档防止以后再被带歪：

- 成本 ≈ miss token × 单价。miss = 这次查询喂进去的**新原文**（缓存从没见过 → 必 miss → 这是真正在干活的部分）。
- exp-008 全量 39 次实测，成本拆开：

  | | token | 占成本 |
  |---|---|---|
  | cache **miss** input | 290 万 × $0.14/M | **93%** |
  | cache hit input | 164 万 × $0.0028/M | 1% |
  | output | 9 万 × $0.28/M | 6% |

  钱几乎全在 miss 上。命中率 36% 不是 bug——是"每次喂新原文"的必然。
- **命中率分两种情形看**（2026-06-12 作者校正，撤回原"命中率是错目标"的一刀切）：
  - **每问现检索（当前 RAG）**：miss = 每次新检索的原文，靠重发拉高命中率是浪费（36%→90% 等于把内容发 10 遍、总 token 454万→约2900万、成本反升 ~$0.44→~$0.48）。这种情形盯 miss 总量。
  - **深读一本书问多遍（BookScope 真实用法）**：把书的稳定上下文钉进 prompt 前缀、跨多次提问复用 → 命中率能上 90% 且越问越省（第一次付全价、之后那段按 1/50）。这是另一套架构（钉稳定上下文 vs 每问现检索），对深读场景可能真更优。**作者定缓存率 ≥90% 为硬目标。**
  - caveat：百万字书塞不进 100万 context、钉不了整本；钉法对精确引用有取舍。所以是"深读可塞下的书"上追 90%。
- 换 pro 不行（无论哪种情形）：缓存机制与模型无关（命中率不变），pro 每 token 贵 ~12 倍（~$5.4 vs flash ~$0.44）。

所以本 WP：Phase 1 同时量 miss 构成**和**"钉稳定上下文能不能把命中率推到 90% 且更省"，用数据定该砍 miss 还是该改架构；不碰换模型。

---

## 2. 现状（代码实证，不是印象）

每查询平均 input 11.6 万 token、其中 miss 约 7.4 万。miss ≈ 系统段（首发一次）+ 问题 + 这轮检索回来的所有原文（每条首发各算一次）。新原文从哪来：

- **`search_chunks`**：返回 top_k 条 `ChunkMatch`，每条带**整块 `chunk.text`**（[r0_search_chunks.py:215](bookscope/agent/backends/r0_search_chunks.py:215)）。一个 chunk ~1500 字。top_k 由 LLM 在 tool 入参给（schema 默认/上限待 Phase 1 确认）。一次 search ≈ top_k × ~750 token。
- **`get_chapter_range`**：返回区间内每章的**完整 `full_text`**（[r0_chapter_range.py:151](bookscope/agent/backends/r0_chapter_range.py:151)）。dispatcher 唯一的闸是 **20 万字上限**——单次合法调用最大能灌入十万级 token 的新内容。**头号肥源嫌疑**：哪怕只拉单章（这本书 ~4000 字/章）也是 search 一条 chunk 的数倍；拉个 5-10 章区间就是几万 token 一次性进上下文。
- **重发**：loop 每轮把完整 message 历史重发给 LLM。旧工具结果的重发**是 cache hit（便宜）**，但撑大总 token I/O = 拖延迟。当前只有 reactive 的 `_truncate_messages_r2`（[loop_r2.py:1246](bookscope/agent/loop_r2.py:1246)），撞上下文上限才截，**没有主动按预算裁剪**。

一句话：miss 钱主要砸在**检索/拉章返回的新原文体量**上，尤其 `get_chapter_range` 的整章 full_text。

---

## 3. Phase 1 · 先量（measure）

不先量就砍 = 拍脑袋。这一步把"7.4 万 miss/query 到底怎么构成"变成数字。

- **加 per-tool-call token 计量**进 `LoopTrace`：每个 tool result 进上下文贡献多少 token、其中首发（miss）多少 / 重发（hit）多少。区分 `search_chunks` vs `get_chapter_range` 各自的贡献。
- **跑一小批 profile**：复用 exp-008 那 39 次的同款题（或抽一批），产出 miss token 构成分解——system / question / search 结果 / chapter 拉取 / 重发各占百分之几。
- **验收**：能明确回答"miss token 里 `get_chapter_range` 占百分之几、`search` 占百分之几"。Phase 2 砍哪、砍多少由这个数定，不由猜定。

估 1 agent 天（加计量 + 跑 + 出分解图）。

---

## 3.5 Phase 1 实测结果（2026-06-16，预判被数据推翻）

per-tool 计量已落地（`measure_output_size` + `trace.tool_calls` 加
`result_chars` / `result_tokens_est`，commit `7246271`）。
`scripts/profile_token_budget.py` 跑 anshi（37.8 万字）3 题（全局论点 / 具体事件 /
章节描述），全 success，数据 `docs/internal/experiments/data/profile-token-budget-20260616-112519.json`：

| tool | result_tokens_est 聚合 | 占 tool 结果 | 调用次数 |
|---|---|---|---|
| **search_chunks** | 58,381 | **74.0%** | 6（2/题）|
| get_chapter_range | 20,461 | 26.0% | 1 |

真实 API usage：miss=96,733 / hit=96,640 / **命中率 50%**（每问现检索情形）。
tool 结果 est 合计 78,842 ≈ 真实 miss 的 81%，其余 ~19% 是 system + question +
citation_hint（首发也算 miss）。校准吻合。

**§2 的头号嫌疑（get_chapter_range 整章 full_text）被推翻**：

- **总量肥源是 `search_chunks`（74%）**，频次驱动——每题平均 2 次 search、每次 ~9,700 est-tok。
- `get_chapter_range` 是**单次最肥**（1 次调用就 20,461 est-tok，比单次 search 大一倍多），
  但 agent 用得少（3 题只 1 次）。所以"单次最肥 ≠ 总量肥源"。
- **mix 敏感**：这 3 题偏 search 友好；多问"第 X 章讲了啥"会抬高 get_chapter_range 占比。
  小样本（3 题），方向性结论，未来跑代表性题组（如 exp-008 那种拉章多的伏笔题）会更准。

**Phase 2 杠杆顺序据数据翻转**（原 WP 把 get_chapter_range 排第一）：

1. **`search_chunks` 收口**（总量第一杠杆）：top_k 设合理上限 + 单 chunk 文本超长截断到相关窗口。
2. **`get_chapter_range` 输出限体量**（单次肥源，第二杠杆）：拉章返回"相关段 + 摘要"而非整章 full_text。

≥90% 命中是**另一条路**（长上下文钉稳定上下文，已 GO/接入 agent_ask）的事，与本 RAG 模式砍
miss 是两件并行的事，别混。

---

## 3.6 长上下文钉稳定路实测（2026-06-16，≥90% 目标达成 + 暴露可靠性坑）

`scripts/profile_long_context.py` 把同一本 anshi（39.5 万字）钉进 system 前缀、背靠背问
6 题（关 L2、每题真打 DeepSeek），数据 `docs/internal/experiments/data/profile-long-context-20260616-113959.json`：

| 问 | 命中率 | miss | 说明 |
|---|---|---|---|
| q1 | —（回退）| — | 答案 JSON chapter 非 int → 解析失败回退 RAG；但书已发出、前缀进了缓存 |
| q2–q5 | **100%** | ~112/题 | 书全在 DeepSeek 前缀缓存（hit=264,832），只有问题 + 输出算 miss |
| q6 | —（回退）| — | 答案 JSON 缺 citations 字段 → 回退 RAG |

**结论**：

- **≥90% 命中目标达成——实测稳态 100%**（第 2 问起）。书钉进稳定前缀，DeepSeek 服务端
  前缀缓存满命中。这条路就是作者 ≥90% 硬目标的正解。
- **越问越省**：稳态 ~112 miss/题 vs RAG ~32,244 miss/题。算上一次性冷加载整本
  （~264,832 miss），深读约 **9 题**后累计成本反超 RAG，问得越多越省。（profiler 打印的
  "反超=2 题"偏乐观——q1 回退没把冷加载计进 cum，真账要算上那 ~26 万。）
- **⚠️ 可靠性坑**：6 题里 2 题（q1/q6）flash 返回的答案 JSON 不合格（chapter 非 int /
  缺 citations）→ `run_long_context` 回退 RAG。回退优雅（不崩、不丢答案），但 33% 回退率
  太高，长上下文还不能"可靠默认"。

**Phase 2 长上下文这一支**：① 硬化 `run_long_context` 的答案 JSON 解析——chapter `str→int`
强转、坏 citation 单条丢而非整条废、重试一次（同 reasoning model JSON autofix 既有套路），
把回退率压下去；② 据此把长上下文设成"塞得下的书"的默认问答路（`BOOKSCOPE_LONGCTX`
从灰度转默认）。质量护栏同 §4：引用真实性不许掉。

**① 落地 + 重测（2026-06-16，commit `3f9f2b5`）**：parse_final_answer 加 lenient 模式
（chapter str→int、坏 citation 单条丢）+ run_long_context 重试一次（纠正提示放 user 消息、
不破书前缀缓存）。同 6 题重跑（`profile-long-context-20260616-115111.json`）：

- **回退率 33% → 0%**（6/6 全 success，对比修前 2/6 翻车）。
- 命中率 6/6 全 **100%**（书前缀缓存满命中）。
- 引用质量按构造不掉：lenient 只动"会被 chunk-match 覆盖的章号"+ "丢没 snippet 的无证据
  citation"，从不把 verified 的 citation 改没；verify_citations 逻辑没碰。

**引用真实性 A/B 实测（2026-06-16，作者要求转默认前补）**：`scripts/probe_longctx_citation.py`
同 6 题在 anshi 上两条路都跑，逐字核验命中率（`probe-longctx-citation-20260616-120339.json`）：

- **长上下文 30/30 = 100%　·　RAG 51/51 = 100%**——引用质量实测不掉（= RAG，都满分）。
- 长上下文每答 citation 偏少（3–7 条）但全核验；RAG 偏多（5–12 条）也全核验。少而全验更干净。
- 附带：长上下文还快 2–4 倍（8–22s vs RAG 27–62s，单次缓存调用 vs 多轮检索）。

② 转默认：作者设的"先补引用真实性实测"前置已满足（实测 100% = RAG），待作者最终拍板翻 flag。

---

## 4. Phase 2 · 据数据砍（每条带质量护栏）

候选杠杆，**最终砍哪个、砍多狠由 Phase 1 数据排序**：

1. **`get_chapter_range` 输出限体量**（若 Phase 1 证实是肥源，最高优先）：20 万字上限砍到合理值；或返回"相关段 + 章节摘要"而非整章 full_text；或在 prompt 里引导 agent 优先用 search、只在必要时小范围拉章。
2. **`search_chunks` 收口**：top_k 设合理上限 / 单 chunk 文本超长时截断到相关窗口，而不是整块 ~1500 字全回。
3. **旧 observation 压缩**（smolagents 模式，OSS 借鉴清单 #8）：跑了 N 轮后把早先检索到的长 chunk 压成"摘要 + chunk_id"，要引用再凭 id 重拉。**注意**：重发本就是 cache hit、省的是延迟和总 I/O，不是省 miss 钱——所以这条主要降延迟，不是降成本的主力，排在 1/2 之后。
4. **headroom（OSS 评估候选，2026-06 作者分享）**：LLM 前压 tool 输出/日志/历史 60-95% token，CCR 可逆（原文本地存、用 tool 取回）、Apache 2.0、本地、pip。**边界**：① 只压"非引用的 token 垃圾"（旧工具元数据/trace），**绝不压要逐字引用的原文**（evidence-first 红线）；② prose 压缩器是 HF 训练模型，警惕拉模型依赖（同本地 embedding 的重量风险，待查）；③ 能塞下的书已被长上下文路覆盖（缓存~100%、不压原文、更优），所以 headroom 主要对 **RAG 路（塞不下的大书）**有意义。先评估再决定引不引。

**质量护栏（红线，不可省）**：砍上下文有伤答案和引用的风险——少喂原文，agent 可能找不全证据、引用变少变差。每个 cap 落地后**必须重跑 exp-008 probe（配对准确率 / 引用真实性不许掉）+ 检索 golden set**，确认"省了钱没换来答案变烂"。省钱伤了 evidence-first 立身之本就是负优化，宁可不砍。

估 1-2 agent 天（取决于 Phase 1 指向几个杠杆）。

---

## 5. 成功标准

- **主**：每查询成本降（miss token 降 + 缓存率升的综合）。**缓存率目标 ≥90%（作者定）**，具体路径（砍 miss / 钉稳定上下文）由 Phase 1 数据定。
- **护栏**：exp-008 配对准确率（事件族判）、引用真实性相对本轮基线（100% / 96.1%）不退；检索 golden set recall 不退。
- **附带**：单查询延迟下降（重发量降）。

达不到主标但护栏守住 → 记 STATE，保留计量能力，砍法待再议；伤了护栏 → 回退该项 cap。

---

## 6. 不做什么

- **不换 pro**——贵 12x、命中率不变（DeepSeek 缓存机制与模型无关）。
- **不动 r0 章节存储 schema**——代际级改动，副管理不得自行扩 r0（沿用 backend 外部注入的既有约定）。
- **不动 DeepSeek 前缀缓存的现有适配**（第九波 citation_hint 进固定段那套）——那个是对的，继续保留，本 WP 只减新内容体量。

---

## 7. 影响范围（批准后才动）

- `bookscope/agent/loop_r2.py`：`LoopTrace` 加 per-tool-call token 计量（Phase 1）；可能加 observation 压缩（Phase 2）。
- `bookscope/agent/backends/r0_chapter_range.py` + dispatcher：`get_chapter_range` 输出体量限制（Phase 2）。
- `bookscope/agent/backends/r0_search_chunks.py`：top_k 上限 / chunk 截断（Phase 2）。
- 验证：复用 `scripts/probe_foreshadowing.py`（exp-008）+ `scripts/eval_retrieval.py`（golden set）做质量回归。
- 落地后补一条 ADR 记成本优化决策 + 前后 miss token / 质量数据。

---

## 8. 给案例研究的礼物

这条线本身是好素材：**"优化对了数——成本由 cache miss 驱动，而不是命中率；冲命中率是新手陷阱"**。带真实 token 账本 + DeepSeek 定价 + "90% 命中率反而更贵"的反直觉算账，可直接写进 case-study 的成本工程章节。
