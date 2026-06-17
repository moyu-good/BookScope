# ADR-007 r1→r2 Migration Plan Retrospective

**时间跨度**：2026-05-13 ~ 2026-05-15，三天
**实际跨越**：Sprint 4 第一波到 Sprint 7 步骤 ④
**总 commit 数**：10（不含 STATE 头注 commit）
**测试 baseline 变化**：527（Sprint 4 启动前）→ 663（Sprint 6 收口峰值）→ 496（Sprint 7 收口）
**作者签字次数**：3 次（5/13、5/14、5/15）

---

## 一、整件事在做什么

把 BookScope 的 AgentLoop 内部消息形态从 Anthropic tool_use 切到 OpenAI function calling。表面上是协议切换，里子是把 DeepSeekAdapter 那条用了五个月的双向翻译路径砍掉——以及把"未来接任何新 provider 都要翻译一遍"这条隐性税废掉。

ADR-007 是这条切换的决策文档，Migration Plan 拆成四个 sprint：
- Sprint 4 落 r2 骨架与 adapter
- Sprint 5 跑 r1 vs r2 对照实验，等数据决定要不要切
- Sprint 6 切默认让 r2 上线
- Sprint 7 删 r1 代码完成代际清退

整个 epic 用了三天而不是四个 sprint 的八周——副管理姿态加并发派 agent 把节奏压到了原计划的三十分之一。这条压缩本身值得记下来。

---

## 二、关键决策与节奏

### 第一次签字（5/13）—— ADR 草案签字

作者口头批"签名没有问题，都可以继续"。ADR 文本本身这一刻还有 Open Questions 1-5 未答，Sprint 4 第一波 r2 骨架（commit `1c74806`）当天落地。

这是"签方向"——五条决策能不能立、loop_r2 五处改动点能不能列清、anthropic_r2 反向翻译镜像 deepseek 的工程量。签了允许花 5 agent 天落代码。

### 第二次签字（5/14）—— 切默认 r2

作者明示"按你的建议来，签字一下，我都同意"。中间隔了一天，这一天里 Sprint 5 跑完 r1 vs r2 对照实验 12 个 batch（commit `c847169`）。两本书各跑三次求 std——anshi r1 平均 15.80、r2 平均 13.79，Δ -2.01 落在容忍带 ±5.07 内；mingchao r1 平均 17.67、r2 平均 17.80，Δ +0.13 落在容忍带 ±2.47 内。两本书都不退化，撤回条件不命中。

第二次签字"签切换"。env 默认翻面会让所有 user-facing 流量直接走 r2，这一签下去 r1 进 deprecated 段位，下一个 sprint 直接走 git rm。要签这条得先看到数据。如果 Sprint 5 只跑了一次 r1 加一次 r2，看到 Δ -2.01 这条数字作者大概率不会下笔——memory `feedback_baseline_variance_first.md` 在这里第二次兑现价值。

### 第三次签字（5/15）—— Sprint 7 启动授权

作者明示"按你的建议继续，通过我的签名"。这次签字的时候 audit 报告还在后台跑，作者没看到具体影响面就先签了。这是个值得记的姿态——签字不是"看完所有细节后的精确批准"，是"基于副管理信任的高层授权 + 工程节奏约束"。

ADR-007 同步写明三条约束：(a) audit 报告产出后再执行；(b) 按报告推荐节奏分步推；(c) 每步独立 commit 加 baseline 零回归。如 audit 命中撤回条件，本签字暂停回 STATE 等复审。

这条约束后来在步骤 ③ 真的兑现了一次——见下文撤回章节。

---

## 三、audit 实际表现 vs 预测的偏差

Sprint 7 启动前花了一道 read-only audit（commit `f355593`，`docs/internal/audit/sprint-7-r1-removal-impact.md` 3500 字 9 节）。audit 给的预测和实际执行下来的数字有几处偏差，每一处都有教训。

### 偏差一：r1 runtime 行数

audit 第 1 节预测删 2150 行，实际删 1693 行。差额 457 行不是 audit 算错——是步骤 ③a（抽 25 个共享 symbol 到 `bookscope/agent/_internal/`）已经把这些行从 r1 三文件物理搬出去了。这个差额本身就是分步推方案的最好证据——audit 数字看着唬人，分步走下来其实没那么险。

如果当时没拆 ③ 成 ③a 加 ③b，直接 git rm 三文件 2150 行，r2 整套 ImportError 雪崩。先抽 symbol 后删码是顺序问题不是工作量问题。

### 偏差二：r1 测试条数

audit 第 3 节预测删约 129 条，实际删 167 条。多删的 38 条主要是 `test_adapters.py` 整文件——audit 判断"保留部分"，QA agent 看 r2 套已有等价覆盖直接整删更激进。另外 4 条是 `test_question_processor.py::TestAgentLoopIntegration`——audit 第 3.3 节把它当通用层漏判，BE agent 在步骤 ③b 现场发现 stub 形态不匹配整组删。

教训：audit 第 3 节按文件名扫描判断去留，没读到测试族内部用什么形态 stub。如果 audit 在每个保留候选文件里都跑一次"找 Anthropic content_blocks 出现频率"会更准。

### 偏差三：r2 对 r1 internal symbol 的 import 链

这是 audit 最严重的一处漏审。audit 第 5 节只审了 reviewer.py 对 r1 loop 的依赖，r2 runtime 四个模块（loop_r2 / fast_path / anthropic_r2 / deepseek_r2）对 r1 internal symbol 的物理 import 链漏了。BE agent 在步骤 ③ 跑 grep 揭出来：

- `loop_r2.py:72-95` import r1 loop 13 个常量加 5 个私有 helper 加 AgentLoop 的 2 个实例方法（当 mixin 借用）
- `fast_path.py:38-42` import r1 loop 3 个 symbol
- `anthropic_r2.py:44` import r1 anthropic 的 `_translate_error`
- `deepseek_r2.py:33-38` import r1 deepseek 的常量加 3 个 helper

这条漏审让步骤 ③ 第一次跑就触发撤回。问题深度比 audit 预估广一层——不只 fast_path 残留，r2 主循环加两个 adapter 也都还在物理依赖 r1 文件。

教训：audit 应该 grep `from bookscope.agent.loop import` 在所有 bookscope/ 下而不只是 reviewer.py。第 5 节标题写"reviewer.py r2 兼容性 audit"本身就限制了视野——下次写 audit 这种工程评估文档，节标题不要锚到某个具体文件而应该锚到"删 r1 后哪些路径会挂"这种问题层面。

---

## 四、撤回机制真兑现一次

Sprint 7 步骤 ③ 第一次跑（第十一波），BE agent 跑 grep 揭出 audit 第 5 节漏审的 import 链就守住了。没有写代码、没有 commit、写撤回判断回 STATE，提三选一推荐 take A。这是 ADR-007 第三次签字写的"如 audit 命中撤回条件，本签字暂停回 STATE 等复审"硬规则真兑现一次。

这个时刻值得放慢讲。

撤回机制不是写在文档里就完事——它要在真触发时被守住。BE agent 当时完全可以走另一条路：强删三文件，看雪崩有多大，再回头修。如果走那条路，r2 测试套立刻挂、500/500 baseline 被打破、git stash 加 git reset 来回拉扯。这条路在 commit 历史里会留下"步骤 ③ 一次失败回滚"的伤口。

副管理也完全可以越界——既然作者已经签字"按你的建议继续"，副管理可以判断"audit 漏审不是停的理由，继续推"。但 ADR-007 第三次签字的约束是我自己锚住的——"如 audit 命中撤回条件，本签字暂停回 STATE 等复审"。锚住的规则要在触发时执行，不是当条件命中时找借口绕。

作者批 take A 拆 ③a 加 ③b，整件事就顺了——③a 把共享 symbol 抽到 `_internal` 中性位置，r2 对 r1 物理 import 清零；③b git rm 三文件加改 init 翻面默认 r2 加抛 RuntimeError。两步独立 commit，零回归。

签字不等于立刻 rm -rf——签字是预先授权加节奏约束，由副管理代行节奏控制，子 agent 在执行前事前核对硬条件。三层结构都成立才推进。这条工程姿态如果将来还有代际级变更，可以直接复用。

---

## 五、副管理姿态在跨 sprint 工程里的有效性

ADR-007 Migration Plan 原本估八周（四个 sprint × 两周）。实际三天完成。压缩比例三十比一——这不是因为工程量被低估，而是因为副管理姿态加并发派 agent 把节奏压到极限。

哪些事情副管理推得动：
- Sprint 内部独立 deliverable 的并发执行（步骤 ③b 加步骤 ④ 当时本想并发，最后串行也无所谓）
- audit 类 read-only 工作单 agent 后台跑
- 测试套补全（Sprint 6 r2 mock 32 测试分三波派 QA agent）
- 文档同步（chapter-05 第七节 + 第八节 starter）

哪些事情必须停下：
- 代际级签字
- audit 撤回条件命中
- 工程姿态层的决策（take A vs B vs C）

副管理在跨 sprint 工程里最大的价值不是写代码——是节奏控制。把作者从"每个 commit 都要审"释放出来，让作者只在签字节点出现。三次签字时间间隔分别是一天加一天，节奏对得起一个工程团队的协作密度。

---

## 六、Backlog 现状

ROADMAP 五·二、Backlog 表收过的两条：

- **B-1 `Adapter.extract_final_text` 进 Protocol 契约** —— 仍是 backlog 状态。Sprint 7 r1 删完之后这条工程债的优先级从 P2 升一级是合理的——现在 fast_path 加 loop_r2 仍各自调 `extract_final_text` 模块级函数，下沉到 adapter 是对 ADR-003 protocol 抽象更彻底的归位。但不是 Sprint 7 收尾后立刻该做的事，等 r2 runtime 稳定一两轮再说。
- **B-2 reviewer 复用的 autofix 函数下沉 adapter** —— 已 ✅ done（commit `1050367`）。

Sprint 7 实际新积累的 backlog：

- `bookscope/agent/_internal/` 三个 shared 模块的命名 —— 当初叫 `_internal` 是为了 r1 加 r2 共用的"内部共享层"。现在 r1 删了只剩 r2 在用，"_internal" 这个名字的"内部共享"含义稀释了。是否要重命名为更直接的位置（如直接放 `bookscope/agent/` 顶层不带 `_internal/` 前缀，或者明确叫 `bookscope/agent/r2_shared/`），等几个月后回头看哪个名字更自然
- adapter 文件名后缀 `*_r2` —— 用户面 API 名 `AnthropicAdapter` / `DeepSeekAdapter` 已稳定，模块文件名 `anthropic_r2.py` / `deepseek_r2.py` 的 r2 后缀活在物理层。等 r3 切换那一刻这个后缀的存在才有意义；当前它只是"曾经有过 r1"的考古标记。不急着改

---

## 七、给 chapter-05 第八节定稿润色的素材接续

chapter-05 第八节 starter 已落（commit `09bd668`，2536 中文字 5 个 H3 标题）。定稿期作者要补充的几条事实层素材：

- 三次签字的精确 timestamp（已在 ADR-007 作者签字段位）
- audit 漏审第 5 节的具体 import 链（本 retrospective 第三节有）
- 撤回机制真兑现一次的副管理姿态思考（本 retrospective 第四节有）
- 副管理节奏控制的压缩比例（八周压三天，本 retrospective 第五节有）

starter 当前覆盖的 H3 五项加结尾散文段已经把核心叙事铺开。定稿润色阶段如果作者想把"撤回那一刻"从一段扩到一节，本 retrospective 第四节可以直接借用。

---

## 八、给未来类似 epic 的姿态约定

如果将来还有代际级切换（r3 切某个新 protocol、provider adapter 大重构、KG 抽取从手工切真 KG 全量化等），按 ADR-007 这次的姿态复用：

1. **先写 ADR 草案，作者签方向（第一次签字）** —— 不需要等所有 Open Questions 都答完。允许花 sprint 工程量落骨架
2. **跑对照实验，看数据决定（第二次签字）** —— baseline std 用三次跑求出来，不要单次 vs 单次对比
3. **audit 在切核心代码之前跑一道** —— audit 节标题锚到"删 X 后哪些路径会挂"这种问题层面，不要锚到具体文件名。grep 命令在每个候选保留文件里跑一次
4. **签字加节奏约束 + 撤回机制** —— 签字不是"看完一切的精确批准"，是"基于副管理信任的高层授权 + 工程节奏约束"。撤回条件硬规则要写明白，触发时副管理守住不绕
5. **代际级删码分两步** —— ①a 抽共享 symbol 到中性位置 + ①b git rm。不要一刀切

这五条不是"流程"，是基于一次实战的姿态约定。如果将来违背任何一条出了问题，回头读这份 retrospective。

---

*本文件由副管理在 Sprint 7 收尾时撰写（commit 链 `1050367` → `b29d626` → `0d4d210` → `440bcad` → `09bd668` → `7d60319`）。事实部分基于 commit message 加 audit 报告加 STATE 头注的客观记录；判断与教训部分代表副管理在执行链里的现场观察，作者复核或修订时可直接覆盖。*
