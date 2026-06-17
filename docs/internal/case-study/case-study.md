# BookScope 案例研究

> **状态**：持续更新 · 章节随代际推进增量沉淀
> **撰写分工**：AI 主循环（副管理）写草稿 → 作者润色定稿 → 对外发布
> **匿名化**：全文以"作者" / "项目负责人" / "CEO" 等职能称谓指代，不出现真实姓名或公司名

---

## 这份文档是什么

BookScope 是一个**查询时智能代理 + 原文证据优先**的深度阅读工具，服务对象首先是项目作者本人——一位几十万到几百万字级别的长篇网络小说作者，需要把自己的草稿当成"真正的书"来扫描、对话、反馈。

这份案例研究记录**项目从架构设想到真实可用产品的全过程**，不是产品说明书。重点在：

- **技术判断的分叉点**：每一次代际升级、每一份 ADR、每一次方向推翻都保留前因与取舍
- **真实验的意外**：真正接上 API、真正扫整本书时发生了什么，和预先设想的偏离
- **约束驱动的架构演进**：硬约束（禁 GPU、10 秒读取、BYOK、国内 LLM 优先）在真实摩擦下如何把架构压进特定形状

对外它是一份可发表、可展示的长线个人作品；对内它是未来重读项目时的"为什么"字典。

---

## 读者是谁

- **正在做长期技术项目的独立开发者**：你可能在类似分叉点上做判断；看看另一个人走到这一步时的权衡
- **对 agentic RAG / 长文本问答架构感兴趣的工程师**：r1 从"批量预处理 + 静态展示"转向"轻量索引 + 查询时代理"的真实样本
- **对"AI 做多少、人做多少"协作模式好奇的观察者**：本项目采用"CEO + AI 团队 24/7 自主循环"模式，作者保留不可代做的四件事（自试、方向、代际签字、案例定稿）

---

## 代际与章节索引

| 代际 | 章节 | 主题 |
|------|------|------|
| r0-baseline（冻结） | chapter-00（待写） | 三阶段预处理流水线的取舍与归档 |
| r1-agent-loop（当前主线） | [chapter-01](./chapter-01-r1-launch-and-api-first-pivot.md) | **r1 首次真 API 跑通 + API-first 架构重构**（第 16–20 轮） |
| r1-agent-loop | [chapter-02](./chapter-02-query-time-assembly-and-r0-legacy-patches.md) | **查询时装配的代价：r0 数据层遗产与缺口修补**（第 11–15 轮） |
| r1-agent-loop | [chapter-03](./chapter-03-training-contamination-night.md) | **训练污染那一晚**（第 25–26 轮）·公开书 baseline 被 minimax 揭穿 |
| r1-agent-loop | [chapter-04](./chapter-04-the-book-it-never-read.md) | **它没读过的那本书**（第 28–33 轮）·冷热书对照与 v3.2→v3.4 迭代 |
| r2-agent-protocol | [chapter-05](./chapter-05-decommissioning-bidirectional-adapter.md) | **拆掉双向 adapter**（第 33–35 轮）·ADR-007 全程到 r1 git rm |
| r2-agent-protocol | [chapter-06](./chapter-06-from-3min-to-30s.md) | **从 3 分钟到 30 秒**（Sprint 5）·tool 并行 / 题型路由 / fast_path |
| r2-agent-protocol | [chapter-07](./chapter-07-ai-as-judge-out-of-lab.md) | **AI-as-judge 走出实验室**（Sprint 5.5）·reviewer 接进用户评分卡 |
| r2-agent-protocol | [chapter-08](./chapter-08-dogfood-day.md) | **dogfood 一日**（第 35 轮第二波）·作者 4 句反馈触发 UX 重构 |
| r2-agent-protocol | [chapter-09](./chapter-09-one-day-double-front.md) | **一日双重攻**（2026-05-15）·5 句话授权 37 commit 完 ADR-007 收尾加 Sprint 8 三层缓存 |
| r2-agent-protocol | [chapter-10](./chapter-10-ingest-layer-second-cut.md) | **把性能第二刀切到上传那一侧**（Sprint 6 + 第十七波）·三层缓存 664x/1271x + quality probe 撞 reviewer 限制 |
| r2-agent-protocol | [chapter-11](./chapter-11-the-day-of-reckonings.md) | **翻案日**（2026-06-10 · 第十八波）·一天收回三个结论：prompt 冻结 44 天 + reviewer"拒答"错误归因 + 版本污染虚惊·测量仪器先于实验 |
| r2-agent-protocol | [chapter-12](./chapter-12-from-probe-to-product.md) | **把验过的能力搬上货架**（2026-06-12～15）·发明区六炮 GO 后建成关系图/概念图/citation 精度/出题/节奏曲线·结构化输出三守卫·dogfood 驱动·测量层母题在输出端的续篇 |

> **章节号不按时间顺序排版**——前两章按"读者认知路径"组织：先讲"产品跑起来是什么样"（chapter-01），再回溯讲前期架构铺垫（chapter-02）。chapter-03 之后回到时间顺序，按 Sprint 推进沉淀。

---

## Articles 索引

章节按时间线串主线，articles 是单主题深挖——一个坑、一个反 framing、一段 prompt 演化拎出来写厚。chapter 和 article 互为索引：chapter 里点到的现象，article 里展开成证据链。

| 编号 | 标题 | 主题 |
|------|------|------|
| [article-01](./articles/article-01-public-book-baseline-contamination.md) | 公开书 baseline 的训练污染天花板 | 24.8 到 20.0 之间 4.8 分的拆解 |
| [article-02](./articles/article-02-reasoning-model-into-bookscope.md) | Reasoning Model 进入 BookScope | `<think>` 标签与 tool_calls 的兼容假象 |
| [article-03](./articles/article-03-tool-calling-behavior-spectrum.md) | Tool Calling 行为光谱 | 四家 provider 在同一 loop 上的实证比较 |
| [article-04](./articles/article-04-prompt-hard-constraint-failure-mode.md) | Prompt 硬约束的失效边界 | v3.1 在 minimax 上的最低限度遵守 |
| [article-05](./articles/article-05-json-parse-long-march.md) | JSON Parse 长征 | 从定向引号到通用引号到控制字符的四道 autofix |
| [article-06](./articles/article-06-citation-quantity-vs-quality.md) | Citation 数量 vs 质量 | 5 条 vs 13 条的真证据密度博弈 |
| [article-07](./articles/article-07-ai-as-judge-loop-boundary.md) | AI-as-judge 闭环的有效性边界 | 第 25 轮收敛与第 26 轮反向的两次实证 |
| [article-08](./articles/article-08-provider-adapter-long-tail-tax.md) | Provider Adapter 的长尾税收 | OpenAI 兼容假象底下的真实碎片 |
| [article-09](./articles/article-09-batch-experiment-pipeline-birth.md) | 批量实验 Pipeline 的诞生 | 从手工 30 分钟到自动 10 分钟的研究 infra |
| [article-10](./articles/article-10-north-star-validated-by-data.md) | NORTH_STAR 在数据下被反证 | "服务作者本人"从口号到方向锚点 |
| [article-11](./articles/article-11-llm-wiki-vs-query-time-agent.md) | LLM Wiki vs 查询时 agent | 体裁决定承载单位 |
| [article-12](./articles/article-12-experimental-design-fragility-in-ai-era.md) | 实验设计在 AI 时代的预设错误 | 三个被现实压破的实验前提（baseline std / 错误类别 / reviewer 稳定性） |

---

## 附录

- [`appendix-A-adr-index.md`](./appendix-A-adr-index.md)：8 份 ADR 的决策摘要加演化主线（2026-05-15 落）
- `appendix-B-experiment-001-results.md`（待建立）：实验 001 基线对比结果（等正式 G0 轮跑完）
- `appendix-C-failure-diary.md`（待建立）：踩过的坑 / 否决过的方向 / 归档的代码

---

## 撰写约定

1. **AI 草稿不得自作主张定稿**。章节 status 区初始为 `草稿 · 作者未定稿`；**定稿是里程碑级事件**（代际完成 / 对外发表 / 作品集整理时）由作者一次性终审后改为 `已定稿 · YYYY-MM-DD`——**不要求逐章即时定稿**，草稿是积累资产可长期保持待稿状态并持续修订
2. **代码级细节要真**：commit hash、文件路径、行号、耗时数字——全部从实际 commit 与 STATE.md 抄
3. **决策要给 context**：不要只写"我们选了方案 A"，必写"因为 B 违反约束 X / C 的代价 Y / A 的尾巴 Z"
4. **保留作者笔迹接口**：AI 草稿不自称"我"——用"作者" / "团队"；作者定稿时可直接替换为"我"
5. **匿名化硬规则**（CLAUDE.md 最高优先级）：绝不出现真实姓名、公司名、系统用户路径
