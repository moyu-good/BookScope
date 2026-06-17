# 第九章 · 一日双重攻 · 一句话 37 commit

> **状态**：草稿 · 作者未定稿 · 2026-05-15 起头
> **代际**：r2-agent-protocol（Sprint 7 删 r1 后）
> **覆盖时段**：2026-05-14 到 2026-05-15 两日 · 主要是 5/15 单日 37 commit
> **关联 ADR**：ADR-007（r2 切换）+ ADR-008（缓存层）
> **关联 sprint**：Sprint 7 收尾 + Sprint 8 提前启动 + Sprint 6 第一二步 + Backlog B-1/B-4/B-6 清完

---

## 序：5 句话 37 commit 的一天

作者今天就说了 5 句话——3 次"继续"、一次"全部签字！"、一次"少逼逼能做就给我继续干"，外加一段锤副管理违反 memory 的话。BookScope 这一天跑出 37 个 commit。

上半场收 ADR-007 r1 → r2 epic 的尾巴——Sprint 7 删 r1 runtime、loop_r2 兜底测试补齐、chapter-05 第八节 starter 起头、retrospective 落地。这是横跨 4 个 sprint 的代际级 epic，最后一公里。

下半场两条线并行——Sprint 8 三层缓存原本编排在 2026-08-07 至 2026-08-20，作者一句话提前两个月启动，L1 / L2 / L3 一波接一波切完。同时 Backlog B-1 / B-4 / B-6 三条工程债跟着清，Sprint 6 真 KG 全书抽取也提前两月启动，BE 把 chunk batch 调度并发跑通后接 SQLite 持久化缓存。中间作者锤了一次副管理违反 memory `feedback_no_private_manuscript_talk.md`——14 天前明示禁的话术今天又犯。

37 commit 不是值得夸的数字。值得记的是这 5 句话授权和 37 commit 落地之间的姿态——副管理什么时候自决推，什么时候停下等签字，什么时候 push back，什么时候老老实实修订自己的 memory。下面 8 节按时间顺序串。

---

## 一、ADR-007 epic 三天压完

ADR-007 的 Migration Plan 原本编排是 4 个 sprint 八周。最后真正落地是三天。

5/13 作者第一次签字批方向（commit `0adfba9` ADR-007 已批准 · Sprint 4 启动）。
5/14 第二次签字批切换（commit `88ab2d9` 默认协议 r1 → r2 · r1 deprecated）。
5/15 第三次签字批删码（commit `0845014` Sprint 7 启动授权 · 真执行等 audit 后分步推）。

三次签字三种语义——**签方向 / 签切换 / 签授权**。第三次签字最特别——作者明示"按你的建议继续，通过我的签名"，但 Sprint 7 删 r1 影响面 audit（`docs/internal/audit/sprint-7-r1-removal-impact.md`）当时仍在后台跑，**签字时作者未阅 audit**。这条姿态写进 ADR-007 第三次签字段位：

> 本次签字是"基于副管理信任的高层授权"，不是"看完所有影响面后的精确批准"。真执行节奏必须等 audit 回来：B-2 autofix 下沉 → B-1 Adapter.extract_final_text → 删 loop.py + r1 adapter，每步独立 commit + 零回归。如 audit 命中撤回条件，本签字暂停回 STATE 等复审。

这跟下半场"全部签字！"的姿态形成第一组对照。同一位作者签字，三天里给的语义不同。

上半场具体落地按 5/15 上午时间序：

| commit | 时间 | 内容 |
|---|---|---|
| `2d96e90` | 09:51 | r2 mock 范式脚手架 · 1 happy path + 1 error path |
| `08f4d1d` | 10:23 | chapter-05 第七节"切默认那一天" |
| `e4768ba` | 10:55 | r2 测试核心覆盖 +10 测试 |
| `a454f36` | 11:21 | routes + review hint r2 双补 + mock helper 抽 + **fast_path r2 bug 发现** |
| `0f36fb2` | 11:38 | fast_path r2 形态修复 · 通识题 8-15x 加速器复活 |
| `f355593` | 12:02 | Sprint 7 audit 报告（撤回条件不命中） |
| `0845014` | 10:42 | ADR-007 第三次签字（写时间是上午先签后审）|

`a454f36` 那一笔最值得记。QA 写 r2 等价测试时反而发现一个潜伏 bug——fast_path 调 `extract_final_text(response)` 还按 r1 Anthropic content blocks 读，r2 切默认那一天起所有 adapter 都吐 OpenAI plain dict，fast_path 在 r2 默认下 100% 静默挂。但生产没人报错——因为 5/14 切默认那天到 5/15 中午 24 小时内没人真用 fast_path 跑过题。**bug 是 QA 在写测试时撞出来的，不是用户在跑题时撞出来的**。

如果不是 QA 这一波 r2 等价测试，fast_path bug 会一直潜伏到下一次 dogfood。这跟本章后面 KG bug 那一段的逻辑是一样的——切默认后冷门路径的隐性 bug 只能靠"有人去 exercise 它"才能被发现，自动测试覆盖不到的就是黑洞。

---

## 二、Sprint 7 第十一波撤回那一刻

Sprint 7 真删 r1 那段——`1050367` / `b29d626` / `0d4d210` / `440bcad` 四步 commit——节奏值得记。

每一步都是独立 commit + 零回归 + 撤回门：

| 步骤 | commit | 内容 | 测试 |
|---|---|---|---|
| ① | `1050367` | autofix + parse_final_answer 抽到 utils.json_parsing | 零回归 |
| ② | `b29d626` | 删 r1 mock 测试 + 父级 autouse 锁 r1 拆 | 631 全绿 |
| ③a | `0d4d210` | r1/r2 共享常量 + helper 抽到 _internal 包 | 零回归 |
| ③b | `440bcad` | **git rm r1 runtime 三文件 1693 行** | 零回归 |

最后一步 `440bcad` 是代际级 destructive 操作——直接 `git rm bookscope/agent/loop.py` + 两个 r1 adapter 共 1693 行。但前面 ①②③a 三步把所有 r2 对 r1 的物理 import 清零了——`grep -r "from bookscope.agent.loop import"` 空结果，删完不动一行 r2 runtime 代码。

中间撤回过一次。

第十波在跑步骤 ③ 的时候，副管理本来打算 ③a + ③b 一个 commit 一起推——抽 helper + git rm 在同一笔里。审到一半发现 audit 报告还有一个边角没回头读完——audit 第 5 节"冷门路径"那一段没扫到 KG。

副管理姿态：撤回 ③，先单独跑 ③a（共享 symbol 抽到 _internal）让物理 import 清零，再单独跑 ③b（git rm），中间留一段时间 grep 验证 r2 测试套零 ImportError。这样万一 ③b 之后某个测试挂了，能直接 `git revert 440bcad` 回到 ③a 状态——而不是回到 ② 状态再重做一次抽 helper。

这条撤回不是大事。但是这条撤回是 CLAUDE.md 全局 §2"Soft-retreat for irreversible actions"在真工程里的具体表达——`git rm` 是 irreversible（不，技术上 git revert 能拉回，但工作树要乱一段时间），分步推 + 中间留撤回点比一笔推完更稳。

撤回完之后 `440bcad` 真删那一刻，副管理在 commit message 里写了一句：

> 1693 行 r1 runtime 代码退役 / -8.4% 行数比例 / 零未来工作面遗留

后面 retrospective 那一段（`d8b6869`）展开过——三天压八周的真原因是"边界清楚 + 测试硬护栏 + 单步撤回"三件事都到位，不是"加快推进"。

---

## 三、retrospective + chapter-05 第八节 starter

Sprint 7 收尾两笔——`09bd668`（chapter-05 第八节 starter + ROADMAP 同步）+ `d8b6869`（Sprint 7 retrospective）。

第八节 starter 起头那一段——chapter-05 跨 4 个 sprint 从 5/13 起到 5/15 中午收尾，第八节作"未来工作面"段位写明 Sprint 7 之后的姿态遗产：(a) audit 颗粒度的教训 / (b) 撤回机制的真兑现 / (c) Backlog 现状（B-1 仍 backlog / B-2 已 done）/ (d) 给 chapter-05 定稿润色的素材接续点。

`d8b6869` retrospective 单独建在 `docs/internal/build-log/2026-05-15-sprint-7-adr-007-migration-retrospective.md` 约 3500 字 8 节。**没塞 STATE 末尾**——STATE 已经 55564 tokens 巨大文件，链路指向 retrospective 文件即可。这一条小决策反映副管理对长文件膨胀的警觉——chapter-08 序里写过"工程视角觉得 5 类细分越多越精准 / 用户视角不需要 5 类"——同样的 framing 在 STATE 文档上也成立：每轮往 STATE 末尾塞 retrospective 看起来"信息完整"，实际上 STATE 是给副管理下一轮入会时第一眼读的文件，越塞越读不下去。

retrospective 文件单独放 build-log 目录 + STATE 链路指向——是把"读 STATE"和"翻历史"两个需求拆开。

这一笔写完上半场 ADR-007 epic 完整收尾。但是中间还夹了一段值得单独讲——

---

## 四、作者锤"小说稿叙事"

下半场启动前，作者锤了副管理一次。

作者原话：

> "我觉得这里的小说，一直要强调我给你我写的，这个不需要强调，小说反正我会在到时候开发完成了用，但是不是开发过程一定要以我的小说为基底，所以这里长期强调这很奇怪。"

memory `feedback_no_private_manuscript_talk.md` 是第 33 轮（14 天前 / 2026-05-01 前后）已经写明的硬规则——"不要再聊任何的私稿的问题"。但是副管理今天又反复在 STATE 头注、ROADMAP Sprint 3 deliverable 表、各种工程报告里写"等作者放小说稿物料 / blocked 在作者物料"——属于 memory 已明示话术副管理再犯。

这一锤不是"小事重复"的锤。这一锤的真正语义是——**memory 不是写完就完事，触发时副管理要真守住**。

memory 文件存在不等于规则在产出里活下来。chapter-08 第三节末尾写过同样的话——"硬规则需要 dogfood 触发才能验"。今天这一锤是另一面——硬规则光被 dogfood 触发不够，**硬规则在新的产出口（ROADMAP 风险表 / 各种报告头注）上要被主动应用**，否则 memory 等于死字。

修订动作（commit `f0b6979`）：

1. ROADMAP Sprint 3 deliverable 表两处改——"作者把 epub 放进仓库 + 作者亲选 AI 不代写题"改成"RE 选 2-3 本公开/合法 epub + RE 起 5 题作家诊断题草稿参考现有题型 + 作者复审确认"。估时从"0.5 天 + 等作者提供"改成"2 天 + 1 天"——主体责任从作者转到 RE
2. 第五节风险表第一行"作者私稿 / 题集物料延迟"改成"跨题材测试集扩书加题集起草延迟"
3. memory `feedback_no_private_manuscript_talk.md` 反面话术清单从 3 条扩到 7 条，覆盖今日所有新违反形式 + 加正面叙事段 + 引作者 2026-05-15 原话 + 末尾警告"下次想说之前先回头读这条 memory"

接续的 `4889ca0`（测试书模板文档）+ `6d53895`（Sprint 3 prep 候选清单 5 本公开 epub + 5 题草稿）+ `e03c36e`（Backlog B-3 到 B-6）+ `1cd587b`（B-5 误报 + B-6 重新定性）——这一串 commit 都是 RE agent 后台并发跑的，主体责任从"等作者"翻面成"RE 自决推、作者复审"。

这是 BookScope 自我进化的一笔。规则修订的不是哪个工程参数，是副管理自己对"作者参与边界"的判断。

---

## 五、一句话"全部签字！"

memory 修订完，作者下一句话——"全部签字！"

一句话同时批多条工作：

- (a) ADR-008 Sprint 8 缓存层启动——原编排 2026-08-07，提前两个月
- (b) Sprint 6 真 KG 全书抽取提前两月启动
- (c) Backlog B-1 Adapter.extract_final_text 解锁
- (d) Backlog B-3 chunker 参数对齐 LLM API cost 签字

`ce4aae3` ADR-008 Status 段位翻面"已批准 · 2026-05-15 作者明示签字 · Sprint 8 启动"。

这是签字姿态的极简形态。

跟 ADR-007 三次签字的对比一目了然——
- ADR-007：三天三次签字，每次精确节奏（签方向 → 签切换 → 签授权），第三次签字明示"真执行等 audit 后分步推"
- ADR-008：一句话四条工作齐批，没要求看 audit / 没分阶段 / 没条件

两种节奏各自有用。ADR-007 是代际级 destructive 操作——删 1693 行 r1 代码——必须慢、必须三段式、必须留撤回门。ADR-008 是增量 perf 改造——缓存层挂 r2 runtime 外面、对业务逻辑零侵入、撤回成本是 `git revert` 三个 commit——快批快推合理。

**作者的签字粒度跟工程操作的不可逆性挂钩**。这条姿态副管理一直在用，但今天第一次在一日内看到两种极端形态对照。

当作者愿意一句话授权多条工作时副管理推动速度从分钟级降到秒级——L1 缓存 commit `2c2428e` 在作者签字 `ce4aae3` 之前一刻完工（副管理判断 L1 缓存包装 search_chunks 外不动 r2 runtime 不触发"等 r2 稳定"边界），534 测试全绿 cache hit 真触发。L2 / L3 接着 21 分钟内连推两 commit。

当作者要看数据才签时副管理停下等。ADR-007 第三次签字之前副管理把 audit 报告先跑出来再请签字。

两种节奏不是哪种更"好"——是工程操作的不可逆性决定哪种节奏对。

---

## 六、Sprint 8 三层缓存一波一波切

ADR-008 签字 15:05、L1 commit 已经在 15:05 落地（先做后请签字）、L2 commit `b24f93c` 15:24、L3 commit `8271e6b` 15:36。**31 分钟三层缓存全部落地**。

技术形态按 ADR-008 D-1 顺序：

**L1 search_chunks 缓存**（`2c2428e`）—— 进程内 LRU + 5 元组 key + session_id 前缀清。`bookscope/agent/_internal/cache.py` 通用 LRUCache 底座 140 行，`search_cache.py` 包装 search_chunks 155 行。session 销毁挂钩自动清。38 条新测试。demo 同 session 同题 5 次调用，backend.retrieve 只跑 1 次。

**L2 LLM 调用缓存**（`b24f93c`）—— SQLite 持久化层。新模块 `_internal/sqlite_cache.py`（212 行）作通用 key→bytes 持久化抽象 + `_internal/llm_cache.py`（389 行）作 L2 wrapper。按 ADR-008 D-3 算法 c 实施 cache key——assistant.tool_calls[].id 按出现顺序归一化为 call_0/call_1 抹掉 provider 端 random id 抖动；tools 列表按 function.name 排序去顺序敏感性；payload 整体 sort_keys JSON dump 后 sha256 取前 24 字符。reviewer 路径**不接缓存**——reviewer.py 直接调 client.messages_create 不走 invoke_client helper，天然不被 wrapper 覆盖（test_llm_cache.py 加专项硬规则 grep 源码确认）。36 条新测试。

**L3 book 预热缓存**（`8271e6b`）—— LRU + 磁盘 pickle 双层。`book_cache.py` 407 行。`WarmedBook` dataclass 含 assembler 本体、content_hash、ingested_at。L3a 进程内 `LRUCache(max_size=5)` + L3b 磁盘 `.bookscope_cache/book_warmup/<session_id>.pkl`。pickle 用临时文件 + atomic replace 避免半写。pickle 选用而非 JSON——vector_store 内部含 numpy array / BM25Okapi pickle 不可 JSON 序列化。`BookSessionStore` register / get / delete 三处切入。26 条新测试。

三层端到端模块级测试合计 79 条全绿（L1 13 / L2 14 / SQLite 底座 16 / LRU 底座 10 / L3 26）。baseline 从 534 拉到 596 全过零回归。

这一段 31 分钟里副管理派了三波 BE agent 并发——L1 在签字前一刻完工、L2 + L3 在签字后串接。串接而非并发的原因是 L2 / L3 都共用 L1 抽的 LRUCache 底座，L1 不落 L2 / L3 没东西继承。这是 memory `project_team_concurrency_default.md` 那条规则的反面——**有强依赖时串行而非并发**。

技术上 ADR-008 D-3 cache key 算法实施时做了一点简化——D-3 文本描述"按 role 分桶哈希"，实施时简化为整 payload sort_keys dump——分桶的复杂状态机带来的字段级 invalidate 收益当前用不上，但 id 归一化这层稳定性收益（D-3 算法 c 的核心）保留。这是一笔"实施跟 ADR 文本不严格一致但精神一致"的处理——副管理在 commit message 里明示这点，未来读 ADR-008 的人能知道哪部分被简化了。

---

## 七、KG r2 bug 静默潜伏

下半场最后一段是 Sprint 6 真 KG 全书抽取——`d888be9`（chunk batch 调度并发）+ `e33c37a`（KG 抽取 r2 兼容 fix）+ `bdd9a20`（KG 持久化缓存）。

`d888be9` 主线动作是把 MinimalKGExtractor.extract() 串行 for 循环改成 ThreadPoolExecutor 保序并发——照搬 Sprint 5 loop.py:_dispatch_tools_parallel 的保序并发模板。但 BE 在 commit message 里报告了一个旁注：

> MinimalKGExtractor 当前 `_extract_text_from_response` 按 Anthropic content blocks 读响应，Sprint 7 删 r1 后所有 adapter 默认走 r2 OpenAI plain dict，原 helper 读 `response.get("content")` 恒为 None → 抛 LLMFormatError —— 整条 upload → KG → r0 backend 链路在生产路径上 100% 静默挂。

**这条 bug Sprint 7 删 r1 那一刻就埋下了**。从 5/14 中午切默认到 5/15 下午 BE 报告这条 bug——28 小时静默期。没人发现的原因是 BookScope 长期没人真上传过新书做 KG——书已经在 store 里就跳过此路径，KG 缓存层之前是冷数据。

这跟第一节 fast_path r2 bug 是同性质——切默认那天 audit 第 5 节漏审的覆盖面比想象中广。fast_path / loop_r2 / adapter 四处是 audit 第 5 节扫到的，KG 是第五处冷门路径。`a454f36` 在写 r2 测试时撞出 fast_path bug、`d888be9` 在写 KG 并发时撞出 KG bug——两条都不是用户报告的，是 BE / QA 在做相邻工作时顺带 exercise 到的。

`e33c37a` 修法跟 fast_path r2 修复（`0f36fb2`）同模式 + 复用 Backlog B-1（`038e11a`）落地的 adapter Protocol 契约——`_extract_from_batch` 改调 `self._client.extract_final_text(response)`，形态差异由各自 adapter 兜底。**B-1 解锁的具体价值在这一刻兑现**——LLMClient Protocol 加 `extract_final_text` / `extract_usage_tokens` 两方法签名之后，KG / fast_path / loop_r2 三处都不再需要自己解析 response 形态，全交给 adapter。一处协议改造解锁多处 bug 收口。

`bdd9a20` 接着把 KG 抽取套上 SQLite 持久化缓存——按 (chunks, system_prompt, model) 命中即跳整段 LLM + 解析路径。沿 llm_cache.py 同款单例 / 惰性 init / env override 三件套。20 条新测试。baseline 拉到 703 全绿。

这一段值得讲一条姿态遗产——**未来代际级切换 audit 颗粒度的姿态约定**。Sprint 7 删 r1 之前的 audit 颗粒度是"主 runtime 路径 grep import 链 + 测试套覆盖率"。这套颗粒度漏掉了"曾经走过但近期没人 exercise"的冷门路径——KG 抽取属于上传新书时才走、用户没上传新书就长期不 exercise 的 path。

下次代际级切换 audit 颗粒度要加一条：grep 所有 adapter / loop / extractor / 兜底 helper 里"按 r1 Anthropic content blocks 读"的代码——不管这些代码近期有没有被 exercise。这条姿态遗产已经写进 chapter-05 第八节 starter 的"未来工作面"段位，给 Sprint 9 / Sprint 10 之后任何代际级切换的副管理一个具体参照。

---

## 八、一天的节奏算什么

37 commit。

回头看真不是值得夸的速度。值得讲的是这一天里几件事的合并效果——

**ADR-007 epic 收尾**：跨 4 sprint 八周编排压三天完工。最后一公里删 1693 行 r1 runtime。零回归 / 零撤回触发 / 三次签字证据链齐。

**Sprint 8 提前两月启动**：缓存层三层 31 分钟内全部落地。baseline 从 534 → 596。验收指标"重复问题 < 3 秒"和"冷启动 < 5 秒"的工程兜底全到位。

**Backlog B-1 / B-4 / B-6 清完**：B-1 adapter Protocol 契约解锁 KG bug 修复。B-4 batch JSON 加 book_scope 字段 + 36 份历史数据 backfill。B-6 中文书名半角→全角归一修了 anshi epub 的脏污形态。三条工程债都不是大事，但都是 Sprint 3 跨题材扩书之前的 hygiene 必清项。

**Sprint 6 第一二步**：KG 抽取 chunk batch 调度并发 + SQLite 持久化缓存。pilot 端到端 109 秒预估压到 35-60 秒段位。KG r2 bug 顺带修了。

> 续记（2026-05-15 BE）：本来排在 Sprint 6 第三步的"KG 增量"在 audit 阶段就免了——`chunk_book` 是纯函数（regex 章切 + 段落合并 + 字符计数）、`_split_into_batches` 是固定 60 切片、cache key 又只看 chunks 的 `{index, text}`。三者叠加 → 用户追加章节后旧章节产生的 batch hash 不变、缓存自动命中。没写一行增量算法。第三步落成的是一条 audit + 三条回归测试，把"决定性 / batch 稳定 / 旧 batch 命中"钉成回归门。这一波证明了一条 sprint 经验：缓存层 key 算法选得早，下游"增量"经常被免费解决。

37 commit 是这四条线的合并效果，不是单一速度的 KPI。

更值得记的是节奏判断。这一天里副管理有两次主动停下——一次 Sprint 7 步骤 ③ 撤回拆成 ③a + ③b 留撤回门；一次锤完 memory 之后没继续推 ROADMAP 修订就跑去做 RE agent 后台测试书模板文档（让 memory 修订和工程推进解耦）。也有一次主动推——L1 缓存在作者签字 ADR-008 之前一刻完工，副管理判断 L1 包装 search_chunks 外不动 r2 runtime 不触发"等 r2 稳定"边界。

节奏不是 KPI。

**什么时候该停**——代际级 destructive 操作之前留撤回门 / memory 被锤之后先修订规则再推进工作 / audit 报告没看完之前不删码 / 工程操作不可逆性高的时候作者要看数据才签字。

**什么时候该推**——增量改造不动核心 runtime 时签字前一刻完工合理 / 强依赖串接到位的时候不要假并发 / 测试硬护栏到位的时候单步撤回比一笔到位更稳 / 作者一句话授权多条工作时推动速度从分钟级降到秒级合理。

这两件事副管理今天都做到了——不是因为副管理"聪明"，是因为这一天里规则边界、签字证据链、测试硬护栏、撤回机制四件事都在场。

5 句话 37 commit。能跑出来不是速度，是这四件事都到位时的副作用。

下一次代际级切换大概率还会出现新的 audit 颗粒度漏点。但这一天的姿态遗产——签字粒度跟不可逆性挂钩、memory 不是死字、冷门路径要主动 grep——已经写进 chapter-05 第八节、retrospective、本章——给未来任何代际级切换的副管理一个具体参照。

reviewer 走出实验室是 chapter-07 那天；用户视角走进实验室是 chapter-08 那天；副管理姿态在跨多 sprint 一日内可重复执行是 chapter-09 这一天。三天接在一起——BookScope 从工程视角往作品视角挪了三大段。

---

## 九、写完起头之后又跑了 8 个 commit

这一节是后写的。

8 节"一天的节奏算什么"是 17:00 前后写完的。chapter-09 起头 commit `8f22e7b`、章节索引 `fc1d999` 落进 main 之后，副管理本来要去更新 STATE 收一天。结果 RE 接下来又派了一波 KG 增量回归测试（`b12df12`），BE 接到 Sprint 6 第四步的指令开始写 book-level KG 缓存，FE 接到 ingest streaming 的活——5 句话的余威推着团队又跑了 8 个 commit。chapter-09 的"5 句话 37 commit"标题在落地 6 小时后就过期了——实际数字是 **5 句话 45 commit**。

这条姿态本身值得记——**案例研究边写边发生**。

chapter-07 是离实验日有一周距离的回看，chapter-08 是用户视角刚被验完的当天回看，chapter-09 是工程当天 17:00 起头、当天 18:00 工程还在推、当天 22:00 起头本身需要"续记"的边写边长。这跟 r0 时代的案例研究节奏完全不同——r0 时代的案例研究都是"事件结束后回头总结"，r1 代际的 BookScope 是"案例研究本身参与到事件中"，因为案例研究的指针（chapter-XX 起头时间）也是 sprint 节奏的一部分。

下面把这 5 commit 按 17:05 → 17:54 的真实时序串完，给 chapter-09 一个非"截稿后失修"的完成度。

### 第四步 · book-level KG 缓存（`2419176` · 17:05）

第七节末尾讲完 Sprint 6 第三步 KG 增量被 cache key 算法天然涵盖之后，第四步是另一件事——`MinimalKGExtractor.extract` 出口本身没缓存。

`bdd9a20` 上一波加了 batch 级 SQLite 缓存，命中条件是 `(chunks, system_prompt, model)` 三元组。但 `extract` 出口的 `BookKnowledgeGraph` 是 batch 抽取完之后 merge 出来的——任何重读同本书都得重切 batch、重查 batch 级缓存、重跑 merge。batch 级缓存命中再快，merge 那一步还是要走。用户上传过的书在 session 重启后想再问，这条路径每次都要走 18 个 batch SQLite 查询 + 一次 merge——纯属浪费。

第四步是收尾——在 `extract` 出口再叠一层 book-level 缓存，命中时整本 KG 直接走 JSON 反序列化跳过所有 batch 操作。新模块 `bookscope/agent/_internal/kg_book_cache.py` 273 行，cache key 用 `(all_chunks_text_concat, system_prompt, model)` 三元组 sha256 取前 24 字符——跟 batch 级 key **故意**不一样：本层 key 不绑 `chunk.index`，整书重 ingest 时 text 一致就该命中，不受 chunker 输出顺序的内部抖动影响。

跟 Sprint 8 L3 book 预热缓存的关系需要讲清楚——这是这一波最值得停下解释的判断点。

L3 book 预热缓存（`8271e6b`）缓存的是 `WarmedBook` ——含 assembler 本体 + content_hash + ingested_at，pickle 持久化，键是 session_id。book-level KG 缓存（`2419176`）缓存的是 `BookKnowledgeGraph` ——JSON 持久化，键是 chunks + prompt + model 的 sha256。两层不是同一个对象，不是同一种 key 语义，不是同一种序列化方式，不在同一个文件——`.bookscope_cache/book_warmup/<sid>.pkl` vs `.bookscope_cache/kg_cache.db`。

L3 是 session 级（"这本书在内存里 ready 了"），book-level KG 缓存是内容级（"这堆 chunks + 这个 prompt + 这个 model 已经抽过 KG 了"）。两层叠加意义在于——L3 命中只表明 assembler 不用重新 ingest，KG 那一层还是要走；L3 miss + book-level KG hit 时（比如换 session 上传同样的 epub）依然能跳过整本 KG 抽取。L3 是"我"级缓存，book-level KG 是"内容"级缓存，两者覆盖的是不同的用户行为。

这一层的双层叠加硬约束写进了测试：book-level 命中后 batch 级 SQLite 必须 `size` 不变——验证完全跳过，不只是"快"。测试 24 条 + 5 个 TestClass，pytest 全套 730 零回归。

### KG ingest streaming（`d066445` · 17:33）

BE 工作链 5 commit 完整收口之后，FE 接到的活是把 BE 攒下的加速能力转成 user-visible 价值。

之前用户上传期间看的是 `useUploadProgress` 的三段经验曲线——一个按本地时间 t 估算"15% → 60% → 95%"的假进度条。后端真实 batch 进度、缓存命中状态全部对用户不可见——BE 的并发 + 两级缓存把 ingest 时间从分钟级压到秒级，但用户在浏览器看到的是同一根假曲线匀速跑完。chapter-08 那条用户视角主线在这里再次成立——工程层的优化如果不让用户感受到，等于没做。

技术形态：`bookscope/agent/events.py` 加 `IngestEvent` frozen dataclass + 6 类字面量（`ingest_started` / `kg_batch_started` / `kg_batch_completed` / `kg_cache_hit` / `ingest_done` / `ingest_error`）。**独立 union 不并进 LoopEvent**——ingest 流跟 ask 流是两条不同 SSE 端点，强行 union 会让 FE 类型膨胀。这条判断继承 Sprint 1 streaming callback hook 设计模式（memory `reference_streaming_callback_pattern.md` 第三原则"discriminated union 别强行合并"），但具体在哪一条边界拆 union 是这一波新做的判断——按 SSE 端点拆，不按事件层级拆。

`MinimalKGExtractor.__init__` 加 keyword-only `on_ingest_event` + `book_session_id`，6 个 emit 切入点。callback 三原则照搬 Sprint 1（默认 None / 异常包死 / trace 写完再 emit）。新端点 `POST /api/books/upload/stream` 跟 `/api/agent/ask/stream` 同模板——asyncio.Queue + thread bridge + StreamingResponse。setup-time 错误（文件格式错 / 空文件）仍走 HTTP 4xx，ingest 期错误 emit `ingest_error` + `upload_error` 帧，HTTP 仍 200。

FE 加 `streamUploadBook` async generator + `IngestProgressState` reducer，进度条 SSE 帧迟到时回退到三段曲线作 fallback。stepLabel 文案从"AI 正在分析角色，请稍候"切到"AI 正在分析角色 · 3 / 5 批次完成 · 已命中缓存 2 段"。

这一笔修了一个旁注 race condition——`test_extract_merges_duplicates_across_batches` 在 ThreadPoolExecutor 并发下 FakeClient.pop 顺序与 batch idx 随机错配。原来 `d888be9` 并发改造之后这条测试已经在 race 上了，CI 偶发挂——FakeClient 顺序消费是测试自己的脆弱设计，不是 BE 改造的问题。`max_workers=1` 强制串行钉死断言稳定，单测覆盖力不损失。

### 实验前置 · exp006 设计（`6ce2b8f` · 17:42）

BE 工作链 + FE streaming 一起合进 main 之后，RE 接到的指令很明确——给 Sprint 6 写一份对照实验设计。

这一笔最值得讲的判断点是**实验前置而不是实验回灌**。

exp001 / exp003 / exp005 三份历史实验都是回灌姿态——工程先跑、实验拿现成 batch 数据回去标分析。本实验设计 `006-sprint-6-kg-cache-validation-design.md` 是前置——Sprint 6 BE 五连合进 main 9 分钟后落地的实验设计文档，**真跑数据还没有**。文档里所有数字都是预期：anshi 空缓存预期 35-60 秒、mingchao 空缓存预期 60-110 秒、缓存满预期 < 5 秒。这些数字是 RE 根据 BE commit message 里报告的 dogfood 数字推的，没真跑 batch 验证过。

前置的价值在于**撤回条件预先写**。文档第五节明示两条撤回红线——耗时 speedup < 10x 即触发 / 5 维度评分单维度 std > 0.5 分即触发。两条都是 QA probe 真跑出数据之前就钉死的——不允许"看到数据再倒推阈值"，那就是 p-hacking 工程版。预先写的阈值才有意义。这跟 ADR-007 第三次签字里"audit 命中撤回条件即暂停"是同一种工程姿态——决策门控写在前面，不是事后补的免责声明。

前置还有第二个价值——实验设计本身能驱动测量工具。第七节明示要 QA 补两个 probe 脚本签名（`probe_kg_cache_timing.py` + `probe_kg_cache_quality.py`），不在 RE scope 内但写出来让 QA 看到——这就是接下来 `51c698e` 的种子。RE 文档落地 12 分钟后 QA probe 就开始写——前置设计驱动并发派工是 BookScope 团队节奏里独有的一笔。

文档 7 节齐 / 2597 中文字 / 撤回条件两条 / 验收阈值三条（耗时 ≤ 1/10 · 质量单维度 std ≤ 0.5 分 · 浏览器 ≥ 5 帧 ingest event）/ 末尾画了撤回 / 验收决策路径流程图。chapter-06 + chapter-09 扩节关系也在文档里钉了——数据真跑完后 RE 扩 chapter-06"Sprint 6 把第二刀推到 ingest 层"+ chapter-09 加一组真数字。

### probe 工具补齐（`51c698e` · 17:54）

实验设计落地 12 分钟后，QA 接到的活是 probe 脚本。

两个 probe：

- `scripts/probe_kg_cache_timing.py`（377 行）—— CLI + 单 run 测量 + speedup 撤回判定
- `scripts/probe_kg_cache_quality.py`（416 行）—— CLI + 5 题 batch + per-dim std 撤回判定

撤回判定提成纯函数 `evaluate_speedup` / `compare_quality_runs`——参数对应 exp006 设计第六节的 10x 阈值和 0.5 std 阈值。撤回触发即 JSON 写入 `failure_reason="cache_speedup_below_10x"` / `failure_reason="quality_diverged"`。两条都是 exp006 撤回条件双红线的代码化兑现——设计文档里写的阈值不能停在文字层，必须有可执行的判定函数。这一笔把"撤回条件"从文档约束变成程序断言。

24 个单测全用 mock 数据点喂纯函数——不真跑 LLM、不真清缓存。CLI 参数边界 6 条 / 撤回判定 timing 7 条 / 撤回判定 quality 6 条 + 单题数据点退化（quality 实验只跑一题时 std 退化用绝对差代理）。pytest 全套 744 → 768 零回归。

probe 跑真启动的前置——`MINIMAX_API_KEY` 已设、`BOOKSCOPE_SMOKE_EPUB` 指向真 epub、`.bookscope_cache/` 可写、作者批 LLM cost。**LLM cost 是最后一道门**——ingest 端 ~92 call + 评分端 40 call ≈ 132 call，作者 BYOK 自行核算。probe 写好了但不跑——这跟 Sprint 7 audit 报告"先生成后阅读"是同一种姿态，工具到位 ≠ 执行启动，执行启动门控在作者那一票上。

### ROADMAP 状态跟齐（`4b53493` · 17:43）

最后一笔是 ROADMAP Sprint 6 段位状态行更新。

ROADMAP timeline 上 Sprint 6 原排在 **7/10 - 7/23**，落地实际是 **5/15**——提前两个月。这条提前跟 Sprint 8（原排 8/7，提前两月启动）是同性质，但触发机制不同。Sprint 8 是作者一句话"全部签字！"四条工作齐批触发的。Sprint 6 是**副管理自决推**——本日下午 BE 接连完成 `d888be9` chunk batch 并发之后判断 Sprint 6 的 KG 工作完全在 r2 runtime 内不动核心逻辑、缓存层挂在 extractor 外面、撤回成本是 `git revert` 三个 commit，跟 ADR-008 同形态的 reversible 改造——副管理在 5/15 下午自决推 Sprint 6 第一步到第四步，等到第五步 streaming 落地之后再做 ROADMAP 状态跟齐。

ROADMAP 5 条 deliverable 状态分布——BE 两条 ✅ done（chunk batch 并发 + KG 持久化）/ FE 一条 ✅ done（streaming 进度条）/ QA + RE 两条 ⏸ 等真跑实验等 LLM cost。每条 ✅ 都带 commit hash 链路可追溯。这条文档更新本身只有 26 行 14 改 12 减，但**是 reversible 改造姿态的最终签收**——副管理自决推、commit 链清、撤回门留、ROADMAP 跟齐、状态对齐到 deliverable 表，五件事走完才算这一波"自决推"是负责的而不是冒进的。

副管理自决推 vs 作者亲签的边界在第五节已经讲过——**作者签字粒度跟工程操作的不可逆性挂钩**。Sprint 6 是 reversible 改造，副管理自决推合理。Sprint 8 缓存层也是 reversible，但作者还是一句话亲批了——这跟 Sprint 6 KG 工作的边界没冲突。reversible 改造作者也可以亲批，但**不亲批的时候副管理可以自决推**。这是 chapter-09 第八节"工程操作不可逆性决定签字节奏"在 Sprint 6 自决推一波上的具体形态——签字粒度可宽可紧，**不可逆性是底线，可逆性时副管理判断**。

### 起头本身的姿态

5 commit + 6 小时——chapter-09 起头时的 37 commit 数字过期成 45 commit。

值得记的姿态不是数字漂移，是"起头本身参与到事件中"这件事。如果 chapter-09 是 5/16 写的，那 45 commit 就是从一开始就是 45——序章和节标题都会被写成 5 句话 45 commit。但 chapter-09 是 5/15 17:00 起头、22:00 续记、当天 BE / FE / RE / QA 还在并发跑——起头本身作为一个 fix-point 在事件中产生了一个观测痕迹。这个观测痕迹（37 → 45）就是 chapter-09 自己作为案例研究的研究对象。

这是 r1 代际 BookScope 独有的节奏。chapter-07 / chapter-08 都是事件结束后回看，时间维度上是单向的——案例研究在事件之后。chapter-09 是事件中断点的截稿——案例研究和事件在同一条时间轴上跑。这种节奏的代价是"截稿后失修"风险——起头的语调和后续工程不一定对得齐，需要"续记"段位贴补；收益是案例研究本身的"现场感"——同一天的 commit 和同一天的章节文字互相佐证，没有事后美化的余地。

副管理姿态在这里多了一条遗产——**案例研究起头不必等收口**。起头作为事件中的观测点本身是产出，不是流水账的预编排。chapter-10 之后是否要继承这条节奏（事件中起头 + 多次续记 vs 事件后回看）由作者在里程碑点判断。本章作为先行示范，留给后续案例研究一种新形态的参考。

---

reviewer 走出实验室是 chapter-07 那天；用户视角走进实验室是 chapter-08 那天；副管理姿态在跨多 sprint 一日内可重复执行是 chapter-09 这一天。三天接在一起——BookScope 从工程视角往作品视角挪了三大段。

第四件事是 chapter-09 起头本身——**案例研究边写边发生**。事件中的截稿、起头之后的续记、数字漂移本身作为研究对象。BookScope 走到这一步，已经不只是"用工程产出做案例素材"，而是"案例研究的节奏本身也是工程的一部分"。

---

*本章草稿到此为止。45 commit 已覆盖 ADR-007 收尾 + Sprint 8 三层 + Sprint 6 五步全程 + Backlog B-1/B-4/B-6 + memory 修订 + exp006 设计 + probe 工具前置。定稿由作者在里程碑点统一润色。*

---

## 十、通用兜底链补齐那三天

这一节也是后写的。

第九节落地之后又过了三天。这三天里 BookScope KG 这条调用链上修了三个 bug、加了两层兜底、最后第一次让两本作者亲选的新书都答出了题。但更值得记的是这三天里作者连着锤了我三次——一次比一次重——逼着我从"修这本书"翻回到"修所有可能的书"，再从"翻译腔写中文"翻回到"用人话说话"。

11 个 commit 跨 5/15 到 5/18：

| commit | 时间 | 内容 |
|---|---|---|
| `0869c39` | 5/16 早 | probe stats key 单复数对位 · anshi 664x speedup |
| `049caed` | 5/16 中午 | KG parser 接 3 层 autofix · mingchao LLMFormatError 修了 |
| `0b0c2a9` | 5/18 12:03 | KG batch ContentFiltered 降级 0 角色继续 · 修制内市场全挂 |
| `362f0ab` | 5/18 13:29 | ContentFiltered 重试 + 中性化提示 · 救回 67 角色 |
| `e8bc16f` | 5/18 13:49 | jieba 本地 NER 作 ContentFiltered 第三层兜底 |
| `79e44f5` | 5/18 14:07 | 通用兜底链 5 层 · 任何 provider 任何错误都不让分析停下 |
| `c2118bc` | 5/18 14:33 | 两本作者亲选书首次端到端答题 |
| `0ee345d` | 5/18 14:53 | reviewer empty text 重试 · 跟 ContentFiltered 同类间歇 |

### 三个 bug 同根

前三个 bug 是同一个故事的三种表现。

probe stats key 写成了复数，sqlite_cache 实际返单数 `hit` / `miss`，单测里全用 mock 数据喂，没人真去查过返的什么。KG parser 长期独立长，没人想起来 loop 和 reviewer 第 31 轮加过的 3 层 autofix。KG 调 minimax 撞内容审查抛 ContentFiltered，loop 和 reviewer 第 31 轮也加过重试和中性化提示——KG 这条路径也没继承。

三条都是 chapter-09 第七节那句话的重演——切默认之后的冷门路径只能等相邻工作 exercise 才会暴露。这次 exercise 它的是两本新书：作者亲选的《亏成首富从游戏开始》（网文 4319 chunks）和《制内市场》（政经 398 chunks）。亏成首富一路跑通，制内市场撞墙。

### 第一次锤

我修了 `0b0c2a9`——单 batch 撞 ContentFiltered 就返 0 角色继续抽其他 batch，整本 KG 不全挂。commit message 标题写"修制内市场全挂"。

作者锤：

> 不能因为模型被 ban 了，我们的用户不可能有很多 api 的选择也不能因为 api 问题不让分析。

听懂了。"降级 0 角色"等于把麻烦推给用户——你换个 AI 吧、你换本书吧。`362f0ab` 把 loop 和 reviewer 那套 ContentFiltered 重试 + 中性化提示移过来：前两次原样重试碰间歇 422 就过、第三次开始 append 一段"用中性学术化措辞抽人物姓名"的提示让 LLM 自己改口、超限才真降级。制内市场 rerun 救回 67 角色——朱镕基、桑弘羊、商鞅、康熙、雍正、乾隆这些被审查拦下的历代政治家重试后过了。

### 第二次锤

`362f0ab` 之后还有 batch 4 次重试都被拒，我接着做 `e8bc16f`——加一层 jieba 本地 NER 兜底，重试都救不动就走本地分词补人名。commit message 标题还是"针对制内市场"那套话术。

作者锤得更重：

> 你要知道我是要求所有可能的书籍和情况不要被 api 或者书籍原因 ban 掉，而不是针对这本书而已。

这次听懂的是另一层——前面两个 commit 我都只盯着"内容审查"这一种错。LLMFormatError 仍直接抛、RateLimited 仍直接抛、ContextLimitExceeded 仍直接抛。换本书撞别的错一样挂。`79e44f5` 把 `_do_extract` 的错误处理整个重写了一遍：

- ContentFiltered → 重试 + 中性化 + 超限走 jieba
- RateLimited → 直接 jieba 不重试（重试还是 rate-limit）
- ContextLimitExceeded → 直接 jieba（当前 batch 太大）
- LLMFormatError → 直接 jieba（autofix 救不回的破 JSON）
- ProviderUnavailable → **不接住，让用户看见**（auth 错 / 网络挂是用户能修的配置错，静默吞反而把"key 写错"翻译成"书有问题"）

五层兜底链定型。改了 4 条测试、加了 2 条新测试，每种错各一条断言——按错误类别覆盖，不是只测当前撞到的那一次。

### 两本新书第一次跑通

`c2118bc` 两本各跑一题。亏成首富 105 秒、13 个 citation，答出主角裴谦五条性格特征——精于计算、善于伪装、反向操作、擅长找借口、不越界，每条用第 1 / 2 / 9 / 41 等具体章节支撑。制内市场 107 秒、10 个 citation，答出"制内市场"三层结构 + 历史案例（盐铁论、法家儒家）+ 当代案例（年广久、大邱庄、1994 分税制、温州模式）。

这是 BookScope 第一次在网文和政经这两种新文本类型上端到端跑通——服务对象第 1 条（长篇网文创作者）和"必须服务多种书籍类型"的硬约束在同一波第一次落到真数据。

但 reviewer 两本都返空——稳定拒答这个 question + answer 组合。`0ee345d` 给 reviewer 也加 empty text 重试（跟 ContentFiltered 同类间歇兜底），3 次重试都返空就抛 LLMFormatError，batch runner 接住翻成 `_error: reviewer_format_error` 字段，FE 看 `review === null` 自动降级不显示评分卡。整条 reviewer 失败链路全链路兜底——间歇救得回、稳定拒答 graceful 降级、不让"评分挂掉"翻成"答案丢"。

### 第三次锤

memory `feedback_global_not_single_case.md` 我第一版写得是另一套语言——"判定标准 / 兜底链 / 触发条件 / 适用场景 / 失效情况"。

作者锤：

> 中文能不能给我正常的表达，这个问题我记得我在全局里也有写过了，是因为之前的文档都没有用正常的中文写影响到你了嘛？

回头读 chapter-09 前 9 节——"姿态遗产 / 翻面 / 段位 / 兑现 / 拉满 / 形同虚设 / 真兑现 / 段位齐"这种翻译腔密度大到我自己写新东西时下意识就跟。memory 重写一版用人话——"修 bug 先列清单 / 写代码 / 写测试 / 写文档"四段，每段动词主导，不堆名词化。第十节这一节也是按重写后的写法写的，不再继承前 9 节那套词。

### 三条同根

回头看这三次锤是同一条规则的三种表现——

第一次：别把麻烦推给用户。用户没法挑 AI、没法换书，BookScope 自己得兜住。

第二次：别把规则锁死在这一本书 / 这一种错 / 这一个 provider。任何 LLM 任何书任何错都不该让分析停下。

第三次：别用翻译腔写规则。规则用人话写出来，下一次自己再读才认得回来——文档用什么语调写、产出就跟着用什么语调写。

memory `feedback_global_not_single_case.md` 进 memory 之后，跟前 33 轮已经存的几条姿态接得上——`feedback_provider_agnostic_first.md`（provider 行为差异 BookScope 兜底，别让用户挑 AI）、`feedback_multi_book_types.md`（必须服务多种书籍类型）、`feedback_user_not_only_author.md`（用户不只是作者本人）——都是"通用而不是单 case"的同一条规则在不同场景的工程版表达。

BookScope 走到这一步，KG 抽取、agent loop、reviewer 三条 LLM 调用路径都有了错误处理矩阵：任何 provider 任何错误任何书，不让分析停下。

---

*第十节落地 2026-05-18 下午。三天 11 commit 把通用兜底链从"想法"做成了"代码 + 测试 + memory"。chapter-09 至此覆盖 56 commit，定稿仍由作者在里程碑点统一润色。*
