# 第十一章 · 翻案日——一天收回三个结论

> **状态**：草稿 · 作者未定稿 · 2026-06-11 起头
> **代际**：r2-agent-protocol
> **覆盖时段**：2026-06-10 单日（第十八波 · 停摆 22 天后）+ 2026-06-11 上午余波
> **关联设计稿**：`docs/internal/design/WP0-prompt-version-chain.md` / `docs/internal/design/2026-06-10-design-gap-review.md`
> **关联实验**：exp-004（第 9 节实跑数据）/ exp-006（第十、十一节两次勘误）
> **关联章节**：chapter-10 第九节（本章是它的勘误）/ article-12（实验设计预设错误——本章给它补第四个案例）
> **关联 memory**：`project_prompt_v31_regression.md` / `reference_minimax_reviewer_limit.md` / `reference_concurrent_agent_workspace_pollution.md`

---

## 序：盘点日变成翻案日

2026-06-10，BookScope 停摆 22 天后作者回来，第一句话是："整理梳理一下项目情况……很多设计和目的的留存并不完善。"

副管理派三个探查代理并发盘 docs 全集、代码、测试与数据，上午 11:48 落下盘点报告（commit `b14e010`）。这一天原本的剧本是文档日——补齐过期的 NORTH_STAR、追认积压的 ADR、把名存实亡的 ROADMAP 时间线重排一遍。

结果这一天跑出 25 个 commit，真正值得写进案例研究的不是哪个新功能，而是**三个既有结论在同一天里被收回**：

- 一个 P0：生产 prompt 在 v3.1 上静默冻结了 44 天，三轮实验验证过的改进从来没进过产品；
- 一次错误归因翻案："minimax reviewer 稳定拒答 60/60"——写过勘误、做过换 provider 决策、存过 memory 的三层结论，根因其实是自己代码里的一个形态不匹配 bug；
- 一场虚惊："同一本 epub 两次 ingest 切出不同 chunks"差点升级成 P0 调查，三分钟查实是并发代理共享工作区的版本污染。

三件事的具体形态完全不同——一个是配置常量、一个是取文本函数、一个是工作区时序——但拆开看是同一个结构：**测量层出了问题，下游所有结论跟着错**。prompt 版本是没人记录的仪器读数，reviewer 取文本是静默归零的评分仪器，代码版本锚是数据点上没标注的仪器状态。实验跑得再勤，仪器不可信，数据就是在说谎。

这一天还有一笔正面收尾：下午 15:31 上线的 citation 核验链，当天晚上就和修好的 reviewer 从两个独立侧面抓到了同一个坏输出。测量仪器修好之后，立刻开始产出价值——这是三次翻案之后这一天给的回报。

先把整天的 commit 时间轴摆出来，三次翻案在哪个时刻发生一目了然（加粗的是本章主角）：

| 时间 | commit | 事件 |
|---|---|---|
| 11:48 | `b14e010` | 停摆 22 天后全面盘点报告 |
| 12:06 | `229958d` | 盘点修正清单执行（作者批"按你的建议来"） |
| 13:38 | `882c33c` | NORTH_STAR 月度修订 · 作者亲笔签字 · exp-001b 裁决 |
| 14:18 | `ebaa9b0` | 设计缺口评审 13 条 · **P0 发现：生产 prompt 冻结 v3.1** |
| 14:26 | `17cec9e` | WP0 设计稿过闸 |
| 14:49 | `c8f8a13` | **WP0 修复：v3.1 → v3.5 + trace 版本字段 + 哨兵测试** |
| 15:09 | `af1a484` | WP1 + WP2a 设计稿过闸 |
| 15:31 | `5f3b716` / `c717f8e` | WP1 citation 可信链 + WP2a 检索降级可见 |
| 15:47 | `9eda1f8` | 22 个存量 lint 错误清零 |
| 16:13 | `9a9778d` | WP3 设计稿过闸 |
| 16:39 | `bb008d2` | WP3 章节鲁棒性 Phase A+B（chunker 改动——虚惊的伏笔） |
| 16:57 | `05f0755` | WP2 golden set 74 条 + BM25-only 基线 |
| 16:58 | `aed4c53` | STATE 第六段 · **"loader 不确定性"虚惊三分钟查实** |
| 17:26 | `f99f94a` | **reviewer 翻案：取文本兼容 OpenAI 形态 · 错误归因收回** |
| 17:35 | `8c32fa9` | key 安全清理 · settings.local.json 移出 git 跟踪 |
| 17:50 | `eca8a57` | exp-004 跨题材验收 12 batch 数据 · 4 书 × 3 run |
| 18:04 | `7ad2cc8` | exp-004 第 9 节分析 · Sprint 3 验收压哨过 |
| 18:14 | `4ffcb6b` | WP5 + WP8a + exp-007 三设计稿过闸 |
| 18:21 | `d7b343f` | PE 交付 loop v3.6 + reviewer rubric_v2 |
| 18:22 | `4ca6396` | ADR-009 多轮对话草案（次日上午作者签字） |

下面按时间序串。

---

## 一、上午：盘点报告里的"留存断点"

先把这一天的起点讲清楚，因为三次翻案的种子全埋在上午的盘点里。

盘点报告（`docs/internal/audit/2026-06-10-project-inventory.md`）给出的健康面不差：780 个测试全部可收集、r1 删干净零残留、跨文档引用链无断裂。问题集中在另一类——**文档落后于现实**：

- NORTH_STAR 修订过期 21 天（必修订日是 5/20，作者每月亲笔的那条线断了 22 天停摆期）；
- ADR-001~005 挂着"草案"状态 47 天，其中 004 / 005 的代码早就实现了；
- exp-001——北极星级的"引用精度 > 80%"验证——从未跑过；实验编号还断了 003 / 004 两档；
- `search_chunks` 里两处 TODO 注释说"待接 FAISS"，实际早已接上——**注释在撒谎**。

单看每一条都是小事。但"代码与文档各说各话"这个面，正是下午三次翻案的共同土壤——盘点报告里有三条结构性发现当时就写进了 STATE（commit `b14e010`），现在回头看像预言：

> ① prompt 承诺 ≠ 机制保证——项目不信任 LLM 训练记忆，却完全信任 LLM 引用诚实；② 兜底路径静默劣化——五层兜底保住"不崩"没保住"降级可见"；③ 测量仪器先于定义。

中午作者批"按你的建议来"，四件盘点修正全部执行（commit `229958d`），13:38 作者亲笔签了 NORTH_STAR 月度修订（commit `882c33c`）——里面有一条裁决本章第八节会回头讲：exp-001 以 r2 口径重立为 exp-001b。

然后作者问了第二个问题："设计的框架、蓝图、目的是什么 → 细节要补什么 → 汲取高星开源经验。"两路代理并发调研，14:18 设计缺口评审落地（commit `ebaa9b0`）——13 条缺口、8 个工作包蓝图，外加一份 dsRAG / Contextual Retrieval / RAGAS / promptfoo 的开源对标笔记。评审末尾给作者留了三个拍板位：WP0 是否立刻执行、WP1-8 方向是否认可、百万字测试书是作者亲选还是授权 RE——副管理对每个都给了自己的 take，第一个的 take 是"是，所有后续实验的前置"。

第一次翻案就藏在这份评审的 P0 段里。

---

## 二、第一案：生产 prompt 在 v3.1 上冻了 44 天

设计缺口评审写到 prompt 工程那一节时，评审代理顺手核对了一个理应没有悬念的问题：生产现在跑的是哪个 prompt 版本。答案让主 Claude 亲自下场验证了一遍——`bookscope/agent/_internal/loop_shared.py:112` 硬编码 `loop_system_prompt_v3.1.md`。

`git log -S "loop_system_prompt_v3.1"` 把整条历史钉死，总共只有三个 commit 碰过这个字符串：

| commit | 日期 | 发生了什么 |
|---|---|---|
| `b09b5e8` | 2026-04-27 | 第 26 轮引入 v3.1，写进 r1 loop.py |
| `0d4d210` | 2026-05-15 | Sprint 7 ③a 抽共享包，**原样照抄进 loop_shared.py** |
| `c8f8a13` | 2026-06-10 | WP0 修复，44 天后第一次改动 |

也就是说，从 4 月 27 日到 6 月 10 日，**用户面产品一直跑 v3.1**。chapter-04 里写过的 v3.2 → v3.3 → v3.4 三轮 prompt 迭代——B-2-i 子模板把 anshi q5 的 std 从 3.8 压到 0.47、题型路由、citation 厚度约束——全部只在 batch 实验的环境变量 override 下生效过，一行都没进过产品。实验室里验证了三轮的改进，产品用户一天都没用上。

诚实记一笔：当天的修复 commit、设计稿、memory 里都把这段时间写成"三个月"。日历上是 44 天。"三个月"是发现那一刻的情绪量级，不是事实量级——本章按 git log 说话。

这不是一个 bug，是三个叠在一起：

**第一连：常量冻结。** Sprint 7 抽 `_internal` 共享包的时候，BE 把 r1 loop.py 里的常量原样搬家。搬家这个动作本身零错误——测试全绿、行为不变。但"行为不变"恰恰是问题：第 26 轮写下的旧值被原封不动地带进了新结构，从此再没人看它一眼。chapter-09 第二节里那次干净利落的 ③a 重构，埋下了本章的第一案。

**第二连：override 机制死了没人知道。** `scripts/run_batch_r1.py:338-347` 的版本 override 靠 patch `bookscope.agent.loop` 实现——这个模块 Sprint 7 已经 git rm。5/15 之后设这个环境变量直接 ImportError；就算 patch 成功，r2 runtime 读的是 loop_shared 的常量，patch 的对象根本不对。实验基础设施坏了快一个月，没有任何报错冒出来——因为 5/15 之后没人跑过带 override 的 batch。

**第三连：probe 脚本的 docstring 在撒谎。** `scripts/probe_kg_cache_quality.py:43` 自称"默认 v3.4"，但脚本体根本不读 override 环境变量。exp-006 的 4 组 quality probe 数据（5/18-19）实跑全是 v3.1，JSON 元数据里没有任何版本字段——数据无法自证自己是用哪把尺子量出来的。

影响判定要分开算，这是 RE 视角最关心的部分。exp-006 的内部对照（empty vs warm）**仍然有效**——四组用的是同一个 prompt，比的是缓存效应，prompt 版本是被控制住的变量，只是值跟标签不符；chapter-10 第十节"不撤回 book-level cache"的判定不动。但任何跟"v3.4 / v3.5 baseline"的跨实验比较**全部作废**——差异里混着 prompt 版本这个没被记录的变量。5/15 之后所有 batch、所有端到端数据，包括 zhinei / kuicheng 两本新书的首次答题，都是 v3.1 跑出来的。

---

## 三、修法：让版本成为被记录的事实

WP0 的修复走了完整的 design-first 闸门：14:26 设计稿（commit `17cec9e`）、作者批"开始"、14:49 落地（commit `c8f8a13`）——从发现到修复 31 分钟，但中间过了一道设计审查，不是顺手改一行常量了事。设计稿里方法论锚写得很直白：

> 测量仪器先于实验：版本不是实验变量的注脚，是必须先固定的仪器读数。

> 无观测不控制：prompt 版本是三个月未被观测的系统状态；修复 = 先建观测（trace 字段 + 单测哨兵），再动状态（切 v3.5），且可逆（env override 保留、历史数据不改写只补勘误）。

落地五件套：

1. **单一事实源**——`CURRENT_PROMPT_VERSION = "v3.5"`，路径由版本号拼出，今后切版本只动这一个常量；
2. **trace 可观测**——`LoopTrace` 加 `prompt_version` 字段，从实际加载路径的文件名解析，override 也如实反映；batch / probe 输出元数据一律写入。版本从"文件名外部标注"变成"运行时自己报告"；
3. **override 内建**——环境变量读在加载层的 `resolve_system_prompt_path`，每次实例化生效，patch 已删除模块的死代码整块删掉；
4. **哨兵测试**——`tests/agent/r2/test_prompt_version.py` 10 条：默认版本断言、路径推导、override 生效、trace 如实记录、旧数据兼容。下次再有人重构搬家，常量被静默改动会直接红；
5. **历史勘误**——exp-006 文档补第十节"4 组 quality probe 实跑 v3.1 非 v3.4"。历史 JSON 不回溯篡改，勘误明文补记——这条纪律本章后面还会用到第二次。

修前修后两行对照就能看出这次修的不是值，是结构：

```python
# 修前（loop_shared.py:112 · 第 26 轮的值在 Sprint 7 搬家后又活了 26 天）
SYSTEM_PROMPT_PATH = ... / "loop_system_prompt_v3.1.md"

# 修后（版本号是单一事实源，路径由它拼出，trace 反向解析回版本号）
CURRENT_PROMPT_VERSION = "v3.5"
SYSTEM_PROMPT_PATH = ... / f"loop_system_prompt_{CURRENT_PROMPT_VERSION}.md"
```

修前那一行的问题不在 v3.1 这个值，在于值和"现在该用哪个版本"这个判断之间没有任何结构关联——改 prompt 的人不知道要来改这里，改这里的人（Sprint 7 的搬家重构）不知道自己在替 prompt 版本做决定。修后版本号自己是常量、路径是推导、trace 是反向解析——三者咬死，哪一环动了哨兵测试都会红。

副作用也查了：L2 LLM 缓存的 key 含 system prompt 哈希，切 v3.5 自动 miss 旧缓存，无脏缓存风险。测试 780 → 789 全绿。

生产切到 v3.5 的代价在设计稿里写明了：v3.5 的题型路由、citation 厚度、并发查证指引全部生效意味着**产品行为变化**，6/10 起的新数据跟 5 月所有数据跨版本不可直接比。这是修复的必然代价，不是风险——继续装作可比才是风险。

这一案的通用教训进了 memory `project_prompt_v31_regression.md`：**配置常量被重构搬家时，值会被静默冻结**；任何影响实验结论的运行时配置——prompt 版本、provider、model——必须写进 trace 和 batch 元数据，文件名和口头标注不可信。

第二天上午这条教训立刻派上用场。6/11 修 batch JSON 元数据时（commit `6e6bf06`）挖出同类第二案：`run_batch_r1.py` 用 `getattr(book, "source_path", "test明朝那些事儿.epub")` 兜底取书路径，而 `BookText` 根本没有 `source_path` 字段——兜底值永远生效，exp-004 四本书 12 份 JSON 的 `book.path` 全写着明朝。

顺藤还摸出更深的一条：`BookText.word_count` 用 `split()` 数词，中文没空格，anshi 38 万字被记成 3134。`schemas.py` 改成 CJK 按非空白字符计数后，四本书修正成 anshi 378171、zhinei 448103、mingchao 1480879、kuicheng 5381554——word_count 的口径分界就是这个 commit，旧数据与新数据从此不可混比。

`getattr(obj, field, 兜底值)` 是危险写法——字段名拼错或不存在时静默落兜底，元数据从此说谎。跟 prompt 版本案是同一个病：**元数据要从实际运行对象直接取，取不到就报错，不要给"看起来合理"的默认值**。

---

## 四、下午两路并发：WP1 / WP2a / WP3 / golden set

第二案发生在下午的并发工地上，先把工地交代清楚。

WP0 落地后作者授权"按你的节奏来，继续"，副管理按设计闸门连推两波。第一波（15:09 设计稿 `af1a484` 过闸，15:31 双 commit 落地）：

- **WP1 citation 可信链**（commit `5f3b716`）：新模块 `citation_check.py` 用纯标准库 3-gram 匹配核验每条引用；loop_r2 每个 query 建证据登记表；citations 一律带 `verified` / `chunk_id` / `match_score` 三个字段；fast_path 自动拼引用加 `auto_filled` 诚实标注；LoopTimeout / MaxIterations 时填 `partial_evidence`——第 35 轮 dogfood 那天作者锤的"失败前证据要兜底"的债，这一笔还清。batch summary 加 `citation_verified_rate`——"引用真实率"第一次有了测量装置。首版**只观测不执法**：先拿 verified 率的真实分布，再决定 enforcement 阈值；
- **WP2a 检索降级可见**（commit `c717f8e`）：`retrieval_mode` 从 SessionVectorStore 透传到每条 ChunkMatch——BM25-only 静默降级从此留痕。盘点报告那条"兜底路径静默劣化"的结构性发现，当天就有了第一块补丁。

第二波（16:13 WP3 设计稿 `9a9778d` 过闸后）两路并发：一路 WP3 章节鲁棒性改 `book_chunker`（commit `bb008d2`）——真章号解析、中文数字、单调守护整书回退，四本真书实测顺带揭开三个月度疑团：mingchao 七部书章号各自重排、kuicheng 有两个真重复的"第 1134 章"、zhinei 同组 8 章在 epub 里重复出现 3 遍；另一路 WP2 golden set（commit `05f0755`）——四本书 74 条检索标注（每条 expected 带原文依据）+ `eval_retrieval.py` 评测脚本 + BM25-only 基线，跑出一个清晰的短板：**位置找是 BM25 的系统性弱项，kuicheng 的 r@5 在位置题上归零**——contextual header 实验（exp-007）的 before 数字就位。

测试基线这一天从 780 一路爬到 859。然后第二案来了。

---

## 五、第二案：一场虚惊，三分钟查实

golden set 这一路的 RE 回报了一个吓人的发现：同一本 zhinei epub，两次 ingest 切出来的 chunks 数不一样——首跑 398，之后稳定 319。"loader 有不确定性"——如果成立，这是 P0 级问题：chunks 不确定，chunk_id 就不稳定，citation 核验、golden set、所有缓存 key 全部地基松动。WP1 刚上线三小时，地基就晃，这个时机让报告显得格外可信。

主 Claude 没有直接采纳，亲自动手验，两步：

1. **现代码同进程连跑两次**——逐位一致。排除不确定性。
2. **`git show` 取 WP3 改动前的旧版 chunker 单独加载跑一次**——复现 398。坐实版本污染。

真相：golden 代理首跑发生在 WP3 改 chunker **之前**，398 是旧代码的输出；之后的 319 是新代码的输出（WP3 清掉了 zhinei 的脚注假章，398 → 319 是预期后果，kuicheng 同理 4319 → 4315）。两个数字都是确定的，只是来自两个版本的代码。"不确定性"是把时间轴上的版本切换误读成了随机性。

三分钟，虚惊解除。这一案没造成任何下游污染，但它值得单独写一节，因为它跟前后两案放在一起构成一个完整的光谱——这次**测量纪律先到位了**：

- RE 报告异常时留了证据 dump——两次 ingest 的输出都存了下来，主 Claude 验证才只花三分钟。结论方向错了，但留证据的习惯是对的；
- 主 Claude 在"子代理报告不可复现类重大结论"时亲自复验再升级——而不是直接按报告开 P0 调查。chapter-09 第七节那句"bug 是相邻工作 exercise 出来的"在这里有了一个镜像版本：**虚惊也是相邻工作 exercise 出来的，区别只在有没有人在升级之前先复验**。

教训进 memory `reference_concurrent_agent_workspace_pollution.md`，三条规则：并发派 agent 时若一路在改 X 模块，另一路凡是依赖 X 输出的中途数据都不可信——要么错开，要么后跑的一路在任务里写明"以最终代码重验全部数据"；数据标注类交付物必须带代码版本锚（commit hash + 关键行为值），消费侧加守卫拒跑不匹配数据——`eval_retrieval.py` 的 n_chunks 守卫当天就是按这条写的；子代理报"不可复现"类结论时主 Claude 必须亲验再升级。

第 33 轮之后 BookScope 把"团队并发是默认"写成了硬规则（memory `project_team_concurrency_default.md`），chapter-09 整章都是并发提速的正面记录。本案是并发模式收的第一笔学费——不贵，三分钟，但只因为运气好赶上纪律在场。

---

## 六、第三案：reviewer"minimax 拒答"翻案

这是三案里最重的一案，因为被收回的不是一个数字，是一整套已经写进文档、做过决策、存过 memory 的结论体系。

先回放既有结论。chapter-10 第九节写过：exp-006 quality probe 4 组 × 5 题，reviewer 调用 60 次全部返空，"这不是 cache 层的问题，是 minimax 在 reviewer 这条调用路径上的稳定拒答"。基于这个归因，项目做了三层动作：

1. **实验勘误**——exp-006 第九节把"5 维度 std ≤ 0.5"撤回判定标记为不可执行，改用替代证据链；
2. **架构决策**——"要拿到 reviewer 评分必须换 provider（DeepSeek / Anthropic）"，写进 Sprint 7 多 provider 兜底的规划；
3. **memory**——`reference_minimax_reviewer_limit.md`，"minimax 对作家诊断题 reviewer 评分稳定拒答（60 次调用全空），需要 DeepSeek / Anthropic 兜底"。

连带一个解释性结论：第 33 轮 anshi 曾经拿到过 reviewer 分数，被解读成"间歇性运气，不是稳态"。

6/10 傍晚，作者给了 DeepSeek key，Sprint 3 batch 启动。按既有结论，换 DeepSeek 当 reviewer 应该立刻出分——结果依然 "returned empty text"。同一个模型当生成方完全正常，当 reviewer 就返空。嫌疑一下子从 provider 身上移开了：**两家 provider 在同一条调用路径上 100% 失败，这不像模型行为，像代码 bug**——模型行为有方差，代码 bug 没有。

顺藤摸下去，根因在 `reviewer.py` 的 `_extract_text`：它只认 Anthropic block list 形态（`response["content"]`）。而 Sprint 7（ADR-007，5/15）之后，所有 adapter 统一返回 OpenAI 形态（`choices[0].message.content`）。**reviewer 从 r2 切换那天起，对所有 provider 一律取出空文本**——exp-006 的 60/60 全空（5/18-19，恰在 5/15 之后）、第十六波两本新书 reviewer 全空，全是这一个 bug。潜伏 26 天。

为什么 KG extractor 的同款 bug 当天就被修了（chapter-10 第二节，commit `e33c37a`），reviewer 的却潜伏 26 天？因为 KG 那条路径上有人在做相邻工作——BE 写并发改造时撞出来了。

reviewer 这条路径上发生的事不一样：**输出恰好可以被解释**。"返空"撞上了 minimax 在生成路径上确实有过的 ContentFiltered 历史（chapter-09 第十节整节都在跟它搏斗），一个现成的嫌疑人站在那里，没人再看第二眼。**错误归因最危险的温床不是没有解释，是已经有一个貌似合理的解释。**

修复是 commit `f99f94a`（17:26）：先试 OpenAI 形态（复用 loop_shared 现成的 `read_openai_choice_content` helper），退 Anthropic 形态兼容历史 mock，加 `_OpenAIFormClient` 回归测试锁死。修复后的 `_extract_text` 在 docstring 里把整个翻案写成了代码注释——这段注释值得抄进案例研究，因为它示范了"勘误留在离错误最近的地方"：

```python
def _extract_text(response: dict[str, Any]) -> str:
    """把 adapter 返回的 response 抽成纯文本——兼容 OpenAI / Anthropic 两种形态。

    2026-06-10 修：Sprint 7（ADR-007）后 adapter 返回 OpenAI 形态
    （``choices[0].message.content``），本函数原来只认 Anthropic block list
    （``content``）——导致 r2 切换起 reviewer 对所有 provider 一律
    "returned empty text"。exp006 记录的"minimax reviewer 60/60 全空"
    根因是这里，不是 minimax 拒答。
    """
```

下次有人读这个函数，不需要去翻 exp-006 第十一节就知道这里翻过案。修复后整链烟测：deepseek 生成 38.8 秒 + 15 条 citation + deepseek-chat reviewer 评分 20/25——**r2 切换以来 reviewer 第一次真正出分**。

翻案翻得很彻底，连那个解释性结论也一起翻了：第 33 轮 anshi 拿过分不是"间歇运气"——那是 r2 切换之前，**当时的代码真的能跑**。"间歇运气"这个解释是为了圆"稳定拒答"这个错误归因而生造出来的二阶错误——错误结论会自我繁殖，把碰巧不符合它的旧证据也重新解释掉。

还有一条要诚实挂起的：minimax 当 reviewer 到底有没有拒答问题，**至今未知**——当天查实 minimax key 配额已耗尽，无法复测。在 key 恢复重测之前，"minimax reviewer 拒答"这个说法一律不再引用。不是翻案成"minimax 没问题"，是翻案成"不知道"——这两者的区别正是这一案的教训所在。

---

## 七、错误归因的代价与勘误文化

这一案值得单独算一笔账：一个取文本函数的形态 bug，污染了多少下游结论。

- exp-006 第九节的"minimax 稳定拒答"画像和"必须换 provider"判定；
- memory `reference_minimax_reviewer_limit.md` 整份；
- chapter-10 第九节——案例研究文档本身也继承了错误结论，"minimax 在 reviewer 这条调用路径上的稳定拒答"那句话白纸黑字写在章节里；
- article-12 把"reviewer 稳定性"当作三个被压破的实验前提之一展开论述——前提描述对了（预设 reviewer 能跑确实是错的），但病因写错了；
- 第 33 轮旧数据的"间歇运气"重新解释。

五个落点，横跨实验文档、长期记忆、案例研究、方法论文章、历史数据解读。错误结论不是一个点，是一棵树。

处理方式延续 WP0 那条纪律：**错误结论不删除，明文勘误留痕**。exp-006 文档加第十一节"第二次勘误"——这份实验文档至此有了两个勘误节，第十节勘误 prompt 版本、第十一节勘误 reviewer 归因，两次都是 2026-06-10 同一天补记。memory 重写时保留【翻案】标头和原结论的残骸，让下次读到的人知道这里曾经错过、为什么错。chapter-10 第九节原文不动，由本章充当它的勘误——案例研究写错了的部分，本身就是案例研究的素材。一份实验文档带着两个勘误节继续被引用，比一份"看起来从来没错过"的文档可信得多。

教训提炼成一句话进了 memory：**0% 成功率先查代码再怪 provider**。60/60 全空这种整齐的失败画像，更像确定性的代码 bug 而不是概率性的模型行为。当时如果对"全空"这个形状多问一句"模型拒答会拒得这么整齐吗"，26 天前就能翻案。第十六波作者锤过的"修 bug 先想全局再想本案"（memory `feedback_global_not_single_case.md`），在这里长出了归因侧的对应物——**归因也要先想全局**：把失败归给"这家 provider 在这类题上的行为"之前，先排除"我们自己的代码对所有 provider 都坏了"。

第二条教训是给未来代际切换的：**跨大版本迁移要审计旁路 LLM 消费方**。Sprint 7 的 audit 只审了主循环——chapter-09 第七节记过 fast_path 和 KG extractor 两条冷门路径的 r2 形态 bug，当时都修了；reviewer 这条旁路漏网，多潜伏了 26 天。主循环、fast_path、KG extractor、reviewer、question_processor——所有直接消费 LLM response 的代码，迁移时要逐个过形态审计，不管它近期有没有被 exercise。chapter-09 第七节末尾预告过，下一次代际级切换大概率还会冒出新的 audit 漏点——本案就是那个漏点，比预言来得快。

---

## 八、三案同构：测量仪器先于实验

把三案并排放：

| | 坏掉的测量层 | 污染范围 | 潜伏期 | 查实手段 |
|---|---|---|---|---|
| prompt 版本 | 实验配置无记录、靠口头标注 | 5/15 后所有数据的版本归属 + 三轮 prompt 改进未上线 | 44 天 | `git log -S` 钉历史 |
| reviewer 取文本 | 评分仪器对所有 provider 静默归零 | exp-006 判定 + memory + chapter-10 + provider 决策 | 26 天 | 换 provider 复现 + 读代码 |
| 代码版本锚 | 数据点没标产出它的代码版本 | 零（3 分钟拦截） | 3 分钟 | 连跑两次 + `git show` 旧版对照 |

同一个结构重复三次：实验层勤勤恳恳地跑，测量层悄悄地坏，所有下游结论跟着测量层一起错。BookScope 这个项目从第一天起就不信任 LLM 的训练记忆，要求一切结论带原文证据——但 6/10 盘点报告里那条结构性发现说得很准：项目不信任 LLM 训练记忆，**却完全信任了自己的测量层**。prompt 版本信了文件名标注，reviewer 可用性信了第 33 轮的旧印象，chunks 数信了首跑的输出。

三案的潜伏期梯度也说明问题：44 天、26 天、3 分钟。差别不在运气，在仪器纪律到位的时间点。prompt 版本案发生时没有任何版本观测，靠 22 天后一次人工评审撞出来；reviewer 案靠"作者给了新 key"这个外部变化撞出来；loader 案发生时，"留证据 dump"和"主 Claude 亲验再升级"两条纪律已经在场，所以当场拦截。**仪器越早建，翻案越便宜。**

修复动作也是同构的，全是 WP0 设计稿里那条控制论锚——先建观测，再动状态：prompt 版本先加 trace 字段和哨兵测试再切 v3.5；reviewer 先加 OpenAI 形态回归测试再修取文本；golden set 数据先加 n_chunks 守卫再继续标注。无观测不控制。

三案的查实手段也值得单独收进工具箱，都便宜、都不依赖运气：

- **`git log -S "<字符串>"`**——查"这个值是什么时候定下来的、之后谁动过"。prompt 版本案用它三条 commit 钉死 44 天的完整历史，比任何人的记忆可靠；
- **换一个变量复现**——失败如果跟着代码走而不是跟着 provider 走，嫌疑就在代码。reviewer 案换 DeepSeek 依然全空，一步把"minimax 行为"排除出去；
- **现代码连跑两次 + `git show` 旧版对照**——"不确定性"指控的标准核查流程。逐位一致排除随机性，旧版复现坐实版本差异。loader 案靠它三分钟收工。

三条的共同点：**先让证据替换印象，再下结论**。三案翻掉的旧结论，没有一个是当初用这三条手段里任何一条得出来的。

这条母题在本套案例研究里不是第一次出现。chapter-04 第八节的 baseline std 翻转——单次 baseline 当 ground truth 得出错误结论——是它的第一次现身；article-12 把它归纳成"实验设计的预设要先校验"；本章这一天，它被三个翻案从三个方向重锤了一遍，而且锤的位置更深：chapter-04 那次错的是**统计读数的解读**，本章三案错的是**读数本身的产生装置**。解读错了重算就行，装置错了，过去所有读数批量召回。

---

## 九、仪器修好当天就开始抓真问题

如果本章在第八节收尾，故事是"修了三个测量 bug"。但这一天的下半场给了一个更好的收尾：测量仪器修好之后，当天晚上就开始产出价值。

17:26 reviewer 修复、17:50 exp-004 跨题材验收 12 个 batch 跑完（数据 `docs/internal/experiments/data/exp004-{mingchao,anshi,zhinei,kuicheng}-run{1,2,3}.json` 共 12 份，commit `eca8a57`）——4 本书 × 3 run，19 分 57 秒并发跑完，生成和评分都是 deepseek-chat，prompt v3.5。这是 WP0 解冻当天的第一组带版本归属的数据，也是 minimax 时代单 batch 17 分钟的画像对照：12 个 batch 跑完只比当年 1 个 batch 多 3 分钟。

数据里埋着一起事故，exp-004 第 9.4 节拆开了它：kuicheng run1 q3，全场最低单题分 14 分。这道题问"想亏钱的项目意外爆赚"这个核心反转铺垫够不够厚，run2 / run3 同题都拿 23 分、答案 2014 / 2844 字逐案拆解；run1 的答案**只有 197 字**——一段结论，题目明确要求的"逐一检查"一个案例都没展开。

抓到它的是两个互相独立的测量装置：

- **citation 核验链**（当天 15:31 刚上线的 WP1）：run1 q3 挂了 13 条 citation，**11 条 unverified**——`chunk_id` 全 null，match_score 0.22–0.6。这 11 条不是原文摘抄，是带评论的转述（"裴谦看向马洋……——这里埋下摸鱼网咖持续扩张的伏笔"，后半句是模型自己的解读，原文里没有这句话），逐字核验自然失败。整个 run1 的 60 条 citation 里，unverified 的 11 条**全部**来自这一题——全场最低 verified 率 0.817，责任百分之百在它。run2 同题只有 2 条 unverified，run3 是 0 条。
- **reviewer**（当天 17:26 刚修好）：structural_judgment 2 分（"只给了结论没拆手法差异"）、actionability 2 分（"作家看完不知道哪条线要加料"）、evidence_density 3 分，评语里点名"只有两条标 verified"、"第 270 章那条 match_score 只有 0.22，几乎算误捡"。

一个从引用的字面核验侧，一个从答案的编辑价值侧，两边各自独立地把同一个坏输出按在地上——而且 reviewer 的评语直接引用了 citation 核验链产出的 verified 标记，两个装置开始互相喂证据。坏输出没有混过去——这是 citation 可信链上线后的首个正面案例，也是本章三次翻案故事的反面对照：**仪器在场的时候，坏数据当天现形；仪器缺位的时候，错误结论存活 26 到 44 天。**

exp-004 本身的验收结论顺带记一笔：跨书 std 1.02（验收线 ≤ 1.5，过），60 题 58 题有分，Sprint 3 在原窗口（5/29–6/11）最后一天压哨交付。但 22+ 的均分**不能**跟 minimax 时代的 19–20 比——生成和评分同为 deepseek-chat 的自评偏袒风险写在每份 JSON 的 `config.limitation` 里，generator / reviewer / prompt 三个变量同时换了，这组数据的正确用法是新 baseline 的第一组 std（书内 0.31–1.51，跨书 1.02），不是"分数提升"的证明。第 33 轮立下的 baseline 方差纪律继续生效。

数据里还有一条直接喂给下一节 WP8 的发现，记在 exp-004 第 9.6 节：zhinei q1 三个 run 拿 17 / 17 / 20，全场最低题——但检索完全正常（citation 14–16 条，verified 率 94%–100%），分掉在 actionability 三次只有 1 / 2 / 2。

根因 reviewer 自己说破了，run3 的评语原话："作家问的是『核心论点+支撑案例』，这偏向信息整理而非诊断修改，因此可操作性天生不强。"q1 是一道综述题，而作家 rubric 里 actionability 占 5 分——综述题在这个维度上结构性拿不到分，答得再好上限也就 21–22。**这道题测的不是 BookScope 在政论书上弱，是这道题和这把尺子不配套**——题集和 rubric 的错配，也是一种测量仪器问题，跟本章三案同一个家族，只是藏得更深：仪器没坏，仪器和被测对象不匹配。

6/11 上午的余波也属于这条线：exp-004 第 9.3 节记的两道缺分题——reviewer 分都打出来了（raw 里都是 22 分），一道毁在 trailing comma、一道毁在全角引号收尾——上午 10:03 补进 autofix 链（commit `4e4c183`）。报告引用一律按 JSON 落盘数字不做人工回收（回收后 anshi run3 均分 22.75 → 22.6、zhinei run2 19.0 → 19.6，方向上不改任何结论），但 autofix 链从此多两个 case。测量链上的小窟窿，发现一个堵一个。

测试基线给这一天画了一条增长曲线：早上盘点时 780，WP0 哨兵进来 789，WP1 / WP2a 进来 825，WP3 / golden set 进来 859，reviewer 回归测试进来 860；次日上午元数据修正后 874。一天净增 80 个测试，其中过半是三次翻案直接催生的守卫——哨兵测试、形态回归、n_chunks 守卫。翻案不只是收回结论，每次收回都在测量层上多钉一颗钉子。

这一天最后三个 commit 是傍晚 18:14–18:22 落的：WP5 / WP8a / exp-007 三份设计稿过闸（`4ffcb6b`）、PE 交付 loop v3.6 + reviewer rubric_v2（`d7b343f`）、ADR-009 多轮对话草案（`4ca6396`，次日上午作者签字）。翻案日的尾声已经在为下一轮实验铺仪器了。

---

## 十、未来工作面

本章收的三个翻案都指向同一个方向：BookScope 的下一段工程重心不在生成端，在**评估端的可信度**。两件已经排上的事：

**WP8 主体 · rubric 人机一致率校准。** exp-004 的 limitation 第 1 条悬而未决——deepseek 同模型自评的偏袒幅度到底有多大，现在没有数字。WP8 的设计（`docs/internal/design/2026-06-10-design-gap-review.md` 缺口 13）分三步：作者按 rubric 盲评 10–20 份历史 answer，算 LLM-人类相关系数——这是作者不可替代清单（每周自试）的自然延伸，AI 不代评；双 provider 交叉评分，实测自评偏袒的幅度；promptfoo 式 prompt 回归 CI，作为 OSS 发布前的必备闸门。第一步的物料 rubric_v2 已经在 6/10 晚间由 PE 交付（commit `d7b343f`），把 `total` / `overall` 字段语义钉死成硬 schema——exp-004 发现 DeepSeek 和 minimax 对这两个字段的理解正好相反（一家当数字总分、一家当文字总评），靠 provider 自己理解 rubric 输出格式这条路走到头了。

**exp-001b · 引用精度基线重立。** exp-001 是北极星级验证（"引用精度 > 80%"），从未跑过——r0 口径已过时。作者在 6/10 NORTH_STAR 月度修订（commit `882c33c`）里裁决：以 r2 口径重立为 exp-001b，Sprint 9（案例研究整理阶段）补跑，指标保留。测量装置按设计评审拆成两个：**真实率**（snippet 可在原书定位的比例，WP1 的 verified 率就是它，程序可测、已上线）+ **支撑率**（citation 真支撑对应主张的比例，按 RAGAS faithfulness 思路拆 claim 测）。WP1 先观测后执法的第一批 verified 率分布——exp-004 全场 0.82–1.00——就是 exp-001b 的前哨数据。

两个续记钩子留在这里：minimax key 恢复后重测 reviewer，给"minimax 拒答"案一个真正的终审（现在的状态是"未知"，不是"无罪"）；chapter-10 第九节等 exp-006 的 reviewer 评分对照补跑后加续记，把那一节从"错误结论的现场"变成"错误结论 + 勘误链路"的完整样本。

测量仪器先于实验——这条规则在 chapter-04 的 baseline std 翻转里第一次出现，在 article-12 里被归纳成方法论，在本章这一天里被三个翻案从三个方向重锤了一遍。下一次它再出现的时候，希望是出现在哨兵测试的绿灯里，而不是勘误节的标题里。

reviewer 走出实验室是 chapter-07 那天；用户视角走进实验室是 chapter-08 那天；副管理姿态在一日内可重复执行是 chapter-09 那天；多证据链兜起失效判定是 chapter-10 那一周；**学会收回自己的结论是本章这一天**。前面几章 BookScope 在学怎么得出结论，这一章它在学怎么对待错的结论——对一个把"案例研究"当第一交付物的项目来说，后者大概更重要：读者最终要信的不是这个项目从来没错过，是它错的时候留下了完整的查实、勘误和防再犯链路。

---

*第十一章草稿到此为止。覆盖 2026-06-10 单日 25 commit + 6/11 上午余波：盘点（`b14e010`）、WP0 prompt 版本链（`c8f8a13`）、版本污染虚惊（STATE 第六段）、reviewer 翻案（`f99f94a`）、WP1 citation 可信链首个正面案例（`5f3b716` + exp-004 第 9.4 节）。定稿由作者在里程碑点统一润色。*
