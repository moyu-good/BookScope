# 给 BookScope 提贡献

欢迎。在动手之前，请先把这页读完——大概 10 分钟。BookScope 不是一个普通工具仓库，它有自己的节奏和硬规则，读完能省你和维护者双方时间。

中文为主项目。issue / PR 描述 / commit message 请用中文写，技术术语（API / SSE / agent / provider 等）保留英文原样。

---

## 1. 先理解你在贡献什么

BookScope 是一个**案例研究为核心的研究 + 产品项目**。三件事按 NORTH_STAR 优先级排：

1. 服务作者本人作为长篇网文创作者的第一读者工具
2. AI 时代以查询时智能代理 + 原文证据为核心的书籍深度分析系统
3. 沉淀一份带完整研究轨迹的案例研究文档（`docs/internal/case-study/`）

代码是实验产物，案例研究才是长线对外示人的东西。

**目标用户不只是作者本人**——任何在写长篇虚构、啃大部头非虚构、做基于原文精读的人都是 BookScope 的用户。如果你对"长文本深度阅读 / 写作"场景有共鸣，你的贡献会更容易被接受。

**案例研究定稿章节由作者亲笔润色**（项目 CLAUDE.md 第五节硬规则）。草稿章节欢迎你 PR 改错字、补论据、润色，但**定稿版本不接受外部直接 PR**——那是要对外发表的个人资产，风格判断必须来自作者。

---

## 2. 本地开发环境

需要：

- Python 3.14 或更新
- Node 20 或更新
- git

跑起来：

```bash
git clone https://github.com/moyu-good/BookScope.git
cd BookScope

# 后端
pip install -e ".[dev]"
python -m textblob.download_corpora     # 一次性 NLTK 资源

# 前端
cd web
npm install
cd ..
```

动手改之前先确认环境干净：

```bash
pytest                                   # 应该看到 526 passed
ruff check bookscope tests               # 应该 0 error
cd web && npm run build && cd ..         # FE 改之前确认能 build
```

任何一项不过，先把环境搞通再开始。**不要在测试本来就红的状态下提 PR**。

---

## 3. 代际管理（先看这一节再写 PR）

BookScope 用代际制管理大方向：

| 代际 | 状态 | 接不接 PR |
|------|------|-----------|
| `r0-baseline` | 冻结 | 不接受新功能，只接 critical bug fix（且要证明影响到 r1） |
| `r1-agent-loop` | 当前主线 | 欢迎贡献 |
| `r2-*` | 未启动 | 等 ADR-007 作者签字才会开 branch，期间不接 r2 相关 PR |

不确定你的想法属于哪个代际？先开一个 issue 问。

---

## 4. 欢迎的贡献

- **bug fix**——带最小复现步骤、复现的测试用例、修复的测试用例
- **新 LLM provider adapter**——GLM / Qwen / Kimi / DeepSeek 等国内 provider 优先。看 [ADR-003 provider adapter layer](docs/architecture-decisions/003-provider-adapter-layer.md) 知道接口契约，新 adapter 必须实现 provider-agnostic Protocol
- **性能优化**——必须带 benchmark 对比数据，参考 `scripts/benchmark_compare.py`。BookScope 把延迟当产品级问题，没有数据的"提速"不收
- **文档改进**——README / USER_GUIDE / 案例研究**草稿章节**润色、补例子、改错字
- **测试用例补强**——补缺失的边界 case、provider failure 模拟、SSE 流式断连等
- **翻译**——`README.en.md` 现在是占位文件，欢迎接手英文版
- **前端视觉 / 交互细节**——保持现有视觉词（印章红主色 + PingFang），不做风格全换

---

## 5. 不欢迎的贡献

下面这些直接 close，不要浪费你的时间：

- **内置 hosted LLM key**——BYOK 是 NORTH_STAR 不变量，BookScope 永远不绑某家 provider
- **引入 GPU 依赖**——Web 产品要在普通 CPU 上能跑，强制 GPU 的方案不收
- **破坏匿名化**——产出不得出现真实姓名 / 公司名（项目 CLAUDE.md 第一条硬规则）
- **改 `docs/internal/NORTH_STAR.md`**——作者每月手动更新，不走 PR 流程
- **改 `CLAUDE.md` 顶部硬规则段**——session 必读不能动；如果觉得规则有问题，开 issue 讨论
- **案例研究定稿章节直接 PR**——草稿可改，定稿是 Sprint 10 由作者亲笔的里程碑事件
- **r2 代际级实施**——等 ADR-007 签字
- **过度抽象 / 为假想未来设计的 PR**——CLAUDE.md 有"不为假想未来设计"硬规则。一个 PR 引入三层抽象只为应付"以后可能要"——不收
- **营销话术**——PR / issue 描述里不要写"革命性""突破""颠覆"，BookScope 不做这种文案

---

## 6. PR 流程

1. fork 仓库
2. 从 `r1-agent-loop` 起 feature 分支：`git checkout -b feat/your-feature r1-agent-loop`
3. 改代码、加测试
4. 跑过本地检查：
   ```bash
   pytest                                # 0 fail
   ruff check bookscope tests            # 0 error
   cd web && npm run build               # FE 改了才需要
   ```
5. 写 commit message——**必须四要素分节**（项目级硬规则）：

   ```
   <type>(scope): <一行 subject>

   ## 目的
   为什么做这次 commit · 回应哪个 issue / 实验结论 / bug

   ## 过程
   具体怎么做 · 关键决策点 · 放弃的备选方案

   ## 结果
   可验证的产出 · 测试通过数 · 新文件 · 新功能

   ## 变化
   文件改动 · 测试零回归 / 有回归 · 对未来工作的影响
   ```

   `type` 用 conventional commit：`feat` / `fix` / `refactor` / `docs` / `test` / `chore` / `perf` / `ci`。
   小 commit 四节都瘦但不省略；大 commit 四节都厚。

6. **不要加 `Co-Authored-By: Claude`**——本仓库全局禁用 Claude Code 自动归属，加了会被要求改

7. push 到你 fork 的分支，开 PR 指向 `r1-agent-loop`

8. PR 描述写清楚：
   - 解决什么问题
   - 怎么解决的
   - 测试计划（跑了哪些测试 / 新增了哪些用例）
   - 截图或 GIF（如果是 FE 改动）

9. 等作者或副管理 review。一般 24-72 小时内有反馈。

---

## 7. Issue 流程

**报 bug**：

- 一句话标题说清现象
- 复现步骤（最小可复现 case 最好）
- 期望行为 vs 实际行为
- 环境：Python 版本 / Node 版本 / OS / 用的哪个 provider
- 相关日志或错误截图

**功能请求**：

- 先看 `docs/internal/ROADMAP.md`——可能已经在 sprint 计划里
- 再看 `docs/internal/NORTH_STAR.md`——确认不违反不变量（BYOK / 无 GPU / 隐私 / evidence-from-text）
- 描述用户场景：你在用 BookScope 做什么 → 卡在哪 → 想要什么

**案例研究反馈**：

- 草稿章节读完发现事实错误、论据弱、行文别扭——欢迎开 issue
- 定稿章节有润色建议——欢迎 issue，但 polish 由作者亲自做

---

## 8. 测试要求

- 测试覆盖率不低于 80%
- 新功能必须带测试。优先 TDD：先写测试让它红，再写实现让它绿
- 不动现有测试，除非你正在修 bug 或 schema 变了
- `pytest` 必须 0 fail 才能开 PR

测试组织：

- 单元测试在 `tests/`
- agent loop 相关在 `tests/agent/`
- FE 测试在 `web/tests/`

---

## 9. 行为准则

- **尊重方向**——NORTH_STAR 是作者每月手动定的，不接 PR
- **批判性辅助不顺从执行**——如果你觉得某个决策方向不对，开 issue 说理由。BookScope 欢迎 push back，不欢迎"老板说啥都对"
- **中文像中文**——不要写"对 X 进行优化处理"，写"优化了 X" / "把 X 改成 Y"。禁翻译腔（"surgical 修""退避""降级""赋能""抓手"等命中即不合格）
- **短句胜长句**——一个句号一个意思
- **PR / issue 不夹塞营销话术**——没有人想读"革命性突破"
- **不在公开内容里出现真实姓名 / 公司名**——GitHub 用户名一律 `moyu-good`，作者称谓用"作者"或"项目负责人"

---

## 10. 学习路径

按这个顺序读，能最快理解项目：

**入门（30 分钟）**：

1. [README.md](README.md)
2. [docs/internal/NORTH_STAR.md](docs/internal/NORTH_STAR.md)
3. [docs/internal/case-study/chapter-01-r1-launch-and-api-first-pivot.md](docs/internal/case-study/chapter-01-r1-launch-and-api-first-pivot.md)

**工程理解（1-2 小时）**：

4. [CLAUDE.md](CLAUDE.md)——项目所有硬规则在这
5. [docs/internal/WORKFLOW.md](docs/internal/WORKFLOW.md)——工作手册
6. [docs/architecture-decisions/](docs/architecture-decisions/)——所有 ADR

**Sprint 视角**：

7. [docs/internal/ROADMAP.md](docs/internal/ROADMAP.md)——22 周 / 11 sprint 时间线
8. [docs/internal/STATE.md](docs/internal/STATE.md)——当前进度

**给作者发 PR 前最好读**：

9. [docs/internal/DEPUTY_MANAGER.md](docs/internal/DEPUTY_MANAGER.md)——理解副管理姿态，知道 review 时会被怎么质询

---

## 11. 不确定就开 issue 问

写 PR 前不确定方向对不对、是不是已经有人在做、要不要加这个抽象——**先开 issue**。一句话问比写 200 行被打回省事多了。

issue 标题清楚一点：`[question] 想加 X provider 的 adapter，是否符合 ADR-003 接口` 比 `请教一下` 好。

---

## 12. License

MIT。提 PR 即视为同意按 MIT 协议授权你的贡献。

---

谢谢你愿意把时间花在 BookScope 上。
