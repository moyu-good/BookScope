"""``bookscope.agent.citation_check`` 单测（WP1 citation 可信链）。

设计稿：``docs/internal/design/WP1-citation-trust-chain.md``。覆盖：

1. ``normalize_text`` —— 去空白 + 全半角标点归一
2. ``char_ngram_containment`` —— 含比例计算与边界
3. ``verify_citations`` —— 精确命中 / 轻改写过阈值 / 编造不命中 /
   空登记表 / 全半角混排 / 阈值边界 / 原有字段不动
"""

from __future__ import annotations

from bookscope.agent.citation_check import (
    CONTAINMENT_THRESHOLD,
    char_ngram_containment,
    normalize_text,
    verify_citations,
)

# ---------------------------------------------------------------------------
# normalize_text
# ---------------------------------------------------------------------------


class TestNormalizeText:
    def test_removes_all_whitespace(self) -> None:
        assert normalize_text("朱 元 璋\t出身\n贫寒") == "朱元璋出身贫寒"

    def test_fullwidth_punctuation_to_halfwidth(self) -> None:
        assert normalize_text("出身贫寒，做过和尚。") == "出身贫寒,做过和尚."
        assert normalize_text("（一三六八年）！？；：") == "(一三六八年)!?;:"

    def test_cjk_quotes_to_ascii(self) -> None:
        assert normalize_text("“高筑墙”‘缓称王’") == (
            '"高筑墙"' + "'缓称王'"
        )

    def test_empty_string(self) -> None:
        assert normalize_text("") == ""

    def test_mixed_width_equivalence(self) -> None:
        """全角写法与半角写法归一化后相等——比对不受标点宽度影响。"""
        assert normalize_text("洪武元年，定都南京。") == normalize_text(
            "洪武元年,定都南京."
        )


# ---------------------------------------------------------------------------
# char_ngram_containment
# ---------------------------------------------------------------------------


class TestCharNgramContainment:
    def test_identical_returns_one(self) -> None:
        assert char_ngram_containment("朱元璋建立明朝", "朱元璋建立明朝") == 1.0

    def test_substring_returns_one(self) -> None:
        assert char_ngram_containment("建立明朝", "朱元璋于一三六八年建立明朝政权") == 1.0

    def test_disjoint_returns_zero(self) -> None:
        assert char_ngram_containment("abcdef", "xyzuvw") == 0.0

    def test_needle_shorter_than_n_returns_zero(self) -> None:
        assert char_ngram_containment("ab", "abcdef") == 0.0

    def test_haystack_shorter_than_n_returns_zero(self) -> None:
        assert char_ngram_containment("abcdef", "ab") == 0.0

    def test_partial_overlap_exact_fraction(self) -> None:
        """needle 12 字 10 个 3-gram，前 8 字在 haystack → 6/10 = 0.6。"""
        needle = "abcdefghijkl"  # 3-gram: abc..jkl 共 10 个
        haystack = "abcdefgh0123456789"  # 命中 abc bcd cde def efg fgh 共 6 个
        assert char_ngram_containment(needle, haystack) == 0.6


# ---------------------------------------------------------------------------
# verify_citations
# ---------------------------------------------------------------------------

_EVIDENCE = {
    "r0-chunk-7": {
        "chapter": 7,
        "text": (
            "朱元璋出身贫寒，幼年做过放牛娃，后来入皇觉寺为僧。"
            "至正十二年投奔郭子兴的红巾军，从此踏上征途。"
        ),
    },
    "chapter-3": {
        "chapter": 3,
        "text": "陈友谅率六十万大军顺江而下，鄱阳湖一战定天下归属。",
    },
}


class TestVerifyCitations:
    def test_exact_hit_verified_with_score_one(self) -> None:
        citations = [{"chapter": 7, "snippet": "幼年做过放牛娃，后来入皇觉寺为僧。"}]
        out = verify_citations(citations, _EVIDENCE)
        assert out[0]["verified"] is True
        assert out[0]["chunk_id"] == "r0-chunk-7"
        assert out[0]["match_score"] == 1.0
        assert out[0]["match_type"] == "quote"  # 逐字命中

    def test_light_paraphrase_passes_threshold(self) -> None:
        """同义轻改写（个别词替换）3-gram containment 应过 0.6。"""
        # 原文"至正十二年投奔郭子兴的红巾军，从此踏上征途"
        # 改写：投奔→加入，征途→道路——大部分 3-gram 仍命中
        citations = [
            {"chapter": 7, "snippet": "至正十二年加入郭子兴的红巾军，从此踏上道路"}
        ]
        out = verify_citations(citations, _EVIDENCE)
        assert out[0]["verified"] is True
        assert out[0]["chunk_id"] == "r0-chunk-7"
        assert CONTAINMENT_THRESHOLD <= out[0]["match_score"] < 1.0
        assert out[0]["match_type"] == "paraphrase"  # 过阈值但非逐字

    def test_fabricated_snippet_not_verified(self) -> None:
        citations = [
            {"chapter": 7, "snippet": "刘伯温夜观天象，断言金陵有王气，劝主公早定大计。"}
        ]
        out = verify_citations(citations, _EVIDENCE)
        assert out[0]["verified"] is False
        assert out[0]["chunk_id"] is None
        assert out[0]["match_score"] < CONTAINMENT_THRESHOLD
        assert out[0]["match_type"] == "none"  # 未核验

    def test_empty_evidence_not_verified(self) -> None:
        citations = [{"chapter": 1, "snippet": "朱元璋出身贫寒"}]
        out = verify_citations(citations, {})
        assert out[0]["verified"] is False
        assert out[0]["chunk_id"] is None
        assert out[0]["match_score"] == 0.0

    def test_empty_snippet_not_verified(self) -> None:
        citations = [{"chapter": 1, "snippet": ""}]
        out = verify_citations(citations, _EVIDENCE)
        assert out[0]["verified"] is False
        assert out[0]["chunk_id"] is None

    def test_mixed_width_punctuation_exact_hit(self) -> None:
        """LLM 引用时把全角标点换成半角、加空格——归一化后仍精确命中。"""
        citations = [
            {"chapter": 3, "snippet": "陈友谅率六十万大军顺江而下, 鄱阳湖一战定天下归属."}
        ]
        out = verify_citations(citations, _EVIDENCE)
        assert out[0]["verified"] is True
        assert out[0]["chunk_id"] == "chapter-3"
        assert out[0]["match_score"] == 1.0

    def test_threshold_boundary_exactly_at_threshold_verified(self) -> None:
        """containment 恰为 0.6 时 verified=True（≥ 含等号）。"""
        evidence = {"c1": {"chapter": 1, "text": "abcdefgh0123456789"}}
        citations = [{"chapter": 1, "snippet": "abcdefghijkl"}]  # 6/10 = 0.6
        out = verify_citations(citations, evidence)
        assert out[0]["match_score"] == 0.6
        assert out[0]["verified"] is True
        assert out[0]["chunk_id"] == "c1"

    def test_threshold_boundary_just_below_not_verified(self) -> None:
        """containment 低于 0.6（5/10 = 0.5）时 verified=False。"""
        evidence = {"c1": {"chapter": 1, "text": "abcdefg0123456789"}}  # 命中 5 个
        citations = [{"chapter": 1, "snippet": "abcdefghijkl"}]
        out = verify_citations(citations, evidence)
        assert out[0]["match_score"] == 0.5
        assert out[0]["verified"] is False
        assert out[0]["chunk_id"] is None

    def test_original_fields_untouched(self) -> None:
        """原有字段（chapter / snippet / 任意附加字段）一律不动。"""
        citations = [
            {
                "chapter": 7,
                "snippet": "朱元璋出身贫寒",
                "auto_filled": True,
            }
        ]
        out = verify_citations(citations, _EVIDENCE)
        assert out[0]["chapter"] == 7
        assert out[0]["snippet"] == "朱元璋出身贫寒"
        assert out[0]["auto_filled"] is True
        assert out[0]["verified"] is True

    def test_best_match_chunk_id_picked_across_chunks(self) -> None:
        """多个登记 chunk 时填的是 containment 最大的那个。"""
        citations = [{"chapter": 3, "snippet": "鄱阳湖一战定天下"}]
        out = verify_citations(citations, _EVIDENCE)
        assert out[0]["verified"] is True
        assert out[0]["chunk_id"] == "chapter-3"

    def test_match_score_rounded_to_two_decimals(self) -> None:
        citations = [
            {"chapter": 7, "snippet": "至正十二年加入郭子兴的红巾军，从此踏上道路"}
        ]
        out = verify_citations(citations, _EVIDENCE)
        score = out[0]["match_score"]
        assert score == round(score, 2)
