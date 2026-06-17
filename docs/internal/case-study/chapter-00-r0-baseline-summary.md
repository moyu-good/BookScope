# 第 0 章 · r0-baseline 总结：三阶段预处理流水线的取舍与归档

> **状态**：草稿 · 作者未定稿 · 2026-05-15 起头
> **时段**：2026-03-26 至 2026-04-20（v0.1 初版到 v7 冻结，约一个月，第 1–15 轮）
> **覆盖 commit**：`e807acc`（初版）→ `aefc60d`（v6 20x 提速）→ `b8ad305`（TransformerAnalyzer 移除）→ `165642b`（v7 三阶段引擎）→ `3bd9676`（r0 冻结）
> **与后续章节的关系**：本章是案例研究的起锚章。[第 1 章](./chapter-01-r1-launch-and-api-first-pivot.md) 接 r1 启动，[第 2 章](./chapter-02-query-time-assembly-and-r0-legacy-patches.md) 讲 r1 怎么继承 r0 数据层并补丁三个结构性缺口，[第 5 章](./chapter-05-decommissioning-bidirectional-adapter.md) 接 r2 协议切换。完整代际链路从这里起步。

---

## 一、三阶段流水线是什么

r0-baseline 不是一开始就长这样。从 `e807acc`（2026-03-26 初版）到 `165642b`（2026-04-10 v7 三阶段引擎），中间走过 v1 多语言、v2 PDF/URL ingestion、v3 KG + hybrid RAG、v4 unified FastAPI+React、v5 BYOK + Transformer 情感分析 + MapReduce KG、v6 性能优化二十倍，一共大约二十几个 commit。**r0 真正的稳定形态是 v7**，前面六代都是迭代过程，迭代过程里被砍掉的尝试比留下来的多。

v7 的核心是一条三阶段流水线，写在 `legacy/v7/bookscope/nlp/chunk_scanner.py` 和 `chunk_selector.py` 里。简单说：一本书上传进来，离线阶段做完三件事，再把结果存盘等用户来翻。

第一阶段，全量轻扫描。书被切成大概一千个 chunk，每个 chunk 喂给便宜的 LLM（Haiku 或 DeepSeek），提取一份很小的结构化元数据：出场角色、关键事件、紧张度（tension）、主题词、一句话摘要。`chunk_scanner.py` 顶部那段成本估算注释里写得很清楚——四百个 chunk 跑 Haiku 大约六毛四美元，每个 chunk 输出约二百 token。

第二阶段，智能选择。这一步纯算法不调 LLM，看 `chunk_selector.py` 顶部那段就知道在干什么：从第一阶段的扫描结果里挑出三十到五十个"关键 chunk"。挑的依据是张力峰值、人物首现、事件重要性、结构覆盖（每个章节至少出一个代表）、信息密度。

第三阶段，定向深度分析。被挑出来的几十个 chunk 走 Sonnet 那一档贵但准的模型，做精炼分析，产出角色卡、关系图、章节弧、风格画像、洞察文字。这些结果落盘，存进一个叫 `AnalysisResult` 的大 Pydantic 模型，前端（御览模式 React UI）从这里读，做出"奏折"和"朱批对话"那种皇家档案风的展示。

这是一条典型的"批量预处理 + 静态展示"架构。书上传那一刻所有 LLM 算力被烧掉，分析结果冻干成 JSON 落盘；用户来翻书，只是翻一份预先做好的档案。

---

## 二、当时为什么选预处理而不是查询时

回头看 r0 的架构选择，今天的视角很容易说"这是过时范式"。但如果把日历拨回 2026 年三月底——那时作者刚开始这个项目，BookScope 还叫"书鉴"，前端在折腾"墨韵"视觉设计——预处理路径其实是当时唯一合理的判断。

三个具体约束逼着 r0 走这条路。

第一个约束是 LLM 成本。`chunk_scanner.py` 注释里那段成本估算是关键证据：四百个 chunk 跑 Haiku 大约六毛四美元，已经是当时能找到的最便宜组合。如果改成查询时智能代理——用户每问一句话 agent 都现场调 LLM 扫书——一本三十多万字的书每问一次都得花同样的钱，作者自己 dogfood 一周就能把账单跑爆。预处理至少把账单锁死在"上传一次烧一次"。

第二个约束是 context window。2026 年三月，大部分国内 LLM 的 context window 还停在 32k 到 128k 之间。一本《明朝那些事儿》一卷三十多万字，整本喂不进去；甚至单个长章节也得切碎。"agent 现场拉原文"这件事在工程上就跑不动——拉多少？拉哪段？拉了塞不进 context window 怎么办？查询时代理要成立，必须先有 chunk 级的检索能力，而 chunk 级检索的前提是 chunk 已经切好、embedding 已经算好。一句话：**r1 哲学要成立，r0 的索引层必须先存在**。

第三个约束是延迟。当时国内 LLM 单次调用普遍在五到三十秒，多轮 tool use 那种 agent loop 一次问答动辄一两分钟。如果用户每问一句话都要等这么久，产品不可用。预处理把延迟全部前置到上传阶段——上传一次几分钟，用户接受度高；用户翻书时几乎零等待，看的是预生成的 JSON。

所以 r0 不是"做错了所以推翻"。**r0 是在三月底那个时间点、那套成本和能力约束下，最合理的工程判断**。后面会看到，这套判断的每一条都在四月被一项一项压垮——不是因为判断错了，是因为约束在变。

---

## 三、跑下来的真实数字

判断合不合理是一回事，真跑起来是另一回事。r0 跑了一个月，留下来的真实数字有几条很硬。

最早压上来的是延迟。v5 那版 `knowledge_extractor` 跑完一本书要四十分钟——三百七十六次 LLM 调用，三百一十万字符 input。四十分钟对作者自己 dogfood 都难忍，对潜在用户更是劝退。`aefc60d`（2026-04-08）是 v6 那次"二十倍提速"的 commit，把分析路径砍成"智能弧采样 + 两阶段并行"：分组采样把一千多个 chunk 压成十五个弧，LLM 调用从三百七十六次砍到十九次，input 字符从三百一十万压到三十七万五千，时间从四十分钟降到两分钟。同一天又跟了一次更深的设计调整，把流水线分成 Tier 1（无 LLM，三十秒内出文风和情感）和 Tier 2（LLM，九十秒出 KG 和弧），前端做分阶段渲染。这是 r0 时期最猛的一次性能改造。

第二个数字更刺眼。`b8ad305`（2026-04-08，比 v6 提速晚十几分钟）把 `TransformerAnalyzer` 整个删了。原因写在 commit message 里："CPU 不可用（692s），不应要求用户有 GPU"。`TransformerAnalyzer` 是 v5 引入的 transformer 情感分析器，在 GPU 上几秒能跑完一本书，CPU 上一千个 chunk 要十一分半钟。这次删除是 r0 期第一次正面撞上"禁止 GPU 依赖"这条硬约束——后来这条约束写进了 `CLAUDE.md` 技术栈节，再后来 ADR-006 把它扩展成"本地 ML 推理全 API 化"。`TransformerAnalyzer` 被替换成 `LexiconAnalyzer`（基于词典的轻量情感分析），CPU 上二十一秒跑完，精度让步换可用性。

第三个数字藏在 v7 那次三阶段引擎重写里。v6 的智能弧采样虽然把时间压下来了，但 commit `165642b` 的 message 里点出一个根因问题："v6 盲采样只读 20% 原文，80% 内容未被 LLM 读过，是数据质量差的根因"。v6 的速度是用"少读"换来的，v7 把这个 trade-off 翻过来：第一阶段全量扫描，所有 chunk 都被 LLM 看过一遍（用最便宜的模型）；第二阶段算法选关键 chunk；第三阶段才用贵模型深挖。覆盖率从二成回到十成，单本书成本回到一美元级，时间在四到八分钟。

这三个数字串起来就是 r0 期的真实曲线：四十分钟 → 两分钟（v6 提速）→ 砍掉 GPU 路径（v6.x 删除 TransformerAnalyzer）→ 全覆盖加回（v7 三阶段）。一个月，工程账面上跑了一圈。

但这条曲线压不下来的是另一类数字。预生成的 `AnalysisResult` JSON 上线后，作者自己 dogfood 时发现一件事：**所有分析结论都没有原文引用**。chunk 在第三阶段被 Sonnet 精炼成一段角色描述、一段章节弧解读，但产出的文字里看不出"这句话是从书里哪里来的"。当作者自己看到一段对角色的判断，第一反应是"凭什么这么说"——预处理流水线给不出答案，因为它把原文证据在第二阶段就抽象掉了。这件事在四月中下旬反复被作者锤，直接催生了 r1 代际"原文引用必选"那条 [ADR-001](../architecture-decisions/001-r1-agent-tool-interfaces.md) 的核心约束。

---

## 四、触发代际升级的硬约束

四月二十日 `3bd9676` 这个 commit 把 v7 冻结，标记为 r0-baseline。从 `165642b`（4-10 v7 上线）到 `3bd9676`（4-20 冻结），中间只有十天。十天里到底发生了什么，让 v7 这条刚刚跑通的流水线被判了死缓？

不是 v7 本身坏了。是几条约束同时撞上了天花板。

第一条是"原文证据必选"。前面提到，预处理产物是冻干 JSON，没法回答"凭什么这么说"。这不是 v7 的 bug，是预处理范式本身的结构性限制——一旦把原文摘要成 KG 节点和弧分析文本，证据链就被切断了。补救方案只有一个：让 agent 在用户问的那一刻回到原文。这件事预处理范式做不到。

第二条是 10 秒读取目标。这条目标后来写进了长期记忆 `feedback_performance_target.md`："整本书必须 10 秒内读取"。v7 上传一本书要四到八分钟——离 10 秒差了两个数量级。预处理的代价就在这里：所有延迟前置在上传阶段。要把延迟压到 10 秒，预处理范式没救——只能转向"上传时几乎不做事，查询时做该做的事"。

第三条是多种书籍类型。长期记忆 `feedback_multi_book_types.md` 锁死这一条：BookScope 必须能跑历史小说、理论书、科研论文、工具书、哲学、诗歌——承载单位完全不同。v7 的 KG 抽取深绑"角色 + 事件 + 弧"那一套小说叙事模型，跑科研论文时角色字段是空的，跑哲学时事件字段是空的，跑诗歌时章节都难定义。预处理路径要支持多种书籍类型，需要为每种类型写一套抽取 schema、一套 chunk_scanner prompt、一套 chunk_selector 启发式——工程膨胀不可控。

第四条是禁 GPU 这条硬约束在 v5/v6 时已经显形（删 TransformerAnalyzer 那次），到 r1 启动第 16 轮才被彻底落地——把所有本地 ML 推理转成 API 调用（[ADR-006](../architecture-decisions/006-local-ml-api-only.md)）。这条约束在 r0 期没办法彻底解决，因为 r0 的 hybrid 检索里 cross-encoder reranker 还是本地 CPU 模型，r1 早期继承下来时第一次 smoke test 直接撞了 892 秒的 BM25 路径（第 1 章里详细写了这一笔）。

四条约束串在一起，r0 没有渐进改良的空间。"批量预处理 + 静态展示"和"查询时智能代理 + 原文证据"是范式之争，不是参数调优。所以 4-20 那次冻结不是放弃 v7，是承认 v7 完成了它该完成的事——把 ingest、chunker、KG 抽取、hybrid 检索、章节识别、embedding 等基础设施搭起来了——剩下的范式问题，要换一个代际重做。

---

## 五、归档与起点

`3bd9676` 那次冻结把 v7 的代码搬进 `legacy/v7/`，归档说明写在 `legacy/v7/README.md` 里。归档时间 2026-04-20，归档前 r1 测试 162 passed，归档后 r1 测试 162 passed，归档后 r0-pure 测试 133 passed——这组对照数字是当时确认"归档动作没破坏任何东西"的依据。

r1 从 r0 继承什么、抛弃什么，在 `legacy/v7/README.md` 第 31 行那段"与 r1 的关系"里写得很直接。继承的是基础设施：`bookscope/models/`（Pydantic 数据模型）、`bookscope/ingest/`（加载、清洗、分块、章节检测）、`bookscope/store/`（仓储 + SessionVectorStore + embedding_provider）、`bookscope/utils/`（NLTK 资源等）。这四块从 r0 沿用到 r1 再到 r2，是 BookScope 横跨三个代际不变的地基。

被搬进 legacy 的是上层应用：`bookscope/nlp/`（v7 三阶段分析器 lexicon / style / arc / ner / relation / knowledge / soul / llm）、`bookscope/services/`（extraction_pipeline、derived_fields）、`bookscope/api/`（v7 FastAPI 入口 + 12 个 router）、`bookscope/eval/`、`bookscope/viz/`，加上整套御览模式 React 前端和 Streamlit 上位层。这些代码不删——`legacy/v7/README.md` 写明，未来某些分析器（例如 ArcClassifier、LexiconAnalyzer）若需要在 r1 / r2 复用，可以 `git mv` 移回原位，保留 git history 让 blame 仍能追踪。

[第 2 章](./chapter-02-query-time-assembly-and-r0-legacy-patches.md) 会详细讲 r1 继承 r0 数据层时，发现 r0 schema 有三个为"批量预处理"设计、对"agent 查询时反向查询"不友好的结构性缺口（chunk → chapter 映射、chunk → characters 倒排、章节原文持久化），以及 r1 第 4–15 轮怎么用 workaround 和正式 patch 一一闭合。那些补丁工作是 r0 → r1 过渡的真实工程账。

r0 留给 BookScope 案例研究的最大遗产不是代码，是判断框架的演化轨迹本身。三月底那套基于成本、context window、延迟三约束的合理判断，在一个月内被原文证据需求、10 秒读取目标、多书籍类型、禁 GPU 四条新约束逐条压垮。这种"判断框架被现实压出来必须重做"的场面，是任何在 AI 产品早期阶段做架构决策的人都会反复遇到的——所以 chapter-00 不是怀旧章，是案例研究全套代际叙事的方法论起点。

---

## 六、史料缺口与后续补完

副管理没亲历 r0 期。本章基于 git log、commit message、`legacy/v7/README.md`、chapter-01 / chapter-02 已有引述、ADR-006 反向追溯的现场数据拼接而成。以下几条事实需要作者在定稿时补完或纠正：

- **v7 上传一本书的真实时间窗**：本章引用了 v6 的"两分钟"和"四到八分钟"做 v7 估算（基于 v7 多了第一阶段全扫描 + 第三阶段定向深挖、commit `165642b` 没直接给端到端时间）。v7 实际上线后单本书完整 ingest 的真实时间数据，作者本人 dogfood 时的体感应该比副管理拼凑准。
- **"作者反复锤'凭什么这么说'"那段场景**：副管理基于 ADR-001 的 r0 dogfood 回顾引述（"LLM 算力全部烧在 ingest 阶段，书被'冻干'成一堆静态分析产物"）反推，并没有具体到某一次 session 的原话。如果作者记得是哪一次 dogfood 触发了这条转折判断，定稿时可以补一句具体场景。
- **十天里发生了什么**：4-10 v7 上线到 4-20 r0 冻结之间，副管理只能从外部 commit log 看到"什么都没动 v7、转头开始起草 r1"。这十天里作者的内部判断过程（什么时候决定要转 r1、看了哪些资料、跟谁讨论过、是渐进觉悟还是某个具体 trigger）是 chapter-00 最大的史料缺口。定稿前作者可以补一段第一人称的"我是怎么决定要换代际的"。
- **v7 BYOK 的具体覆盖范围**：commit `9c6810f` 写"v5 BYOK architecture — multi-provider LLM support"，但具体 v7 时期支持哪几家 provider、第一个 LLM 后端是 Anthropic 还是 DeepSeek、作者自己最早用哪家——副管理没考据出，定稿可补。
- **r0 案例研究值得引用但本章没覆盖的素材**：`legacy/v7/PLAN.md`（v7 时代的计划文档）和 `legacy/v7/book-analyzer-project-plan.md`（v7 项目计划书）副管理本次没读，里面应该有 r0 设计初衷的第一手记录。后续 article 系列（`docs/internal/case-study/articles/`）可以单独写一篇 r0 设计意图溯源，引用这两份文档原话。

副管理的写法是：先把能考据到的结构性事实写实，留缺口给作者亲笔补。这条本章末尾"史料缺口"段位的体例，建议沿用到任何未来副管理代写、需要作者亲历者补完的章节。
