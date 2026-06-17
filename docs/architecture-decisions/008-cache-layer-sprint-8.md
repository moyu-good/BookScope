# ADR-008：Sprint 8 三层缓存设计

## Status

**已批准 · 2026-05-15 作者明示签字 · Sprint 8 启动**

- 代际：r2-agent-loop 单形态（Sprint 7 删 r1 后启动）
- 起草：副管理
- 创建日期：2026-05-15
- 作者签字：2026-05-15（"全部签字！"——同时批 Sprint 8 启动 + Sprint 6 真 KG 全书抽取提前两月启动 + Backlog B-1 解锁等多条工作）
- Sprint 8 实施进度：✅ L1 search_chunks 缓存（commit `2c2428e`，534 测试全绿）/ 推进 L2 LLM 调用缓存 / 推进 L3 book 预热缓存
- ADR Migration Plan timeline 实际提前：原 Sprint 8 编排是 2026-08-07，作者本日明示签字提前两月启动 5/15 即推
- 决策摘要：BookScope 在 r2 单形态稳定后加三层缓存——`search_chunks` 结果缓存 / LLM 调用结果缓存 / book 预热缓存。三层叠加在 Sprint 5 已有的工具并行加 fast_path 题型路由上，达成"重复问题 < 3 秒 / 冷启动 < 5 秒 / 单题 P50 < 30 秒"三个 Sprint 8 验收指标
- 本 ADR 是 Sprint 8 启动 prep 文档。真正落地代码在 Sprint 8 时间窗（2026-08-07 至 2026-08-20）内由 BE 分波执行；prep 阶段不写 runtime 代码，不改 ROADMAP timeline

## Context / 背景

Sprint 5 性能第一刀已经落了两件事：

- **工具并行**（commit `74bddd5`）：同一轮里 agent 起的多个 tool call 并发派发，单轮 wall time 不再线性叠加
- **题型路由 fast_path**（commit `fc10b20`，commit `0f36fb2` r2 兼容）：通识题（"主要角色有哪几个"等）走单次 `search_chunks` 加单次 LLM，端到端 3-12 秒；深题继续走完整 agent loop

实测数据点：通识题已经从原 90-180 秒降到 3-12 秒，深题维持 90-180 秒。Sprint 5 之后单题 P50 大约落在 30-60 秒区间——卡在深题的多轮工具调用上。

Sprint 8 的三个验收指标分别针对三种用户场景：

| 场景 | 当前耗时 | Sprint 8 目标 | 主要瓶颈 |
|------|---------|--------------|---------|
| 单题端到端 P50 | 30-60 秒 | < 30 秒 | 深题的重复 `search_chunks` + LLM 多轮 |
| 冷启动（用户问已上传书首字） | 当前会触发 lazy build，5-15 秒 | < 5 秒 | session 切回时 vector index / KG 要重新加载 |
| 重复问题（同 prompt 同上下文） | 同首次耗时 | < 3 秒 | LLM 调用本身可避免 |

三个场景对应三层缓存。Sprint 8 之前要先确认每层的命中率预估、存储后端选择、key 算法、失效策略——这是本 ADR 要回答的问题。

CLAUDE.md 硬约束在 prep 阶段就要先 lock 住：BYOK 原则下不假设用户有 Redis；普通 CPU 上可跑；缓存层不引入 GPU 依赖。

## Problem / 问题

直接说三个问题。

### 问题 1：BookScope 当前没有任何缓存层

请求生命周期"用户问 → fast_path 或 agent loop → tool 调 → LLM 调用 → 答案"在每一层都重复算。同一个 session 内反复问"角色 X 在第几章登场"，每次都重新跑 BM25 加 vector search；同一个 prompt 同一个 user message 第二次问，仍然实打实打一次 LLM API。这跟 BYOK 用户付费用 API token 的成本模型直接冲突——重复问要花两次钱。

ADR-005 落地的 session 持久化（JSON 文件存储）严格意义上只是"book 切回不丢"，不是缓存层——session 切回时 vector index 仍要重新 build，KG 仍要重新装载。

### 问题 2：每层的设计参数差异极大，不能一把抓

`search_chunks` 缓存命中率高但单层加速量适中（节省 BM25 加 vector search，约 100-500ms 每次）；LLM 调用缓存命中率视用户行为而定但单层加速量极大（从 30 秒直接到 < 1 秒）；book 预热缓存只在首次冷启动有效但解决的是"首字延迟"这个产品级问题。

不能拿同一份存储后端、同一个 TTL 策略、同一个失效逻辑套到三层上——会做到一半发现哪一层都不舒服。

### 问题 3：LLM provider 的非确定性让"缓存"语义模糊

第 31 轮 `ContentFiltered` 兜底里发现的现象：同 input 重试通常能过。这意味着 LLM provider 端有非确定性——内容审查触发、temperature 采样、provider 端 routing 都可能让"同 prompt 同上下文 → 同响应"这条假设打折扣。

缓存命中时直接返历史响应，是把这种非确定性折叠成确定性——好处是产品体验稳；代价是丢掉一次"重试可能更好"的机会。要明确这是设计选择，不是疏忽。

## Decision / 决策

### D-1：三层缓存按访问频次从外到内

按命中率与加速量的乘积排优先级，三层分别是：

**Layer 1 — `search_chunks` 结果缓存**

- 缓存对象：`(query, chapter_scope, character_filter, top_k)` → `list[ChunkMatch]`
- 缓存 key：`sha256(book_id + query + chapter_scope + character_filter + top_k)` 短指纹（前 16 字符）
- 范围：进程内全局（不分 session——同一本书在多用户场景下共享命中）
- TTL：默认 24 小时；book 重新 ingest 时整批 invalidate
- 失效条件：book vector index rebuild、chunk schema 升级、BM25 算法升级
- 命中率预估：单 session 内反复问同书时 40-60%；跨 session 但同书时 20-30%
- 单层加速量：100-500ms 每次（节省一次 BM25 加 vector search）

**Layer 2 — LLM 调用结果缓存**

- 缓存对象：`(messages, tools, tool_choice, model, temperature)` → `ChatCompletion` dict
- 缓存 key：按 D-3 计算
- 范围：进程内全局；但要按 `prompt_version` 字段分桶
- TTL：默认 7 天；prompt 版本升级时整版本 invalidate（不是单条）
- 失效条件：prompt 版本升级、tools schema 升级、model 切换
- 命中率预估：单用户单 session 内同题重问 70%+；跨用户同问题（"主要角色有哪几个"这类通识题）30-50%；深题跨用户命中率 < 10%
- 单层加速量：5-60 秒每次（视模型与轮数）

**Layer 3 — book 预热缓存**

- 缓存对象：vector index + KG + chunk-to-chapter / chunk-to-character 映射
- 缓存 key：`book_id`（即 `session_id`，ADR-005 已落地）
- 范围：进程内 + 磁盘双层（进程内 LRU 保最近 N 本，磁盘存全部）
- TTL：进程内 LRU 不设 TTL（按访问时间淘汰）；磁盘永久（跟 ADR-005 session 持久化同步生命周期）
- 失效条件：用户重新上传同书、ingest 算法升级（chunk 切分策略变 / KG 抽取器升级）
- 命中率预估：作者本人 dogfood 同一本 anshi 几乎 100% 命中；多用户场景下视 session 复用率
- 单层加速量：首次切回 5-15 秒 → < 1 秒（vector index 从磁盘 mmap 加载，不重新 build）

三层在乘积效应下叠加：通识题重复问命中 L2 直接 < 1 秒；深题命中 L1 节省 5-10 次 BM25 加 vector search、再命中 L2 部分轮的 LLM 调用，深题从 90-180 秒降到 60-100 秒，再叠加 L3 冷启动 < 1 秒——整体 P50 < 30 秒可达。

### D-2：缓存存储后端按层选择

四种候选放在一张表上比：

| 后端 | 跨进程 | 重启不丢 | 复杂度 | 引入外部依赖 |
|------|--------|---------|--------|-------------|
| in-memory dict | 否 | 否 | 低 | 否 |
| disk JSON | 否 | 是 | 低 | 否 |
| SQLite | 否 | 是 | 中 | 否（stdlib）|
| Redis | 是 | 是 | 高 | 是 |

按层选择：

- **L1 `search_chunks` 缓存**：in-memory dict + LRU 上限 1000 条。重启丢可接受——重新 build 时 cache 自然预热前几题就回到稳态
- **L2 LLM 调用缓存**：SQLite。重启不丢是产品级要求（用户付的 token 钱不能因为进程重启就再付一次）；LRU + TTL 双约束；引入 stdlib 不算外部依赖
- **L3 book 预热缓存**：进程内 LRU（最近 5 本书的 vector index）+ 磁盘（跟 ADR-005 session 存储共享路径）

**最终推荐选择**：**L1 in-memory + L2 SQLite + L3 进程内 LRU 加磁盘双层**。

Redis 全部 layer 都不选——BYOK 原则下不假设用户有 Redis，多用户场景 Sprint 8 不在 scope 内（见 D-9 第 4 条）。

### D-3：LLM 调用缓存的 key 计算

三个候选算法：

**算法 a — 整 messages JSON dump 后 sha256**

- 利：实现最简，一行 `sha256(json.dumps(messages + tools + tool_choice, sort_keys=True))`
- 弊：messages 数组在多轮 agent loop 下能堆到 50KB+，每次 dump 加 hash 有几十 ms 开销；assistant tool_calls 的 id 字段在不同轮次可能不一样（OpenAI 端生成的 random id），不归一化的话同 input 算出不同 key
- 评：作 baseline 可，需要归一化字段处理

**算法 b — 只对最后一条 user + 最近 N 条 tool result 哈希**

- 利：key 短，计算快；忽略中间 assistant 的 tool_call id 抖动
- 弊：丢失了上下文——前几轮的 tool result 也影响 LLM 输出；命中率会被错误抬高，导致返回过期答案
- 评：不接受

**算法 c — 按字段分层哈希加短指纹**

- 算法：
  - 把 messages 数组按角色分桶：system / user / assistant.content / assistant.tool_calls.function / tool.content
  - 每个桶单独 sort_keys dump + sha256
  - 五个 sha256 拼起来再算一次 sha256，取前 16 字符做短指纹
  - assistant.tool_calls 里的 `id` 字段在哈希前归一化（按出现顺序重新编号为 `call_0` / `call_1`），消除 provider 抖动
- 利：稳定、可读、字段级 invalidate 友好（如只想 invalidate "user 改了 system prompt" 那种情况，可只比 system 桶）
- 弊：实现量比 a 大；新增一类 message 字段时要更新分桶逻辑
- 评：**推荐**——稳定性收益值得多写 50 行代码

最终 key 形态：`f"v{schema_version}:p{prompt_version}:{hash16}"`——schema_version 控制 key 算法本身的变更（升级时全 invalidate），prompt_version 控制业务侧 prompt 升级时的整版本 invalidate（按 D-4）。

### D-4：缓存失效策略

每层的失效触发条件分开说，再统一在"缓存 versioning 字段"上落地。

- **L1 `search_chunks`**：key 已经含 query / chapter_scope / character_filter，用户改 query 形态时 key 自然变。需要主动 invalidate 的场景：book vector index rebuild、chunk schema 升级、BM25 算法升级。这三类操作触发 book_id 维度的整批 drop
- **L2 LLM 调用**：prompt 版本升级（v3.4 → v3.5 这种）整版本 invalidate；tools schema 改了整批 invalidate；model 切换不 invalidate（model 名是 key 的一部分，不同 model 各占各的 key）
- **L3 book 预热**：用户重新上传同书 → 新 book_id（ADR-005 session 隔离已落）；ingest 算法升级 → ingest_version 字段不匹配则强制 rebuild

**缓存 versioning 字段约定**：每条缓存条目带三个版本字段：

```
{
  "schema_version": "v1",       # key 算法 / 缓存条目结构本身的版本
  "prompt_version": "v3.4",     # 业务侧 prompt 版本
  "tool_version": "v1",         # tools schema 版本
  "value": ...,
  "created_at": ...,
  "hits": 0
}
```

读缓存时比对三个字段——任一不匹配就 miss（不是 hit 后再校验，是 key 设计上就把字段拼进去，see D-3 key 形态）。这避免"代码改了但 cache 没改"导致返回过期数据。

### D-5：缓存命中率预估与撤回阈值

| 层 | 场景 | 预估命中率 | 撤回阈值（低于此值不值得做）|
|----|------|-----------|---------------------------|
| L1 | 单 session 反复问同书 | 40-60% | < 20% |
| L1 | 跨 session 同书 | 20-30% | < 10% |
| L2 | 单用户单 session 重问 | 70%+ | < 40% |
| L2 | 跨用户通识题（如"主要角色有哪几个"）| 30-50% | < 15% |
| L2 | 跨用户深题 | < 10% | 已经在阈值下——L2 不针对深题优化 |
| L3 | 作者 dogfood 同书 | ~100% | < 50% |
| L3 | 多用户复用 | 视 session 复用率 | < 30% |

**撤回阈值用法**：Sprint 8 落地后 QA 跑命中率测试（D-8）。任一层连续两周低于阈值，下个 sprint 评估是否回退该层。撤回不是失败——是"这层不值得维护"的明确信号。

撤回阈值参考 CLAUDE.md memory `feedback_baseline_variance_first.md`：单次跑不算数，要跑出 std 之后再判。

### D-6：与 Sprint 5 性能优化的乘积效应

Sprint 5 落地的两件事在 Sprint 8 缓存层叠加之后的预期：

- **通识题**：当前 fast_path 已经 3-12 秒；重复问命中 L2 直接 < 1 秒。L1 在 fast_path 内部也命中（fast_path 只用一次 `search_chunks`），首次也能从 3-12 秒降到 2-8 秒
- **深题**：当前 agent loop 90-180 秒。L1 命中能节省 5-10 次 BM25 加 vector search（每次 100-500ms），降到 60-160 秒；L2 在多轮里部分命中——通常前几轮的 LLM 调用（generate query / route）会命中，后几轮的 synthesize 不太命中，整体降到 45-100 秒
- **长题分子问题**：Sprint 5 已落子问题拆分加难度评估。每个子问题独立走缓存——子问题级命中率比整题级高（子问题更短、更标准化）

三个 deliverable 的乘积让 P50 < 30 秒目标可达。冷启动 < 5 秒主要靠 L3；重复问题 < 3 秒主要靠 L2。

### D-7：与 ADR-007 r2 的兼容性

Sprint 8 在 Sprint 7 删 r1 之后做——只对 r2 形态考虑。简化点：

- LLM 调用缓存的 messages 形态固定是 OpenAI function calling（`role` / `content` / `tool_calls` / `tool_call_id`）
- D-3 的分桶哈希不用维护 r1 的 `tool_use` / `tool_result` block 形态
- LoopTrace 已经在 ADR-007 加了 `protocol_version`，缓存条目复用这个字段不另起一套

如果 Sprint 7 因故没删干净 r1 代码（audit 报告命中撤回条件），Sprint 8 启动前要先评估是否同时支持 r1 形态——本 ADR 默认 r1 已删，Sprint 8 真启动时再确认。

### D-8：QA 验收测试设计

QA Deliverable "缓存命中率加一致性测试"具体怎么测：

**命中率测试**

- 输入：anshi 5 题 batch
- 流程：清空所有缓存 → 第一次跑完整记录每题每层是否走缓存（应该全 miss）→ 第二次跑同 batch 不清缓存（应该 L2 大量命中、L1 命中率视题型分布、L3 全命中）
- 指标：每层命中率、第二次跑的端到端 P50 加速比
- 验收：L1 ≥ 30%、L2 ≥ 50%、L3 = 100%、第二次跑总耗时 ≤ 第一次 30%

**一致性测试**

- 输入：anshi 同一题跑 3 次（不清缓存）
- 验证：第 1 次填缓存，第 2-3 次返同样答案
- 边界：在 LLM 调用前主动 patch 一次让 provider 返不同内容，验证缓存条目以第一次为准（不是每次重新写）

**性能回归测试**

- benchmark 脚本（Sprint 5 已落 commit `078643c`）加一个 `cache_hit_rate` 维度的产出
- 跑两次：cold start（清缓存） vs warm（不清）；两次端到端 P50 都记录

**非确定性边界测试**

- 测 LLM provider 返 `ContentFiltered`（内容审查）时缓存行为——不缓存失败结果（要让重试能跑），只缓存成功结果
- 测 LLM provider 返 `length`（输出截断）时——同上不缓存

### D-9：Open Questions

至少留 5 条给 Sprint 8 启动时讨论：

1. **LLM 调用缓存的非确定性边界**：provider 端内容审查触发 / temperature 采样 / provider routing 都让"同 input 同 output"假设打折。缓存有效性的边界要按 provider 实测——MiniMax / DeepSeek / Claude 三家分别的命中后准确率要在 Sprint 8 启动前过一遍 audit。如果某 provider 命中后准确率 < 95%，对该 provider 禁用 L2
2. **缓存与 streaming 的兼容性**：当前 SSE 流式响应是边算边推；命中缓存时能不能"一次性返完"还是要"重新切片成 chunk 模拟流式"。前者改前端 SSE 处理；后者缓存层要存原始 chunk 序列。推荐前者——重复问体验从"慢慢出字"变"瞬间出完"是正向产品反馈
3. **缓存大小上限策略（LRU / LFU / TTL only）**：L1 推荐 LRU + 上限 1000 条；L2 推荐 LRU + TTL 双约束 + 上限按 disk 占用（默认 100MB）；L3 进程内 LRU 5 本 + 磁盘无上限。LFU 看似更优但需要每次访问写计数，对 L2 SQLite 多一次 write，得不偿失
4. **多用户场景下缓存的隔离与共享**：当前 BookScope 单用户工具假设，缓存全局共享没问题。如果未来上线变多用户工具，L1 / L2 是否要按用户隔离？倾向"按 book_id 共享、不按用户隔离"——因为同书的语义搜索结果跟用户无关。L2 LLM 调用缓存按 prompt + tool + model 隔离已经够，不需要再加用户维度
5. **缓存命中时是否照样跑 reviewer**：reviewer 评分本身是输出质量的一部分。命中 L2 时直接返历史答案，reviewer 已经评过——是否要复用历史 reviewer 评分？倾向"复用 reviewer 评分并标 cached"——这避免重复打分；但 case-study / batch 归档要区分"原 reviewer 评分 vs cached reviewer 评分"
6. **缓存 hit 时的 LoopTrace 形态**：命中 L2 时实际没跑 loop，trace 怎么记？倾向新增 `LoopTrace.cache_hit_layer: Literal["L1", "L2", "L3"] | None` 字段，case-study 分析时可按这个字段过滤
7. **L2 SQLite 在 BookScope 部署形态下的并发安全**：FastAPI 多 worker 部署时多个进程写同一个 SQLite 文件需 WAL 模式 + 文件锁。Sprint 8 落地前要在 ROADMAP 的部署形态（单进程 dev / 多进程 prod）下分别测一次

## Consequences / 后果

### 好

- 单题 P50 从 30-60 秒降到 < 30 秒，重复问 < 3 秒，冷启动 < 5 秒——三项产品级指标改善
- BYOK 用户的 LLM token 成本随命中率线性下降，重复问基本不烧 token
- 跟 ADR-005 session 持久化叠加，作者 dogfood anshi 体验从"每次切回慢半天"变成"打开即用"
- 缓存层独立于 prompt / tool / loop，本 ADR 落地不需要改业务逻辑——纯叠加

### 弊

- **三层叠加的复杂度**：L1 / L2 / L3 各自有 invalidate 时机、版本字段、命中率监控。debug 时"为什么这题没命中" / "为什么命中了但答错了"会比无缓存时难定位
- **SQLite 引入持久化责任**：L2 缓存文件本身要管 schema migration、文件损坏恢复、磁盘占用监控。ADR-005 JSON 文件存储是 schemaless，L2 SQLite 是 schema 化的，多一层 ops 负担
- **缓存返过期数据风险**：缓存 versioning 字段（D-4）漏改一处就有可能让用户拿到 stale 答案。Sprint 8 落地后 case-study / batch 数据要标注是否走了缓存——避免缓存数据混进研究记录
- **多 worker 部署时 L2 并发**：见 Open Q-7，需在 ROADMAP 部署形态下补测一轮

### 撤回条件

任一条命中重开本 ADR：

- L2 命中后准确率 < 95%（用户拿到错答案的频率超过阈值）
- L2 SQLite 在 BookScope 多 worker 形态下出现锁竞争或文件损坏
- 三层叠加后 P50 仍 > 40 秒——说明瓶颈不在缓存层（可能在 LLM 调用本身或 ingest），Sprint 8 方向要换
- BYOK 用户报告 cache 让 token 消耗看似下降但实际产品体验下降（如答案陈旧、缺少最新 prompt 优化效果）

## Alternatives / 备选方案

### A-1：不做缓存层，靠 prompt 优化加 model 选型

- 利：0 维护成本
- 弊：触不到"重复问 < 3 秒"目标——LLM 调用本身就要 5-30 秒；冷启动 < 5 秒也做不到
- 评：不接受。Sprint 5 已经压榨了工具并行加题型路由，下一刀不靠缓存就没大头空间

### A-2：只做 L2（LLM 调用缓存），不做 L1 / L3

- 利：实现量小，单层收益最大（L2 加速量 5-60 秒）
- 弊：冷启动延迟没救（L3 才管这事）；L1 的小加速量在深题多轮叠加下也能切 30-100 秒
- 评：可作为 Sprint 8 第一波 deliverable，但完整 Sprint 8 三个验收指标都达成需要三层都做

### A-3：用第三方缓存中间件（如 langcache / GPTCache）

- 利：现成轮子，不用自己实现 key 算法
- 弊：多一层依赖；GPTCache 等假设 OpenAI 协议形态，BookScope 多 provider 形态可能踩坑；命中率 / 一致性测试还是要自己写
- 评：不接受。本 ADR 的复杂度可控，自己实现能精确控制 key 算法（D-3）和失效策略（D-4）

### A-4：用 Anthropic prompt caching / OpenAI prompt caching 等 provider 端缓存

- 利：完全 provider 端，BookScope 0 代码
- 弊：每家 provider 接口不一样，BookScope 多 provider 形态下要分别接；BYOK 用户用国内 provider 时可能没有这种 feature；只优化 prompt 部分不优化 tool result 部分
- 评：可以叠加在 L2 之上（provider 支持时启用），但不能替代本 ADR 的 L2

## Migration Plan / 迁移方案

Sprint 8 时间窗 2026-08-07 至 2026-08-20，按 ROADMAP 列的 4 条 deliverable 排波：

| 波次 | 工作 | Deliverable | 估时 |
|------|------|-------------|------|
| W1 | L1 `search_chunks` 缓存 | in-memory LRU + key 算法 + 单测 | 1 agent 天 |
| W2 | L2 LLM 调用缓存 | SQLite + D-3 key 算法 + versioning 字段 + 单测 | 2 agent 天 |
| W3 | L3 book 预热缓存 | 进程内 LRU + 磁盘双层 + ADR-005 集成 | 3 agent 天 |
| W4 | QA 命中率 / 一致性测试 | benchmark 脚本扩展 + 验收报告 | 1 agent 天 |
| W5 | OPS 监控 dashboard | 每层命中率 / 大小 / 失效次数指标 | 1 agent 天 |

合计 8 agent 天，Sprint 8 两周（10 工作日）有 2 天 buffer 处理 Open Questions 的实测。

### 数据约定

- benchmark 跑出的 batch 归档加 `cache_layer_hits: {L1: int, L2: int, L3: int}` 字段
- case-study 章节涉及性能数据时显式标注"无缓存 baseline" / "缓存预热后" / "缓存冷启动"三种状态
- ROADMAP 不改，本 ADR 是 prep doc 不动 timeline

### 测试范围

- `tests/agent/` 下新增 `tests/agent/cache/` 子目录，三层各自的单测
- 集成测试：fast_path 与 agent_loop 各跑一次"清缓存 → 跑 → 不清缓存 → 跑"对比
- benchmark 脚本（Sprint 5 commit `078643c`）扩展 `cache_hit_rate` 维度

## Open Questions / 待定

见 D-9，已展开 7 条。Sprint 8 启动时由 PE / RE / BE 联合过一遍，逐条转 Decision 或留 Backlog。

## References

- ADR-005：book session 持久化（L3 缓存的磁盘层基础）
- ADR-007：r2 OpenAI function calling 主格式（L2 缓存 key 算法的 messages 形态依据）
- `bookscope/agent/loop_r2.py`：r2 主循环，L2 缓存接入点
- `bookscope/agent/fast_path.py`：通识题快路径，L1 / L2 在此叠加
- `bookscope/agent/tools/search_chunks.py`：L1 缓存包装目标
- `bookscope/store/repository.py`：ADR-005 JSON 持久化，L3 磁盘层复用
- Sprint 5 commit `74bddd5`：工具并行（性能第一刀）
- Sprint 5 commit `fc10b20` / `0f36fb2`：fast_path 题型路由
- Sprint 5 commit `078643c`：benchmark 脚本基线
- memory `feedback_baseline_variance_first.md`：撤回阈值要靠 std 不靠单次跑
- memory `feedback_performance_first_class.md`：BookScope 延迟是产品级问题
- memory `feedback_byok.md`：BYOK 原则下不假设用户有 Redis
- memory `feedback_no_gpu.md`：缓存层不引入 GPU 依赖

## 作者签字

**已批准 · 2026-05-15 作者明示签字**（与上方 Status 段一致；早先这里还留着"待签"是回写没跟上，已修正）。

签字栏：

```
日期：2026-05-15
作者签字：moyu-good
范围：全部 W1-W5（作者"全部签字！"一次性批，提前两月启动）
备注：本 ADR 原为 prep doc，签字后 Sprint 8 即推；L1 已落地 commit 2c2428e。
```
