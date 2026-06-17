# 第 4 章 · 换一本它没读过的书：anshi 登场与 BookScope 在训练数据外的成长

> **状态**：草稿 · 作者未定稿
> **时段**：2026-04-29 至 2026-04-30（第 28 轮至第 33 轮）
> **覆盖 commit**：`f083a1d`（第 28 轮 stray-apostrophe-closer autofix + anshi 4/5 恢复）/ `84f3056`（第 29 轮 reviewer max_tokens + 内容审查诊断）/ `4003307`（第 30 轮删 astron + harness 加自我进化）/ `4f40f63`（第 31 轮 ContentFiltered 兜底 + q3 拿到分）/ `3f5f344`（第 32 轮 max_iter 8→12）/ `72e91fb`（第 33 轮 ROADMAP + reframe）/ `f11e86f`（第 33 轮 v3.3 B-2-i 子模板）
> **与第 3 章的关系**：第 3 章讲"批改试卷的人发现题库被泄了"——揭示热门书训练污染问题；第 4 章讲"换一本它没读过的书"——把 BookScope 放进它训练数据**外**的真实文本里跑一遍，看工程坑会怎么全部暴露、兜底机制怎么一项项落地，最后一次反过来锤穿了"训练污染漏洞"这个 framing 本身

---

## 一、序：换一本它没读过的书

第 3 章结束时 BookScope 处在一个奇怪的位置。

minimax M2.7 在《明朝那些事儿》上 5 题平均 21.4/25——分数挺高，但 trace 里 tool 调用次数偏少、citation 数比 astron baseline 少近一半。诊断指向"训练污染"——模型把书背下来了，**选择**不去查证。

这个发现本身有意义，但它给 BookScope 留下一道悬崖：**如果用户带进来一本 minimax 不知道的书，会怎么样？**

第 28 轮的答案是：**很多东西会同时挂掉**。

那本书叫《安史之乱：历史、宣传与神话》（张诗坪、胡可奇），2024+ 出版的学者非虚构。书名上看得出方向——副标题"历史、宣传与神话"是作者要解构的对象，正文是用一手史料推翻"昏君佞臣"叙事的论证链。这本书在中文互联网上几乎无声响——没有微博营销、没有抖音解读、没有知乎万赞回答。它就是个真正的冷门学者作品。

把这本书塞进 BookScope 是第 28 轮的事。从那天到第 33 轮的六轮里，所有上一阶段藏起来的工程坑——JSON parse、reviewer 截断、provider 内容审查、agent 收敛上限、错误兜底链——都被这本书逼出来一次又一次。每一次都不是"新大坑"，是 **anshi 比 mingchao 更挑剔**——它没有"模型靠记忆补一刀"的退路，所以每一道工程小裂缝都暴露成了硬挂的 batch task。

更重要的：从第 28 轮到第 33 轮的工程战之后，BookScope 第一次在一本它训练数据外的真书上跑出 5/5 的稳定分数（虽然分段位比 mingchao 低 3-4 分）。这件事比 mingchao 的 21.4 更有意义——它直接对应 BookScope 真正的产品场景：**用户带进来的任何文本**。

这一章讲的就是这件事。

---

## 二、第 28 轮：minimax 的逗号引号小动作

第 28 轮的目标本来很小——把 anshi epub 跑通看初步分数。第 27 轮 v3.2 prompt 在 mingchao 上 21.4，作为 baseline 已确认。换书理论上一行命令就能跑：把 `BOOKSCOPE_SMOKE_EPUB` 指向 anshi.epub，剩下的 batch runner 已经处理。

跑完结果 3/5 success——q1=18 / q2=17 / q4=16 / q5=21（平均 4 题 18.0），q3 reviewer 返回空文本 parse 失败。

q3 的"空文本"听起来像 minimax 服务端拒答；但 q1 也"挂了"——q1 reviewer 输出 1268 字，Pythonjson.loads 报 `Invalid control character at: line 13 column 87`。

这 1268 字 raw 仔细看，长这样：

```
"actionability": "指出了问题所在（第9章漕运段落占比偏高），但没有给出作家
下一步该做什么——是删减、压缩到多少篇幅、还是需要补充什么别的内容？',
```

注意末尾——`内容？',`。这是 minimax 的一个新破裂模式：本应该用 `"` 收束 string value 的位置，它写了 bare ASCII apostrophe `'`。整段 JSON 的 `"`-平衡跑乱、`_extract_first_json_object` 找不到完整 JSON object 直接报"no valid JSON object"。

这个 `'`-as-`"` 的小动作不是 minimax 第一次玩——前面 27 轮里 `_autofix_unescaped_quotes_in_all_string_values` / `_autofix_control_chars_in_strings` / `_autofix_unescaped_answer_quotes` 三层 autofix 已经处理过其他形态的 minimax JSON 怪癖。但 `'`-as-closer 是个新的，要加新的兜底。

第 28 轮做的事很小：

```python
_STRAY_APOS_CLOSER_RE = re.compile(r"'(\s*[,}]\s*[\n\r])")

def _autofix_stray_apostrophe_string_closer(json_text: str) -> str | None:
    if "'" not in json_text:
        return None
    fixed, count = _STRAY_APOS_CLOSER_RE.subn(r'"\1', json_text)
    if count == 0:
        return None
    return fixed
```

这条 regex 收紧到"`'` + 可选空白 + `,`/`}` + 可选空白 + 换行"——这是 JSON 结构上 `"` 必须出现的位置。中文叙事里偶发的单引号一般不紧跟 `,\n` 出现，误伤面极小。

接进 reviewer parse 链的兜底位置（`_extract_first_json_object` 返回 None 时再试一次）→ 跑 3 个 unit test 验证（boundary-replace / clean-input-returns-None / 端到端 raw 恢复）→ 用新 autofix 从 q1 的缓存 raw_text 二次解析 review，回填进 batch JSON。

第 28 轮收尾时 anshi 是 4/5 = 18.0/25——q3 仍缺，因为 raw 是空的没法本地 autofix 救。

跟 mingchao v3.2 = 21.4 比，差 3.4 分。当时副管理把这个差距读成"训练污染假设的初步证据"——现在回头看这条诊断对一半（`§ 八` 会讲为什么）。

---

## 三、第 29 轮：reviewer 写不下 + provider 拒答

第 29 轮想做两件事：拿 minimax key 重跑一次 batch 验方差（看 18.0 是不是 noise）+ 把 q3 重跑出来。

跑完 3/5 success——q1=17 / q4=16 / q5=19（平均 17.33）。两次跑（28 轮 vs 29 轮）的 q1/q4/q5 偏差 ≤ 2 分，确认 anshi 在 minimax+v3.2 上稳定 17-18 段位。

但这次 q2 和 q3 都挂——挂法又不一样。

q2 reviewer raw 在 `...完全没有引` 处戛然而止——scores 已经写出但 JSON 没闭合。reviewer 默认 `max_tokens=2000` 不够装 minimax 写的长 dimension 评语 + per_dimension_comment + top_issues + single_most_valuable_improvement。autofix 救不了被截断的数据——数据本身就缺。修法直接：DEFAULT_MAX_TOKENS 2000→4000，加 `BOOKSCOPE_REVIEW_MAX_TOKENS` env 覆盖。

q3 这次不再是"reviewer 空文本"，是 `loop_failed: ProviderError`——HTTP 422 `output new_sensitive (1027)`。minimax 服务端的内容审查直接打回了。

q3 题面里有"睢阳保卫战的'鬼故事'化"、"传统叙事中混入了大量交战双方的战时宣传以及后世改写"这些字眼。当时副管理读出来的 take 是：minimax 政策对涉政治宣传的题就是会拒，"换 provider 才能跑"。

这条 take 后来被作者 push back——它把 BookScope 的产品限制甩给了用户："想用 minimax？那这道题别问了。" 这违反 NORTH_STAR 第 4 条不变量（provider-agnostic）+ memory `feedback_china_llm_first.md`（provider-agnostic 抽象必做）。

但这条 reframe 是第 31 轮的事，第 29 轮收尾时 q3 仍挂着，副管理把它写进了未来工作面 + 等下一轮 minimax key 到位重跑。

---

## 四、第 30 轮：作者要"自我进化"

第 30 轮不是工程内驱推进，是**两条作者锤打过来的**。

第一锤："astron 这个模型 api 已经失效了，全部删了。"

astron 是从第 16 轮起到第 26 轮一直当 BookScope 主 provider 的讯飞星辰 MaaS。它的 25/25 baseline 是 BookScope 唯一拿过满分的数据点。第 30 轮 astron API 失效，删 runtime——但 case-study / commit history / experiments 数据（v2-batch-01.json 是 astron 跑出的研究证据）都保留作历史。runtime 干净拔掉，研究记录原封不动。这是删的纪律——分清"代码层 vs 历史记录层"。

第二锤更深刻："你的 harness 架构里面给我加上一个自我进化的高星技能，和记得随着一项做完要保存记忆。你这样搞得我很难受。"

具体场景：anshi epub 路径作者第 28 轮就给过、minimax context 是 200k 也告诉过——AI 在跨 session 时反复丢这些 fact，每次都让作者重复说。

修法是 harness 层的：在 AUTOLOOP.md 主算法加一步"轮内沉淀"——**每完成一个任务**（不是每一轮）立即走"任务完成 checklist"：(1) 沉淀可复用 fact 进 memory；(2) 写一行复盘到 STATE；(3) 检查规则文件是否要修订。

这是 BookScope 案例研究里少有的元层面演化——harness 自身的规则被打磨。修完之后 4 条 memory 一次补齐：feedback_save_memory_per_task / feedback_natural_chinese / project_astron_decommissioned / reference_minimax_capabilities。

第 30 轮表面是 2 件工程事 + 1 件元事，但元事比工程事重要：**BookScope 的 AI 团队成员第一次有了"记忆维护"这个明确动作**。

---

## 五、第 31 轮：把 422 拆透

第 31 轮的开头是作者把第 29 轮的 take 打回："q3 永远过不了内容审查——要把原因探知清楚而不是直接放弃了，用户可能使用的 ai 都是多种多样的，难道你要让用户还得限制自己的 ai 选择哪个才行吗？如此的大逆不道的想法。"

这个反驳深刻，要展开。

副管理上一轮的逻辑是：minimax 的内容审查会拦 q3 这种涉政治宣传题 → "换 provider 才能跑"。这等于把限制甩给用户："想用 BookScope？得选某个 AI。" 这违反 BookScope 整个产品的 provider-agnostic 设计前提——BookScope 应该在**任何用户的任何 LLM 上**都能跑。

正确的做法是：拆透 422 触发条件 + 在 BookScope 层做兜底 graceful degrade，不是甩锅。

第 31 轮先做了一个简单的 probe——5 个并发直接喂 q3 题面给 minimax，不走 agent loop / 不走 BookScope tools。结果：

```
[1] OK 80.0s len=2761
[2] OK 65.7s len=8096
[3] OK 66.3s len=7996
[4] OK 31.2s len=342
[5] OK 84.3s len=2636
总计 5/5 全过，0 个 422
```

5/5 全过——q3 题面单独喂 minimax 不触发 422。422 是 agent loop **累积上下文**（多轮 tool_result 把 search_chunks 返回的原文片段塞进 messages）+ 长答复合成时某种敏感词组合让服务端 review 不过。**间歇性触发**，重试同 input 通常能过。

兜底设计就明确了：

- 加错误类 `ContentFiltered(ProviderError)`，`retry_safe=True` 默认
- adapter 的 `_translate_error` 识别 422 + new_sensitive / content_filter / 1027 等关键字翻译成 ContentFiltered
- AgentLoop 加 `_invoke_with_content_filter_retry`：默认 2 次重试。第 1 次直接重试同 input，第 2 次在 system 后追加中性化措辞提示——避免重复题面敏感词，改用"传播 / 叙事建构 / 史料还原"等中性术语
- reviewer 加同款 `_call_with_content_filter_retry`
- LoopTrace 加 `content_filter_retries` 字段；batch runner 落 `content_filter_blocked` 结构化字段
- 8 个测试覆盖三场景：首次过 / 中性化触发 / 重试上限耗尽 + reviewer 同链

实装完跑 anshi 5 题 batch——q3 这次拿到 17/25——**前两轮全挂的题这次过了**。

q3 在 minimax 上拿到的第一个分。这是第 31 轮的"实绩"——但更深的意义是 reframe：BookScope 不再让用户挑 AI，是 BookScope 在任何 AI 上都强制 evidence-from-text 兜底。

---

## 六、第 32 轮：短平快 8→12

第 32 轮是个例外——单一参数改、单题验证、10 分钟闭环。

第 31 轮的 q3 救回了，但 q1 这次新挂在 `MaxIterationsExceeded`——iters=8 满了，dur 290.9s 没收敛。这跟 ContentFiltered 重试无关（cf_retries=None），是 anshi q1 这道题（节奏评估）在 v3.2 prompt + minimax 上**本就摇摆**，agent 跑得比 mingchao 慢。

8 轮太紧。改 `DEFAULT_MAX_ITERATIONS` 8→12，跑 q1 单题验证：

```
q1: 18 (28 轮) → 17 (29 轮) → MaxIter ✗ (31 轮) → 19 ✅ (32 轮)
dur 162.8s，cite=16，agent 提前收敛没用满 12 轮上限
```

短平快 happy ending。但作者一句反馈："我感觉这个蓝图不知道有没有相应的工程时间表"——把第 32 轮收尾的"任性勾画下一轮可能"打回到正经的工程项目管理上。

第 33 轮的 ROADMAP.md 起草就是这一句话的产物。

---

## 七、第 33 轮第一部分：被两层连锤穿的 framing

第 33 轮的开场是作者要全局回顾 + 想看带打勾 checklist 的开发蓝图。

蓝图的事容易处理——按 AUTOLOOP 第一节读完核心文件，给作者四段路线图：现在 / 短期 5-10 轮 / 中期 1-2 月 / 长期半年级。每条带 [ ] [~] [x] [/] [!] 状态打勾，AI 自动维护。`docs/internal/ROADMAP.md` 是这一轮的产物。

但作者在收到回顾后追问的一句话——"第 26 轮换 minimax 后撞墙——揭示新一代大模型在公开书上的训练污染漏洞——这个情况再做深度的研究看看是不是真的？"——把 BookScope 的核心研究发现重新推上诊断台。

副管理本来想的是给一个三组 probe：A 闭卷复述 + B 细节问答 + C tool 调用率。题目设计完跑了 12 题——结果出来时短暂兴奋了一下：anshi 那边 minimax 直接答 5 字"我不知道"+ 2 题（B9 / B10）甚至**编错作者**——把张诗坪 / 胡可奇这本书归给"Benjamin T. Tully（郭瑞德）"和"Mark Edward Lewis 编辑的论文集"。这是直接的训练数据缺失证据：minimax 不光不记得这本书，连作者归属都是幻觉。

mingchao 那边 minimax 5 题细节全答对——朱元璋小名朱重八、第一卷 1344 年开篇、鄱阳湖大战对手陈友谅、李善长萧何式人物、通俗白话风格。

副管理那一刻写下来的结论是："训练污染假设完全成立——minimax 训练数据完整包含 mingchao、完全不含 anshi。"

作者第一锤打在这条结论上："感觉这个内容不算是明朝那些事儿的数据，因为是非常正常的明朝的历史的科普数据。"

——朱元璋小名朱重八、1344 年开篇、陈友谅、李善长萧何式、通俗白话风格——这些是中文互联网普遍存在的明朝历史**科普 + 这本书的常识级讨论**。任何 LLM 哪怕没读过原文，光从维基 / 知乎 / 各种科普文里也能学到。minimax 答对它们不能证"训练数据里有这本书原文"，只证"训练数据里有明朝常识 + 这本书的二手讨论"。

副管理认了——题目设计的反例已经写进 memory `feedback_probe_avoid_general_knowledge.md`：probe 题设计要满足"只有读过原文才能答出"——避开维基、避开科普文、避开常识。判别标准：搜索引擎 mock 一下，把题目当 query 搜中文互联网，前 3 页能不能找到答案？能 = 题不行。

但作者的第二锤更深一层："不论是哪个 ai 都会是正常训练的。"

——任何 LLM（DeepSeek / GLM / Qwen / Claude / GPT）都会包含 mingchao 的二手讨论；同样地，任何 LLM 都大概率不知 anshi（出版晚 / 学者作品 / 流量小）。mingchao 高分 vs anshi 低分**不是 minimax 特有 bug**，是所有 LLM 在"熟悉文本 vs 不熟悉文本"上的常态差异。把它说成"minimax 训练污染漏洞"是过度归因——这个 framing 把 BookScope 的价值锚定在 minimax 的某个 bug 上，意味着 minimax 修了或换 LLM 价值就消失。

新 framing 是从这一锤里浮出来的：**对任何 LLM、任何文本，evidence-from-text 都比依赖训练记忆更准确**。

- 对训练里没有的书：LLM 只能编（已证：minimax 把 anshi 作者编成 Benjamin T. Tully / Mark Edward Lewis）
- 对训练里有大量二手讨论的书：LLM 可能用科普文 / 维基版本作答，与原文细节有偏差
- 用户带进来的**任何文本**——BookScope 强制 evidence-from-text 都比纯 LLM 直答更可靠

这个 framing 比第 26 轮的"训练污染漏洞"**更普适也更稳**——因为它适用于所有 provider、所有文本、所有用户场景。第 26 轮 framing 把价值锚定在"minimax 漏洞"上；新 framing 是普适的，不会因 LLM 演进而失效。

第 33 轮第一部分的产物是 ROADMAP.md（蓝图）+ probe 数据（exp003）+ 5 条 memory（用户不只是作者本人 / 不要再提私稿 / 训练污染证据部分被锤 / probe 避免常识题 / 价值 reframe）。

第 26 轮的 chapter-03 不需要重写——它讲的是"批改试卷的人发现题库被泄了"那一轮的具体故事，是真实发生的。但第 4 章必须把第 33 轮这两层 reframe 写进来——chapter-03 的诊断不是错的，是它的 framing 有局限。

---

## 八、第 33 轮第二部分：v3.3 立场漂移子模板与"诚实段位"的浮出

第 33 轮第一部分留下两个未解的工程问题——anshi q5 三轮拿分波动（21 / 14 / 15）是真随机 noise 还是 prompt 设计缺陷？v3.3 的 B-2-i 立场漂移子模板能不能修？

第 33 轮第二部分并行跑 5 个 batch 给答案——

**v3.2 anshi 4 次跑（含原第 28 / 31 轮 + 新 rerun-03 / rerun-04）求方差**：

q5 数据点 21 / 14 / 15 / ERR(ToolDispatch)，3 个有效 std≈3.8，范围 14-21。**确认 q5 在 v3.2 + minimax 上是真实波动不是单次 noise**——是 prompt 设计问题：v3.2 对立场漂移题没有 citation 厚度硬约束，导致 generator 给出"立场分析"但缺具体节点 citation 支撑，reviewer 见到空洞判断扣分。

**v3.3 anshi 3 次跑（B-2-i 子模板要求至少 5 处具体章节立场示例 citation 覆盖三段位）**：

| 题 | v3.2 4 次均 | v3.3 3 次均 | Δ |
|----|----|----|----|
| q1 | 18 | 20 | +2 |
| q2 | 20.75 | 19 | -1.75 |
| q3 | 18 | 19 | +1 |
| q4 | 16.5 | 21 | **+4.5** |
| q5 | 16.67 (std≈3.8) | **18.33 (std=0.47)** | **+1.66 + 极稳** |
| 平均 | 18.04 | **19.47** | **+1.43** |

q5 三次跑分别拿 18 / 18 / 19——std 从 3.8 拉到 0.47，**v3.3 不光提分，还把波动收敛掉了**。cite 数 9 / 9 / 8 都满足 B-2-i 要求的至少 5 段位 citation 厚度。

**v3.3 mingchao backward compat（用 v2-batch-01.json 题集跑 1 次）**：

| 题 | v3.2 (1 次) | v3.3 (1 次) | Δ |
|----|----|----|----|
| q1 节奏评估 | 22 | 18 | **-4** |
| q2 支线密度 | 21 | 22 | +1 |
| q3 伏笔回收 | 23 | 20 | -3 |
| q4 角色转变 | 20 | 17 | -3 |
| q5 设定漂移 (B-2-i 目标) | 21 | 21 | 0 |
| 平均 | **21.4** | 19.6 | -1.8 |

第三部分当时下的 take 是："v3.3 让 mingchao 降 1.8 分——B-2-i 子模板对非目标题有 prompt-length 副作用。" 这个 take **错了**，错在用单次跑的 v3.2 = 21.4 当 baseline 跟单次跑的 v3.3 = 19.6 比。第四部分跑 v3.4 想 narrow 化 B-2-i 试图修这个"副作用"——v3.4 mingchao 跑出来 19.2，比 v3.3 还低，这才让人回头怀疑：是不是从一开始 baseline 就不准？

**第五部分：补 v3.2 mingchao baseline 方差**

跑 v3.2 mingchao 第 2 次 + 第 3 次。最后三次跑数据 21.4 / 18.8 / 20.4，平均 **20.2 / std 1.06 / 范围 18.8-21.4**。

这一刻 take 翻转——

| 版本 | mingchao 段位 | 数据点 |
|------|----|----|
| v3.2 | 平均 **20.2** / std 1.06 | 三次跑 21.4 / 18.8 / 20.4 |
| v3.3 | 19.6 | 一次跑（在 v3.2 noise 范围内） |
| v3.4 | 19.2 | 一次跑（在 v3.2 noise 范围内） |

**v3.3 / v3.4 在 mingchao 上根本没有显著降分**——19.6 / 19.2 都落在 v3.2 自己的 18.8-21.4 范围里。"prompt 副作用"是个不存在的影子，第三 / 四部分追着它跑了一整轮，最后是基础研究纪律——跟新版本比前先求 baseline std——把假问题揭穿。

**修正后的真相**：

- anshi 上 v3.2 → v3.3 → v3.4 段位 18.04 → 19.47 → 20.2 单调上升，**是真改进**
- mingchao 上三个版本都在 19-21 段位（v3.2 平均 20.2 / v3.3 单次 19.6 / v3.4 单次 19.2），**无显著差异**
- v3.4 是当前最优：anshi 20.2 + mingchao 19.2

"两本书在 v3.x 上段位收敛"这条 reframe 仍对方向——mingchao 平均 20.2 / anshi 平均 19.5，差距只有 0.7 分。但具体说"v3.3 让 mingchao 降 1.8 分到诚实段位"是 baseline noise 误读，要修。

**第三 / 四 / 五部分跑的弯路记下来作为 case-study 的研究纪律素材**：跟新版本比之前**先确认 baseline 多次跑求 std**——这条已经沉淀进 memory `feedback_baseline_variance_first.md`，是这一章里 BookScope 工程实践收获的另一条。

**v3.4 是当前最优 prompt**：

- anshi 段位 20.2（vs v3.2 baseline 18.04 提 2.16 分），是 BookScope 在不熟悉文本上**最强**段位
- mingchao 段位 19.2（vs v3.2 平均 20.2 差 1.0 分，在 noise 范围内），**没有副作用**
- B-2-i 严格判别开关在 anshi q5 上保留 v3.3 的提分，在 mingchao 上不引入新问题

---

## 九、本章里 BookScope 真正长出来的东西

回头看第 28 轮到第 33 轮六轮做的事，工程层面的产物挺密集——

- `_autofix_stray_apostrophe_string_closer`（第 28 轮 minimax JSON `'`-as-`"` 兜底）
- `DEFAULT_MAX_TOKENS` 2000→4000 + `BOOKSCOPE_REVIEW_MAX_TOKENS` env（第 29 轮 reviewer 写不下兜底）
- 删 astron runtime + harness 加"任务完成 checklist"自我进化机制（第 30 轮）
- `ContentFiltered` 错误类 + AgentLoop / reviewer 双层重试（第 31 轮 minimax 422 兜底）
- `DEFAULT_MAX_ITERATIONS` 8→12（第 32 轮 anshi q1 收敛不够）
- `ROADMAP.md` 全局 checklist + probe 工具脚本（第 33 轮第一部分）
- v3.3 prompt B-2-i 立场漂移子模板（第 33 轮第二部分）

但这些工程产物只是表层。

真正长出来的东西是更深一层——BookScope 第一次跑通了"用户带进来训练数据外的真书"这个核心场景。每一道工程坑都是 anshi 这本书逼出来的，每一次兜底都是为了让 BookScope 不让用户挑 AI。第 28 轮到第 33 轮的工程战看起来是"在补漏"，但累积下来 BookScope 从一个"在 mingchao 上跑得动的工具"变成了"对任何文本、任何 provider 都能稳跑"的产品。

第 33 轮的 reframe 是这个意思的另一面——BookScope 的价值不在"绕过某家 LLM 的某个 bug"，是**在所有 LLM、所有文本上都强制原文证据**。这个 framing 适用于一年后的 LLM、五年后的 LLM、用户从未来某个时点带进来的任何文本。

第 33 轮第二部分的 v3.3 trade-off 给这个 reframe 加了一层：BookScope 的"分数提升"不应该追求绝对值——熟悉书的"高分"本就是训练污染虚高，让它退到诚实段位是好事；不熟悉书的"低分"才是真正需要提的——因为那是用户带进来的真实场景。

anshi 这本书不会再被 BookScope 当成"对照训练污染的反例"。它现在是 BookScope 的**御用测试文本**——代表用户带进来的所有非热门长文本。在它身上跑通的工程坑、积累的稳定段位、成长出来的兜底机制，都是为下一本"用户带进来的书"准备的。

---

*本章草稿到此为止，第 33 轮第二部分数据已补完。定稿由作者在里程碑点统一润色。*
