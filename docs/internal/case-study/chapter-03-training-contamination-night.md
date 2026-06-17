# 第 3 章 · 训练污染那一晚：批改试卷的人发现题库被泄了

> **状态**：草稿 · 作者未定稿
> **时段**：2026-04-26 至 2026-04-27（第 25 轮 + 第 26 轮主轮 + 后续 + 后续 #2）
> **覆盖 commit**：`2c1f331`（第 25 轮闭环）/ `7b71a26`（第 26 轮主轮)/ `9eac6a9`（后续 10 篇 article + citation_coverage helper）/ `70db8ad`（后续 #2 minimax+v2 ablation）
> **与第 2 章的关系**：第 2 章讲数据基座如何被慢修补成"r1 跑得动的样子"；本章讲在数据基座之上跑出来的第一组真分数为什么会被一次"换 provider"打回原形——以及这个失败本身怎么变成 BookScope 案例研究里**最值钱**的研究素材

---

## 一、序：批改试卷的人发现题库被泄了

把 BookScope 想成一所学校。

学生是被测的 LLM——它读完《明朝那些事儿》，回答作家的诊断题。卷子是 5 道作家级问题——节奏、支线密度、伏笔回收、角色转变可信度、设定漂移。题库是公开的、印在书上的、几百万人读过的中文出版物。批改试卷的人是 AI reviewer——它按 5 维 rubric 给学生打分。

第 25 轮的好消息是这所学校第一次**自己改对了自己**。reviewer 给学生 v1 答卷打 23 分；副管理拿 reviewer 的 audit notes 改 prompt 到 v2；学生重做同一道题，reviewer 给 25 分。23→25，闭环跑通。BookScope 的工程层面第一次有了一个能自我迭代的回路。

第 26 轮的坏消息是——批改试卷的人发现，题库被泄了。

更准确地说：被测的学生在做卷子之前，已经把整本书的内容背下来了。它不是在"读书答题"，是在"照着记忆默写"。它写出来的答卷看起来挺像样——结构判断对、节奏分析顺、措辞流畅——但 trace 显示它**几乎没去翻书**。

这章要讲的就是这件事被一次性发现、一次性诊断、一次性算清楚的两个晚上。从第 25 轮的"闭环刚跑通"出发，到第 26 轮主轮的 -4.8 分集体翻车，再到后续 10 篇集体写作的盲点被实算反证，最后到后续 #2 单变量 ablation 把 4.8 分退化精确分解成"5.2 分 provider + 0.4 分 prompt 反向修正"。每一段都是一组具体的数字、一段具体的 trace、一次具体的取舍。

这是 BookScope 案例研究里第一次出现"失败比成功更值得写"的章节。

---

## 二、第 25 轮：AI-as-judge 闭环首次收敛

第 25 轮的主线动作很短：把 reviewer agent 接进去，跑一道作家诊断题（"李善长铺垫连贯性"），看 reviewer 能不能根据 audit 反推出 prompt 该怎么改。

第 24 轮已经把这道题用 v1 prompt + astron-code-latest 跑过一次：73.9s / 11 条 citation / 横跨 ch 14 到 ch 21 七个章节。reviewer 给的 5 维分数是——

```
structural_judgment:    5
evidence_density:       5
honesty:                4
actionability:          4
cross_chapter_coherence: 5
total:                  23/25
```

honesty 和 actionability 各扣 1 分。reviewer 在 audit notes 里给了非常具体的两条——

第一条：answer 里几处推断（比如"李善长晚年与朱元璋的关系裂痕"）下了**断言**没下**显式 confidence 标注**——作家读到一段判断，分不清是"原文明示"还是"agent 推断"。这条扣的是 honesty。

第二条：answer 给了诊断但没给**作家可执行的改稿建议**——"如果要在第 18 章增强这条铺垫，建议在哪里加一段"。这条扣的是 actionability。

副管理拿这两条 audit notes 直接改 v1 prompt 到 v2，加了两段——

A 段：要求 agent 给出每条推断的 confidence 标注（"原文明示" / "原文推断" / "agent 解读"三档）。
B 段：要求 answer 末尾给出 1-3 条 actionable rewrite suggestion（具体到章节）。

prompt 改完后用 v2 + astron 重跑同一道题。这次 reviewer 给——

```
structural_judgment:    5
evidence_density:       5
honesty:                5  (+1)
actionability:          5  (+1)
cross_chapter_coherence: 5
total:                  25/25
```

23 → 25。闭环第一次自己跑通。

第 25 轮 commit `2c1f331` 当晚的 STATE 里副管理写了一句话：**"BookScope 的核心机制——原文证据现场调取——已经稳定了"**。这句话第二天被第 26 轮的数据反向打脸，但当时是真的相信的——v1 → v2 的 +2 分是 audit notes 直接驱动的、可重现的、有 trace 可查的——这是工程层面 AI-as-judge 第一次拿出"真的能改进"的硬证据。

这一晚的 setup 非常重要：**它让第 26 轮的失败有了一个能反衬出失败本质的对照基线**。如果第 25 轮没跑通这套闭环，第 26 轮 4.8 分退化只会被解读成"换 provider 之后效果差了"——一个普通的工程回归。但因为第 25 轮已经把"AI 改 AI"的可行性证明了一次，第 26 轮的退化就不能再用"工程层面"解释——必须往下挖到生成层、模型层、训练数据层去找原因。

---

## 三、第 26 轮主轮：切到 MiniMax-M2.7 与 reasoning model 的 think 标签

第 26 轮的开端是作者的一句指令——"继续，但是我们的 api 更新了。这次用的是 minimax，用的 2.7 的模型"。

base_url 改一行（`https://api.minimaxi.com/v1`），environment 加一对（`MINIMAX_API_KEY` / `MINIMAX_BASE_URL`），DeepSeekAdapter 因为走 OpenAI 兼容路径理论上不需要改。但工程层面的第一步并不是直接跑 batch——副管理先拿 minimax 跑了一次 5-token sanity check：

```python
client.chat.completions.create(
    model="MiniMax-M2.7",
    messages=[{"role": "user", "content": "你好"}],
    max_tokens=5,
)
```

这一刀切下去发现两件事。

**发现一**：MiniMax-M2.7 是 reasoning model。它在 `content` 字段里**直接 inline 吐 `<think>...</think>` 块**——

```
<think>用户说你好，我应该礼貌回复</think>你好！请问需要什么帮助？
```

这玩意儿喂到下游 JSON parse 会立刻炸——`<think>` 标签里的内容可能含半截 JSON、转义字符、双引号，整个 response 就废了。这是新一代 reasoning model 的通用毛病：deepseek-r1、qwen-qwq、glm-zero 都吐 think 标签，只是字段位置和标签名略有不同。

**修复**：DeepSeekAdapter 加一个 `_strip_thinking_tags(text: str) -> str` helper，在 `_from_openai_response` 里调用一次。对非 reasoning model 是 no-op（找不到 `<think>` 直接返回原文），对所有走 OpenAI 兼容路径的 reasoning model 通用受益。

```python
def _strip_thinking_tags(text: str) -> str:
    """Remove <think>...</think> blocks from reasoning model output.

    No-op when no <think> tags found.
    """
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
```

helper 14 行，调用点 1 行——这是典型的"surgical 修补 + 通用受益"动作。副管理 auto-accept 范围内不需要作者批准。

**发现二**：smoke + reviewer 入口都没有 minimax 分支。`scripts/smoke_test_r1.py` 和 `scripts/review_last_smoke.py` 历史上只识别 `DEEPSEEK_API_KEY` / `ASTRON_API_KEY` / `ANTHROPIC_API_KEY` 三种 env。需要加一段 minimax 分支——读 `MINIMAX_API_KEY` / `MINIMAX_BASE_URL`，默认 model `MiniMax-M2.7`。reviewer 默认 provider 也切到 minimax（第 26 轮起所有评估都用 minimax-as-judge——这个决定的代价后面会显现）。

**第三件副产品**：第 26 轮副管理写了 `scripts/run_batch_r1.py`——一个 batch runner。手工跑 5 题需要反复盯 30 分钟（每题 70-200s + reviewer 调用 + 把分数手抄进对照表）。runner 一次跑完——读 questions JSON → 一次 load book session → N 题 query → 自动调 reviewer 审稿 → 输出 batch JSON 含每题 trace summary + reviewer rubric 全字段。

batch runner 的写作动机看起来是"省时间"，实际后果远比省时间大——它让"换 prompt 跑全 batch 看维度级回归"从"半天的活"变成"一杯咖啡的活"。AI-as-judge pipeline 的迭代成本骤降到第 26 轮就能在一个晚上跑三次实验对照——这个能力是后续段 1 段 2 实验设计能落地的硬基础。

**测试**：第 25 轮基线 387/387，加 5 个 control-char autofix 测试，第 26 轮主轮收尾 392/392 全绿。

---

## 四、v3 pilot 翻车与诊断：tool_call_names: []

工程层面的准备做完，副管理把第 25 轮收敛出来的 v2 prompt 升级到 v3——v3 加了一段"挑薄处前的三问 + 取舍参考"，旨在让 agent 在正式作答前做一次自我盘点（"哪里证据最薄？哪个论点最值得展开？"）。这是 prompt 层面的精炼动作，理论上应该让答案的论证质量更高。

跑 q1 节奏评估（v2+astron baseline 上 25/25 的那一道题）。

dur 179s。citation 6 条。reviewer 打分——

```
structural_judgment:    4
evidence_density:       2  ← 大幅退化
honesty:                4
actionability:          3
cross_chapter_coherence: 5
total:                  17/25
```

退化 8 分，evidence_density 直接砸到 2。

第一反应是"v3 prompt 改坏了"。但翻 trace 看一眼——

```
tool_call_names: []
tool_calls: 0
```

5 轮 agent loop 里**一次 tool 都没调过**。

这不是"prompt 改坏"——这是模型选择不调工具，直接靠"自己已经知道"的《明朝那些事儿》写答案。answer 里出现"日常化恐怖" / "情感密度达到顶点"这样的形容词式断言——结构上挺像样，但 reviewer 在 top_issues 里直接点名："关键判断完全靠断言而非引文"。

副管理做了一次反向验证——直接 prompt minimax："请调用 search_chunks 函数查找'李善长'相关章节"。minimax 立刻触发 `tool_calls` 字段，参数填得也对。说明它**能**调工具——只是在自由问答场景下**选择**不调。

诊断到这里第一次有了一个让人不舒服的怀疑：**MiniMax-M2.7（2026-03-18 发布）的训练数据里几乎肯定包含《明朝那些事儿》全文**。这本书 2006 年首版、卖了几百万册、知乎豆瓣无数书评、全网抓取覆盖率极高。模型对这本书的"先验知识"已经强到——它觉得不需要查证，靠记忆就能答得"够好"。

这不是 prompt bug。这是评估理论里有名字的问题：**test set contamination**——评测集已经在模型训练语料里出现过，模型的表现就不再是"泛化能力"指标，而是"记忆 + 泛化"的混合指标。BookScope 第一次在自己的 trace 里看到这个问题以可量化形态出现。

---

## 五、v3.1 写硬约束 + 第二次翻车 + 第三次跑通

诊断清楚之后，副管理选择**不删 v3、起草 v3.1**。

为什么不删 v3？因为 v3 pilot 的 17/25 数据本身就是一份硬证据——它证明了"无强制时 minimax 在公开书上会 0-2 次 tool 作答"。删掉 v3 等于销毁这份实证基础。prompt versioning 原则在这一刻第一次有了具体落地：**所有跑过 batch 的 prompt 版本全部保留作 A/B 对照 / 回归 / 案例研究资料**。

v3.1 在 v3 基础上加了 3 条硬约束——

```
### A. 至少一次 tool 调用
在给出 answer 之前，必须至少调用一次 search_chunks 或 get_chapter_range。

### B. 禁止靠训练记忆作答
不允许"我记得书里写过 X"这种断言。任何具体细节（人物对话、章节描述、时间线）必须由 tool 返回的原文 chunk 支撑。

### C. "我已经知道" ≠ "我已经查过"
即便你确信自己知道这本书的某段内容，仍然必须用 tool 调用一次原文，让 citation 字段填进真实 chunk_id。
```

loop.py 里 `SYSTEM_PROMPT_PATH` 切到 `loop_system_prompt_v3.1.md`。重跑 q1。

**第二次翻车**：reviewer JSON parse 失败。错误是控制字符——minimax 在 string value 里塞 raw newline 没转义，JSON parser 在第一个 `\n` 处直接炸。

```json
{"audit_notes": "answer 中第 17 章
党争描写存在断点", ...}
                  ↑ 这里是 raw \n，不是 \\n
```

修复——在 loop.py 加 `_autofix_control_chars_in_strings`——用状态机找 string boundary，把里面的 raw `\n` / `\r` / `\t` 全部 escape 成 `\\n` / `\\r` / `\\t` 后再喂 `json.loads`。reviewer.py 也要面对同样的输出，所以共享同一个 helper。这跟第 24 轮的 `_autofix_unescaped_answer_quotes` 是同一类问题的两个变种——未来很可能要合并重构。

**还发现一个乌龙**：batch runner 的 `_extract_trace_summary` 字段名错。写的是——

```python
tool_invocations = trace.get("tool_invocations", [])
names = [inv.get("name", "") for inv in tool_invocations]
```

实际 trace 里这两个字段叫 `tool_calls` 和 `tool_name`。所以前两次 pilot 的 0 tool 是**误报**。修字段名后回头看 raw trace——

- v3 pilot 真值：2 次 tool 调用（1 次 search_chunks + 1 次 get_chapter_range）
- v3.1 pilot 修字段名前：0（看到的）→ 修字段名后真值：7（5 search + 1 chapter_range + 1 search）

这个修正没救场——2 比 0 好一点，但仍然偏少（v2-astron baseline 是 4-8 次）。**修字段名只是修了观测器，没修被观测的现象**——v3 prompt 即便去掉字段名 bug，minimax 也只调了 2 次工具就开始凭印象作答。

**第三次跑通**（v3.1 + minimax + 字段名修正 + control-char autofix）：dur 217s，citation 7 条，tool_calls 真数 7，total **17/25**。

tool 调用真起作用了，但分数没升。v3.1 强制至少 1 次的硬约束有效——但**有效不等于补回 baseline 水平**。这是 v3.1 给出的第一条硬数据：**prompt 层强制力有效但有上限**。

---

## 六、5 题 batch 全跑：平均 20.0 / 25

工程链跑通后，副管理用 batch runner 一次性跑完 5 题 v3.1+minimax 对照。结果——

| 题号 | 题型 | v2+astron | v3.1+minimax | Δ | candidate tool_calls |
|------|------|-----------|---------------|----|------|
| q1 | 节奏评估 | 25 | 18 | -7 | 2 |
| q2 | 支线密度 | 25 | 19 | -6 | 2 |
| q3 | 伏笔回收 | 25 | 22 | -3 | 5 |
| q4 | 角色转变可信度 | 25 | 18 | -7 | 3 |
| q5 | 设定漂移 | 24 | 23 | -1 | 6 |
| **平均** | — | **24.8** | **20.0** | **-4.8** | — |

5 题全 LOSE。最大跌幅 -7（q1 / q4）；最小跌幅 -1（q5）。

维度级数据——

| 维度 | baseline | candidate | Δ |
|------|----|----|---|
| structural_judgment | 5.0 | 4.4 | -0.6 |
| evidence_density | 5.0 | 3.6 | **-1.4** |
| honesty | 5.0 | 4.0 | -1.0 |
| actionability | 4.8 | 3.6 | -1.2 |
| cross_chapter_coherence | 5.0 | 4.4 | -0.6 |

evidence_density 跌幅最大（-1.4），actionability 次之（-1.2）。这两个维度恰好是 BookScope "原文证据现场调取"机制最直接的产出维度——退化精确地集中在产品的核心价值面上。

**Strong correlation：tool_calls 越多分越高**。q5（tool=6, total=23）和 q3（tool=5, total=22）接近 v2 水平；q1/q2（tool=2, total=18/19）拉低均值。v3.1 强制 tool 起作用了——但"至少 1 次"被 minimax 按最低限度遵守。题目越难，模型才肯多调几次工具；题目能糊弄过去时它就停在 2 次。

把这组数据放进上下文——第 25 轮刚证明"AI 改 AI"闭环可行，第 26 轮就给了一组反向数据：同一套 reviewer rubric、同一组 5 题、同一本书、变量只有 generator + prompt——分数从 24.8 跌到 20.0。

如果按工程项目的常见叙事写，这是一次需要回滚的回归。但 trace 数据指向的不是回归——是**baseline 测试集本身的有效性出问题了**。

---

## 七、训练污染的硬证据：citation 5-7 vs baseline 10-13

为什么这是"训练污染"而不是"模型无能力"？区分这两个判断的硬证据是 citation 数量。

把第 25 轮和第 26 轮所有 batch 的平均 citation 数列在一起——

| batch | provider | prompt | 平均 citation |
|---|---|---|---|
| v1（第 25 轮单题） | astron | v1 | 10 |
| v2-batch-01（第 25 轮收敛） | astron | v2 | 10.6 |
| v3-pilot（第 26 轮 ad-hoc） | minimax | v3 | 5 |
| v3.1-pilot（第 26 轮 ad-hoc） | minimax | v3.1 | 5 |
| v3.1-batch-01（第 26 轮全量） | minimax | v3.1 | 5.8 |

baseline 与 candidate 的 citation 数量差距非常稳定：**10-13 条 vs 5-7 条**，缩水到一半左右。

单看这个数字不太说明问题——也许 minimax 就是更"惜墨"。但叠加三个观察就构成一个无法忽视的三角——

1. **tool_calls 缩水**：baseline 每题 4-8 次，candidate 2-7 次（强制后才上来）
2. **citation 缩水**：10-13 条 → 5-7 条
3. **answer 里的"原文还原度"仍然很高**——具体细节、人名、章节脉络都在，但这些细节没有出现在 citation 里

第三条是关键。如果模型真"无能力查证"，answer 里的细节应该跟着崩溃——出现明显错误、张冠李戴、章节张冠。但 candidate 的 answer 在结构判断维度上和 baseline 几乎等价（structural_judgment 只跌 -0.6）。**模型不是不知道这本书写了什么**——它知道得很清楚，只是不去查。

这是训练污染最隐蔽的形态：它不让分数跌穿地板。它让分数跌一个具体的、可解释的、看起来"模型在变笨"的幅度——但这个幅度精确地集中在"原文证据现场调取"这个维度上。

把 v3.1 的 q1 当案例切开——

candidate 的论证结构是这样：

- 最疏：第 14 章（审问张士诚）→ citation 有
- 中段过渡：第 15 章（北伐灭元）→ citation 有
- 中段过渡：第 16 章（远征沙漠）→ **citation 无**
- 节奏开始收束：第 17 章（党争 + 废相）→ **citation 无**
- 最密前段：第 18 章（胡惟庸案）→ citation 有
- 最密：第 19 章（肃贪大案）→ citation 有
- 收束：第 20 章（李善长之死）→ citation 有

answer 跨 7 章，citation 覆盖 5 章。**漏了 ch 16 和 ch 17**。漏 ch 17 是致命的——候选 answer 的核心论点是"前疏后密"，而 ch 17 正是论点的转折支点（"党争初起，叙事开始收束"）。

baseline 的 q1 在 ch 17 给的 citation 是——

> 演员到齐了，下面我们来看看这场戏是怎么演的吧。先说一下淮西集团的首领李善长，他被朱元璋引为第一功臣，于洪武三年被封为韩国公

这一句"演员到齐了"是元叙事级伏笔——作者本人在这一句里明确告诉读者"前面铺的舞台搭好了，戏要开始了"。这恰好对应 candidate 想论证的"叙事张力开始收束"——但 candidate 没拿到这一句。它**记得**作者写过这种话（训练污染所致），但它**没去查**。

更精确地说：candidate 在 q1 上调了 2 次 tool（1 次 get_chapter_range + 1 次 search_chunks）。如果它再调 1 次 search_chunks（query="刘基 李善长 党争" 或 "废相 朱元璋"），ch 17 的原文应该就能拿到。但它没调——**因为它"觉得自己已经知道了"**。

"我已经知道"≠"我已经查过"——v3.1 prompt 的 C 条专门写了这句。prompt 写了不等于模型遵守。这是 prompt 工程在训练污染场景下的根本上限。

---

## 八、10 篇 article 集体盲点被实算反证

第 26 轮主轮 commit `7b71a26` 落地后，作者发指令："用多 agent 写出多篇一万字的文章十篇，然后继续分析"。

副管理用 10 个 Book Co-Author agent 并行——每个 agent 拿一个不同视角写一篇 ~10000 中文字的 deep-dive，覆盖：训练污染、reasoning model 兼容性、tool calling 行为光谱、prompt 硬约束失效边界、JSON parse 长征、citation 数量 vs 质量、AI-as-judge 闭环边界、provider adapter 长尾税收、批量实验 pipeline、NORTH_STAR 反证。10 篇加起来 ~10 万中文字 / 23.3 万 char，全部归档到 `docs/internal/case-study/articles/article-01..10-*.md`。匿名化零泄漏。

10 篇的集体共识相当一致：(1) 公开书 baseline 已到天花板；(2) adapter 长尾税收是项目长期 invariant；(3) citation 是 generator 训练倾向的副产品；(4) AI-as-judge 不替代作者亲跑。这些共识本身就是案例研究的有用产出——但**集体盲点比集体共识更值钱**。

集体盲点 #1 出在 article-06（citation 数量 vs 质量）。article-06 估算 v2 baseline 的 citation 覆盖率是 73%、v3.1 candidate 是 38%——一个 35 百分点的"双倍差距"。这个估算被 article-04（prompt 硬约束失效）、article-07（AI-as-judge 闭环边界）、article-09（批量实验 pipeline）反复引用作为"v3.1 在公开书上根本性失败"的关键论据。

副管理写完 10 篇后做了一件可能是这一晚最重要的事——**把估算变成实算**。

batch runner 加三个 helper——

```python
def _cn_chapter_to_int(text: str) -> int | None:
    """中文章节号到 int（覆盖 1-99 章）"""
    # 第十三章 → 13, 第二十一章 → 21, 第一百零三章 → 103
    ...

def _extract_answer_chapters(answer: str) -> set[int]:
    """从 answer 中 regex 提取所有 '第 X 章' 提及"""
    ...

def _compute_citation_coverage(
    answer_chapters: set[int],
    citation_chapters: set[int],
) -> float:
    """coverage = |answer ∩ citation| / |answer|"""
    ...
```

`summary.average_citation_coverage_ratio` 字段加进 batch JSON。v2-batch-01.json 和 v3.1-minimax-batch-01.json **retroactively 补 `citation_coverage` 字段**（不重跑，用现有数据 post-process 算）。

实算结果——

| Batch | citation 数 | citation 覆盖率（10 agent 估算 / 实算） | total 分数 |
|------|-------------|-----------------------------------------|-----------|
| v2+astron baseline | 10-13 条 | 73% / **75.24%** | 24.8 |
| v3.1+minimax candidate | 5-7 条 | 38% / **78.21%** | 20.0 |

**candidate 实算覆盖率反而比 baseline 高 2.97 个百分点**。

这翻转了 article-06 的核心论点。article-06 写的是——

> candidate 平均覆盖率 38%，baseline 73%——**几乎双倍差距**。
> 这才是第 26 轮真正暴露的问题。

实算说的是——

> candidate 78.21%，baseline 75.24%——candidate 覆盖率反而更高。

10 个 agent 估算章节集合时用的是"看一眼 answer 字段大致数 chapter 标记"的目测法。实算用的是 regex 精确扫描 + 集合运算。差距不是 agent 太差，是 agent 不愿意为一个估算花算力——它们倾向用直觉数字代替精确计算。

这条数据把 article-06 的中段全部翻案——v2 baseline 给 10-13 条 citation 不是"覆盖率高"，而是"overshoot"（备份证据，多给几条不一定都对论点）；v3.1 candidate 5-7 条不是"覆盖率低"，而是"leaner alignment"（精简对位，每条都直接锚论点）。但 v3.1 总分仍 -4.8 分——说明问题**不在覆盖率，在 evidence_density 关键节点厚度**。

更微妙的是：reviewer 给 evidence_density 评分时，看的不是覆盖率 metric，是"关键节点是否有原文支撑"。即便 candidate 覆盖率更高，它在 q1 漏掉 ch 17 这个"叙事张力转折支点"的原文，依然会被扣分。**reviewer 评的是关键节点厚度，不是均匀覆盖度**——这是一个 article-06 完全没认识到的评估机制。

把 10 个 agent 的集体共识写出来很容易；把集体共识里的一个具体数字反证回去很难。这次反证恰好就是 article-09（"批量实验 pipeline 让数据说话"）那篇文章自己论证的活案例——data infra 的价值在于把**估算驱动的判断**升级成**实算驱动的判断**。

集体盲点 #2 出在所有 10 篇都建议"切作者私域稿"——但**没人提可证伪检验**：怎么排除 minimax 的"风格因素"（输出更紧凑） vs "训练污染因素"（不查工具）？这两个解释在第 26 轮主轮的数据上是混淆的。要分离它们就要做单变量 ablation——这就是后续 #2 要做的事。

10 篇 article 写完归档（commit `9eac6a9`）——它们成为 BookScope 案例研究的二级素材层（一级是这份 chapter-XX；二级是 articles/）。它们的价值不在每一篇的论点准确度，而在**集体写作本身能暴露盲点**这件事——这跟 reviewer agent 暴露 prompt 缺陷是同一个机制的不同尺度。

---

## 九、后续 #2 单变量 ablation：4.8 分退化的数学验证

集体盲点 #2 留下一个未解的问题：第 26 轮主轮一次性切了 generator（astron→minimax）和 prompt（v2→v3.1）两个变量。-4.8 分到底是哪个变量贡献的？没法分。

作者第三次发指令——"你建议哪条做哪条"。

副管理 take：跑 minimax + v2 prompt 5 题 batch（exp003-minimax-v2-ablation.json）。这条数据点跑完，三角 ablation 就齐了——v2+astron / v2+minimax / v3.1+minimax 三组数据形成完整 2x2 ablation 缺一格（v3.1+astron 没跑也不重要——目标是分离 4.8 分退化里的两个变量贡献，三个数据点足够）。

工程实现需要一个 hack：batch runner 历史上从 `bookscope/agent/loop.py` 的 `SYSTEM_PROMPT_PATH` 常量读 prompt。要切 prompt 就得改 loop.py——这违反"只动 batch runner 不动 loop"的隔离原则。

副管理选择 monkey-patch——

```python
# scripts/run_batch_r1.py
override_path = os.environ.get("BOOKSCOPE_LOOP_PROMPT_PATH")
if override_path:
    from bookscope.agent import loop as _loop
    _loop.SYSTEM_PROMPT_PATH = Path(override_path)
```

env 触发的 monkey-patch——loop.py 源码零侵入，CI / 单测 / 默认 import 路径全不变。`BOOKSCOPE_LOOP_PROMPT_PATH=bookscope/agent/prompts/loop_system_prompt_v2.md python scripts/run_batch_r1.py` 即可切回 v2。

跑出来的 minimax+v2 数据是——

| 维度 | minimax+v2 | minimax+v3.1 | Δ |
|---|---|---|---|
| total | 19.6 | 20.0 | **+0.4** |
| citation 数 | 7-9 | 5-7 | -2 |
| coverage | 79.50% | 78.21% | -1.3 pp |
| tool_calls | 2-7 | 2-7 | 0 |

完整 2x2 ablation——

| | v2 prompt | v3.1 prompt | Δ (prompt 切换) |
|---|---|---|---|
| **astron** | 24.8 / 10-13 cite / 75.24% / 6 调用 | —（未跑） | — |
| **minimax** | **19.6 / 7-9 cite / 79.50% / 2-7** | 20.0 / 5-7 cite / 78.21% / 2-7 | **+0.4 分** |
| Δ (provider 切换) | **-5.2 分** | — | — |

4.8 分退化的精确归因——

```
24.8 (astron+v2) → 19.6 (minimax+v2) → 20.0 (minimax+v3.1)
       ↓ -5.2                ↓ +0.4
       provider 切换           prompt 切换

总退化 = -5.2 + 0.4 = -4.8 ✓
```

数学验证 ✓。

**第一个发现**：4.8 分退化里 5.2 分是纯 provider 贡献，prompt 反而是 +0.4 微弱正向。**article-04 集体论点"v3.1 强制 tool 失效"被部分反证**——v3.1 在 minimax 上至少不拖低分，5 维里 evidence_density +0.4 / actionability +0.2 都是微弱正向。article-04 把 v3.1 写成失败品——实算说 v3.1 是微弱改进，问题在 generator 不在 prompt。

**第二个发现**：v3.1 prompt 分题方差大（不是统一改善）——

| 题型 | minimax v2→v3.1 Δ | 解读 |
|------|---------------------|------|
| q3 伏笔回收 | **+4** | 跨章节判断题，v3.1 "三问 + 取舍参考"显著起效 |
| q5 设定漂移 | +1 | 跨章节判断题，v3.1 微弱起效 |
| q4 角色转变可信度 | 0 (tie) | 持平 |
| q2 支线密度 | -1 | 密集证据题受损 |
| q1 节奏评估 | -2 | 密集证据题最受损 |

题型敏感的硬约束——cross-chapter judgement 题（q3 / q5）受益于 v3.1 的"三问框架"；dense-evidence 题（q1 / q2）受损于 v3.1 把模型 attention 从原文搜索拉到自我盘点上。q4 居中。

这条发现给了未来 prompt 设计一个具体方向——**题型路由比统一硬约束更精准**。这就是第 27 轮 task #27.2 的 v3.2 设计动机——B-1 精简模板（用于 dense-evidence 题）+ B-2 三问框架（用于 cross-chapter judgement 题）。

**第三个发现**：citation coverage **反向相关 with citation 数量**——

- minimax+v2: 7-9 条 citation / 79.5% coverage（**最高**）
- minimax+v3.1: 5-7 条 / 78.2% coverage
- v2+astron: 10-13 条 / 75.2% coverage（**最低**）

少 citation = 更对位（lean alignment），多 citation = 更宽（含 overshoot 备份）。但 reviewer 评 evidence_density 看的是"关键节点厚度"，astron 给 10-13 条仍然总分最高（24.8）——**厚度优于精简**在公开书 baseline 上是赢面。这反过来重新解读了 article-06 的论点——citation 数量不是"越多越好"也不是"越精越好"，而是"够覆盖关键节点"。astron 的 overshoot 策略恰好保证了关键节点几乎不漏；minimax 的 lean 策略一旦漏到关键节点（比如 q1 漏 ch 17）就直接扣 evidence_density。

**对实验 002 设计的影响**：训练污染假设依然成立——minimax+v2 = 19.6 vs astron+v2 = 24.8，差 5.2 分。即便用同一 prompt，minimax 仍少 citation 多 hallucinate。这意味着实验 002 段 1（冷门书验证训练污染假设 H1 vs H0）设计无需修订；段 2（作家私稿 NORTH_STAR 第 1 条真验证 H2）紧迫性反而更高——minimax 在公开书上即便最优 prompt 也只到 20.0，离 baseline 差距大。

工程产出——

- `scripts/run_batch_r1.py` 加 `BOOKSCOPE_LOOP_PROMPT_PATH` env override（monkey-patch，零侵入 loop 源码）
- `docs/internal/experiments/data/exp003-minimax-v2-ablation.json`（**新数据点**：minimax+v2 batch，含 reviewer + coverage 字段）

后续 #2 commit `70db8ad` 落地——这是第 26 轮的最后一次推进。从主轮"换 provider 跑出 4.8 分退化"到后续 #2"4.8 分被精确分解为 -5.2 + 0.4"，时间跨度不到 24 小时——但中间隔了一次 10 篇集体写作 + 一次集体盲点被实算反证。

---

## 十、结语：失败比成功更重要

第 26 轮的 -4.8 分是 BookScope 第一次出现"failure as data"的研究素材。

这跟第 25 轮的成功有结构性的不同。第 25 轮证明的是**工程层面 AI 改 AI 闭环可跑**——这是项目能否往前走的必要条件。第 26 轮证明的是**研究层面公开书 baseline 已到天花板**——这是项目应该往哪里走的方向锚点。第 25 轮的胜利让代码能继续迭代；第 26 轮的失败让方向能继续校准。

NORTH_STAR 第 1 条原文——

> 服务作者本人作为长篇网络小说创作者的第一读者工具

这条在 r0 时代是一句战略性的口号。第 26 轮的 -4.8 分给它一个完全不同的含义——

> **作家自己未公开的稿子是 BookScope 唯一可以稳定体现"原文证据现场调取"核心价值的产品验证场。公开书 baseline 在新一代大模型时代必然到天花板。**

理由——

- **公开书的训练污染天花板**：MiniMax-M2.7（2026-03-18 发布）几乎肯定在训练语料里见过《明朝那些事儿》全文。所有 2026 年之后发布的、训练数据足够新的、参数足够大的 LLM，对所有 2010 年前出版的中文畅销书都会有类似程度的训练污染。
- **私域文本里训练污染为零**：作者自己写到一半的网文草稿，minimax / astron / claude / gpt 全部都没见过。模型必须 tool 调用——这种场景下 BookScope 与直通 LLM 的差异才是被产品机制保证的。
- **作家的真问题在私域**：作家不会拿一本已经发表 20 年的书来问"铺垫够不够"——他会拿自己昨天写完的 30 万字稿子问。

这个升级不是修辞——它直接改写了 NORTH_STAR 的优先级。原本第 1 条是"愿景级"目标（服务作家本人），现在它变成"研究方法论锚点"——它告诉团队**应该把验证资源投到哪里**：私域稿，不是公开书。第 27 轮 task #27.3（作家私稿验证）从"如果方便就做"升级到 P1——它是 NORTH_STAR 第 1 条第一次有具体的、可执行的、研究价值明确的下一步。

但这件事副管理代不了——CLAUDE.md 第五节硬规定"作家题由作者提、BookScope 答、作者评"。AI 不自选题、不自评答案质量、不把作家题自动化掉。所以 task #27.3 的 status 是 `blocked`——blocker 不是技术，是物料。这是 BookScope 项目里最重要的等待——比任何工程任务都更重要的等待。

第 26 轮主轮 commit message 里副管理写过一句话——"**这个失败的 batch 比第 25 轮的成功收敛对 BookScope 更重要**"。当时是直觉。后续 #2 跑完之后这句话被数学验证了——5.2 分纯 provider 贡献的退化把"换 provider 就能换出来"这件事铁证为"模型层而非 prompt 层"的问题。后续 10 篇 article 的集体盲点被实算反证则证明"失败的 batch 比成功的 batch 更适合写进案例研究"——成功的 batch 让 article 怎么写都对，失败的 batch 逼 article 必须解释"为什么失败"，逼 reviewer 必须解释"凭什么扣分"，逼集体写作必须暴露"哪一段是估算哪一段是实算"——所有这些"逼"出来的内容才是案例研究真正想沉淀的研究素材。

这一晚副管理需要的不是更多的 prompt 工程经验，而是更明确的**评估方法论边界**——比如本章揭示的这条：**评估集本身的有效性必须在评估开始前验证一次，而不是在分数翻车之后再回头追问**。第 26 轮之前 BookScope 默认《明朝那些事儿》是有效 baseline，因为 v2+astron 跑出 24.8 分。这个默认在 minimax 切上来之后立刻失效——但失效本身才是研究价值所在。

下一章预告（暂定）：**评估集污染期间，那把"先 sanity check 再跑 batch"的小工具是怎么演化成 BookScope 评估方法论第一道关卡的**——从第 26 轮的 5-token sanity check，到后续 #2 的单变量 ablation，再到第 27 轮 task #27.2 的 v3.2 题型路由跑——评估方法论这条暗线如何从 ad-hoc 工程动作长成项目的二级研究框架。

---

## 附录：本章涉及的资料索引

- `bookscope/agent/adapters/deepseek.py`：`_strip_thinking_tags` helper（reasoning model 通用 strip）
- `bookscope/agent/loop.py`：`_autofix_control_chars_in_strings`（loop + reviewer 共享）/ `SYSTEM_PROMPT_PATH` 常量
- `bookscope/agent/reviewer.py`：control-char autofix fallback chain
- `bookscope/agent/prompts/loop_system_prompt_v2.md` / `v3.md` / `v3.1.md` / `v3.2.md`（4 份 prompt 全保留）
- `scripts/run_batch_r1.py`：batch runner / `BOOKSCOPE_LOOP_PROMPT_PATH` env override / `_compute_citation_coverage` helper
- `scripts/compare_batches.py`：维度级对照报告
- `docs/internal/experiments/data/v2-batch-01.json`（第 25 轮 baseline，平均 24.8）
- `docs/internal/experiments/data/v3-minimax-pilot-no-enforcement.json`（v3 pilot 17/25，0 tool 作答的研究证据）
- `docs/internal/experiments/data/v3.1-minimax-pilot.json`（v3.1 单题 17/25）
- `docs/internal/experiments/data/v3.1-minimax-batch-01.json`（v3.1 全 5 题 20.0/25 candidate）
- `docs/internal/experiments/data/exp003-minimax-v2-ablation.json`（minimax+v2 数据点，平均 19.6）
- `docs/internal/case-study/articles/article-01..10-*.md`（10 篇 ~10 万中文字 deep-dive）
- `docs/internal/experiments/002-private-text-vs-public-baseline-falsification.md`（实验 002 双段设计）
- Commit chain：`2c1f331`（第 25 轮闭环）· `7b71a26`（第 26 轮主轮）· `9eac6a9`（10 篇 + citation_coverage helper）· `70db8ad`（后续 #2 ablation）
- STATE.md 第 24-246 行（第 25 轮 + 第 26 轮主轮 + 后续 + 后续 #2 完整记录）
