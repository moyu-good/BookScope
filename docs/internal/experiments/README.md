# 实验记录

本目录用于每次工程或研究实验的完整档案，须包含假设、实验设置、运行数据、结论与后续动作。

**命名规则**：`EXP-NNNN-主题.md`，NNNN 为四位递增编号，从 `0001` 起。

**必含字段**：假设、前置条件、输入数据、环境与参数、输出结果、与对照组的对比、结论、遗留问题。

**撰写人**：AI 主循环撰写，作者复核并签署结论。

**频率**：每一次启动独立实验即建一条，失败实验同样留档，不得省略。

---

## benchmark 数据点（QA 自动化）

`docs/internal/experiments/data/benchmark-<timestamp>[-<label>].{json,md}` 由
`scripts/benchmark_run_and_report.py` 写出，schema 见脚本文档（`bookscope-benchmark/v2`）。
关键字段：`p50_ms` / `p90_ms` / `mean_ms` / `per_question[].duration_ms`。

每次 BE 性能优化 PR 跑一次 benchmark + 跟最近一份基线对比：

```bash
python scripts/benchmark_run_and_report.py --label sprint5-post
python scripts/benchmark_compare.py \
    docs/internal/experiments/data/benchmark-<prev>.json \
    docs/internal/experiments/data/benchmark-<curr>.json
```

`benchmark_compare.py` 在 P50 上涨超 20%（默认阈值，可 `--threshold` 覆盖）时
`exit 1`，CI 用此挂掉性能回归 PR。

CI 烟测用 `BOOKSCOPE_BENCHMARK_DRY_RUN=1` 验证脚本可跑通而不烧 LLM key。
旧版 `benchmark-latency-*.json` 是 v1 schema，与新 v2 不兼容；新文件统一走 v2。

