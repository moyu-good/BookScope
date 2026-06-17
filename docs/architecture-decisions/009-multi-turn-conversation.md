# ADR-009：多轮对话——从"每问一次全量重启"到"连续追问"

## Status

**已批准 + Phase 1a 已落地**（作者口头批准 2026-06-11"全部同意，开始"；方案 C 分两阶段。Phase 1a = 对话骨架 + 上轮答案注入，已实现 915 测试全绿；Phase 1b 指代消解 / Phase 2 登记表预热待续）

- 代际：r2-agent-loop
- 起草：副管理（RE 执笔）
- 创建日期：2026-06-10
- 来源：设计缺口评审缺口 10 + WP6（`docs/internal/design/2026-06-10-design-gap-review.md`）——这是 8 份 ADR 里从未讨论过的产品形态盲区，不是"设计了没做"，是"没意识到要设计"
- 决策摘要：给 BookScope 加多轮对话能力。三个候选方案（A 完整 messages 续写 / B 上轮答案进 system 附录 / C 证据登记表跨轮预热 + 旧轮观察压缩）。副管理推荐 **C，分两阶段落地，API schema 与持久化一步按 C 设计**——Phase 1 先把对话骨架（conversation_id + 轮次摘要 + 指代消解）立起来，Phase 2 补登记表预热与 chunk_id 重拉
- 本 ADR 是设计文档，签字前不动任何 runtime 代码。建议 Sprint 5（6/26-7/9）窗口实现

## Context / 背景

### 创作者真实的提问方式是连续的

作者问自己稿子的方式不是一锤子买卖，是一条追问链：

> "这本书的节奏是不是前密后疏？" → "具体哪几章最稀？" → "第 40 章后加个事件行不行？"

第二问的"哪几章"指着第一问的结论，第三问的"加个事件"指着第二问点出的稀疏段。这是创作者跟第一读者对话的自然形态——BookScope 的项目目的第 1 条就是做这个第一读者。

### 当前实现：每一问都从零开始

代码现状三处证据：

1. **`bookscope/agent/loop_r2.py:339`**：`query()` 每次新建 `messages` 数组，只装本次题面 + citation 格式提示。上一问跑出来的全部上下文——LLM 的推理轨迹、tool 拉回的原文——进不来。
2. **`bookscope/api/schemas.py:34`**：`AgentAskRequest` 没有任何历史字段。最接近的先例是 `previous_review`（schemas.py:80，重答按钮把上次 reviewer 批评带回 generator），但那是"同一题重答"，不是"下一题接着问"。
3. **ADR-005 session 持久化**：JSON per session 存的是书的索引工件（book_text / chunks / kg / vector_index），对话一个字没存。"session"在 BookScope 里至今指"一本书"，不指"一场对话"。

后果具体到那条追问链上：

- **上轮证据全丢**。第一问深题跑 5-10 次 tool 调用、拉回 30-80KB 原文（ADR-008 D-3 实测"messages 数组在多轮 agent loop 下能堆到 50KB+"），答完即弃。第二问把其中大半原文重新检索一遍，BYOK 用户的 token 钱重新烧一遍，90-180 秒的深题耗时重新等一遍。
- **指代无法消解**。"具体哪几章最稀？"单独丢进系统，`question_processor` 不知道"稀"指节奏，检索层拿这种残句去跑 BM25 + 向量搜索基本是掷骰子。
- **第三问这种跨轮综合问根本没法答**。"第 40 章后加个事件行不行"需要同时握着第一问的节奏结论和第二问的稀疏章列表。

### 已有的可复用资产

这次不是白手起家，三块现成资产直接决定了方案 C 的形态：

- **WP1 证据登记表**（`loop_r2.py:324`）：本次 query 内所有 tool 返回的原文按 chunk_id 登记成 `{chunk_id: {chapter, text}}`，已经在给 citation 校验（`verify_citations`）和 partial_evidence 兜底（WP5a）供货。它就是"本轮查到了哪些原文"的天然台账——多轮复用只差"跨 query 存活"一步。
- **ADR-008 L1 缓存**：`search_chunks` 结果缓存已落地（commit `2c2428e`），追问重复检索同样的 query 时本来就会命中。但 L1 只省检索耗时（100-500ms/次），省不了 LLM 重新读这些 chunk 的 token。
- **业界已验证的模式**（`docs/internal/research-notes/002-oss-benchmark-survey.md` 第三节）：smolagents 的 step_callbacks 把旧轮次检索到的长 chunk 压成"一行摘要 + chunk id"，要引用时凭 id 重拉；Anthropic 多代理系统在上下文将满时把计划写到外部 memory，再起新上下文接续。两家走的是同一条路——**旧观察不全量保真，压缩成可重拉的指针**。

## Problem / 问题

### 问题 1：证据丢弃直接跟成本与延迟目标打架

深题单轮 90-180 秒、几万 token。追问链上第二问与第一问的证据重叠度极高（"哪几章最稀"要的恰恰是第一问已经拉过的节奏证据），但当前架构让重叠部分全额重付。`feedback_performance_first_class.md`：延迟是产品级问题——追问比首问更该快，现在追问跟首问一样慢。

### 问题 2：指代消解断裂让追问的答案质量不可信

带指代的残句进检索层，检索失准 → 证据错 → 答案错。这打的是框架主张②"没有原文证据的结论一律不输出"——不是不输出，是输出了但证据找歪了。

### 问题 3：对话历史没有归宿

ADR-005 的 session 目录里没有对话的位置；trace 也不记"这是哪场对话的第几轮"。case-study 想分析"多轮追问的质量衰减曲线"时连数据都没有——对一个把案例研究当第一交付物的项目，这是测量仪器缺口（设计评审"测量仪器先于定义"模式的又一例）。

## Decision / 决策

### 三个候选方案

#### 方案 A：完整 messages 续写

**机制**：上一轮 query 结束时的完整 `messages` 数组（含全部 assistant tool_calls 与 role=tool 消息）保留，下一问 append 上去继续跑。LLM 看到的就是一场没断过的对话。

**context 增长曲线**：单轮深题终态 30-80KB 字符（≈ 3-7 万 token，中文混 JSON 按 0.7-1 token/字符估）。第 2 问 input 从上轮终态起步，第 3 问累计 100-150KB ≈ 8-12 万 token——**第 3-4 问就顶到 DeepSeek 128k context 上限**。且每一问都要把之前所有轮的 token 重新作为 input 付一遍钱，成本是平方级累积。

**更糟的是它的"全保真"承诺是假的**：`loop_shared.py:98` 的 `CONTEXT_TRUNCATE_KEEP_LAST = 6` 在 context 超限时配对丢弃旧的 tool_calls/tool 消息组（`_truncate_messages_r2`，loop_r2.py:1075）——方案 A 跑到第 3 问触发截断，最先被砍的恰恰是第 1 问的证据。保真承诺被现有截断机制自己打破，剩下的只有成本。

**工程量**：最小，约 1.5 agent 天（schema 加历史字段 + replay）。

**对 API schema 的影响**：要么 FE 每次回传完整 messages（单请求 100KB+ 的 payload，丑），要么服务端按 conversation_id 存完整 messages（存储随轮数膨胀）。

**对 session 持久化的影响**：对话文件每轮增长几十 KB，十轮就是半 MB 一场对话。

#### 方案 B：上轮 answer + citations 进 system 附录

**机制**：每轮只把上一轮的最终答案（500-1500 字）和 citations（3-6 条 × 200 字 snippet）拼成一段"前情提要"注入 system prompt 附录，messages 仍每轮从零建。复用 `previous_review` 的注入套路（routes 层拼 system 附录，格式异常 fallback 跳过不崩）。

**context 增长曲线**：每轮新增 2-3KB 字符，3 轮累计 < 10KB ≈ 5-8k token。线性、平缓、永远不会顶 context。

**致命短板**：丢掉了 tool 证据。上轮 agent 拉回 30-80KB 原文，最终 citations 只引用了其中 3-6 条 snippet——**没被引用但相关的原文（往往是"哪几章最稀"真正需要的那批节奏数据）全丢**。第二问还是要重新检索，省的只是"上轮结论"这一小块。指代消解能靠前情提要部分解决，证据复用基本为零。

**工程量**：约 2 agent 天。

**对 API schema 的影响**：最轻——FE 回传上轮 answer + citations（几 KB），或服务端按 conversation_id 存轮次摘要。

**对 session 持久化的影响**：每轮几 KB 的摘要，对话文件千字节级。

#### 方案 C：证据登记表跨轮预热 + 旧轮观察压缩（smolagents 模式）

**机制**：三件事。

1. **登记表跨轮存活**。WP1 的 `evidence_registry` 从"只活在单次 query 作用域"（loop_r2.py:319-324 注释明示的当前设计）升级为挂在 conversation 上：本轮 tool 拉回的原文照常登记，query 结束后登记表不弃，下一轮带着进来。
2. **旧轮观察压缩进 context**。下一轮注入 system 附录的内容是：每条历史轮的答案 + 该轮登记证据的压缩形态——`chunk_id + 章号 + 前 100 字摘要`一行一条（smolagents step_callbacks 同款）。LLM 看得见"上轮查过哪些原文、各讲什么"，但不付全文的 token。
3. **chunk_id 凭证重拉**。新增一个轻量 tool `fetch_chunks(chunk_ids)`：LLM 要细看某条压缩证据时凭 chunk_id 直接取全文——从 session store 的 chunks（ADR-005 已持久化）按 id 取，零检索成本、确定性命中。比重新 search_chunks 便宜且准。

**context 增长曲线**：每轮新增 = 答案摘要 + 本轮新登记 chunk 的压缩条目（10-30 条 × ~120 字符 ≈ 1.5-4KB）。关键性质：**登记表按 chunk_id 去重，追问命中同样原文时增量趋零**——而追问链恰恰是高重叠场景。3 轮累计约 10-18KB ≈ 8-15k token，且可以硬 cap（登记表压缩条目上限 60 条 ≈ 8KB，超出按最近访问淘汰）。增长是次线性 + 有界的。

**工程量**：约 5 agent 天（WP6 原估）。拆开看：conversation 骨架 + 摘要注入 ~2.5 天，登记表预热 + fetch_chunks tool + 压缩格式 ~2.5 天。

**对 API schema 的影响**：`AgentAskRequest` 加一个 `conversation_id: str | None`（None = 新对话），响应回显。历史与登记表全在服务端，FE 不搬运证据。

**对 session 持久化的影响**：最优雅的一点——登记表条目本质是指向已持久化 chunk 的**指针**。落盘形态只需 chunk_id 列表 + 各轮答案摘要，对话文件千字节级；重启后凭 chunk_id 从 session store 重建登记表，秒级。

### 三方案 context 增长对比（3 轮深题追问链）

| | 第 1 轮 input 增量 | 第 3 轮累计携带 | 10 轮后 | 截断风险 | 证据复用 |
|---|---|---|---|---|---|
| A 完整续写 | 0 | 100-150KB（8-12 万 token） | 早已爆 context | 第 3-4 轮触发，**最老的证据最先被砍** | 理论全量，实际被截断打破 |
| B 摘要附录 | 0 | < 10KB（5-8k token） | ~30KB，无忧 | 无 | 仅 citations，tool 证据全丢 |
| C 登记表压缩 | 0 | 10-18KB（8-15k token） | cap 在 ~8KB 压缩条目 + 摘要 | 无（硬上限） | 压缩可见 + chunk_id 全文可重拉 |

### 副管理推荐：C，分两阶段，schema 一步到位

独立评估后推荐 **C**，与设计评审的倾向一致，但加一条执行策略：**分阶段 B→C 落地，API schema 与持久化设计从第一天就按 C 的形态定**。理由四条：

1. **B 是 C 的退化形态，不是独立岔路**。C 的轮次摘要注入（答案 + 压缩证据条目）天然包含 B 的全部 payload（答案 + citations）。先实现 Phase 1（= B 的能力 + conversation 骨架 + 指代消解），再补 Phase 2（登记表预热 + fetch_chunks），每一步都可独立验收，且不存在"做完 B 再迁移到 C"的二次 schema 改造——`conversation_id` 服务端态从第一天就是 C 的设计。
2. **A 不可救**。增长曲线是平方级成本 + 第 3-4 轮爆 context，而且它依赖的"全保真"被 `_truncate_messages_r2` 现有行为否定。唯一优点工程量小，但 1.5 天省出来的代价是产品上限锁死在 2-3 轮——追问链的典型长度恰恰是 3 轮起步。
3. **C 复用了三块已落地资产**（WP1 登记表、ADR-005 chunk 持久化、ADR-008 L1 缓存），新造的轮子只有 fetch_chunks 一个 tool 和压缩格式一份。5 agent 天的估算里没有高风险段。
4. **C 的形态对 case-study 最有利**：登记表跨轮命中率、压缩证据被重拉的比例、追问链质量衰减曲线——全是可量化、可发表的数据点，正是研究笔记 002 第三节两个业界模式在"整本书对话"场景下的首次实测。

### D-1：对话标识与 API schema

- `AgentAskRequest` 新增 `conversation_id: str | None = None`。None = 开新对话，服务端生成 id；非 None = 续上。`book_session_id` 照旧必填——对话从属于书。
- `AgentAskResponse` 新增 `conversation_id: str` 回显 + `turn_index: int`（本轮是第几问，从 1 起）。
- `previous_review`（重答）与 `conversation_id`（追问）语义正交，并存：重答是"同一轮重跑"，turn_index 不增；追问 turn_index 递增。
- `LoopTrace` 新增 `conversation_id: str | None` 与 `turn_index: int`——多轮质量分析的测量仪器，跟 WP0 给 trace 加 `prompt_version` 是同一条纪律（测量仪器先于实验）。

### D-2：指代消解放 question_processor，不靠历史自带

两个候选：把消解责任全交给主 loop 的 LLM（反正历史摘要在 system 附录里）；或在 `question_processor` 做显式的"独立化改写"。

**倾向后者**，理由是一条硬逻辑：**检索层看不见 system 附录**。主 LLM 靠历史能读懂"哪几章最稀"，但它发出的 search_chunks query、fast_path 的路由判断、BM25 的分词输入，拿到的还是残句。`question_processor` 本来就是"长题先整理再进 loop"的预处理引擎（作者原话："字数越长你就需要整理问题，需要一个问题的处理引擎"），给它喂上几轮的 Q/A 摘要、让它先把追问改写成独立可查的完整问题（"第 12-18 章节奏最稀"级别的自包含表述），是它职责的自然延伸。改写后的独立问题同时喂给检索、路由、登记表压缩条目的相关性排序——一处改写，三处受益。

兜底原则照旧：processor 挂了就 fallback 原题进 loop，不阻断主流程。多轮场景下 fallback 的代价从"没拆题"升级为"指代没消解、答案可能跑偏"，这点要在 FE 给降级提示（Open Q-5）。

### D-3：对话持久化——ADR-005 session 目录下的独立文件，不进 metadata.json

```text
data/sessions/<session_id>/
  metadata.json            # 不动
  book_text.json / chunks.json / kg.json / vector_index/   # 不动
  conversations/
    <conversation_id>.json # 新增：{turns: [{turn_index, question, rewritten_question,
                           #   answer, citations, evidence_chunk_ids, created_at}],
                           #   registry_chunk_ids: [...]}
```

**倾向独立文件而非塞进 metadata.json 或另起顶层目录**，理由：

- 书的工件（book_text / chunks / kg）是 ingest 一次性产物，对话是每轮增长的日志——可变与不可变分开存，save 语义才干净（追问一轮不该重写整个 session）。
- 对话从属于书（追问链离开这本书没有意义），放 session 目录下而不是顶层 `data/conversations/`，删书即删对话，生命周期自然绑定。
- 登记表落盘只存 `chunk_ids`（指针），全文从同目录 chunks.json 重建——这是方案 C 持久化便宜的来源。
- 与 ADR-005 "JSON-on-disk、人眼可读、rsync 即备份"的既有习惯一致。

### D-4：验收标准草案

QA 验收四件套（数字是草案，实测后 Sprint 5 内可调，调整要记 STATE）：

1. **3 轮追问链场景测试**：anshi 上设计 3 组追问链脚本（每组 3 轮：主问 → 指代追问 → 跨轮综合问，原型即"节奏前密后疏 → 哪几章最稀 → 第 40 章后加事件行不行"）。判定：第 2/3 轮答案的 reviewer 评分不低于**同题人工独立化改写版的单轮 baseline 均分 − 1 std**。baseline 先跑 3 次求 std 再比（`feedback_baseline_variance_first.md`，不拿单次跑当 ground truth）。
2. **context token 增长上限**：第 N 轮 input_tokens ≤ 单轮 baseline 均值 + 15k；连续 10 轮追问任意一轮 input 不超过 provider context 上限的 60%。两个数字都要进 trace 可观测。
3. **指代消解命中**：10 道带指代的追问题，question_processor 改写后人工判"独立化正确"（不看历史也能理解且语义不变）≥ 9/10。检索层命中率（golden chunk 进 top-k）依赖 WP2 golden set——golden set 没好之前先只验改写正确性，golden set 落地后补检索命中 ≥ 8/10。
4. **零回归**：`conversation_id` 缺省时所有行为与现状逐字段一致，现有测试套全绿；登记表跨轮逻辑不改变单轮 query 的 verify_citations / partial_evidence 行为。

## Consequences / 后果

### 好

- 追问链从"三次全量重启"变成"一场对话"——创作者真实使用形态第一次被产品形态接住，项目目的第 1 条的兑现。
- 追问的延迟与 token 成本随证据重叠度下降：第 2 问起登记表预热 + L1 缓存双层命中，重叠证据不重付。
- 对话持久化 + trace 字段让"多轮质量衰减"成为可测量对象，case-study 多一整章可写的实测数据。
- fetch_chunks tool 顺手填了一个通用缺口：citation 校验失败时"凭 chunk_id 核对原文"也能用它（WP1 后续受益）。

### 弊

- **conversation 服务端态是新的复杂度**：BookScope 至今所有请求无状态（book session 是只读索引），对话引入第一个跨请求可变状态。并发同一 conversation 的两问、进程重启时登记表重建、对话文件损坏，都是新的故障面。
- **压缩摘要可能误导**：100 字摘要丢了上下文，LLM 可能基于摘要下结论而懒得重拉全文——prompt 要明示"压缩条目只可用于定位，引用前必须 fetch_chunks 取全文"，这条跟缺口 1（citation 真实性）同根，执法靠 WP1 的 verify_citations 兜住。
- **question_processor 从锦上添花变关键路径**：单轮场景它挂了无所谓，多轮场景它挂了指代消解就没了。fallback 路径的产品体验要 FE 配套（降级提示）。
- **5 agent 天是三方案里最贵的**，且 Phase 2 依赖 Phase 1 验收通过——Sprint 5 排期要留串行余量。

### 撤回条件

任一条命中重开本 ADR：

- 3 轮追问链测试中第 2/3 轮 reviewer 评分系统性低于单轮独立化 baseline 1 std 以上（多轮形态反而伤质量）
- 登记表压缩条目导致 LLM 普遍跳过 fetch_chunks 直接引用摘要，unverified citation 比例较单轮明显上升（与 WP1 观测数据比）
- conversation 服务端态在作者 dogfood 中出现对话串台 / 丢轮等状态管理事故两次以上

## Alternatives / 备选方案

（A / B 两个候选已在 Decision 节展开，此处是方案空间之外被排除的路。）

### A-1：不做多轮，靠 FE 提示用户"把问题问完整"

- 利：0 工程量
- 弊：把系统的活甩给用户——跟第 35 轮"换题写法是甩锅"被锤的是同一类错误（`feedback_fe_error_coverage.md`）。创作者凭什么要学会"自带上下文地提问"？
- 评：不接受

### A-2：FE 本地拼接历史进 question 文本

- 利：服务端零改动
- 弊：历史以纯文本塞进 2000 字上限的 question 字段，两轮就顶满；证据复用为零；指代消解质量取决于 FE 拼接模板——把架构问题伪装成文案问题
- 评：不接受

### A-3：引第三方记忆框架（mem0 / LangGraph checkpointer 等）

- 利：现成的对话状态管理
- 弊：BookScope 的对话状态核心是**证据登记表**这个领域特有结构，通用记忆框架管的是 messages 级状态，登记表 + chunk_id 重拉还得自己做——引了依赖只省最薄的一层；与 ADR-003 / ADR-008 两次驳回第三方中间件的理由同构
- 评：不接受

## Migration Plan / 迁移方案

建议挂 Sprint 5（6/26-7/9），前置条件：本 ADR 作者签字。

| 阶段 | 工作 | Deliverable | 估时 |
|------|------|-------------|------|
| Phase 1 | conversation 骨架 | `conversation_id` schema + 服务端对话态 + 轮次摘要 system 附录注入 + question_processor 指代消解改写 + D-3 持久化 + trace 字段 | 2.5 agent 天 |
| Phase 1 验收 | QA 跑 D-4 第 1/3/4 条（此时证据复用未开，第 2 条只记录不判定） | 验收报告 | 0.5 agent 天 |
| Phase 2 | 证据登记表跨轮 | 登记表挂 conversation + 压缩条目格式 + `fetch_chunks` tool + prompt 配套段（PE） | 2.5 agent 天 |
| Phase 2 验收 | QA 跑 D-4 全四条 + 登记表命中率观测 | 验收报告 + 数据归档 `docs/internal/experiments/data/` | 0.5 agent 天 |

- Phase 1 验收不过则 Phase 2 不启动，对话骨架本身（B 级能力）仍可保留——这是"分阶段 B→C"策略的止损点。
- prompt 改动（压缩条目使用规则、fetch_chunks 指引）走 PE，且要在 WP0 修好 prompt 版本链之后做——否则又是改了不知道生效没生效。
- batch / 实验数据元数据新增 `conversation_id` / `turn_index` 字段，单轮数据两字段为空，向后兼容。

## Open Questions / 待定

1. **fast_path 与多轮的关系**：追问还能走 fast_path 吗？路由判断看不见历史会把"哪几章最稀"误判成通识题。Phase 1 先简单处理——带 `conversation_id` 的请求一律走 agent_loop；fast_path 的多轮适配（路由时喂改写后的独立问题）留 Phase 2 后评估
2. **对话长度上限与折叠**：超过 N 轮（暂定 10）后最老的轮次摘要是否二次压缩成"一段话前情"？Anthropic 外部 memory 模式的接续做法可参考，先观测 dogfood 里真实追问链长度分布再定
3. **reviewer 在多轮下评什么**：当前 rubric 按单轮答案评。第 3 轮这种跨轮综合答案，evidence_density 维度该不该把前轮已建立的证据算进来？需要 PE 评估 rubric 是否加多轮说明段
4. **并发安全**：同一 conversation_id 并发两问怎么处理？倾向简单加锁拒绝（409），单用户场景够用——但要显式写，不能靠运气
5. **processor fallback 的降级可见性**：指代消解失败回退原题时，FE 要不要提示"本轮按原题理解，可能没接住上文"？倾向要——这是"兜底路径静默劣化"模式（设计评审三个结构性模式之二）的预防
6. **登记表 cap 的淘汰策略**：60 条上限满了之后按最近访问淘汰还是按轮次淘汰？倾向最近访问（追问链常回头引用第 1 轮的证据），实测后定
7. **多轮对话与 L2 LLM 缓存（ADR-008）的 key 兼容**：system 附录每轮变化会让 L2 几乎不命中——多轮场景 L2 命中率预期要单独建档，避免污染 ADR-008 D-5 的撤回阈值判定

## References

- `docs/internal/design/2026-06-10-design-gap-review.md`：缺口 10 + WP6（本 ADR 直接来源）
- `docs/internal/research-notes/002-oss-benchmark-survey.md` 第三节：smolagents step_callbacks 旧观察压缩、Anthropic 外部 memory 接续模式
- ADR-005：book session 持久化（D-3 目录结构的宿主；chunk 持久化是 fetch_chunks 的供货方）
- ADR-007：r2 OpenAI function calling（messages 形态与 `_truncate_messages_r2` 配对截断语义）
- ADR-008：三层缓存（L1 与登记表预热的叠加关系；Open Q-7 的 L2 key 兼容问题）
- `bookscope/api/schemas.py:34`：AgentAskRequest 现状（无历史字段）；`:80` previous_review 注入先例
- `bookscope/agent/loop_r2.py:324`：WP1 证据登记表；`:339` messages 每次从零建；`:1008` `_register_evidence`；`:1075` `_truncate_messages_r2`
- `bookscope/agent/question_processor.py`：问题处理引擎（D-2 指代消解的宿主）
- `bookscope/agent/_internal/loop_shared.py:98`：`CONTEXT_TRUNCATE_KEEP_LAST = 6`（方案 A 保真承诺的反证）
- memory `feedback_baseline_variance_first.md`：验收判定先求 baseline std
- memory `feedback_performance_first_class.md`：延迟是产品级问题
- memory `feedback_fe_error_coverage.md`：兜底不甩锅给用户
- memory `feedback_user_not_only_author.md`：目标用户是任何长文本创作者，追问形态有普适性

## 作者签字

**待签**。本 ADR 是产品形态级决策（引入第一个跨请求可变状态 + API schema 变更 + 新 tool），按副管理模式 escalation 规则必须作者签字后实施。签字前 BE / PE / QA 不动 runtime 代码与 prompt。

签字栏：

```
日期：2026-06-11
作者签字：moyu-good（口头批准，副管理代录——先例同 ADR-006）
方案选择：C 分两阶段（副管理推荐方案，作者全盘同意）
Sprint 5 排期确认：是（Phase 1 即刻启动，不必等窗口）
备注：作者原话"全部同意，开始"。
```
