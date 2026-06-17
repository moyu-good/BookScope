# WP1 设计稿 · citation 可信链（含 WP5a partial_evidence）

**日期**：2026-06-10
**状态**：✅ 已落地（commit `5f3b716`，2026-06-10）· 第 4 步对照通过

**实现 vs 设计 vs 目的对照**：方案五条全部落地；成功标准 6/6 验证（编造 snippet 标 false 不拒答 / auto_filled 可见 / partial_evidence 进 ErrorEvent+异常+API 504 / verified 率进 batch summary / 825 测试全绿）。偏离两处均有理由记录：旧测试 citations 全等断言按新契约更新（契约变更的必然）；fast_path 清洗循环丢附加字段顺修（auto_filled 可见的必要前提）。
**上游**：`docs/internal/design/2026-06-10-design-gap-review.md` 缺口 1/2/3/8

---

## 目的

把"没有原文证据的结论一律不输出"从 prompt 约定升级成系统保证的第一步：**每条 citation 由系统比对原文后标注 verified，编造的引用无处藏身**；顺带还掉作者第 35 轮锤过的债——超时失败时把已查到的证据带回去（partial_evidence）。

**受益者**：用户（看到的引用是机器核验过的，不是 LLM 自称的）；exp-001b（"引用真实率"指标从此有测量装置）；case-study（核心主张有了机制背书）。

**成功标准**（可检验）：
1. 正常答题后每条 citation 带 `verified` / `match_score` / `chunk_id`（系统填充，LLM 输出格式零改动）
2. 喂一条编造 snippet 的 mock 回复，citation 被标 `verified=false`，答案不被拒绝（首版只观测不执法）
3. fast_path 自动拼的 citation 带 `auto_filled=true`，不再伪装成 LLM 引用
4. mock 触发 LoopTimeout / MaxIterations 时，`ErrorEvent.partial_evidence` 非空，API 错误响应携带
5. batch 汇总新增 verified 率统计
6. 全套测试零回归 + 新增测试覆盖上述各条

## 方法论锚

1. **钱学森控制论（观测先于执法）**——首版只标注不拒绝：先把 verified 率变成可观测量，拿到真实分布数据后再决定 enforcement 策略，不在无数据时设惩罚阈值。
2. **Karpathy 简洁原则**——校验用纯标准库（归一化 + 子串 + 字符 3-gram），不引入新依赖、不动 prompt（LlamaIndex 编号模式里"要求 LLM 输出编号"那半边推迟到 v3.6，系统侧匹配先行）。

## 方案概要

### 1. 证据登记表（EvidenceRegistry，WP1/WP5a 共享）

`loop_r2.AgentLoop.query` 内每次 query 建一个登记表：`dict[chunk_id, {"chapter": int, "text": str}]`。
- `search_chunks` 返回的每条 `ChunkMatch`（chunk_id / chapter / text）登记
- `get_chapter_range` 返回的章节文本按 `"chapter-{N}"` 伪 id 登记
- 只活在 query 作用域内，不进 trace（trace 仍只存 summary，避免膨胀）

### 2. citation 校验层（新模块 `bookscope/agent/citation_check.py`）

`parse_final_answer` 成功后、组装 `AgentQueryResult` 前跑：

```
归一化（去空白、统一全半角标点）
→ 精确子串命中任一登记 chunk → verified=true, score=1.0, chunk_id=命中者
→ 否则字符 3-gram containment 对全部登记 chunk 求最大值
   ≥ 0.6 → verified=true + 命中 chunk_id；< 0.6 → verified=false
```

citation dict 附加字段：`chunk_id: str|None` / `verified: bool` / `match_score: float`（保留两位）。**不删除、不重试、不改 answer**——首版纯观测。

### 3. fast_path 诚实标注

`fast_path.py:405-415` 自动拼 citation 处加 `auto_filled: true`；同样过校验层（文本来自 fallback chunk，verified 自然为 true，但 auto_filled 明示"系统定位，非 LLM 论点对应"）。不改 retry / 回退逻辑（latency 优先）。

### 4. partial_evidence 填充（WP5a）

LoopTimeout / MaxIterationsExceeded 两条路径：从登记表取前 5 条 `{chunk_id, chapter, snippet（截 200 字）}` 填进 `ErrorEvent.partial_evidence` 与异常对象；检查 `api/routes/agent.py` 的 504/500 翻译是否把它带进错误响应（FE ErrorBanner 第 35 轮已有渲染约定），缺则补最小接线。

### 5. batch 汇总

`run_batch_r1.py` 的 summary 加 `citation_verified_rate`（verified 条数 / 总条数）——"引用真实率"指标的第一个数据源。

## 影响范围

- 新增 `bookscope/agent/citation_check.py` + `tests/agent/test_citation_check.py`
- `loop_r2.py`（登记表 + 校验调用 + 两处错误路径填 partial_evidence）
- `fast_path.py`（auto_filled + 校验调用）
- citation 数据模型字段附加（向后兼容默认值；具体落点由实现时定位——`api/schemas.py` 或 `agent/models.py`，旧数据反序列化不炸）
- `api/routes/agent.py`（partial_evidence 接线，如缺）
- `scripts/run_batch_r1.py`（verified 率汇总）

## 不做什么

- 不 reject / 不重答 unverified citation（执法策略等观测数据，二期）
- 不改任何 prompt（让 LLM 输出 chunk_id 编号 → v3.6 / WP5 主体）
- 不动 reviewer rubric（faithfulness 拆 claim → WP8）
- 不做 FE 展示弱化（PM/FE 拿到字段后自行排期）
- 阈值 0.6 是工程起点值，进常量留调——不在本版做阈值标定实验

## 验证方法

- 新模块单测：精确命中 / 改写命中（轻度同义改写过 0.6）/ 编造不命中 / 空登记表 / 全半角混排
- loop 集成测：mock 一次带真 snippet 的答题 → verified=true；带编造 snippet → false
- fast_path 测：auto_filled 标记存在
- timeout mock 测：partial_evidence 非空且 ≤ 5 条
- 全套回归 + ruff

---

## 自审记录（第 3 步，以目的为抓手）

| 要素 | 服务哪个目的 | 锚透镜 |
|---|---|---|
| 登记表不进 trace | 校验需要全文、trace 防膨胀——两个目的分开满足 | 简洁 ✓ |
| 只标注不执法 | 成功标准 2——观测先行 | 控制论 ✓ |
| 纯标准库 3-gram | 成功标准 6 零回归风险最小化 | 简洁 ✓ |
| auto_filled | 成功标准 3——系统不再自产 decoration | 诚实降级（项目既有姿态）✓ |
| partial_evidence 同表复用 | 成功标准 4——一个机制还两笔债 | 简洁 ✓ |
| 砍掉：prompt 编号、执法、FE 展示 | 与首版目的（建立观测）无直接支撑 | 外科手术 ✓ |

**估时**：3 agent 天 → 并发压缩为一个执行代理一轮。
