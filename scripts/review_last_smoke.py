"""审稿第 N 次 smoke test 的 answer —— 独立 AI reviewer 闭环。

用法::

    DEEPSEEK_API_KEY=... python scripts/review_last_smoke.py <smoke_output_path>

或不传路径，默认读 ``BOOKSCOPE_SMOKE_LAST_OUTPUT`` 环境变量。

脚本从 smoke_test_r1.py 产生的 stdout 文本里 regex 抽出
``question`` / ``book_title`` / ``answer`` / ``citations``，喂给
:func:`bookscope.agent.reviewer.review_answer` 跑一次独立评估，
打印评分报告。

**已知 limitation**：reviewer 默认走 deepseek（与 generator 同家），
存在"同模型自评的偏袒"。脚本在输出开头会明示这一点。要换独立
reviewer，可通过 ``BOOKSCOPE_REVIEW_PROVIDER`` / ``BOOKSCOPE_REVIEW_MODEL``
覆盖（如 anthropic）。
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

# Windows 控制台 utf-8
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# 从 smoke output 抽字段
# ---------------------------------------------------------------------------

_QUESTION_RE = re.compile(r"^\[smoke\] question = (.+)$", re.MULTILINE)
_BOOK_TITLE_RE = re.compile(r"^\[smoke\] 书名: ([^，]+)，", re.MULTILINE)
_ANSWER_RE = re.compile(r"\[answer\]\n(.+?)\n+\[citations\]", re.DOTALL)
_CITATIONS_RE = re.compile(r"\[citations\]\n(\[.+?\])\n+\[trace\]", re.DOTALL)


def _extract_fields_from_smoke_output(text: str) -> dict[str, Any]:
    """从 smoke_test_r1.py stdout 抽 question/book_title/answer/citations。"""
    q = _QUESTION_RE.search(text)
    bt = _BOOK_TITLE_RE.search(text)
    ans = _ANSWER_RE.search(text)
    cit = _CITATIONS_RE.search(text)

    if not (q and bt and ans and cit):
        missing = [
            name for name, m in [
                ("question", q), ("book_title", bt),
                ("answer", ans), ("citations", cit),
            ] if m is None
        ]
        raise RuntimeError(
            f"未能从 smoke output 抽取字段: {missing}。"
            f"确认输入是成功 smoke 的 stdout（outcome=success）。"
        )

    citations = json.loads(cit.group(1))
    return {
        "question": q.group(1).strip(),
        "book_title": bt.group(1).strip(),
        "answer": ans.group(1).strip(),
        "citations": citations,
    }


# ---------------------------------------------------------------------------
# Provider 构造
# ---------------------------------------------------------------------------


def build_reviewer_client() -> tuple[Any, str, str]:
    """返回 (adapter, model, provider_name)；默认 deepseek。

    第 27 轮提升为 module-level 公开函数，让 ``smoke_test_r1.py`` 直接复用，
    避免两份脚本拷贝同一段 provider 选择逻辑。
    """
    provider = os.environ.get("BOOKSCOPE_REVIEW_PROVIDER", "deepseek")
    if provider == "deepseek":
        from bookscope.agent import DeepSeekAdapter as _DS
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            raise RuntimeError("DEEPSEEK_API_KEY 未设置。")
        model = os.environ.get("BOOKSCOPE_REVIEW_MODEL") or "deepseek-v4-flash"
        return _DS(api_key=api_key), model, "deepseek"
    if provider == "anthropic":
        from bookscope.agent import AnthropicAdapter
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY 未设置。")
        model = os.environ.get("BOOKSCOPE_REVIEW_MODEL") or "claude-sonnet-4-6"
        return AnthropicAdapter(api_key=api_key), model, "anthropic"
    raise RuntimeError(f"未知 BOOKSCOPE_REVIEW_PROVIDER: {provider!r}")


# ---------------------------------------------------------------------------
# 报告打印
# ---------------------------------------------------------------------------


def print_report(
    *,
    fields: dict[str, Any],
    review: dict[str, Any],
    provider: str,
    model: str,
) -> None:
    """打印 reviewer 报告。第 27 轮提升为公开函数，与 ``build_reviewer_client``
    一同被 ``smoke_test_r1.py`` 集成模式复用。
    """
    print("=" * 64)
    print("[reviewer] 审稿报告")
    print("=" * 64)
    print(f"题目    : {fields['question']}")
    print(f"书      : {fields['book_title']}")
    print(f"citation: {len(fields['citations'])} 条")
    print(f"审稿人  : provider={provider}, model={model}")
    print()
    print("--- limitation 提示 ---")
    print(f"当前 reviewer ({provider}/{model}) 可能与生成方同模型。")
    print("存在自我偏袒风险。多家 key 到位后可通过 BOOKSCOPE_REVIEW_PROVIDER")
    print("切到独立 provider 做盲评。")
    print()
    print("--- 各维度评分 ---")
    scores = review["scores"]
    for dim, score in scores.items():
        comment = review["per_dimension_comment"].get(dim, "")
        print(f"  {dim:30s} : {score}/5")
        print(f"    ↳ {comment}")
    total = sum(scores.values())
    maxtotal = 5 * len(scores)
    print(f"\n  合计: {total}/{maxtotal}")
    print()
    print("--- 总评 ---")
    print(review["overall"])
    print()
    print("--- 最大问题 ---")
    for issue in review.get("top_issues", []):
        print(f"  • {issue}")
    print()
    print("--- 如果只能改一件事 ---")
    print(f"  {review.get('single_most_valuable_improvement', '')}")
    print()
    print("=" * 64)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def main() -> int:
    if len(sys.argv) >= 2:
        smoke_path = Path(sys.argv[1])
    else:
        env_path = os.environ.get("BOOKSCOPE_SMOKE_LAST_OUTPUT", "").strip()
        if not env_path:
            print(
                "用法: python scripts/review_last_smoke.py <smoke_output_path>",
                file=sys.stderr,
            )
            return 1
        smoke_path = Path(env_path)

    if not smoke_path.is_file():
        print(f"[reviewer] 文件不存在: {smoke_path}", file=sys.stderr)
        return 1

    text = smoke_path.read_text(encoding="utf-8")
    try:
        fields = _extract_fields_from_smoke_output(text)
    except RuntimeError as exc:
        print(f"[reviewer] 抽字段失败: {exc}", file=sys.stderr)
        return 2

    print(f"[reviewer] 读取 smoke output: {smoke_path}")
    print(f"[reviewer] question 前 60 字: {fields['question'][:60]}...")
    print()

    try:
        client, model, provider = build_reviewer_client()
    except RuntimeError as exc:
        print(f"[reviewer] 配置错误: {exc}", file=sys.stderr)
        return 3

    from bookscope.agent.reviewer import review_answer

    print(f"[reviewer] 调 {provider} / {model} 做审稿...")
    try:
        review = review_answer(
            client=client,
            model=model,
            question=fields["question"],
            answer=fields["answer"],
            citations=fields["citations"],
            book_title=fields["book_title"],
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[reviewer] 失败: {type(exc).__name__}: {exc}", file=sys.stderr)
        raw = getattr(exc, "raw_text", None)
        if raw:
            print("[reviewer] ---- raw reviewer output ----", file=sys.stderr)
            print(raw)
        return 4

    print_report(fields=fields, review=review, provider=provider, model=model)
    return 0


if __name__ == "__main__":
    sys.exit(main())
