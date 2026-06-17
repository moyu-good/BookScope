# WP-character-graph · 人物关系图功能建设（设计）

> **性质：建设设计稿（design-first 过闸，作者已批准"继续"）。已建成 MVP。** 上游 exp-013（抽取已 GO）。

**日期**：2026-06-12

> **建成验收（2026-06-12）**：BE 抽取模块 + schema + 端点 `POST /api/agent/character-graph`（18 单测、719 全绿零回归）+ FE 自写力导向图组件 + 集成。anshi 真跑：24 节点、22 边、**22/22 边原文核验通过**、章号纠偏生效（命中 chunk 真章号）、40s。结构化 JSON 路径端到端验通。

---

## 目的

读者/学习者读长篇、复杂人物网的书容易迷失"谁是谁、什么关系"。exp-013 验证了 agent 能从整本书抽出全面、每边带原文证据的人物关系网且不瞎编。**现在建成用户真能看的图**——发明区从作家受众扩到读者受众的第一个落地功能。

## 方法论锚

- **精益 MVP（Build-Measure-Learn）**：先做能跑通的最小可用图证明价值，再迭代——作者明确要"收敛范围、不堆样式"。
- **Karpathy 简洁 + DRY**：抽取复用 `long_context` 既有形态（整本进 system + 缓存），只把"要 JSON 图"换进去；不另起一套。

一句话：这是长上下文抽取的一个结构化变体 + 一个最小能看的图组件，跑通优先。

## 方案概要

1. **BE 抽取**（新 `bookscope/agent/character_graph.py`）：复用 long_context 形态（整本进 system 固定段、缓存），prompt 改成要结构化 JSON `{"nodes":[{"name":...}], "edges":[{"source","target","relation","evidence"}]}`，`max_tokens=8000`（exp-013 验过图输出要这么大）。parse JSON → 对每条 edge 的 `evidence` 跑边粒度校验（复用 `verify_citations` 思路：snippet 命中某 chunk → `verified=true` + 用命中 chunk 真章号填 `chapter`）。失败返 `None`（与 long_context 同契约）。
2. **BE schema + 端点**：`CharacterGraph` / `GraphNode` / `GraphEdge` Pydantic（edge 带 verified/chapter/evidence）。新路由 `POST /api/agent/character-graph`（入参 session_id）→ 取 assembler → 仅当书塞得下（复用 `_should_use_long_context` 的大小判断）→ 抽取 → 返回图 JSON。塞不下 → 返回明确的"暂不支持大书"提示（MVP 不做 RAG 路抽图）。
3. **FE 组件**（新 `web/src/CharacterGraph.tsx`）：依赖无关的 SVG 力导向图（轻量自写简单斥力+连边，~15-25 节点够用，不引重库、合 CPU-only 底线）。节点=人物、边=关系（边上标 relation）。点边 → 弹出该关系的原文出处（evidence + 章号）。App.tsx 加一个"人物关系图"入口按钮。
4. **测试**：BE 抽取（mock LLM 吐结构化 JSON → parse + 边校验 + 章号填充 / parse 失败→None / 塞不下→提示）；schema；端点；FE `npm build` 过。

## 影响范围

- **新增**：`bookscope/agent/character_graph.py`、`bookscope/api/schemas.py` 加 3 个图 model、`bookscope/api/routes/agent.py`（或同级）加 1 端点、`web/src/CharacterGraph.tsx`、对应测试。
- **改动现有**：App.tsx 加入口按钮（最小）；不动现有问答 / 长上下文问答流。

## 不做（scope 边界）

- **不做塞不下的书**（RAG 路抽图）——MVP 只支持长上下文塞得下的书，大书给明确提示。
- **不做概念图**（理论书版）——留下一炮 probe（跨题材投影）。
- **不堆样式/重交互**（缩放/拖拽/过滤/高亮路径）——最小能看 + 点边看出处即可。
- **不做图缓存/增量**——每次现抽（可后续加，非 MVP）。
- **不引重前端图库**（cytoscape/d3 全家桶）——自写轻量 SVG，避免依赖膨胀。

## 验证方法

- BE：pytest——抽取 parse 结构化 JSON、边 evidence 过校验且章号来自命中 chunk、parse 失败→None、塞不下→明确提示；零回归。
- FE：`npm build` 过。
- 真跑：anshi 实际抽一次，节点/边合理（覆盖核心关系）、点边能看到原文出处。

## 风险 / 取舍

- **FE 力导向自写有风险铺开**：缓解——MVP 用最简斥力模型（固定迭代次数的力松弛），节点少够用；若布局太乱，退circular 布局兜底。这是最大不确定点。
- 抽取延迟（exp-013 ~45-67s）：MVP 接受（带 loading），后续可缓存。
