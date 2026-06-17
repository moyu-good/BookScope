# WP5 设计稿 · loop 收敛（空转检测 + 预算规则 + prompt v3.6）

**日期**：2026-06-10
**状态**：✅ 空转检测 + 强制综合已落地（commit `8481d9a`，2026-06-11）· prompt v3.6 已交付未切生产（等 anshi 对照）

**实现 vs 设计对照**：空转检测（成功标准①）+ 剩时强制综合（②）落地，880 测试含 5 个 WP5 测试全绿。BE 代理搭好脚手架后失联、空转逻辑未接 + 零测试，主 Claude 接管补完。**对照判定（2026-06-11，pro + rubric_v2）**：anshi v3.5 vs v3.6 各 2 run（预热省 KG 调用 + 并行）。结果 **v3.6 退步、不切**——v3.5 mean 24.07（std 0.46），v3.6 mean 22.68（std 0.11），差 1.39 > 2×max(std)=0.92，超 noise 显著退步。生产保持 v3.5。reviewer 版本一致性已核验：4 batch 全 rubric_v2（对照有效）。v3.6 的预算指引段疑似挤占了密集证据题的 token 预算（与第 26 轮 v3.1→v3.2 同类副作用），具体留 article-12 母题。空转检测/强制综合（运行时机制，不依赖 prompt 版本）已生效，不受本判定影响。
**上游**：缺口 9（设计缺口评审）；对标 Anthropic 多代理文章"预算规则进 prompt"+ smolagents planning_interval

## 目的

循环不收敛目前只有"傻跑到 180 秒超时"一条出路（anshi q1 历史固有不稳）；prompt 还在用错误的预算数字误导模型（说 8 次，代码是 12）。本 WP 给循环装两层自救 + 把预算口径统一。

**成功标准**：① 空转 mock 场景（连续相同 search）触发 nudge 且 trace 留痕；② 剩余时间 < 阈值时触发强制综合而非硬切；③ v3.6 prompt 数字与代码常量一致性有哨兵测试；④ anshi v3.5 vs v3.6 各 3 run 对照，均分差在 noise 内（run 间 std 基准 0.31）则切生产指针；⑤ 全套零回归。

## 方法论锚

1. **对照实验 + 基线方差纪律**（本人沉淀）——v3.6 不白切：先 3+3 对照，差异落在已知 noise 内才动生产指针。
2. **控制论（闭环自救优于开环硬切）**——超时硬切是开环；剩时预算触发强制综合是把"时间"变成反馈量。

## 方案概要

1. **空转检测**（loop_r2）：记录每轮 search_chunks 的 (normalized query, top-3 chunk_ids)；连续 2 轮与历史某轮重叠度 ≥ 0.8 → 向 messages 注入一条 user 提示"检索已重复，请基于已有证据综合作答"，每 query 至多注入 1 次；`LoopTrace` 加 `spin_nudges: int`
2. **剩时强制综合**：每轮开始检查剩余时间，< 30 秒（常量留调）且尚未注入过 → 注入"时间预算将尽，立即给出 final answer"，trace 加 `forced_synthesis: bool`；注入后仍超时则按原超时路径走（partial_evidence 已有）
3. **prompt v3.6**（PE 起草）：基于 v3.5 全文，仅三处改动——预算数字 8→12 修正；新增"预算指引"段（事实/通识题 3-6 次 tool 调用、诊断题 8-12 次，引 Anthropic 多代理文章的预算分级思路）；新增一句与空转 nudge 呼应（"系统提示检索重复时立即转入综合"）。其余原样保留
4. **一致性哨兵**：单测断言 v3.6 文本里的预算上限数字 == `DEFAULT_MAX_ITERATIONS`
5. **对照后切指针**：QA 跑 anshi v3.5/v3.6 各 3 run（env override 跑 v3.6，生产指针先不动）；判定过线后 `CURRENT_PROMPT_VERSION` 切 v3.6 + 哨兵测试同步

## 影响范围

`loop_r2.py` / `models.py`（trace 两字段）/ `prompts/loop_system_prompt_v3.6.md`（新）/ `loop_shared.py`（常量 + 指针）/ 新测试 / batch 数据 6 份

## 不做什么

- 不做 smolagents 式周期性 planning step（注入式 nudge 先验证，重机制等数据）
- 不改 v3.5 及更早 prompt 文件（版本不可变纪律）
- 空转判定不用 LLM（纯字符串/集合重叠，零成本零延迟）

## 验证方法

mock 空转 / 剩时触发单测；一致性哨兵；anshi 3+3 对照数据；全套回归 + ruff。

## 自审

nudge 一次上限（防 prompt 污染滚雪球）✓ 服务目的①；对照实验先于切指针 ✓ 锚 1；强制综合复用 partial_evidence 兜底 ✓ 简洁；砍掉 planning step ✓ 外科手术。
