> 🗄️ **历史内部文档 / HISTORICAL**
> 本文是早期内部工作文档，可能包含已废弃方向（论文垂直、托管/Docker、沉浸阅读器等）。
> **不是当前设计依据**；当前唯一设计依据：[docs/CURRENT_DESIGN.md](../../CURRENT_DESIGN.md)

# BookScope 工作手册（WORKFLOW）

怎么干活、什么自动做、什么停下问。**每 session 必读。**

分工:项目目的 / 底线看 `NORTH_STAR.md`,在做什么看 `ROADMAP.md`,告警看 `FLAGS.md`,上轮交接看 `STATE.md`,auto-accept / escalation 边界看 `DEPUTY_MANAGER.md`,主循环 / 续跑看 `AUTOLOOP.md`。本手册只讲操作方法,不重复那些文件的内容。

> 历史:早期版本是「CEO + AI 团队 24/7 每 30 分钟自动循环」蓝图,那套从未真跑起来,原文已删。现状是**作者开窗口 = 主 Claude 进副管理姿态**,接高层指令自动拆解推进。下面是现状的规矩。

---

## 一、当前运行方式

- **代际**:runtime 走 r2 协议（OpenAI function calling,`bookscope/agent/loop_r2.py`）。分支名仍叫 `r1-agent-loop`。
- **测试对象**:多本公开书（明朝 / 安史 / 制内市场 / 亏成首富 等）+ 公文 + 会议三垂直,不是单一基线。见 `tests/file/`。
- **成本**:默认 DeepSeek 最便宜档 `deepseek-v4-flash`、禁 GPU（硬规矩,见 CLAUDE.md + memory `feedback_no_gpu` / `feedback_china_llm_first`）。**不是**"成本不设红线"。
- **每 session 按序读核心文件**:`CLAUDE.md → NORTH_STAR.md → ROADMAP.md → FLAGS.md → STATE.md → 本手册`。读完才判断本轮任务,顺序不可倒置。

## 二、工作原则

1. **原文证据为本**:任何分析结论必须带可追溯的原文引用;没有原文支撑的结论一律不输出。这是立身之本。
2. **代际 ≠ commit 版本号**:r0/r1/r2 标架构代际（思想转变）;commit 走 conventional commits（日常迭代）。两者分开不混用。
3. **痕迹可检索**:决策 / 实验 / 设计落 `docs/` 对应目录,未落盘的决策不存在。
4. **设计优先**:非自明的开发先设计后写;走 skill `design-first`（任何开发先设计）/ `vertical-design`（新垂直照七步）。

## 三、副管理模式（默认姿态）

作者开窗口即视为副管理上线,口头"开始 / 继续"即批准,不等电子签名。接高层指令自动拆解、连续推进,不为每步小决策停。

- **小事自动做不请示**:命名、测试用例、子项权重、commit 措辞、依赖 patch、文案微调等。完整 auto-accept 清单见 `DEPUTY_MANAGER.md` 第二节。
- **大事停下问**:代际升级、NORTH_STAR 改动、破坏性 git、对外 push / 发布、红色告警 override、作者点名要请示的。完整 escalation 清单见 `DEPUTY_MANAGER.md` 第三节;push 必须作者明确点头（memory `feedback_push_requires_signoff`）。
- **多 role 无依赖并发派**:一轮里多个角色的活没依赖关系就并发（单消息多 Agent）,有强依赖才串行（PE 出 prompt → BE 接 → QA 验）。
- **任务完成即沉淀**:每完成一项（不是每轮）走"任务完成 checklist"——存可复用 fact 进 memory、写一行复盘到 STATE、查规则文件要不要改。细节见 `AUTOLOOP.md`。
- **作者不可替代的事不代做**:方向复核、代际 ADR 签字、case-study 定稿（见 CLAUDE.md「作者不可替代的事」）。

## 四、作者给问题点 → 标准处理流程（列清单 → 记录在册 → 一一解决）

作者实测后常一次甩多个问题点（多带截图 / 实例）。**每个问题点都要走完整闭环,不许有的建任务、有的随手做就忘了登记**（2026-06-30 作者明示:列清单、记在册、一个个解决到关闭,并把这套流程记牢）。五步:

1. **列清单**:当场把每个问题点拆成独立一条,一条一个问题,不合并糊弄。
2. **溯源诊断**:逐条刨根,先看是不是通用根因而非个案（守 `feedback_global_not_single_case`）。是 bug 找错误类别、是设计问题给 take。
3. **记录在册**:每条 `TaskCreate` 进任务清单（任务清单就是"册"）;严重 / 跨功能的同时进 `ROADMAP.md` 带验收标准。**先登记再动手**,哪怕随手能改的小修也先建一条任务。
4. **一一解决**:小修直接做、大件走 design-first;解决一条就 `TaskUpdate` 标 completed,全程可追踪、不丢。
5. **收口汇报**:哪些已解、哪些在做、哪些 design-first 待作者批,一次说清,对得上任务清单。

判据:作者问"那个问题解决了吗",应能在任务清单里一条条指出状态,而不是靠回忆。出处与教训见 memory `feedback_issue_intake_workflow`。

## 五、问题分级与方法论（遇到难题怎么升级）

- **零层（日常）**:构建、修缺陷、跑工具读书。
- **一层（中等难点）**:工程层穷举 3–5 个已知方案,1 天内验证,挑合适的落地。
- **二层（真难题、领域前沿）**:升研究层走论文汲取五步——① 问题重述（学术语重写）② 关键词 3–5 个 ③ 检索（Semantic Scholar / arxiv）④ 筛选精读前 3–5 篇,只记方法核心 + 对 BookScope 的启示 ⑤ 48 小时内回工程层验证。研究笔记落 `research-notes/`,**强制末三字段**:拟尝试 / 实验日期 / 实验结果,缺则视为未完成。

判错层级代价高:一层误升二层浪费研究预算,二层压在一层反复徒劳。

## 六、架构代际管理

- `r0-baseline`（v7 三阶段流水线,已冻结）/ `r1-agent-loop`（分支名,runtime 已走 r2）/ `r2`（OpenAI function calling,当前）。
- 代际升级必须写 ADR 并由作者签字;日常工程演进走 commit、不动代际标签。每代开独立分支,main 只合并经验证的代际。

## 七、文档结构（实际）

- `docs/internal/`:运行文件（NORTH_STAR / ROADMAP / WORKFLOW / STATE / FLAGS / AUTOLOOP / DEPUTY_MANAGER）+ `case-study/`（对外交付）+ `experiments/` + `research-notes/` + 各审计 md。
- `docs/design/`:设计书 WP-*。`docs/architecture-decisions/`:ADR。`docs/images/`:图。
- **内部资产不进公开仓**:STATE / FLAGS / .claude / CLAUDE.md / memory 等 gitignore;跨机器靠私有仓 `BookScope-internal` + `sync.ps1`（memory `project_internal_sync_repo`）。

---

本手册随 `NORTH_STAR.md` 复核时一起过;大调整走 ADR。
