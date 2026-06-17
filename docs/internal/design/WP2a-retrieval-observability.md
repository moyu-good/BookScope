# WP2a 设计稿 · 检索降级可见 + golden set 格式规范

**日期**：2026-06-10
**状态**：✅ 已落地（commit `c717f8e`，2026-06-10）· 第 4 步对照通过——成功标准 3/3（ChunkMatch 带 retrieval_mode / 两种模式 mock 验证 / 零回归）。golden set 标注本体留 RE 专项（按设计）。
**上游**：`docs/internal/design/2026-06-10-design-gap-review.md` 缺口 5

---

## 目的

消掉检索链路最危险的静默降级：无 embedding key 时退 BM25-only，同一道题检索质量完全不同，但任何地方不留痕——分数波动无法归因到检索层。

**受益者**：所有实验（检索失败与生成失败从此可分开归因）；用户（降级可见是项目既有姿态）。

**成功标准**：
1. 每条 `ChunkMatch` 带 `retrieval_mode`（`"hybrid"` / `"bm25_only"`）
2. mock 两种模式各跑一次，字段如实反映
3. 全套零回归

## 方法论锚

**戴明（无测量不改进）/ 项目自有"降级可见"姿态**——和 WP0 同型：先把隐藏状态变成记录的事实。

## 方案概要

1. `SessionVectorStore` 暴露 `retrieval_mode` 属性（现有降级分支处已有内部状态，对外吐字符串）
2. `ChunkMatch` 加 `retrieval_mode: str | None = None`（向后兼容）
3. `r0_search_chunks.py` 的 backend 在构造 ChunkMatch 时从 vector_store 读取填充
4. **golden set 格式规范**（本版只定格式，标注下一轮 RE 专项跑）：
   `docs/internal/experiments/data/golden-retrieval-{book}.json`，每条 `{query, expected_chunk_ids: [...], expected_chapters: [...], note}`，每本书 20-30 条，覆盖语义找 / 位置找 / 角色找三类工具动作

## 影响范围

`bookscope/store/vector_store.py` / `bookscope/agent/tools/schemas.py` / `bookscope/agent/backends/r0_search_chunks.py` + 对应测试。

## 不做什么

- 不做 golden set 标注本体（需逐书人工质量判断，RE 专项）
- 不动 relevance_score 归一化（等 golden set 数据说话再定）
- 不做 contextual chunk header 实验（WP2 主体，等 golden set 当对照基线）

## 验证方法

mock vector_store 两种模式 → ChunkMatch.retrieval_mode 断言；全套回归 + ruff。

**估时**：0.5 agent 天。
