# 附录 A · ADR 索引

> **状态**：草稿 · 作者未定稿
> 用途：案例研究读者从章节文本回查决策原文的快速索引
> 维护：ADR 文件每次修订后同步本附录摘要段位
> 创建：2026-05-15

---

读案例研究正文时，章节里频繁出现"ADR-007 决定切到 OpenAI function calling"、"按 ADR-006 删掉本地 reranker"这类引用。这些 ADR 自己就是 BookScope 工程路线的关节点，原文都躺在 `docs/architecture-decisions/`。附录 A 把 9 份 ADR 串成一份带摘要的索引，读者从章节回查时不用一份份点开看头。

ADR 之间不是各自独立的决策，而是有几条主线在演化：

- **provider 选择三步走**：ADR-002 v1 锁 Anthropic → v2 翻成国内优先 DeepSeek + Anthropic 备选 → ADR-007 把内部协议从 Anthropic tool_use 翻到 OpenAI function calling
- **协议抽象逐步深化**：ADR-003 定 `LLMClient` Protocol → ADR-007 把内部主格式翻面 → ADR-008 在 r2 单形态稳定后加缓存层
- **硬约束反向压出的下线**：ADR-006 因为"禁 GPU"硬约束被实测违反，反过来把本地 cross-encoder 与 sentence-transformers 全部 API 化

---

## ADR-001 · r1 查询时智能代理的三个核心 tool 接口规范

- **状态**：已批准（作者口头，2026-04-20）
- **代际**：r1-agent-loop

r0 三阶段流水线把 LLM 算力全烧在 ingest 阶段，书被"冻干"成静态分析产物——这是 r1 代际启动时被锤破的根因。ADR-001 给 r1 agent 圈定了能调的全部工具：`search_chunks` / `get_chapter_range` / `list_characters_in_chapter`，多一不加少一不减。所有工具返回必须带原文 `text` 字段，章节范围与角色过滤作为一等公民参数。这份契约是后续整个 r1 / r2 工程的地基——loop 实现、实验设计、prompt 工程、Sprint 5 的题型路由全部在这三个工具上展开。

附录正文里把这套设计完整描述的章节是 chapter-01（r1 启动与 API-first 翻转）；chapter-02（查询时装配）描述了三个工具背后的 r0 数据层是怎么被"降级"成 backend 的。

## ADR-002 v1 → v2 · r1 agent loop 的技术实现选型

- **状态**：v1 作废 / v2 已批准（作者口头，2026-04-20）
- **代际**：r1-agent-loop
- **关联 commit**：`a48c86e`（ADR-002 v2 + ADR-003 + adapter 层落地）

ADR-002 是 BookScope 早期最干净的一次方向翻转。v1 上午定稿"锁定 Claude Sonnet 4.6 原生 tool use + 自建 loop"，下午作者补一条不变量"LLM provider 国内优先"，v1 直接撞墙作废。v2 改成 DeepSeek function calling 首选 + Anthropic 备选 + provider-agnostic adapter 层，AgentLoop 主循环本体零改动（已有 128 条单测继续绿）。

v2 留了一条显式技术债：当时为了不动 loop 主体，让 `DeepSeekAdapter` 做 OpenAI function calling 到 Anthropic tool_use 的双向翻译。这条技术债的还款单后来由 ADR-007 接走。

附录正文里 chapter-01 写了这次翻转——为什么 v1 写完几小时就被作废，"国内优先"这条不变量怎么进的 NORTH_STAR。

## ADR-003 · LLM provider adapter 层

- **状态**：已批准（作者口头，2026-04-20，方案 B 衍生）
- **代际**：r1-agent-loop
- **关联 commit**：`a48c86e`

ADR-002 v2 把"换哪家 provider"决了，"怎么抽象"留给 ADR-003。`LLMClient` Protocol 定一个最小接口 `messages_create`，AgentLoop 只依赖这个 Protocol。首发两个 adapter：`DeepSeekAdapter`（默认 / OpenAI 兼容端点 / 内部做双向翻译）和 `AnthropicAdapter`（接近 passthrough）。GLM / Qwen / Kimi 列为 v0.2+ 候选——它们都走 OpenAI 兼容端点，未来接入只需继承一个共用基类。

这份 ADR 自己就在第 67 行承认了"未来演化"：r2 应该把内部形态切到 OpenAI function calling，让 AnthropicAdapter 反向翻译。这条预言两个月后被 ADR-007 兑现。

附录正文里 article-08（provider adapter 的长尾税）写了这个 adapter 层后来怎么变成所有 provider 怪癖的兜底场——`<think>` 标签 strip / 内容审查识别 / arguments 空串容错全堆在这里。

## ADR-004 · upload 端点策略

- **状态**：草案（副管理起草，待作者选定）
- **代际**：r1-agent-loop
- **关联 commit**：`f541306`（起草）/ `e2bbf20`（方案 B 落地）

r1 已经能问书，但还不能上传一本新书——这是 ADR-004 起草时的具体堵点。v7 那条三阶段 KG 提取流水线已经按"r1 不依赖 legacy/v7"的归档约定挪到 `legacy/v7/`。要让新书走完 upload→ask 闭环，KG 这一块必须有出处。ADR-004 给了三个方案：复活 v7 流水线（A）/ 写一个最小 KG extractor（B）/ 完全不做 upload 只接 JSON 导入（C）。副管理推荐 B，作者最终接受。

`MinimalKGExtractor` 约 150-250 行，靠 ADR-003 已有的 `LLMClient` Protocol 做 batch map-reduce 抽取，KG 提取失败时降级为空 KG 继续建 session。这份 ADR 同时让 adapter 层多了第二个使用者（第一个是 AgentLoop），算是 provider-agnostic 抽象的一次复用验证。

## ADR-005 · book session 持久化

- **状态**：草案（副管理起草，2026-04-20）
- **代际**：r1-agent-loop
- **关联 commit**：`e2bbf20`（ADR-005A 实施）/ `bbec6fa`（vector index 持久化收尾，第 13 轮）

`BookSessionStore` 早期是纯内存 `dict`——进程退出全丢。一本 50 万字的明朝那些事儿要重新 ingest + 重建 KG + 重算 FAISS 大约 30-60 秒，作为长线自用工具这个起手成本不能接受。ADR-005 给了三个方案：JSON file per session（A）/ SQLite（B）/ Redis（C）。副管理推荐 A——零外部依赖、文件可读（作者可以直接打开 `kg.json` 审查 KG 质量）、和 `Repository` 已有的 JSON-on-disk 习惯一致。

落地后每个 session 是 `data/sessions/<session_id>/` 一个目录：`metadata.json` / `book_text.json` / `chunks.json` / `kg.json` / `vector_index/faiss.index`。懒加载——首次访问 0.5-1 秒反序列化，之后全在内存。这个设计也给 ADR-008 的"book 预热缓存"留好了入口。

## ADR-006 · r1 本地 ML 模型推理全部 API 化

- **状态**：已批准（作者口头，2026-04-24）
- **代际**：r1-agent-loop
- **关联 commit**：`8ca0671`（第 16 轮首次端到端真 API 跑通 + ADR-006 签字）/ `077b8ec`（第 17 轮实施 · 本地 ML 依赖全部下线）

ADR-006 是 BookScope 写过最"硬"的一份 ADR——不是"我们想这么做"，是"硬约束被实测违反，必须把违规路径砍掉"。第 16 轮 smoke test 跑明朝那些事儿，agent 调一次 `search_chunks` 单步耗时 209-393 秒，整个 trace 表明耗时全在 `_maybe_rerank` 里的 cross-encoder CPU 推理上。"禁止 GPU 依赖"和"10 秒读取目标"两条硬约束当场撞穿。

作者一句"全部 API 化"，副管理转成 5 条工程动作：删本地 reranker / 新增 `RerankerProvider` Protocol 候选 / 删 embedding 本地 Tier 2/3 / 清理 `sentence-transformers` 与 `torch` 依赖 / 划清 API 化边界（BM25 / jieba / FAISS 不动）。依赖瘦下来好几 GB，冷启动不再 lazy-load 重模型。

附录正文里 chapter-02 写了这一夜——本地 ML 模型怎么进的 r1、又怎么被 209 秒数据当场赶出去。

## ADR-007 · r2 切换 OpenAI function calling 为内部主格式

- **状态**：已批准 · 2026-05-15 作者第三次明示签字 · Sprint 7 删 r1 授权
- **代际**：r1-agent-loop → r2 演化
- **关联 commit**：`4adf736`（草案）/ `abf10a6`（第一次签字）/ `d236a05`（第二次签字 · Sprint 4 D-2 反向翻译实施）/ `c847169`（Sprint 5 r1 vs r2 12 batch · 撤回条件不命中）/ `88ab2d9`（Sprint 6 启动 · 默认协议 r1→r2 · r1 deprecated）/ `0845014`（第三次签字 · Sprint 7 启动授权）/ `d8b6869`（Sprint 7 Migration retrospective）

ADR-007 是 ADR-002 v2 + ADR-003 留下的技术债的还款单。ADR-003 在第 67 行就预言过这条路径——r2 应该让多数派（OpenAI function calling）做内部主格式，让少数派（Anthropic tool_use）反向翻译。问题三条说得很清楚：翻译层成了所有 provider 怪癖的兜底场（`DeepSeekAdapter` 428 行一半在翻译一半在补怪癖）/ 新 provider 接入要继承全套翻译开销 / 工程直觉本来就该让多数派打头。

这份 ADR 走完了 BookScope 最长的签字流程：5 月 13 日草案 → 同日第一次口头批准 Sprint 4 骨架 → 5 月 14 日第二次明示签字（"按你的建议来，签字一下，我都同意"）→ Sprint 5 跑完 12 个 batch r1 vs r2 对照（anshi r1 15.80 / r2 13.79 容忍带 ±5.07 不退化；mingchao r1 17.67 / r2 17.80）→ Sprint 6 默认协议翻面、r1 deprecated → 5 月 15 日第三次签字授权 Sprint 7 删 r1 + Migration retrospective。

附录正文里 chapter-05（拆掉双向 adapter）从草案写到 r1 git rm 全过程。

## ADR-008 · Sprint 8 三层缓存设计

- **状态**：草案 · 等 Sprint 8 启动时作者签字
- **代际**：r2-agent-loop 单形态（Sprint 7 删 r1 后启动）
- **关联 commit**：`66ad36f`（草案）

Sprint 5 性能第一刀砍完之后：通识题靠 fast_path 从 90-180 秒降到 3-12 秒，深题维持 90-180 秒，单题 P50 落在 30-60 秒。要继续往"重复问题 < 3 秒 / 冷启动 < 5 秒 / 单题 P50 < 30 秒"推，得加缓存层。

ADR-008 把缓存分三层：`search_chunks` 结果缓存（24 小时 TTL，节省 100-500ms/次）/ LLM 调用结果缓存（7 天 TTL，按 prompt 版本分桶，节省 5-60 秒/次）/ book 预热缓存（启动期预热 hot session 的 vector index 与 KG）。每层的 key 算法、存储后端、命中率预估、失效策略都在 ADR 里 lock 住——Sprint 8 启动时直接照着 prep 文档实施。

这份 ADR 自己还在 Problem 段处理了 LLM 非确定性的语义问题：缓存命中时直接返历史响应，等于把 provider 端的非确定性折叠成确定性——好处是产品体验稳，代价是丢掉"重试可能更好"的机会。这是显式的设计选择，不是疏忽。

附录正文 chapter-06（从 3 分钟到 30 秒）写了 Sprint 5 那刀；ADR-008 落地后会有 chapter-09 或同章后半段对照。

## ADR-009 · 多轮连续追问

- **状态**：已批准 · 2026-05-15 之后作者签字生效 · 方案 C 分两阶段 · Phase 1a 已落地
- **代际**：r2-agent-loop 单形态
- **关联 commit**：`4ca6396`（草案 · 三方案对比推荐 C）/ `3d9a0ad`（作者签字生效 · Phase 1 即刻启动）/ `e6c6208`（Phase 1a 骨架 + 上轮答案注入）/ `eb2090c`（Phase 1b 追问指代消解）

创作者真实的用法是连着追问，但 r2 此前每问都全量重启，上一轮的证据全丢——这是设计缺口评审 13 条里的第 10 条，也是当时唯一"没意识到要设计"的缺口。ADR-009 在三个方案里选了 C 分两阶段：Phase 1 先做轻量的上轮答案注入加指代消解（"他"指谁靠上下文补全），Phase 2 再把上轮证据集做成预热缓存。先落 Phase 1 拿真实追问跑通，避免一上来就背 context 爆炸的包袱。

---

## ADR 写作约定与维护建议

写到第 8 份了，回看 BookScope 这套 ADR 沉淀下来的姿态约定，给未来 ADR 作者（包括副管理自己）几条：

**Status 段位的翻面节奏**。早期 ADR-001 / 002 / 003 全是"已批准 + 一行口头记录"，简洁但回查模糊。ADR-007 走完三次签字之后，副管理学会了把每次签字的 commit hash 和签字日期都写进 Status 段——读者从 git log 倒查时不用再翻 STATE。建议：从签字密度大的 ADR 开始，Status 段就用 commit hash 加日期的清单形态，不要塞进 Revision History 一段散文里。

**Problem 段位是把"为什么这个 ADR 值得写"讲清楚的关键**。早期几份 ADR 把 Context 写得很长，但读者读完不一定知道"那现在的痛点究竟是什么"。ADR-007 / 008 把 Problem 拆成"问题 1 / 2 / 3"三条，每条写一个具体的 file / line 或一个具体数据点（428 行 / 209-393 秒 / 30-60 秒 P50）。后续 ADR 建议继承这个写法——Context 给背景，Problem 给痛点，Decision 给动作。

**Open Questions 留 3-5 条合适**。多了像没想清楚，少了像没想到。ADR-004 / 005 在副管理推荐方案下面各留了两三条"作者选完之后再答"的开放问题（TTL、并发上限、fallback 策略等），这种规模刚好——签字后副管理可以在 STATE 里追这几条收口，不用再开新 ADR。

**Migration Plan 用 sprint 拆分而不是写"分阶段实施"**。ADR-007 把迁移拆成 Sprint 4（骨架）/ Sprint 5（双轨实验）/ Sprint 6（默认翻面）/ Sprint 7（删 r1）四个 sprint，每个 sprint 都有具体验收测试。这套方式让 ADR 自己成了 ROADMAP 的一个真实节点——签字之后副管理拿这份计划直接派 BE / QA 干活，不用二次翻译。建议：所有涉及代际级 / 协议级变更的 ADR，Migration Plan 段强制用 sprint 拆分。

**撤回条件要写死，不要含糊**。ADR-006 写了三条很硬的撤回条件：recall@10 持续低于阈值 / 作者本人小说草稿跑得显著不准 / 合规要求全本地运行。ADR-007 写了 r1 vs r2 容忍带（±5.07 / ±2.47）和具体 batch 结果。这两份 ADR 后来在 Sprint 5 实验数据回来时，可以"按写好的条件判定不撤回"而不是临时讨论。撤回条件不是装样子，是给未来的自己一个止损线。

**关联 commit 与正文章节一并写进 ADR 末尾**。读者从案例研究跳到 ADR，从 ADR 还要能跳回 git log 和 case-study 章节——这是双向索引。早期 ADR-001 / 002 没这一节，后期 ADR-007 / 008 都开始挂了。建议：ADR 末尾固定加一节"Related"，列章节链接 + commit hash + 相关 memory 名。
