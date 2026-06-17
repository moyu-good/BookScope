# Sprint 7 删 r1 代码 · 影响面 audit

**生成时间**：2026-05-15（第 35 轮第八波 · Sprint 6 完工后启动前 audit）
**作者**：BE agent（read-only）
**目标读者**：作者（需作者签字才能启动 Sprint 7）
**baseline**：663/663 全绿（commit `0f36fb2` 后实测）

---

## 0. TL;DR

- r1 runtime 代码净删约 **2150 行**（loop.py 1528 + deepseek.py 434 + anthropic.py 188，不含测试），代码总量净减 30%+
- **撤回条件不命中** —— reviewer / loop_r2 / fast_path 三处依赖 r1 都可切干净，作者私稿与历史 batch 数据不依赖 r1 runtime（trace 是数据，不是代码）
- **reviewer.py r2 兼容选方案 A** ——把 4 个 `_autofix_*` 函数从 loop.py 抽到 `bookscope/agent/utils/json_parsing.py`，仿 b33e985 的姿态。loop_r2 已经在 docstring 自述"直接 import r1 的 `_autofix_*` 函数复用"——它跟 reviewer 同病相怜
- **执行节奏**：4 步走（utils 抽 autofix → 删 r1 mock 测试 + 父 conftest 锁 → 删 r1 runtime + adapters → 文档同步），每一步独立 commit + 测试零回归
- **关键签字判断点**：autofix 函数从 loop.py 抽公共包这一步**必须先做且 zero-behavior 改动**——这是把 reviewer / loop_r2 / fast_path 跟 loop.py 解耦的咽喉，做完才能动 git rm

---

## 1. r1 代码总量

| 文件 | 行数 | Sprint 7 处置 | 备注 |
|------|------|---------------|------|
| `bookscope/agent/loop.py` | 1528 | **删** | r1 主循环 |
| `bookscope/agent/adapters/deepseek.py` | 434 | **删** | r1 OpenAI→Anthropic 反向翻译 adapter |
| `bookscope/agent/adapters/anthropic.py` | 188 | **删** | r1 near-passthrough Anthropic adapter |
| `bookscope/agent/loop_r2.py` | 1013 | **保留** | r2 主循环 |
| `bookscope/agent/adapters/deepseek_r2.py` | 253 | **保留** | r2 OpenAI 直通 adapter |
| `bookscope/agent/adapters/anthropic_r2.py` | 456 | **保留** | r2 反向（OpenAI→Anthropic）adapter |
| `bookscope/agent/utils/json_parsing.py` | 58 | **保留 + 扩** | b33e985 抽公共；Sprint 7 把 4 个 autofix 也搬过来 |
| `bookscope/agent/utils/response_text.py` | 110 | **保留** | 0f36fb2 抽公共 |
| `bookscope/agent/fast_path.py` | 649 | **保留 + 微调** | 删 L474 的 env 读取（见 §5） |
| `bookscope/agent/reviewer.py` | 327 | **保留 + 改 import** | 改成从 utils 导（见 §4） |
| `bookscope/agent/__init__.py` | 118 | **保留 + 简化** | `_select_agent_loop_class` 退化成直接返回 r2 AgentLoop |
| `bookscope/agent/adapters/__init__.py` | 35 | **保留 + 改 export** | 删 r1 adapter 的 re-export |

**runtime 代码净删**：1528 + 434 + 188 = **2150 行**。

**测试侧 r1-mock 集合**（按文件统计，主测试函数数 = 该文件 collected 总数）：

| 测试文件 | 测试数 | Sprint 7 处置 | 理由 |
|----------|--------|---------------|------|
| `tests/agent/test_agent_loop.py` | 42 | **删** | 全部 mock 走 r1 Anthropic content_blocks 形态；r2 等价测试在 `tests/agent/r2/test_loop_r2.py` |
| `tests/agent/test_adapters.py` | 42 | **保留部分 / 删 r1 部分** | 含 r2 adapter 错误翻译，需筛 r1-only 子集；保守判断按文件结构整体删，r2 部分已在 `tests/agent/r2/test_deepseek_r2.py` / `test_anthropic_r2.py` 等价覆盖 |
| `tests/agent/test_loop_callback.py` | 9 | **删** | r1 mock 桩 |
| `tests/agent/test_loop_context_truncate_retry.py` | 7 | **删** | 测 `_truncate_messages` r1 配对语义；r2 等价测试 `tests/agent/r2/test_loop_r2.py` 已覆盖 `_truncate_messages_r2` |
| `tests/agent/test_loop_default_model.py` | 含在 42 | **删** | `DEFAULT_MODEL` 等常量 r2 重定义，r2 测试套已覆盖 |
| `tests/agent/test_loop_rate_limit_retry.py` | 7 | **删** | 同上 |
| `tests/agent/test_loop_tool_parallel.py` | 含在 42 | **删** | ThreadPoolExecutor 并发，r2 已等价覆盖 |
| `tests/agent/test_r2_skeleton.py` | 含在 42 | **改** | 包含 r1 兜底回滚 case（L51 monkeypatch r1），删掉 r1 case 留 r2 default + 未知值兜底 |
| `tests/agent/test_route_decision_event.py` | 含在 156 总数 | **改** | L369 一处 r1 monkeypatch 删掉 |
| `tests/api/conftest.py` autouse | — | **删** | 不再需要锁 r1 兜底 |
| `tests/api/test_routes_agent.py` 等 22 测试 | — | **删** | 改用 `tests/api/r2/` 下的 r2 mock 套（commit `2d96e90` `e4768ba` `a454f36` 已补齐） |
| `tests/api/test_protocol_routing.py` | 含 | **改** | 删 r1 case，保留 r2 + 未知值兜底 case |

r2 测试套现状（不动）：`tests/agent/r2/` **51 测试** + `tests/api/r2/` **32 测试** = 83 r2 mock 测试，跟即将删的 r1 mock 集合等价覆盖。

---

## 2. r1 引用面 grep 消化

### 2.1 直接 import r1 模块的位置

`bookscope/agent/__init__.py:53`、`adapters/__init__.py:27,29`：把 r1 三模块 re-export 成公共 API。Sprint 7 必须改成只 export r2 等价物（`loop_r2.AgentLoop` 化名 `AgentLoop`、`deepseek_r2.DeepSeekAdapter`、`anthropic_r2.AnthropicAdapter`），保持外部 API surface 不变。

`bookscope/agent/loop_r2.py:69-92`：r2 loop **大量复用** r1 的 13 个常量 / helper / 4 个 autofix（通过 `_R1AgentLoop._parse_final_answer` 调）。这是 Sprint 7 最大的耦合点——直接 git rm loop.py 会让 loop_r2 立刻爆炸。详见 §4。

`bookscope/agent/fast_path.py:38`：fast_path 从 r1 loop 拿 `TOOL_NAME_SEARCH` / `_elapsed_ms` / `_extract_first_json_object` / `_invoke_client` / `_strip_code_fence` 5 个 helper。同样需要先抽公共再删 r1。

`bookscope/agent/reviewer.py:29`：reviewer 从 r1 loop 拿 4 个 `_autofix_*` + `_extract_first_json_object` + `_strip_code_fence`。详见 §4。

`bookscope/agent/adapters/deepseek_r2.py:33` 和 `anthropic_r2.py:44`：r2 adapter 复用 r1 adapter 的内部 helper（`_strip_thinking_tags` 等）。Sprint 7 删 r1 adapter 时必须先把这些 helper 抽到 `adapters/_shared.py` 或类似公共位置，保持 reasoning model 的 `<think>` 块剥能力不丢。

**判断**：所有 runtime 引用都是真 dependency，**必须先抽公共再删 r1**，不能直接 git rm。

### 2.2 `BOOKSCOPE_AGENT_PROTOCOL` env 读取面

实际 runtime 读 env 的只有 3 处：

- `bookscope/agent/__init__.py:76`：`_select_agent_loop_class` 入口判断
- `bookscope/agent/fast_path.py:474`：给 `LoopTrace(protocol_version=...)` 赋值（commit `0f36fb2` 加的）
- `bookscope/agent/loop.py:5`、`adapters/*.py:7` 等：docstring 内引用（注释级别，删 r1 文件时一并清掉）

测试侧读 env 17 处（`monkeypatch.setenv`），属于测试范畴，跟 r1 测试套一起删除。

文档侧 `docs/architecture-decisions/007-r2-openai-function-calling.md:91` / `docs/internal/STATE.md` / chapter-05 等多处引用——历史文档保留不动（"事情做完之后写"姿态，案例研究记录的就是这段切换史）。

**Sprint 7 处置**：删 `_select_agent_loop_class` 的 r1 分支保留 r2 直返；删 `fast_path.py:474` 的 env 读取，直接硬编码 `"r2"`（因为 r1 都没了）。env flag 整个机制 retire。

### 2.3 case-study 引文面

chapter-01 / 03 / 05 / 06 / 08 + articles 01/02/03/05/07/08/09 多达 30+ 处引 `loop.py` / `deepseek.py` / `anthropic.py` 的具体行号或片段。**这些全是历史叙事**——讲第 16 轮加 autofix、第 22 轮翻 prompt 版本、第 26 轮 4 个 autofix 堆 loop.py 这些事情，**保留不动**。

理由：案例研究本身就是讲 r0→r1→r2 演进史，引文记录的是"那个时间点 r1 长什么样"。Sprint 7 之后 r1 代码消失，案例研究里的引文成为"考古记录"——这正是 case-study 第一交付物的价值所在（feedback_case_study_first.md）。

**Sprint 7 处置**：case-study 现有引文一字不改；chapter-05 第八节新写一段"5 个月后的 git rm"补完本章（详见 §6）。

---

## 3. r1 测试套去留判定

### 3.1 父级 autouse 锁 r1

`tests/api/conftest.py:23-31` 的 `_lock_r1_protocol_for_api_mocks` autouse fixture **删**——理由：

- 该 fixture 存在的唯一目的是给 22 条 r1 mock 测试兜底（commit `88ab2d9` 写进 docstring）
- 22 条 r1 mock 测试 Sprint 7 删除之后，fixture 失去服务对象
- `tests/api/r2/conftest.py` 已经覆盖自己的 r2 autouse 锁，子目录测试不依赖父锁

### 3.2 r1 mock 测试 22 测试是删还是留

**删**。理由按重要性排序：

1. **r2 mock 套已等价覆盖**（commit `2d96e90` `e4768ba` `a454f36`）。`tests/api/r2/` 下 32 测试覆盖 routes_agent / review_hint_injection / error_handling_e2e / agent_ask 4 个面，跟 r1 mock 套语义等价
2. **没了 loop.py 仍跑会失败**。r1 mock 测试的桩响应是 Anthropic content_blocks 形态，必须搭 r1 loop 才能跑——Sprint 7 删 r1 loop 后这些测试 import 一炸全炸（`from bookscope.agent.loop import TOOL_NAME_SEARCH`）。强行保留只能改 import 路径，但桩响应形态不变 = 全部跑失败
3. **维护负担**。两套等价测试维护成本翻倍，违反 simplicity 原则

### 3.3 `tests/agent/` 下 r1 测试集合

`tests/agent/` 一级共 **156 测试**（不含 r2 子目录的 51）。其中**纯 r1 mock 测试**约 7 个文件（test_agent_loop / test_adapters / test_loop_callback / test_loop_context_truncate_retry / test_loop_default_model / test_loop_rate_limit_retry / test_loop_tool_parallel），合计约 **107 测试**。

剩余 ~49 测试是 r0 / fast_path / question_processor / smoke / route_decision 等通用层，**保留不删**。

`tests/agent/test_r2_skeleton.py` 和 `tests/agent/test_route_decision_event.py` 含少量 r1 monkeypatch 桩，**改不删**——删掉 r1 case，保留 r2 default + 未知值兜底 case。

### 3.4 测试净删预估

Sprint 7 删除测试约 **107 (tests/agent r1) + 22 (tests/api r1) = 129 测试**。

删除后基线预估：663 − 129 = **534/534 全绿**（保守估计；实际删除时按文件维度走可能略多/少）。

---

## 4. reviewer.py r2 兼容性 audit

### 4.1 现状

`reviewer.py:29-36` 从 r1 loop 拿 6 个内部函数：

```python
from bookscope.agent.loop import (
    _autofix_control_chars_in_strings,
    _autofix_stray_apostrophe_string_closer,
    _autofix_unescaped_answer_quotes,
    _autofix_unescaped_quotes_in_all_string_values,
    _extract_first_json_object,
    _strip_code_fence,
)
```

`_extract_first_json_object` 已经在 commit `b33e985` 抽到 `bookscope/agent/utils/json_parsing.py`（私有别名转调），reviewer 现在拿的其实是个 loop.py 内的转调别名。

剩 5 个函数（4 autofix + 1 strip_code_fence）还在 loop.py 第 1320-1530 行。

### 4.2 三种方案对比

**方案 A：抽到 `bookscope/agent/utils/json_parsing.py`（仿 b33e985）**

- 把 4 个 `_autofix_*` + `_strip_code_fence` 整体搬到 utils
- loop.py 里留私有别名转调（Sprint 7 后期连同 loop.py 一起删）
- reviewer.py / loop_r2.py（间接通过 `_R1AgentLoop._parse_final_answer`）/ fast_path.py 改 import 路径
- 工程量：1 commit ~50 行代码移动 + import 改 3 处

**方案 B：下沉到 adapter 层**

- 按 ADR-007 D-3 "怪癖兜底应在 adapter" 思路，把 autofix 改成各 adapter 的协议方法
- 工程量：单独一个 ADR + adapter Protocol 改造 + 测试套重写，至少 1 个 sprint 工作量
- Sprint 7 时间窗内做不完

**方案 C：留在 r1 loop.py 暂不删**

- 违反 Sprint 7 "删 r1 代码" 核心目标
- loop.py 留 200 行只为给别人 import autofix——是 anti-pattern

### 4.3 推荐

**方案 A**。理由：

1. b33e985 已经立了"私有 helper 抽到 utils"的 precedent，方案 A 是同一姿态的延续
2. 工程量小（1 commit），不阻塞 Sprint 7 主进度
3. 方案 B 是更彻底的归位（autofix 跟 provider 怪癖绑定，确实该在 adapter 层），但属于 Sprint 8+ 范畴
4. loop_r2.py 第 28-33 行 docstring 自述"本文件不重复 copy 实现，直接 import r1 的 `_autofix_*` 函数复用 —— `_parse_final_answer` 在 r1 / r2 形态下完全一致"——这恰好印证 autofix 是 protocol-agnostic 的，归位到 utils 比留在 r1 loop 更合适

### 4.4 loop_r2.py 的隐藏依赖

`loop_r2.py:360` 有一行 `answer, citations = _R1AgentLoop._parse_final_answer(...)`——r2 loop **直接调 r1 loop 的 classmethod 复用 autofix 链**。

Sprint 7 删 r1 loop 时这一行也炸。方案 A 落地时 `_parse_final_answer` 也要抽——可以做成 `bookscope/agent/utils/json_parsing.py` 里的 `parse_final_answer(text: str) -> tuple[str, list[dict]]` 公共函数，loop_r2 直接调，不再走 `_R1AgentLoop._parse_final_answer` 这条诡异路径。

---

## 5. fast_path 后续 r2 化空间

grep `bookscope/agent/fast_path.py` 的 `content` / `stop_reason` / `tool_use` 命中 4 处：

- L506：`tool_use_id=None` —— 给 `ToolUseEvent` 传 None，这是 event schema 字段名跟 r1/r2 协议无关，**不动**
- L567：`messages = [{"role": "user", "content": user_prompt}]` —— OpenAI / Anthropic 都用 `content` 字段，protocol-agnostic，**不动**
- L597-598：注释解释 `extract_final_text` 如何看响应形态走 r1 / r2 分支
- L474：`os.environ.get("BOOKSCOPE_AGENT_PROTOCOL", "r2")` 读 env 给 `protocol_version` 赋值

**Sprint 7 唯一改动**：L474 删 env 读取，直接 `protocol_version="r2"` 硬编码（r1 都没了，env flag 整个 retire）。`extract_final_text` 在 utils 里保留双形态检测能力不动——因为 `extract_final_text` 本身不依赖 r1 runtime，只看响应形态有没有 `choices` 字段，r1 删除后它实际只走 r2 分支，但留着无害。

**结论**：fast_path 本体 r2 兼容性已经 OK（commit `0f36fb2` 修完），Sprint 7 改动面 1 行。

---

## 6. chapter-05 第八节预告 · 写作素材清单

chapter-05 第七节结尾明确"第八节留给 Sprint 7 真删 r1 代码后再补"。本节给 RE agent 写第八节用的事实点清单——Sprint 7 真做完后 1 小时能成稿。

### 6.1 数据点

- **代码净删**：runtime ~2150 行（1528 loop + 434 deepseek + 188 anthropic），测试 ~129 测试
- **基线变化**：663 → 534 全绿（预估，按本 audit §3 测算）
- **耦合点解锁**：reviewer / loop_r2 / fast_path / adapters/__init__ / agent/__init__ 5 处对 r1 模块的直接 import 全部改成 utils / r2 路径
- **commit 数**：4 commit（utils 抽 autofix / 删 r1 测试 / 删 r1 runtime / 文档同步）
- **删除日**：本 audit 签字之日起的执行窗口（按作者节奏定）

### 6.2 叙事钩子

- **"5 个月后的 git rm"**：ADR-003 选最小工作量的双向 adapter 把账往后压 5 个月；Sprint 7 这一次性还清，但还的姿态仍是"分 4 commit 还"
- **"loop.py 1528 行 → 0"**：从第 16 轮的 800 行膨胀到第 26 轮的 1384 行再到 Sprint 6 完工时的 1528 行——5 个月的债务图谱
- **"autofix 终于归位"**：第 24 轮第一个 autofix 加进 loop.py 时就埋了"未来该归到 adapter 或 utils"的暗钱；b33e985 抽 extract_first_json_object 走第一步，Sprint 7 把剩 4 个 autofix 抽到 utils 把这条路走完
- **"r1 trace 文档考古"**：case-study 里 30+ 处引文从此成为"那个年代 r1 长这样"的考古记录——这正是案例研究第一交付物的价值
- **"baseline 数字下降是健康信号"**：663 → 534 不是回归，是冗余删除；r2 mock 套早就等价覆盖

### 6.3 留给作者定稿的判断

- 第八节是 starter 还是定稿？按 chapter-05 末尾"定稿要等 Sprint 7 完成 + r2 在线上稳定运行一段时间之后的里程碑点"——RE agent 先写 starter，定稿要作者亲笔（feedback_case_study_milestone_finalization.md）

---

## 7. 推荐 Sprint 7 执行节奏

**4 步走，每步独立 commit + 测试零回归**：

### 步骤 1：utils 抽 autofix + parse_final_answer

- 把 `_autofix_unescaped_answer_quotes` / `_autofix_unescaped_quotes_in_all_string_values` / `_autofix_control_chars_in_strings` / `_autofix_stray_apostrophe_string_closer` / `_strip_code_fence` 5 个函数从 loop.py 搬到 `bookscope/agent/utils/json_parsing.py`
- 抽 `parse_final_answer(text, chunk_dicts=None) -> tuple[str, list[dict]]` 公共函数（融合 `_R1AgentLoop._parse_final_answer` 的 JSON parse + autofix 链）
- loop.py 留私有别名转调（5 行）保持向后兼容到下一步真删
- reviewer.py / loop_r2.py / fast_path.py 改 import 走 utils
- adapter 层共享 helper（如 `_strip_thinking_tags`）抽到 `bookscope/agent/adapters/_shared.py`
- **commit**：`refactor(agent): autofix + parse_final_answer 抽到 utils / adapter helper 抽 _shared.py · Sprint 7 解耦准备`
- **测试**：663 → 663 零回归

### 步骤 2：删 r1 测试 + 父级 conftest autouse 锁

- 删 `tests/agent/test_agent_loop.py` / `test_adapters.py`（保留 r2 部分如有）/ `test_loop_callback.py` / `test_loop_context_truncate_retry.py` / `test_loop_default_model.py` / `test_loop_rate_limit_retry.py` / `test_loop_tool_parallel.py`
- 删 `tests/api/conftest.py` 的 `_lock_r1_protocol_for_api_mocks` autouse fixture
- 删 `tests/api/` 下 22 条 r1 mock 测试（保留 r2 等价覆盖在 `tests/api/r2/` 下）
- `tests/agent/test_r2_skeleton.py` / `test_route_decision_event.py` / `tests/api/test_protocol_routing.py` 删 r1 case 留 r2 case
- **commit**：`test(agent): 删 r1 mock 测试 129 测试 · r2 mock 等价覆盖已就位 · Sprint 7 测试侧清理`
- **测试**：663 → ~534 全绿（数字按实际走）

### 步骤 3：git rm r1 runtime

- `git rm bookscope/agent/loop.py bookscope/agent/adapters/deepseek.py bookscope/agent/adapters/anthropic.py`
- 改 `bookscope/agent/__init__.py`：`_select_agent_loop_class` 退化成直接 `from bookscope.agent.loop_r2 import AgentLoop; return AgentLoop`；删 r1 三模块的 import
- 改 `bookscope/agent/adapters/__init__.py`：r1 adapter re-export 改成 r2 adapter（化名 `DeepSeekAdapter` / `AnthropicAdapter` 保持外部 API surface）
- 改 `bookscope/agent/fast_path.py:474`：删 env 读取，硬编码 `protocol_version="r2"`
- env flag `BOOKSCOPE_AGENT_PROTOCOL` retire（runtime 不再读，docstring 全清）
- **commit**：`feat(r2): Sprint 7 删 r1 runtime · loop.py + r1 adapters 共 2150 行 git rm · env flag retire`
- **测试**：~534 → ~534 全绿

### 步骤 4：文档同步 + chapter-05 第八节 starter

- 改 `docs/architecture-decisions/007-r2-openai-function-calling.md` Migration Plan 标 Sprint 7 完成
- 改 `docs/internal/STATE.md` 头注加新一波
- 改 `CLAUDE.md` 项目级"代际管理"表：r1-agent-loop 状态"当前主线" → "已退役"
- 派 RE agent 写 chapter-05 第八节 starter（用 §6 素材清单）
- **commit**：`docs(state+r2): Sprint 7 删 r1 完工 · STATE 第 36 轮第一波 + chapter-05 第八节 starter`

### 节奏说明

- 步骤 1 / 2 / 3 严格串行（依赖关系：抽公共 → 删测试 → 删 runtime）
- 步骤 4 与步骤 3 可并发（chapter-05 starter 不动 runtime）
- 总工程量预估 5-8 小时（一个集中工作日）

---

## 8. 撤回条件 · 诚实判断

audit 全程检查，**未发现 Sprint 7 不应推进的硬阻塞**。逐项过：

| 候选撤回条件 | 命中 | 理由 |
|--------------|------|------|
| r1 路径还有 user-facing 流量 | 否 | Sprint 6 切默认 r2 后所有 BYOK 用户走 r2；env flag 是回滚兜底，commit `88ab2d9` 起未发现作者真用过 `BOOKSCOPE_AGENT_PROTOCOL=r1` |
| 作者私稿依赖 r1 runtime | 否 | 作者 anshi 跑批历史 batch 数据是 JSON 文件（trace 写到 data/），不依赖 r1 runtime；下次跑 batch 走 r2 即可 |
| 历史 batch 数据回归依赖 r1 | 否 | data/r1-vs-r2 对照实验已完成（commit `c847169`）；后续 batch 跑 r2 即可，r1 数据保留作历史不需要重跑 |
| reviewer 没干净分离 | 否 | 方案 A 抽 autofix 到 utils 是干净分离路径，工程量 1 commit |
| loop_r2 对 r1 有运行时依赖（非纯 helper 复用） | 否 | grep 确认 loop_r2 只复用 r1 的常量 / helper / autofix，不调 r1 类方法实例化（除了一行 `_R1AgentLoop._parse_final_answer` classmethod 调用，步骤 1 同步抽掉）|
| 测试零回归不可达 | 否 | r2 mock 套（83 测试）已等价覆盖即将删除的 r1 mock 套（129 测试），数学上覆盖面不减 |
| ADR-007 撤回条件命中 | 否 | Sprint 5 实验数据（c847169）两本书都不退化，ADR-007 Migration Plan Sprint 7 推进的前置条件全满足 |

### 唯一软风险

**autofix 抽 utils 过程中有 import 循环风险**——reviewer / loop_r2 / fast_path 三处都要从 utils 导，utils 不能反向导任何 agent 模块。步骤 1 落地时严格控制 utils 是纯函数包，不引 LLMClient / LoopTrace 等 agent 内部类型。这条已经在 `bookscope/agent/utils/json_parsing.py` 的 b33e985 实现里有 precedent，按同样姿态做。

---

## 9. 给作者签字的关键判断点

**一句话**：autofix 函数从 loop.py 抽到 `bookscope/agent/utils/json_parsing.py` 这步必须先做且 zero-behavior 改动——这是把 reviewer / loop_r2 / fast_path 跟 loop.py 解耦的咽喉，做完才能动 git rm；剩余 git rm + 删 r1 测试 + 文档同步都是纯机械动作。

签字之后 Sprint 7 按本 audit §7 节奏 4 步走，预计 5-8 小时（一个集中工作日）完工。撤回条件不命中。

---

*audit 截止 2026-05-15 · 663/663 全绿 baseline · 不动 runtime 代码 · 纯 read-only 报告*
