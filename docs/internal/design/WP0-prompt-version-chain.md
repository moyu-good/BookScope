# WP0 设计稿 · prompt 版本链修复

**日期**：2026-06-10
**状态**：✅ 已过闸（作者 2026-06-10 批"开始"）· 已实现 · 第 4 步对照通过

**实现 vs 设计 vs 目的对照**（design-first 第 4 步）：方案五条全部落地，与设计零偏离；成功标准 4 条全验证——①哨兵断言 v3.5 ✓ ②trace + batch/probe 元数据带 prompt_version ✓ ③override 测试在 r2 加载层生效 ✓ ④789 测试全绿 + ruff 全绿 ✓。计划外发现一处：上一轮改 search_chunks 骨架时旧测试未同步（test_search_chunks_skeleton_raises_not_implemented 期望已删除的 NotImplementedError），本轮顺手改为委托断言——教训：改行为必须当轮跑全套，不能只跑 ruff。
**上游**：`docs/internal/design/2026-06-10-design-gap-review.md` P0 发现 + 缺口 12

---

## 目的

让"跑的是哪个 prompt"从口头约定变成被系统记录、被测试守护的事实——终结生产冻结 v3.1、override 失效、实验数据无版本归属的三连断裂。

**受益者**：作者（产品终于用上三轮实验验证过的 prompt 改进）；之后所有 batch / probe 实验（数据有版本归属，对照实验结论可信）；case-study（数据可信度是发表的底线）。

**成功标准**（可检验）：
1. 单测断言生产默认加载 v3.5
2. 任意一次 query 的 `LoopTrace` 带 `prompt_version` 字段，batch 输出 JSON 元数据含该字段
3. 设 `BOOKSCOPE_LOOP_PROMPT_PATH` 跑 mock 题，trace 显示 override 的版本（机制在 r2 下真生效）
4. 全套 780 测试零回归 + ruff 全绿

## 方法论锚

1. **对照实验 + 基线方差纪律**（本人沉淀，第 33 轮验证）——测量仪器先于实验：版本不是实验变量的注脚，是必须先固定的仪器读数。
2. **钱学森控制论**——无观测不控制：prompt 版本是三个月未被观测的系统状态；修复 = 先建观测（trace 字段 + 单测哨兵），再动状态（切 v3.5），且可逆（env override 保留、历史数据不改写只补勘误）。

## 方案概要

1. **单一事实源**：`loop_shared.py` 新增 `CURRENT_PROMPT_VERSION = "v3.5"`，`SYSTEM_PROMPT_PATH` 由版本号拼出——改版本只动这一个常量
2. **override 内建**：`load_system_prompt()` 内读 `BOOKSCOPE_LOOP_PROMPT_PATH`（每次实例化生效）；`run_batch_r1.py:335-348` 的 patch 已删除模块的死代码整块删掉，改为校验文件存在 + 打印确认；probe 脚本撒谎的 docstring 修正
3. **trace 可观测**：`LoopTrace` 加 `prompt_version: str` 字段（从实际加载路径的文件名解析，override 也如实反映）；`loop_r2.AgentLoop` 构造时填入；batch / probe 输出 JSON 元数据写入该字段
4. **测试哨兵**：新增 `tests/agent/r2/test_prompt_version.py`——默认版本断言 / override 生效断言 / trace 字段断言
5. **历史勘误**：`docs/internal/experiments/006-*.md` 第九节后补一段"数据勘误：4 组 quality probe 实跑 v3.1 非 v3.4"——历史 JSON 不篡改，勘误明文补记

## 影响范围

- `bookscope/agent/_internal/loop_shared.py`（常量 + load 函数）
- `bookscope/agent/models.py`（LoopTrace 加一个向后兼容字段）
- `bookscope/agent/loop_r2.py`（构造时填 prompt_version，~3 行）
- `scripts/run_batch_r1.py`（删死代码块 + 元数据写入）、`scripts/probe_kg_cache_quality.py`（docstring 修正 + 元数据写入）
- `tests/agent/r2/test_prompt_version.py`（新增）
- `docs/internal/experiments/006-*.md`（勘误段）
- **副作用确认**：L2 LLM 缓存 key 含 system prompt 哈希——切 v3.5 自动 miss 旧缓存，无脏缓存风险；LoopTrace 是 Pydantic 模型加默认值字段，API 响应向后兼容

## 不做什么

- **不改任何 prompt 文件内容**——v3.5 里"上限 8 次"与代码 12 的数字打架归 WP5（那是 prompt 内容设计，会产生 v3.6，需要走 PE + batch 验证）
- 不给 fast_path 路径加版本（fast_path 用独立子模板，作家诊断题都走 agent_loop；需要时 WP5 一起做）
- 不回溯篡改历史 batch JSON（只补勘误文档）
- 不动 reviewer / citation prompt 的加载逻辑

## 验证方法

- `pytest tests/agent/r2/test_prompt_version.py` 新测试全过
- `pytest` 全套零回归（baseline 780）
- `ruff check` 改动文件全绿
- mock 跑一条题断言 trace JSON 里 `prompt_version == "v3.5"`（不花 LLM cost）

---

## 第 3 步审查记录（以目的为抓手逐项过）

| 设计要素 | 服务哪个目的 | 锚的透镜 |
|---|---|---|
| 单一事实源常量 | 成功标准 1——"改版本只动一处"消灭冻结复发条件 | 控制论：把分散状态收敛为可控变量 ✓ |
| override 内建到 load | 成功标准 3——实验机制在 r2 下真生效 | 可逆性：随时切回任意版本 ✓ |
| trace 字段 | 成功标准 2——版本成为记录的事实 | 无观测不控制 ✓；测量仪器先于实验 ✓ |
| 测试哨兵 | 成功标准 1/3 的持续守护——重构搬家不再静默冻结 | 控制论：观测自动化 ✓ |
| exp006 勘误 | 受益者 case-study——数据可信度 | 基线方差纪律：错标的 baseline 必须显式纠正 ✓ |
| 砍掉的：prompt 数字统一 | 与目的无直接支撑（属 prompt 内容设计）→ 移 WP5 | 外科手术式改动 ✓ |

**审查结论**：六要素全部挂到目的，无装饰项。一个取舍提请作者注意——**切 v3.5 意味着产品行为变化**（答题风格会变：题型路由 + citation 厚度 + 并发查证），这正是目的本身，但 6/12 起 Sprint 3 batch 的数据将与 5 月所有数据不可直接比（版本不同）。这是修复的必然代价，不是风险。

**估时**：0.5 agent 天。批准后 BE+QA 并发执行。
