# BookScope 项目全面盘点（2026-06-10）

**起因**：作者指出项目复杂、开发时间长，"很多设计和目的的留存并不完善"。本文档是对这句话的系统性检查——把 docs 全集、代码、测试与实验数据各盘一遍，列出"文档说的"和"代码做的"之间所有错位点。

**盘点方式**：3 个探查代理并发，分别扫 docs/（very thorough）、bookscope/ + web/ + scripts/（very thorough）、tests/ + 实验数据 + git 历史（medium）。本文档只记事实与断点，判断标注为副管理 take。

---

## 一、项目一句话史

- **r0-baseline**（已冻结）：v7 三阶段预处理流水线，归档在 `legacy/v7/`
- **r1 代际**（2026-04-20 启动）：查询时智能代理，三 tool + 原文引用
- **r2 协议**（ADR-007，2026-05-15 签字）：AgentLoop 内部主格式从 Anthropic tool_use 切到 OpenAI function calling；r1 runtime 三文件（1693 行）同日 `git rm`
- **现状**：分支名还叫 `r1-agent-loop`，代际口径还叫 r1，但唯一现行 runtime 是 `loop_r2.py`。5/19 之后 0 commit，仓库停摆 22 天

## 二、现状快照

### 代码（健康）

- `bookscope/agent/`：loop_r2（1041 行）+ fast_path + question_processor + reviewer + events + errors，r1 残留 0
- adapter 两家：`anthropic_r2`（490 行）+ `deepseek_r2`（280 行）。**没有独立 minimax adapter**——minimax 走 DeepSeekAdapter 的 OpenAI 兼容端点
- 缓存四层全在 `_internal/`：L1 search LRU / L2 LLM SQLite / L2.5 KG SQLite / L3 book pickle（ADR-008）
- prompt 版本：loop_system_prompt v1~v3.5 共 9 个并列保留；reviewer_rubric / question_processor / citation_format 各 v1
- API 8 个端点（ask / ask/stream / upload / upload/stream / sessions×3 / health）；前端 `web/` React 19 + Vite 6 + Tailwind 4
- scripts/ 13 个：batch runner 3 / benchmark 3 / probe 4 / 工具 3

### 测试与数据（健康）

- **780 测试全部可收集，无报错**（STATE 最后记录 768，5/18-19 两波又加了 12 个但 STATE 没更新数字）
- 实验数据 47 份 JSON：anshi / mingchao 完整，kuicheng / zhinei 各只有单题；最新一份 2026-05-19
- 测试书 4 本 EPUB 在仓库根：mingchao / anshi / kuicheng / zhinei
- 未提交改动只有 `.claude/settings.local.json`

### 文档（断点集中区，见第三节）

- ADR 8 份编号连续；case-study 11 章 + 12 篇 article 草稿全齐、零定稿（定稿等 Sprint 10 作者亲笔，符合既定约定）
- 跨文档引用链检查：**无断裂链接**

## 三、留存断点清单（本次盘点的核心产出）

### A. 文档落后于现实

| # | 断点 | 事实 | 该谁修 |
|---|------|------|--------|
| A1 | **NORTH_STAR 修订过期** | 文内写"下次必修订日期 2026-05-20"，今天 6/10，过期 21 天。作者每月手动更新，AI 不得代改 | **作者** |
| A2 | **CLAUDE.md 代际表没记 r2** | 代际管理表只有 r0 / r1；"代码结构总览"还写"bookscope/agent/ — r1 查询时智能代理"。实际 r1 runtime 5/15 已删，现行协议是 r2 | AI 可改，建议作者过目 |
| A3 | **ADR-001~005 长期草案** | 创建于 4/20，47+ 天未签。其中 ADR-004（upload 端点）/ ADR-005（session 持久化）的代码早按副管理推荐方案实现了（books.py upload 端点、JSONFileSessionStorage 都在跑）——设计文档比现实落后一整个代际 | 作者补签或明示"事后追认" |
| A4 | **代码注释过期** | `bookscope/agent/tools/search_chunks.py:88` 和 `backends/r0_search_chunks.py:103` 的 TODO 还写"骨架占位、待接 FAISS+BM25"，实际 SessionVectorStore 早接上了 | AI 直接修 |
| A5 | **STATE.md 过长** | 1304 行，十七波全文堆叠。第十一波之前的内容早无人读，该归档瘦身 | AI 直接做 |

### B. 实验与验证欠账

| # | 断点 | 事实 |
|---|------|------|
| B1 | **exp-001 从未跑** | NORTH_STAR 4/20 写的本月方向核心验证（r1 vs r0 vs 微信读书 AI vs ChatGPT 对比报告）状态还是"待 r1 首版可跑后执行"。r1 早可跑了（现在连 r1 都退役了），这个实验一直没人回头补。北极星的两条验证指标（引用精度 > 80% / 回答深度优于对照）**至今没有数据支撑** |
| B2 | **exp 编号断号** | 只有 001 / 002 / 005 / 006，缺 003 / 004。003 大致对应训练污染 probe（实际做了但没立项归档），004 对应跨题材稳定性（计划 Sprint 3 窗口跑，未启动） |
| B3 | **exp-002 结论混淆** | 第 26 轮一次变了三个变量（generator + prompt + 书），结论没法归因，文档自己标了"待补" |
| B4 | **reviewer 评分链路断** | minimax 当 reviewer 稳定拒答（exp006 60/60 全空）。多 provider 兜底排在 Sprint 7，等作者批 key——在那之前所有质量评分实验都跑不了 |

### C. 时间线错位

| # | 断点 | 事实 |
|---|------|------|
| C1 | **Sprint 3 验收窗口明天（6/11）到期** | QA 4 本书 × 3 batch + RE 数据分析报告没启动。STATE 写"5/29 进窗口自动启动"，但 5/19 之后没有任何 session 跑过 |
| C2 | **ROADMAP 时间线名存实亡** | Sprint 6（计划 7/10-7/23）和 Sprint 8（计划 8/7-8/20）都在 5/15 提前两个月做完；Sprint 3（5/29-6/11）反而卡死。按编号顺序读时间线已经对不上现实，需要一次重排 |
| C3 | **仓库停摆 22 天** | 最后 commit 2026-05-19。自主循环约定"每 30 分钟一轮"实际依赖作者开 session，这 22 天的空白说明"24/7 自主推进"在没有外部触发时不存在——这是工作手册描述与现实的差距，值得在 WORKFLOW 里写实 |

## 四、没坏的部分（盘点确认）

- r1 删除干净：runtime 物理消失、import 链零残留、780 测试零收集错误
- ADR 编号连续、case-study 引用链完整、commit hash 链可追溯——第十五~十七波的留存纪律是好的
- 匿名化检查：盘点过程未发现真名 / 公司名泄漏
- 三层缓存、五层兜底链、provider-agnostic 抽象都有对应 ADR / chapter / memory 三处留存

## 五、副管理 take · 处理顺序

1. **作者不可替代（最优先）**：NORTH_STAR 月度修订（A1）。它过期意味着"本月方向"还停在 4 月——而 4 月方向的核心验证 exp-001 至今没跑（B1），两件事合在一起是真正的方向性空洞：**北极星声称要证明的事，没有实验证明过，且北极星本身已过期**。建议作者修订时直接决定 exp-001 是补跑还是改写成 r2 口径
2. **作者一句话能解决**：ADR-004/005 补签或追认（A3）；Sprint 3 窗口处置——补跑或正式延期重排（C1/C2）
3. **AI 直接修，无需批准**：过期 TODO 注释（A4）、CLAUDE.md 代际表（A2，改完给作者过目）、STATE 瘦身（A5）、exp-003/004 编号补档（B2）
4. **等外部条件**：reviewer 多 provider 兜底等 key（B4）

以上 1、2 已写入 `docs/internal/FLAGS.md`"需作者决策"区。
