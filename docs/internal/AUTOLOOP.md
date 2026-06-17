# 全自动循环规范

本文件写给把 BookScope 当 24/7 自跑系统的人看。副管理（也就是主 Claude）每次进 session 后按本文件描述的算法走，不再凭直觉判断"下一轮干什么"。

`WORKFLOW.md` 是项目长期工作手册，讲方向、原则、节奏。本文件只讲一件事：循环怎么转起来不卡死。

---

## 一、循环每轮的输入和输出

每轮开始读这五份文件，按顺序读。前一份没读完不读下一份：

1. `CLAUDE.md` —— 项目硬规则（匿名化、commit 格式、技术栈约束）
2. `docs/internal/NORTH_STAR.md` —— 方向和不变量
3. `docs/internal/FLAGS.md` —— 告警，命中红色条件本轮直接停
4. `docs/internal/STATE.md` —— 上轮留下的状态和任务队列（重点是第三节定义的队列结构）
5. `docs/internal/WORKFLOW.md` —— 工作手册，平时知道在哪儿，不必每轮通读

每轮可能写：

- `docs/internal/STATE.md` —— 必写。每完成一个大步骤把状态更新进去
- 项目代码、文档、实验数据 —— 按当前任务需要写
- git commit —— 一组改动跑通测试且属于同一个目的就 commit，按 CLAUDE.md 四要素格式

---

## 二、循环主算法

```
每轮执行：

  files = 读核心文件()

  如果 files.flags 有活跃红色告警:
      在 STATE.md 写"循环暂停，等作者处理告警 X"
      停下不再循环

  task = 从 STATE 队列取下一个任务()

  如果 task 为空:
      task = 走 filler 算法()

  如果 task 卡在等作者物料:
      把 task 标 blocked，记原因到 STATE
      继续从队列取下一个 ready 任务（跳过 blocked）
      如果取不到，走 filler

  执行 task
  更新 STATE.md（任务状态 + 大步骤汇报）

  # 轮内沉淀（第 30 轮起强制）—— 详见第十一节
  跑完任务后立即走"任务完成 checklist"：
    1. 沉淀 memory（这次学到了什么 fact 是下次 session 还要用的）
    2. 写一行复盘到 STATE 末尾"轮内复盘"小节
    3. 检查是否要修订 AUTOLOOP / NORTH_STAR / CLAUDE.md（多数情况不要）

  如果 task 完成且到达 commit 节点:
      按 CLAUDE.md 四要素格式 commit

  下一轮继续
```

主算法不复杂。复杂的是后面三件事：取任务怎么取（第三节）、队列空了怎么办（第四节）、什么算"卡在等物料"（第五节）。

---

## 三、任务队列结构

队列写在 `docs/internal/STATE.md` 的"任务队列"小节，每个条目长这样：

```
### Task #N · <一句话标题>

- priority: P0 / P1 / P2 / P3
- status: ready / in_progress / blocked / done
- blocker: <仅当 status=blocked 时填，写阻塞原因>
- next_action: <下一步具体动作，能直接执行那种>
- notes: <可选，背景说明、相关 commit、相关文件>
```

priority 怎么定：

- **P0** —— 作者本 session 明确指令的事。"现在去做 X"
- **P1** —— 直接服务 NORTH_STAR 三条目的之一，且 AI 自己能跑完
- **P2** —— 工程严谨度类。跑了好，不跑也不影响主线
- **P3** —— 保底任务，队列空时拿出来做（见第四节 filler 算法）

`pick_next_task` 怎么挑：

1. 先按 priority 高低，P0 > P1 > P2 > P3
2. 同优先级里取 id 最小（先进先做）
3. status=blocked 的跳过
4. status=in_progress 的优先继续推进，不要切换上下文

---

## 四、Filler 算法（队列空了怎么办）

队列里没有 ready 状态的任务时，按下面顺序找事，找到一项就停：

1. **`docs/internal/case-study/` 下有未写的章节** —— 写下一章草稿。题材按时间顺序补：第 26 轮"训练污染那一晚"是现成的好素材
2. **当前代际有 ablation 数据空缺** —— 跑那个 batch。判断"空缺"看 `docs/internal/experiments/data/` 里有没有缺角的对照组
3. **`docs/internal/experiments/00X-*.md` 有起草中的实验设计** —— 把它写完，但不擅自跑（跑实验前看是否需要作者准备物料）
4. **STATE.md 历史轮次堆太多没归档** —— 把 6 轮以前的内容挪到"已完成"小节
5. **以上都没事可做** —— 在 STATE 末尾"副管理建议"小节写一句"队列已空，建议 X 或 Y"，然后停

filler 不是凑数。每件 filler 任务必须直接服务于 NORTH_STAR 三条目的之一。如果连 filler 都凑不出真有意义的事，就老实停下。**不要为了让循环不空转而编造工作**。

---

## 五、必须停下等人的事（escalation 三类）

只有三类。其他全自动。

### 物料类 —— 等作者提供输入

- **作家私稿 + 配套作家题** —— NORTH_STAR 第 1 条的真验证回路。AI 不能代写小说草稿、不能代出题
- **自试笔记** —— CLAUDE.md 第五节第 1 条，作者本人用 BookScope 的体感记录

物料类任务在队列里标 `blocked: 等作者提供 X`，AI 自动跳过去做下一个 ready 任务。

### 签字类 —— 等作者亲手批准

- **`docs/internal/NORTH_STAR.md` 内容修订** —— 任何字段改动
- **代际升级 ADR 末尾签字** —— `r1 → r2` 这种切换
- **case-study 章节定稿** —— 注意：**草稿不算定稿**。草稿 AI 该写就写，定稿才是仪式

签字类任务在队列里标 `blocked: 等作者签 X`。

### 风险类 —— 等作者授权破坏性操作

- 远程仓库的任何 push（包括 push 到 origin）
- `git push --force` / 分支删除 / 历史改写
- main 分支合并、PR、release、tag
- 与外部账号、第三方服务的写操作

风险类任务**不进队列**，遇到时直接在 STATE 里写"需作者出手 X"，等作者来了再做。

### 不在以上三类的事，AI 全权处理

明确列举几件 AI 自决、**不要再问**的事：

- prompt 版本迭代（v3.1 → v3.2 → v3.3...）
- batch 跑实验、跑测试
- commit 改动（本地 commit，不 push）
- 文件命名、字段命名、测试用例构造
- case-study **章节草稿**起草和修订
- 实验设计文档起草
- ADR 起草（除了末尾签字位）
- STATE.md / FLAGS.md 格式调整（不改告警条件本身）
- 依赖 patch 升级、ruff 自动修复
- 重命名分支（非代际级分支）

如果某件事你判断不准是不是 escalation，按可逆性问自己：做错了能十分钟内改回来吗？能的话就做，做完写到 STATE 给作者看；不能的话停下问。

---

## 六、失败重试矩阵

碰到下面这些情况按这表处理，不要每种失败都现场想新策略。

| 失败类型 | 怎么办 | 上限 | 还失败时 |
|---|---|---|---|
| API 5xx | 指数退避 | 3 次 | 切 provider，没备用 provider 就标 task blocked |
| API 4xx 限流 | 等 60 秒重试 | 3 次 | 标 task blocked，跳到下个任务 |
| API key 失效 | 不重试 | — | 标 task blocked + STATE 写"key 过期，需作者更新" |
| LLM 输出格式错 | 走 autofix 链 | 3 次 | 把 trace 写到 STATE，跳过该题 |
| 测试挂 | 修代码 | 不限次 | 测试不绿坚决不 commit |
| git 操作被拒 | 不重试 | — | 走 escalation 风险类 |
| 文件冲突 | 读现场判断 | — | 不确定就停下，不要硬 merge |

---

## 七、什么时候 commit

commit 的判据：

- 一组改动跑通测试
- 改动属于同一个目的（不要把"改 prompt"和"重构 batch runner"塞进同一个 commit）
- 测试是绿的（红的不 commit）
- 作者没在窗口内说"先别 commit"

不为 STATE.md 单独 commit。STATE 改动跟着触发它的那组工作一起 commit。

长 batch（5 题以上的实验）跑完一轮就 commit，不必等 5 轮全跑完。

commit message 一律按 CLAUDE.md 四要素格式（目的 / 过程 / 结果 / 变化），不省略也不缩写。

---

## 八、什么时候停下不再循环

只有这四种情况：

1. 作者在窗口内说"停"、"先放一下"、"我要亲自处理"
2. 队列里所有任务都 blocked，filler 也找不到合 NORTH_STAR 的事做
3. `docs/internal/FLAGS.md` 有活跃红色告警未解除
4. 当前 session 上下文接近上限（这是 harness 层的事，不是循环逻辑要管的）

停下时把当前状态写清楚到 STATE.md 末尾，让下一次启动的 session 接得住。

---

## 九、跨 session 续跑

BookScope 的循环不靠 cron，靠 session 启动 + STATE.md 续跑。具体：

- session 关闭 = 当前轮停。下次 session 启动 = 接着上次 STATE 跑
- 每轮的"上下文"都从核心文件里重读，不依赖 session 内存
- 这意味着每轮工作到一半就要把"下一步预定动作"写进 STATE，否则下次接不上

如果在 `/loop` 的动态自定步模式下跑（用 `ScheduleWakeup`），节奏建议：

- 当前在跑长 batch（10–20 分钟级）→ 270 秒醒一次查状态
- 当前在等 API key、等作者物料 → 1200–1800 秒探一次
- 当前队列全 blocked → 不要硬醒，写"等指令"到 STATE 后停

---

## 十、和其他文件的关系

- `CLAUDE.md` 硬规则压过本文件。匿名化、commit 格式、四件作者不可代做的事，本文件不重复，但任何地方冲突都以 CLAUDE.md 为准。
- `NORTH_STAR.md` 方向压过队列优先级。如果队首任务和 NORTH_STAR 不一致，立刻在 STATE 标"方向漂移"，不执行
- `FLAGS.md` 红色告警压过一切。任何告警活跃时本文件停摆
- `WORKFLOW.md` 是工作手册，本文件是工作手册的一节"循环怎么跑"的细化。两者不矛盾时本文件描述更具体
- `DEPUTY_MANAGER.md` 是副管理姿态的职责说明。本文件描述算法，副管理文档描述职责，两者互补

---

本文件 2026-04-30 起草，起因是循环卡在"作者决定方向，AI 不自选"。后续修订需走 ADR 流程，不能由副管理自己改。

---

## 十一、自我进化与轮内沉淀

第 30 轮加。起因：作者两次发现 AI 在跨 session 时丢上次的事实（anshi.epub 路径上次给过没存、astron 失效要全删却散落在六个文件、minimax context 200k 不知道）。AI 团队成员不能每次都从零开始，必须有"做完一件事 → 立刻把可复用的 fact 沉淀下来"的硬动作。

### 任务完成 checklist（每完成一项立即走，不等到一轮末）

跑完一个任务（包括 filler 任务）后**必走**这三步，再考虑 commit：

#### 1. 沉淀 memory

问自己：这次跑下来，有哪条事实是**下次 session 启动还需要知道**的？典型例子：

- 新的 API key 形态、provider 默认 base_url、context window 上限
- 某个 provider / 模型的稳定坑点（minimax 内容审查 / 长 reviewer 截断）
- 作者口头表达的偏好规则（中文像中文 / 不戏剧化自责）
- 某个测试资料的路径（epub / 题集）
- 某个数据点本轮拿到了（exp002 段 1 双批 18.0 / 17.33）

写法：

- 已有 memory 文件描述同一事实 → **更新它**（不是再开一份新）
- 没有 → 新建文件，类型按 [feedback / project / reference / user] 选；MEMORY.md 加一行索引（≤150 字符）
- **不要**把代码模式、git 历史、debug recipe 写进 memory（这些读源码就有，memory 是"读不到的事实"）

写完默念一遍：下次完全失忆的 session 启动后，能不能靠这条 memory 接得住。能就留，不能就改。

#### 2. 写一行复盘到 STATE

每个完成的任务写一句话进 STATE 的"本轮工作焦点"小节末尾或单独"轮内复盘"小节：

- "做对的事" —— 一句话
- "做错的事 / 早该想到的" —— 一句话（如果有）

复盘是给自己看的元信息，不要堆术语，别写"surgical 修"那种。

#### 3. 检查规则文件是否要修订

只在以下 trigger 才动：

- 同类失败连续两次以上（说明规则有 gap）
- 作者明确指令"以后每次都 X"（说明要落地成 hook 或硬规则）
- 发现 AUTOLOOP / CLAUDE.md / NORTH_STAR 里某条已经过时（如 astron 还在引用）

**不要**为了"显得在进化"而频繁改规则。规则修订是慢动作。

### 什么不属于自我进化

避免误用：

- ❌ 把每次跑实验的具体数字写进 memory（数据点放 STATE / experiments/）
- ❌ 把 commit message 内容复制进 memory（commit 自己有历史）
- ❌ 写"我学到了 XYZ 哲学"这种空话（沉淀的是可执行 fact，不是反思日记）
- ❌ 改 NORTH_STAR / 代际级规则（这是签字类，AI 不自决，见第五节）

### 跨 session 续跑的额外要求

session 关闭前最后一个任务完成时，特别注意：

- 把"下一步预定动作"写到 STATE 末尾（已经在第九节强调过）
- 把这一 session 攒下的 memory 一次性 review，避免散落在不同任务记录里
- 如果发现某条 memory 与现 fact 冲突（比如 astron 已下线但 reference_astron_*.md 还存在）→ 改 / 删，不留鬼影

---

本节 2026-04-30 起草，第 30 轮起生效。修订门槛同第一版（要走 ADR）。

---

## 十二、团队并发流程

第 33 轮第七部分加。起因：作者锤"完全可以在各种情况下都实现团队的并发流程"——BookScope 是多 agent 团队（见 CLAUDE.md "团队架构"节），role 之间的 deliverable 没有依赖关系时**必须并发**，串行只在有强依赖时。

### 主算法补充（第二节主算法外加这一步）

```
取下一 deliverable 时：

  active_sprint = 读 ROADMAP 当前 sprint
  candidates = active_sprint 里所有 [ ] / [~] / 未阻塞 的 deliverable
  
  按依赖关系把 candidates 分组：
    - 独立组 A：deliverable 之间无依赖（如 BE 改 batch runner / FE 接 SSE / RE 起草 chapter / QA 写 benchmark 脚本）
    - 依赖组 B：有先后依赖（如 PE 起 v3.5 prompt → BE 接通 → QA 跑 batch 验收）
  
  独立组 A 全部启动并发：
    单条消息里多 Agent tool call 同时跑 —— 比如：
      Agent(subagent_type=bookscope-researcher, prompt="起草 chapter-05 性能优化")
      Agent(subagent_type=bookscope-qa-engineer, prompt="写 benchmark_latency.py")
      Agent(subagent_type=python-reviewer, prompt="审 BE 已改的 batch runner")
    这 3 个 agent 在同一次 tool call 里并发跑，结果一起回来
  
  依赖组 B 串行启动：
    PE 起 v3.5 完成 → 才 BE 接通 → 才 QA 验收
    每步完成才进下一步
```

### 哪些 sprint deliverable 通常是独立组（默认并发）

- **跨 role 独立工作**：BE 改 backend / FE 改 UI / RE 写章节 / QA 写测试 / PM 改文档——这些是默认**全部并发**
- **同 role 多任务**：QA 跑 anshi batch + mingchao batch 同时（同 minimax key 5 并发已验证）
- **probe 类**：probe 设计（RE）跟跑 probe（QA）可以并发设计中跑现成的

### 哪些是依赖组（必须串行）

- **PE → BE → QA**：prompt 改 → loop.py / adapter 接通 → batch 验收
- **BE → FE**：BE 出 API → FE 接入
- **RE probe 设计 → QA 跑 probe**：脚本要先写完才跑
- **作者签字 → AI 启动**：代际升级 / NORTH_STAR 改 / OSS 公开等

### 并发上限与限流

- minimax key 同时 5 并发已验证 OK（第 31 轮 probe + 第 33 轮第三部分 3 batch 并发 + 第五部分 2 batch 并发都跑通）
- 同时启动 ≥ 6 个 agent 的场景实际不多——一个 sprint 平均 5-7 个独立 deliverable，5 并发已经够推
- 失败 → 按第六节失败重试矩阵处理

### 写实战例子

第 33 轮第三部分作者批"按你的建议来"时启动了：
- v3.2 anshi rerun 第 4 次（QA）
- v3.2 anshi rerun 第 5 次（QA）
- v3.3 anshi 第 1 次（QA + 跑新 PE 出的 prompt）

3 个 batch 并发 ~ 17 分钟一起出。如果串行要 50 分钟。这是团队并发的具体收益。

第 33 轮第三部分还可以加上**期间 RE 起草 chapter-04**（不烧 token / 跟 batch 并行），最大化每一段 wall-clock 时间。

### 不并发会浪费什么

- **wall-clock**：3 件独立工作串行 = 3 倍时间
- **token 利用**：等 batch 跑时主 Claude 闲置 = 浪费
- **作者等待时间**：作者以为 AI 在猛干，实际 AI 等单个 batch 出来——糟糕的体验

### 反模式

- ❌ 一轮里只启动一个 agent 工作（其他 role 等着）
- ❌ 串行启动 BE 改 → FE 改 → RE 写——这三件没依赖关系应当并发
- ❌ 等 batch 完成再起下一个独立任务

### 正模式

- ✅ 单条消息多 Agent tool call（Anthropic Claude 强项）
- ✅ 后台 batch 跑期间前台启动其他 role 任务
- ✅ 跑完 batch 通知到 → 主 Claude 整理结果 + 同时启动下一组并发

---

第十二节 2026-04-30 第 33 轮第七部分起草。修订门槛同第十一节。
