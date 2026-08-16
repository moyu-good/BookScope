"""书×书对照（bookscope.agent.book_cross）单元测试。

覆盖：章脉压缩、锚定校验（nodes/edges 过滤）、报告契约组装、空输入边界。
纯本地，不调 LLM。
"""

import unittest

from bookscope.agent.book_cross import (
    RELATIONS,
    _compact_spine,
    _sanitize_reason,
    build_cross_book_report_input,
)
from bookscope.report.service import validate_input


class TestCompactSpine(unittest.TestCase):
    def test_compacts_events_and_claims(self):
        spine = [
            {"chapter": 1, "events": ["主角登场", "遇险"], "claims": ["设定：乱世"]},
            {"chapter": 2, "events": [], "claims": ["伏笔回收"], "mainline": False},
        ]
        out = _compact_spine(spine)
        assert "第1章" in out and "主角登场" in out and "伏笔回收" in out
        assert out.index("第1章") < out.index("第2章")  # 按章序

    def test_empty_spine(self):
        assert _compact_spine([]) == ""


class TestSanitizeReason(unittest.TestCase):
    PERSPECTIVES = [
        {"title": "A", "slug": "a", "stance": "x", "summary": "s", "claims": []},
        {"title": "B", "slug": "b", "stance": "y", "summary": "t", "claims": []},
    ]

    def test_drops_bad_slugs_and_relations(self):
        data = {
            "nodes": [
                {"slug": "a", "label": "A"},
                {"slug": "b", "label": "B"},
                {"slug": "ghost", "label": "G"},  # 不在输入 → 丢
            ],
            "edges": [
                {"from": "a", "to": "b", "relation": "继承", "rationale": "ok"},
                {"from": "a", "to": "ghost", "relation": "反驳", "rationale": "to 不存在 → 丢"},
                {"from": "a", "to": "b", "relation": "点赞", "rationale": "关系类型非法 → 丢"},
            ],
            "concept_evolution": [],
            "disagreements": [],
            "narrative": "n",
        }
        out = _sanitize_reason(data, self.PERSPECTIVES)
        assert [n["slug"] for n in out["nodes"]] == ["a", "b"]
        assert len(out["edges"]) == 1
        assert out["edges"][0]["relation"] == "继承"

    def test_all_bad_returns_empty_edges(self):
        data = {"nodes": [], "edges": [{"from": "x", "to": "y", "relation": "继承"}],
                "concept_evolution": [], "disagreements": [], "narrative": ""}
        out = _sanitize_reason(data, self.PERSPECTIVES)
        assert out["edges"] == []


class TestBuildReportInput(unittest.TestCase):
    def test_contract_valid_and_spines_mapped(self):
        perspectives = [
            {"title": "书A", "slug": "a", "summary": "A的主旨", "stance": "现实主义",
             "claims": [{"claim": "主张一", "chapter": 3, "kind": "主题"}]},
            {"title": "书B", "slug": "b", "summary": "B的主旨", "stance": "批判",
             "claims": [{"claim": "主张二", "chapter": 7, "kind": "方法"}]},
        ]
        reason = {
            "nodes": [
                {"slug": "a", "label": "书A", "stance": "现实主义"},
                {"slug": "b", "label": "书B", "stance": "批判"},
            ],
            "edges": [{"from": "a", "to": "b", "relation": "补充", "rationale": "B 补充 A"}],
            "concept_evolution": [{"concept": "X", "stages": []}],
            "disagreements": [],
            "narrative": "对照叙事",
        }
        inp = build_cross_book_report_input(
            perspectives=perspectives, reason=reason,
            meta={"title": "对照报告", "seal": "书 鉴", "nav_title": "对照", "unit_label": "份", "generated_by": "单测"},
        )
        assert inp["layout"] == "crossdoc"
        assert len(inp["spines"]) == 2
        assert inp["spines"]["a"]["core_thesis"] == "A的主旨"
        # 跨文本关系是研判：引文核验全 False
        assert inp["e1"]["a"]["quotes"][0]["verified"] is False
        assert validate_input(inp) == []

    def test_empty_perspectives(self):
        inp = build_cross_book_report_input(
            perspectives=[], reason={"nodes": [], "edges": [], "concept_evolution": [], "disagreements": [], "narrative": ""},
            meta={"title": "t", "seal": "书 鉴", "nav_title": "n", "unit_label": "份", "generated_by": "g"},
        )
        assert validate_input(inp) == []


if __name__ == "__main__":
    unittest.main()
