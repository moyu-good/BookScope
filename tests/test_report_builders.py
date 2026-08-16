"""书报告组装器（bookscope.report.builders）单元测试。

覆盖：章脉 → 契约映射（节点/脊/引文核验）、doc 模式渲染（章序流/无关系图/
无概念分歧段）、空输入边界。
"""

import unittest

from bookscope.report.builders import build_book_report
from bookscope.report.service import render_report, validate_input

META = {
    "title": "测试书 · 书鉴报告",
    "subtitle": "3 章 · 章脉已建",
    "seal": "书 鉴",
    "nav_title": "书鉴 · 报告导航",
    "unit_label": "章",
    "generated_by": "单测",
}

SPINE = [
    {"chapter": 1, "title": "开篇", "events": ["主角登场", "遇险"], "claims": ["设定：乱世"],
     "mainline": True, "pov": "主角", "evidence": "第一章原文证据一", "verified": True},
    {"chapter": 2, "title": "转折", "events": ["冲突升级"], "claims": [],
     "mainline": True, "pov": "主角", "evidence": "第二章原文证据二", "verified": False},
    {"chapter": 3, "title": "收束", "events": [], "claims": ["伏笔回收"], "mainline": False,
     "pov": "配角", "evidence": "", "verified": False},
]


class TestBuildBookReport(unittest.TestCase):
    def test_nodes_and_spines_mapped(self):
        inp = build_book_report(SPINE, META)
        assert inp["layout"] == "doc"
        assert len(inp["nodes"]) == 3
        assert inp["nodes"][0]["label"].startswith("第1章")
        assert inp["nodes"][0]["stance"] == "主线"
        assert inp["nodes"][2]["stance"] == "支线"
        assert len(inp["spines"]) == 3
        assert "主角登场" in inp["spines"]["ch1"]["core_thesis"]

    def test_evidence_citations_and_e1(self):
        inp = build_book_report(SPINE, META)
        c1 = inp["spines"]["ch1"]["key_citations"]
        assert c1[0]["quote"] == "第一章原文证据一"
        assert inp["e1"]["ch1"]["quotes"][0]["verified"] is True
        assert inp["e1"]["ch2"]["quotes"][0]["verified"] is False
        # 无证据的章：无引文、E1 空
        assert inp["spines"]["ch3"]["key_citations"] == []
        assert inp["e1"]["ch3"]["quotes"] == []

    def test_contract_valid(self):
        inp = build_book_report(SPINE, META)
        assert validate_input(inp) == []

    def test_empty_spine(self):
        inp = build_book_report([], META)
        assert inp["nodes"] == [] and inp["spines"] == {}
        assert validate_input(inp) == []


class TestDocRender(unittest.TestCase):
    def test_doc_layout_render(self):
        inp = build_book_report(SPINE, META)
        page = render_report(inp)
        for needle in ("章序流", "第1章", "第3章", "各章要点", "第一章原文证据一",
                       "鉴", "研判", "总览", "追问", "主线"):
            assert needle in page, f"缺 {needle!r}"
        # doc 模式不出现跨文本区块（CSS 注释里的字不算）
        assert '<section id="concepts">' not in page
        assert '<section id="disputes">' not in page
        assert "关系边" not in page
        assert "观点分歧" not in page

    def test_crossdoc_still_default(self):
        from tests.test_report_service import _min_input
        page = render_report(_min_input())
        assert "概念演变" in page
        assert "观点分歧" in page


if __name__ == "__main__":
    unittest.main()
