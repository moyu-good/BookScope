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


# ---------------------------------------------------------------------------
# verify_citations —— 多命中消歧（自报章号弱先验 tie-break）
# ---------------------------------------------------------------------------

# 同一句在两章逐字复现——母题回环 / 伏笔回收 / 同名不同事的典型形态。
# 旧实现取字典首个（ch2），probe 实测这类锚错率 60%；消歧后用自报章号选对的那章。
_DUP_EVIDENCE = {
    "ch2": {
        "chapter": 2,
        "text": "话说天下大势，分久必合，合久必分，此乃古今不易之理。",
    },
    "ch8": {
        "chapter": 8,
        "text": "孔明叹曰：天下大势，分久必合，合久必分，今又当分矣。",
    },
}

_DUP_SNIPPET = "天下大势，分久必合，合久必分"  # 两章都逐字含


class TestVerifyCitationsDisambiguation:
    def test_multi_exact_picks_chunk_matching_self_chapter(self) -> None:
        """同句两章逐字命中：自报第 8 章 → 锚 ch8（旧实现会锚字典首个 ch2）。"""
        citations = [{"chapter": 8, "snippet": _DUP_SNIPPET}]
        out = verify_citations(citations, _DUP_EVIDENCE)
        assert out[0]["verified"] is True
        assert out[0]["chunk_id"] == "ch8"
        assert out[0]["match_score"] == 1.0
        assert out[0]["match_type"] == "quote"

    def test_multi_exact_self_chapter_other_side(self) -> None:
        """对称验证：自报第 2 章 → 锚 ch2。"""
        out = verify_citations([{"chapter": 2, "snippet": _DUP_SNIPPET}], _DUP_EVIDENCE)
        assert out[0]["chunk_id"] == "ch2"

    def test_multi_exact_nearest_chapter_when_no_exact(self) -> None:
        """自报章号谁都不等于 → 取最近：自报 7 → |2-7|=5 vs |8-7|=1 → ch8。"""
        out = verify_citations([{"chapter": 7, "snippet": _DUP_SNIPPET}], _DUP_EVIDENCE)
        assert out[0]["chunk_id"] == "ch8"

    def test_multi_exact_no_prior_falls_back_to_first(self) -> None:
        """不传 chapter（无先验）→ 退回确定性首个 ch2，与旧实现一致（向后兼容）。"""
        out = verify_citations([{"snippet": _DUP_SNIPPET}], _DUP_EVIDENCE)
        assert out[0]["verified"] is True
        assert out[0]["chunk_id"] == "ch2"
        assert out[0]["match_type"] == "quote"

    def test_multi_exact_non_int_chapter_falls_back_to_first(self) -> None:
        """chapter 非整数（None）→ 当无先验，退回首个。"""
        out = verify_citations([{"chapter": None, "snippet": _DUP_SNIPPET}], _DUP_EVIDENCE)
        assert out[0]["chunk_id"] == "ch2"

    def test_single_exact_chapter_prior_does_not_misfire(self) -> None:
        """单一命中时章号先验不改变结果（消歧只在多命中时起作用）。"""
        # 整句只在 ch2 完整出现，自报一个不存在的章号也不该乱锚
        citations = [
            {"chapter": 99, "snippet": "话说天下大势，分久必合，合久必分，此乃古今不易之理。"}
        ]
        out = verify_citations(citations, _DUP_EVIDENCE)
        assert out[0]["chunk_id"] == "ch2"
        assert out[0]["verified"] is True


# ---------------------------------------------------------------------------
# verify_citations —— 宽松二次核验（繁简 / 引号 / 省略号 / 超短 的召回补齐）
# ---------------------------------------------------------------------------

# 登记原文一律简体（epub 正文形态）。下面各条 snippet 用繁体 / 带引号 / 省略号拼接 /
# 超短——都是 exp022 实测里被主比对误判成 none 的真原文形态。宽松二次核验要把它们捞回，
# 同时不相干 / 掺假的绝不放进来。
_LOOSE_EVIDENCE = {
    "c1": {"chapter": 1, "text": "官渡一战，曹操大破袁绍百万之众，自此雄踞北方，威震天下。"},
    "c2": {"chapter": 5, "text": "天子册封曹操为魏王，加九锡，赞拜不名，入朝不趋。"},
    "c3": {"chapter": 9, "text": "关羽大意失荆州，兵败之后，望麦城而走，终为孙权所擒。"},
    "c4": {"chapter": 2, "text": "龙腾虎跃凤鸣朝阳国运昌隆四海归心万民欢腾。"},
}


def _strict_would_miss(snippet: str) -> bool:
    """主比对（逐字子串 + 0.6 containment，不折繁简、不去引号）一定核不上。

    用它在每条测试里坐实"是宽松通路把这条捞回来的"，而不是碰巧过了主比对——否则测试
    看似过了，其实没在考宽松逻辑。
    """
    ns = normalize_text(snippet)
    for entry in _LOOSE_EVIDENCE.values():
        nt = normalize_text(entry["text"])
        if ns and nt and ns in nt:
            return False
        if char_ngram_containment(ns, nt) >= CONTAINMENT_THRESHOLD:
            return False
    return True


class TestVerifyCitationsLoosePass:
    """主比对判 none 后的宽松二次核验：召回上去、精度不丢。"""

    def test_traditional_variant_verifies_as_quote(self) -> None:
        """繁体引原文（epub 是简体）：折简体后逐字命中 → quote。"""
        snip = "官渡一戰，曹操大破袁紹百萬之眾"
        assert _strict_would_miss(snip)
        out = verify_citations([{"chapter": 1, "snippet": snip}], _LOOSE_EVIDENCE)
        assert out[0]["verified"] is True
        assert out[0]["chunk_id"] == "c1"
        assert out[0]["match_type"] == "quote"
        assert out[0]["match_score"] == 1.0

    def test_added_quotes_around_term_verifies(self) -> None:
        """原文「魏王」被 LLM 引成带单引号 '魏王'：去引号后逐字命中 → quote。"""
        snip = "'魏王'"
        assert _strict_would_miss(snip)
        out = verify_citations([{"chapter": 5, "snippet": snip}], _LOOSE_EVIDENCE)
        assert out[0]["verified"] is True
        assert out[0]["chunk_id"] == "c2"
        assert out[0]["match_type"] == "quote"
        assert out[0]["match_score"] == 1.0

    def test_super_short_traditional_verifies(self) -> None:
        """超短片段（5 字）带一处繁体差异（麥→麦）：折简体后逐字命中 → quote。"""
        snip = "望麥城而走"
        assert _strict_would_miss(snip)
        out = verify_citations([{"chapter": 9, "snippet": snip}], _LOOSE_EVIDENCE)
        assert out[0]["verified"] is True
        assert out[0]["chunk_id"] == "c3"
        assert out[0]["match_type"] == "quote"

    def test_ellipsis_spliced_real_fragments_verify(self) -> None:
        """省略号拼接跨段的两句真原话（还都是繁体）：逐段折简体逐字全命中 → quote。"""
        snip = "官渡一戰……冊封曹操為魏王"
        assert _strict_would_miss(snip)
        out = verify_citations([{"chapter": 5, "snippet": snip}], _LOOSE_EVIDENCE)
        assert out[0]["verified"] is True
        assert out[0]["match_type"] == "quote"
        assert out[0]["match_score"] == 1.0
        assert out[0]["chunk_id"] == "c2"  # 锚到最长片段所在 chunk

    def test_loose_containment_rescues_traditional_paraphrase(self) -> None:
        """繁体轻改写（末字 腾→欣）：折简体后 containment 才过 0.6 → paraphrase。"""
        snip = "龍騰虎躍鳳鳴朝陽國運昌隆四海歸心萬民歡欣"
        assert _strict_would_miss(snip)
        out = verify_citations([{"chapter": 2, "snippet": snip}], _LOOSE_EVIDENCE)
        assert out[0]["verified"] is True
        assert out[0]["chunk_id"] == "c4"
        assert out[0]["match_type"] == "paraphrase"
        assert CONTAINMENT_THRESHOLD <= out[0]["match_score"] < 1.0

    # ---- 精度守卫：命根子是提召回不丢精度 ----

    def test_unrelated_simplified_stays_none(self) -> None:
        """编造的简体句：宽松也找不到 → 仍 none。"""
        snip = "刘伯温夜观天象，断言金陵有王气，劝主公早定大计。"
        out = verify_citations([{"chapter": 1, "snippet": snip}], _LOOSE_EVIDENCE)
        assert out[0]["verified"] is False
        assert out[0]["chunk_id"] is None
        assert out[0]["match_type"] == "none"

    def test_unrelated_traditional_stays_none(self) -> None:
        """编造但用繁体写：折简体也找不到，绝不能因放宽繁简而误判成 verified。"""
        snip = "劉伯溫夜觀天象，斷言金陵有王氣，勸主公早定大計。"
        out = verify_citations([{"chapter": 1, "snippet": snip}], _LOOSE_EVIDENCE)
        assert out[0]["verified"] is False
        assert out[0]["match_type"] == "none"

    def test_ellipsis_with_fabricated_fragment_stays_none(self) -> None:
        """前半真、后半编造用省略号拼一起：有一段够长的找不到 → 整条不认。"""
        snip = "官渡一战，曹操大破袁绍百万之众……刘伯温夜观天象断金陵王气"
        out = verify_citations([{"chapter": 1, "snippet": snip}], _LOOSE_EVIDENCE)
        assert out[0]["verified"] is False
        assert out[0]["chunk_id"] is None
        assert out[0]["match_type"] == "none"

    def test_loose_hit_keeps_output_shape_and_original_fields(self) -> None:
        """宽松命中也只附加 4 个标准字段，不引入新字段、原字段不动（8 个消费端契约）。"""
        cit = {"chapter": 1, "snippet": "官渡一戰，曹操大破袁紹百萬之眾", "extra": "keep"}
        out = verify_citations([cit], _LOOSE_EVIDENCE)[0]
        assert out["extra"] == "keep"
        assert out["chapter"] == 1
        assert set(out) == {
            "chapter",
            "snippet",
            "extra",
            "verified",
            "chunk_id",
            "match_score",
            "match_type",
        }
        assert out["match_type"] in {"quote", "paraphrase", "none"}

    def test_disambiguation_flows_through_loose_pass(self) -> None:
        """繁体短语折简体后在两章都逐字命中：自报章号 tie-break 在宽松通路里仍生效。"""
        dup = {
            "a": {"chapter": 2, "text": "话说天下大势分久必合合久必分"},
            "b": {"chapter": 8, "text": "孔明叹曰天下大势合久必分今又当分"},
        }
        snip = "天下大勢"  # 繁体 勢；主比对因 勢≠势 核不上，折简体后两章都含
        assert normalize_text(snip) not in normalize_text(dup["a"]["text"])
        out = verify_citations([{"chapter": 8, "snippet": snip}], dup)
        assert out[0]["verified"] is True
        assert out[0]["chunk_id"] == "b"  # 自报第 8 章 → 锚 b，不取字典首个 a
        assert out[0]["match_type"] == "quote"
