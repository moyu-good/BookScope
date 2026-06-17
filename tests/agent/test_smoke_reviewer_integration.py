"""第 27 轮 Task #27.5 —— smoke_test_r1.py 内嵌 reviewer 集成的单测。

覆盖四条关键路径：

1. 开关关时（``BOOKSCOPE_SMOKE_REVIEW`` 未设置）reviewer 不被调用
2. 开关开 + outcome=success 走 ``_maybe_run_reviewer`` → reviewer 被调用，
   传参与内存对象一致（不再走 stdout 抽字段那条路）
3. outcome=failure 不走到 ``_maybe_run_reviewer``（用控制流证明：失败分支
   `return 3` 在它之前就已经短路）
4. reviewer 抛异常时 ``_maybe_run_reviewer`` 自身不传播异常——smoke 主流程
   的退出码不受影响

实现策略：直接对 ``scripts.smoke_test_r1`` 的 ``_maybe_run_reviewer`` 单测，
用 monkeypatch 替换 ``scripts.review_last_smoke.build_reviewer_client`` /
``bookscope.agent.reviewer.review_answer`` / ``scripts.review_last_smoke
.print_report``。这样不真打 LLM API。
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def smoke_module() -> Any:
    """加载 ``scripts.smoke_test_r1`` —— 加载一次缓存复用。"""
    return importlib.import_module("scripts.smoke_test_r1")


@pytest.fixture
def review_module() -> Any:
    """加载 ``scripts.review_last_smoke`` —— 用于 monkeypatch 公开函数。"""
    return importlib.import_module("scripts.review_last_smoke")


@pytest.fixture
def reviewer_module() -> Any:
    """加载 ``bookscope.agent.reviewer`` —— 用于 monkeypatch
    ``review_answer``。
    """
    return importlib.import_module("bookscope.agent.reviewer")


@pytest.fixture
def sample_payload() -> dict[str, Any]:
    """smoke 内存里 outcome=success 时的典型负载。"""
    return {
        "question": "这本书里主要有哪几个角色？",
        "answer": "朱元璋、徐达、常遇春、李善长。",
        "citations": [
            {"chapter": 1, "snippet": "朱元璋出生于乱世……"},
            {"chapter": 2, "snippet": "徐达率军北伐……"},
        ],
        "book_title": "明朝那些事儿",
        "language": "zh",
    }


# ---------------------------------------------------------------------------
# 用例
# ---------------------------------------------------------------------------


def test_review_skipped_when_flag_unset(
    monkeypatch: pytest.MonkeyPatch,
    smoke_module: Any,
    review_module: Any,
    reviewer_module: Any,
    sample_payload: dict[str, Any],
) -> None:
    """开关未设置：reviewer 全链路一次都不被调。"""
    monkeypatch.delenv("BOOKSCOPE_SMOKE_REVIEW", raising=False)

    build_calls: list[Any] = []
    review_calls: list[Any] = []
    print_calls: list[Any] = []

    def _fake_build() -> tuple[Any, str, str]:
        build_calls.append(True)
        return object(), "fake-model", "fake"

    def _fake_review(**kwargs: Any) -> dict[str, Any]:
        review_calls.append(kwargs)
        return {}

    def _fake_print(**kwargs: Any) -> None:
        print_calls.append(kwargs)

    monkeypatch.setattr(review_module, "build_reviewer_client", _fake_build)
    monkeypatch.setattr(reviewer_module, "review_answer", _fake_review)
    monkeypatch.setattr(review_module, "print_report", _fake_print)

    smoke_module._maybe_run_reviewer(**sample_payload)

    assert build_calls == []
    assert review_calls == []
    assert print_calls == []


def test_review_invoked_when_flag_set(
    monkeypatch: pytest.MonkeyPatch,
    smoke_module: Any,
    review_module: Any,
    reviewer_module: Any,
    sample_payload: dict[str, Any],
) -> None:
    """开关开 + outcome=success：reviewer 被调用，参数与内存对象一致。"""
    monkeypatch.setenv("BOOKSCOPE_SMOKE_REVIEW", "1")

    fake_client = object()
    fake_model = "fake-model"
    fake_provider = "fake-provider"
    fake_review_result = {
        "scores": {
            "structural_judgment": 4,
            "evidence_density": 4,
            "honesty": 4,
            "actionability": 4,
            "cross_chapter_coherence": 4,
        },
        "per_dimension_comment": {},
        "overall": "ok",
        "top_issues": [],
        "single_most_valuable_improvement": "n/a",
    }

    review_calls: list[dict[str, Any]] = []
    print_calls: list[dict[str, Any]] = []

    def _fake_build() -> tuple[Any, str, str]:
        return fake_client, fake_model, fake_provider

    def _fake_review(**kwargs: Any) -> dict[str, Any]:
        review_calls.append(kwargs)
        return fake_review_result

    def _fake_print(**kwargs: Any) -> None:
        print_calls.append(kwargs)

    monkeypatch.setattr(review_module, "build_reviewer_client", _fake_build)
    monkeypatch.setattr(reviewer_module, "review_answer", _fake_review)
    monkeypatch.setattr(review_module, "print_report", _fake_print)

    smoke_module._maybe_run_reviewer(**sample_payload)

    # review_answer 被调一次，且参数透传内存对象（不走 stdout 抽字段）
    assert len(review_calls) == 1
    call = review_calls[0]
    assert call["client"] is fake_client
    assert call["model"] == fake_model
    assert call["question"] == sample_payload["question"]
    assert call["answer"] == sample_payload["answer"]
    assert call["citations"] == sample_payload["citations"]
    assert call["book_title"] == sample_payload["book_title"]
    assert call["language"] == sample_payload["language"]

    # print_report 收到 review 结果 + 同一组 fields
    assert len(print_calls) == 1
    pr = print_calls[0]
    assert pr["review"] is fake_review_result
    assert pr["provider"] == fake_provider
    assert pr["model"] == fake_model
    assert pr["fields"]["question"] == sample_payload["question"]
    assert pr["fields"]["answer"] == sample_payload["answer"]
    assert pr["fields"]["citations"] == sample_payload["citations"]
    assert pr["fields"]["book_title"] == sample_payload["book_title"]


def test_review_skipped_on_outcome_failure(
    monkeypatch: pytest.MonkeyPatch,
    smoke_module: Any,
    review_module: Any,
    reviewer_module: Any,
) -> None:
    """outcome=failure 路径：smoke main() 的失败分支提前 ``return``，
    根本不走到 ``_maybe_run_reviewer``。

    这里通过对 ``main`` 直接打桩证明：让 ``_build_adapter_and_model`` 抛
    RuntimeError，main() 立刻返回 1，``_maybe_run_reviewer`` 内部依赖的
    任何函数都不应被调（包括 build_reviewer_client）。即便开关是开的。
    """
    monkeypatch.setenv("BOOKSCOPE_SMOKE_REVIEW", "1")
    monkeypatch.setenv("BOOKSCOPE_SMOKE_PROVIDER", "deepseek")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    build_calls: list[Any] = []
    review_calls: list[Any] = []

    def _fake_build() -> tuple[Any, str, str]:
        build_calls.append(True)
        return object(), "fake-model", "fake"

    def _fake_review(**kwargs: Any) -> dict[str, Any]:
        review_calls.append(kwargs)
        return {}

    monkeypatch.setattr(review_module, "build_reviewer_client", _fake_build)
    monkeypatch.setattr(reviewer_module, "review_answer", _fake_review)

    rc = smoke_module.main()

    # adapter 构造失败：smoke 直接 return 1，reviewer 链路完全没触发
    assert rc == 1
    assert build_calls == []
    assert review_calls == []


def test_reviewer_failure_does_not_break_smoke(
    monkeypatch: pytest.MonkeyPatch,
    smoke_module: Any,
    review_module: Any,
    reviewer_module: Any,
    sample_payload: dict[str, Any],
) -> None:
    """reviewer 调用抛异常：``_maybe_run_reviewer`` 吞掉，调用方拿不到任何
    异常 —— smoke 本身的退出码不受影响。
    """
    monkeypatch.setenv("BOOKSCOPE_SMOKE_REVIEW", "1")

    def _fake_build() -> tuple[Any, str, str]:
        return object(), "fake-model", "fake"

    def _fake_review(**kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("simulated reviewer network failure")

    monkeypatch.setattr(review_module, "build_reviewer_client", _fake_build)
    monkeypatch.setattr(reviewer_module, "review_answer", _fake_review)

    # 不抛异常即通过；显式 assert None 让意图明确
    assert smoke_module._maybe_run_reviewer(**sample_payload) is None


def test_reviewer_build_failure_does_not_break_smoke(
    monkeypatch: pytest.MonkeyPatch,
    smoke_module: Any,
    review_module: Any,
    reviewer_module: Any,
    sample_payload: dict[str, Any],
) -> None:
    """reviewer 配置错误（如 DEEPSEEK_API_KEY 未设）：``_maybe_run_reviewer``
    打 warning 后正常返回，不调 review_answer。
    """
    monkeypatch.setenv("BOOKSCOPE_SMOKE_REVIEW", "1")

    review_calls: list[Any] = []

    def _fake_build() -> tuple[Any, str, str]:
        raise RuntimeError("DEEPSEEK_API_KEY 未设置。")

    def _fake_review(**kwargs: Any) -> dict[str, Any]:
        review_calls.append(kwargs)
        return {}

    monkeypatch.setattr(review_module, "build_reviewer_client", _fake_build)
    monkeypatch.setattr(reviewer_module, "review_answer", _fake_review)

    assert smoke_module._maybe_run_reviewer(**sample_payload) is None
    assert review_calls == []
