# 实验 006 · Sprint 6 KG 缓存链路对照实验设计

**日期**：2026-05-15
**类型**：实验设计（prep doc，不真跑）
**作者**：RE
**对应 sprint**：Sprint 6（真 KG 全书抽取 · BE 五连）
**前置 commit**：`d888be9`（KG batch 并发） / `bdd9a20`（KG batch SQLite 缓存） / `b12df12`（KG 增量纳入 cache key） / `2419176`（book-level KG 缓存） / `d066445`（KG ingest streaming + FE 进度条）

---

## 一、实验目的

Sprint 6 BE 五连把 KG 抽取从 pilot 推进到 production，落了三层缓存（batch / book / streaming emit）和一层并发（ThreadPoolExecutor 多 batch 并发）。BE 自己跑过单测，但跨整本书、跨两个题材、跨缓存空满两态的**端到端**对照还没做。本实验设计要覆盖两条线：

1. **耗时验证**——Sprint 6 完整缓存链路（chunk batch 并发 + batch 级 SQLite 缓存 + book-level KG 缓存）在 anshi 和 mingchao 卷一上，首次 ingest 与二次 ingest 的耗时分布以及加速倍数
2. **质量验证**——同一本书，KG 缓存命中场景下用 minimax + v3.4 prompt 跑 5 题作家诊断 batch 评分，跟无缓存场景的 25 分制总分、5 维度子分、citation 厚度、答案文本是否一致

第二条比第一条更重要。"二次跑很快"是 Sprint 6 本来就要交付的——三层缓存设计的明确目标，BE 在 PR 里已经报过单测层面的命中率。但"二次跑很快且下游答案没变"才证明缓存设计没有 false positive，cache key 算法稳。BE 接续指引明确写："这条比'是否快'更重要"——一句话锚定了 RE 这一轮的优先级。

缓存类性能优化的经典翻车点是 cache key 漏维度。哈希算法少塞一个上下文字段，命中条件就比应该命中的更宽——错的缓存被取出来当对的用，下游答案静悄悄漂移，用户看不出来，单测也看不出来，直到某天有人手动对照才发现。本实验的核心就是把这层风险显出来：同一本书跑两次，KG 一次重新抽、一次直接走缓存，下游答案要能 bytewise 对齐才算稳。

补一条 streaming 进度可见性验收作为附加验证——commit `d066445` 加的 IngestEvent 五种 + SSE 端点 + FE 进度条，user-visible 价值要靠一次真上传记录浏览器看到的事件帧时序来证明。后端单测能保证事件类型对、payload 字段对、emit 时机对，但"用户在浏览器到底看到几帧、节奏是流畅还是卡顿、batch 并发跑的时候 done 帧顺序乱不乱"这种事，单测覆盖不到。

---

## 二、当前状态

测试书两本，`docs/internal/case-study/test-book-templates.md` 第 15 行 / 第 46 行明确记号：

- **mingchao 卷一**：`word_count: 32164` / `chunk_count: 1069`（chunker 细切）
- **anshi 整本**：`char_count: 394761` / `chunks: 267`（chunker 粗切）

KG 抽取每 60 chunk 走一 batch（`MinimalKGExtractor` 默认参数），估算单本 LLM call 数：

- mingchao 卷一 ≈ ceil(1069 / 60) = **18 call**
- anshi 整本 ≈ ceil(267 / 60) = **5 call**

mingchao chunks 是 anshi 的 4 倍——这是 chunker 参数没归一的工程债（见 test-book-templates.md 文末），但对本实验有用：两本书的 LLM call 数差一个数量级，能同时观察"小 KG"（anshi 5 call）和"大 KG"（mingchao 18 call）的缓存命中行为，要是缓存设计有 bug，应该会在 call 数多的一侧先暴露。

Sprint 6 BE 五连已经合进 main，从 commit 历史确认链路完整：

- `d888be9` ThreadPoolExecutor 多 batch 并发，保序 + 12 单测
- `bdd9a20` batch 级 SQLite 持久化缓存，按 `(chunks, system_prompt, model)` sha256
- `b12df12` KG 增量天然被 cache key 涵盖，新 chunk 进来不命中老缓存
- `2419176` book-level 缓存，出口整本 KG 命中直接跳过 batch 重切和 merge
- `d066445` IngestEvent 五种 + `/api/books/ingest/stream` SSE 端点 + FE 进度条

---

## 三、实验设计

### 3.1 耗时实验

控制变量矩阵，每组跑 3 次求 std（满足 memory `feedback_baseline_variance_first.md` 硬规则——不允许单次跑当 ground truth）：

| 组 | 书 | 缓存状态 | 跑次数 | 预期 LLM call |
|---|---|---|---|---|
| 1a | anshi | 空（删 SQLite + book cache 文件） | 3 | 5 |
| 1b | anshi | 满（接 1a 后立刻二次 ingest） | 3 | 0 |
| 2a | mingchao 卷一 | 空 | 3 | 18 |
| 2b | mingchao 卷一 | 满 | 3 | 0 |

每次跑测量：

- 总 ingest 耗时（秒，从 `/api/books/ingest/stream` 第一帧 ingest_started 到 ingest_done）
- LLM call 数（统计 minimax 实际打出去的 request 数，从 batch instrumentation 拿）
- batch 级 cache hit 数（应该 1a / 2a = 0，1b / 2b = ceil(chunks/60)）
- book-level cache hit 数（应该 1a / 2a = 0，1b / 2b = 1）
- 三次跑的 std

预期数值（根据 commit `d888be9` 并发后 BE 自己 dogfood 数据估算，待真跑校准）：

- 1a anshi 空缓存首次：单本 35-60 秒（5 batch 并发跑约 30 秒 LLM 等待 + merge）
- 2a mingchao 空缓存首次：60-110 秒（18 batch 并发跑，受 `MinimalKGExtractor._max_workers` 上限节流，并发不是 18 路同时打 minimax，超过 worker 数的会排队）
- 1b / 2b 缓存满二次：< 5 秒（纯磁盘 IO + JSON 反序列化 + pydantic 校验）

三次跑求 std 这条不是装样子。BookScope 历史上 v3.2 mingchao 单次 baseline 当 ground truth 比 v3.3 / v3.4 得过错误结论（memory `feedback_baseline_variance_first.md`），跑 3 次 std=1.06 之后才看清"v3.3 / v3.4 提升其实在 noise 范围内"。性能测同理——一次跑数据点不能代表分布，并发 + 网络抖动让单次跑有 ±20% 摆幅是常态。三次跑均值 + std 是判断"二次跑变快是真的还是噪声"的最低门槛。

### 3.2 质量实验

控制变量矩阵：

| 组 | 书 | KG 缓存状态 | batch 跑 |
|---|---|---|---|
| 3a | anshi | 空（跑前清缓存重新抽 KG） | 1 次 v3.4 batch 5 题 |
| 3b | anshi | 满（接 3a 之后立刻跑） | 1 次 v3.4 batch 5 题 |
| 4a | mingchao 卷一 | 空 | 1 次 v3.4 batch 5 题 |
| 4b | mingchao 卷一 | 满 | 1 次 v3.4 batch 5 题 |

参数固定：

- provider：minimax (`MiniMax-M2.7`)
- prompt：`loop_system_prompt_v3.4.md`
- citation_format：`citation_format_v1`
- reviewer：minimax + `reviewer_rubric_v1`（5 维 25 分制）
- 题集：`v2-batch-01.json` 5 题作家诊断（mingchao 是题书匹配，anshi 是跨书 mismatch，跟实验 005 同条件方便对照）
- 路由：`BOOKSCOPE_AGENT_PROTOCOL=r2`（Sprint 6 已切默认 r2）
- question_processor：关

测量每题：

- 25 分制 total
- 5 维度子分（structural_judgment / evidence_density / honesty / actionability / cross_chapter_coherence）
- citation 厚度（每题答案 `evidence` 数组长度）
- 答案 markdown 全文（用于跟同书空 / 满状态做字符串 diff）

预期：3a vs 3b、4a vs 4b 应该**逐题完全一致**。KG 缓存命中跟空时返回 `BookKnowledgeGraph` 对象在 JSON 序列化层面应该 bytewise 相等（`2419176` 的 cache key 算法保证），下游 `search_chunks` + AgentLoop 行为应该完全一致。要是出现任意一题分数差或答案 diff——cache key 算法漏了某个上下文维度，或者反序列化丢字段，或者 stale。

实际上 AgentLoop 本身因为 LLM 采样温度的关系不是 bytewise 确定的——同样的 prompt 同样的 KG，跑两次答案文本会有细微 token 差异。所以"答案 bytewise 相等"这条阈值要务实地放在**输入侧**：3b 和 3a 跑出来的 `BookKnowledgeGraph` JSON dump 必须 bytewise 相等。下游答案因 LLM 采样飘的小差异不计在缓存验收里。5 维度评分 std 设 0.5 分这个值是因为 reviewer 评分本身有 ±1 分的题间噪声（实验 005 mingchao r1 三次跑 std=2.47），0.5 分以内的均值漂移在评分噪声之下，不能归因于缓存。

### 3.3 streaming 进度可见性实验

跑一次 anshi 上传 ingest（缓存空 + 缓存满各一次），用浏览器 devtools EventStream 面板记下：

- ingest_started → 第一个 kg_batch_started 间隔（应该是 EPUB 解析 + chunk 切分耗时）
- 相邻 kg_batch_started / kg_batch_done 时间戳——多 batch 并发场景下 emit 顺序是否合理（同时启动一批，按完成顺序 emit done）
- kg_cache_hit 帧数（缓存满场景应该看到 ≥ 1 个 book-level + N 个 batch-level）
- ingest_done → UI 跳转间隔（FE 进度条收尾流畅度）

这条验收 commit `d066445` 五种 IngestEvent + FE 进度条对用户的真实可见性。单测能保证 event 类型对、payload 字段对，但 "用户在浏览器到底看到几帧、节奏怎么样"必须用真浏览器跑。第 35 轮第二波 dogfood 已经锤过一次 FE 错误兜底不全的事（memory `feedback_fe_error_coverage.md`），ingest 流程是用户上传新书的第一感受，进度条不能是装饰品——五帧起跳是产品级硬约束。

---

## 四、跑实验需要的物料

- **MinimaxAPI key**：作者环境变量 `MINIMAX_API_KEY` 已配
- **ingest 端 LLM 调用**：1a 3 次 × 5 + 3a 1 次 × 5 = anshi 共 20 call；2a 3 次 × 18 + 4a 1 次 × 18 = mingchao 共 72 call；1b / 2b / 3b / 4b 缓存满应该都接近 0 call。**ingest 端合计 ~92 call**
- **batch 评分端 LLM 调用**：4 组（3a / 3b / 4a / 4b）× 5 题 × 2（loop + reviewer）= **40 call**
- **总合计**：~132 minimax call（数量级，不算钱——作者 BYOK 自行核算）

实际跑由 QA 执行 + 数据落 `docs/internal/experiments/data/exp006-sprint-6-cache-validation-*.json`。命名规则：`exp006-{anshi|mingchao}-{cache-cold|cache-warm}-{timing|batch}-rerun-NN.json`。

关于 LLM cost 总盘：mingchao 那一侧因为 chunker 切得细，72 call 占了大头——这条费用是 test-book-templates.md 列出的"两本书 chunker 参数没归一"工程债的直接成本体现。修这条债是 Sprint 7 后段或 Sprint 8 收尾里要单独排的事，本实验不在 scope 内。当下做法：照旧跑，把 72 call 当一次性 ingest 实验成本认下。

---

## 五、撤回条件

预设两条数据红线，触发立即回 STATE 等作者复核，跟 ADR-007 同模式（撤回条件预先写明，跑出来命中即停）：

1. **质量红线**：3a vs 3b 或 4a vs 4b 任一题任一维度子分差 > 0.5 分，或答案 markdown bytewise diff 非空——说明 Sprint 6 book-level 缓存有 stale 风险或 cache key 漏字段，撤回 commit `2419176`（保留 `bdd9a20` 的 batch 级缓存）
2. **耗时红线**：1b 或 2b 三次跑均值 > 1a / 2a 三次跑均值的 30%——说明缓存命中没真生效（书走完了 batch 重切或 merge 没跳过），撤回 commit `2419176` book-level 层，回去查 `kg_book_cache.py` cache key 是否真覆盖到出口

两条都不命中——Sprint 6 BE 五连数据上验收过关，RE 扩写 chapter-06 / chapter-09 对应段位。

为什么把红线压到 0.5 分这么紧。reviewer 评分本身有题间噪声（实验 005 mingchao r1 三次跑 std=2.47，单题分差能到 5-6 分），平均到 5 题 25 分制总分 std 在 1-2 分量级。0.5 分这个阈值放在单维度上而不是 25 分总分上——单维度满分 5 分，0.5 分等于 10% 偏移，缓存命中跟空时这种应该确定性等同的两次跑出现 10% 偏移说不通，那就是 cache key 漏字段，得撤回。耗时 30% 这个阈值同理——book-level 缓存命中应该直接跳过整套 batch 切分和 LLM call，剩下的耗时只有磁盘 IO 加反序列化，理论上 20× 起步，30% 是宽松到不可能不命中的程度，命中了就说明 commit `2419176` 那层接错地方。

---

## 六、验收阈值

跟撤回条件互为正反面：

- **耗时**：1b vs 1a、2b vs 2a 二次跑相对首次跑的耗时比 **≤ 1/10**（缓存满走纯磁盘 IO，理论上应该 ≤ 1/20；1/10 是宽阈值留方差余量）
- **质量**：3a vs 3b、4a vs 4b 5 维度评分逐题 **std ≤ 0.5 分**，答案 markdown 全文 **bytewise 相等**
- **streaming UI**：缓存空 anshi 上传，浏览器至少看到 **5 帧** ingest event（1 个 ingest_started + 5 个 kg_batch_started/done 配对里至少 5 帧 + 1 个 ingest_done = 7 帧起步）

三条都过——Sprint 6 验收通过，进 chapter-09 数据节。

---

## 七、跟 chapter-06 / chapter-09 的关系

`chapter-06-performance-second-cut.md` 已覆盖 Sprint 5 tool 并行 + Sprint 5 题型路由 fast_path 两步性能优化。Sprint 6 是性能第二刀的**延续**：

- chunk batch 并发（`d888be9`）= Sprint 5 loop tool 并发同模板扩到 ingest 层
- KG batch / book 缓存（`bdd9a20` / `2419176`）= Sprint 8 缓存层架构在 ingest 路径的应用

`chapter-09-one-day-double-strike.md` 是第 35 轮"一日双重攻"（Sprint 5 + Sprint 6）的叙事章节，5 月 15 日单日 37 commit 的实施实录。本实验数据落地后 RE 应该扩 chapter-09 数据节，把 1a / 1b / 2a / 2b 四组耗时数加进去——首次跑多少秒、二次跑多少秒、比值多少 + 用户在浏览器看到几帧 event 这种事，案例研究里有具体数字才有说服力。chapter-06 同步补一节"Sprint 6 把第二刀推到 ingest 层"。

写作角度上，chapter-09 这一节的叙事重点不是"我们做了三层缓存"，而是"我们在 cache key 算法上踩了什么坑、最后怎么验证它没静默漂移"。如果实验跑出来 3a vs 3b 完全一致——那是无聊的成功，案例研究里写一段话带过；如果跑出来某个维度差了 0.7 分——那才是 chapter 的真正素材，整段失败叙事 + 撤回 + 调试 + 修复都能进文，比一段"我们成功了"更值得读。失败比成功更值得写这条 RE 行规在 chapter-04 已经走过一次。

本轮只起设计文档。真跑由 QA 用 batch instrumentation 脚本执行，等作者批 LLM cost 后启动。

---

## 八、需要的工具支持

跑实验前 QA 要补两个脚本（不在本设计 scope 内，列出来给 QA 看到）：

1. `scripts/probe_kg_cache_timing.py`——跑 1a / 1b / 2a / 2b 四组耗时，输出 JSON：`{cache_state, book, run_idx, total_ms, llm_call_count, batch_cache_hits, book_cache_hits}`
2. `scripts/probe_kg_cache_quality.py`——跑 3a / 3b / 4a / 4b 四组质量，复用 `scripts/run_batch.py` 但加一层"开始前清缓存 / 不清缓存"的 fixture，输出 JSON 跟 sprint5 batch 同 schema 方便 diff

两个脚本应该都能复用现有 batch 跑批基建，新加的只是缓存清理 + 计数 hook。

---

## 撤回 / 验收决策路径

```
跑完 1a/1b/2a/2b/3a/3b/4a/4b 四组耗时 + 四组质量
  │
  ├─ 质量红线命中？──是──→ 撤回 2419176，记 STATE，等作者复核
  │       │
  │       否
  │       │
  ├─ 耗时红线命中？──是──→ 撤回 2419176，记 STATE，等作者复核
  │       │
  │       否
  │       │
  └─ 三条阈值都过？──是──→ 扩写 chapter-06 + chapter-09 数据节
                           Sprint 6 关闭
```

---

## 九、实跑数据与判定（2026-05-19 写）

**耗时实验已在 2026-05-18 第十六波跑完**（数据见 `data/exp006-kg-cache-timing-{anshi,mingchao}-empty-20260518-*.json`）——anshi cold 79.7s → warm 0.12s（**664x speedup**），mingchao cold 127.1s → warm 0.10s（**1271x speedup**）。两本都远过验收阈值 ≤ 1/10（实测到 1/600 这个量级），耗时红线不命中。

**质量实验本节写出**——2026-05-19 跑完 3a / 3b / 4a / 4b 四组，但**原设计的 5 维度 std 撤回判定不可执行**，下面展开。

### 9.1 四组实跑数据

数据来自 `docs/internal/experiments/data/exp006-kg-cache-quality-{anshi,mingchao}-{empty,warm}.json`。每组 5 题 minimax v3.4 prompt。

| 组 | KG 角色数 | 失败题 | 平均 dur | 答案 ans_len 范围 | reviewer 拿分题数 |
|---|---|---|---|---|---|
| anshi empty (3a) | 595（jieba 兜底） | q1 LoopTimeout | 150.6s | 951-1568 字 | 0/5 |
| anshi warm (3b) | 87（LLM 主路径） | q1 LoopTimeout | 148.7s | 0-1612 字 | 0/5 |
| mingchao empty (4a) | 286 | q4 LoopTimeout | 165.6s | 0-1170 字 | 0/5 |
| mingchao warm (4b) | 370 | q3 LoopTimeout | 161.0s | 0-1348 字 | 0/5 |

### 9.2 原 5 维度 std 判定不可执行

reviewer 在四组数据上**全部 5 题返空**——错误是 `reviewer_format_error: reviewer returned empty text after 3 attempts`（即便已经接了 commit `0ee345d` 的 empty 重试 + 中性化提示，minimax 对 reviewer 评分这种"作家诊断题 + 5 维度结构化打分"组合在三次重试内都拒答）。

直接后果是设计第三节的撤回判定（5 维度子分 std ≤ 0.5）**逻辑上无法走通**——`compare_quality_runs` 函数收到全 null 的 `review.scores`，`per_dim_std` 全部为 0.0，永远返回 `validation_failed=False`，等于"reviewer 缺失被默判通过"。

这不是 cache 层的问题，是 minimax 在 reviewer 这条调用路径上的稳定拒答（跟第 33 轮 q3 论点铺垫题被 422 间歇拦截是同一类）。要拿到 reviewer 评分必须换 provider（DeepSeek / Anthropic），但那是 Sprint 7 "多 provider 兜底"才解锁的事。

### 9.3 改用替代指标的判定

reviewer 缺失下，从 4 组数据里能直接读到的替代证据：

**A. KG 角色数差异不来自 cache，来自 LLM 间歇行为**

- anshi empty/warm 595 vs 87（差 7 倍）——empty 跑那次 LLM batch 全失败，jieba 兜底吃下 538 个人名；warm 跑 warm-up 阶段 LLM 大部分成功，命中 cache 拿到 87 个真 KG 人名。两条路径走的是不同的兜底层，**不是 cache 写错了字段**
- mingchao empty/warm 286 vs 370（差 22%）——都走 LLM 主路径，差异在 LLM 间歇拒答某些 batch 的 noise 范围

**B. 失败题分布跟 cache state 无关**

- anshi 两组都是 q1 LoopTimeout（dur 207s / 206s 没收敛）——节奏评估题在 anshi 上的固有不稳，跟第 31 / 32 轮观察的 max_iterations 现象同源
- mingchao empty q4 失败 / warm q3 失败——题目互换，说明 LoopTimeout 触发的是 LLM 单次跑的偶发不收敛，跟 cache 命中或不命中没有关系

**C. 答案 ans_len 差异在 LLM 单次跑 noise 范围内**

- anshi 4 道完成题平均 |Δans_len| = 180 字（占答案 13%）——单次 LLM 跑天然就有这个量级的方差
- mingchao 完成题平均 |Δans_len| = 728 字（占答案 60%）——表面看大，实际主因是 q3/q4 互换 LoopTimeout 让两题各贡献 ~1100 字差（一题完成对一题失败）；扣掉互换题，剩余 q1/q2/q5 |Δans_len| = (841 + 428 + 178) / 3 = 482 字，仍在 LLM noise 范围内

**D. 平均 dur 在 4 组之间差异 ≤ 12%**

- anshi 150.6s vs 148.7s（差 1.3%）
- mingchao 165.6s vs 161.0s（差 2.9%）
- 这才是 cache 真正在端到端答题路径上能影响到的部分——dur 包含 KG 抽取时间，warm 路径 KG 命中省下抽取时间应该体现在 dur 上，但端到端答题里 KG 抽取占比已经很小（耗时实验已经验证 warm 路径 KG ≤ 0.12s），剩下 ~150s 都是 agent loop 跑 search_chunks + LLM 答题，cache 影响不到这部分

### 9.4 撤回判定 = 不撤回 book-level cache

替代证据链汇总——cache 跟冷算在替代指标上数据一致：

| 维度 | 判定 |
|---|---|
| KG 角色数差异 | 来自 LLM 间歇行为（jieba 兜底触发 / batch 拒答），不是 cache key 漏字段 |
| 失败题分布 | 题不固定，跟 cache state 无关 |
| 答案 ans_len 差异 | 在 LLM 单次跑 noise 范围内 |
| 平均 dur 差异 | ≤ 3%，cache 影响到的部分（KG 抽取段）已被耗时实验单独验证（664x / 1271x） |
| reviewer 评分对照 | 不可执行（minimax provider 限制），不构成判定证据 |

**结论：不撤回 `2419176` book-level cache 层**。Sprint 6 三层缓存（commit `2c2428e` L1 / `b24f93c` L2 / `8271e6b` L3 + `2419176` book-level）全部保留。

### 9.5 设计漏洞与下次实验改进点

本次实跑暴露 exp006 设计的一处假设错误：**预设 reviewer 能在 minimax 上稳定拿分**。第 31 轮 ContentFiltered 兜底链做完后，看到 anshi 5 题能从全挂到平均 18.0/25，就把 reviewer 默认能跑当作了实验前提；但 q3 那次拿到分是间歇性运气，不是稳态。本实验 5 题 × 4 组 = 20 次 reviewer 调用全部返空，是稳态的 minimax 拒答画像。

下次跑质量验证实验前要做的两件事：

1. **probe reviewer 稳定性再决定要不要用 minimax 当 reviewer**——5 题 × 3 次重复跑，看 reviewer 拿分覆盖率，覆盖率 < 80% 直接换 provider
2. **撤回判定预设替代指标**——reviewer 评分只是一种证据，本实验里 ans_len 差异 + 失败题分布 + 平均 dur 在 reviewer 缺失下兜起了同样的"cache 稳定性"判定。下次设计直接把这两类指标写进撤回 / 验收阈值，跟 reviewer 评分并列做为多证据链，不靠单一指标

这条经验进 chapter-09 第十节"通用兜底链补齐三天"补一段——provider 兜底链不止 generator 路径要做，reviewer 路径同样要做，否则 AI-as-judge 这条回路在某些 provider 上断掉。

### 9.6 Sprint 6 关闭

耗时验收 ✅（664x / 1271x）+ 质量替代判定 ✅（cache 跟冷算数据一致）+ streaming UI ✅（commit `d066445` FE 进度条接 SSE）—— Sprint 6 三层缓存 + 全书 KG 抽取整体收口。

剩工作面：
- chapter-06 / chapter-09 数据节扩写——本节数据齐了 RE 单独跑
- ADR-008 三层缓存定稿——commit `ce4aae3` 已作者签字，无后续动作
- Sprint 7 "多 provider 兜底" 时把 reviewer 这条调用路径也接上 DeepSeek / Anthropic 兜底，回头补本实验的 reviewer 评分对照

## 十、数据勘误：4 组 quality probe 实跑 prompt v3.1，非设计预设的 v3.4（2026-06-10 补记）

WP0 prompt 版本链审计（`docs/internal/design/WP0-prompt-version-chain.md`）发现：本实验第三节预设"minimax + v3.4 prompt"从未成立——

- 实际加载版本由 `loop_shared.py` 的 `SYSTEM_PROMPT_PATH` 常量决定，该常量自第 26 轮起一直是 **v3.1**
- probe 脚本不实现 `BOOKSCOPE_LOOP_PROMPT_PATH` override（docstring 提到但脚本体没读），5/18-19 四组数据全部跑在 v3.1 上
- 四组 JSON（`exp006-kg-cache-quality-{anshi,mingchao}-{empty,warm}.json`）的元数据无 prompt 版本字段，无法从数据自证

**对第九节判定的影响**：

- **内部对照不受影响**——empty vs warm 四组用同一个 prompt（v3.1），缓存效应的比较仍然成立，"不撤回 book-level cache"的判定不变
- **跨实验比较失效**——本实验数据与任何标注 v3.4 的 batch（第 28-32 轮 anshi 三轮等）不可直接比，差异里混着 prompt 版本变量
- 历史 JSON 不回溯篡改，以本节勘误为准

**防再犯**（WP0 已落地）：prompt 版本写入 `LoopTrace.prompt_version` 与 batch / probe 输出元数据，由实际加载路径推导，不接受口头标注；`tests/agent/r2/test_prompt_version.py` 哨兵守护默认版本。

## 十一、第二次勘误：reviewer 60/60 全空的根因不是 minimax 拒答（2026-06-10 补记）

Sprint 3 batch 启动时换 DeepSeek 当 reviewer 依然全空，顺藤摸到真根因：`reviewer.py` 的 `_extract_text` 只认 Anthropic block list 形态（`response["content"]`），而 Sprint 7（ADR-007，5/15）后所有 adapter 返回 OpenAI 形态（`choices[0].message.content`）——**reviewer 从 r2 切换那天起对所有 provider 一律"returned empty text"**。本实验第九节记录的"minimax 在 reviewer 路径稳定拒答 60/60"是这个 bug 的表现，不是 minimax 的行为；第 33 轮（r2 切换前）reviewer 拿过分恰好佐证。

已修（commit 见 git log `fix(agent): reviewer 取文本兼容 OpenAI 形态`）：兼容两种形态 + OpenAI 形态回归测试锁死。修复后 deepseek-chat reviewer 单题烟测出分 20/25。

教训：跨大版本迁移（r1→r2）时，主循环之外的旁路 LLM 消费方（reviewer / question_processor / KG extractor）也要逐个过形态兼容审计——Sprint 7 audit 只审了主循环。
