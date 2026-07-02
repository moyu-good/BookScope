"""公文条款四态分类 classify_policy_clause 单测(#41 方针三态)。

WP-redhead-substance-vs-slogan §八:「方针类 + 三空」大桶再劈 signal / direction / slogan,
桶外算 substantive。全 deterministic(不调 LLM、不加阈值),判据建在现成信号上
(instruction_type + 三空 + detect_nuances 串匹配 + substance)。
"""

from __future__ import annotations

from bookscope.agent.redhead_codebook import (
    classify_policy_clause,
    clause_is_pure_statement,
)


def _clause(**kw: object) -> dict[str, object]:
    """默认是「方针部署 + 三空 + 空头倡导 + 无 marker 原文」= policy_slogan 底子,按需覆盖。"""
    base: dict[str, object] = {
        "instruction_type": "方针部署",
        "actor": "",
        "deadline": "",
        "penalty": "",
        "substance": "空头倡导",
        "evidence": "坚持以人民为中心的发展思想。",  # 无 nuance marker
    }
    base.update(kw)
    return base


# ── 出桶 = substantive(有可执行内核,三空硬门槛任一破即出桶）──────────────────
def test_substantive_when_has_actor_or_deadline_or_penalty() -> None:
    assert classify_policy_clause(_clause(actor="财政部")) == "substantive"
    assert classify_policy_clause(_clause(deadline="2024年6月底前")) == "substantive"
    assert classify_policy_clause(_clause(penalty="予以通报问责")) == "substantive"


def test_substantive_when_not_policy_type() -> None:
    # 非「方针部署」→ 不进桶 → 实质(哪怕三空)
    assert classify_policy_clause(_clause(instruction_type="硬要求")) == "substantive"


# ── 桶内三态 ─────────────────────────────────────────────────────────────────
def test_policy_signal_when_nuance_marker_hit() -> None:
    # 方针类 + 三空 且 原文命中弦外 marker（「结合实际」）→ 信号
    c = _clause(evidence="各地要结合实际探索可行路径。")
    assert classify_policy_clause(c) == "policy_signal"


def test_policy_direction_conditional_no_marker() -> None:
    # 方针类 + 三空 + 无 marker + 有条件兑现 → 半信号
    c = _clause(substance="有条件兑现", evidence="完善配套工作机制。")
    assert classify_policy_clause(c) == "policy_direction"


def test_policy_slogan_empty_no_marker() -> None:
    # 方针类 + 三空 + 无 marker + 空头倡导 → 纯口号废话
    assert classify_policy_clause(_clause()) == "policy_slogan"


# ── 边界 ─────────────────────────────────────────────────────────────────────
def test_signal_beats_substance_when_marker_present() -> None:
    # 即便 substance=空头倡导,只要命中 marker(「结合实际」)就是 signal，不是 slogan——有信号优先
    c = _clause(substance="空头倡导", evidence="各地结合实际制定具体办法。")
    assert classify_policy_clause(c) == "policy_signal"


def test_real_money_three_empty_defaults_direction_not_slogan() -> None:
    # 真金白银 + 三空 是矛盾组合(真金白银本需主体/时限/罚则),不命中 slogan 的空头倡导条件
    # → 落 direction(中性),绝不误判成废话
    c = _clause(substance="真金白银", evidence="完善配套工作机制。")
    assert classify_policy_clause(c) == "policy_direction"


# ── clause_is_pure_statement 薄包装 = policy_slogan（语义收窄）──────────────────
def test_pure_statement_wrapper_is_slogan_only() -> None:
    assert clause_is_pure_statement(_clause()) is True  # slogan
    # 带 marker 的（signal）不再算 pure_statement（旧逻辑会误判 True）
    assert clause_is_pure_statement(_clause(evidence="各地结合实际制定具体办法。")) is False
    # 有条件兑现（direction）也不是 slogan
    assert clause_is_pure_statement(_clause(substance="有条件兑现")) is False
    # 实质不是 slogan
    assert clause_is_pure_statement(_clause(actor="财政部")) is False
