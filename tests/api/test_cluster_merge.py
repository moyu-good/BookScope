"""簇关系聚合整理函数测试：边去重 + 概念/分歧按主题合并。"""

from __future__ import annotations

import bookscope.api.routes.agent as agent_routes


def test_dedupe_cluster_edges_keeps_first_rationale() -> None:
    edges = [
        {"from": "a", "to": "b", "relation": "继承", "rationale": "第一版"},
        {"from": "a", "to": "b", "relation": "继承", "rationale": "重复版"},
        {"from": "b", "to": "a", "relation": "反驳", "rationale": "反向"},
    ]
    out = agent_routes._dedupe_cluster_edges(edges)
    assert len(out) == 2
    assert out[0]["rationale"] == "第一版"


def test_merge_cluster_concepts_groups_by_name_and_ranks() -> None:
    items = [
        {"concept": "法治", "stages": [{"paper": "a", "stage": "提出"}]},
        {"concept": "法治", "stages": [{"paper": "b", "stage": "发展"}, {"paper": "a", "stage": "提出"}]},
        {"concept": "市场", "stages": [{"paper": "c", "stage": "落地"}]},
    ]
    out = agent_routes._merge_cluster_concepts(items)
    assert [x["concept"] for x in out] == ["法治", "市场"]
    assert len(out[0]["stages"]) == 2  # a/b 两本书，重复的 a-提出 只留一次


def test_merge_cluster_disputes_groups_by_question_and_ranks() -> None:
    items = [
        {"question": "政府角色", "sides": [{"paper": "a", "stance": "小政府"}]},
        {"question": "政府角色", "sides": [{"paper": "b", "stance": "大政府"}, {"paper": "a", "stance": "小政府"}]},
        {"question": "市场边界", "sides": [{"paper": "c", "stance": "放任"}]},
    ]
    out = agent_routes._merge_cluster_disputes(items)
    assert [x["question"] for x in out] == ["政府角色", "市场边界"]
    assert len(out[0]["sides"]) == 2
