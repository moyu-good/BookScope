"""书鉴报告引擎（bookscope.report.service）单元测试。

覆盖：契约校验（必填/关系类型）、最小输入渲染冒烟、引文鉴印逻辑、HTML 转义。
纯本地，不调 LLM、不碰文件系统。
"""

import unittest

from bookscope.report.service import esc, render_report, validate_input


def _min_input() -> dict:
    return {
        "meta": {
            "title": "测试报告",
            "subtitle": "最小输入冒烟",
            "seal": "书 鉴",
            "nav_title": "测试导航",
            "unit_label": "篇",
            "generated_by": "单测",
        },
        "nodes": [
            {"slug": "a", "label": "论文A", "stance": "实证"},
            {"slug": "b", "label": "论文B", "stance": "理论"},
        ],
        "edges": [
            {"from": "a", "to": "b", "relation": "继承", "rationale": "B 发展了 A 的主张"},
        ],
        "concept_evolution": [
            {"concept": "财政激励", "stages": [
                {"stage": "提出", "claim": "财政分权给地方正确激励", "paper": "a", "evidence": "摘要"}]},
        ],
        "disagreements": [
            {"question": "分权是否是主因", "sides": [
                {"paper": "a", "stance": "是", "evidence": "实证"},
                {"paper": "b", "stance": "否", "evidence": "理论"}]},
        ],
        "narrative": "一段总体逻辑。",
        "spines": {
            "a": {
                "_title": "论文A", "_slug": "a",
                "core_thesis": "财政分权带来正确激励",
                "theoretical_stance": {"label": "财政联邦主义", "inference": False},
                "method": "实证",
                "key_citations": [{"quote": "fiscal incentives matter", "role": "核心论点"}],
            }
        },
        "e1": {"a": {"quotes": [{"quote": "fiscal incentives matter", "verified": True}]}},
        "quality": {"e2_mean": 4.5, "e3": {"correct": 1, "total": 1}},
        "ask": {"question": "谁继承谁", "answer": "B 继承 A", "sources": ["a", "b"]},
    }


class TestValidate(unittest.TestCase):
    def test_min_input_valid(self):
        assert validate_input(_min_input()) == []

    def test_missing_top_keys(self):
        errs = validate_input({})
        assert "缺 meta" in errs and "缺 nodes" in errs

    def test_missing_meta_fields(self):
        inp = _min_input()
        del inp["meta"]["seal"]
        errs = validate_input(inp)
        assert "meta 缺 seal" in errs

    def test_bad_relation_rejected(self):
        inp = _min_input()
        inp["edges"][0]["relation"] = "点赞"
        errs = validate_input(inp)
        assert any("关系类型" in e for e in errs)

    def test_node_missing_slug(self):
        inp = _min_input()
        del inp["nodes"][0]["slug"]
        errs = validate_input(inp)
        assert any("nodes[0]" in e for e in errs)


class TestRender(unittest.TestCase):
    def test_min_render_contains_core_sections(self):
        page = render_report(_min_input())
        for needle in ("测试报告", "书 鉴", "总览", "脉络关系", "概念演变", "观点分歧", "证据脊", "追问",
                       "继承", "fiscal incentives matter", "鉴", "E1 引文核验 1/1", "E2 4.5/5", "1/1"):
            assert needle in page, f"缺 {needle!r}"

    def test_ask_prerendered(self):
        page = render_report(_min_input())
        assert "B 继承 A" in page
        assert "来源: a, b" in page

    def test_unverified_quote_marks_judgement(self):
        inp = _min_input()
        inp["e1"]["a"]["quotes"][0]["verified"] = False
        page = render_report(inp)
        assert "研判" in page

    def test_escaping(self):
        inp = _min_input()
        inp["meta"]["title"] = '<script>alert(1)</script>'
        inp["spines"]["a"]["core_thesis"] = 'x"y'
        page = render_report(inp)
        assert "<script>alert" not in page
        assert "&lt;script&gt;" in page

    def test_empty_edges_ok(self):
        inp = _min_input()
        inp["edges"] = []
        page = render_report(inp)
        assert "0 关系" in page

    def test_esc_none(self):
        assert esc(None) == ""
        assert esc(0) == "0"


if __name__ == "__main__":
    unittest.main()
