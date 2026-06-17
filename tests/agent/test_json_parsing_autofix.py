"""exp004 两类 reviewer JSON 翻车的 autofix 回归测试。

起源：exp004 跨题材验收（docs/internal/experiments/004-cross-genre-stability.md §9.3）
实跑发现两题纯解析损失——分都打出来了（22 分），JSON 没写对：

- anshi run3 q1：``per_dimension_comment`` 最后一个键值对后多个逗号
  （trailing comma），严格 parse 失败，原 autofix 链全不命中
- zhinei run2 q5：``top_issues`` 第二条用全角 ``”`` 收尾，string 没闭合，
  ``extract_first_json_object`` 引号平衡跑乱、整段定位失败

两题的真实 raw 文本固化在 ``tests/fixtures/exp004_*_reviewer_raw.txt``
（从 ``docs/internal/experiments/data/exp004-*.json`` 的 ``review._raw_text``
字段逐字拷出），作为端到端复现用例：修后必须解析出 22 分。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bookscope.agent.reviewer import _parse_review_json
from bookscope.agent.utils.json_parsing import (
    autofix_fullwidth_quote_string_closer,
    autofix_trailing_commas,
    parse_final_answer,
)

_FIXTURES = Path(__file__).parent.parent / "fixtures"


def _load_fixture(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 端到端复现：exp004 真实 raw 文本必须解析出 22 分
# ---------------------------------------------------------------------------


def test_exp004_anshi_run3_q1_trailing_comma_recovers_22() -> None:
    """anshi run3 q1 真实 raw（trailing comma）——修后 5 维合计 22。"""
    raw = _load_fixture("exp004_anshi_run3_q1_reviewer_raw.txt")
    obj = _parse_review_json(raw)
    assert sum(obj["scores"].values()) == 22


def test_exp004_zhinei_run2_q5_fullwidth_quote_recovers_22() -> None:
    """zhinei run2 q5 真实 raw（全角引号收尾）——修后 5 维合计 22。"""
    raw = _load_fixture("exp004_zhinei_run2_q5_reviewer_raw.txt")
    obj = _parse_review_json(raw)
    assert sum(obj["scores"].values()) == 22
    # 全角引号那条 top_issue 的文本要回收完整，不能丢字
    assert any("空口断言" in issue for issue in obj["top_issues"])


# ---------------------------------------------------------------------------
# autofix_trailing_commas 单元测试
# ---------------------------------------------------------------------------


def test_trailing_comma_before_object_close() -> None:
    fixed = autofix_trailing_commas('{"a": 1, "b": 2,}')
    assert fixed == '{"a": 1, "b": 2}'


def test_trailing_comma_before_array_close() -> None:
    fixed = autofix_trailing_commas('{"items": ["x", "y",]}')
    assert fixed == '{"items": ["x", "y"]}'


def test_trailing_comma_across_newline_and_indent() -> None:
    # anshi q1 的真实形态：`,` 和 `}` 隔着换行 + 缩进
    broken = '{\n  "a": "文本。",\n}'
    fixed = autofix_trailing_commas(broken)
    assert fixed == '{\n  "a": "文本。"\n}'


def test_trailing_comma_inside_string_untouched() -> None:
    # string value 里的 `,}` 字面量不是 trailing comma
    text = '{"a": "句末是,}", "b": 1}'
    assert autofix_trailing_commas(text) is None


def test_trailing_comma_none_when_clean() -> None:
    assert autofix_trailing_commas('{"a": 1, "b": [2, 3]}') is None


def test_trailing_comma_multiple_occurrences() -> None:
    fixed = autofix_trailing_commas('{"a": [1, 2,], "b": {"c": 3,},}')
    assert fixed == '{"a": [1, 2], "b": {"c": 3}}'


# ---------------------------------------------------------------------------
# autofix_fullwidth_quote_string_closer 单元测试
# ---------------------------------------------------------------------------


def test_fullwidth_closer_before_array_close() -> None:
    # zhinei q5 的真实形态：`”` 收尾 + 换行 + 缩进 + `]`
    broken = '{"items": [\n  "第一条",\n  "第二条。”\n]}'
    fixed = autofix_fullwidth_quote_string_closer(broken)
    assert fixed == '{"items": [\n  "第一条",\n  "第二条。"\n]}'


def test_fullwidth_closer_before_comma() -> None:
    broken = '{"a": "文本”, "b": 1}'
    fixed = autofix_fullwidth_quote_string_closer(broken)
    assert fixed == '{"a": "文本", "b": 1}'


def test_fullwidth_quotes_inside_closed_string_untouched() -> None:
    # 正常成对的 “...” 后面跟真收束符 `"`，不在结构符位置，不动
    text = '{"a": "他说：“好。”", "b": 1}'
    assert autofix_fullwidth_quote_string_closer(text) is None


def test_fullwidth_none_when_absent() -> None:
    assert autofix_fullwidth_quote_string_closer('{"a": 1}') is None


# ---------------------------------------------------------------------------
# parse_final_answer 链路：loop 侧同病同治
# ---------------------------------------------------------------------------


def test_parse_final_answer_recovers_trailing_comma() -> None:
    broken = (
        '{"answer": "回答正文。",'
        ' "citations": [{"chapter": 3, "snippet": "原文片段",},]}'
    )
    answer, citations = parse_final_answer(broken)
    assert answer == "回答正文。"
    assert citations[0]["chapter"] == 3


def test_parse_final_answer_recovers_fullwidth_closer() -> None:
    broken = (
        '{"answer": "回答正文。”,'
        ' "citations": [{"chapter": 3, "snippet": "原文片段"}]}'
    )
    answer, citations = parse_final_answer(broken)
    assert answer == "回答正文。"
    assert len(citations) == 1


def test_parse_final_answer_still_rejects_garbage() -> None:
    from bookscope.agent.errors import LLMFormatError

    with pytest.raises(LLMFormatError):
        parse_final_answer("not json at all")


# ---------------------------------------------------------------------------
# parse_final_answer lenient 模式（长上下文路；WP-token-budget Phase 2）
# ---------------------------------------------------------------------------


def test_lenient_coerces_string_chapter() -> None:
    # flash 把章号写成 "第5章" / "12" → 强转成 int
    out = (
        '{"answer": "结论。", "citations": ['
        '{"chapter": "第5章", "snippet": "片段甲"},'
        '{"chapter": "12", "snippet": "片段乙"}]}'
    )
    answer, citations = parse_final_answer(out, lenient=True)
    assert answer == "结论。"
    assert citations[0]["chapter"] == 5
    assert citations[1]["chapter"] == 12


def test_lenient_missing_chapter_defaults_zero() -> None:
    out = '{"answer": "a", "citations": [{"snippet": "片段"}]}'
    _, citations = parse_final_answer(out, lenient=True)
    assert citations[0]["chapter"] == 0


def test_lenient_drops_bad_citation_keeps_good() -> None:
    # 一条缺 snippet（无证据 → 丢），一条好的（留）
    out = (
        '{"answer": "a", "citations": ['
        '{"chapter": 1},'
        '{"chapter": 2, "snippet": "好片段"}]}'
    )
    _, citations = parse_final_answer(out, lenient=True)
    assert len(citations) == 1
    assert citations[0]["snippet"] == "好片段"


def test_lenient_missing_citations_key_raises() -> None:
    # citations 整个缺失 → 宽松也得失败（触发重试/回退），不能无证据放行
    from bookscope.agent.errors import LLMFormatError

    with pytest.raises(LLMFormatError):
        parse_final_answer('{"answer": "无引用的答案"}', lenient=True)


def test_strict_still_rejects_string_chapter() -> None:
    # 回归：strict（默认）路径行为不变，字符串章号照样拒
    from bookscope.agent.errors import LLMFormatError

    out = '{"answer": "a", "citations": [{"chapter": "5", "snippet": "片段"}]}'
    with pytest.raises(LLMFormatError):
        parse_final_answer(out)
