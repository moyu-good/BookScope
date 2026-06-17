# WP · 把 25 分评分卡从用户界面下线 + 文档对账

> **性质：设计草稿，待作者审，批准前不动手。**
> 只出提案和对账清单，不改任何代码或现有文档。
> 提案人：moyu-good ｜ 日期：2026-06-12 ｜ 待批人：作者

---

## 1. 目的（一句话）

把给用户看的 25 分评分卡（ReviewCard）下线——同 provider 自评分天然偏高，5 维里只有 actionability 一维有区分力、其余 4 维全贴顶没区分力，给用户看这种分数是误导。这条直接执行 `docs/internal/design/2026-06-11-design-audit-conclusion.md` 第 20 行的决定："留作开发工具，不给用户看"。

reviewer 评分回路本身**不砍**——开发期评估还要用它跑 batch、看 prompt 改了有没有用。这次只切断它通往用户界面的那一段。

---

## 2. 改动范围（提案，不动手）

### 2.1 前端 ReviewCard：建议整删，不收折叠

**take：整删，不进折叠区。**

理由：

1. 评分本身没区分力。审核结论说得很直白——4 维贴顶、只剩 actionability 一维有信息量。一个没区分力的分数，收进折叠区还是给用户看，本质没变，只是藏深一点。藏起来的误导还是误导。
2. trace 折叠区（`web/src/App.tsx:1764-1769` 那个 `<details>`）的定位是"可观测性 / 给好奇用户看 agent 怎么跑的"，放的是 iteration 数、duration 这类**客观事实**。评分是 LLM 主观自评，性质不一样，塞进 trace 会污染 trace 的"都是事实"语义。
3. 开发者要看评分不靠前端——靠 batch 输出和 trace 落盘（reviewer 回路保留，见 2.2）。前端折叠区对开发者没增量价值。

所以 ReviewCard 在用户界面**整个移除**：

- `web/src/App.tsx:1087` `<ReviewCard review={review} onRedo={handleRedo} />` 这一行删掉。
- `web/src/ReviewCard.tsx` 组件文件：暂留还是删，看下面"重答交互"的处置——`buildPreviousReviewHint` / `PreviousReviewHint` 类型可能还有用，别一刀切删文件，先删用法。

### 2.2 "建议重答"交互：跟着下线，不换别的触发方式

**take：重答这个交互整个取消，不换成手动按钮或别的形式。**

现在的重答逻辑（`web/src/App.tsx:214-229` ReviewCard 里的按钮 + `App.tsx:859-861` handleRedo + `runAsk(previousReview)`）依赖两样东西：① 总分 < 18 触发 `suggest_redo`；② 把上次 5 维评语当"上次哪里没答好"喂回 generator。

这两样都站不住：

1. 触发条件 `suggest_redo`（总分 < 18）本身基于那个没区分力的分数。分数不可信，"建议重答"的建议就不可信——可能该重答的没提示、不该重答的瞎提示。
2. "带上次批评重答"喂回去的是 5 维评语，其中 4 维贴顶评语没信息量，等于拿没用的反馈让 generator 再赌一次。

用户要重问，本来就能改一下题目重新提问——这是更直接、更可控的路径，不需要一个基于坏分数的自动按钮。所以重答交互**直接取消**，不保留、不换皮。

> 注：generator 端接收 `previous_review` 的入参（`App.tsx:353` `body.previous_review`、`streamAskAgent` 的 `previousReview` 参数）属于前后端接口，删用户侧按钮后这条入参就没人传了。后端要不要保留这个可选参数是 BE 的事，本草稿不动后端代码，只标一句：**前端不再发 `previous_review`**。

### 2.3 后端 reviewer 回路：保留评分，切断送往用户的 SSE

**边界怎么切：review 事件不再发给前端用户路径，只进 trace / batch。**

现状：review 事件照样 streaming 推给前端（`App.tsx:934-957` runAsk 里处理 `event.type === "review"`，写进 `setReview`、回填 `answer.review`、写历史 `entry.review`）。

提案的切法，按"改动最小 + 边界最干净"排，给两个方案，推荐第一个：

**方案 A（推荐）：后端照常跑 reviewer 评分，但 review 不再作为 SSE 事件推给 `/api/agent/ask/stream` 的用户路径；评分只落 trace（开发期从 trace / batch 输出读）。**

- 好处：前端彻底收不到 review 事件，App.tsx 里整段 review 处理逻辑（`934-957`）连同 `review` state、`Review` import、历史里的 `entry.review` 字段都能干净删掉。前后端边界清晰——用户路径不碰评分，评分是纯后端开发产物。
- 这是 BE 的活（改 SSE 发什么），本草稿只提边界，不写后端代码。

**方案 B（次选）：review 事件继续发 SSE，但前端收到后丢弃不渲染。**

- 不推荐。事件还在网线上跑，前端要写"收到但忽略"的死代码，边界含糊，将来有人误以为还在用。除非 BE 说改 SSE 成本高，否则走 A。

无论 A 还是 B，前端可见行为一致：**用户看不到任何评分卡、看不到重答按钮**。区别只在后端 SSE 还发不发、前端要不要留死代码。

**reviewer 回路保留的部分（明确不动）**：

- batch 评估链路照常跑 reviewer，分数进 batch 归档——这是 prompt 迭代的正回路（memory `project_ai_as_judge_pipeline.md`），是 BookScope 改进的命根子，绝不能砍。
- trace 里可以继续记 review 结果，给开发者 / 案例研究当数据。
- 这次下线的只是"用户界面这一个出口"，不是评分能力本身。

---

## 3. 文档对账清单（只列，不动文件）

### 3.1 评分卡相关（USER_GUIDE.md）

| 位置 | 现在写的 | 该怎么改 |
|------|---------|---------|
| `docs/USER_GUIDE.md:78-79` | streaming 事件列表里列了 `review` —— 25 分制评分卡 | 删掉 `review` 这一条。用户路径不再收到 review 事件。 |
| `docs/USER_GUIDE.md:214-235`（整个 §5.3 "25 分制评分卡（ReviewCard）"+ §5.4 "评分卡看哪个维度最关键"）| 教用户看 5 维评分卡、总分 < 18 点重答、哪维最关键 | 整段删。这是跟"不给用户看"决定直接打架的最大一处。删完 §5 的 5.x 编号顺延。 |
| `docs/USER_GUIDE.md:212` | "或者按 §5.3 重答" | 改成"自己改一下问题重新提问"——§5.3 要删了，引用得跟着改。 |
| `docs/USER_GUIDE.md:286`（§7.3 "答案分数低"第 1 条）| "点 **建议重答** 按钮——会换个角度自动重跑" | 删这一条。重答按钮没了。剩下的"题目改具体 / 换 provider / 通识题低分别当真"保留，重新编号。 |
| `docs/USER_GUIDE.md:284` | §7.3 标题"答案分数低" + "总分 < 18/25 时建议" | 用户看不到分数了，"答案分数低"这个入口词不成立。改成"答案不满意时怎么办"之类，按现象不按分数。 |
| `docs/USER_GUIDE.md:299`（§7.4 性能表"首字延迟"行附近）/ `:228` | §5.3 里"评分由独立 reviewer agent 跑 / 同 provider 自评 limitation 会在评分卡明示" | 跟 §5.3 一起删。 |

补一句给用户的话（建议，作者定稿时把关）：在 §5（怎么读答案）收尾处可加一行——"BookScope 内部有个评分 agent 在帮开发者打磨质量，但它的分数对你没有参考价值（同一个 AI 给自己打分会偏高），所以不展示给你。你判断答案好不好，看下面这两点就够：证据指不指得回原文、有没有给出你下一步能用的判断。"——把"为什么不给你看分"说清楚，顺带把作者认为最有用的两维（诚实 / 可操作）翻译成用户能自己用的判断标准（见第 4 节）。

### 3.2 minimax 残留（USER_GUIDE.md + Onboarding.tsx）

minimax 已彻底删（`App.tsx:29` Provider 类型只剩 `deepseek | anthropic`，memory 也记了 2026-06-11 minimax 彻底删除），文档没跟上。

| 位置 | 现在写的 | 该怎么改 |
|------|---------|---------|
| `docs/USER_GUIDE.md:50` | "推荐先选 `deepseek`（默认）；中文长书要 200k 上下文可选 `minimax`" | 删 minimax 那半句。只留 deepseek 默认 + anthropic 备选。 |
| `docs/USER_GUIDE.md:50` | "model 默认（`deepseek-chat` / `MiniMax-M2.7` / `claude-sonnet-4-6`）" | 删 `MiniMax-M2.7`。 |
| `docs/USER_GUIDE.md:51` | "base_url：选 minimax 会自动填 `https://api.minimaxi.com/v1`" | 删。base_url 现在只 deepseek 用（`App.tsx:786-789` anthropic 忽略 base_url）。 |
| `docs/USER_GUIDE.md:106-111`（整个 §3.1 "minimax"）| 教怎么拿 minimax key、base_url、model | 整段删。§3.2 deepseek、§3.3 anthropic 顺次提前编号。 |
| `docs/USER_GUIDE.md:108` | "minimax ... 评分实验一律走 deepseek / anthropic" | 随 §3.1 删。 |
| `docs/USER_GUIDE.md:131-134`（§3.4 "怎么挑"）| "写中文长篇 → deepseek 或 minimax（书特别长选 minimax 的 200k 上下文）" | 删 minimax 选项。只留 deepseek / anthropic 两条挑法。 |
| `web/src/Onboarding.tsx` | 我读了全文（102 行），COPY 三条文案（`Onboarding.tsx:58-65`）**没有提 minimax**，只讲"上传书 / 试题 / 切书"。 | **Onboarding.tsx 无 minimax 残留，不用改。** 任务背景里说的"Onboarding 大篇幅教 minimax"在当前代码里没找到——可能是早先版本已清过，或指的是 USER_GUIDE §1.4 那段填表引导（`USER_GUIDE.md:46-53`，那段确有 minimax，已列在上面 :50/:51 两行）。 |

> 校正一条背景信息：任务说"USER_GUIDE §3.1 + Onboarding.tsx 还在大篇幅教 minimax"。实读下来——USER_GUIDE 确实有（§1.4 + §3.1 + §3.4，已逐行列出）；**Onboarding.tsx 没有**。对账以实读为准。

### 3.3 清单合计

**评分卡相关：6 条要改**（USER_GUIDE 的 :78、§5.3+§5.4 整段、:212、:286、:284、:228，外加建议补 1 段用户向说明）。
**minimax 残留：6 条要改**（USER_GUIDE 的 :50 两处、:51、§3.1 整段、:108、§3.4；Onboarding.tsx 经核实无需改）。

> 都集中在 `docs/USER_GUIDE.md` 一个文件。Onboarding.tsx 这次不动。

---

## 4. 影响：用户少看一张卡，丢不丢有用反馈？

**判断：不丢真东西，但要补一个轻量替代——把"诚实 / 可操作"翻译成用户自己能上手的判断标准，不是给分。**

拆开看：

**丢掉的是什么——其实没多少。** 4 维（结构判断 / 证据厚度 / 诚实 / 跨章节）贴顶没区分力，等于一直给高分，用户看了也得不到信息。这部分丢了不可惜。唯一有区分力的 actionability（可操作），和作者认为最有用的 honesty（诚实），确实是真信号——但用一个 1-5 的数字 + 一句自评评语来传，本来就传得很糟（同 provider 自评，分数虚高，评语也偏自夸）。

**该补什么——把这两维变成用户的"自检视角"，不是分数。** 建议在答案区下方放一行很轻的提示文字（不是卡片、不打分、不调 reviewer），引导用户自己判断：

> 这条答案靠不靠谱，你自己扫两眼就知道：
> ① 关键结论后面有没有指回原文的引用？（没引用的判断打个折）
> ② 它有没有给你下一步能用的判断，还是只在复述情节？

理由：

- 这两条正好对应 honesty（敢不敢说"这里薄"、结论有没有原文撑）和 actionability（读完知不知道下一步），是作者点名最有用的两维。
- 但它把"AI 给 AI 打分"换成了"教用户自己看"——绕开了自评偏高的根本毛病。用户自己的眼睛不会自我偏好。
- 成本极低：纯静态文案，不调 reviewer、不发 SSE、不占等待时间。跟现有 Onboarding 提示卡同一个量级。

**这一步是建议，不是必做。** 最省的做法是评分卡删了就完事，答案区已有 citation 列表（`App.tsx:1738-1762`）本身就支撑用户判断"有没有原文"。是否加这行自检提示，留给作者定。我的倾向：加——它把下线评分卡这件事从"少给一个东西"变成"换个更诚实的方式给同一个价值"，更符合 BookScope "evidence-from-text、不糊弄用户"的立身之本。

---

## 5. 一句话回总

ReviewCard 用户侧**整删**（不收折叠，藏起来的误导还是误导）；**重答交互整个取消**（基于坏分数的自动按钮不如让用户自己改题重问）；后端 reviewer 回路**保留**只切断送往用户的 SSE（推荐方案 A：评分只落 trace / batch）；文档对账**共 12 条**——评分卡 6 条 + minimax 6 条，全在 `docs/USER_GUIDE.md`，Onboarding.tsx 经核实无 minimax 残留、不用动。
