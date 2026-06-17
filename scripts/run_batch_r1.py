"""按一组作家题批量跑 BookScope agent loop + reviewer，产出对照基准。

用途：第 26 轮起的 v3 vs v2 prompt 对比（provider 切换实验留作历史记录，
generator 对比）。**手工跑 5 题需要 ~10 分钟反复盯**，本脚本一次性自动跑完
整组 + 调 reviewer，输出和 ``v2-batch-01.json`` 同结构的 JSON。

用法（bash，key 内联）::

    DEEPSEEK_API_KEY=sk-xxxxx \\
    PYTHONIOENCODING=utf-8 \\
    python scripts/run_batch_r1.py \\
        --questions docs/internal/experiments/data/v2-batch-01.json \\
        --output    docs/internal/experiments/data/v3-deepseek-batch-01.json \\
        --batch-id  v3-deepseek-batch-01 \\
        --generator-prompt loop_system_prompt_v3 \\
        --citation-format  citation_format_v1 \\
        --reviewer-rubric  reviewer_rubric_v1

环境变量（与 smoke_test_r1.py 对齐）：

  - ``BOOKSCOPE_SMOKE_PROVIDER``   生成方 provider；默认 ``deepseek``
  - ``BOOKSCOPE_SMOKE_MODEL``      生成方 model；默认按 provider 选
  - ``BOOKSCOPE_REVIEW_PROVIDER``  reviewer provider；默认同上
  - ``BOOKSCOPE_REVIEW_MODEL``     reviewer model
  - ``BOOKSCOPE_SMOKE_TIMEOUT``    单次 query 超时（秒）；默认 600
  - ``BOOKSCOPE_SMOKE_MAX_ITER``   AgentLoop 最大迭代数
  - ``DEEPSEEK_API_KEY`` / ``ANTHROPIC_API_KEY`` 等：见各 provider 分支

只复用 smoke_test_r1.py 里的 ``_load_book_session`` / ``_build_adapter_and_model``
等公共部件，**不替换** smoke 脚本。smoke 是单题手动调试入口；本脚本是
研究批跑入口；两者并存。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="批量跑作家题 + reviewer")
    p.add_argument(
        "--questions",
        type=Path,
        required=True,
        help="输入 JSON：与 v2-batch-01.json 同结构（取 questions[].smoke.question）",
    )
    p.add_argument(
        "--output",
        type=Path,
        required=True,
        help="输出 JSON 路径（同 v2-batch-01.json 结构）",
    )
    p.add_argument("--batch-id", required=True, help="batch_id 字段值")
    p.add_argument(
        "--generator-prompt",
        default=None,
        help=(
            "【已废弃，WP0 起忽略】config.generator_prompt 改为从"
            " loop_shared 实际加载路径推导，不再接受口头标注"
        ),
    )
    p.add_argument(
        "--citation-format",
        default="citation_format_v1",
        help="顶层 config.citation_format 字段值（记录用）",
    )
    p.add_argument(
        "--reviewer-rubric",
        default="reviewer_rubric_v1",
        help="顶层 config.reviewer_rubric 字段值（记录用）",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=0,
        help="只跑前 N 题；0 表示全跑（默认）",
    )
    p.add_argument(
        "--book-scope",
        default="unknown",
        help=(
            "batch 跑的是这本书的哪部分。取值：'vol-1' / 'full' / "
            "'chapters-N-to-M' / 'unknown'。写到顶层 book.book_scope，"
            "用于跨 batch 对照时确认书范围一致（B-4 schema 字段）"
        ),
    )
    return p.parse_args()


# ---------------------------------------------------------------------------
# 单题跑：smoke + review
# ---------------------------------------------------------------------------


def _run_one_question(
    *,
    loop: Any,
    reviewer_client: Any,
    reviewer_model: str,
    question: str,
    book_title: str,
    language: str,
) -> dict[str, Any]:
    """跑一道题：generator → reviewer，返回单条 result dict。

    失败时（loop 抛异常 / reviewer JSON 解析失败）会把字段尽量填上
    并把 error 信息塞进结果，**不中断 batch**——避免一道题失败拖垮 5 题。
    """
    from bookscope.agent.errors import (
        AgentError,
        ContentFiltered,
        LLMFormatError,
    )
    from bookscope.agent.reviewer import review_answer

    smoke: dict[str, Any] = {"question": question}
    review: dict[str, Any] = {}
    error: str | None = None

    t0 = time.monotonic()
    try:
        result = loop.query(question)
    except ContentFiltered as exc:
        elapsed = time.monotonic() - t0
        smoke.update({
            "duration_s": round(elapsed, 1),
            "outcome_error": f"ContentFiltered: {exc}",
            "content_filter_blocked": True,
        })
        error = "loop_content_filtered_after_retries"
        return {"smoke": smoke, "review": review, "error": error}
    except (AgentError, Exception) as exc:  # noqa: BLE001
        elapsed = time.monotonic() - t0
        smoke.update({
            "duration_s": round(elapsed, 1),
            "outcome_error": f"{type(exc).__name__}: {exc}",
        })
        error = f"loop_failed: {type(exc).__name__}"
        # trace 在异常上时也带上
        partial_trace = getattr(exc, "trace", None)
        if partial_trace is not None:
            try:
                smoke["trace_summary"] = _extract_trace_summary(partial_trace)
            except Exception:  # noqa: BLE001
                pass
        return {"smoke": smoke, "review": review, "error": error}

    elapsed = time.monotonic() - t0
    coverage = _compute_citation_coverage(result.answer, result.citations)
    smoke.update({
        "duration_s": round(elapsed, 1),
        "answer": result.answer,
        "citations": result.citations,
        "citation_count": len(result.citations),
        "trace_summary": _extract_trace_summary(result.trace),
        "citation_coverage": coverage,
    })

    # reviewer
    try:
        review = review_answer(
            client=reviewer_client,
            model=reviewer_model,
            question=question,
            answer=result.answer,
            citations=result.citations,
            book_title=book_title,
            language=language,
        )
        # total = 5 维度求和
        scores = review.get("scores", {})
        if isinstance(scores, dict):
            review["total"] = sum(
                v for v in scores.values() if isinstance(v, (int, float))
            )
    except ContentFiltered as exc:
        error = f"reviewer_content_filtered_after_retries: {exc}"
        review = {"_error": error, "content_filter_blocked": True}
    except LLMFormatError as exc:
        error = f"reviewer_format_error: {exc}"
        review = {"_error": error, "_raw_text": getattr(exc, "raw_text", None)}
    except Exception as exc:  # noqa: BLE001
        error = f"reviewer_failed: {type(exc).__name__}: {exc}"
        review = {"_error": error}

    return {"smoke": smoke, "review": review, "error": error}


_CN_DIGIT_TO_INT = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9,
}

_CHAPTER_REF_RE = re.compile(r"第([一二三四五六七八九十百\d]+)[章回节]")


def _cn_chapter_to_int(s: str) -> int | None:
    """把"第七章"/"第二十三章"等中文数字章节字面量转 int。

    覆盖 1-99 范围，足够现役 baseline 书。失败返回 None（caller 跳过）。
    """
    if s.isdigit():
        return int(s)
    # 单字中文数字 1-9（"第七章"等）
    if s in _CN_DIGIT_TO_INT:
        return _CN_DIGIT_TO_INT[s]
    if s == "十":
        return 10
    if len(s) == 2:
        if s.startswith("十"):
            return 10 + _CN_DIGIT_TO_INT.get(s[1], 0)
        if s.endswith("十"):
            return _CN_DIGIT_TO_INT.get(s[0], 0) * 10
    if len(s) == 3 and s[1] == "十":
        return _CN_DIGIT_TO_INT.get(s[0], 0) * 10 + _CN_DIGIT_TO_INT.get(s[2], 0)
    return None


def _extract_answer_chapters(answer: str) -> set[int]:
    """从 answer 文本里抽出所有"第 N 章"形态的章节号 set。

    覆盖阿拉伯数字与中文数字（1-99）。answer 提到的章节号是"BookScope
    实际论证用到了哪些章节"的代理；与 citations 的 chapter 字段交集即
    citation 覆盖率。
    """
    out: set[int] = set()
    for m in _CHAPTER_REF_RE.finditer(answer):
        n = _cn_chapter_to_int(m.group(1))
        if n is not None and n > 0:
            out.add(n)
    return out


def _compute_citation_coverage(
    answer: str, citations: list[dict[str, Any]],
) -> dict[str, Any]:
    """citation 覆盖率 metric：answer 提到的章节有多少在 citations 里。

    返回字段（与 batch JSON 结构对位）：
    - ``chapters_referenced_in_answer`` : list[int]
    - ``chapters_with_citation`` : list[int]
    - ``citation_coverage_ratio`` : float in [0, 1]，answer 无章节引用时为 None

    研究意义：article-06 + article-09 集体提案的二级 metric，剥离
    "citation 数量"与"citation 与论点对位"两个维度。第 26 轮 baseline
    与 candidate 的 citation 数量差距已经显著（10-13 vs 5-7），但论点
    覆盖率差距更刺眼（v3.1+minimax q1 漏第 16/17 章）。
    """
    ans_chapters = _extract_answer_chapters(answer)
    cite_chapters = {
        int(c["chapter"]) for c in citations
        if isinstance(c, dict) and isinstance(c.get("chapter"), int)
    }
    if not ans_chapters:
        return {
            "chapters_referenced_in_answer": [],
            "chapters_with_citation": sorted(cite_chapters),
            "citation_coverage_ratio": None,
        }
    inter = ans_chapters & cite_chapters
    return {
        "chapters_referenced_in_answer": sorted(ans_chapters),
        "chapters_with_citation": sorted(cite_chapters),
        "citation_coverage_ratio": round(len(inter) / len(ans_chapters), 4),
    }


def _extract_trace_summary(trace: Any) -> dict[str, Any]:
    """从 LoopTrace 抽出 summary 字段子集（与 v2-batch-01 结构对齐）。

    LoopTrace 的字段名是 ``tool_calls``（不是 tool_invocations），每个
    dict 的工具名是 ``tool_name`` 字段——v2-batch-01.json 是手工填的所以
    用了别名 ``tool_call_names``，本函数做 surface mapping。
    """
    d = trace.model_dump() if hasattr(trace, "model_dump") else dict(trace)
    tool_calls = d.get("tool_calls") or []
    return {
        "iterations": d.get("iterations"),
        "duration_ms": d.get("duration_ms"),
        "total_input_tokens": d.get("total_input_tokens"),
        "total_output_tokens": d.get("total_output_tokens"),
        "content_filter_retries": d.get("content_filter_retries"),
        "outcome": d.get("outcome"),
        "tool_call_names": [
            tc.get("tool_name") for tc in tool_calls
            if isinstance(tc, dict) and tc.get("status") == "ok"
        ],
        "tool_call_count_total": len(tool_calls),
    }


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def main() -> int:
    args = _parse_args()

    # 加载输入题集
    if not args.questions.is_file():
        print(f"[batch] 题集文件不存在: {args.questions}", file=sys.stderr)
        return 1
    src = json.loads(args.questions.read_text(encoding="utf-8"))
    questions = src.get("questions") or []
    if args.limit > 0:
        questions = questions[: args.limit]
    if not questions:
        print("[batch] 题集为空", file=sys.stderr)
        return 1

    # prompt path override（用于单变量分离实验）
    # WP0：旧实现 patch ``bookscope.agent.loop``（Sprint 7 已 git rm，
    # import 直接炸）。override 现在内建在 loop_shared.resolve_system_prompt_path，
    # 本脚本只做存在性校验 + 把相对路径归一成绝对路径（保持旧的
    # "相对仓库根" 语义，loop_shared 按 cwd 解析）。
    prompt_override = os.environ.get("BOOKSCOPE_LOOP_PROMPT_PATH")
    if prompt_override:
        override_path = Path(prompt_override)
        if not override_path.is_absolute():
            override_path = _PROJECT_ROOT / override_path
        if not override_path.is_file():
            print(
                f"[batch] BOOKSCOPE_LOOP_PROMPT_PATH 不存在: {override_path}",
                file=sys.stderr,
            )
            return 2
        os.environ["BOOKSCOPE_LOOP_PROMPT_PATH"] = str(override_path)
        print(f"[batch] prompt override → {override_path}")

    # provider 默认 deepseek
    os.environ.setdefault("BOOKSCOPE_SMOKE_PROVIDER", "deepseek")
    os.environ.setdefault("BOOKSCOPE_REVIEW_PROVIDER", "deepseek")

    # 复用 smoke_test_r1.py 的公共部件
    from bookscope.agent import AgentLoop
    from bookscope.agent.backends.r0_assembler import R0BookAssembler
    from scripts.smoke_test_r1 import (  # type: ignore[import-not-found]
        DEFAULT_EPUB,
        _build_adapter_and_model,
        _load_book_session,
    )

    provider = os.environ["BOOKSCOPE_SMOKE_PROVIDER"]
    print(f"[batch] generator provider = {provider}")
    try:
        gen_adapter, gen_model = _build_adapter_and_model(provider)
    except RuntimeError as exc:
        print(f"[batch] generator 配置错误: {exc}", file=sys.stderr)
        return 2
    print(f"[batch] generator model = {gen_model}")

    # reviewer
    review_provider = os.environ["BOOKSCOPE_REVIEW_PROVIDER"]
    print(f"[batch] reviewer provider = {review_provider}")
    review_adapter, review_model = _build_review_client(review_provider)
    print(f"[batch] reviewer model = {review_model}")

    # epub 路径：优先 env var，否则 DEFAULT_EPUB（与 _load_book_session 保持一致）
    _smoke_epub_env = os.environ.get("BOOKSCOPE_SMOKE_EPUB")
    _book_path = _smoke_epub_env if _smoke_epub_env else str(DEFAULT_EPUB)

    # 加载书 + 构造 loop（一次性，多题共享）
    print("[batch] 加载书 + 装配 backends ...")
    book, chunks, kg, vector_store = _load_book_session()
    _kg_char_names = [c.name for c in kg.characters]
    _kg_source = (
        f"manual_{len(_kg_char_names)}_characters_{'_'.join(_kg_char_names)}"
        if _kg_char_names else "empty_kg"
    )
    assembler = R0BookAssembler(
        book_text=book,
        chunks=chunks,
        knowledge_graph=kg,
        session_vector_store=vector_store,
    )
    backends = assembler.build_all()
    if backends["search"] is None:
        print("[batch] vector store 装配失败", file=sys.stderr)
        return 3

    timeout_seconds = float(os.environ.get("BOOKSCOPE_SMOKE_TIMEOUT", "600"))
    max_iter_env = os.environ.get("BOOKSCOPE_SMOKE_MAX_ITER")
    loop_kwargs: dict[str, Any] = {
        "client": gen_adapter,
        "search_chunks_backend": backends["search"],
        "chapter_range_backend": backends["chapter_range"],
        "list_characters_backend": backends["list_characters"],
        "model": gen_model,
        "timeout_seconds": timeout_seconds,
    }
    if max_iter_env:
        loop_kwargs["max_iterations"] = int(max_iter_env)
    loop = AgentLoop(**loop_kwargs)

    book_title = book.title
    language = getattr(book, "language", "zh") or "zh"
    _wc = getattr(book, "word_count", "?")
    print(f"[batch] book = {book_title} ({_wc} 字 / {len(chunks)} chunk)")
    n_concurrent_env = os.environ.get("BOOKSCOPE_BATCH_CONCURRENCY", "5")
    try:
        n_concurrent = max(1, int(n_concurrent_env))
    except ValueError:
        n_concurrent = 5
    serial = n_concurrent <= 1
    print(
        f"[batch] 共 {len(questions)} 题，"
        f"{'串行' if serial else f'并发 {n_concurrent}'} 跑"
    )
    print("=" * 64)

    print_lock = threading.Lock()

    def _run_indexed(idx: int, q: dict[str, Any]) -> dict[str, Any] | None:
        qid = q.get("id", f"q{idx}")
        qtype = q.get("type", "")
        qtype_desc = q.get("type_description", "")
        question = (q.get("smoke") or {}).get("question") or q.get("question")
        if not question:
            with print_lock:
                print(
                    f"[batch] [{idx}/{len(questions)}] {qid} 跳过（缺 question）"
                )
            return None
        rec = _run_one_question(
            loop=loop,
            reviewer_client=review_adapter,
            reviewer_model=review_model,
            question=question,
            book_title=book_title,
            language=language,
        )
        rec_full: dict[str, Any] = {
            "id": qid,
            "type": qtype,
            "type_description": qtype_desc,
            "_orig_idx": idx,
            **rec,
        }
        # 单题完成时打印（并发场景下每题完成顺序不确定）
        smoke = rec.get("smoke", {})
        review = rec.get("review", {})
        err = rec.get("error")
        cite = smoke.get("citation_count", 0)
        dur = smoke.get("duration_s", 0)
        total = review.get("total")
        with print_lock:
            print(
                f"[batch] [{idx}/{len(questions)}] {qid} [{qtype}] 完成 "
                f"→ dur={dur}s cite={cite} "
                f"total={total if total is not None else 'N/A'} "
                f"{'ERR=' + err if err else ''}"
            )
        return rec_full

    results: list[dict[str, Any]] = []
    t_batch_start = time.monotonic()
    if serial:
        for idx, q in enumerate(questions, start=1):
            rec = _run_indexed(idx, q)
            if rec is not None:
                results.append(rec)
    else:
        with ThreadPoolExecutor(max_workers=n_concurrent) as ex:
            futures = {
                ex.submit(_run_indexed, idx, q): idx
                for idx, q in enumerate(questions, start=1)
            }
            for fut in as_completed(futures):
                rec = fut.result()
                if rec is not None:
                    results.append(rec)

    # 按原题目顺序排序输出 JSON（并发时完成顺序不确定）
    results.sort(key=lambda r: r.get("_orig_idx", 0))
    for r in results:
        r.pop("_orig_idx", None)

    batch_elapsed = time.monotonic() - t_batch_start

    # 汇总
    from bookscope.agent._internal import loop_shared as _loop_shared

    summary = _build_summary(results, batch_elapsed)
    out = {
        "batch_id": args.batch_id,
        "created_at": time.strftime("%Y-%m-%d"),
        "book": {
            "title": book_title,
            "path": _book_path,
            "word_count": getattr(book, "word_count", None),
            "chunk_count": len(chunks),
            "book_scope": args.book_scope,
        },
        "config": {
            "generator_provider": provider,
            "generator_model": gen_model,
            # WP0：从 loop_shared 实际加载路径推导，不再用 CLI 口头标注——
            # exp006 数据归属事故（实跑 v3.1 标 v3.4）的直接防再犯
            "generator_prompt": _loop_shared.resolve_system_prompt_path().stem,
            "prompt_version": _loop_shared.current_prompt_version(),
            "citation_format": args.citation_format,
            "kg_source": _kg_source,
            "vector_mode": "bm25_only",
            "reviewer_provider": review_provider,
            "reviewer_model": review_model,
            "reviewer_rubric": args.reviewer_rubric,
            "limitation": "reviewer 与生成方同 provider/model；存在自我偏袒风险"
            if review_provider == provider and review_model == gen_model
            else "reviewer 与生成方异 provider/model；可视为部分独立审稿",
        },
        "questions": results,
        "summary": summary,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("=" * 64)
    print(f"[batch] 完成，写出 {args.output}")
    print(f"[batch] 总耗时 {batch_elapsed:.1f}s")
    if "average_total" in summary:
        print(f"[batch] 平均 total = {summary['average_total']}")
    return 0


# ---------------------------------------------------------------------------
# 子工具
# ---------------------------------------------------------------------------


def _build_review_client(provider: str) -> tuple[Any, str]:
    """复用 review_last_smoke.py 的 provider 构造（直接拷贝出关键分支以保独立）。"""
    from bookscope.agent import DeepSeekAdapter

    if provider == "deepseek":
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            raise RuntimeError("DEEPSEEK_API_KEY 未设置（reviewer 用）")
        model = os.environ.get("BOOKSCOPE_REVIEW_MODEL") or "deepseek-v4-flash"
        return DeepSeekAdapter(api_key=api_key), model
    if provider == "anthropic":
        from bookscope.agent import AnthropicAdapter

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY 未设置（reviewer 用）")
        model = os.environ.get("BOOKSCOPE_REVIEW_MODEL") or "claude-sonnet-4-6"
        return AnthropicAdapter(api_key=api_key), model
    raise RuntimeError(f"未知 reviewer provider: {provider!r}")


def _build_summary(
    results: list[dict[str, Any]], batch_elapsed_s: float,
) -> dict[str, Any]:
    """汇总 5 题：平均分 / min / max / 总耗时 / 总 token / outcome 统计。"""
    dim_keys = (
        "structural_judgment",
        "evidence_density",
        "honesty",
        "actionability",
        "cross_chapter_coherence",
    )
    score_lists: dict[str, list[float]] = {k: [] for k in dim_keys}
    totals: list[float] = []
    in_tokens = 0
    out_tokens = 0
    success_count = 0

    for r in results:
        smoke = r.get("smoke") or {}
        review = r.get("review") or {}
        scores = review.get("scores") or {}
        for k in dim_keys:
            v = scores.get(k)
            if isinstance(v, (int, float)):
                score_lists[k].append(float(v))
        if isinstance(review.get("total"), (int, float)):
            totals.append(float(review["total"]))
        ts = smoke.get("trace_summary") or {}
        in_tokens += int(ts.get("total_input_tokens") or 0)
        out_tokens += int(ts.get("total_output_tokens") or 0)
        if (ts.get("outcome") == "success") and not r.get("error"):
            success_count += 1

    # citation 覆盖率（None 题剔除后求平均）
    cov_values: list[float] = []
    for r in results:
        cov = ((r.get("smoke") or {}).get("citation_coverage") or {}).get(
            "citation_coverage_ratio"
        )
        if isinstance(cov, (int, float)):
            cov_values.append(float(cov))

    # WP1 引用真实率：全 batch 所有 citation 里 verified=true 的占比。
    # 一条 citation 都没有时记 None——区分"没数据"与"全编造"。
    verified_count = 0
    citation_total = 0
    for r in results:
        for cit in (r.get("smoke") or {}).get("citations") or []:
            if not isinstance(cit, dict):
                continue
            citation_total += 1
            if cit.get("verified") is True:
                verified_count += 1

    summary: dict[str, Any] = {
        "average_scores": {
            k: round(sum(vs) / len(vs), 2) if vs else None
            for k, vs in score_lists.items()
        },
        "average_total": (
            round(sum(totals) / len(totals), 2) if totals else None
        ),
        "min_total": min(totals) if totals else None,
        "max_total": max(totals) if totals else None,
        "average_citation_coverage_ratio": (
            round(sum(cov_values) / len(cov_values), 4) if cov_values else None
        ),
        "citation_coverage_sample_size": len(cov_values),
        "citation_verified_rate": (
            round(verified_count / citation_total, 4) if citation_total else None
        ),
        "citation_verified_sample_size": citation_total,
        "all_outcomes_success": success_count == len(results),
        "success_count": success_count,
        "total_questions": len(results),
        "total_duration_s": round(batch_elapsed_s, 1),
        "total_input_tokens": in_tokens,
        "total_output_tokens": out_tokens,
    }
    return summary


if __name__ == "__main__":
    sys.exit(main())
