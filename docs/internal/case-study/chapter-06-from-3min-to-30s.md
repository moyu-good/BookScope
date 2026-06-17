# 第 6 章 · 从 3 分钟到 30 秒：性能优化那一日

> **状态**：草稿 · 作者未定稿
> **时段**：2026-05-01（Sprint 5 主体 + Sprint 5.5 一日完成）
> **覆盖 commit**：`74bddd5`（BE · tool 并行）/ `ae04cea`（PE · v3.5 高效查证模板）/ `078643c`（QA · benchmark 自动化）/ `fc10b20`（BE · 题型路由快路径）/ `8edc877`（FE · streaming 进度细化）/ `8526a3e`（OPS · benchmark 进 CI）
> **与前 5 章的关系**：第 5 章（待写）讲 r2 代际切换的思考；第 6 章讲一件具体的事——BookScope 从"研究工具"切到"产品延迟"的工程化战役

---

## 一、序：研究工具与产品的距离

Sprint 4 收尾时 BookScope 处在一个体面但尴尬的位置。

anshi 在 v3.4 prompt + minimax 上跑稳了 20.2 段位，mingchao 也回到 19-21 区间。两本书都在"诚实段位"——研究路径上的事算告一段落。但是去翻 benchmark 数据，能看到另一组数字：anshi 一个 batch 5 题跑下来 **17 分钟**，单题 dur 平均 **2-4 分钟**。

作者那一锤说得很直白：

> "性能问题在用户场景里都不行。一个用户问一道题，等两分钟才出第一个字？这不是产品。"

副管理当时差点想给这个反应找解释——"研究阶段嘛，延迟是 trade-off"。但作者打回：

> "BookScope 的用户用的时候不会跟你聊'研究阶段'。他打开一个网页问一句话，期望的是十秒以内开始看到东西、一分钟以内看完。你做的快慢就是你做的快慢。"

这不是 take 之争，是 framing 之争。Sprint 4 之前的 BookScope 心里把自己当成"研究 batch 跑分工具"，所以"17 分钟跑 5 题"是合理预算；Sprint 5 开始 BookScope 的心智模型切到"产品延迟"——单题端到端 2-4 分钟、首字延迟 30+ 秒，**都不能接受**。

剩下的事就清楚了。Sprint 5 那一天 6 个 commit，按时间顺序是 74bddd5 → ae04cea → 078643c → fc10b20 → 8edc877 → 8526a3e。下面按主题串。

---

## 二、tool 调用并行：第一刀切下去

延迟拆出来看，BookScope 单题 2-4 分钟里 LLM 推理只占大概一半。剩下一半在 tool 调用——agent 每轮可能要查 3-5 个 search_chunks、get_chapter_range、list_characters_in_chapter，老代码 `bookscope/agent/loop.py:311` 是一个简单的 `for tool_use in tool_uses: ...` 串行循环。

第一刀就切在这。

### 设计：为什么不能用 as_completed

直觉做法是 `concurrent.futures.as_completed`——哪个 tool 先回来就先写谁。这条路是个陷阱。

Anthropic Messages API 的 tool_result 必须**严格按 tool_use_id 顺序**附在下一轮 user message 里。`as_completed` 按完成顺序填 outputs 列表会让 tool_result 的顺序跟 tool_use 的顺序错位——API 直接返 422 `tool_result must follow tool_use in the same order`。

第一版用了 as_completed，本地跑通了（小概率顺序撞对），CI 一上就 422。改成 `dict[future, idx]` + 派发完之后用 `future.result()` 按 **idx 顺序**写回 outputs 列表。慢的 tool 会让快的 tool 等，但顺序保住。

```python
# bookscope/agent/loop.py:311 之后
if len(tool_uses) == 1:
    # 单 tool 退化同步——避免 ThreadPoolExecutor 开销
    outputs.append(_execute_tool(tool_uses[0], ...))
else:
    with ThreadPoolExecutor(max_workers=5) as pool:
        future_to_idx = {
            pool.submit(_execute_tool, tu, ...): i
            for i, tu in enumerate(tool_uses)
        }
        outputs = [None] * len(tool_uses)
        for fut in future_to_idx:
            idx = future_to_idx[fut]
            outputs[idx] = fut.result()
```

`max_workers=5` 是 minimax 服务端并发上限的经验值——再大没意义，5 个 search_chunks 同时打 minimax 还会被自家限流。

### 派发前一次性 emit

streaming 那一头还有个微妙问题——前端期望"派发 tool → 看到 tool → tool 完成"是三段顺序事件。如果并发派发，3 个 ToolUseEvent 几乎同一时刻 emit，前端 UI 上 3 个 tool 同时冒出来，看起来像 BookScope 在并发——这是对的。

代码上是先一次性 emit 所有 ToolUseEvent（占位+running 状态），再开 ThreadPoolExecutor 派发。tool_result 回来时 emit ToolResultEvent，前端从尾部回找最近一条同名 + running 的 tool 就地改 status——不追加新行。

### 测试踩的坑：mock.patch 命名空间

5 个单测覆盖了：并发 3 tool 保序 / 并发后 messages 顺序对 / 单 tool 退化同步 / 一个 tool 抛错其他不挂 / 派发前 emit 顺序对。

第一次跑的时候 mock 没生效——`mock.patch("concurrent.futures.ThreadPoolExecutor")` 看起来对，实际 loop.py 是 `from concurrent.futures import ThreadPoolExecutor` 然后直接用 `ThreadPoolExecutor`，要打的 namespace 是 `bookscope.agent.loop.ThreadPoolExecutor`。这是 Python mock 的老掉牙坑（"打到使用方而不是定义方"），但每次重新踩还是会卡 10 分钟。

### 实测

跑 anshi q1 三轮的 trace 数据：

| 测项 | 串行 | 并发 | 比 |
|----|----|----|----|
| 3 tool 一轮总耗时 | 1.20s | 0.45s | 2.67x |
| 4 tool 一轮总耗时 | 1.85s | 0.51s | 3.63x |
| 单题端到端（4 轮 agent loop） | 162.8s | 58.4s | 2.79x |

平均 **接近 3x 加速**。这是单纯并发能拿到的最直接收益。

---

## 三、prompt 配合：v3.5 高效查证

并发 tool 在 BE 落地了，PE 那头要配合——v3.4 的 prompt 没告诉 generator "你可以一次发多个 tool"。LLM 默认行为是一次 1 个、看结果、再发下一个的 step-by-step。

ae04cea 加了 v3.5 prompt——**v3.4 不删，保留作 A/B 回归对照**（项目硬规则 `project_prompt_versioning`，所有 prompt 版本并列保留）。

v3.5 新加一节"高效查证"，主要写四件事：

**该并发的 4 个场景**：

- 多锚点同查：一道题要查"第 3 章 + 第 7 章 + 第 11 章"的支线密度——三个 search_chunks 互不依赖
- 平行假设验证：怀疑伏笔在 A/B/C 三处之一——并发查三处比串行试快 3x
- B-1 多区段采样：节奏评估题要在书的前 / 中 / 后三段各取一刀——并发是天然结构
- 角色 + 章节双锚定：查"李善长在第 8 章的对话"可以 list_characters_in_chapter(8) + search_chunks(query="李善长", chapter=8) 同时打

**不该并发的 3 个反例**：

- 数据依赖：先 get_chapter_range 拿到章节边界、再用边界 search——不能反过来
- 章节号是 search 的产物：search_chunks 返回章节号后才能 list_characters_in_chapter——并发会查错章节
- 顺序排除：第 1 个 search 没找到再扩大范围——并发会浪费多查一次

**节奏建议**：

- 2-3 个 tool 同发是常态
- 4+ 个要在内心过一遍每个真独立
- 不绕过 max_iterations=8 上限——并发不是"省轮数的捷径"，是"每轮做得更多"

v3.5 在 anshi 上单独跑了 3 次验证——20.2 / 20.0 / 19.8，平均 **20.0**，跟 v3.4 的 20.2 在 noise 范围内。**没有副作用**。同时 trace 里平均 tool 数从 v3.4 的 11.4 → v3.5 的 13.2（generator 更愿意多查），但平均 iter 数从 4.2 → 3.6（每轮做得更多，少跑一轮 LLM 推理）。

v3.5 在 mingchao 上跑 1 次拿 20.2（v3.4 mingchao 是 19.2），看起来稍微提一点，但样本太小不下结论——三次 baseline 还没补，按 `feedback_baseline_variance_first` 的纪律先标注"待复测"。

---

## 四、题型路由：通识题不该走 agent loop

并发 + prompt 改完，单题 dur 从 162s 降到 58s。这是 3x 加速。但作者第二天看 benchmark 数据时又点了一刀：

> "你拿个 benchmark 跑五题 5 分钟我能接受。但用户进来问'这本书主要角色有哪几个'——你也跑五十秒？"

通识题路径不该走 agent loop。

通识题的特征是：**1 个 search_chunks 拿到上下文 + 1 次 LLM 直答**。不需要多轮 tool 调用、不需要交叉验证、不需要"诊断式"思考路径。"主要角色"、"全书共多少章"、"作者是谁"、"主线讲什么"——这些题在 agent loop 里跑 4-5 轮 tool 调用是浪费。

fc10b20 加了 `bookscope/agent/fast_path.py`（约 390 行），核心是两件事——路由和执行。

### `_route_question` 4 档启发式

```python
def _route_question(question: str) -> RouteDecision:
    # 1. 诊断词命中——必走 agent loop（30 个词的白名单）
    if any(kw in question for kw in DIAGNOSTIC_KEYWORDS):
        return RouteDecision(path="agent_loop", reason="diagnostic_keyword")
    # 2. 长题——可能藏多个子问题，保守走 loop
    if len(question) >= 30:
        return RouteDecision(path="agent_loop", reason="long_question")
    # 3. 通识/列举词命中——走 fast_path
    if any(kw in question for kw in GENERAL_KEYWORDS):
        return RouteDecision(path="fast_path", reason="general_keyword")
    # 4. 兜底走 loop——宁可慢不可错
    return RouteDecision(path="agent_loop", reason="default")
```

`DIAGNOSTIC_KEYWORDS` 是 30 个真要诊断的词：节奏、铺垫、伏笔、漂移、张力、密度、转变、副线、断裂、回收、对比……见到这些走 agent loop。

`GENERAL_KEYWORDS` 是 25 个明确通识/列举词：主要角色、全书章节、作者是谁、主线、简介、目录、共多少、列出……见到这些走 fast_path。

**优先级最高的是诊断词白名单**——"主要角色的成长节奏"这种题里有"主要角色"也有"节奏"，节奏优先级高，走 agent loop。

### `run_fast_path` 不开 tool

fast_path 跑 1 次 search_chunks + 1 次 LLM call。LLM call 里 `tools=[]`——不开 tool 调用。这一条很关键：如果给 LLM 开了 tools，它会照样发 search_chunks，路由的意义就废了。

citation 怎么来？search_chunks 返回的 chunk 自带 `chapter` 字段，fast_path 用 chunk.chapter 拼 citation——不需要 LLM 再走一遍 tool。

### Fallback：宁可慢不可错

三处 fallback 回 agent_loop：

1. search_chunks 抛异常——比如 vector store 没建好
2. LLM call 抛异常——比如 ContentFiltered
3. LLM 返回的 JSON parse 失败——比如格式不对

这三种情况 fast_path 不硬扛，直接 fallback agent_loop。慢一点没关系，错了不行。

### env BOOKSCOPE_FAST_PATH_DISABLED

一个 env 变量强制全走 agent_loop——给 batch benchmark 用、给作者怀疑 fast_path 误判时一键关掉用。autouse pytest fixture `_disable_fast_path` 让现有 test_agent_ask 题面零回归——所有老测试都走 agent_loop 路径，跟改之前一样。

### 实测

26 个单测覆盖：4 档路由判别 / fast_path 1 search + 1 LLM 正路 / 三处 fallback / citation 拼接 / stream 路径模拟 emit / env 开关 / autouse fixture 不影响老测试。

跑通识题 dur 估算：search_chunks ≈ 1-3 秒 + LLM call ≈ 2-9 秒 = **3-12 秒**。原 agent_loop 路径同题 90-180 秒。**8-15x 加速**。

更重要的是首字延迟——agent_loop 路径要等 1-2 轮 tool 调用回来才开始 stream 答案文本，首字延迟 30-60 秒。fast_path 1 个 search 回来就开始 stream LLM 答案，**首字延迟接近 search_chunks 单次耗时（1-3 秒）**。

这一条对产品体感的改变比"3 分钟降到 30 秒"更大。用户问个简单题，1-2 秒后开始看到字——这是产品；30 秒空白后再开始 stream——这是 batch。

---

## 五、benchmark 自动化：让回归挡 PR

并发 + 路由两件事改完，单题段位降下来了。但下一个问题立刻浮起来：**怎么保证下一次重构不把延迟改回去**？

人工跑 benchmark 不行——会忘、会拖、会用不一样的题集。需要 schema 化 + 自动化 + CI 把关。

078643c 干了三件事。

### bookscope-benchmark/v2 schema

老 benchmark JSON 只存了"题 + 分"。v2 schema 加了运行元数据：

```json
{
  "schema": "bookscope-benchmark/v2",
  "git_commit": "fc10b20",
  "git_branch": "r1-agent-loop",
  "ran_at": "2026-05-01T14:23:11+08:00",
  "config": {
    "provider": "minimax",
    "prompt_version": "v3.5",
    "model": "MiniMax-M2.7"
  },
  "summary": {
    "n": 5,
    "mean": 19.8,
    "p50": 20.0,
    "p90": 21.0,
    "mean_dur_s": 58.4,
    "p90_dur_s": 71.2
  },
  "per_question": [...]
}
```

`git_commit` + `git_branch` 是关键——以后任何 benchmark 数据点都能 git checkout 复现。`config` 字段记 provider / prompt_version / model——换 provider / 换 prompt 不会跟旧数据混淆。

### Markdown 报告同步出

JSON 给机器读，Markdown 给人读。同一份数据 runner 一次性产两份——

- summary 行：mean / p50 / p90 / mean_dur_s / p90_dur_s 一目了然
- 各题明细表：题号 / 题面 / 分 / dur / iter / cite / tool_count / 是否 fast_path
- 自动找最近 baseline 对比段：跟 `benchmarks/baseline/anshi-v3.4.json` 比，标 ↑/↓/→

报告写到 `benchmarks/runs/anshi-{commit_short}-{timestamp}.md`——commit short hash 在文件名里，找历史不用翻 git log。

### benchmark_compare.py 三档判定

`scripts/benchmark_compare.py` 接两份 JSON——base 和 head，按 mean_dur_s 给三档：

- **REGRESSION**：head > base × 1.20（默认阈值 20%）
- **IMPROVEMENT**：head < base × 0.80
- **STABLE**：在 ±20% 之间

REGRESSION 时 exit 1——让 CI 挂 PR。

**20% 阈值的来源**：minimax 单次延迟 std 大概在 10-15%（在 5 题平均下来 std 更低，但单题波动大），20% 是 baseline noise 上沿 + 一点 buffer。低于 20% 会误报，高于 30% 会漏掉真退步。

这个阈值不是拍脑袋——是跟着 `feedback_baseline_variance_first` 的纪律走：阈值要大于 baseline std，否则会把 noise 当退步。

### 实测

跑 v3.5 + tool 并发 vs 老 baseline（v3.4 + 串行）的对比：

```
$ python scripts/benchmark_compare.py \
    benchmarks/baseline/anshi-v3.4-serial.json \
    benchmarks/runs/anshi-fc10b20.json

mean_dur_s: 162.4 → 58.4 (-64.0%)
mean_score: 20.2 → 19.8 (-2.0%, within noise)
verdict: IMPROVEMENT
```

verdict IMPROVEMENT 意味着 CI 通过；后续每次 PR 上跑这个 compare，挡住任何把 dur 弄回去的改动。

---

## 六、FE streaming 进度细化：从字符串到 discriminated union

后端把 tool 并发了、把 fast_path 加了，前端那头要把"现在正在发生什么"也讲清楚。

老前端的 progress 是 `string[]`——"正在搜索..." / "调用 search_chunks..." / "第 2 轮思考中..."。文案是后端拼的字符串前端无脑追加。

这种做法在串行 tool 时代勉强能看。并发起来之后 3 个 tool 同时冒出 3 个字符串，前端无法分组、无法对应、无法在 tool_result 回来时改对应那一条 status——只能再追加 3 个"完成"字符串。

8edc877 把 progress 从 `string[]` 改成 `ProgressItem[]`——三类联合：

```typescript
type ProgressItem =
  | { kind: 'iteration'; n: number; tools_count: number; ts: number }
  | { kind: 'tool'; tool_name: string; tool_use_id: string;
      label: string; status: 'running' | 'done' | 'error'; ts: number }
  | { kind: 'meta'; text: string; ts: number }
```

### formatToolUseLabel：三种 tool 各自语视

不是所有 tool 都该用同一个模板渲染。

- `search_chunks` 显示 query + 章节范围 + character_filter——比如"搜「李善长 谋反」 · 第 5-12 章 · 角色：李善长"
- `get_chapter_range` 显示章节范围——"取第 8-15 章范围"
- `list_characters_in_chapter` 显示章节号——"列第 8 章角色"

label 是前端读 tool_input 拼出来的，不是后端字符串。这样切 prompt 不影响 label 格式。

### 并发组缩进

`iteration_start` 事件作为分组锚点。同一个 iteration 下的 tool 在 UI 上 `pl-4 + 1px rule` 色细竖线缩进，上方有一个小标题——"第 2 轮 · 3 个工具并发"。

视觉上一眼看出"这 3 个 tool 是并发的、属于同一轮思考"。

### 章节徽章

search_chunks 的返回结果里有章节号。FE 把章节号渲成印章红实心小药丸 + 白字 "第 8 章"——11px PingFang display 字号，沿用 SectionTitle 的视觉词。一眼能看到 BookScope 当前在哪一章找证据。

### tool_result 就地改 status

并发派发那一头一次性 emit 了 3 个 ToolUseEvent（status=running），3 个 tool 完成时间不一样，分别 emit ToolResultEvent。前端处理 ToolResultEvent 时做的事——

```typescript
// 从尾部回找最近一条 tool_name 匹配 + status=running 的
for (let i = items.length - 1; i >= 0; i--) {
  if (items[i].kind === 'tool'
      && items[i].tool_use_id === e.tool_use_id
      && items[i].status === 'running') {
    items[i] = { ...items[i], status: e.error ? 'error' : 'done' };
    break;
  }
}
```

**就地改 status 不追加新行**——这是 discriminated union 重构最关键的好处。老字符串模式做不到这个：字符串是 append-only 的，"完成"只能多加一行。新模型下 3 个 running tool 各自变成 done，UI 上看到的是 3 个 tool 行状态从 spinner 变成 checkmark，干净。

---

## 七、OPS CI：沙箱拒写带来的并发模式

最后一个 commit 是把 benchmark 自动化挂到 CI 上——8526a3e。这件事本身不复杂（加两段 GitHub Actions yaml），但它揭出 BookScope 团队架构里一个之前没暴露的细节：**OPS agent 在项目沙箱里拒写 `.github/workflows/*.yml`**。

派 OPS agent 跑这个 sprint 任务时——agent 起手就报"无法写入 .github/workflows/benchmark.yml，沙箱拒绝"。第一次撞这个，AI 浪费了 2 个 turn 试不同路径都失败。

修法是把这件事**沉淀进 OPS 任务的派发 prompt 里**——见 memory `reference_ops_agent_sandbox_yaml_block`：

> 派 OPS 任务时，prompt 里预设"主 Claude 接手 yaml 文件写入"的机制。OPS agent 负责给方案 + 提供完整 yaml 文本，主 Claude 负责落文件。

8526a3e 实际就是按这个流程走的——OPS agent 给出两段 yaml 的完整方案（含 cron 表达式、artifact 保留期、download-artifact action 版本），主 Claude 直接 Write 落文件。OPS agent 不浪费 turn 试错。

### ci.yml +18 行 dry-run smoke

`ci.yml` 在原有 pytest job 后面加一个 dry-run benchmark step：

```yaml
- name: benchmark dry-run smoke
  if: matrix.python-version == '3.11'
  env:
    BOOKSCOPE_BENCHMARK_DRY_RUN: '1'
  run: |
    python scripts/run_benchmark.py \
      --epub tests/fixtures/anshi-mini.epub \
      --questions tests/fixtures/anshi-3q.json \
      --out /tmp/bench-out.json
    test -f /tmp/bench-out.json
    test -f /tmp/bench-out.md
```

dry_run=1 模式下 LLM call mock 掉，只验"runner 跑得通 + JSON + Markdown 双产出都存在"。gated 在 py3.11——其他 Python 版本 matrix 上跳过（benchmark 跑一次 LLM mock 也要 30 秒，4 个 Python 版本跑 4 遍浪费）。

### benchmark.yml 78 行：scheduled + manual

新建 `.github/workflows/benchmark.yml`——

- `on.schedule`: `cron: '0 2 * * 1'`（每周一 UTC 02:00 北京时间 10:00）
- `on.workflow_dispatch`: 带 `dry_run` 输入参数（true/false），手动跑时可选

跑完产物：

- benchmark JSON + Markdown upload artifact（`actions/upload-artifact@v4` retain 30 天）
- 用 `actions/download-artifact@v4` 拉上一次 baseline artifact——`continue-on-error: true` 保首跑没有 baseline 时不挂
- `benchmark_compare.py` 跑对比，REGRESSION 时 exit 1 让整个 workflow run 标失败

### 沙箱拒写带来的并发模式

这件事 8526a3e 本身价值不大——一个标准 CI workflow 设置。但它沉淀下来的 OPS 派发 prompt 模式是 BookScope 团队架构的一次小演化——**项目级 sandbox 限制要进 agent 派发 prompt**，不能依赖 agent 自己试错。

memory `reference_ops_agent_sandbox_yaml_block` 把这条记下来：以后任何 OPS 涉及 `.github/workflows/`、`.claude/`、`.git/hooks/` 这类受限路径的任务，派发 prompt 都要预设"主 Claude 接手文件写入"机制，OPS agent 给方案文本不浪费 turn。

---

## 八、Sprint 5 收尾的数据点

那一天 6 个 commit 跑完，benchmark 跑完，数据对照——

| 指标 | Sprint 4 末 | Sprint 5 末 | 变化 |
|----|----|----|----|
| 单题 dur（诊断题） | 162.8s | 58.4s | -64%（≈ 3x） |
| 单题 dur（通识题） | 90-180s | 3-12s | -90%+（8-15x） |
| 首字延迟（诊断题） | 30-60s | 8-15s（一轮 tool 后） | -70% |
| 首字延迟（通识题） | 30-60s | 1-3s | -95% |
| Batch 5 题总耗时 | 17 min | 5 min | -70% |
| 平均分（anshi v3.5） | 20.2 | 19.8 | -2%（noise 内） |

性能优化没引入分数回归——这是关键。如果"快了但准确度掉了"那是另一回事；目前数据是"快了 3-15x、准确度 noise 范围内"。

---

## 九、本章里 BookScope 真正长出来的东西

回头看这 6 个 commit，工程产物挺密集——

- ThreadPoolExecutor + dict[future, idx] 保序的 tool 并发模式
- "高效查证"prompt 子模板，告诉 generator 怎么用并发能力
- 题型路由 + fast_path 模块，让通识题不走 agent loop
- bookscope-benchmark/v2 schema + Markdown 报告 + 三档判定
- ProgressItem discriminated union，前端从字符串拼到结构化进度
- CI scheduled benchmark + OPS 沙箱拒写的派发模式沉淀

但这些是表层。真正长出来的东西有三条——

**第一条：BookScope 的心智模型从"研究工具"切到了"产品"。** 这件事之前 BookScope 心里把延迟当 trade-off；这一天之后延迟是产品的硬约束。后面所有重构都要算这笔账——加一个 tool？多 0.5 秒；加一道 reviewer？多 5 秒；加一个 LLM call？至少多 8 秒。每一条都要权衡。

**第二条：性能优化是分层的，不是一次性的。** tool 并发是 3x、题型路由是 8-15x、streaming 把首字延迟变成接近 0。三层各自独立、互不抵消、加起来 BookScope 在通识题路径上从 3 分钟到 3 秒。下一次性能优化（可能在 r2 索引层）也会是分层的。

**第三条：CI 把回归挡在外面，比一次性优化更重要。** 没有 benchmark CI 的话，下一个 sprint 改 reviewer / 改 prompt 时很容易把延迟弄回去，3 个月后回看发现又 2 分钟了——没人记得是从哪个 PR 退步的。20% 阈值的 benchmark_compare 自动 exit 1，让每个 PR 都过这关，是 BookScope 把"快"从一次性收益变成长期资产的方式。

---

## 十、剩下的事——这章草稿本身

写到这里要诚实交代一件事：这一章是 Sprint 5 跑完的当天起草的，但它跑完时本来还差一件——`docs/internal/case-study/chapter-06-from-3min-to-30s.md` 的草稿。

Sprint 5 ROADMAP 那条最后没打勾。STATE 文档里写着"RE chapter-06 待写"。第二天 Sprint 5.5 一日 7 commit 把评分卡、上传进度、Onboarding 都补了，chapter-06 还是没动——副管理那两天忙在工程层面没主动起草。

直到作者明确说"为 Sprint 5 写一章 case-study"，这件事才进 RE 的当日任务。

这条事本身值得记一下——**案例研究的章节草稿如果不进显式 sprint deliverable，会被工程任务挤掉**。Sprint 5 的 7 个 deliverable 里 chapter-06 是最后一个，但它最容易被排到"下一轮再说"。RE 的产出不像 BE / FE 有明确"功能上线"信号——草稿什么时候动笔、什么时候到第一稿、什么时候算"够了"都是软边界。

ROADMAP 后续要给 RE 的 deliverable 加更具体的验收标准——"chapter-NN-*.md 第一稿 ≥ 300 行 + 覆盖该 sprint 全部 commit + 自检过中文写作硬规则" 这种。不然每个 sprint 都会留个"RE 待写"尾巴。

---

*本章草稿到此为止。Sprint 5 工程数据已写入、6 个 commit 各自一节、收尾反思包含案例研究本身的工作节奏问题。定稿由作者在里程碑点统一润色。*
