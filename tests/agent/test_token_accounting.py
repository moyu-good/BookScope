"""WP-agent-token-budget Phase 1 · per-tool 体量计量的单元测试。

只测纯函数 ``measure_output_size`` 的契约：它要能把"灌进上下文的新原文体量"
量出来，并且让 get_chapter_range 这类整章 full_text 的肥源明显大于 search 的
单条 chunk——这是 Phase 1 归因 miss 构成的地基。
"""

from __future__ import annotations

import json

from bookscope.agent._internal.loop_shared import measure_output_size


def test_chars_matches_serialised_length():
    output = {"chapter": 3, "full_text": "唐玄宗天宝年间，安禄山起兵范阳。"}
    expected_chars = len(json.dumps(output, ensure_ascii=False, default=str))
    chars, tokens_est = measure_output_size(output)
    assert chars == expected_chars
    assert tokens_est > 0


def test_cjk_weighted_higher_than_ascii_same_length():
    cjk = measure_output_size("一" * 100)[1]
    ascii_ = measure_output_size("a" * 100)[1]
    assert cjk > ascii_  # 中文按 ~0.6/字、ASCII 按 ~0.3/字


def test_chapter_range_dwarfs_single_chunk():
    # 头号肥源嫌疑：整章 full_text 远大于一条 search chunk
    chapter = {"chapter": 5, "full_text": "安史之乱。" * 800}
    chunk = [{"chunk_id": "c1", "text": "安史之乱。" * 60}]
    assert measure_output_size(chapter)[1] > measure_output_size(chunk)[1]


def test_non_serialisable_falls_back_to_str():
    class Weird:
        pass

    chars, tokens_est = measure_output_size({"x": Weird()})
    assert chars > 0
    assert tokens_est >= 0  # default=str 兜底，不抛异常
