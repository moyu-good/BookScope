# 设计缺口评审与工作包蓝图（2026-06-10）

**性质**：设计稿，待作者审。按设计先行规则，本文档批准前不动代码。
**来源**：作者问"设计的框架、蓝图和目的是什么 → 有什么细节需要补齐"。两路并发调研：内部设计审计（13 条缺口，全部带文件行号证据）+ 高星开源对标（`docs/internal/research-notes/002-oss-benchmark-survey.md`）。
**审计基准**：框架三条核心主张——①所有结论由查询时 agent 现场生成；②没有原文证据的结论一律不输出；③同时服务多种书型、最终服务百万字级网文。

---

## 〇、P0 发现：生产 prompt 一直是 v3.1，v3.2~v3.5 从未进过产品

这条不是设计缺口，是**正在发生的 bug**，单独提级。证据链（主 Claude 亲自验证，非 subagent 转述）：

1. **生产默认 v3.1**：`bookscope/agent/_internal/loop_shared.py:112` 硬编码 `loop_system_prompt_v3.1.md`。`git log -S` 证明这个常量自第 26 轮（引入 v3.1 时）从未改过——r1 时代在 `loop.py`，Sprint 7 ③a 原样抽进 `loop_shared.py`。**用户在浏览器里问的每一道题，从第 26 轮至今跑的都是 v3.1**。
2. **v3.2~v3.5 只活在实验里**：四个版本的改进（题型路由 / citation 厚度 / B-2-i 开关 / tool 并发指引）全部通过 `BOOKSCOPE_LOOP_PROMPT_PATH` 环境变量 override 在 batch 实验里生效，从未改过生产默认值。
3. **override 机制 Sprint 7 后已坏**：`scripts/run_batch_r1.py:338-347` 的 override 实现是 `from bookscope.agent import loop as _loop_mod` 再 patch `_loop_mod.SYSTEM_PROMPT_PATH`——`loop.py` 已于 5/15 git rm，**现在设了这个环境变量直接 ImportError**；即使 import 成功，r2 读的是 `loop_shared` 的常量，patch 错对象。
4. **probe 脚本文档撒谎且不实现**：`scripts/probe_kg_cache_quality.py:43` 自称"默认走 loop.py 内置 v3.4"——loop.py 已删、默认从来不是 v3.4；且该脚本只在 docstring 提到环境变量，**自己根本不实现 override**。
5. **数据归属污染**：exp006 quality probe 4 组数据（5/18-19）的 JSON 元数据没有 prompt 版本字段，实际跑在 v3.1 上，而实验设计文档写的是 v3.4。**exp006 内部对照仍有效**（empty vs warm 同 prompt 比缓存），但任何跟"v3.4 baseline"的跨实验比较无效。

**修复设计（批准后 BE+QA 执行，估 0.5 天）**：

- 指针切 `loop_system_prompt_v3.5.md`（副管理 take：v3.5 包含 v3.2~3.4 全部经实验验证的改进，新增的 tool 并发指引对应的代码能力 Sprint 5 早已落地，prompt 和代码终于对上）
- `LoopTrace` 加 `prompt_version` 字段，batch / probe 元数据强制记录（测量仪器先于实验——这是第 33 轮"baseline std 先行"教训的同款）
- 单测断言 `SYSTEM_PROMPT_PATH` 指向预期版本 + prompt 文本里的预算数字等于 `loop_shared` 常量（当前 prompt 说"上限 8 次"、代码是 12，见缺口 9）
- `run_batch_r1.py` override 改 patch `loop_shared`；probe 脚本真实现或删掉撒谎的 docstring

---

## 一、设计缺口 13 条（按对框架主张的威胁程度排序）

完整证据（文件 + 行号）见审计原文，此处每条压缩为三行。

| # | 缺口 | 打哪条主张 | 一句话 |
|---|------|-----------|--------|
| 1 | **citation 真实性零校验** | ② | snippet 是否真在原书里，系统层从不比对；prompt 写"编造=硬违规"但无执法机制；reviewer 明确豁免事实核验——循环依赖，谁都没把关。第 33 轮已实证模型会编造 |
| 2 | **citation schema 丢了 chunk_id** | ② | tool 返回带 chunk_id，final answer 的 citation 只剩 chapter+snippet——可验证性在数据结构层断掉，验证只能全书扫描 |
| 3 | **fast_path 自动拼 decoration 引用** | ② | `fast_path.py:405-415`：LLM 不给 citation 时系统取检索第一条前 200 字硬拼一条，与论点零对应——框架自己生产 rubric 定义的 1 分引用 |
| 4 | **"引用精度>80%"无操作性定义无测量装置** | ②+研究可信度 | 分子分母是什么没定义过；唯一 eval 集是 5 道 mingchao 通识题（正是 memory 明令避开的题型） |
| 5 | **检索质量从未评估，三处静默降级** | ① | 无 SiliconFlow key 时静默退 BM25-only 且不留痕；BGE-M3 中文网文效果无验证；relevance_score 局部归一化让"全不相关"也显示 1.0 |
| 6 | **章节号是检测序号不是书内章号** | ③ | 正则命中顺序赋号，不解析标题真实章号；漏检一个全书 citation 章号偏移；无章节书整本归第 1 章，三 tool 架构剩一条腿 |
| 7 | **百万字书扩展性零设计** | ③+性能硬规则 | 当前验证上限 4319 chunks（目标量级的 1/20）；300 万字 ≈ 8 万 chunks = 2500 次 embedding 请求 + 1300 次 KG 调用，和"10 秒读取"目标差两三个数量级，8 份 ADR 无一讨论 |
| 8 | **partial_evidence 是死字段** | ②的兜底承诺 | `events.py:131-146` 定义了（第 35 轮作者锤出的产品需求），`loop_r2.py` 全部 7 处 ErrorEvent 构造都不填——r2 重写时丢了 |
| 9 | **循环不收敛无诊断，prompt 与代码预算数字打架** | ① | prompt 说上限 8 次、代码 12 次；anshi q1 固有不稳已知但 loop 对"连续空转"零感知，只能傻跑到 180s timeout |
| 10 | **多轮对话不存在** | ①的产品兑现 | 创作者真实形态是连续追问；当前每问全量重启，上轮证据全丢。8 份 ADR、ROADMAP 任何地方没有设计讨论——不是"设计了没做"，是"没意识到要设计" |
| 11 | **KG 质量无验收线，两条静默失效路径** | ①③ | "弱于 v7"没有数字；jieba 兜底的角色 key_chapter_indices 恒空 → 两个 tool 对兜底角色失明；aliases 恒空 → "裴谦/裴总/老板"只命中一个 |
| 12 | **prompt 版本无单一事实源**（→ 已提级为 P0） | ①可复现性 | 见上节 |
| 13 | **reviewer 无人类锚点，盲区与缺口 1 重叠** | 研究可信度 | 全部改进证据是 LLM 评 LLM；同 provider 自评偏袒只写在 docstring；作者 dogfood 不满意点从未结构化为标注集 |

**三个结构性模式**（建议进 case-study，比单条缺口更有发表价值）：

1. **prompt 承诺 ≠ 机制保证**（缺口 1/3/9）——项目起点是"不信任 LLM 的训练记忆"，但完全信任 LLM 的引用诚实
2. **兜底路径静默劣化**（缺口 3/5/8/11）——五层兜底保住了"不崩"，没保住"降级可见"
3. **测量仪器先于定义**（缺口 4/12/13）——对一个把案例研究当第一交付物的项目，这类缺口比工程缺口更致命

---

## 二、工作包蓝图（缺口 × 开源对标 → 8 个 WP）

每个 WP 是一组强相关缺口的整体设计，避免逐条小修。排序 = 副管理建议的执行顺序。

### WP0 · prompt 版本链修复【P0，0.5 天，唯一建议立刻做的】

见上节。不做这个，后面所有实验数据都没有版本归属。

### WP1 · citation 可信链（缺口 1+2+3+4 × 对标 #3 #4）

把"原文证据"从 prompt 约定升级成系统保证：

- citation schema v2 加 `chunk_id`（必填，LLM 抄错时用 snippet 反查校正）
- 程序化校验层：snippet 与 chunk 文本模糊匹配（n-gram 重叠阈值），失败标 `unverified` 不展示——LlamaIndex 编号模式
- fast_path 自动拼引用改为：重试一次 → 回退 agent_loop → 实在不行带"系统自动定位，未经论点对应"标注
- "引用精度"操作性定义拆两个指标：**真实率**（snippet 可在原书定位的比例，程序可测）+ **支撑率**（citation 真支撑对应主张的比例，RAGAS faithfulness 拆 claim 测）——exp-001b 的测量装置就是它
- 估 3-4 agent 天。**这是框架核心主张的兑现，建议挂 Sprint 4（6/12-6/25）与 Sprint 3 验收并行**

### WP2 · 检索质量基线（缺口 5 × 对标 #1 #9）

- 四本测试书各标 20-30 条"query → 应命中 chunk"golden set，跑 recall@k / MRR 基线——检索失败和生成失败从此分开归因
- `ChunkMatch` / trace 加 `retrieval_mode` 标记（hybrid / bm25-only），降级可见
- Contextual chunk header 实验（chunk 前拼"书名+章节+一句话前情"再进双索引）——Anthropic 实测失败率近半下降，BookScope 架构即插即用
- 估 3 agent 天，golden set 标注可派 RE+QA 并发

### WP3 · 章节与书型鲁棒性（缺口 6 × 对标 #1）

- 章节号解析标题文本（中文数字转阿拉伯），不再用检测序号
- 检测置信度：检出 1 章但全书 50 万字之类的异常 → 上传时告警给用户
- 无章节书降级策略设计（虚拟分卷？按字数伪章节？）+ 每种书型的章节识别验收标准
- 分块可视化抽查页面（RAGFlow 模式）服务作者每周自试
- 估 4 agent 天

### WP4 · 百万字扩展性实测（缺口 7）

- 先实验后设计：拿一本 100 万字级公开网文实测三条曲线（上传耗时 / 索引内存 / 单查询延迟），数据出来再决定要不要 IVF 索引、分卷 ingest、embedding 按 chunk hash 增量缓存
- "10 秒读取"目标拆解：重新打开已索引的书（L3 缓存已解）vs 首次 ingest（无设计），后者的可接受上限需要作者定
- 估 2 agent 天实验 + 1 份 ADR

### WP5 · loop 收敛与降级可见（缺口 8+9 × 对标 #6 #8）

- partial_evidence 填充：loop 层 emit ErrorEvent 前从 trace 抽 search 类调用摘要（作者第 35 轮明确锤过的承诺，还债）
- 预算规则写进 prompt（简单题 3-10 次 / 诊断题 10-15 次）+ prompt 数字与常量一致性单测
- 空转检测：连续 N 轮 tool 输入输出高度重叠 → 注入"基于已有证据作答"；接近 timeout 剩 30s 主动触发强制综合轮
- 估 3 agent 天

### WP6 · 多轮对话 ADR-009（缺口 10 × 对标 #8）

- 这是唯一需要新 ADR 的 WP——形态选择影响 API schema、session 持久化、上下文管理三层
- 设计空间：完整 messages 续写（context 爆炸快）vs 上轮 answer+citations 进 system 附录（轻量丢证据）vs 上轮证据集作预热缓存 + smolagents 式旧观察压缩（推荐起点）
- 估 1 份 ADR + 5 agent 天实现，建议 Sprint 4 出 ADR、Sprint 5 窗口实现

### WP7 · KG 验收线（缺口 11）

- 定最低验收线：top-20 高频角色召回率 ≥ X%（拿 kuicheng 人工点验一次定 X）
- jieba 兜底补"按 chunk 文本反查角色出现章节"的廉价后处理，消掉两个 tool 的静默失明
- alias 缺失伤害实测（kuicheng "裴谦/裴总"命中率）后决定要不要 LLM 抽 alias
- 估 2-3 agent 天

### WP8 · 评估管线升级（缺口 13 × 对标 #5 #7）

- judge 人机一致率校准：作者按 rubric 盲评 10-20 份历史 answer（**这是作者不可替代清单的自然延伸**，每周自试时间可复用），算 LLM-人类相关系数
- 双 provider 交叉评分实测自评偏袒幅度
- promptfoo 式 prompt 回归 CI（OSS 发布前必备闸门）
- 估 2 agent 天 + 作者 1 小时盲评

---

## 三、与现有 ROADMAP 的挂载建议

| WP | 建议窗口 | 依赖 |
|----|---------|------|
| WP0 | 立刻（作者批准本文档即启动） | 无 |
| WP1 citation 可信链 | Sprint 4（6/12-6/25），与 Sprint 3 验收并行 | WP0（trace 版本字段） |
| WP2 检索基线 | Sprint 4 | 无 |
| WP5 loop 收敛 | Sprint 4-5 | WP0 |
| WP3 章节鲁棒性 | Sprint 5（6/26-7/9） | 无 |
| WP6 多轮 ADR | Sprint 4 出 ADR / Sprint 5 实现 | 作者签 ADR-009 |
| WP7 KG 验收线 | Sprint 5 | 无 |
| WP4 百万字实测 | Sprint 5-6 | 需 LLM cost 批准 |
| WP8 评估管线 | Sprint 6 + 作者盲评 1 小时 | WP1（faithfulness 复用校验层） |

Sprint 3（跨题材验收）不受影响照跑，但**建议等 WP0 完成后再跑**——否则 batch 又是 v3.1 数据，元数据还是没有版本字段。

---

## WP 落地状态（2026-06-11 回写）

本文档前面几节是 6/10 的设计稿语气，还在"待作者批"。作者批了之后这一个月大半工作包已经做完，逐条记一下当前状态，hash 已对过 git log。

**已落地：**

- **WP0 · prompt 版本链修复** ✅ — 生产默认从 v3.1 切到 v3.5、`prompt_version` 进 trace 成为单一事实源、override 机制修好。commit `c8f8a13`。
- **WP1 · citation 可信链** ✅ — 每条引用走系统层核验（`verified` / `match_score`），不再只靠 prompt 约定。commit `5f3b716`。
- **WP2a · 检索降级可见** ✅ — `retrieval_mode` 从 store 一路透传到每条 `ChunkMatch`，hybrid / bm25-only 降级在数据里看得见。commit `c717f8e`。
- **WP2 · 检索 golden set** ✅ — 74 条 query→应命中 chunk 标注集加 `eval_retrieval` 脚本和 BM25-only 基线。commit `05f0755`。配套的 contextual header 实验（exp-007）跑完判定不进产品——positional 召回 +25pp 但成本不划算，收口见 commit `118764e`。
- **WP3 · 章节鲁棒性** ✅ — 真章号解析（Phase A 观测 + Phase B 中文数字转阿拉伯）加检测质量可观测。commit `bb008d2`。
- **WP5 · loop 收敛** ✅ — 空转检测接入 + 接近 timeout 强制综合轮。commit `8481d9a`。
- **WP8a · rubric 版本管线** ✅ — reviewer rubric v2 进生产 + 题型感知解析（这是 WP8 评估管线里先拆出来能独立做的一块）。commit `716d0f6`。

**多轮对话升级成 ADR-009：**

- **WP6 · 多轮对话** → 升级为 ADR-009（作者已签字，方案 C 分两阶段）。Phase 1 已落地——Phase 1a 骨架加上轮答案注入 commit `e6c6208`，Phase 1b 追问指代消解 commit `eb2090c`。Phase 2（上轮证据集作预热缓存）登记表预热待排。

**还没做：**

- **WP4 · 百万字扩展性实测** ⏳ — 卡资源，还缺一本百万字级测试书。
- **WP7 · KG 验收线** ⏳ — 未动。
- **WP8 主体 · 人机一致率校准** ⏳ — 需要作者盲评一批历史 answer 才能算 LLM-人类相关系数，未排期。

---

## 四、需要作者拍板的三件事

1. **WP0 立刻执行**？（副管理 take：是。指针切 v3.5 + trace 记版本 + 修 override。所有后续实验的前置）
2. **WP1-8 整体方向认可**？认可后副管理按挂载表分 sprint 派活，每个 WP 动工前不再单独请示（ADR-009 例外，要你签字）
3. **百万字实测**（WP4）需要一本 100 万字级公开网文做测试书——你亲选还是授权 RE 自决？（上次 RE 自决选书被你撤回过，这次先问）
