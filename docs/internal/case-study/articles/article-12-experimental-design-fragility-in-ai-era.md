# 实验设计在 AI 时代的预设错误 · 三个被现实压破的实验前提

> **状态**：草稿 · 作者未定稿
>
> slug：`article-12-experimental-design-fragility-in-ai-era`
> 视角：研究方法论
> 关联代际：r1-agent-loop / r2-agent-protocol
> 关联章节：`chapter-04-the-book-it-never-read.md` 第八节、`chapter-09-one-day-double-front.md` 第十节、`chapter-10-ingest-layer-second-cut.md` 第九 / 十节
> 关联 memory：`feedback_baseline_variance_first.md`、`feedback_global_not_single_case.md`、`reference_minimax_reviewer_limit.md`、`feedback_probe_avoid_general_knowledge.md`、`project_value_reframe_evidence_universal.md`

---

## 一、序：实验设计在 AI 时代是怎么变脆的

写软件的人做实验有一套老规矩：定假设、跑对照、收数据、给结论。这套规矩在算法领域几十年没大变——做一个 sort 算法的对照实验，跑一次 baseline、跑一次 candidate、看时间差，结论就出来了。两边的"行为"是确定的，跑一次就是真相。

BookScope 在 2026 年 4 月到 5 月这一个半月里反复撞同一面墙——**这套规矩在 LLM 实验上不成立**。不是工程出错，不是算法选错，是研究者预设了一条在 LLM 行为下根本不成立的前提，跑出来的数据没法用，被迫换一套判定方法 / 反过来重新理解 / 重写实验模板。

撞了三次，每次都撞在不同的位置——

- **第 33 轮**：拿 v3.2 baseline 单次跑 21.4 当真相去比 v3.3 / v3.4，得出"v3.3 让 mingchao 降 1.8 分"的结论，结论错了
- **第十六波**：修 ContentFiltered bug 时只盯着"内容审查"这一种错，第二天换本书撞别的错一样挂，被作者锤"针对这本书"
- **第十七波**：跑 cache 质量 probe 时预设 reviewer 能稳定拿分，结果 20 次 reviewer 调用全部返空，原撤回判定逻辑上无法走通

三次撞墙的具体场景不同——一次是 baseline 方差、一次是错误兜底、一次是 reviewer 稳定性——但归到方法上是同一条：**LLM 实验设计的前提不靠谱**。研究者预设了一个 LLM 行为的稳定性 / 确定性 / 一致性假设，跑出来发现假设不成立，整套实验设计走不通。

这篇 article 把三次撞墙串起来读，提炼三条规律，留下"下次实验前先校验前提"的研究规矩。前置阅读 chapter-04 第八节（baseline std 翻转）、chapter-09 第十节（通用兜底链补齐）、chapter-10 第九 / 十节（reviewer 限制的换指标判定）——下面每节都引这三个章节的现场作证据。

为什么三次撞墙值得单写一篇——因为撞墙的位置都不在工程上。工程层面 BookScope 这段时间跑得很顺：v3.x prompt 改进有数据支撑、错误兜底矩阵在 KG 路径上做完、cache 层 timing probe 跑出 664x / 1271x 的实测加速。但**研究层面**反复撞——三次都是预设错误压垮实验设计。这套预设错误对所有做 LLM 应用的研究者都成立——做 prompt 改进的会撞 baseline std；做错误处理的会撞错误类别覆盖；做 LLM benchmark 的会撞 provider 行为差异。把 BookScope 撞墙的现场写明，比抽象总结"实验设计要稳"更有用——后面读者撞类似的墙时知道这不是第一次有人撞，知道当时怎么校正的，可以省一段弯路。

题外补一句——本 article 跟其他几篇 article 的位置关系。article-01 讲公开书的训练污染、article-07 讲 AI-as-judge 闭环的边界、article-08 讲 provider adapter 长尾税。这三篇都各自讲一个工程现象；本 article 走更上一层，讲"研究方法本身在 AI 时代怎么变脆"——它不是工程现象，是研究者怎么读 LLM 数据 / 怎么设计 probe / 怎么做实验设计的方法层。所以本 article 跟其他三篇是互补的——其他三篇讲"撞到具体哪一面墙"，本 article 讲"为什么会撞 / 撞完该怎么改方法"。读完三篇 article 看完工程现象，再回到本 article 看方法提炼，比单看任何一篇都更完整。

---

## 二、第一次撞墙：v3.3 baseline std 翻转

时间是 2026-04-30 第 33 轮第二部分。

那一轮 PE 做 v3.3 prompt 改进——加了一个 B-2-i 子模板，针对"立场漂移题"要求至少 5 处具体章节立场示例 citation 覆盖。anshi 这本书上 v3.2 q5 的三次跑分数是 21 / 14 / 15，std≈3.8，明显是 prompt 设计缺陷不是单次 noise——v3.2 对立场漂移题没有 citation 厚度硬约束，generator 给出"立场分析"但缺具体节点 citation 支撑，reviewer 见到空洞判断扣分。B-2-i 子模板就是为这道题型设计的兜底。

跑 v3.3 anshi 3 次的数据漂亮（数据见 `docs/internal/experiments/data/exp002-anshi-minimax-v3.3-batch-{01,02,03}.json`）——

| 题 | v3.2 4 次均 | v3.3 3 次均 | Δ |
|----|----|----|----|
| q1 | 18 | 20 | +2 |
| q2 | 20.75 | 19 | -1.75 |
| q3 | 18 | 19 | +1 |
| q4 | 16.5 | 21 | **+4.5** |
| q5 | 16.67 (std≈3.8) | **18.33 (std=0.47)** | **+1.66 + 极稳** |
| 平均 | 18.04 | **19.47** | **+1.43** |

q5 三次跑分别拿 18 / 18 / 19——std 从 3.8 缩到 0.47，B-2-i 子模板提分 + 缩小波动一起做到。这条数据在 anshi 上当时就立住了，没争议。

争议出在 backward compat 那一步。要确认 v3.3 在熟悉书 mingchao 上不引入副作用，跑了一次 v3.3 mingchao（数据见 `docs/internal/experiments/data/v3.3-mingchao-minimax-batch-01.json`）——

| 题 | v3.2 (1 次) | v3.3 (1 次) | Δ |
|----|----|----|----|
| q1 节奏评估 | 22 | 18 | **-4** |
| q2 支线密度 | 21 | 22 | +1 |
| q3 伏笔回收 | 23 | 20 | -3 |
| q4 角色转变 | 20 | 17 | -3 |
| q5 设定漂移 | 21 | 21 | 0 |
| 平均 | **21.4** | 19.6 | -1.8 |

副管理当时下的判断写在第三部分的结论里：

> v3.3 让 mingchao 降 1.8 分——B-2-i 子模板对非目标题有 prompt-length 副作用。

这条判断后面被现实压破了。压破的过程值得一节一节讲。

第四部分跑 v3.4——把 B-2-i 改严（只在 q5 这种立场漂移题上启严格判别，q1 / q3 这种非目标题走 v3.2 路径），想修这个所谓"副作用"。跑出来 v3.4 mingchao 19.2 分（数据见 `docs/internal/experiments/data/v3.4-mingchao-minimax-batch-01.json`）——**比 v3.3 还低**。

到这里副管理懵了一下——v3.4 改动面比 v3.3 更窄，按理说应该比 v3.3 更接近 v3.2 才对，怎么反而更远了？

先停一下解一下当时副管理的内心戏。第三部分跑出 v3.3 mingchao 19.6（比 v3.2 的 21.4 降 1.8）时，副管理的判断是"B-2-i 子模板对非目标题有 prompt-length 副作用"——具体猜测是 prompt 长度增加让 generator 在非目标题上推理资源被挤占，导致 q1 / q3 / q4 这三道非目标题各降 3-4 分。这条猜测**可以由 v3.4 改严测试**——v3.4 把 B-2-i 限定在 q5 题型 trigger，q1 / q3 / q4 走 v3.2 原路径，那 v3.4 mingchao 平均应该接近 v3.2 的 21.4。

跑 v3.4 mingchao 拿到 19.2——比 v3.3 还低 0.4 分。

这一笔是关键。如果"prompt-length 副作用"假说成立，v3.4 改严应该让 mingchao 数据回到 21 上下；v3.4 反而更低，假说不成立。但副管理当时第一反应不是"假说错了"，是"改严做得不够窄"——想第六部分继续做 v3.5 更窄的 trigger。

是这一刻短暂的犹豫让事情转向——开始想"会不会从一开始 baseline 就不准"。如果 v3.2 自己跑 2 次 / 3 次得到的不是 21.4 而是 19 上下的数据，那 v3.3 / v3.4 跟 v3.2 比就没有"降分"这回事，连带 v3.5 整轮改严都没必要。这一念头催生了第五部分。

第五部分——回头补 v3.2 mingchao 的基线方差。跑 v3.2 mingchao 第 2 次和第 3 次（数据见 `docs/internal/experiments/data/v3.2-mingchao-minimax-batch-{02,03}.json`）——

三次跑数据：21.4 / 18.8 / 20.4，**平均 20.2 / std 1.06 / 范围 18.8-21.4**。

这一刻判断反过来了。

| 版本 | mingchao 分数 | 数据点 |
|------|----|----|
| v3.2 | 平均 **20.2** / std 1.06 | 三次跑 21.4 / 18.8 / 20.4 |
| v3.3 | 19.6 | 一次跑（在 v3.2 noise 范围内） |
| v3.4 | 19.2 | 一次跑（在 v3.2 noise 范围内） |

v3.3 / v3.4 在 mingchao 上**根本没有显著降分**——19.6 / 19.2 都落在 v3.2 自己的 18.8-21.4 范围里。"prompt 副作用"是个不存在的影子，第三 / 四部分追着它跑了一整轮。

修正后的真相反过来更漂亮——anshi 上 v3.2 → v3.3 → v3.4 分数 18.04 → 19.47 → 20.2 单调上升，是真改进；mingchao 上三个版本都在 19-21 之间，无显著差异；v3.4 是当前最优 prompt：anshi 20.2 + mingchao 19.2。

回头清算第三 / 四部分追这个"不存在的副作用"花的成本——

- 跑 v3.4 改严 prompt 设计 + 跑 mingchao 一次 batch：约 90 分钟工程时间 + 18 分钟 batch run
- 准备第六部分 v3.5 更窄 trigger 的预设计：约 60 分钟工程时间（最后没跑，回头止住了）
- 内心戏判断"是不是该撤回 v3.3"耗的注意力：第三 / 四部分整段都在这个框架里跑
- 跑 v3.2 mingchao 第 2 / 3 次补 baseline：约 35 分钟 batch run + 15 分钟数据分析

补 baseline std 的成本是 50 分钟，反而是整段最便宜的一笔——但它是最晚做的。如果第二部分 v3.3 mingchao 跑出 19.6 时就先补 v3.2 baseline std 而不是直接对单点 21.4 比较，第三 / 四 / 五部分的工作完全可以避免——省下 4 小时工程时间 + 一次抑郁式归因。**研究的工时成本不在跑实验，在因为预设错误追错方向的时间**。这一笔账后来直接进 memory `feedback_baseline_variance_first.md` 的"为什么这件事重要"段落——不是研究纪律好不好的偏好问题，是实打实的工时账。

---

## 三、校正一：baseline std 不能省

第二节那段撞墙的根因写在一句话里——**单次 LLM 跑不是真相，是一个 sample**。

传统算法实验里 baseline 跑一次就够，因为算法行为是确定的——sort 算法处理同一份输入，两次跑的输出 bit-for-bit 一致。LLM 不是这样——同一个 prompt + 同一个 input，跑两次的 trace、token 数、citation 数、reviewer 评分都不一样。LLM 行为是一个分布，每次跑给你这个分布的一个样本。

第二节的错误就出在这一步——拿 v3.2 mingchao 一次跑的 21.4 当真相，跟 v3.3 一次跑的 19.6 比，得出 Δ = -1.8 的结论。**两边都是 sample，不是真相，Δ 落在两个分布的方差范围内根本无信号**。后来补的三次跑数据证明 v3.2 自己的范围就是 18.8-21.4，v3.3 的 19.6 就在这个范围里——压根没有"降 1.8 分"这回事。

这条经验后来写进 memory `feedback_baseline_variance_first.md`，归成三条研究规矩——

**1. baseline 至少跑 3 次求 std**

跟新版本比之前，先把 baseline 跑 3 次拿到均值和 std。如果 baseline 自己的 std 比你期望看到的改进 Δ 大，那这次实验设计本身就不成立——你没法在 noise 范围内识别信号。

**2. 单点比较只能下"无显著差异"结论**

新版本跑一次得到 N1，跟 baseline 多次跑的均值 M ± std 比——如果 |N1 - M| > 2σ，可以下"可能有差异"结论；如果 |N1 - M| ≤ σ，只能下"在 noise 范围内"，不能下"无变化"也不能下"有变化"。

**3. 单调改进比单次提分可信**

v3.2 → v3.3 → v3.4 在 anshi 上 18.04 → 19.47 → 20.2 单调上升，这条信号比"v3.3 比 v3.2 提了 1.43 分"更可信——单调改进意味着不是单次 noise 巧合落在高位，是结构性改进。

这三条用 BookScope 的话说就是——**LLM 实验的"baseline"不是一个数，是一组数加它们的方差**。设计实验前要先确认 baseline 的方差，不然 candidate 跑出来的数据不知道该怎么读。

这条规律在 BookScope 案例研究里被反复印证。第 33 轮第五部分是第一次系统化写进 memory；后面 Sprint 5 R1 vs R2 protocol 比较时（chapter-08 R1 vs R2 那一段）也是按这条做法先各跑 3 次取均值；Sprint 6 cache 质量验证（chapter-10 第十节）失败后改用多证据链时仍坚持"replicate 至少 3 次才能下结论"。

回头读第二节那条 v3.2 mingchao 三次跑的数据（21.4 / 18.8 / 20.4）有个细节值得记——单看每一次跑的 trace，三次都是合理的输出，agent 走的轮数 / search_chunks 调用次数 / citation 数都在正常范围。**没有任何单次跑会让你怀疑它有问题**。问题不在单次跑——问题在"把单次跑当真相"这个研究思路。LLM 实验数据的读法跟传统实验不同——传统实验里看到一个数字写在那里就是事实，LLM 实验里看到一个数字得问"这个数字来自分布的哪个位置"。

这条思路有个具体的工程做法——data 目录下所有 batch JSON 命名约定带 `batch-01 / batch-02 / batch-03` 后缀，就是为了强制每次实验跑多次。`docs/internal/experiments/data/v3.2-mingchao-minimax-batch-{01,02,03}.json` 三个文件代表的是 v3.2 mingchao 这个 cell 的三次采样，不是三个不同实验。BookScope 后续每次 prompt 改进或 protocol 切换的实验都按这个约定跑——至少 3 次，超过 3 次的更稳；少于 3 次的数据不准下结论，只准当"探索性观察"。

还有一条隐含的规矩——**单次 baseline 看起来"漂亮"的实验结果尤其要怀疑**。第二节 v3.3 mingchao 单次跑 19.6 当时副管理读出来是"显著降分"——但如果当时停下来想"v3.2 自己的方差有多大"，就会发现这个判断没有基础。后来很多 LLM benchmark 论文报"我们的模型比 baseline 高 X 分"都有同样的问题——baseline 跑一次 vs 自家模型跑一次的比较，Δ 落在 baseline σ 范围内毫无信号。BookScope 在自己的实验上踩过这个坑之后，对所有公开 LLM benchmark 数据都自动加一层怀疑——除非论文报了 baseline std，否则单次比较的提分不能算证据。

把这条规律写进工作流的具体动作——BookScope `docs/internal/experiments/` 目录下每个实验设计文档（如 exp006）的"实验设计"节都得明写"baseline 跑 N 次 / 期望 σ 范围 / 期望识别的 Δ 量级"三个数。如果 σ 跟期望 Δ 同量级，实验设计本身不成立——要么改实验设计（用更稳定的指标 / 用更大的差距）要么先做 baseline 稳定性 probe 看能否压 σ。这是把"实验是否值得跑"的判断前置——在 batch 跑出来之前就过一道筛子。

实验数据归档的命名规范也跟着这条做法走。`docs/internal/experiments/data/<exp-id>-<book>-<provider>-<prompt-version>-batch-<NN>.json` 是默认模板——`batch-NN` 后缀强制提醒"这只是 N 次采样中的一次"。后续 batch 数据进来时按同 prefix 累加，分析时按 prefix 聚合算均值和 std。这条约定看似只是文件命名细节，实际是"不让单次数据被当真相引用"的一道工程屏障——下次有人想引 v3.2-mingchao-batch-01 当结论时，自然会问"还有 batch-02 / batch-03 吗？"

---

## 四、第二次撞墙：通用兜底链按错误实例不按错误类别

时间是 2026-05-18 第十六波，跟第一次撞墙隔了 18 天。

那天 BookScope 第一次跑作者亲选的两本新书——《亏成首富从游戏开始》（网文 4319 chunks）和《制内市场》（政经 398 chunks）。亏成首富一路跑通，制内市场撞墙：KG 抽取调 minimax 抽人名时被服务端内容审查拦下，整本书 0 角色。

副管理修的第一刀是 commit `0b0c2a9`——单 batch 撞 ContentFiltered 就返 0 角色继续抽其他 batch，整本 KG 不全挂。commit message 标题写"修制内市场全挂"。

作者第一锤打过来：

> 不能因为模型被 ban 了，我们的用户不可能有很多 api 的选择也不能因为 api 问题不让分析。

听懂的是"返 0 角色"等于把麻烦推给用户——你换个 AI 吧、你换本书吧。commit `362f0ab` 把 loop 和 reviewer 第 31 轮加的 ContentFiltered 重试 + 中性化提示移到 KG 路径：前两次原样重试碰间歇 422 就过，第三次开始 append 一段"用中性学术化措辞抽人物姓名"的提示让 LLM 自己改口。制内市场 rerun 救回 67 角色——朱镕基、桑弘羊、商鞅、康熙、雍正、乾隆这些被审查拦下的历代政治家重试后过了。

`362f0ab` 之后还有 batch 4 次重试都被拒。commit `e8bc16f` 接着做——加一层 jieba 本地 NER 兜底，重试都救不动就走本地分词补人名。commit message 标题还是"针对制内市场"那套话术。

作者第二锤打过来，这次更重：

> 你要知道我是要求所有可能的书籍和情况不要被 api 或者书籍原因 ban 掉，而不是针对这本书而已。

这次听懂的是另一层——前面两个 commit 都只盯着"内容审查"这一种错。LLMFormatError 仍直接抛、RateLimited 仍直接抛、ContextLimitExceeded 仍直接抛。换本书撞别的错一样挂。

commit `79e44f5` 把 `_do_extract` 的错误处理整个重写了一遍，五层兜底链定型——

- ContentFiltered → 重试 + 中性化 + 超限走 jieba
- RateLimited → 直接 jieba 不重试（重试还是 rate-limit）
- ContextLimitExceeded → 直接 jieba（当前 batch 太大）
- LLMFormatError → 直接 jieba（autofix 救不回的破 JSON）
- ProviderUnavailable → **不接住，让用户看见**（auth 错 / 网络挂是用户能修的配置错，静默吞反而把"key 写错"翻译成"书有问题"）

改了 4 条测试、加了 2 条新测试，每种错各一条断言——按错误类别覆盖，不是只测当前撞到的那一次。

这条经验写进 memory `feedback_global_not_single_case.md`。

---

## 五、校正二：错误矩阵按类别覆盖

第四节的错误根因写在另一句话上——**当前撞到的 bug 是某个错误类别的代表，修复要按类别覆盖不是按实例**。

这条规矩在传统软件工程里也成立，但在 LLM 调用路径上尤其重要——因为 LLM provider 的错误种类比传统 service 更宽：

- HTTP 层错误（连接挂 / 5xx）
- 认证错误（key 错 / quota 用光）
- 速率限制（429）
- 内容审查（422 + new_sensitive）
- 上下文超限（input + output 超模型上限）
- 格式错误（LLM 吐回的 JSON 解析挂）
- 间歇拒答（empty text / 服务端默拒）
- 模型行为漂移（同样 prompt 不同时间不同输出）

任何一条调用路径都可能撞上面任何一种错。修复时如果只盯着"当前撞到的那一种"，下次换本书 / 换 provider / 换时间窗口撞别的错，整条路径一样挂。

校正写成两条研究规矩——

**1. 按错误类别建矩阵覆盖**

不要按"当前 bug 现场"修。修复前先列错误矩阵——这条调用路径可能撞哪几类错？每一类的预期兜底是什么？兜底覆盖到哪一层是合理的？

KG 抽取这条路径的错误矩阵在 commit `79e44f5` 里写明了：5 类错 + 5 种处理方式 + 6 条测试覆盖。下次再有 KG 路径相关 bug 报告进来，先对照这个矩阵看是哪一类——如果是矩阵内已覆盖的类别，找具体兜底为什么没生效；如果是矩阵外的新类别，加新行覆盖。

**2. 错误兜底不只是工程动作，是产品立场**

memory `feedback_provider_agnostic_first.md` 跟 `feedback_global_not_single_case.md` 是同一条规矩的两面——provider 行为差异要 BookScope 兜底，不要让用户挑 AI。这不是"性能优化"或"代码质量"那种工程偏好，是产品的硬约束：用户不可能为每本书 / 每道题挑一个不会撞内容审查的 LLM，BookScope 自己得兜住。

这条立场在第十六波之后还往前走了一步——chapter-10 第十节那条 reviewer empty 重试 commit `0ee345d` 把同样的兜底链也接到 reviewer 路径上。第 31 轮做的是 ContentFiltered 兜底；第十六波做的是 KG 路径的通用兜底；第十六波尾巴接的是 reviewer 路径的同款兜底——三条 LLM 调用路径（generator / KG extractor / reviewer）都开始按相同的错误矩阵处理。

这个立场在第六节会被反过来锤回——reviewer 路径加了 ContentFiltered 兜底之后，下一波实验仍然撞了 reviewer 稳定拒答的墙，因为这次撞的不是"内容审查"这一类错，是更深一层的"provider 限制"。

补一段方法论侧的反思——第四节那三次锤的现场比第二节 baseline std 翻转更刺。第二节是数据自己说话——补了 baseline std 之后真相自然浮出；第四节是作者一锤一锤把规矩打过来的，每一次副管理都"听懂了"但还停在错误的层级。第一次锤之后副管理改了 commit `362f0ab`——加重试和中性化，但仍把这件事当成"修制内市场"。第二次锤之后副管理改了 commit `79e44f5`——按错误类别覆盖，但 memory 第一版写得用翻译腔（"判定标准 / 兜底链 / 触发条件 / 适用场景 / 失效情况"）。第三次锤之后才用人话重写。三层抽象——bug 修复的对象（具体书 → 错误类别）/ 兜底设计的范围（当前错 → 错误矩阵）/ 文档的语言（翻译腔 → 人话）——每一层都得作者亲自锤过才升一阶。这条经验后来写进 chapter-09 第十节"三条同根"那段：别把麻烦推给用户 / 别把规则锁死在单 case / 别用翻译腔写规则——都是"通用 vs 单例"在不同层面的同一条规则。

跟方法论侧紧贴的工程数据——commit `79e44f5` 之前的 KG 抽取测试只有 3 条（针对 ContentFiltered 那一类），覆盖不到 LLMFormatError / RateLimited / ContextLimitExceeded。`79e44f5` 之后测试改了 4 条 + 加了 2 条新测试，每种错各一条断言。测试本身就是"按错误类别覆盖"这条规矩的工程外化——如果只测当前撞到的 case，下次撞别的错也写不出 reproducible test，回归保护失效。BookScope 后面所有 LLM 调用路径的测试都按这个模式写——provider error 路径上有几类错就有几条测试，不只测 happy path。

---

## 六、第三次撞墙：exp006 reviewer 限制

时间是 2026-05-19 第十七波，跟第二次撞墙隔了一天。

那天跑 cache 质量 probe——验证 Sprint 6 的 book-level KG cache 不引入答案质量退化。实验设计写在 `docs/internal/experiments/006-sprint-6-kg-cache-validation-design.md` 第三节，撤回判定写在第六节：**5 维度子分的单维度 std ≤ 0.5 分**——即同一道题 cache 跑 vs 冷算跑的 reviewer 评分在 5 个维度上各维度方差 ≤ 0.5，超过就撤回 cache 层。

跑了 4 组 × 5 题 = 20 道作家诊断题，配 minimax + v3.4 prompt（数据见 `docs/internal/experiments/data/exp006-kg-cache-quality-{anshi,mingchao}-{empty,warm}.json`）——

| 组 | KG 角色数 | 失败题 | 平均 dur | 答案 ans_len 范围 | reviewer 拿分题数 |
|---|---|---|---|---|---|
| 3a anshi empty | 595（jieba 兜底） | q1 LoopTimeout | 150.6 s | 951-1568 字 | **0 / 5** |
| 3b anshi warm | 87（LLM 主路径） | q1 LoopTimeout | 148.7 s | 0-1612 字 | **0 / 5** |
| 4a mingchao empty | 286 | q4 LoopTimeout | 165.6 s | 0-1170 字 | **0 / 5** |
| 4b mingchao warm | 370 | q3 LoopTimeout | 161.0 s | 0-1348 字 | **0 / 5** |

reviewer 在四组数据上**全部 5 题返空**——错误是 `reviewer_format_error: reviewer returned empty text after 3 attempts`。即便已经接了 commit `0ee345d` 的 empty 重试 + 中性化提示（第五节末尾说的那条 reviewer 路径兜底），minimax 对 reviewer 评分这种"作家诊断题 + 5 维度结构化打分"组合在三次重试内都拒答。

直接后果——`compare_quality_runs` 函数收到全 null 的 `review.scores`，`per_dim_std` 全部为 0.0，永远返 `validation_failed=False`，等于"reviewer 缺失被默判通过"。撤回判定**逻辑上无法走通**。

预设错在哪里——回头看 exp006 设计第二节那一句"reviewer：minimax + reviewer_rubric_v1（5 维 25 分制）"。第 31 轮 ContentFiltered 兜底链做完后看到 anshi 5 题能从全挂到平均 18.0/25，副管理就把"reviewer 在 minimax 上能稳定拿分"当成了实验前提。但 q3 那次拿到分是间歇性运气，不是稳态。本实验 5 题 × 4 组 = 20 次 reviewer 调用全部返空，才是稳态的 minimax 拒答画像。

更深一层的讽刺——第五节末尾那条 reviewer empty 重试兜底（commit `0ee345d`）就是为了救这种 reviewer 间歇返空设计的。但 4 组 × 5 题 = 20 次调用，每次都试 3 次重试，全部失败——**重试兜底的设计前提是"间歇拒答"，但 minimax 对作家诊断题 + 5 维评分的组合是稳态拒答**。重试 3 次 vs 重试 30 次 vs 重试 300 次，对稳态拒答都没用。这一笔 reviewer empty 兜底虽然在第十六波修对了"间歇"这一类，但碰到"稳态"就失效——又是同一条规矩的另一面：当前撞到的 bug 现象（间歇返空）只是某个类别（reviewer 拒答）的一个样本，类别下还有别的实例（稳态拒答）。

跟 reviewer 拒答同步发生的另一件事是 LoopTimeout——q1（anshi 节奏评估）两组都挂、mingchao q3 / q4 各挂一次。dur 207 s 没收敛对照 BookScope 默认 timeout 180 s——agent 在迭代到第 5 / 第 8 轮 search_chunks 时仍在堆 token，到 180 s 触发 LoopTimeout 抛出。作家诊断题在节奏 / 论点 / 支线密度三种题型上对 LLM 算力的需求本身就高，agent 跑不完 + reviewer 评不动叠在一起，让 4 组数据里"既有完整答案又有 reviewer 评分"的题数为 0。

回头看完成题的 trace 反而有意思的细节——q2（anshi 支线密度）在 empty 跑了 101.2 s / 5 iterations / 4 次 search_chunks，answer 1568 字 / 6 citations，章节覆盖 6 / 7 / 11；q3（anshi 论点铺垫）在 empty 跑了 212.0 s / 8 iterations / 7 次 search_chunks 在 timeout 边沿险过，answer 4296 tokens / 8 citations 覆盖 1 / 6 / 10 / 18 / 29 五个章节。这种"题做出来了但 reviewer 评不了"的状态是案例研究里最值得记的——单看 answer 文本，agent 在 anshi 上的作家诊断答题质量是肉眼可读的厚度；但工程验证维度上拿不到分。**人眼能判断好坏不等于工程能自动判断好坏**。

补一句关于"间歇 vs 稳态"的工程辨析——这两类失败的兜底设计完全不同。

间歇拒答的特征——同一个 input 反复跑，部分次数过 / 部分次数不过；分布上 reviewer 拿分覆盖率在 40-90% 区间内浮动；提示 LLM 用更中性的措辞 / 重组上下文 / 改写 prompt 角度，覆盖率会上升。兜底就是重试 + 中性化提示 + 多次重试拿其中一次成功的结果。

稳态拒答的特征——同一个 input 跑 N 次全部不过；分布上 reviewer 拿分覆盖率近 0%；提示 LLM 改写措辞、改写角度都没用——provider 在这种特定 prompt 组合下就是不答。兜底没有重试层面的解，只有换 provider / 换 prompt 大幅改写 / 换评分体系（比如从 5 维度结构化评分改成单维度 0-5 整数评分，让输出复杂度变低）。

minimax 对作家诊断题 + 5 维结构化评分的组合是稳态拒答——20 次调用全空说明覆盖率接近 0%。chapter-09 第十节加的 reviewer empty 重试兜底是按"间歇拒答"设计的——所以救不了稳态。这两类的辨析得在 probe 阶段就做出来：跑 3-5 次重复看分布形态——如果数据分布是双峰（要么拿分要么 0）且 0 那一峰占多数，大概率是稳态；如果数据分布是连续的（拿分密度从 0 到 25 平滑分布），大概率是间歇。

这条辨析没做好的代价就在第六节——预设 reviewer "可用"是基于 anshi q3 那次拿到 17/25 的单次观察，没去看 20 次重复的分布是双峰还是连续。后来跑出 20/20 全空才意识到原观察来自双峰中的"拿分那一峰的一次"，不是稳态。

---

## 七、校正三：多证据链 + 关键路径稳定性 probe

第六节那段撞墙根因写在更深一层——**实验设计预设了单一指标（reviewer 评分）作为唯一证据，单一指标失效后整个实验设计无法走通**。

校正写成两条研究规矩，都写在 chapter-10 第十节末尾——

**1. 跑实验前先 probe 关键路径稳定性**

> probe reviewer 稳定性再决定要不要用 minimax 当 reviewer——5 题 × 3 次重复跑看 reviewer 拿分覆盖率，覆盖率 < 80% 直接换 provider。

这条做法跟第二节"baseline std 不能省"是同一脉——LLM 行为是分布，关键路径的稳定性也是分布。要 reviewer 在某 provider 上"稳定拿分"，跑 1 次拿到 18/25 不够，得跑 5-15 次看分布。如果分布是双峰（一半拿分一半空文本），就不能预设它在实验里稳定可用。第十七波之前如果跑过这个 probe，就不会在 exp006 里把 minimax reviewer 当默认前提。

**2. 撤回判定预设多证据链**

第十七波撞墙时换到 4 条替代证据，最后得出"不撤回 book-level cache"的结论——

| 维度 | 判定 |
|---|---|
| KG 角色数差异 | 来自 LLM 间歇行为（jieba 兜底触发 / batch 拒答），不是 cache key 漏字段 |
| 失败题分布 | 题不固定，跟 cache state 无关 |
| 答案 ans_len 差异 | 在 LLM 单次跑 noise 范围内 |
| 平均 dur 差异 | ≤ 3%，cache 影响到的部分（KG 抽取段）已被耗时实验单独验证（664x / 1271x） |
| reviewer 评分对照 | 不可执行（minimax provider 限制），不构成判定证据 |

这 4 条替代证据是 RE 在数据齐了之后**临时立起来**的——不是事先在 exp006 第六节那张验收阈值表里写好的。这是 chapter-09 第六节"决策门控写在前面不是事后补的免责声明"那条规则的反面教材——门控写在前面是好规则，但门控可能失效；失效后的替代判定是临时立起来的，不是事先准备的。

下次实验设计要把这条做法写在前面——撤回阈值不是单一指标，是一组指标的组合。reviewer 评分是其中一种，ans_len 差异 + 失败题分布 + 平均 dur 是另一种。任何一条单独失效，剩下的几条还能合力得出判定。这样实验设计的抗风险能力比依赖单一指标高一个量级。

第三个隐含校正——**probe 设计避开"维基级常识题"**——也是同期写进 memory 的研究规矩。memory `feedback_probe_avoid_general_knowledge.md` 写在第 33 轮第一部分作者锤"朱元璋小名朱重八不算证据"那一刻：训练污染 probe 的题如果在维基 / 知乎 / 抖音科普能搜到答案，LLM 答对它只证它有这些二手讨论的训练数据，不证它读过原文。这跟"多证据链"是同一条思路的不同侧面——单一类型的证据（"LLM 能答出题面"）不足以下结论，得用多种证据（"题在公开网络上搜不到"+ "LLM 答对原文细节"+ "LLM 答错时编错的方向"）联合判定。

校正三的工程外化——稳定性 probe 怎么写。BookScope 在 chapter-10 第十节末尾留了下次实验前要跑的 probe 模板（思路写明在 exp006 第九节末尾）：

- 选 5 道有代表性的题（覆盖不同题型，比如 anshi 的节奏 / 论点 / 支线密度）
- 跑 3 次重复，配定 provider + prompt 版本
- 拿到 3 × 5 = 15 次 reviewer 调用的结果
- 算"reviewer 拿分覆盖率"——拿到非 null 评分的次数 / 总次数
- 覆盖率 < 80% 直接换 provider 不要硬上

probe 时间成本——按 chapter-10 第十节单题 100-200 秒、5 题约 15 分钟 × 3 次 = 45 分钟。45 分钟比跑完整 4 组 × 5 题 = 20 题实验（约 1 小时 + 数据分析时间）便宜得多——如果实验前 45 分钟的 probe 就发现 reviewer 覆盖率不够，整个实验设计直接换 provider，省下后面所有跑出 0 分的时间。

probe 设计的另一个原则——**probe 跟实验本身要在同一条调用路径上**。第十七波之前如果有人想 probe reviewer 稳定性，写一个孤立的"调 minimax LLM 问 5 维度评分"的脚本是不够的——因为实际 reviewer 调用路径上的 prompt 是 reviewer rubric v1 那一整套结构化指令 + 题目 + 答案的拼接，跟孤立调用的 token 长度、prompt 复杂度都不一样。要 probe 得拿 5 道真题跑完整的 generator + reviewer 链路，才能采到实验环境下的真实分布。这一条在 chapter-09 第七节 fast_path r2 静默挂那段也有同道理的规律——单元测试在简化 mock 下覆盖不到的 bug，QA 写 r2 等价测试时才撞出来；probe 写在简化路径上拿到的稳定性数据，到完整实验路径上也可能失效。

写到 BookScope 的具体工程动作——`scripts/probe_*.py` 这套脚本就是这条做法的实物：`probe_minimax_content_filter.py` 在真实 ContentFiltered 路径上跑、`probe_training_contamination.py` 在真实 generator 路径上跑、未来要加的 `probe_reviewer_stability.py` 也得在真实 reviewer rubric v1 + 题目 + 答案的拼接路径上跑。每个 probe 写 stdout 报告 + 写 JSON 持久化数据点 + 5 并发设计，跟实验本身共享底层调用栈。这是 BookScope 团队架构 `bookscope-researcher.md` 那条"probe 脚本设计原则"在 file 层的具体动作。

---

## 八、三条规律合起来：AI 实验设计的预设脆弱性

把三次撞墙的根因汇到一张表上——

| 撞墙 | 错误预设 | 现实情况 | 校正 |
|---|---|---|---|
| v3.3 baseline std 翻转 | 单次 baseline 是真相 | LLM 行为是分布，单次跑只是一个 sample | baseline 至少 3 次求 std，跟新版本比的 Δ 要超 σ 才有信号 |
| 通用兜底链按实例 | 当前撞到的错就是要修的全部 | 错误种类比想象的宽，单错误兜底救不了下次撞别的错 | 按错误类别建矩阵覆盖，每类都有兜底 |
| exp006 reviewer 限制 | reviewer 拿过一次分就稳态可用 | provider 在某些 prompt 组合上稳态拒答，跟"间歇拒答"是两类 | 跑实验前 probe 关键路径稳定性，撤回判定预设多证据链 |

三条规律合起来是一句话——**"什么是真的"在 LLM 行为下需要主动测量验证，不能默认**。

传统软件实验里"baseline 跑一次就是真相"、"修了当前 bug 就修完了"、"reviewer 拿过一次分就稳态可用"——这些预设在算法行为确定的环境下是合理的，跑一次确认就够，节省工时。在 LLM 行为分布化、错误种类宽、provider 稳定性不可预设的环境下，这些预设全部失效。

三个具体子层面——

**1. LLM 行为是分布不是点**

一次跑给的不是真相，是一个 sample。设计实验前要先量 baseline 的方差，否则跟新版本比的 Δ 全在 noise 范围内，结论是假的。BookScope 第 33 轮第三 / 四部分追着一个不存在的"prompt 副作用"跑了一整轮，最后第五部分补 baseline std 才发现 Δ = -1.8 落在 σ = 1.06 范围内毫无信号。

**2. 错误类别不是错误实例**

当前撞到的 bug 是某个类别的代表，修复要按类别覆盖不是按实例。同理实验撤回判定要按"错误类别"预设兜底——不是只防"当前撞到的那一种失败"，是防"当前调用路径上所有可能的失败类别"。BookScope 第十六波修了三个 commit（`0b0c2a9` / `362f0ab` / `e8bc16f`）才意识到自己一直在按 case 修，commit `79e44f5` 重写按类别覆盖之后才稳定下来。

**3. provider 行为差异是常态不是异常**

minimax / DeepSeek / Anthropic / GLM / Qwen 在同一调用路径上能拿到完全不同的稳定性画像。实验设计预设单 provider 稳定可用 = 假设 N 个 provider 行为等同 = 错。BookScope 第十七波撞 reviewer 限制就是因为 exp006 设计时把 minimax reviewer 当默认前提，没考虑 minimax 对"作家诊断题 + 5 维结构化评分"这种特定 prompt 组合的稳态拒答画像。

三条合起来——AI 实验设计的预设脆弱性。研究者要做实验，但 LLM 的"行为定义"本身在变化、在波动、在 provider 之间漂移——预设任何一条"稳定" / "确定" / "一致" 性质都需要先测量，不能默认。

跟 memory `project_value_reframe_evidence_universal.md` 那条做法对得上——BookScope 的价值不在"绕过某家 LLM 的某个 bug"，是"在所有 LLM、所有文本、所有用户场景上都强制 evidence-from-text 兜底"。实验设计的做法也得同步——不在"某家 LLM 某次跑的结果"上下结论，得在"这本书 × 这道题 × 这个版本 × 多次跑的分布"上下结论。

再往深一层挖——这三条规律其实是同一条 epistemology 的三个表面。LLM 不是确定性的计算工具，是一个被训练数据塑造的概率系统。研究者跟 LLM 做实验的方法不该是"测一个固定对象的属性"，得是"采样一个分布并推断其参数"。前者的研究方法学几十年没大变；后者是统计学课本第一章的内容——但工程师做 LLM 实验时大多数时候在用前者的方法。

BookScope 三次撞墙都来自这个错配——

- 第一次撞墙：拿单点当分布参数估计（21.4 当 v3.2 的 μ）
- 第二次撞墙：拿单类别错当错误分布的全部（ContentFiltered 当 KG 错误的全部）
- 第三次撞墙：拿单 provider 行为当 LLM 行为的代表（minimax 当 reviewer 的全部可能）

每一次都是在 LLM 这个概率系统里取了一个样本，错把它当成了总体。统计学课本第一章就警告过这种 sampling fallacy，但传统软件工程里它不是问题——因为软件行为是确定的，单样本就是总体。LLM 把这种课本上的警告变成了日常工程纪律——每个 commit、每次实验、每次 bug 修复都得问一句"这是单样本还是总体？"

这条 epistemology 还有一个更隐蔽的层面——**研究者本人对 LLM 行为的认知也是分布**。BookScope 副管理第 31 轮见到 reviewer 在 anshi 上拿到 18.0/25 一次之后，脑子里形成了"reviewer 在 minimax 上能用"的认知；这个认知本身就是一个采自小样本的估计。后来第十七波 20 次调用全部返空才意识到原估计偏差大。这意味着——LLM 实验的"实验前提"不只是数据 sampling 的问题，也是研究者认知本身需要 calibration 的问题。每跑一次实验前要问的不只是"数据怎么采"，还有"我对这件事的预期来自哪几次观察 / 这几次观察是否构成可信样本"。

这一层在 case-study 里反复出现——副管理读到一次数据就建立起一条认知，下一次新数据进来又推翻。chapter-04 第八节那条"训练污染漏洞"框架被作者两层连锤打穿改成"任何 LLM 都正常训练"；chapter-09 第十节副管理三次锤之后才升到"通用兜底"的做事方法；本章第三次撞墙那个 reviewer 预设也是同类——副管理建立的认知来自一个采样，新数据进来才推翻。LLM 实验里的研究者要随时准备 reframe，因为 LLM 行为本身在持续给你新样本，旧采样下建立的认知随时可能失效。

这条认知跟 BookScope 的 NORTH_STAR 第 2 条直接挂钩——"所有结论由查询时的 agent 循环根据原文证据现场生成；没有原文证据的结论一律不输出"——本来这条针对的是用户查询，挪到研究层面同样适用：**没有多次跑数据 / 多 provider 数据 / 多书数据支撑的研究结论，一律不输出**。研究方法跟产品立场对得上——这是 BookScope 作为一个"既是产品又是案例研究"的项目的独特之处。其他 LLM 应用项目可以分开做产品和写论文；BookScope 一个 repo 同时承担产品迭代和方法论沉淀，所以两边的做法必须互相印证。本 article 写出来的三条规律既是研究方法，也是产品立场的方法论侧——这是把 BookScope 跟"做一个 LLM 应用 demo"区分开来的根本之处。

---

## 九、收尾：怎么在下次实验前先校验前提

三次撞墙合起来留下的研究规矩，写成 checklist 给下次跑实验前过一遍——

**实验设计前**

- [ ] baseline 至少跑 3 次拿到均值和 std，新版本要看到的 Δ 是否大于 σ？
- [ ] 撤回判定写了几条证据？单一证据失效后剩下的几条够不够下结论？
- [ ] 关键路径（reviewer / generator / KG extractor）在选定 provider 上的稳定性是否 probe 过？
- [ ] 题目设计避开"公开网络能搜到答案"的维基常识级问题？
- [ ] 错误兜底矩阵列了几类错？每类是否都有具体处理路径？

**实验跑出来之后**

- [ ] Δ 落在 baseline σ 范围内时不下"有变化"也不下"无变化"，下"在 noise 范围内"
- [ ] 单次跑发现的"反例"要先看 baseline std 再下结论
- [ ] 替代证据链下的结论要写明"在 X 指标缺失下的判定"，不藏失败现场
- [ ] 失败的实验值得写进案例研究，比成功的更值得

**事后沉淀**

- [ ] 撞墙的预设错误归到三条母题（分布 / 类别 / provider 差异）的哪一条
- [ ] memory 写明"什么前提错了 / 现实情况怎样 / 校正怎么做"
- [ ] case-study 写现场——具体 commit hash / 具体数据点 / 具体作者锤的原话

这套 checklist 不是事先想出来的，是 BookScope 三次撞墙之后回头总结出来的。其他做 LLM 实验的项目大概率会撞同样的墙——所以写下来。下次实验跑之前过一遍 checklist，比跑出来不知道怎么读数据再回头补便宜得多。

这套 checklist 的另一个用途——给 AI 副管理用。BookScope 现在的工作流里很多实验设计 / batch 跑 / 数据分析都由 AI 副管理推进，每次进 session 重读核心文件后判断本轮任务。三次撞墙都是 AI 副管理跟作者协作的过程中暴露的——AI 起 take 错、作者锤，AI reframe；下次 AI 进 session 时这条 checklist 跟 memory 一起 load，理论上能早一步识别预设错误，少绕一圈弯路。这是把"研究经验"写进"工作流"的具体动作——不是写在哪本书里供人事后翻看，是写进每次 session 启动必读的 memory 里强制提醒。

下一次撞墙时大概率不是上面三类预设错误的简单重演——LLM 行为会演化，错误种类会扩展，新预设错误会出现。但本 article 写明的那句话——**"什么是真的"在 LLM 行为下需要主动测量验证**——会继续适用。新的预设错误出现时，按这条母题去找它的具体形态、找它对应的校正、找它在 BookScope 工作流里的具体动作；写新的 article 时不要替换本 article，而是接续本 article 的母题往前推。这是 case-study 长期积累的做法——不是一篇就讲完，是一年又一年加 case。

最后留一句——失败的实验比成功的实验更值得写。BookScope 一年来跑过几十次 batch、几次 probe、几个 sprint 验收，成功的部分大多数都是工程交付（数据进了 STATE / 通过了验收 / 进入下一个 sprint）；真正进案例研究文档当主角的，是失败的部分——chapter-04 v3.3 q5 std 翻车、chapter-09 第十节通用兜底链补齐三天、chapter-10 第九 / 十节 quality probe 撞 reviewer 限制。三次接在一起，BookScope 案例研究的"研究"成分一次次比"工程交付"成分更厚。这条 article 不是工程交付的副产品，是失败实验沉淀出的方法论资产。

还有一句留给未来——本 article 写的三次撞墙都发生在 BookScope 2026-04 到 2026-05 这一个半月内，跨第 33 轮到第十七波。LLM 应用层的研究还很年轻——BookScope 这一年踩到的坑大概是任何认真做 LLM 应用的项目都会踩的，按本 article 这种"反复撞同一条母题"的频率推算，未来一两年还会撞别的预设错误。比如——LLM 在长上下文里 attention 漂移会让结论跟"输入材料中的位置"挂钩，跟内容本身关系不大；比如——同一题在不同 session 之间因为 cache 状态 / 系统 prompt 微调 / temperature 默认值的变化结果不可重现；比如——LLM 在某些题型上"输出长度"跟"输出质量"反向相关（长答案靠堆字数刷过 reviewer，短答案反而更精准）。这些都是 BookScope 现在没碰到但将来可能碰到的预设错误。

本 article 写完不是结束——是一个 placeholder。下次撞墙时回来加第四个 / 第五个 case，让母题更厚。case-study 跟研究本身一样是慢慢加的，不是一篇就盖棺定论的。这条做法跟 chapter-09 第九节那段"案例研究边写边发生"是同样形态——研究文档跑在事件之前，等事件来填。下一次撞墙时记得回来加上。

---

*草稿到此为止。三次撞墙现场来自 chapter-04 第八节、chapter-09 第十节、chapter-10 第九 / 十节；研究规矩来自 memory `feedback_baseline_variance_first.md` / `feedback_global_not_single_case.md` / `reference_minimax_reviewer_limit.md` 三条；隐含原则关联 `feedback_probe_avoid_general_knowledge.md` / `project_value_reframe_evidence_universal.md` 两条。定稿由作者在里程碑点统一润色。*

*下次撞墙时回来续——第四个 case 已经留好位置。*

*草稿覆盖 commit 跨度：v3.2 mingchao baseline 三次跑 `b8c2d34` 系列 → v3.3 / v3.4 prompt 改进数据 → 第十六波 `0b0c2a9` / `362f0ab` / `e8bc16f` / `79e44f5` 通用兜底链补齐 → 第十七波 `589f522` / `0e50449` exp006 reviewer 限制实跑判定。完整 commit hash 与数据 JSON 路径见三个关联 chapter 末尾。*
