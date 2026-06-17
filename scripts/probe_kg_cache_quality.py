"""Sprint 6 KG 缓存质量验证 probe.

用途：跑 exp006 设计文档（``docs/internal/experiments/006-sprint-6-kg-cache-validation-design.md``）
第三节质量实验矩阵（3a / 3b / 4a / 4b 四组）。验证 KG book-level 缓存命中跟
空缓存场景下跑 5 题作家诊断 batch 评分**逐题 5 维度
std ≤ 0.5 分**——超过即说明 cache key 漏字段、stale 风险或反序列化丢字段。

.. note:: WP0 勘误（2026-06-10）：本 docstring 旧版自称"默认 v3.4 prompt"
   为误——当时默认实为 v3.1（loop_shared 冻结 bug），且本脚本从不实现
   prompt override。5/18-19 的 4 组 exp006 数据实跑 v3.1，详见 exp006
   设计文档第十节勘误。WP0 起 prompt 版本由 ``loop_shared`` 单一事实源
   决定并写进 trace 与输出元数据。

跑出来的 JSON 落 ``docs/internal/experiments/data/exp006-kg-cache-quality-{book}-{state}.json``，
schema 跟 ``v2-batch-01.json`` 同结构方便 diff，给 RE 写撤回判定用。

实验设计要点（节选自 exp006 设计第三节）：

- empty 状态：跑前清两层 KG 缓存重新抽 KG，再跑 5 题 batch
- warm 状态：跑前先 warm-up 一次（保证 book-level 命中），再跑 5 题 batch
- 同一组 question + 同一 prompt + 同一 reviewer rubric——只缓存状态变
- 测量每题：25 分制 total / 5 维度子分 / citation 厚度 / 答案 markdown 全文
- 撤回判定：5 维度任一维度 std > 0.5 分 → ``validation_failed=true``
  + ``failure_reason="quality_diverged"``

注意：本脚本一次只跑一种 state，撤回判定需要 empty 与 warm 两份 JSON 比对。
跑两次后用 ``compare_quality_runs`` helper 函数（导出给 CLI / 后续脚本）
读两份 JSON 算逐维度 std。

用法::

    DEEPSEEK_API_KEY=sk-xxxxx \\
    PYTHONIOENCODING=utf-8 \\
    BOOKSCOPE_SMOKE_EPUB=path/to/book.epub \\
    BOOKSCOPE_LOOP_PROMPT_PATH=bookscope/agent/prompts/loop_system_prompt_v3.4.md \\
    python scripts/probe_kg_cache_quality.py \\
        --book anshi --cache-state empty

参数：

- ``--book``：``anshi`` / ``mingchao``，决定加载哪本书 + 用哪个题集
- ``--cache-state``：``empty`` / ``warm``
- ``--output``：JSON 落地路径（默认按命名规则拼）

环境变量（与 ``run_batch_r1.py`` 对齐）：

- ``DEEPSEEK_API_KEY``：必填
- ``BOOKSCOPE_SMOKE_EPUB``：epub 路径
- ``BOOKSCOPE_LOOP_PROMPT_PATH``：prompt 路径 override（WP0 起由
  ``loop_shared.resolve_system_prompt_path`` 内建支持；不设则走
  ``loop_shared.CURRENT_PROMPT_VERSION`` 默认版本）

**前置条件**：

- ``DEEPSEEK_API_KEY`` 已设
- ``BOOKSCOPE_SMOKE_EPUB`` 指向真 epub 文件
- 题集存在：``docs/internal/experiments/data/exp002-anshi-questions.json``（anshi）
  或 ``docs/internal/experiments/data/v2-batch-01.json``（mingchao）

本脚本不在 CI 跑，由 QA 在作者明示批 LLM cost 后手动跑。
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from pathlib import Path
from typing import Any

# Windows 控制台 UTF-8 兜底
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# 撤回阈值（与 exp006 设计第五节对位）
# ---------------------------------------------------------------------------

QUALITY_STD_MAX: float = 0.5
"""5 维度任一维度的 empty vs warm 跑分 std 上限。超过即 cache key 漏字段。

阈值出处：exp006 设计第五节第 1 条——"任一题任一维度子分差 > 0.5 分"。
单维度满分 5 分，0.5 分等于 10% 偏移，缓存命中跟空时这种应该确定性
等同的两次跑出现 10% 偏移说不通——撤回 commit ``2419176`` book-level
层，回查 ``kg_book_cache.py`` cache key 是否漏字段。"""

FAILURE_REASON_DIVERGED: str = "quality_diverged"
"""撤回 JSON 字段值，给后续判定脚本读。"""

QUALITY_DIMENSIONS: list[str] = [
    "structural_judgment",
    "evidence_density",
    "honesty",
    "actionability",
    "cross_chapter_coherence",
]
"""reviewer rubric v1 的 5 个维度名称（按 exp006 第三节列出顺序）。

实际 reviewer 返回的 ``scores`` dict 字段名跟 rubric prompt 一致；
这里写死一份给 cross-run diff 检测用——dict 命中其中之一即对位。"""


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """CLI 解析。argv 显式传入让单测直接喂参数列表。"""
    p = argparse.ArgumentParser(
        description="Sprint 6 KG 缓存质量验证 probe",
    )
    p.add_argument(
        "--book",
        choices=["anshi", "mingchao"],
        required=True,
        help="测哪本书：anshi 整本 / mingchao 卷一",
    )
    p.add_argument(
        "--cache-state",
        choices=["empty", "warm"],
        required=True,
        help="跑前缓存状态：empty 清缓存 / warm 先做一次 warm-up",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        help="JSON 落地路径；不给走默认命名 exp006-kg-cache-quality-{book}-{state}.json",
    )
    return p.parse_args(argv)


# ---------------------------------------------------------------------------
# 撤回判定（两份 JSON 比对）
# ---------------------------------------------------------------------------


def compare_quality_runs(
    *,
    empty_questions: list[dict[str, Any]],
    warm_questions: list[dict[str, Any]],
    max_std: float = QUALITY_STD_MAX,
) -> tuple[bool, str | None, dict[str, float]]:
    """对照 empty / warm 两次跑的 5 维度评分算逐维度 std，判是否过线。

    Args:
        empty_questions: empty 状态 batch JSON 的 ``questions`` 数组。
        warm_questions: warm 状态 batch JSON 的 ``questions`` 数组。
        max_std: 单维度 std 上限，默认 0.5。

    Returns:
        ``(validation_failed, failure_reason, per_dimension_std)``。
        ``per_dimension_std`` dict 把每个维度名映射到对照 std（题间平均）。
        任一维度 std > max_std 即触发 validation_failed=True。

    Note:
        两份 JSON 的 questions 必须按 ``id`` 一一对应——靠 caller 保证（同
        题集跑两次，顺序天然一致）。本函数按 index 配对，不再按 id rejoin。
    """
    # 按 question index 提取 review.scores dict
    n = min(len(empty_questions), len(warm_questions))
    per_dim_diffs: dict[str, list[float]] = {dim: [] for dim in QUALITY_DIMENSIONS}
    for i in range(n):
        eq = empty_questions[i].get("review", {}) or {}
        wq = warm_questions[i].get("review", {}) or {}
        e_scores = eq.get("scores", {}) or {}
        w_scores = wq.get("scores", {}) or {}
        if not isinstance(e_scores, dict) or not isinstance(w_scores, dict):
            continue
        for dim in QUALITY_DIMENSIONS:
            e_val = e_scores.get(dim)
            w_val = w_scores.get(dim)
            if isinstance(e_val, (int, float)) and isinstance(w_val, (int, float)):
                per_dim_diffs[dim].append(abs(float(e_val) - float(w_val)))

    # 把每维度逐题差值的 std 算出来——差值越分散表示缓存命中下评分越不稳
    per_dim_std: dict[str, float] = {}
    for dim, diffs in per_dim_diffs.items():
        if len(diffs) >= 2:
            per_dim_std[dim] = round(statistics.stdev(diffs), 4)
        elif len(diffs) == 1:
            # 只有一题对照——直接拿绝对差当 std 代理
            per_dim_std[dim] = round(diffs[0], 4)
        else:
            per_dim_std[dim] = 0.0

    failed_dims = [dim for dim, s in per_dim_std.items() if s > max_std]
    if failed_dims:
        return (
            True,
            FAILURE_REASON_DIVERGED,
            per_dim_std,
        )
    return False, None, per_dim_std


# ---------------------------------------------------------------------------
# 题集 / 书路径解析
# ---------------------------------------------------------------------------


_QUESTION_FILE_BY_BOOK = {
    "anshi": "exp002-anshi-questions.json",
    "mingchao": "v2-batch-01.json",
}


def _resolve_questions_path(book: str) -> Path:
    """按 ``--book`` 拼题集路径。"""
    return _PROJECT_ROOT / "docs" / "experiments" / "data" / _QUESTION_FILE_BY_BOOK[book]


def _default_output_path(book: str, cache_state: str) -> Path:
    """默认 JSON 落地路径（不带 timestamp——同 state 多次跑会覆盖）。"""
    return (
        _PROJECT_ROOT
        / "docs"
        / "experiments"
        / "data"
        / f"exp006-kg-cache-quality-{book}-{cache_state}.json"
    )


# ---------------------------------------------------------------------------
# 缓存清理 / warm-up 工具
# ---------------------------------------------------------------------------


def _clear_both_kg_caches() -> None:
    """清两层 KG 缓存（batch + book）。empty 跑前调用。"""
    from bookscope.agent._internal.kg_book_cache import clear_book_kg_cache
    from bookscope.agent._internal.kg_cache import clear_kg_cache

    clear_kg_cache()
    clear_book_kg_cache()


def _warm_up_kg(
    *,
    chunks: list[Any],
    book_title: str,
    language: str,
    adapter: Any,
    model: str,
) -> None:
    """跑一次 KG 抽取让 book-level 缓存有数据。warm 状态下用。"""
    from bookscope.agent.backends.minimal_kg_extractor import MinimalKGExtractor

    print("[probe] warm-up 中（不计入数据点）...")
    extractor = MinimalKGExtractor(client=adapter, model=model)
    extractor.extract(chunks=chunks, book_title=book_title, language=language)
    print("[probe] warm-up 完成")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("[probe] DEEPSEEK_API_KEY 未设置", file=sys.stderr)
        return 1
    if not os.environ.get("BOOKSCOPE_SMOKE_EPUB"):
        print(
            "[probe] BOOKSCOPE_SMOKE_EPUB 未设置（要指向 anshi 或 mingchao 卷一 epub）",
            file=sys.stderr,
        )
        return 1

    questions_path = _resolve_questions_path(args.book)
    if not questions_path.is_file():
        print(f"[probe] 题集文件不存在: {questions_path}", file=sys.stderr)
        return 1

    # 复用 smoke_test_r1 / run_batch_r1 的书加载 + adapter 构造
    from scripts.run_batch_r1 import (  # type: ignore[import-not-found]
        _build_review_client,
        _build_summary,
        _run_one_question,
    )
    from scripts.smoke_test_r1 import (  # type: ignore[import-not-found]
        _build_adapter_and_model,
        _load_book_session,
    )

    print(f"[probe] book={args.book} cache-state={args.cache_state}")
    print(f"[probe] 题集: {questions_path.name}")

    # 加载题集
    src = json.loads(questions_path.read_text(encoding="utf-8"))
    questions = src.get("questions") or []
    if not questions:
        print("[probe] 题集为空", file=sys.stderr)
        return 1

    # 加载书 + 缓存 state 准备
    book, chunks, _seed_kg, vector_store = _load_book_session()
    book_title = book.title
    language = getattr(book, "language", "zh") or "zh"

    adapter, gen_model = _build_adapter_and_model("deepseek")
    review_adapter, review_model = _build_review_client("deepseek")
    print(f"[probe] generator={gen_model} reviewer={review_model}")

    # 缓存 state 切换
    if args.cache_state == "empty":
        _clear_both_kg_caches()
        print("[probe] 已清两层 KG 缓存（batch + book）")
    else:
        _clear_both_kg_caches()
        _warm_up_kg(
            chunks=chunks,
            book_title=book_title,
            language=language,
            adapter=adapter,
            model=gen_model,
        )

    # 真跑 KG 抽取（empty 时走全量；warm 时命中 book-level）
    from bookscope.agent.backends.minimal_kg_extractor import MinimalKGExtractor

    extractor = MinimalKGExtractor(client=adapter, model=gen_model)
    kg = extractor.extract(chunks=chunks, book_title=book_title, language=language)
    print(f"[probe] KG 抽取完成：{len(kg.characters)} 角色")

    # 构造 loop（沿用 run_batch_r1 的装配路径）
    from bookscope.agent import AgentLoop
    from bookscope.agent.backends.r0_assembler import R0BookAssembler

    assembler = R0BookAssembler(
        book_text=book,
        chunks=chunks,
        knowledge_graph=kg,
        session_vector_store=vector_store,
    )
    backends = assembler.build_all()
    loop = AgentLoop(
        client=adapter,
        search_chunks_backend=backends["search"],
        chapter_range_backend=backends["chapter_range"],
        list_characters_backend=backends["list_characters"],
        model=gen_model,
    )

    # 跑 5 题（串行——本 probe 不追求速度，只要稳）
    results: list[dict[str, Any]] = []
    for idx, q in enumerate(questions, start=1):
        qid = q.get("id", f"q{idx}")
        qtype = q.get("type") or q.get("category", "")
        question = (q.get("smoke") or {}).get("question") or q.get("question")
        if not question:
            print(f"[probe] q{idx} 跳过（缺 question）")
            continue
        rec = _run_one_question(
            loop=loop,
            reviewer_client=review_adapter,
            reviewer_model=review_model,
            question=question,
            book_title=book_title,
            language=language,
        )
        rec_full = {"id": qid, "type": qtype, **rec}
        results.append(rec_full)
        total = (rec.get("review") or {}).get("total")
        print(
            f"[probe] {idx}/{len(questions)} {qid} 完成 total="
            f"{total if total is not None else 'N/A'}"
        )

    # 汇总
    summary = _build_summary(results, batch_elapsed_s=0.0)

    from bookscope.agent._internal import loop_shared as _loop_shared

    payload: dict[str, Any] = {
        "schema": "bookscope-kg-cache-probe/v1",
        "probe": "quality",
        "book": args.book,
        "cache_state": args.cache_state,
        "batch_id": f"exp006-kg-cache-quality-{args.book}-{args.cache_state}",
        # WP0：版本是记录的事实——5/18-19 四组数据缺这个字段导致归属事故
        "prompt_version": _loop_shared.current_prompt_version(),
        "book_info": {
            "title": book_title,
            "chunk_count": len(chunks),
        },
        "config": {
            "generator_provider": "deepseek",
            "generator_model": gen_model,
            "reviewer_provider": "deepseek",
            "reviewer_model": review_model,
            "kg_character_count": len(kg.characters),
        },
        "questions": results,
        "summary": summary,
        "quality_std_threshold": QUALITY_STD_MAX,
    }

    out_path = args.output or _default_output_path(args.book, args.cache_state)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[probe] 写出 {out_path}")
    print(
        f"[probe] {len(results)} 题完成 "
        f"({args.cache_state})。撤回判定需 empty + warm 两份 JSON 后跑 "
        f"compare_quality_runs。"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
